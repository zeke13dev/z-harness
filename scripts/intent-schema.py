#!/usr/bin/env python3
"""
scripts/intent-schema.py — INTENT.md + LEDGER.md schema validation,
acceptance-criterion lint helper, and TASKS.md sanity checks.

CLI:
  python3 scripts/intent-schema.py validate-intent <path-to-INTENT.md>
  python3 scripts/intent-schema.py lint-criteria <path-to-INTENT.md>
  python3 scripts/intent-schema.py validate-ledger <path-to-LEDGER.md>
  python3 scripts/intent-schema.py freeze-intent <path-to-INTENT.md>
  python3 scripts/intent-schema.py reopen-intent <path-to-INTENT.md>
  python3 scripts/intent-schema.py bootstrap-ledger <path-to-LEDGER.md> <intent_frozen_at> <slug>
  python3 scripts/intent-schema.py evaluate-acceptance <path-to-INTENT.md> <path-to-LEDGER.md> [<path-to-diff>]
  python3 scripts/intent-schema.py validate-tasks <path-to-INTENT.md> <path-to-TASKS.md> [<#1,#3,...>]

Exit codes:
  0 — valid / no lint failures / operation succeeded / overall verdict is "done"
  1 — validation or lint errors found (details on stdout); or already-frozen when --error-if-frozen;
      or overall verdict is "continue" (for evaluate-acceptance)
  2 — usage error

Also callable as a Python module:
  from scripts.intent_schema import validate_intent, lint_criteria, validate_ledger
  from scripts.intent_schema import freeze_intent, bootstrap_ledger, evaluate_acceptance, validate_tasks

Level semantics (from SPEC.md):
  quick (L1)    — checklist required; not-doing + consider optional
  standard (L2) — checklist, not-doing, consider all required
  deep (L3)     — same as L2 (all sections required)

Acceptance-criterion lint heuristic:
  A criterion is flagged as non-observable if it contains a bare "runs" or "works"
  (case-insensitive) with no observable object following. The heuristic checks
  for these patterns: the word "runs" or "works" appears in the criterion line
  but is NOT followed by a noun phrase that would make it observable
  (e.g. "runs and exits 0" → passes; "runs" alone → fails).
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

VALID_ARTIFACTS = {"intent", "ledger"}
VALID_LEVELS = {"quick", "standard", "deep"}
VALID_PLANNING_MODES = {"intent", "full"}

# Required frontmatter fields for INTENT.md
INTENT_REQUIRED_FIELDS = {
    "artifact",
    "slug",
    "level",
    "generated_at",
    "frozen_at",
    "planning_mode",
}

# Required frontmatter fields for LEDGER.md
LEDGER_REQUIRED_FIELDS = {
    "artifact",
    "slug",
    "intent_frozen_at",
}

# Required sections per level
# checklist is ALWAYS required; not-doing + consider required at L2+
INTENT_SECTIONS_ALWAYS = {"acceptance checklist"}
INTENT_SECTIONS_L2_PLUS = {"not doing", "consider for this"}

# Section heading → canonical name mapping (lowercase, stripped)
SECTION_ALIASES: dict[str, str] = {
    "intent": "intent",
    "not doing": "not doing",
    "consider for this": "consider for this",
    "acceptance checklist": "acceptance checklist",
}

# ---------------------------------------------------------------------------
# Lint heuristic for non-observable criteria
# ---------------------------------------------------------------------------

# Patterns that indicate a bare "runs" or "works" with no observable object.
# A criterion is non-observable when it contains "runs" or "works" as a
# standalone predicate with nothing meaningful following it on the same line.
#
# Observable indicators that save a criterion containing "runs"/"works":
#   - a noun phrase follows (e.g. "runs the tests", "works correctly with X")
#   - an exit code, count, or measurement follows ("runs and exits 0")
#   - "runs" appears in a compound that describes something specific
#
# We flag a criterion when it matches a bare-verb pattern with no substance:
#   - The line (after stripping the checkbox prefix) is ONLY "runs" or "works"
#     optionally with filler words like "correctly", "as expected", "fine", "ok"
#   - The line contains "runs" or "works" but the remainder is empty or only filler

_BARE_VERB_RE = re.compile(
    r"""
    \bruns?\b|\bworks?\b      # the bare verb (run/runs/work/works)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Words that do NOT make the criterion observable — only filler
_FILLER_ONLY_RE = re.compile(
    r"""
    ^[\s,;.\-–—]*                                    # leading punctuation/space
    (?:                                               # optional filler words
        correctly|as\s+expected|fine|ok|okay|
        without\s+errors?|without\s+issues?|
        properly|successfully|normally|smoothly|
        as\s+intended|without\s+problems?
    )?
    [\s,;.\-–—]*$                                    # trailing punctuation/space
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _is_non_observable_criterion(criterion_text: str) -> bool:
    """Return True if the criterion is a bare 'runs'/'works' with no observable object.

    The criterion_text should be the full text of one checklist item, e.g.:
      "[ ] the service runs"
      "[ ] runs"
      "[ ] system works"

    Strips the checkbox prefix before evaluating.
    """
    # Strip checkbox prefix (e.g. "- [ ] ", "[ ] ", "- [x] ")
    text = re.sub(r"^\s*[-*]?\s*\[[x ~]\]\s*", "", criterion_text, flags=re.IGNORECASE)
    text = text.strip()

    # Must contain a bare verb at all
    m = _BARE_VERB_RE.search(text)
    if not m:
        return False

    # Extract what follows the bare verb on the same line
    after_verb = text[m.end():]

    # If what follows is ONLY filler (or empty), the criterion is non-observable
    return bool(_FILLER_ONLY_RE.match(after_verb))


# ---------------------------------------------------------------------------
# Frontmatter parser (simple; handles YAML scalars only)
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, body_without_frontmatter).

    Only parses simple scalar key: value pairs (no nested YAML).
    Returns ({}, content) if no frontmatter block found.
    """
    fm_match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", content, re.DOTALL)
    if not fm_match:
        return {}, content

    fm_body = fm_match.group(1)
    body = content[fm_match.end():]

    fields: dict[str, str] = {}
    for line in fm_body.splitlines():
        kv_match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)", line)
        if kv_match:
            key = kv_match.group(1).strip()
            val = kv_match.group(2).strip()
            # Strip surrounding quotes
            if (val.startswith('"') and val.endswith('"')) or \
               (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            fields[key] = val

    return fields, body


# ---------------------------------------------------------------------------
# Section extractor
# ---------------------------------------------------------------------------

def _extract_sections(body: str) -> set[str]:
    """Return the set of canonical section names found in body.

    Looks for ## headings and maps them to canonical names (lowercase, stripped).
    """
    sections: set[str] = set()
    for line in body.splitlines():
        h_match = re.match(r"^##\s+(.*)", line)
        if h_match:
            heading = h_match.group(1).strip().lower()
            # Normalize to canonical name
            canonical = SECTION_ALIASES.get(heading)
            if canonical:
                sections.add(canonical)
    return sections


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

class ValidationResult(NamedTuple):
    valid: bool
    errors: list[str]


# ---------------------------------------------------------------------------
# validate_intent
# ---------------------------------------------------------------------------

def validate_intent(path: Path) -> ValidationResult:
    """Validate INTENT.md frontmatter + required sections per level.

    Checks:
    1. Frontmatter exists and has all required fields.
    2. artifact == "intent"
    3. level is a valid level value (quick|standard|deep)
    4. planning_mode is a valid value
    5. Required sections are present for the level:
       - checklist always required
       - not-doing + consider required at L2+ (standard|deep)

    Returns ValidationResult(valid, errors) where errors is a list of strings.
    """
    errors: list[str] = []

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult(False, [f"Cannot read file: {exc}"])

    fm, body = _parse_frontmatter(content)

    if not fm:
        errors.append("No YAML frontmatter block found (expected --- delimiters).")
        return ValidationResult(False, errors)

    # Check required fields
    for field in sorted(INTENT_REQUIRED_FIELDS):
        if field not in fm:
            errors.append(f"Missing required frontmatter field: {field!r}")

    # Validate artifact
    artifact = fm.get("artifact", "")
    if artifact and artifact != "intent":
        errors.append(f"Invalid artifact value: {artifact!r} (expected 'intent')")

    # Validate level
    level = fm.get("level", "")
    if level and level not in VALID_LEVELS:
        errors.append(f"Invalid level: {level!r} (expected one of: {', '.join(sorted(VALID_LEVELS))})")

    # Validate planning_mode
    planning_mode = fm.get("planning_mode", "")
    if planning_mode and planning_mode not in VALID_PLANNING_MODES:
        errors.append(
            f"Invalid planning_mode: {planning_mode!r} "
            f"(expected one of: {', '.join(sorted(VALID_PLANNING_MODES))})"
        )

    # Check required sections (only if level is known)
    if level in VALID_LEVELS:
        sections = _extract_sections(body)

        # Checklist always required
        if "acceptance checklist" not in sections:
            errors.append("Missing required section: '## Acceptance checklist' (required at all levels)")

        # not-doing + consider required at L2+ (standard, deep)
        if level in {"standard", "deep"}:
            if "not doing" not in sections:
                errors.append(
                    f"Missing required section: '## Not doing' (required at level '{level}')"
                )
            if "consider for this" not in sections:
                errors.append(
                    f"Missing required section: '## Consider for this' (required at level '{level}')"
                )

    return ValidationResult(len(errors) == 0, errors)


# ---------------------------------------------------------------------------
# lint_criteria
# ---------------------------------------------------------------------------

class LintFailure(NamedTuple):
    line_number: int
    text: str


def lint_criteria(path: Path) -> list[LintFailure]:
    """Lint acceptance checklist items in INTENT.md for non-observable criteria.

    Returns a list of LintFailure(line_number, text) for each offending criterion.
    The line_number is 1-based relative to the full INTENT.md file.

    A criterion is flagged when it contains a bare 'runs' or 'works' with no
    observable object following (see module-level docstring for the heuristic).
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return []

    failures: list[LintFailure] = []
    in_checklist = False

    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()

        # Detect checklist section heading
        if re.match(r"^##\s+acceptance\s+checklist\s*$", stripped, re.IGNORECASE):
            in_checklist = True
            continue

        # Detect any other ## heading (exits checklist section)
        if re.match(r"^##\s+", stripped) and in_checklist:
            in_checklist = False
            continue

        # Inside checklist: check each checkbox item
        if in_checklist and re.match(r"^\s*[-*]?\s*\[[ x~]\]", stripped, re.IGNORECASE):
            if _is_non_observable_criterion(stripped):
                failures.append(LintFailure(line_number=lineno, text=stripped))

    return failures


# ---------------------------------------------------------------------------
# validate_ledger
# ---------------------------------------------------------------------------

def validate_ledger(path: Path) -> ValidationResult:
    """Validate LEDGER.md frontmatter.

    Checks:
    1. Frontmatter exists and has all required fields.
    2. artifact == "ledger"
    """
    errors: list[str] = []

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult(False, [f"Cannot read file: {exc}"])

    fm, _body = _parse_frontmatter(content)

    if not fm:
        errors.append("No YAML frontmatter block found (expected --- delimiters).")
        return ValidationResult(False, errors)

    for field in sorted(LEDGER_REQUIRED_FIELDS):
        if field not in fm:
            errors.append(f"Missing required frontmatter field: {field!r}")

    artifact = fm.get("artifact", "")
    if artifact and artifact != "ledger":
        errors.append(f"Invalid artifact value: {artifact!r} (expected 'ledger')")

    return ValidationResult(len(errors) == 0, errors)


# ---------------------------------------------------------------------------
# freeze_intent
# ---------------------------------------------------------------------------

_PENDING_VALUES = {"pending", '"pending"', "'pending'"}


def reopen_intent(path: Path) -> tuple[bool, str]:
    """Set frozen_at back to 'pending' in INTENT.md frontmatter (re-open a frozen contract).

    Frontmatter-aware: parses only the YAML frontmatter block (delimited by ---) and
    rewrites exactly the frozen_at key there.  Does not touch body text even if it
    happens to contain a line matching "frozen_at:".

    Idempotent: if frozen_at is already 'pending' (or absent with no real timestamp),
    do nothing and return (False, 'pending').

    Returns:
        (was_reopened, new_value)
        was_reopened — True if this call changed the field; False if already pending.
        new_value    — 'pending' always.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Cannot read {path}: {exc}") from exc

    # Locate the frontmatter block boundaries.
    fm_match = re.match(r"^(---\r?\n)(.*?)(\r?\n---\r?\n?)", content, re.DOTALL)
    if not fm_match:
        raise ValueError(f"No YAML frontmatter block found in {path}")

    open_delim = fm_match.group(1)   # "---\n"
    fm_body    = fm_match.group(2)   # inner YAML lines (no surrounding ---)
    close_delim = fm_match.group(3)  # "\n---\n"
    remainder  = content[fm_match.end():]

    # Check current frozen_at value inside the frontmatter body only.
    frozen_at_match = re.search(
        r"^(frozen_at\s*:\s*)(.*)$", fm_body, re.MULTILINE
    )
    if frozen_at_match:
        current_val = frozen_at_match.group(2).strip().strip('"').strip("'")
        if not current_val or current_val.lower() == "pending":
            # Already pending — nothing to do.
            return False, "pending"
        # Replace the existing frozen_at line with pending.
        new_fm_body = fm_body[: frozen_at_match.start()] + \
                      frozen_at_match.group(1) + "pending" + \
                      fm_body[frozen_at_match.end():]
    else:
        # frozen_at key not present in frontmatter — append it.
        new_fm_body = fm_body.rstrip("\n") + "\nfrozen_at: pending"

    new_content = open_delim + new_fm_body + close_delim + remainder
    path.write_text(new_content, encoding="utf-8")
    return True, "pending"


def _is_already_frozen(frozen_at_value: str) -> bool:
    """Return True if the frozen_at field already holds a real ISO timestamp.

    A "pending" value (bare or quoted) is treated as not-yet-frozen.
    Any other non-empty value is treated as a valid ISO stamp.
    """
    v = frozen_at_value.strip().strip('"').strip("'")
    return bool(v) and v.lower() != "pending"


def freeze_intent(path: Path) -> tuple[bool, str]:
    """Stamp frozen_at with the current UTC ISO timestamp on INTENT.md.

    Idempotent: if frozen_at is already a real ISO timestamp, do nothing and
    return (False, <existing_frozen_at>).

    Returns:
        (was_frozen_now, frozen_at_value)
        was_frozen_now — True if this call stamped the field; False if already frozen.
        frozen_at_value — the ISO timestamp that is (or was already) in frozen_at.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Cannot read {path}: {exc}") from exc

    fm, _body = _parse_frontmatter(content)
    existing = fm.get("frozen_at", "")

    if _is_already_frozen(existing):
        # Already frozen — idempotent, return the existing value unchanged.
        existing_clean = existing.strip().strip('"').strip("'")
        return False, existing_clean

    # Stamp now.
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Replace the frozen_at line in the raw frontmatter.
    # We match: optional leading whitespace + "frozen_at" + optional spaces + ":" + value
    new_content = re.sub(
        r"(^frozen_at\s*:\s*).*$",
        rf"\g<1>{now_iso}",
        content,
        count=1,
        flags=re.MULTILINE,
    )

    if new_content == content:
        # frozen_at line not found — append to frontmatter.
        # Insert before closing --- of frontmatter block.
        new_content = re.sub(
            r"(\n---\r?\n)",
            rf"\nfrozen_at: {now_iso}\1",
            content,
            count=1,
        )

    path.write_text(new_content, encoding="utf-8")
    return True, now_iso


# ---------------------------------------------------------------------------
# bootstrap_ledger
# ---------------------------------------------------------------------------

def bootstrap_ledger(path: Path, intent_frozen_at: str, slug: str) -> bool:
    """Create LEDGER.md with required frontmatter if it does not already exist.

    Idempotent: if the file already exists (any content), do nothing and return False.

    Args:
        path             — absolute path where LEDGER.md should be created.
        intent_frozen_at — the ISO timestamp from the just-frozen INTENT.md.
        slug             — the plan slug (for the slug frontmatter field).

    Returns:
        True if the file was created; False if it already existed.
    """
    if path.exists():
        return False

    ledger_content = (
        "---\n"
        "artifact: ledger\n"
        f"slug: {slug}\n"
        f"intent_frozen_at: {intent_frozen_at}\n"
        "---\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger_content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# evaluate_acceptance — BFS termination criterion-satisfaction evaluator
# ---------------------------------------------------------------------------
#
# Heuristic design (static; no LLM call):
#
#   For each numbered acceptance criterion in the frozen INTENT checklist:
#
#     met     — at least one LEDGER entry explicitly cites "criterion #N"
#               AND the cumulative diff is non-empty (confirming actual code
#               change was made in this run).
#
#     unknown — the criterion is cited by at least one LEDGER entry BUT no
#               cumulative diff was provided (diff_path is None or the file
#               does not exist) or the diff is empty.  We cannot confirm
#               code changed without a diff.
#
#     unmet   — no LEDGER entry cites this criterion (regardless of diff).
#
#   Conservative bias (HARD RULE, SPEC invariant):
#     unknown is treated as unmet.  Overall verdict is:
#       done     — every criterion is met  (none are unmet or unknown)
#       continue — at least one criterion is unmet or unknown
#
#   The diff cross-check is intentionally coarse: any non-empty diff
#   confirms that *something* changed this run; we do NOT verify that the
#   diff contains the specific file a criterion names.  This avoids false
#   positives (claiming "met" when only a test helper was touched) while
#   staying feasible for a static helper.  The level-cap and budget guard
#   are hard stops enforced ABOVE this helper (in T010's loop); this
#   helper only reports criterion satisfaction.
#
# Output (stdout, one line per criterion + a VERDICT line):
#   CRITERION 1: met | unmet | unknown  — <criterion text (truncated to 80 chars)>
#   CRITERION 2: unmet  — ...
#   VERDICT: done | continue
#
# Exit codes (when used as CLI):
#   0 — overall verdict is "done"
#   1 — overall verdict is "continue"
#   2 — usage error (missing required args)

# Canonical verdict values
VERDICT_DONE = "done"
VERDICT_CONTINUE = "continue"

# Criterion-level status values
STATUS_MET = "met"
STATUS_UNMET = "unmet"
STATUS_UNKNOWN = "unknown"


class CriterionResult(NamedTuple):
    number: int          # 1-based criterion index
    text: str            # raw criterion text (stripped, checkbox removed)
    status: str          # met | unmet | unknown


class AcceptanceResult(NamedTuple):
    criteria: list[CriterionResult]
    verdict: str         # done | continue



# ---------------------------------------------------------------------------
# validate_tasks — Phase 8 TASKS.md sanity helper
# ---------------------------------------------------------------------------

_CANONICAL_TASK_HEADING_RE = re.compile(r"^##\s+(T\d{3})\s+—\s+.+\s+`\[ \]`\s*$")
_LOOSE_TASK_HEADING_RE = re.compile(r"^##\s+(T\d+)\b")
_CRITERION_REF_RE = re.compile(r"#(\d+)")
_TASK_REF_RE = re.compile(r"\bT\d{3}\b")


class TaskBlock(NamedTuple):
    task_id: str
    heading_line: int
    heading: str
    body_lines: list[str]


def _extract_criterion_refs(text: str) -> set[int]:
    """Return positive criterion numbers referenced as #N."""
    refs: set[int] = set()
    for match in _CRITERION_REF_RE.finditer(text):
        number = int(match.group(1))
        if number > 0:
            refs.add(number)
    return refs


def _parse_criteria_numbers(text: str) -> set[int]:
    """Return positive criterion numbers from a loose CLI/list string."""
    numbers: set[int] = set()
    for match in re.finditer(r"\d+", text):
        number = int(match.group(0))
        if number > 0:
            numbers.add(number)
    return numbers


def _extract_task_blocks(tasks_content: str) -> list[TaskBlock]:
    """Extract level-2 task blocks from TASKS.md."""
    blocks: list[TaskBlock] = []
    current_id: str | None = None
    current_line = 0
    current_heading = ""
    current_body: list[str] = []

    for line_number, line in enumerate(tasks_content.splitlines(), start=1):
        if line.startswith("## "):
            if current_id is not None:
                blocks.append(TaskBlock(current_id, current_line, current_heading, current_body))
                current_id = None
                current_body = []

            loose = _LOOSE_TASK_HEADING_RE.match(line)
            if loose:
                current_id = loose.group(1)
                current_line = line_number
                current_heading = line
                current_body = []
            continue

        if current_id is not None:
            current_body.append(line)

    if current_id is not None:
        blocks.append(TaskBlock(current_id, current_line, current_heading, current_body))

    return blocks


def _task_field(block: TaskBlock, field_name: str) -> str | None:
    """Return the stripped value for a task metadata line, if present."""
    prefix = f"**{field_name}:**"
    for line in block.body_lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return None


def _extract_deferred_criteria(tasks_content: str) -> set[int]:
    """Return criterion numbers listed in the Level notes deferral line."""
    prefix = "**Criteria deferred to next level:**"
    for line in tasks_content.splitlines():
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip()
        if not value or value.lower() == "none":
            return set()
        return _extract_criterion_refs(value)
    return set()


def _find_dependency_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """Return one dependency cycle if present."""
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            start = stack.index(node)
            return stack[start:] + [node]
        if node in visited:
            return None

        visiting.add(node)
        stack.append(node)
        for dep in sorted(graph.get(node, set())):
            cycle = visit(dep)
            if cycle is not None:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(graph):
        cycle = visit(node)
        if cycle is not None:
            return cycle
    return None


def validate_tasks(
    intent_path: Path,
    tasks_path: Path,
    current_criteria: set[int] | None = None,
) -> ValidationResult:
    """Validate a current-level TASKS.md batch against INTENT acceptance criteria.

    The helper is intentionally lightweight and static. It checks the Phase 8
    invariants that make the generated level safe to hand to `/z-execute`:
    every current criterion is advanced or explicitly deferred, every task uses
    canonical pending status, siblings have no intra-level dependencies, any
    declared dependency graph is acyclic, and no task is orphaned from the
    current acceptance set.
    """
    errors: list[str] = []

    try:
        intent_content = intent_path.read_text(encoding="utf-8")
        tasks_content = tasks_path.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult(False, [f"File read error: {exc}"])

    _fm, intent_body = _parse_frontmatter(intent_content)
    criteria = _extract_checklist_items(intent_body)
    if not criteria:
        errors.append("INTENT.md has no acceptance checklist items")

    all_criteria = set(range(1, len(criteria) + 1))
    target_criteria = set(current_criteria) if current_criteria is not None else all_criteria
    for number in sorted(target_criteria):
        if number not in all_criteria:
            errors.append(f"Current criterion #{number} does not exist in INTENT.md")

    blocks = _extract_task_blocks(tasks_content)
    if not blocks:
        errors.append("TASKS.md contains no task blocks")

    task_ids = [block.task_id for block in blocks]
    duplicate_ids = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
    for task_id in duplicate_ids:
        errors.append(f"Duplicate task id: {task_id}")

    task_id_set = set(task_ids)
    dependency_graph: dict[str, set[str]] = {task_id: set() for task_id in task_id_set}
    advanced_criteria: set[int] = set()

    for block in blocks:
        if not _CANONICAL_TASK_HEADING_RE.match(block.heading):
            errors.append(
                f"Task {block.task_id} heading must be '## TNNN — <title> `[ ]`' "
                f"with canonical pending status (line {block.heading_line})"
            )

        depends_on = _task_field(block, "Depends on")
        if depends_on != "—":
            errors.append(f"Task {block.task_id} must use literal '**Depends on:** —'")
            if depends_on:
                dependency_graph.setdefault(block.task_id, set()).update(
                    ref for ref in _TASK_REF_RE.findall(depends_on) if ref in task_id_set
                )

        advances = _task_field(block, "Advances")
        if advances is None:
            errors.append(f"Task {block.task_id} is orphaned: missing '**Advances:**' line")
            continue

        refs = _extract_criterion_refs(advances)
        if not refs:
            errors.append(f"Task {block.task_id} is orphaned: '**Advances:**' names no criterion")
            continue

        valid_current_refs = refs & target_criteria
        if not valid_current_refs:
            errors.append(
                f"Task {block.task_id} is orphaned: '**Advances:**' references no current criterion"
            )

        for ref in sorted(refs):
            if ref not in all_criteria:
                errors.append(f"Task {block.task_id} references nonexistent criterion #{ref}")
            elif ref not in target_criteria:
                errors.append(f"Task {block.task_id} references non-current criterion #{ref}")

        advanced_criteria.update(valid_current_refs)

    cycle = _find_dependency_cycle(dependency_graph)
    if cycle is not None:
        errors.append(f"TASKS.md dependency graph must be acyclic: {' -> '.join(cycle)}")

    deferred_criteria = _extract_deferred_criteria(tasks_content)
    for ref in sorted(deferred_criteria):
        if ref not in all_criteria:
            errors.append(f"Deferred criterion #{ref} does not exist in INTENT.md")
        elif ref not in target_criteria:
            errors.append(f"Deferred criterion #{ref} is not a current-level criterion")

    covered = advanced_criteria | (deferred_criteria & target_criteria)
    for ref in sorted(target_criteria - covered):
        errors.append(f"Criterion #{ref} is neither advanced by a task nor explicitly deferred")

    return ValidationResult(len(errors) == 0, errors)

def _extract_checklist_items(body: str) -> list[str]:
    """Return checklist item texts from the ## Acceptance checklist section.

    Returns items in order, with the checkbox prefix stripped, 1-indexed
    by their position in the list.  Items from all other sections are excluded.
    """
    items: list[str] = []
    in_checklist = False

    for line in body.splitlines():
        stripped = line.strip()

        # Enter checklist section
        if re.match(r"^##\s+acceptance\s+checklist\s*$", stripped, re.IGNORECASE):
            in_checklist = True
            continue

        # Exit on any other ## heading
        if re.match(r"^##\s+", stripped) and in_checklist:
            in_checklist = False
            continue

        if in_checklist and re.match(r"^\s*[-*]?\s*\[[ x~]\]", stripped, re.IGNORECASE):
            # Strip checkbox prefix (e.g. "- [ ] ", "[ ] ", "- [x] ")
            text = re.sub(r"^\s*[-*]?\s*\[[x ~]\]\s*", "", stripped, flags=re.IGNORECASE)
            items.append(text.strip())

    return items


def _extract_ledger_cited_criteria(ledger_body: str) -> set[int]:
    """Return the set of 1-based criterion numbers cited in the LEDGER body.

    Looks for patterns like:
      (advances criterion #N)
      advances criterion #N
      criterion #N

    Where N is a positive integer.  Case-insensitive.  Multiple citations
    per line are all captured.  Returns a set of ints.
    """
    cited: set[int] = set()
    pattern = re.compile(r"criterion\s+#(\d+)", re.IGNORECASE)
    for m in pattern.finditer(ledger_body):
        n = int(m.group(1))
        if n > 0:
            cited.add(n)
    return cited


def evaluate_acceptance(
    intent_path: Path,
    ledger_path: Path,
    diff_path: Path | None = None,
) -> AcceptanceResult:
    """Evaluate per-criterion acceptance satisfaction from INTENT + LEDGER + diff.

    Args:
        intent_path — path to the frozen INTENT.md (must have ## Acceptance checklist).
        ledger_path — path to the LEDGER.md (may have Level sections with criterion cites).
        diff_path   — optional path to a cumulative diff file.  If None, or the file
                      does not exist, or the file is empty, "unknown" is returned for
                      any ledger-cited criterion (conservative — cannot confirm code changed).

    Returns:
        AcceptanceResult with per-criterion CriterionResult list + overall verdict.

    Conservative invariant (HARD RULE):
        unknown is treated as unmet for the verdict calculation.  The verdict
        is "done" only when every criterion is STATUS_MET.

    Raises:
        OSError — if intent_path or ledger_path cannot be read.
    """
    # --- Read INTENT.md ---
    intent_content = intent_path.read_text(encoding="utf-8")
    _fm, intent_body = _parse_frontmatter(intent_content)
    items = _extract_checklist_items(intent_body)

    # --- Read LEDGER.md body ---
    ledger_content = ledger_path.read_text(encoding="utf-8")
    _lfm, ledger_body = _parse_frontmatter(ledger_content)
    cited = _extract_ledger_cited_criteria(ledger_body)

    # --- Determine if diff is non-empty ---
    diff_nonempty: bool = False
    if diff_path is not None and diff_path.exists():
        try:
            diff_text = diff_path.read_text(encoding="utf-8")
            diff_nonempty = bool(diff_text.strip())
        except OSError:
            diff_nonempty = False

    # --- Evaluate each criterion ---
    results: list[CriterionResult] = []
    for idx, text in enumerate(items, start=1):
        if idx in cited:
            if diff_nonempty:
                status = STATUS_MET
            else:
                # Ledger cites it but no diff to confirm actual code change
                status = STATUS_UNKNOWN
        else:
            status = STATUS_UNMET

        results.append(CriterionResult(number=idx, text=text, status=status))

    # --- Overall verdict (conservative: unknown == unmet) ---
    all_met = all(r.status == STATUS_MET for r in results)
    verdict = VERDICT_DONE if (results and all_met) else VERDICT_CONTINUE

    return AcceptanceResult(criteria=results, verdict=verdict)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "Usage: intent-schema.py <command> <file> [args...]\n"
            "Commands:\n"
            "  validate-intent <INTENT.md>                                    — validate frontmatter + required sections\n"
            "  lint-criteria   <INTENT.md>                                    — lint acceptance checklist for non-observable items\n"
            "  validate-ledger <LEDGER.md>                                    — validate ledger frontmatter\n"
            "  freeze-intent   <INTENT.md>                                    — stamp frozen_at (idempotent; prints ISO on stdout)\n"
            "  reopen-intent   <INTENT.md>                                    — set frozen_at to pending (re-open frozen contract; idempotent)\n"
            "  bootstrap-ledger <LEDGER.md> <frozen_at> <slug>               — create LEDGER.md if absent (idempotent)\n"
            "  evaluate-acceptance <INTENT.md> <LEDGER.md> [<diff-file>]     — per-criterion met|unmet|unknown + done|continue verdict\n"
            "  validate-tasks <INTENT.md> <TASKS.md> [<#1,#3,...>]            — Phase 8 TASKS.md sanity checks",
            file=sys.stderr,
        )
        return 2

    cmd = argv[1]
    file_path = Path(argv[2])

    if cmd == "validate-intent":
        result = validate_intent(file_path)
        if result.valid:
            print("OK")
            return 0
        for err in result.errors:
            print(f"ERROR: {err}")
        return 1

    if cmd == "lint-criteria":
        failures = lint_criteria(file_path)
        if not failures:
            print("OK")
            return 0
        for f in failures:
            print(f"LINE {f.line_number}: {f.text}")
        return 1

    if cmd == "validate-ledger":
        result = validate_ledger(file_path)
        if result.valid:
            print("OK")
            return 0
        for err in result.errors:
            print(f"ERROR: {err}")
        return 1

    if cmd == "freeze-intent":
        try:
            was_frozen_now, frozen_at = freeze_intent(file_path)
        except OSError as exc:
            print(f"ERROR: {exc}")
            return 1
        if was_frozen_now:
            print(f"FROZEN: {frozen_at}")
        else:
            print(f"ALREADY_FROZEN: {frozen_at}")
        return 0

    if cmd == "reopen-intent":
        try:
            was_reopened, new_val = reopen_intent(file_path)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            return 1
        if was_reopened:
            print(f"REOPENED: {new_val}")
        else:
            print(f"ALREADY_PENDING: {new_val}")
        return 0

    if cmd == "bootstrap-ledger":
        # argv: bootstrap-ledger <LEDGER.md> <frozen_at> <slug>
        if len(argv) < 5:
            print(
                "Usage: intent-schema.py bootstrap-ledger <LEDGER.md> <frozen_at> <slug>",
                file=sys.stderr,
            )
            return 2
        intent_frozen_at = argv[3]
        slug = argv[4]
        created = bootstrap_ledger(file_path, intent_frozen_at, slug)
        if created:
            print(f"CREATED: {file_path}")
        else:
            print(f"EXISTS: {file_path}")
        return 0

    if cmd == "validate-tasks":
        # argv: validate-tasks <INTENT.md> <TASKS.md> [<#1,#3,...>]
        if len(argv) < 4:
            print(
                "Usage: intent-schema.py validate-tasks <INTENT.md> <TASKS.md> [<#1,#3,...>]",
                file=sys.stderr,
            )
            return 2
        intent_file = file_path          # argv[2]
        tasks_file = Path(argv[3])
        current_criteria = _parse_criteria_numbers(argv[4]) if len(argv) >= 5 else None
        result = validate_tasks(intent_file, tasks_file, current_criteria=current_criteria)
        if result.valid:
            print("OK")
            return 0
        for err in result.errors:
            print(f"ERROR: {err}")
        return 1

    if cmd == "evaluate-acceptance":
        # argv: evaluate-acceptance <INTENT.md> <LEDGER.md> [<diff-file>]
        if len(argv) < 4:
            print(
                "Usage: intent-schema.py evaluate-acceptance <INTENT.md> <LEDGER.md> [<diff-file>]",
                file=sys.stderr,
            )
            return 2
        intent_file = file_path          # argv[2]
        ledger_file = Path(argv[3])
        diff_file = Path(argv[4]) if len(argv) >= 5 else None

        try:
            result = evaluate_acceptance(intent_file, ledger_file, diff_file)
        except OSError as exc:
            print(f"ERROR: {exc}")
            return 1

        for cr in result.criteria:
            # Truncate long criterion text to 80 chars for readability
            text_display = cr.text if len(cr.text) <= 80 else cr.text[:77] + "..."
            print(f"CRITERION {cr.number}: {cr.status}  — {text_display}")

        print(f"VERDICT: {result.verdict}")
        return 0 if result.verdict == VERDICT_DONE else 1

    print(f"Unknown command: {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
