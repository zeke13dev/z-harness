"""
export-cursor.py — Build Cursor .mdc rules from z-harness commands, agents, and skills.

Usage:
    python3 scripts/export-cursor.py [--out exports/cursor]

Emits one .mdc file per command / agent / skill into:
    exports/cursor/.cursor/rules/<id>.mdc

Frontmatter mapping:
    source description  → MDC description
    alwaysApply         → false (default)
    globs               → omitted unless source specifies

Body rewriting:
    Lines or blocks invoking Agent(...), Skill(...), or other Anthropic-specific
    constructs are replaced with a one-line HTML comment directing the reader to
    CAPABILITIES.md.

After emission, each .mdc file is re-parsed to verify:
    - YAML frontmatter is present and parseable between --- fences
    - Body is non-empty

A summary count is printed at the end.
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import re
import sys
from pathlib import Path

# Allow running from repo root: python3 scripts/export-cursor.py
_REPO_ROOT = Path(__file__).resolve().parent.parent

# export-common.py uses a hyphen so it is not directly importable; load it
# via importlib instead.
_COMMON_SPEC = _ilu.spec_from_file_location(
    "export_common",
    _REPO_ROOT / "scripts" / "export-common.py",
)
_COMMON_MOD = _ilu.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(_COMMON_MOD)

enumerate_sources = _COMMON_MOD.enumerate_sources
output_path_for = _COMMON_MOD.output_path_for
validate_capabilities = _COMMON_MOD.validate_capabilities


# ---------------------------------------------------------------------------
# Body rewriting
# ---------------------------------------------------------------------------

# Patterns that indicate Anthropic-specific / Claude Code constructs.
_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(", re.MULTILINE)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Cursor; see CAPABILITIES.md -->"
)


def _rewrite_body(body: str) -> str:
    """Rewrite *body* to remove Anthropic-specific constructs.

    Strategy: scan for Agent(...)/Skill(...)/AskUserQuestion(...) call sites.
    When found on a line, replace that entire line with the replacement comment
    (preserving leading whitespace for readability).  Code blocks that contain
    these constructs are handled line-by-line as well since cursor rules are
    read as plain markdown.
    """
    lines = body.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n\r")
        if (
            _AGENT_CALL_RE.search(stripped)
            or _SKILL_CALL_RE.search(stripped)
            or _TOOL_SCHEMA_RE.search(stripped)
        ):
            # Preserve leading whitespace, replace the rest.
            leading = len(stripped) - len(stripped.lstrip())
            result.append(" " * leading + _REPLACEMENT_COMMENT + "\n")
        else:
            result.append(line)
    return "".join(result)


# ---------------------------------------------------------------------------
# MDC rendering
# ---------------------------------------------------------------------------

def _render_mdc(entry: dict) -> str:
    """Render a single source *entry* as a Cursor .mdc string."""
    fm = entry["frontmatter"]
    body = entry["body"]

    description = fm.get("description", "")
    # Escape any double-quotes in description for YAML safety.
    description_escaped = description.replace('"', '\\"')

    globs_line = ""
    if "globs" in fm:
        globs_escaped = fm["globs"].replace('"', '\\"')
        globs_line = f'\nglobs: "{globs_escaped}"'

    frontmatter_block = (
        f'---\n'
        f'description: "{description_escaped}"{globs_line}\n'
        f'alwaysApply: false\n'
        f'---\n'
    )

    rewritten_body = _rewrite_body(body)
    # Ensure body starts with a newline for readability.
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return frontmatter_block + rewritten_body


# ---------------------------------------------------------------------------
# MDC validation
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _validate_mdc(path: Path) -> list[str]:
    """Basic MDC validation: frontmatter present + parseable, body non-empty.

    Returns a list of error strings; empty list means valid.
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors

    fm_text = m.group(1)
    # Verify required keys are present in frontmatter.
    for required_key in ("description", "alwaysApply"):
        if not re.search(rf"^{required_key}\s*:", fm_text, re.MULTILINE):
            errors.append(f"{path}: frontmatter missing required key '{required_key}'")

    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export z-harness commands/agents/skills to Cursor .mdc rules."
    )
    p.add_argument(
        "--out",
        default="exports/cursor",
        help="Output root directory (default: exports/cursor)",
    )
    p.add_argument(
        "--repo",
        default=str(_REPO_ROOT),
        help="Repository root (default: parent of this script's directory)",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()

    repo_root = Path(args.repo).resolve()
    out_root = (repo_root / args.out) if not Path(args.out).is_absolute() else Path(args.out)

    sources = enumerate_sources(repo_root)

    emitted: list[Path] = []
    skipped: list[tuple[str, str]] = []

    # Build a set of command IDs to detect skill/command name collisions.
    command_ids = {entry["id"] for entry in sources["commands"]}

    for kind in ("commands", "agents", "skills"):
        for entry in sources[kind]:
            eid = entry["id"]
            # Skills that share a name with a command get a "-skill" suffix
            # to avoid overwriting the command export.
            export_id = f"{eid}-skill" if kind == "skills" and eid in command_ids else eid
            out_path = output_path_for(repo_root, "cursor", kind, export_id)
            # If --out differs from the default, redirect accordingly.
            # output_path_for always writes under repo_root/exports/cursor;
            # honour --out by replacing that prefix.
            default_base = repo_root / "exports" / "cursor"
            if out_root != default_base:
                relative = out_path.relative_to(default_base)
                out_path = out_root / relative

            out_path.parent.mkdir(parents=True, exist_ok=True)

            mdc_content = _render_mdc(entry)
            out_path.write_text(mdc_content, encoding="utf-8")
            emitted.append(out_path)

    # Validate all emitted files.
    validation_errors: list[str] = []
    for path in emitted:
        validation_errors.extend(_validate_mdc(path))

    # Validate CAPABILITIES.md if it exists.
    caps_path = out_root / "CAPABILITIES.md"
    if caps_path.exists():
        cap_errors = validate_capabilities(caps_path)
        if cap_errors:
            validation_errors.extend(
                [f"CAPABILITIES.md: {e}" for e in cap_errors]
            )

    # Print summary.
    total = len(emitted)
    print(f"export-cursor: emitted {total} .mdc files to {out_root / '.cursor' / 'rules'}")

    if skipped:
        print(f"  skipped {len(skipped)} entries:")
        for sid, reason in skipped:
            print(f"    {sid}: {reason}")

    if validation_errors:
        print(f"\nValidation errors ({len(validation_errors)}):")
        for err in validation_errors:
            print(f"  ERROR: {err}")
        return 1

    print(f"  all {total} files passed validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
