#!/usr/bin/env python3
"""
config.py — z-harness layered TOML config loader.

Subcommands:
  get <dotted.key>                        Resolve a single key and print its value.
  export-env                              Print export lines for all non-meta keys.
  ensure-defaults                         Write global config with defaults if absent.
  explain <dotted.key>                    Print value + source layer.
  should-notify --event <kind>            Print yes/no notification gate.
  list-question-ids                       Print sorted JSON array of registered question IDs.
  resolve-question <question_id>          Return JSON resolver envelope for a question ID.
  check-no-ask --question-id <id>        Return JSON halt/proceed for overnight gate checks.

Layer order (lowest → highest priority):
  1. Built-in defaults (DEFAULTS)
  2. $XDG_CONFIG_HOME/z-harness/config.toml  (global user)
  3. Repo-local: $Z_HARNESS_REPO_CONFIG or <git-toplevel>/.z-harness/config.toml
  4. Env vars: Z_HARNESS_<SECTION>_<KEY> (empty = missing)

Exit codes:
  0  Success
  2  Schema / validation error
  3  Unknown dotted-key
  4  I/O error (ensure-defaults edge cases, permission denied)
  5  Config conflict (Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt both set)
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DEFAULTS: dict = {
    "schema_version": 1,
    "notify": {
        "level": "approval_only",   # off | approval_only | all
    },
    "docs": {
        "always_apply": "always",   # always | never
    },
    "workflow": {
        "audit_to_amend": "ask",          # ask | amend | stop
        "slug_confirm":   "ask",          # ask | auto_accept | recommend_derived
        "implement_all_proceed": "ask",   # ask | auto_resume | halt
        "review_all_proceed":    "ask",   # ask | proceed | halt
        "plan_decisions_approval": "ask", # ask | approve | halt
    },
}

VALIDATORS: dict = {
    "notify.level": {"off", "approval_only", "all"},
    "docs.always_apply": {"always", "never"},
    "workflow.audit_to_amend": {"ask", "amend", "stop"},
    "workflow.slug_confirm":   {"ask", "auto_accept", "recommend_derived"},
    "workflow.implement_all_proceed":    {"ask", "auto_resume", "halt"},
    "workflow.review_all_proceed":       {"ask", "proceed", "halt"},
    "workflow.plan_decisions_approval":  {"ask", "approve", "halt"},
}

META_KEYS: set = {"schema_version"}

# ---------------------------------------------------------------------------
# Question registry (single source of truth for resolver and /z-suggest-memory)
# ---------------------------------------------------------------------------

QUESTION_IDS: dict[str, dict] = {
    "workflow.audit_to_amend": {
        "config_key": "workflow.audit_to_amend",
        "choices": {"ask", "amend", "stop"},
        "skill_default": "amend",
        "callsites": [
            "commands/z-audit-plan.md:183",
            "commands/z-audit-plan-style.md:384",
        ],
    },
    "workflow.slug_confirm": {
        "config_key": "workflow.slug_confirm",
        # `auto_accept` means "always accept derived slug without asking" (resolves to result: skip).
        # `recommend_derived` means "show AskUser with derived slug pre-selected" (resolves to result: prefill).
        # `ask` means "always ask" (resolves to result: ask).
        "choices": {"ask", "auto_accept", "recommend_derived"},
        "skill_default": "yes_keep_derived",
        "callsites": [
            "commands/z-plan.md:21",
            "commands/z-fix.md:18",
            "skills/z-debug/SKILL.md:17",
            "skills/z-brainstorm/SKILL.md:19",
            "skills/z-map/SKILL.md:133",
            "skills/z-plan-light/SKILL.md:19",
            "commands/z-uplift.md:71",
        ],
        # Hard prerequisite: even when resolver returns skip, the slug-COLLISION check runs
        # unconditionally. The resolver only governs the soft non-obvious-slug confirmation.
        "safety_check_runs_unconditionally": True,
    },
    "workflow.implement_all_proceed": {
        "config_key": "workflow.implement_all_proceed",
        "choices": {"ask", "auto_resume", "halt"},
        "skill_default": "ask",
        "callsites": [
            "commands/z-implement-all.md (halt-resolution gate)",
        ],
    },
    "workflow.review_all_proceed": {
        "config_key": "workflow.review_all_proceed",
        "choices": {"ask", "proceed", "halt"},
        "skill_default": "proceed",
        "callsites": [
            "commands/z-review-all.md (Phase 3.7 proceed gate)",
        ],
    },
    "workflow.plan_decisions_approval": {
        "config_key": "workflow.plan_decisions_approval",
        "choices": {"ask", "approve", "halt"},
        "skill_default": "approve",
        "callsites": [
            "commands/z-plan.md (Phase 2.5 decisions-doc approval gate)",
        ],
    },
}

# Default overnight auto-decide allowlist: question_ids that /z-overnight
# handles autonomously without halting, mapped to the chosen option-domain value.
OVERNIGHT_AUTODECIDE_QIDS_DEFAULT: dict[str, str] = {
    "workflow.slug_confirm": "recommend_derived",
    "workflow.audit_to_amend": "amend",
}

# Map each question_id's option-domain value → resolver result-domain
RESULT_MAP: dict[tuple[str, str], str] = {
    ("workflow.audit_to_amend", "ask"):             "ask",
    ("workflow.audit_to_amend", "amend"):           "skip",  # user wants auto-amend → skip the prompt
    ("workflow.audit_to_amend", "stop"):            "skip",  # user wants auto-stop → also skip the prompt
    ("workflow.slug_confirm",   "ask"):             "ask",
    ("workflow.slug_confirm",   "auto_accept"):     "skip",
    ("workflow.slug_confirm",   "recommend_derived"): "prefill",
    ("workflow.implement_all_proceed", "ask"):       "ask",
    ("workflow.implement_all_proceed", "auto_resume"): "skip",
    ("workflow.implement_all_proceed", "halt"):      "halt",
    ("workflow.review_all_proceed",    "ask"):       "ask",
    ("workflow.review_all_proceed",    "proceed"):   "skip",
    ("workflow.review_all_proceed",    "halt"):      "halt",
    ("workflow.plan_decisions_approval", "ask"):     "ask",
    ("workflow.plan_decisions_approval", "approve"): "skip",
    ("workflow.plan_decisions_approval", "halt"):    "halt",
}

# ---------------------------------------------------------------------------
# Startup guards — run at module load; raise SystemExit(2) on violation
# ---------------------------------------------------------------------------

def _run_startup_guards() -> None:
    """Validate internal registry consistency at module load."""
    # Guard 1: every question_id must have a corresponding VALIDATORS entry
    for qid in QUESTION_IDS:
        if qid not in VALIDATORS:
            raise SystemExit(
                f"[config] startup guard failed: QUESTION_IDS key {qid!r} "
                "is not present in VALIDATORS — add it before shipping"
            )

    # Guard 2: every question_id must have a non-null skill_default
    for qid, meta in QUESTION_IDS.items():
        if meta.get("skill_default") is None:
            raise SystemExit(
                f"[config] startup guard failed: QUESTION_IDS[{qid!r}]['skill_default'] "
                "is None — every question_id requires a presentation default"
            )

    # Guard 3: every choice referenced in RESULT_MAP must be a valid choice in QUESTION_IDS
    for (qid, choice), result in RESULT_MAP.items():
        if qid not in QUESTION_IDS:
            raise SystemExit(
                f"[config] startup guard failed: RESULT_MAP references question_id "
                f"{qid!r} which is not in QUESTION_IDS"
            )
        if choice not in QUESTION_IDS[qid]["choices"]:
            raise SystemExit(
                f"[config] startup guard failed: RESULT_MAP[({qid!r}, {choice!r})] "
                f"references choice {choice!r} which is not in "
                f"QUESTION_IDS[{qid!r}]['choices'] = {QUESTION_IDS[qid]['choices']!r}"
            )


_run_startup_guards()

# Valid event kinds for should-notify
_NOTIFY_EVENTS: set = {"approval", "phase_end", "error"}

# Key-format regex: 2 to 4 segments, all lowercase with underscores/digits.
# Valid: notify.level, roles.z_plan.consultant_primary, roles.z_plan.consultant_primary.persona
# Invalid: roles..foo (empty segment), roles.z_plan.role.field.extra (5 segments), uppercase or hyphens
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$")


# ---------------------------------------------------------------------------
# Pure helper: _dotted_to_env
# ---------------------------------------------------------------------------

_ENV_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _dotted_to_env(key: str) -> str:
    """
    Translate a 2-level dotted TOML key to a Z_HARNESS_ env var name.

    notify.level  ->  Z_HARNESS_NOTIFY_LEVEL
    docs.always_apply  ->  Z_HARNESS_DOCS_ALWAYS_APPLY

    Raises SystemExit(2) if key does not match ``^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$``
    (exactly 2 segments; 3-level role keys are not exported as env vars).
    """
    if not _ENV_KEY_RE.match(key):
        print(
            f"[config] key {key!r} does not match required format "
            r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$",
            file=sys.stderr,
        )
        sys.exit(2)
    return "Z_HARNESS_" + key.upper().replace(".", "_")


# ---------------------------------------------------------------------------
# TOML key name validation
# ---------------------------------------------------------------------------

def _validate_toml_keys(data: dict, path: str) -> None:
    """
    Reject hyphenated keys and keys with >3-level table nesting (i.e. no dict
    values at depth ≥4 from the root).

    Supported nesting depth (as TOML table headers):
      [section]                             — depth 1 (e.g. [notify])
      [section.subsection]                  — depth 2 (e.g. [workflow])
      [section.subsection.role]             — depth 3 (e.g. [roles.z_plan.consultant_primary])

    Leaf values (strings, ints, etc.) may appear at any supported depth.
    """
    for top_key, value in data.items():
        if "-" in top_key:
            print(
                f"[config] {path}: hyphenated key {top_key!r} is not allowed "
                "(use underscores)",
                file=sys.stderr,
            )
            sys.exit(2)
        if isinstance(value, dict):
            for sub_key, sub_val in value.items():
                if "-" in sub_key:
                    print(
                        f"[config] {path}: hyphenated key {top_key!r}.{sub_key!r} "
                        "is not allowed (use underscores)",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                if isinstance(sub_val, dict):
                    # 3-level table nesting is allowed: [section.subsection.role]
                    for role_key, role_val in sub_val.items():
                        if "-" in role_key:
                            print(
                                f"[config] {path}: hyphenated key "
                                f"{top_key!r}.{sub_key!r}.{role_key!r} "
                                "is not allowed (use underscores)",
                                file=sys.stderr,
                            )
                            sys.exit(2)
                        if isinstance(role_val, dict):
                            # role_val is a dict — this is the leaf table (depth 4)
                            # containing actual key=value pairs; check leaf keys for hyphens
                            # and reject any deeper nesting (depth 5+)
                            for leaf_key, leaf_val in role_val.items():
                                if "-" in leaf_key:
                                    print(
                                        f"[config] {path}: hyphenated key "
                                        f"{top_key!r}.{sub_key!r}.{role_key!r}.{leaf_key!r} "
                                        "is not allowed (use underscores)",
                                        file=sys.stderr,
                                    )
                                    sys.exit(2)
                                if isinstance(leaf_val, dict):
                                    print(
                                        f"[config] {path}: key "
                                        f"{top_key!r}.{sub_key!r}.{role_key!r}.{leaf_key!r} "
                                        "has >3-level nesting; not supported",
                                        file=sys.stderr,
                                    )
                                    sys.exit(2)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_toml(path: Path) -> dict:
    """Load TOML file; return None if file missing."""
    if not path.exists():
        return None
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except PermissionError:
        print(
            f"[config] permission denied reading {path}",
            file=sys.stderr,
        )
        sys.exit(4)
    except tomllib.TOMLDecodeError as exc:
        print(
            f"[config] {path}: TOML parse error: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)
    return data


def _check_schema_version(data: dict, path: str) -> None:
    if not data:
        return
    v = data.get("schema_version")
    if v is not None and v != 1:
        print(
            f"[config] {path}: schema_version must be 1 (got {v!r})",
            file=sys.stderr,
        )
        sys.exit(2)


def _global_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(xdg) / "z-harness" / "config.toml"


def _repo_config_path(require_exists: bool = True) -> Path:
    """
    Return the repo-local config path.

    When ``require_exists`` is True (the default, used by readers), exits 2 if
    ``Z_HARNESS_REPO_CONFIG`` is set but the path does not yet exist.
    When ``require_exists`` is False (used by writers), returns the path even if
    the file does not exist yet.
    """
    repo_env = os.environ.get("Z_HARNESS_REPO_CONFIG", "")
    if repo_env:
        p = Path(repo_env)
        if require_exists and not p.exists():
            print(
                f"[config] Z_HARNESS_REPO_CONFIG={repo_env!r} does not exist",
                file=sys.stderr,
            )
            sys.exit(2)
        return p
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        repo_root = Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        repo_root = Path.cwd()
    return repo_root / ".z-harness" / "config.toml"


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------

def _validate_enum(dotted_key: str, value: object, source_label: str, is_global: bool) -> object:
    """
    Validate a value against VALIDATORS.
    - global layer: emit warning + return default value (soft fail).
    - repo/env layer: exit 2 (hard fail).
    Returns (possibly substituted) value.
    """
    if dotted_key not in VALIDATORS:
        return value
    allowed = VALIDATORS[dotted_key]
    if callable(allowed):
        valid = allowed(value)
    else:
        valid = value in allowed
    if not valid:
        msg = (
            f"[config] {source_label}: invalid value for {dotted_key!r}: "
            f"{value!r} — allowed: {sorted(allowed)}"
        )
        if is_global:
            print(f"WARNING: {msg}; falling back to default", file=sys.stderr)
            # Get default value for this key
            section, key = dotted_key.split(".", 1)
            return DEFAULTS[section][key]
        else:
            print(msg, file=sys.stderr)
            sys.exit(2)
    return value


# ---------------------------------------------------------------------------
# 3-level role key validation
# ---------------------------------------------------------------------------

def _validate_roles_value(dotted_key: str, value: object, source_label: str, is_global: bool) -> object | None:
    """
    Validate a 3-level role key value (e.g. roles.z_plan.consultant_primary.persona).

    If the key is in VALIDATORS, delegate to _validate_enum.
    Otherwise, validate as a non-empty string (the default for role keys).

    Returns the (possibly substituted) value on success, or None if validation fails
    and is_global is True (soft fail — caller skips the key).
    On hard fail (repo/env layer), exits with code 2.
    """
    if dotted_key in VALIDATORS:
        return _validate_enum(dotted_key, value, source_label, is_global)

    # Default validation: must be a string.
    # Empty string is permitted for the 'model' leaf key (semantics: use provider's
    # default_model). All other role fields must be non-empty strings.
    leaf_key = dotted_key.rsplit(".", 1)[-1] if "." in dotted_key else dotted_key
    allow_empty = leaf_key == "model"
    if not isinstance(value, str) or (not allow_empty and not value):
        msg = (
            f"[config] {source_label}: invalid value for {dotted_key!r}: "
            f"{value!r} — must be a non-empty string"
        )
        if is_global:
            print(f"WARNING: {msg}; skipping key", file=sys.stderr)
            return None
        else:
            print(msg, file=sys.stderr)
            sys.exit(2)
    return value


# ---------------------------------------------------------------------------
# Layer merging
# ---------------------------------------------------------------------------

def _flatten_defaults() -> dict[str, object]:
    """Return flat {dotted_key: value} from DEFAULTS (excluding meta keys)."""
    result = {}
    for section, value in DEFAULTS.items():
        if section in META_KEYS:
            continue
        if isinstance(value, dict):
            for k, v in value.items():
                result[f"{section}.{k}"] = v
        # top-level scalars (none in current schema beyond meta keys)
    return result


def load_config() -> tuple[dict[str, object], dict[str, str]]:
    """
    Build resolved config.

    Returns:
        (values, sources) where both are {dotted_key: ...}
        sources maps each key to 'defaults' | 'global' | 'repo' | 'env:<VAR>'
    """
    values: dict[str, object] = {}
    sources: dict[str, str] = {}

    # Layer 1: Defaults
    flat_defaults = _flatten_defaults()
    for k, v in flat_defaults.items():
        values[k] = v
        sources[k] = "defaults"

    # Layer 2: Global user config
    global_path = _global_config_path()
    global_data = _load_toml(global_path)
    if global_data is not None:
        _check_schema_version(global_data, str(global_path))
        _validate_toml_keys(global_data, str(global_path))
        for section, sv in global_data.items():
            if section in META_KEYS:
                continue
            if not isinstance(sv, dict):
                continue
            for k, v in sv.items():
                if isinstance(v, dict):
                    # 3-level table nesting: e.g. [roles.z_plan.consultant_primary]
                    # sv[k] == {"consultant_primary": {"persona": "X", ...}}
                    # k = "z_plan", v = {"consultant_primary": {"persona": "X", ...}}
                    for role_name, role_fields in v.items():
                        if not isinstance(role_fields, dict):
                            # Unexpected: skip non-dict at this level
                            continue
                        for leaf_k, leaf_v in role_fields.items():
                            dotted = f"{section}.{k}.{role_name}.{leaf_k}"
                            v_validated = _validate_roles_value(dotted, leaf_v, str(global_path), is_global=True)
                            if v_validated is not None:
                                values[dotted] = v_validated
                                sources[dotted] = str(global_path)
                else:
                    dotted = f"{section}.{k}"
                    # Silently ignore unknown 2-level keys for forward compatibility.
                    if dotted not in flat_defaults:
                        continue
                    v = _validate_enum(dotted, v, str(global_path), is_global=True)
                    values[dotted] = v
                    sources[dotted] = str(global_path)

    # Layer 3: Repo-local config
    repo_path = _repo_config_path()
    repo_data = _load_toml(repo_path)
    if repo_data is not None:
        _check_schema_version(repo_data, str(repo_path))
        _validate_toml_keys(repo_data, str(repo_path))
        for section, sv in repo_data.items():
            if section in META_KEYS:
                continue
            if not isinstance(sv, dict):
                continue
            for k, v in sv.items():
                if isinstance(v, dict):
                    # 3-level table nesting: e.g. [roles.z_plan.consultant_primary]
                    # sv[k] == {"consultant_primary": {"persona": "X", ...}}
                    # k = "z_plan", v = {"consultant_primary": {"persona": "X", ...}}
                    for role_name, role_fields in v.items():
                        if not isinstance(role_fields, dict):
                            # Unexpected: skip non-dict at this level
                            continue
                        for leaf_k, leaf_v in role_fields.items():
                            dotted = f"{section}.{k}.{role_name}.{leaf_k}"
                            v_validated = _validate_roles_value(dotted, leaf_v, str(repo_path), is_global=False)
                            if v_validated is not None:
                                values[dotted] = v_validated
                                sources[dotted] = str(repo_path)
                else:
                    dotted = f"{section}.{k}"
                    # Silently ignore unknown 2-level keys for forward compatibility.
                    if dotted not in flat_defaults:
                        continue
                    v = _validate_enum(dotted, v, str(repo_path), is_global=False)
                    values[dotted] = v
                    sources[dotted] = str(repo_path)

    # Layer 4: Env vars
    for dotted_key in list(flat_defaults.keys()):
        env_var = _dotted_to_env(dotted_key)
        env_val = os.environ.get(env_var, "")
        if env_val == "":
            continue
        env_val = _validate_enum(dotted_key, env_val, f"env {env_var}", is_global=False)
        values[dotted_key] = env_val
        sources[dotted_key] = f"env {env_var}"

    return values, sources


# ---------------------------------------------------------------------------
# Event emission (export-env only)
# ---------------------------------------------------------------------------

def _emit_config_resolved(values: dict, sources: dict) -> None:
    """
    Emit config_resolved event once per $Z_HARNESS_RUN via O_EXCL de-dup.
    No-op if $Z_HARNESS_RUN is not set.
    """
    run = os.environ.get("Z_HARNESS_RUN", "")
    if not run:
        return

    tmpdir = tempfile.gettempdir()
    stamp = os.path.join(tmpdir, f"z-harness-config-resolved-{run}")
    try:
        fd = os.open(stamp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return  # already emitted for this run

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    payload = json.dumps({"values": values, "sources": sources})
    try:
        subprocess.run(
            ["bash", str(log_event), run, "config_resolved", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _valid_user_keys() -> list[str]:
    """Return all dotted keys that are NOT meta keys."""
    keys = []
    for section, value in DEFAULTS.items():
        if section in META_KEYS:
            continue
        if isinstance(value, dict):
            for k in value:
                keys.append(f"{section}.{k}")
    return sorted(keys)


def cmd_get(args: list[str]) -> None:
    if len(args) != 1:
        print("usage: config.py get <dotted.key>", file=sys.stderr)
        sys.exit(2)
    key = args[0]
    if key in META_KEYS:
        valid_keys = _valid_user_keys()
        print(
            f"[config] {key!r} is a meta key; valid user keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(3)
    values, _ = load_config()
    if key not in values:
        valid_keys = _valid_user_keys()
        print(
            f"[config] unknown key {key!r}; valid keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(3)
    # Print raw scalar (no quotes, no shlex)
    val = values[key]
    if isinstance(val, bool):
        print("true" if val else "false")
    else:
        print(val)


def cmd_export_env(args: list[str]) -> None:
    values, sources = load_config()
    for dotted_key in sorted(values.keys()):
        # Skip roles.* keys — they are not exported as env vars
        first_segment = dotted_key.split(".", 1)[0]
        if first_segment == "roles":
            continue
        env_var = _dotted_to_env(dotted_key)
        val = values[dotted_key]
        # Coerce to shell string
        if isinstance(val, bool):
            shell_val = "true" if val else "false"
        else:
            shell_val = str(val)
        print(f"export {env_var}={shlex.quote(shell_val)}")
    _emit_config_resolved(values, sources)


def cmd_ensure_defaults(args: list[str]) -> None:
    global_path = _global_config_path()

    if global_path.exists():
        # Check for 0-byte or unparseable
        if global_path.stat().st_size == 0:
            print(
                f"[config] file exists but is empty: {global_path}. "
                "Remove or fix it manually.",
                file=sys.stderr,
            )
            sys.exit(4)
        try:
            with open(global_path, "rb") as fh:
                tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            print(
                f"[config] file exists but is unparseable: {global_path}. "
                f"Remove or fix it manually. Parse error: {exc}",
                file=sys.stderr,
            )
            sys.exit(4)
        print(f"exists {global_path}")
        return

    # Create parent directory if needed
    try:
        global_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"[config] cannot create directory {global_path.parent}: {exc}",
            file=sys.stderr,
        )
        sys.exit(4)

    # Write default config with inline comments
    content = (
        '# z-harness config — generated by "scripts/config.py ensure-defaults"\n'
        "# Edit freely. Run 'scripts/config.py explain <key>' to see effective values.\n"
        "\n"
        "schema_version = 1\n"
        "\n"
        "[notify]\n"
        "# Notification verbosity. Values: off | approval_only | all\n"
        'level = "approval_only"\n'
        "\n"
        "[docs]\n"
        "# Whether to auto-apply docs in light flows. Values: always | never\n"
        'always_apply = "always"\n'
        "\n"
        "# Default role bindings — persona + model + runtime per logical role.\n"
        "# Override per command with [roles.<command>.<role>] sections.\n"
        "\n"
        "[roles.default.consultant_primary]\n"
        'persona = "codex-default-consultant"\n'
        'model = ""              # empty = use provider\'s default_model\n'
        'runtime = "codex-cli"\n'
        "\n"
        "[roles.default.consultant_secondary]\n"
        'persona = "gemini-default-consultant"\n'
        'runtime = "gemini-cli"\n'
        "\n"
        "[roles.default.reviewer]\n"
        'persona = "codex-default-reviewer"\n'
        'runtime = "codex-cli"\n'
    )
    try:
        global_path.write_text(content)
    except OSError as exc:
        print(
            f"[config] cannot write {global_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(4)
    print(f"created {global_path}")


def cmd_explain(args: list[str]) -> None:
    if len(args) != 1:
        print("usage: config.py explain <dotted.key>", file=sys.stderr)
        sys.exit(2)
    key = args[0]
    if not _KEY_RE.match(key):
        print(
            f"[config] key {key!r} does not match required format "
            "(2 to 4 lowercase dot-separated segments, underscores/digits only)",
            file=sys.stderr,
        )
        sys.exit(2)
    if key in META_KEYS:
        valid_keys = _valid_user_keys()
        print(
            f"[config] {key!r} is a meta key; valid user keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(3)
    values, sources = load_config()
    if key not in values:
        valid_keys = _valid_user_keys()
        print(
            f"[config] unknown key {key!r}; valid keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(3)
    val = values[key]
    src = sources[key]
    print(f'{key} = "{val}"   (source: {src})')


def cmd_list_question_ids(args: list[str]) -> None:
    """Print a sorted JSON array of registered question IDs to stdout."""
    print(json.dumps(sorted(QUESTION_IDS.keys())))


# ---------------------------------------------------------------------------
# resolve-question subcommand
# ---------------------------------------------------------------------------

def _emit_askuser_resolved(
    question_id: str,
    result: str,
    source: str,
    strength: str,
) -> None:
    """
    Emit an askuser_resolved event via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    payload = json.dumps({
        "question_id": question_id,
        "result": result,
        "source": source,
        "strength": strength,
    })
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "askuser_resolved", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


def _get_project_root() -> str:
    """
    Return the current project root for memory scope filtering.

    Priority:
      1. Z_HARNESS_PROJECT_ROOT env var
      2. git rev-parse --show-toplevel
      3. Empty string (treat all memories as scope=global matches when outside a git repo)
    """
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


def _emit_routing_preference_malformed(location: str, index: int, reason: str) -> None:
    """
    Emit a routing_preference_malformed event via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        print(
            f"[config] routing_preference_malformed: {location}[{index}]: {reason}",
            file=sys.stderr,
        )
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        print(
            f"[config] routing_preference_malformed: {location}[{index}]: {reason}",
            file=sys.stderr,
        )
        return

    payload = json.dumps({
        "location": location,
        "index": index,
        "reason": reason,
    })
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "routing_preference_malformed", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort
    print(
        f"[config] routing_preference_malformed: {location}[{index}]: {reason}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Overnight override helpers (halt-from-ask integration)
# ---------------------------------------------------------------------------

def _parse_overnight_allowlist(s: str) -> dict[str, str]:
    """
    Parse the Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE env var (a JSON object
    string) into a {question_id: chosen_value} dict.

    Returns the merged allowlist: OVERNIGHT_AUTODECIDE_QIDS_DEFAULT entries
    overlaid by the parsed env entries (env wins on key collision).

    Malformed entries (non-string keys/values, invalid question_id, or invalid
    choice for the question_id) are dropped with a routing_preference_malformed
    event and a stderr warning.  An unparseable JSON string causes the env
    layer to be skipped entirely (defaults still apply).
    """
    merged: dict[str, str] = dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT)

    if not s.strip():
        return merged

    try:
        env_data = json.loads(s)
    except json.JSONDecodeError as exc:
        print(
            f"[config] Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE is not valid JSON: {exc}; "
            "falling back to default allowlist",
            file=sys.stderr,
        )
        return merged

    if not isinstance(env_data, dict):
        print(
            "[config] Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE must be a JSON object; "
            "falling back to default allowlist",
            file=sys.stderr,
        )
        return merged

    for idx, (qid, value) in enumerate(env_data.items()):
        if not isinstance(qid, str) or not isinstance(value, str):
            _emit_routing_preference_malformed(
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", idx,
                "key and value must both be strings"
            )
            continue
        if qid not in QUESTION_IDS:
            _emit_routing_preference_malformed(
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", idx,
                f"unknown question_id {qid!r}"
            )
            continue
        if value not in QUESTION_IDS[qid]["choices"]:
            _emit_routing_preference_malformed(
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", idx,
                f"invalid value {value!r} for question_id {qid!r}; "
                f"allowed: {sorted(QUESTION_IDS[qid]['choices'])}"
            )
            continue
        merged[qid] = value

    return merged


def _emit_config_conflict(conflict: str, payload: dict) -> None:
    """
    Emit a config_conflict event via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    Also prints a warning to stderr.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    print(
        f"[config] config_conflict: {conflict}",
        file=sys.stderr,
    )
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    event_payload = json.dumps({"conflict": conflict, **payload})
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "config_conflict", event_payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


def _apply_overnight_overrides(
    envelope: dict,
    question_id: str,
) -> dict:
    """
    Post-process the resolution envelope for overnight/halt-from-ask behavior.

    This function is called from cmd_resolve_question AFTER building the envelope
    and BEFORE emitting telemetry + printing to stdout.

    Rules (in priority order):
    1. If Z_HARNESS_NO_ASK != 'halt' → no-op, return envelope unchanged.
    2. If Z_HARNESS_ASK_ALL=1 AND Z_HARNESS_NO_ASK=halt → conflict: emit
       config_conflict event, print error JSON, exit 5.
    3. If envelope['result'] == 'ask' and question_id in allowlist →
       swap to overnight_decision envelope; emit overnight_decision event.
    4. If envelope['result'] == 'ask' and question_id not in allowlist →
       swap to halt envelope; emit askuser_halted event.
    5. Else (result is skip/prefill — no ask needed) → no-op.

    Returns the (possibly modified) envelope.  Never returns on cases 2+.
    """
    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask != "halt":
        return envelope

    # Case 2: conflicting config
    ask_all = os.environ.get("Z_HARNESS_ASK_ALL", "")
    if ask_all == "1":
        conflict_envelope = {
            "error": "config_conflict",
            "conflict": "Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt are mutually exclusive",
            "result": "error",
        }
        _emit_config_conflict(
            "Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt",
            {"question_id": question_id},
        )
        print(json.dumps(conflict_envelope))
        sys.exit(5)

    # Only override when the resolved result is 'ask'
    if envelope.get("result") != "ask":
        return envelope

    skill_default: str = envelope.get("default", "")
    qmeta = QUESTION_IDS.get(question_id, {})
    choices: list[str] = sorted(qmeta.get("choices", []))

    # Build would_have_asked (D4: only default + choices — no question/header text)
    would_have_asked = {
        "default": skill_default,
        "choices": choices,
    }

    allowlist = _parse_overnight_allowlist(
        os.environ.get("Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", "")
    )

    if question_id in allowlist:
        # Case 3: allowlist hit → overnight_decision
        chosen_value = allowlist[question_id]
        mapped_result = RESULT_MAP.get((question_id, chosen_value), "ask")
        overnight_envelope = {
            "result": mapped_result,
            "default": skill_default,
            "source": "overnight_allowlist",
            "rule_id": f"{question_id}:{chosen_value}",
            "strength": "policy",
            "reason": f"overnight allowlist: {question_id} = {chosen_value}",
            "sources": [{"kind": "allowlist", "value": chosen_value,
                         "location": "OVERNIGHT_AUTODECIDE_QIDS or env"}],
            "chosen": chosen_value,
        }
        _emit_overnight_event("overnight_decision", {
            "question_id": question_id,
            "chosen": chosen_value,
            "source": "overnight_allowlist",
            "strength": "policy",
            "rule_id": f"{question_id}:{chosen_value}",
            "sources": overnight_envelope["sources"],
        })
        return overnight_envelope
    else:
        # Case 4: not in allowlist → halt
        halt_envelope = {
            "result": "halt",
            "default": skill_default,
            "source": "no_ask_halt",
            "rule_id": "no_ask_halt",
            "strength": "policy",
            "reason": "Z_HARNESS_NO_ASK=halt and question_id not in overnight allowlist",
            "sources": [{"kind": "env", "value": "halt", "location": "Z_HARNESS_NO_ASK"}],
            "halt_reason": "no_ask_blocked",
            "question_id": question_id,
            "would_have_asked": would_have_asked,
        }
        _emit_overnight_event("askuser_halted", {
            "question_id": question_id,
            "would_have_asked": would_have_asked,
        })
        return halt_envelope


def _emit_overnight_event(kind: str, payload: dict) -> None:
    """
    Emit an overnight-related event (overnight_decision, askuser_halted) via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    event_payload = json.dumps(payload)
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, kind, event_payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


# Required fields for a routing-preference memory entry
_ROUTING_PREF_REQUIRED_FIELDS = {"type", "question_id", "value", "scope", "strength"}


def _load_memory_matches(question_id: str, project_root: str) -> list[dict]:
    """
    Walk docs/llm/*.json (skipping INDEX.json), filter memories[] for
    type=routing-preference matching question_id, respect scope.

    Returns list of dicts: {value, strength, location, scope}
    Malformed entries are logged via _emit_routing_preference_malformed and skipped.

    NOTE: docs_dir is resolved relative to the harness repo (where config.py lives),
    not relative to project_root. project_root is only used for scope filtering.
    """
    # Resolve docs/llm relative to the harness repo root (parent of scripts/)
    harness_root = Path(__file__).parent.parent
    docs_dir = harness_root / "docs" / "llm"
    if not docs_dir.is_dir():
        # Fallback to CWD-based resolution for non-standard layouts
        docs_dir = Path.cwd() / "docs" / "llm"

    if not docs_dir.is_dir():
        return []

    matches = []
    for json_path in sorted(docs_dir.glob("*.json")):
        if json_path.name == "INDEX.json":
            continue

        try:
            with open(json_path, "rb") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"[config] skipping {json_path}: {exc}",
                file=sys.stderr,
            )
            continue

        memories = data.get("memories", [])
        if not isinstance(memories, list):
            continue

        for idx, entry in enumerate(memories):
            if not isinstance(entry, dict):
                _emit_routing_preference_malformed(str(json_path), idx, "entry is not a dict")
                continue

            if entry.get("type") != "routing-preference":
                continue

            # Validate required fields
            missing = _ROUTING_PREF_REQUIRED_FIELDS - set(entry.keys())
            if missing:
                _emit_routing_preference_malformed(
                    str(json_path), idx, f"missing required fields: {sorted(missing)}"
                )
                continue

            if entry["question_id"] != question_id:
                continue

            # Validate strength field
            strength = entry["strength"]
            if strength not in {"weak", "strong", "very_strong"}:
                _emit_routing_preference_malformed(
                    str(json_path), idx,
                    f"invalid strength {strength!r}; allowed: weak, strong, very_strong"
                )
                continue

            # Validate value field
            qmeta = QUESTION_IDS.get(question_id)
            if qmeta and entry["value"] not in qmeta["choices"]:
                _emit_routing_preference_malformed(
                    str(json_path), idx,
                    f"invalid value {entry['value']!r} for question_id {question_id!r}"
                )
                continue

            # Respect scope
            scope = entry["scope"]
            if scope == "global":
                pass  # always included
            elif scope == "project":
                entry_project_root = entry.get("project_root", "")
                if not project_root:
                    # Outside a git repo: treat all as global (edge case per SPEC)
                    pass
                elif entry_project_root != project_root:
                    continue  # doesn't match current project
            else:
                _emit_routing_preference_malformed(
                    str(json_path), idx, f"invalid scope {scope!r}; allowed: global, project"
                )
                continue

            matches.append({
                "value": entry["value"],
                "strength": strength,
                "location": str(json_path),
                "scope": scope,
            })

    return matches


# Strength ordering for "highest strength wins"
_STRENGTH_ORDER = {"very_strong": 3, "strong": 2, "weak": 1}


def _resolve_memory_matches(
    matches: list[dict],
) -> tuple[str | None, str | None, list[dict]]:
    """
    Given a list of memory match dicts, return (value, strength, sources).

    - No matches → (None, None, [])
    - One match → (value, strength, [source])
    - Multiple agreeing → highest strength wins → (value, strength, all_sources)
    - Multiple disagreeing → (None, "conflict", all_sources) signals conflict
    """
    if not matches:
        return None, None, []

    # Gather all unique values
    values_seen = {m["value"] for m in matches}

    sources = [
        {
            "kind": "memory",
            "value": m["value"],
            "location": m["location"],
            "strength": m["strength"],
        }
        for m in matches
    ]

    if len(values_seen) == 1:
        # All agree — pick highest strength
        best = max(matches, key=lambda m: _STRENGTH_ORDER.get(m["strength"], 0))
        return best["value"], best["strength"], sources

    # Disagreeing
    return None, "conflict", sources


def _build_resolve_envelope(
    question_id: str,
    explain: bool = False,
) -> tuple[dict, str, str, str, int]:
    """
    Build the resolution envelope for a registered question_id.

    Returns ``(envelope, emit_result, emit_source, emit_strength, exit_code)``
    where the emit_* values are the arguments to pass to ``_emit_askuser_resolved``
    and ``exit_code`` is 0 on success or 4 on I/O error.

    Precondition: ``question_id`` must be present in ``QUESTION_IDS`` (caller checks).
    ``Z_HARNESS_ASK_ALL=1`` short-circuit is NOT applied here — the caller handles it
    before calling this function so that the early-exit path stays in one place.
    """
    qmeta = QUESTION_IDS[question_id]
    skill_default: str = qmeta["skill_default"]
    config_key: str = qmeta["config_key"]

    # Consult 4-layer config
    try:
        values, sources = load_config()
    except SystemExit:
        # load_config exits on I/O or schema errors; re-raise is the right path
        raise
    except OSError as exc:
        envelope = {
            "error": "io_error",
            "message": str(exc),
            "result": "ask",
            "default": skill_default,
            "source": "none",
            "rule_id": config_key,
            "strength": "none",
            "reason": f"I/O error reading config: {exc}",
            "sources": [],
        }
        print(str(exc), file=sys.stderr)
        return envelope, "ask", "none", "none", 4

    config_value: str = values.get(config_key, "ask")
    config_source_label: str = sources.get(config_key, "defaults")

    # Default value for this config key (the "ask" string means "no preference set")
    default_config_value: str = "ask"
    config_is_default: bool = config_value == default_config_value

    # Consult memory (JSON walk over docs/llm/*.json)
    project_root = _get_project_root()
    memory_matches = _load_memory_matches(question_id, project_root)
    mem_value, mem_strength, mem_sources = _resolve_memory_matches(memory_matches)

    # Combine config + memory signals

    # Case: no memory at all
    if mem_value is None and mem_strength is None:
        if config_is_default:
            # No config preference, no memory → ask
            if explain:
                print(
                    f"[explain] question_id={question_id} → config=ask (default), "
                    "no memory → result=ask",
                    file=sys.stderr,
                )
            envelope = {
                "result": "ask",
                "default": skill_default,
                "source": "none",
                "rule_id": config_key,
                "strength": "none",
                "reason": "No config preference set and no memory entries found",
                "sources": [],
            }
            return envelope, "ask", "none", "none", 0
        else:
            # Config has a non-default value, no memory → config wins
            mapped_result = RESULT_MAP.get((question_id, config_value), "ask")
            reason = (
                f"config key {config_key!r} = {config_value!r} "
                f"(source: {config_source_label}); no memory entries"
            )
            if explain:
                print(
                    f"[explain] question_id={question_id} → config={config_value!r} at "
                    f"{config_source_label} → result={mapped_result} (hard), no memory",
                    file=sys.stderr,
                )
            envelope = {
                "result": mapped_result,
                "default": skill_default,
                "source": "config",
                "rule_id": config_key,
                "strength": "hard",
                "reason": reason,
                "sources": [],
            }
            return envelope, mapped_result, "config", "hard", 0

    # Case: memory conflict (multiple disagreeing entries)
    if mem_strength == "conflict":
        if config_is_default:
            # Config has no opinion; memory alone is conflicted → ask, show memory sources
            envelope = {
                "result": "ask",
                "default": skill_default,
                "source": "conflict",
                "rule_id": config_key,
                "strength": "none",
                "reason": "Memory entries disagree on value",
                "sources": mem_sources,
            }
        else:
            # Config has an opinion AND memory is internally conflicted → conflict
            config_source_entry = {
                "kind": "config",
                "value": config_value,
                "location": config_source_label,
                "strength": "hard",
            }
            all_sources = [config_source_entry] + mem_sources
            envelope = {
                "result": "ask",
                "default": skill_default,
                "source": "conflict",
                "rule_id": config_key,
                "strength": "none",
                "reason": "Config and memory entries disagree on value",
                "sources": all_sources,
            }
        if explain:
            print(
                f"[explain] question_id={question_id} → memory conflict → result=ask",
                file=sys.stderr,
            )
        return envelope, "ask", "conflict", "none", 0

    # At this point: mem_value is set (single or agreeing multiple memory entries)
    # mem_strength is one of weak | strong | very_strong

    if config_is_default:
        # Config is "ask" (default) AND memory exists → memory wins (no conflict)
        # Derive result from memory strength
        if mem_strength == "very_strong":
            mem_result = "skip"
        else:
            # strong or weak → prefill
            mem_result = "prefill"

        if explain:
            print(
                f"[explain] question_id={question_id} → config=ask (default), "
                f"memory={mem_value!r} ({mem_strength}) → result={mem_result}",
                file=sys.stderr,
            )
        envelope = {
            "result": mem_result,
            "default": skill_default,
            "source": "memory",
            "rule_id": config_key,
            "strength": mem_strength,
            "reason": (
                f"Memory routing-preference: question_id={question_id!r}, "
                f"value={mem_value!r}, strength={mem_strength!r}"
            ),
            "sources": mem_sources,
        }
        return envelope, mem_result, "memory", mem_strength, 0

    # Config is non-default AND memory exists
    # Check if they agree: translate config value to result-domain then compare mem_value
    # "Agreement" means memory's value == config's value (both are in the option-domain)
    if mem_value == config_value:
        # Config and memory agree → config wins, no conflict
        mapped_result = RESULT_MAP.get((question_id, config_value), "ask")
        if explain:
            print(
                f"[explain] question_id={question_id} → config={config_value!r} and "
                f"memory={mem_value!r} agree → result={mapped_result} (config wins)",
                file=sys.stderr,
            )
        envelope = {
            "result": mapped_result,
            "default": skill_default,
            "source": "config",
            "rule_id": config_key,
            "strength": "hard",
            "reason": (
                f"Config and memory agree: {config_key!r} = {config_value!r} "
                f"(config source: {config_source_label})"
            ),
            "sources": [],
        }
        return envelope, mapped_result, "config", "hard", 0

    # Config is non-default AND memory disagrees → conflict tier
    config_source_entry = {
        "kind": "config",
        "value": config_value,
        "location": config_source_label,
        "strength": "hard",
    }
    all_sources = [config_source_entry] + mem_sources
    if explain:
        print(
            f"[explain] question_id={question_id} → config={config_value!r} "
            f"vs memory={mem_value!r} → conflict → result=ask",
            file=sys.stderr,
        )
    envelope = {
        "result": "ask",
        "default": skill_default,
        "source": "conflict",
        "rule_id": config_key,
        "strength": "none",
        "reason": (
            f"Config says {config_value!r} but memory says {mem_value!r}; "
            "showing both — resolve the conflict"
        ),
        "sources": all_sources,
    }
    return envelope, "ask", "conflict", "none", 0


def cmd_resolve_question(args: list[str]) -> None:
    """
    resolve-question <question_id> [--scope-slug <slug>] [--explain]

    Returns a JSON envelope to stdout. All diagnostics go to stderr.
    Exit codes:
      0  Success
      2  Bad invocation
      3  Unknown question_id (JSON with error key still emitted)
      4  I/O error (JSON still emitted)
      5  Config conflict (Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt)
    """
    if not args:
        print("usage: config.py resolve-question <question_id> [--scope-slug <slug>] [--explain]",
              file=sys.stderr)
        sys.exit(2)

    # Parse positional + optional args
    question_id: str = ""
    explain: bool = False
    i = 0
    while i < len(args):
        if args[i] == "--explain":
            explain = True
            i += 1
        elif args[i] == "--scope-slug":
            # Consume the slug value (not used by the resolver itself — scope is
            # determined by Z_HARNESS_PROJECT_ROOT / git-toplevel, not slug name)
            i += 2
        elif args[i].startswith("--"):
            print(f"[config] unknown flag {args[i]!r}", file=sys.stderr)
            sys.exit(2)
        elif not question_id:
            question_id = args[i]
            i += 1
        else:
            print(f"[config] unexpected argument {args[i]!r}", file=sys.stderr)
            sys.exit(2)

    if not question_id:
        print("usage: config.py resolve-question <question_id> [--scope-slug <slug>] [--explain]",
              file=sys.stderr)
        sys.exit(2)

    # Check Z_HARNESS_EXPLAIN_RESOLUTION
    if os.environ.get("Z_HARNESS_EXPLAIN_RESOLUTION", "") == "1":
        explain = True

    # Step 1: Validate question_id
    if question_id not in QUESTION_IDS:
        envelope = {
            "error": "unknown_question_id",
            "known": sorted(QUESTION_IDS.keys()),
        }
        print(json.dumps(envelope))
        sys.exit(3)

    # Step 2: Honor Z_HARNESS_ASK_ALL=1 short-circuit (but check for conflict first).
    # _apply_overnight_overrides handles the ASK_ALL + NO_ASK=halt conflict case
    # (exits 5), so we build the ASK_ALL envelope and pass it through the override.
    if os.environ.get("Z_HARNESS_ASK_ALL", "") == "1":
        qmeta = QUESTION_IDS[question_id]
        skill_default: str = qmeta["skill_default"]
        envelope = {
            "result": "ask",
            "default": skill_default,
            "source": "override",
            "rule_id": "Z_HARNESS_ASK_ALL",
            "strength": "none",
            "reason": "Z_HARNESS_ASK_ALL=1 forces ask for all questions",
            "sources": [],
        }
        if explain:
            print(
                f"[explain] question_id={question_id} → Z_HARNESS_ASK_ALL=1 override → result=ask",
                file=sys.stderr,
            )
        # Post-process through overnight overrides: detects ASK_ALL+NO_ASK conflict → exit 5
        envelope = _apply_overnight_overrides(envelope, question_id)
        _emit_askuser_resolved(question_id, "ask", "override", "none")
        print(json.dumps(envelope))
        sys.exit(0)

    # Steps 3-11: Build envelope via helper, then apply overnight overrides before
    # emitting telemetry and printing to stdout.
    envelope, emit_result, emit_source, emit_strength, exit_code = _build_resolve_envelope(
        question_id, explain=explain
    )
    # Post-process: halt-from-ask / overnight allowlist (no-op when NO_ASK != halt)
    envelope = _apply_overnight_overrides(envelope, question_id)
    _emit_askuser_resolved(question_id, emit_result, emit_source, emit_strength)
    print(json.dumps(envelope))
    sys.exit(exit_code)


def _emit_unknown_ask_blocked(question_id: str, callsite_hint: str = "") -> None:
    """
    Emit an unknown_ask_blocked event via log-event.sh.
    Non-fatal: silently skips if Z_HARNESS_RUN is unset or log-event.sh unavailable.
    """
    run_id = os.environ.get("Z_HARNESS_RUN", "")
    if not run_id:
        return

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if not log_event.exists() or not shutil.which("bash"):
        return

    payload = json.dumps({
        "question_id": question_id,
        "callsite_hint": callsite_hint,
    })
    try:
        subprocess.run(
            ["bash", str(log_event), run_id, "unknown_ask_blocked", payload],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # non-fatal — observability is best-effort


def cmd_check_no_ask(args: list[str]) -> None:
    """
    check-no-ask --question-id <id>

    Returns JSON: {"result": "halt"|"proceed", "question_id": "<id>", "rule_id": "<rule>"}

    Paths:
      1. Z_HARNESS_NO_ASK != halt  → proceed, rule_id=no_overnight_active
      2. NO_ASK=halt, qid registered, in allowlist → proceed (resolved as overnight_decision)
      3. NO_ASK=halt, qid registered, NOT in allowlist → halt
      4. NO_ASK=halt, qid NOT registered → halt + unknown_ask_blocked event
      5. Bad invocation (missing --question-id) → exit 2

    Exit 0 on all valid invocations, exit 2 on argparse error.
    """
    question_id: str = ""
    i = 0
    while i < len(args):
        if args[i] == "--question-id":
            if i + 1 >= len(args):
                print("usage: config.py check-no-ask --question-id <id>", file=sys.stderr)
                sys.exit(2)
            question_id = args[i + 1]
            i += 2
        elif args[i].startswith("--"):
            print(f"[config] unknown flag {args[i]!r}", file=sys.stderr)
            sys.exit(2)
        else:
            print(f"[config] unexpected argument {args[i]!r}", file=sys.stderr)
            sys.exit(2)

    if not question_id:
        print("usage: config.py check-no-ask --question-id <id>", file=sys.stderr)
        sys.exit(2)

    # Path 1: overnight mode not active
    no_ask = os.environ.get("Z_HARNESS_NO_ASK", "")
    if no_ask != "halt":
        result = {"result": "proceed", "question_id": question_id, "rule_id": "no_overnight_active"}
        print(json.dumps(result))
        sys.exit(0)

    # Path 4: question_id not registered → fail-closed
    if question_id not in QUESTION_IDS:
        _emit_unknown_ask_blocked(question_id)
        result = {"result": "halt", "question_id": question_id, "rule_id": "unknown_ask_blocked"}
        print(json.dumps(result))
        sys.exit(0)

    # Paths 2 & 3: registered question_id — build envelope, apply overnight overrides,
    # then map envelope result to halt/proceed.
    envelope, _emit_result, _emit_source, _emit_strength, _exit_code = _build_resolve_envelope(
        question_id, explain=False
    )
    # Post-process: applies allowlist / halt logic for NO_ASK=halt
    envelope = _apply_overnight_overrides(envelope, question_id)

    envelope_result = envelope.get("result", "ask")
    if envelope_result == "halt":
        result = {"result": "halt", "question_id": question_id, "rule_id": envelope.get("rule_id", "no_ask_halt")}
    else:
        rule_id = envelope.get("rule_id", "no_ask_halt")
        result = {"result": "proceed", "question_id": question_id, "rule_id": rule_id}

    print(json.dumps(result))
    sys.exit(0)


def _toml_write_scalar(lines: list, k: str, v: object) -> None:
    """Append a single TOML key = value line to ``lines``."""
    if isinstance(v, str):
        lines.append(f'{k} = "{v}"\n')
    elif isinstance(v, bool):
        lines.append(f'{k} = {"true" if v else "false"}\n')
    else:
        lines.append(f"{k} = {v}\n")


def _toml_write(path: Path, data: dict) -> None:
    """
    Write ``data`` to ``path`` atomically via tmp+rename.

    Supports up to three-level table nesting:
      schema_version = 1

      [section]
      key = "value"

      [section.subsection.role]
      key = "value"

    Only handles str, bool, and int values at leaf level.
    Raises OSError if the write fails (caller handles exit 4).
    """
    lines: list[str] = []
    # Write top-level scalars first (only schema_version in practice)
    for k, v in data.items():
        if not isinstance(v, dict):
            _toml_write_scalar(lines, k, v)

    # Write each section
    for section, sv in data.items():
        if not isinstance(sv, dict):
            continue
        # Check if any values in this section are nested dicts (3-level tables)
        has_nested = any(isinstance(sv2, dict) for sv2 in sv.values())
        if not has_nested:
            lines.append(f"\n[{section}]\n")
            for sk, sv2 in sv.items():
                _toml_write_scalar(lines, sk, sv2)
        else:
            # 3-level: emit [section.subsection.role] headers with leaf pairs
            # (used by [roles.<command>.<role>] tables)
            for sub_key, sub_val in sv.items():
                if isinstance(sub_val, dict):
                    for role_key, role_val in sub_val.items():
                        if isinstance(role_val, dict):
                            lines.append(f"\n[{section}.{sub_key}.{role_key}]\n")
                            for leaf_k, leaf_v in role_val.items():
                                _toml_write_scalar(lines, leaf_k, leaf_v)

    content = "".join(lines)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file in the same directory, then atomically rename
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except OSError:
        # Clean up temp file if rename failed
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def cmd_set(args: list[str]) -> None:
    """
    set <key> <value> [--scope=global|project]

    Validates <key> against _KEY_RE and VALIDATORS[<key>], then atomically
    writes the value to the target TOML file via tmp+rename.
    Preserves all other existing keys (read-modify-write).
    Exit 0 on success, 2 on validation failure, 4 on I/O error.
    """
    scope = "project"
    positional: list[str] = []

    for arg in args:
        if arg.startswith("--scope="):
            scope = arg[len("--scope="):]
        elif arg.startswith("--"):
            print(f"[config] unknown flag {arg!r}", file=sys.stderr)
            sys.exit(2)
        else:
            positional.append(arg)

    if len(positional) != 2:
        print("usage: config.py set <key> <value> [--scope=global|project]", file=sys.stderr)
        sys.exit(2)

    key, value = positional

    if scope not in {"global", "project"}:
        print(
            f"[config] invalid scope {scope!r}; allowed: global, project",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate key format
    if not _KEY_RE.match(key):
        print(
            f"[config] key {key!r} does not match required format "
            r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate key is known (exists in VALIDATORS)
    if key not in VALIDATORS:
        valid_keys = _valid_user_keys()
        print(
            f"[config] unknown key {key!r}; valid keys: {valid_keys}",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate value against VALIDATORS
    allowed = VALIDATORS[key]
    if callable(allowed):
        valid = allowed(value)
    else:
        valid = value in allowed
    if not valid:
        print(
            f"[config] invalid value for {key!r}: {value!r} — allowed: {sorted(allowed)}",
            file=sys.stderr,
        )
        sys.exit(2)

    # Resolve target path; writers pass require_exists=False to allow creating new files
    if scope == "global":
        target_path = _global_config_path()
    else:
        target_path = _repo_config_path(require_exists=False)

    # Read-modify-write: load existing data or start from scratch
    existing = _load_toml(target_path)
    if existing is None:
        data: dict = {"schema_version": 1}
    else:
        data = dict(existing)

    # Mutate the target key
    section, subkey = key.split(".", 1)
    if section not in data or not isinstance(data[section], dict):
        data[section] = {}
    else:
        data[section] = dict(data[section])
    data[section][subkey] = value

    # Atomic write
    try:
        _toml_write(target_path, data)
    except OSError as exc:
        print(f"[config] cannot write {target_path}: {exc}", file=sys.stderr)
        sys.exit(4)


def cmd_should_notify(args: list[str]) -> None:
    # Parse --event <kind>
    if len(args) != 2 or args[0] != "--event":
        print("usage: config.py should-notify --event <kind>", file=sys.stderr)
        sys.exit(2)
    event = args[1]
    if event not in _NOTIFY_EVENTS:
        print(
            f"[config] unknown event kind {event!r}; "
            f"allowed: {sorted(_NOTIFY_EVENTS)}",
            file=sys.stderr,
        )
        sys.exit(2)

    values, _ = load_config()
    level = values.get("notify.level", DEFAULTS["notify"]["level"])

    if level == "off":
        print("no")
    elif level == "approval_only":
        if event in {"approval", "error"}:
            print("yes")
        else:
            print("no")
    elif level == "all":
        print("yes")
    else:
        # Should not happen — VALIDATORS would have caught it
        print("no")


# ---------------------------------------------------------------------------
# Migrate subcommand
# ---------------------------------------------------------------------------

_PROVIDER_RENAME: dict[str, str] = {
    "codex": "codex-cli",
    "gemini": "gemini-cli",
    "claude": "claude-cli",
}


def _migrate_roles_data(data: dict) -> tuple[dict, int]:
    """
    Walk ``data["roles"]`` and rewrite old provider names in ``runtime`` fields.

    Returns ``(mutated_data, rewrite_count)`` where ``rewrite_count`` is the
    number of values that were actually changed.  The input dict is mutated
    in-place and also returned.
    """
    count = 0
    roles = data.get("roles")
    if not isinstance(roles, dict):
        return data, 0
    for _cmd, cmd_val in roles.items():
        if not isinstance(cmd_val, dict):
            continue
        for _role, role_val in cmd_val.items():
            if not isinstance(role_val, dict):
                continue
            old = role_val.get("runtime")
            if isinstance(old, str) and old in _PROVIDER_RENAME:
                role_val["runtime"] = _PROVIDER_RENAME[old]
                count += 1
    return data, count


def cmd_migrate(_args: list[str]) -> None:
    """
    migrate

    Rewrites old provider names (codex, gemini, claude) in any
    ``roles.*.runtime`` config value to the new ``-cli`` form.  Applied to
    both the global (~/.config/z-harness/config.toml) and project
    (.z-harness/config.toml) layers.  Layers that do not exist are skipped.

    Atomic via temp-file rename.  Idempotent — running twice is a no-op.
    Exit 0 always unless an I/O error occurs (exit 4).
    """
    layers: list[tuple[str, Path]] = [
        ("global", _global_config_path()),
        ("project", _repo_config_path(require_exists=False)),
    ]

    for label, path in layers:
        if not path.exists():
            continue
        data = _load_toml(path)
        if data is None:
            continue
        data, count = _migrate_roles_data(data)
        if count == 0:
            continue
        try:
            _toml_write(path, data)
        except OSError as exc:
            print(
                f"[config] migrate: cannot write {path}: {exc}",
                file=sys.stderr,
            )
            sys.exit(4)
        print(f"[config] migrate: {label} — rewrote {count} runtime value(s) in {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: config.py <get|export-env|ensure-defaults|explain|should-notify"
            "|list-question-ids|resolve-question|check-no-ask|set|migrate> [args...]",
            file=sys.stderr,
        )
        sys.exit(2)

    subcommand = sys.argv[1]
    args = sys.argv[2:]

    if subcommand == "get":
        cmd_get(args)
    elif subcommand == "export-env":
        cmd_export_env(args)
    elif subcommand == "ensure-defaults":
        cmd_ensure_defaults(args)
    elif subcommand == "explain":
        cmd_explain(args)
    elif subcommand == "should-notify":
        cmd_should_notify(args)
    elif subcommand == "list-question-ids":
        cmd_list_question_ids(args)
    elif subcommand == "resolve-question":
        cmd_resolve_question(args)
    elif subcommand == "check-no-ask":
        cmd_check_no_ask(args)
    elif subcommand == "set":
        cmd_set(args)
    elif subcommand == "migrate":
        cmd_migrate(args)
    else:
        print(
            f"[config] unknown subcommand {subcommand!r}; "
            "valid: get, export-env, ensure-defaults, explain, should-notify, "
            "list-question-ids, resolve-question, check-no-ask, set, migrate",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
