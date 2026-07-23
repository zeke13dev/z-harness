#!/usr/bin/env python3
"""
axiom-store.py — CRUD + validation over the two-layer axiom store.

Subcommands:
  path      --scope <global|project> [--repo-root <p>]
  add       --scope <s> --from-json <path|->
  list      [--scope <s>] [--status <st>] [--discipline <d>] [--limit <n>]
  get       <id> [--scope <s>]
  validate  <id>|--all [--scope <s>]
  approve   <id> --scope <s> [--ack-observation]
  reject    <id> [--scope <s>] [--reason <t>]
  edit      <id> --set <field>=<value> ... [--scope <s>]

All output: JSON to stdout.  Diagnostics: stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Store path resolution (mirrors config.py conventions)
# ---------------------------------------------------------------------------

def _xdg_config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(xdg)


def _global_axioms_dir() -> Path:
    return _xdg_config_home() / "z-harness" / "axioms"


def _get_project_root(repo_root: str | None = None) -> str:
    """
    Return project root.

    Priority:
      1. explicit --repo-root argument
      2. Z_HARNESS_PROJECT_ROOT env var
      3. git rev-parse --show-toplevel
      4. Empty string (outside a git repo)
    """
    if repo_root:
        return repo_root
    project_root = os.environ.get("Z_HARNESS_PROJECT_ROOT", "")
    if project_root:
        return project_root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _project_axioms_dir(repo_root: str | None = None) -> Path | None:
    root = _get_project_root(repo_root)
    if not root:
        return None
    return Path(root) / ".z-harness" / "axioms"


def _resolve_axioms_dir(scope: str, repo_root: str | None = None) -> Path:
    """Resolve the axioms store directory for a given scope."""
    if scope == "global":
        return _global_axioms_dir()
    elif scope == "project":
        d = _project_axioms_dir(repo_root)
        if d is None:
            print("ERROR: cannot resolve project root for scope=project", file=sys.stderr)
            sys.exit(1)
        return d
    else:
        print(f"ERROR: unknown scope {scope!r}; must be global or project", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Atomic write helper (mirrors config.py tmp + os.replace pattern)
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON data to path atomically via tmp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        suffix=f".json.tmp.{os.getpid()}",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# ID derivation
# ---------------------------------------------------------------------------

def _derive_id(statement: str, scope: str) -> str:
    """Derive ax-<sha256(statement+scope)[:8]>."""
    digest = hashlib.sha256((statement + scope).encode("utf-8")).hexdigest()
    return f"ax-{digest[:8]}"


# ---------------------------------------------------------------------------
# Schema / validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ["id", "statement", "scope", "status", "confidence", "evidence",
                    "source_run", "created_at"]
_VALID_SCOPES = {"global", "project"}
_VALID_STATUSES = {"candidate", "approved", "rejected"}
_ID_PATTERN_PREFIX = "ax-"
_ID_HEX_LEN = 8

# Load schema from repo to extract required/optional field names (structural only)
def _load_schema() -> dict:
    schema_path = Path(__file__).resolve().parent.parent / "docs" / "schemas" / "axiom.schema.json"
    if schema_path.exists():
        with open(schema_path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


_SCHEMA = _load_schema()
_SCHEMA_PROPERTIES: set[str] = set(_SCHEMA.get("properties", {}).keys())


def _validate_record(record: dict) -> tuple[bool, list[str], list[str]]:
    """
    Validate a single axiom record against SPEC rules.

    Returns (ok, errors, warns).
    Warnings are non-blocking (e.g. observation_not_axiom).
    Graph-level checks (conflicts_with / supersedes referential integrity) are NOT performed here.
    """
    errors: list[str] = []
    warns: list[str] = []

    if not isinstance(record, dict):
        return False, ["record must be a JSON object"], []

    # --- Required fields present ---
    for field in _REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"missing required field: {field!r}")

    if errors:
        return False, errors, warns

    # --- id ---
    id_val = record.get("id", "")
    if not isinstance(id_val, str):
        errors.append("'id' must be a string")
    else:
        if not id_val.startswith(_ID_PATTERN_PREFIX):
            errors.append(f"'id' must start with 'ax-': got {id_val!r}")
        hex_part = id_val[len(_ID_PATTERN_PREFIX):]
        if len(hex_part) != _ID_HEX_LEN:
            errors.append(f"'id' hex part must be {_ID_HEX_LEN} characters: got {hex_part!r}")
        else:
            try:
                int(hex_part, 16)
            except ValueError:
                errors.append(f"'id' hex part must be lowercase hex: got {hex_part!r}")

    # --- statement ---
    statement = record.get("statement", "")
    if not isinstance(statement, str):
        errors.append("'statement' must be a string")
    else:
        if not statement.strip():
            errors.append("'statement' must be non-empty")
        if len(statement) > 200:
            errors.append(f"'statement' must be <=200 chars (got {len(statement)})")
        # Single sentence: ends before a period-space or multiple sentences heuristic
        # Heuristic: count sentence-ending punctuation mid-string
        stripped = statement.strip()
        # Check imperative: not a question, not starting with "the user"
        if stripped.endswith("?"):
            errors.append("'statement' must not be a question (imperative voice required)")
        if stripped.lower().startswith("the user"):
            errors.append("'statement' must use imperative voice, not 'the user…'")
        # Single sentence heuristic: no ". " followed by a capital letter mid-string.
        # Negative lookbehinds exclude common abbreviations: e.g., i.e., vs., etc., cf.
        sentence_break = re.search(r'(?<!e\.g)(?<!i\.e)(?<!vs)(?<!etc)(?<!cf)\.\s+[A-Z]', stripped)
        if sentence_break:
            errors.append("'statement' must be a single sentence (found sentence break)")

    # --- scope ---
    scope = record.get("scope")
    if scope not in _VALID_SCOPES:
        errors.append(f"'scope' must be one of {sorted(_VALID_SCOPES)}: got {scope!r}")

    # --- status ---
    status = record.get("status")
    if status not in _VALID_STATUSES:
        errors.append(f"'status' must be one of {sorted(_VALID_STATUSES)}: got {status!r}")

    # --- confidence ---
    confidence = record.get("confidence")
    if not isinstance(confidence, (int, float)):
        errors.append("'confidence' must be a number")
    elif not (0 <= confidence <= 1):
        errors.append(f"'confidence' must be in [0, 1]: got {confidence!r}")

    # --- evidence ---
    evidence = record.get("evidence")
    if not isinstance(evidence, list) or len(evidence) < 1:
        errors.append("'evidence' must be a non-empty array")
    else:
        for i, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                errors.append(f"evidence[{i}] must be an object")
                continue
            if "run" not in ev:
                errors.append(f"evidence[{i}] missing required field 'run'")
            if "event_id" not in ev and "quote" not in ev:
                errors.append(f"evidence[{i}] must have 'event_id' or 'quote'")

    # --- source_run ---
    if not isinstance(record.get("source_run"), str):
        errors.append("'source_run' must be a string")

    # --- created_at ---
    if not isinstance(record.get("created_at"), str):
        errors.append("'created_at' must be a string")

    # --- optional typed fields ---
    if "discipline" in record and not isinstance(record["discipline"], str):
        errors.append("'discipline' must be a string")

    if "applies_to" in record:
        at = record["applies_to"]
        if not isinstance(at, list) or len(at) < 1:
            errors.append("'applies_to' must be a non-empty array when present")
        else:
            seen_qids: set[str] = set()
            for i, entry in enumerate(at):
                if not isinstance(entry, str):
                    errors.append(f"'applies_to[{i}]' must be a string")
                    continue
                colon_count = entry.count(":")
                if colon_count != 1:
                    errors.append(
                        f"applies_to[{i}] must have exactly one ':' separator"
                        f" (got {colon_count}) — entries must be"
                        f" '<question_id>:<value>' (e.g. 'provider_for_task:gemini-cli'): got {entry!r}"
                    )
                    continue
                qid, value = entry.split(":", 1)
                if not qid:
                    errors.append(
                        f"'applies_to[{i}]' has empty <question_id> before ':': got {entry!r}"
                    )
                if not value:
                    errors.append(
                        f"'applies_to[{i}]' has empty <value> after ':': got {entry!r}"
                    )
                if qid and not re.match(r'^[a-z0-9_.]+$', qid):
                    errors.append(
                        f"'applies_to[{i}]' <question_id> {qid!r} does not match [a-z0-9_.]+"
                        " (lowercase alnum, underscore, and dot — matches config.py QUESTION_IDS"
                        " like workflow.slug_confirm)"
                    )
                if qid and qid in seen_qids:
                    errors.append(
                        f"'applies_to' contains duplicate <question_id> {qid!r}"
                        " — at most one entry per question_id is allowed"
                    )
                seen_qids.add(qid)

    if "boundary_conditions" in record:
        bc = record["boundary_conditions"]
        if not isinstance(bc, list) or not all(isinstance(x, str) for x in bc):
            errors.append("'boundary_conditions' must be an array of strings")

    if "counterexamples" in record:
        ce = record["counterexamples"]
        if not isinstance(ce, list) or not all(isinstance(x, str) for x in ce):
            errors.append("'counterexamples' must be an array of strings")

    if "conflicts_with" in record:
        cw = record["conflicts_with"]
        if not isinstance(cw, list):
            errors.append("'conflicts_with' must be an array")
        else:
            for x in cw:
                if not isinstance(x, str) or not re.match(r'^ax-[0-9a-f]{8}$', x):
                    errors.append(f"'conflicts_with' items must match ax-<8hex>: got {x!r}")

    if "supersedes" in record and record["supersedes"] is not None:
        sup = record["supersedes"]
        if not isinstance(sup, str) or not re.match(r'^ax-[0-9a-f]{8}$', sup):
            errors.append(f"'supersedes' must be ax-<8hex> or null: got {sup!r}")

    # --- Unknown fields (schema: additionalProperties: false) ---
    if _SCHEMA_PROPERTIES:
        unknown = set(record.keys()) - _SCHEMA_PROPERTIES
        for unk in sorted(unknown):
            errors.append(f"unknown field {unk!r} (not permitted by schema)")

    # --- Falsifiability advisory ---
    bc = record.get("boundary_conditions") or []
    ce = record.get("counterexamples") or []
    if not bc and not ce:
        warns.append("observation_not_axiom")

    ok = len(errors) == 0
    return ok, errors, warns


# ---------------------------------------------------------------------------
# Graph validation (R1 — single shared implementation)
# ---------------------------------------------------------------------------

def validate_graph(records: list[dict]) -> dict:
    """
    Validate referential integrity and graph invariants over a set of axiom records.

    This is THE single shared graph validator (R1): both ``approve`` and
    ``build-kernel.py`` call this function with identical load semantics.

    Checks:
      1. Every ``supersedes`` / ``conflicts_with`` target id exists in the
         record set → else error.
      2. No two ``approved`` records mutually conflict (A.conflicts_with B AND
         both approved) UNLESS one supersedes the other AND the superseded one
         is NOT approved (i.e. it is demoted) → else error.
      3. The ``supersedes`` graph is acyclic → else error (cycle caught).

    Args:
        records: list of axiom record dicts (any status mix).

    Returns:
        dict with keys ``ok`` (bool), ``errors`` (list[str]), ``warns`` (list[str]).
    """
    errors: list[str] = []
    warns: list[str] = []

    # Build lookup by id for existence checks
    all_ids: set[str] = {r.get("id") for r in records if r.get("id")}
    approved_ids: set[str] = {
        r.get("id") for r in records
        if r.get("id") and r.get("status") == "approved"
    }

    # Build supersedes map: who supersedes whom (id -> superseded_id)
    supersedes_map: dict[str, str] = {}
    # Reverse: superseded_id -> id of the record that supersedes it
    superseded_by: dict[str, str] = {}
    for rec in records:
        rid = rec.get("id")
        sup = rec.get("supersedes")
        if rid and sup and sup != "null":
            supersedes_map[rid] = sup
            superseded_by[sup] = rid

    # Check 1: referential integrity — supersedes + conflicts_with targets exist
    for rec in records:
        rid = rec.get("id", "<unknown>")
        sup = rec.get("supersedes")
        if sup and sup is not None and sup != "null":
            if sup not in all_ids:
                errors.append(
                    f"{rid}: supersedes target {sup!r} does not exist in the record set"
                )
        cw = rec.get("conflicts_with") or []
        for target in cw:
            if target not in all_ids:
                errors.append(
                    f"{rid}: conflicts_with target {target!r} does not exist in the record set"
                )

    # Check 2: mutual conflict between two approved records
    # A mutual conflict: A.conflicts_with includes B AND B.conflicts_with includes A
    # (symmetric declaration is not required by spec; a one-sided declaration is
    # enough to flag) — but spec says conflict is symmetric, so we check if
    # A ∈ approved AND B ∈ approved AND (A lists B OR B lists A).
    # The exemption: if A supersedes B (or B supersedes A) AND the superseded
    # one is demoted (not approved), the conflict is resolved.
    for rec in records:
        rid = rec.get("id")
        if not rid or rec.get("status") != "approved":
            continue
        cw = rec.get("conflicts_with") or []
        for target in cw:
            if target not in approved_ids:
                continue  # target is not approved → no mutual conflict
            if target == rid:
                continue  # self-reference, ignore
            # Both are approved and they conflict. Check exemption.
            # Exemption: one supersedes the other and the superseded one is demoted.
            # Since both are approved here, neither is demoted → no exemption.
            # (The demoted-exemption only applies when the superseded one is NOT approved.)
            # Check if A supersedes B
            a_supersedes_b = supersedes_map.get(rid) == target
            # Check if B supersedes A
            b_supersedes_a = supersedes_map.get(target) == rid
            if a_supersedes_b or b_supersedes_a:
                # One supersedes the other, but both are still approved.
                # The superseded one must be demoted (not approved) for exemption.
                # Here both are approved → not properly demoted → still an error.
                errors.append(
                    f"{rid}: mutual conflict with {target!r} — both are approved and "
                    f"one supersedes the other but the superseded record is not demoted"
                )
            else:
                errors.append(
                    f"{rid}: mutual conflict with {target!r} — both records are approved"
                )

    # Check 2b: approved A supersedes approved B — the superseded record must be demoted
    # (status != approved). If both A (approved, supersedes B) and B are still approved,
    # that is an invalid state (B must be rejected/demoted before or at approval of A).
    # Note: this check does NOT fire when B is rejected/demoted (B not in approved_ids)
    # or when A is not approved, so legal supersede paths are unaffected.
    for rec in records:
        rid = rec.get("id")
        if not rid or rec.get("status") != "approved":
            continue
        sup_target = rec.get("supersedes")
        if not sup_target or sup_target == "null":
            continue
        if sup_target in approved_ids:
            errors.append(
                f"{rid}: supersedes {sup_target!r} but the superseded record is still "
                f"approved (must be demoted to rejected)"
            )

    # Check 3: supersedes graph is acyclic (detect cycles via DFS)
    def _has_cycle() -> list[str]:
        visited: set[str] = set()
        in_stack: set[str] = set()
        cycle_found: list[str] = []

        def _dfs(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            successor = supersedes_map.get(node)
            if successor:
                if successor in in_stack:
                    cycle_found.append(
                        f"supersedes cycle detected involving {node!r} -> {successor!r}"
                    )
                    return True
                if successor not in visited:
                    if _dfs(successor):
                        return True
            in_stack.discard(node)
            return False

        for node in list(supersedes_map.keys()):
            if node not in visited:
                _dfs(node)

        return cycle_found

    cycle_errors = _has_cycle()
    errors.extend(cycle_errors)

    return {"ok": len(errors) == 0, "errors": errors, "warns": warns}


# ---------------------------------------------------------------------------
# Active-set loading helper (shared between cmd_validate --all and cmd_reject/edit)
# ---------------------------------------------------------------------------

def _load_active_set(scope: str | None, repo_root: str | None) -> list[dict]:
    """
    Load the merged active set (global+project, approved+candidate records),
    project shadowing global on same id — matching how ``list`` builds its set.

    Scope semantics (R1 — must match build-kernel.py load semantics exactly):
      scope=None    → global THEN project (project shadows global by id)
      scope="global" → global only
      scope="project" → global FIRST, then project (project shadows global by id).
                        Project scope is a SUPERSET of global: the merged set is
                        required so approve/validate see cross-store conflicts.

    This is the standard load semantics used by both validate --all and approve.
    """
    records_by_id: dict[str, dict] = {}

    def _load_from(store_dir: Path) -> None:
        for subdir in ("candidates", "approved", "rejected"):
            d = store_dir / subdir
            if not d.exists():
                continue
            for p in sorted(d.glob("*.json")):
                try:
                    with open(p, encoding="utf-8") as fh:
                        rec = json.load(fh)
                    rid = rec.get("id")
                    if rid:
                        records_by_id[rid] = rec
                except (json.JSONDecodeError, OSError) as exc:
                    print(f"WARN: skipping {p}: {exc}", file=sys.stderr)

    # Load global store for: scope=None, scope="global", scope="project".
    # Project scope needs global loaded first so project records shadow global
    # records with the same id (last-write-wins into records_by_id).
    if scope is None or scope in ("global", "project"):
        _load_from(_global_axioms_dir())

    # Load project store for: scope=None, scope="project".
    # Loaded AFTER global so project records take precedence on id collision.
    if scope is None or scope == "project":
        proj = _project_axioms_dir(repo_root)
        if proj is not None:
            _load_from(proj)

    return list(records_by_id.values())


# ---------------------------------------------------------------------------
# Store scanning helpers
# ---------------------------------------------------------------------------

def _iter_records(store_dir: Path) -> list[tuple[str, Path, dict]]:
    """
    Yield (subdir_name, file_path, record_dict) for every .json file in
    candidates/, approved/, rejected/ under store_dir.
    """
    results = []
    for subdir in ("candidates", "approved", "rejected"):
        d = store_dir / subdir
        if not d.exists():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                with open(p, encoding="utf-8") as fh:
                    rec = json.load(fh)
                results.append((subdir, p, rec))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"WARN: skipping {p}: {exc}", file=sys.stderr)
    return results


def _id_exists_in_store(store_dir: Path, axiom_id: str) -> bool:
    """Return True if axiom_id exists in any subdir of store_dir."""
    for subdir in ("candidates", "approved", "rejected"):
        p = store_dir / subdir / f"{axiom_id}.json"
        if p.exists():
            return True
    return False


def _find_record(store_dir: Path, axiom_id: str) -> dict | None:
    """Find a record by id in any subdir, project shadows global."""
    for subdir in ("candidates", "approved", "rejected"):
        p = store_dir / subdir / f"{axiom_id}.json"
        if p.exists():
            try:
                with open(p, encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
    return None


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_path(args: argparse.Namespace) -> None:
    """Print resolved axioms dir for the given scope."""
    d = _resolve_axioms_dir(args.scope, getattr(args, "repo_root", None))
    print(json.dumps({"path": str(d)}))


def cmd_add(args: argparse.Namespace) -> None:
    """Validate and write a candidate record to the store."""
    # Read input
    if args.from_json == "-":
        try:
            raw = sys.stdin.read()
        except OSError as exc:
            print(f"ERROR: reading stdin: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            with open(args.from_json, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            print(f"ERROR: reading {args.from_json}: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    # Assign id if absent
    if "id" not in record:
        statement = record.get("statement", "")
        scope = args.scope
        record["id"] = _derive_id(statement, scope)

    # Force scope to match the --scope argument
    record["scope"] = args.scope

    # Validate
    ok, errors, warns = _validate_record(record)
    if not ok:
        print(json.dumps({"status": "invalid", "errors": errors}))
        sys.exit(1)

    for w in warns:
        print(f"WARN: {w}", file=sys.stderr)

    store_dir = _resolve_axioms_dir(args.scope, getattr(args, "repo_root", None))
    axiom_id = record["id"]

    # Duplicate check across all subdirs
    if _id_exists_in_store(store_dir, axiom_id):
        print(json.dumps({"status": "duplicate", "id": axiom_id}))
        sys.exit(0)

    # Write to candidates/
    out_path = store_dir / "candidates" / f"{axiom_id}.json"
    _atomic_write(out_path, record)

    print(json.dumps({"status": "ok", "id": axiom_id, "path": str(out_path)}))


def cmd_list(args: argparse.Namespace) -> None:
    """Emit JSON array of matching records."""
    scope = getattr(args, "scope", None)
    status_filter = getattr(args, "status", None)
    discipline_filter = getattr(args, "discipline", None)
    limit = getattr(args, "limit", None)
    repo_root = getattr(args, "repo_root", None)

    # Gather records
    # When scope is None, merge global+project (project shadows global on same id)
    records_by_id: dict[str, dict] = {}

    def _load_from(store_dir: Path) -> None:
        for _subdir, _path, rec in _iter_records(store_dir):
            rid = rec.get("id")
            if rid:
                records_by_id[rid] = rec  # later insertion shadows earlier

    if scope is None or scope == "global":
        _load_from(_global_axioms_dir())

    if scope is None or scope == "project":
        proj = _project_axioms_dir(repo_root)
        if proj is not None:
            _load_from(proj)
    # project records loaded second → shadow global on same id

    result = list(records_by_id.values())

    # Apply filters
    if status_filter:
        result = [r for r in result if r.get("status") == status_filter]
    if discipline_filter:
        result = [r for r in result if r.get("discipline") == discipline_filter]
    if limit is not None:
        result = result[:limit]

    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_get(args: argparse.Namespace) -> None:
    """Retrieve one record by id."""
    axiom_id = args.id
    scope = getattr(args, "scope", None)
    repo_root = getattr(args, "repo_root", None)

    record: dict | None = None

    if scope == "global" or scope is None:
        record = _find_record(_global_axioms_dir(), axiom_id)

    if record is None and (scope == "project" or scope is None):
        proj = _project_axioms_dir(repo_root)
        if proj is not None:
            record = _find_record(proj, axiom_id)

    if record is None:
        print(json.dumps({"status": "not_found", "id": axiom_id}))
        sys.exit(1)

    print(json.dumps(record, indent=2, ensure_ascii=False))


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate a single record (--from-json) or the full active set (--all)."""
    validate_all = getattr(args, "all", False)
    from_json = getattr(args, "from_json", None)
    axiom_id = getattr(args, "id", None)
    scope = getattr(args, "scope", None)
    repo_root = getattr(args, "repo_root", None)

    if validate_all:
        # Graph-validate the active merged set
        records = _load_active_set(scope, repo_root)
        result = validate_graph(records)
        print(json.dumps(result))
        if not result["ok"]:
            sys.exit(1)
        return

    if from_json:
        # Single-record validation from file/stdin (backward-compat)
        if from_json == "-":
            try:
                raw = sys.stdin.read()
            except OSError as exc:
                print(f"ERROR: reading stdin: {exc}", file=sys.stderr)
                sys.exit(1)
        else:
            try:
                with open(from_json, encoding="utf-8") as fh:
                    raw = fh.read()
            except OSError as exc:
                print(f"ERROR: reading {from_json}: {exc}", file=sys.stderr)
                sys.exit(1)

        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "errors": [f"invalid JSON: {exc}"], "warns": []}))
            sys.exit(1)

        ok, errors, warns = _validate_record(record)

        for w in warns:
            print(f"WARN: {w}", file=sys.stderr)

        print(json.dumps({"ok": ok, "errors": errors, "warns": warns}))
        if not ok:
            sys.exit(1)
        return

    if axiom_id:
        # Single-record validation by id from the store
        record: dict | None = None
        if scope == "global" or scope is None:
            record = _find_record(_global_axioms_dir(), axiom_id)
        if record is None and (scope == "project" or scope is None):
            proj = _project_axioms_dir(repo_root)
            if proj is not None:
                record = _find_record(proj, axiom_id)

        if record is None:
            print(json.dumps({"ok": False, "errors": [f"not_found: {axiom_id}"], "warns": []}))
            sys.exit(1)

        ok, errors, warns = _validate_record(record)
        for w in warns:
            print(f"WARN: {w}", file=sys.stderr)
        print(json.dumps({"ok": ok, "errors": errors, "warns": warns}))
        if not ok:
            sys.exit(1)
        return

    print("ERROR: validate requires --all, --from-json, or an axiom id", file=sys.stderr)
    sys.exit(2)


def _move_to_rejected(store_dir: Path, src_path: Path, axiom_id: str,
                      *, reason: str | None = None,
                      superseded_by: str | None = None) -> Path:
    """
    Move the record at ``src_path`` into ``<store_dir>/rejected/<id>.json``,
    stamping ``status: rejected`` and optional ``rejected_reason`` /
    ``superseded_by`` fields. Atomic write then unlink the source.

    This is the shared demotion primitive used by both ``reject`` and
    ``approve`` (supersede demotion). Returns the destination path.
    """
    with open(src_path, encoding="utf-8") as fh:
        record = json.load(fh)

    record["status"] = "rejected"
    if reason:
        record["rejected_reason"] = reason
    if superseded_by:
        record["superseded_by"] = superseded_by

    dst_path = store_dir / "rejected" / f"{axiom_id}.json"
    _atomic_write(dst_path, record)

    # Remove the source file after atomic write succeeds (no-op if same path)
    if src_path != dst_path:
        try:
            src_path.unlink()
        except OSError as exc:
            print(f"WARN: could not remove source file {src_path}: {exc}", file=sys.stderr)

    return dst_path


def cmd_reject(args: argparse.Namespace) -> None:
    """Move a candidate or approved record to rejected/, stamping status: rejected."""
    axiom_id = args.id
    scope = getattr(args, "scope", None)
    repo_root = getattr(args, "repo_root", None)
    reason = getattr(args, "reason", None)

    # Resolve the store dir where the record lives
    store_dir: Path | None = None
    src_path: Path | None = None

    def _find_in_store(sd: Path) -> Path | None:
        for subdir in ("candidates", "approved"):
            p = sd / subdir / f"{axiom_id}.json"
            if p.exists():
                return p
        return None

    resolved_scope: str | None = None  # which store the record was actually found in

    if scope == "global" or scope is None:
        sd = _global_axioms_dir()
        found = _find_in_store(sd)
        if found:
            store_dir = sd
            src_path = found
            resolved_scope = "global"

    if src_path is None and (scope == "project" or scope is None):
        proj = _project_axioms_dir(repo_root)
        if proj is not None:
            found = _find_in_store(proj)
            if found:
                store_dir = proj
                src_path = found
                resolved_scope = "project"

    if src_path is None or store_dir is None:
        print(json.dumps({"status": "not_found", "id": axiom_id}))
        sys.exit(1)

    # Capture whether the record was approved before demotion (regen needed if so).
    was_approved = src_path.parent.name == "approved"

    try:
        dst_path = _move_to_rejected(store_dir, src_path, axiom_id, reason=reason)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: reading {src_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    # Kernel regen: only when the rejected record was previously approved (R3).
    # Use resolved_scope (the store where the mutation landed), not scope or "global",
    # so the correct kernel is regenerated when --scope is omitted.
    if was_approved:
        invoked, regen_ok = _regen_kernel(resolved_scope or "global", repo_root)
        if invoked and not regen_ok:
            # Log the stale-kernel event.
            log_event = Path(__file__).resolve().parent / "log-event.sh"
            if log_event.exists():
                payload = json.dumps({"id": axiom_id, "scope": resolved_scope or "global"})
                subprocess.run(
                    ["bash", str(log_event), "axiom-reject", "kernel_regen_failed", payload],
                    capture_output=True, text=True,
                )
            print(json.dumps({
                "status": "rejected_kernel_stale",
                "id": axiom_id,
                "path": str(dst_path),
            }))
            sys.exit(1)

    print(json.dumps({"status": "ok", "id": axiom_id, "path": str(dst_path)}))


def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 with Z suffix."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _regen_kernel(scope: str, repo_root: str | None) -> tuple[bool, bool]:
    """
    Guarded kernel regeneration (Phase 1: T007 does the full synchronous wiring).

    If scripts/build-kernel.py exists, invoke ``build-kernel.py --scope <s>``.
    Returns (invoked, ok):
      - invoked=False, ok=True  → compiler absent, skip note logged (no crash).
      - invoked=True,  ok=True  → regen succeeded.
      - invoked=True,  ok=False → regen failed (caller emits kernel_regen_failed).
    """
    build_kernel = Path(__file__).resolve().parent / "build-kernel.py"
    if not build_kernel.exists():
        print(
            f"NOTE: {build_kernel} not present; skipping kernel regen "
            f"(full wiring lands in T007)",
            file=sys.stderr,
        )
        return False, True

    cmd = [sys.executable, str(build_kernel), "--scope", scope]
    if repo_root:
        cmd += ["--repo-root", repo_root]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(
            f"ERROR: build-kernel.py failed (exit {proc.returncode}): {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return True, False
    return True, True


def cmd_approve(args: argparse.Namespace) -> None:
    """
    Atomic promotion of a candidate to approved (SPEC approve algorithm + R4 lock).

    1. Load candidates/<id>.json in the resolved scope → not_found if absent.
    2. Schema-validate → invalid on failure.
    3. needs_ack gate: observation_not_axiom warn AND no --ack-observation → needs_ack.
    [Under O_EXCL lock — wraps steps 4-7 per R4]
    4. Build prospective set via _load_active_set (merged global+project, R1 semantics),
       applying post-approval transforms (exclude this id, demote supersedes target).
    5. validate_graph(prospective) → graph_invalid on failure (candidate untouched, lock released).
    6. Demote supersedes target → rejected/, write approved/<id>.json, remove candidate file.
    7. Guarded kernel regen → approved_kernel_stale on regen failure.
    """
    axiom_id = args.id
    scope = args.scope
    ack_observation = getattr(args, "ack_observation", False)
    repo_root = getattr(args, "repo_root", None)

    store_dir = _resolve_axioms_dir(scope, repo_root)
    candidate_path = store_dir / "candidates" / f"{axiom_id}.json"

    # Step 1: load candidate
    if not candidate_path.exists():
        print(json.dumps({"status": "not_found", "id": axiom_id}))
        sys.exit(1)

    try:
        with open(candidate_path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: reading {candidate_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    # Step 2: schema validation
    ok, errors, warns = _validate_record(record)
    if not ok:
        print(json.dumps({"status": "invalid", "id": axiom_id, "errors": errors}))
        sys.exit(1)

    # Step 3: needs_ack gate (falsifiability advisory)
    if "observation_not_axiom" in warns and not ack_observation:
        print(json.dumps({
            "status": "needs_ack",
            "id": axiom_id,
            "warns": warns,
        }))
        sys.exit(1)

    # Step 4: prepare stamped record; build prospective set under lock (R4).
    approved_record = dict(record)
    approved_record["status"] = "approved"
    approved_record["approved_at"] = _utc_now_iso()

    supersedes_target = record.get("supersedes")
    if supersedes_target == "null":
        supersedes_target = None

    approved_dir = store_dir / "approved"

    # Step 4b / Step 6/7: acquire O_EXCL lock BEFORE reading the active set and
    # running validate_graph (R4 — lock must wrap the whole validate→move→regen
    # sequence so two concurrent approves cannot both validate against a stale set
    # and then serialize mutations into a graph-invalid combined state).
    lock_path = store_dir / ".approve.lock"
    store_dir.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # Lock already held → exit busy without doing anything (R4).
        print(json.dumps({"status": "busy", "id": axiom_id}))
        sys.exit(1)

    try:
        os.write(lock_fd, f"{os.getpid()}\n".encode())

        # Step 5 (inside lock): build prospective set using the SAME merged-load
        # semantics as build-kernel.py (_load_active_set: global+project, project
        # shadows global on same id) — R1 requires identical semantics so a
        # project-scope approve cannot pass validation while conflicting with a
        # global approved record.
        #
        # Post-approval transforms applied to the loaded set:
        #   • Exclude the record being approved (it's replaced by approved_record).
        #   • Stamp the supersedes_target status:rejected in the prospective set
        #     (demotion modeling; record kept present for referential-integrity check 1).
        #   • All other records stay at their stored status.
        #   • Append approved_record (status: approved).
        active = _load_active_set(scope, repo_root)
        prospective: list[dict] = []
        for r in active:
            rid = r.get("id")
            if rid == axiom_id:
                continue  # replaced by approved_record
            if supersedes_target and rid == supersedes_target:
                demoted = dict(r)
                demoted["status"] = "rejected"
                prospective.append(demoted)
                continue
            prospective.append(r)
        prospective.append(approved_record)

        # Graph validation on the prospective set (still inside the lock).
        graph_result = validate_graph(prospective)
        if not graph_result["ok"]:
            # Abort: candidate left in place, nothing moved.
            print(json.dumps({
                "status": "graph_invalid",
                "id": axiom_id,
                "errors": graph_result["errors"],
            }))
            sys.exit(1)

        # Cross-store supersede guard (v1 policy — intentionally unsupported).
        # SPEC does not define cross-store demotion semantics; the mining flow
        # only ever produces same-scope candidates with supersedes:null.  A
        # hand-authored supersedes pointing at a record in the OTHER store would
        # leave that record approved in its own store while A is also approved,
        # producing a silent inconsistent state.  Forbid it explicitly.
        if supersedes_target:
            target_in_approve_store = _id_exists_in_store(store_dir, supersedes_target)
            if not target_in_approve_store:
                # Check if target lives in the other store (global vs project).
                other_store: Path | None = None
                if scope == "project":
                    other_store = _global_axioms_dir()
                elif scope == "global":
                    proj = _project_axioms_dir(repo_root)
                    if proj is not None:
                        other_store = proj
                if other_store is not None and _id_exists_in_store(other_store, supersedes_target):
                    # Target exists only in a different store — cross-store supersede
                    # is unsupported in v1; abort before writing anything.
                    target_scope = "global" if scope == "project" else "project"
                    print(json.dumps({
                        "status": "cross_store_supersede_unsupported",
                        "id": axiom_id,
                        "supersedes": supersedes_target,
                        "target_scope": target_scope,
                    }))
                    sys.exit(1)

        # Demote any supersedes target to rejected/ (reuse shared move helper).
        if supersedes_target:
            target_path = approved_dir / f"{supersedes_target}.json"
            if not target_path.exists():
                # also accept a candidate-stage target
                cand_target = store_dir / "candidates" / f"{supersedes_target}.json"
                if cand_target.exists():
                    target_path = cand_target
            if target_path.exists():
                _move_to_rejected(
                    store_dir, target_path, supersedes_target,
                    superseded_by=axiom_id,
                )

        # Write the approved record atomically, then remove the candidate.
        approved_path = approved_dir / f"{axiom_id}.json"
        _atomic_write(approved_path, approved_record)
        try:
            candidate_path.unlink()
        except OSError as exc:
            print(f"WARN: could not remove candidate {candidate_path}: {exc}",
                  file=sys.stderr)

        # Guarded kernel regen.
        invoked, regen_ok = _regen_kernel(scope, repo_root)
        if invoked and not regen_ok:
            run_id = record.get("source_run", "axiom-approve")
            log_event = Path(__file__).resolve().parent / "log-event.sh"
            if log_event.exists():
                payload = json.dumps({"id": axiom_id, "scope": scope})
                subprocess.run(
                    ["bash", str(log_event), str(run_id), "kernel_regen_failed", payload],
                    capture_output=True, text=True,
                )
            print(json.dumps({
                "status": "approved_kernel_stale",
                "id": axiom_id,
                "path": str(approved_path),
            }))
            sys.exit(1)

        print(json.dumps({
            "status": "approved",
            "id": axiom_id,
            "path": str(approved_path),
        }))
    finally:
        try:
            os.close(lock_fd)
        except OSError:
            pass
        try:
            lock_path.unlink()
        except OSError:
            pass


def cmd_edit(args: argparse.Namespace) -> None:
    """Patch a candidate or approved record atomically via --set k=v."""
    axiom_id = args.id
    scope = getattr(args, "scope", None)
    repo_root = getattr(args, "repo_root", None)
    set_pairs: list[str] = args.set  # list of "k=v" strings

    # Parse --set k=v pairs
    patches: dict[str, object] = {}
    for pair in set_pairs:
        if "=" not in pair:
            print(f"ERROR: --set value must be k=v: got {pair!r}", file=sys.stderr)
            sys.exit(2)
        k, v = pair.split("=", 1)
        k = k.strip()
        # Attempt JSON parse of the value; fall back to string
        try:
            patches[k] = json.loads(v)
        except json.JSONDecodeError:
            patches[k] = v

    # Locate the record file
    store_dir: Path | None = None
    src_path: Path | None = None
    resolved_scope: str | None = None  # which store the record was actually found in

    def _find_in_store_all(sd: Path) -> Path | None:
        for subdir in ("candidates", "approved", "rejected"):
            p = sd / subdir / f"{axiom_id}.json"
            if p.exists():
                return p
        return None

    if scope == "global" or scope is None:
        sd = _global_axioms_dir()
        found = _find_in_store_all(sd)
        if found:
            store_dir = sd
            src_path = found
            resolved_scope = "global"

    if src_path is None and (scope == "project" or scope is None):
        proj = _project_axioms_dir(repo_root)
        if proj is not None:
            found = _find_in_store_all(proj)
            if found:
                store_dir = proj
                src_path = found
                resolved_scope = "project"

    if src_path is None or store_dir is None:
        print(json.dumps({"status": "not_found", "id": axiom_id}))
        sys.exit(1)

    # Load, patch
    try:
        with open(src_path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: reading {src_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    original_record = dict(record)
    record.update(patches)

    # Schema validation — applies to ALL records (candidate and approved) before any write.
    # Catches unknown fields and type violations introduced via --set.
    schema_ok, schema_errors, _schema_warns = _validate_record(record)
    if not schema_ok:
        print(json.dumps({
            "status": "invalid",
            "id": axiom_id,
            "errors": schema_errors,
        }))
        sys.exit(1)

    # If the record is approved (original or patched), validate graph after patch
    was_approved = original_record.get("status") == "approved"
    is_approved_after = record.get("status") == "approved"

    if was_approved or is_approved_after:
        # Build a prospective active set: load all records, replace this one with patched
        active = _load_active_set(scope, repo_root)
        patched_set = []
        for r in active:
            if r.get("id") == axiom_id:
                patched_set.append(record)
            else:
                patched_set.append(r)
        # If record wasn't in active set (shouldn't happen), append it
        if not any(r.get("id") == axiom_id for r in active):
            patched_set.append(record)

        graph_result = validate_graph(patched_set)
        if not graph_result["ok"]:
            print(json.dumps({
                "status": "graph_validation_failed",
                "id": axiom_id,
                "errors": graph_result["errors"],
            }))
            sys.exit(1)

    # Atomic write back to the same file location
    _atomic_write(src_path, record)

    # Kernel regen: only when the original or patched record is approved (an approved
    # record edit changes kernel content; a candidate-only edit does not).
    # Use resolved_scope (the store where the mutation landed), not scope or "global",
    # so the correct kernel is regenerated when --scope is omitted.
    if was_approved or is_approved_after:
        invoked, regen_ok = _regen_kernel(resolved_scope or "global", repo_root)
        if invoked and not regen_ok:
            log_event = Path(__file__).resolve().parent / "log-event.sh"
            if log_event.exists():
                payload = json.dumps({"id": axiom_id, "scope": resolved_scope or "global"})
                subprocess.run(
                    ["bash", str(log_event), "axiom-edit", "kernel_regen_failed", payload],
                    capture_output=True, text=True,
                )
            print(json.dumps({
                "status": "edited_kernel_stale",
                "id": axiom_id,
                "path": str(src_path),
            }))
            sys.exit(1)

    print(json.dumps({"status": "ok", "id": axiom_id, "path": str(src_path)}))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="axiom-store.py",
        description="CRUD + validation for the z-harness axiom store.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # path
    p_path = sub.add_parser("path", help="Resolve axioms dir for a scope")
    p_path.add_argument("--scope", required=True, choices=["global", "project"])
    p_path.add_argument("--repo-root", dest="repo_root", default=None)

    # add
    p_add = sub.add_parser("add", help="Add a candidate axiom record")
    p_add.add_argument("--scope", required=True, choices=["global", "project"])
    p_add.add_argument("--from-json", required=True, dest="from_json",
                       help="Path to JSON file, or - for stdin")
    p_add.add_argument("--repo-root", dest="repo_root", default=None)

    # list
    p_list = sub.add_parser("list", help="List axiom records")
    p_list.add_argument("--scope", choices=["global", "project"], default=None)
    p_list.add_argument("--status", choices=["candidate", "approved", "rejected"], default=None)
    p_list.add_argument("--discipline", default=None)
    p_list.add_argument("--limit", type=_positive_int, default=None,
                        help="Limit the number of records printed")
    p_list.add_argument("--repo-root", dest="repo_root", default=None)

    # get
    p_get = sub.add_parser("get", help="Get a single axiom record by id")
    p_get.add_argument("id", help="Axiom id (e.g. ax-1a2b3c4d)")
    p_get.add_argument("--scope", choices=["global", "project"], default=None)
    p_get.add_argument("--repo-root", dest="repo_root", default=None)

    # validate
    p_val = sub.add_parser("validate", help="Validate a single record or the whole graph")
    p_val.add_argument("id", nargs="?", default=None,
                       help="Axiom id to validate (single-record); omit when using --all or --from-json")
    p_val.add_argument("--all", action="store_true", default=False,
                       help="Graph-validate the entire active set")
    p_val.add_argument("--from-json", dest="from_json", default=None,
                       help="Validate a single record from a JSON file or - for stdin")
    p_val.add_argument("--scope", choices=["global", "project"], default=None)
    p_val.add_argument("--repo-root", dest="repo_root", default=None)

    # approve
    p_app = sub.add_parser("approve", help="Atomically promote a candidate to approved")
    p_app.add_argument("id", help="Axiom id to approve")
    p_app.add_argument("--scope", required=True, choices=["global", "project"])
    p_app.add_argument("--ack-observation", dest="ack_observation",
                       action="store_true", default=False,
                       help="Acknowledge an observation-like axiom (no boundary/counterexamples)")
    p_app.add_argument("--repo-root", dest="repo_root", default=None)

    # reject
    p_rej = sub.add_parser("reject", help="Reject a candidate or approved axiom")
    p_rej.add_argument("id", help="Axiom id to reject")
    p_rej.add_argument("--scope", choices=["global", "project"], default=None)
    p_rej.add_argument("--reason", default=None, help="Optional rejection reason")
    p_rej.add_argument("--repo-root", dest="repo_root", default=None)

    # edit
    p_edit = sub.add_parser("edit", help="Patch a candidate or approved axiom record")
    p_edit.add_argument("id", help="Axiom id to edit")
    p_edit.add_argument("--set", dest="set", metavar="k=v", action="append",
                        required=True, help="Field=value patch; repeatable")
    p_edit.add_argument("--scope", choices=["global", "project"], default=None)
    p_edit.add_argument("--repo-root", dest="repo_root", default=None)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "path":
        cmd_path(args)
    elif args.subcommand == "add":
        cmd_add(args)
    elif args.subcommand == "list":
        cmd_list(args)
    elif args.subcommand == "get":
        cmd_get(args)
    elif args.subcommand == "validate":
        cmd_validate(args)
    elif args.subcommand == "approve":
        cmd_approve(args)
    elif args.subcommand == "reject":
        cmd_reject(args)
    elif args.subcommand == "edit":
        cmd_edit(args)
    else:
        parser.print_help(sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
