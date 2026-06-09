#!/usr/bin/env python3
"""render-run-brief.py — Render archive/$RUN/run-brief.json to chat, push, or json.

Usage:
    render-run-brief.py --run-dir PATH [--format chat|push|json] [--require]
    render-run-brief.py --self-test

``--require`` exits 2 if run-brief.json is missing or fails JSON Schema validation.
``--self-test`` runs golden fixture checks under tests/run-brief-fixtures/.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

APPROACH_BULLET_BAD = re.compile(r"(\.[A-Za-z0-9]{1,5}:|/)")
BULLET_LINE = re.compile(r"^[-*]\s+")
NUMBERED_LINE = re.compile(r"^\d+[.)]\s+")

MAX_DECISION_ROWS = 8
MAX_APPROACH_BULLETS = 4

DECISION_EVENT_KINDS = frozenset(
    {"user_choice", "user_override", "plan_route_decision", "next_step_choice"}
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _contract_path() -> Path:
    return _repo_root() / "docs" / "llm" / "run-brief-contract.json"


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_events(events_path: Path) -> list[dict]:
    if not events_path.is_file():
        return []
    events: list[dict] = []
    with events_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def extract_approach_bullets(file_path: str | Path) -> list[str]:
    """Extract up to four human-readable approach bullets from a markdown/text artifact."""
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    bullets: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        item = ""
        if BULLET_LINE.match(stripped):
            item = BULLET_LINE.sub("", stripped).strip()
        elif NUMBERED_LINE.match(stripped):
            item = NUMBERED_LINE.sub("", stripped).strip()
        if not item or APPROACH_BULLET_BAD.search(item):
            continue
        bullets.append(item)
        if len(bullets) >= MAX_APPROACH_BULLETS:
            break
    return bullets


def _decision_from_event(event: dict) -> dict | None:
    kind = event.get("kind")
    if kind in ("user_choice", "user_override"):
        question_id = (event.get("question_id") or event.get("decision_key") or "").strip()
        chosen = (event.get("chosen") or "").strip()
        if not question_id or not chosen:
            return None
        entry: dict = {
            "question_id": question_id,
            "chosen": chosen,
            "source": "event",
        }
        tentative = event.get("tentative")
        if kind == "user_override" and tentative and tentative != chosen:
            entry["why"] = f"Overrode recommendation: {tentative}"
        return entry

    if kind == "plan_route_decision":
        chosen = (event.get("user_choice") or "").strip()
        if not chosen:
            return None
        from_command = (event.get("from_command") or "unknown").strip()
        to_command = event.get("to_command")
        question_id = f"plan_route.{from_command}"
        entry = {
            "question_id": question_id,
            "chosen": chosen,
            "source": "event",
        }
        if to_command:
            entry["why"] = f"Route to {to_command}"
        return entry

    if kind == "next_step_choice":
        chosen = (event.get("choice") or "").strip()
        if not chosen:
            return None
        return {
            "question_id": "next_step_choice",
            "chosen": chosen,
            "source": "event",
        }

    return None


def aggregate_decisions(events_path: str | Path) -> list[dict]:
    """Collect decision rows from events.jsonl (last wins per question_id)."""
    by_id: dict[str, dict] = {}
    for event in _load_events(Path(events_path)):
        if event.get("kind") not in DECISION_EVENT_KINDS:
            continue
        entry = _decision_from_event(event)
        if entry is None:
            continue
        by_id[entry["question_id"]] = entry
    return list(by_id.values())


def validate_brief(brief: dict, contract_path: Path | None = None) -> list[str]:
    """Return schema validation error strings; empty list means valid."""
    contract_path = contract_path or _contract_path()
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        return ["jsonschema package required (pip install jsonschema referencing)"]

    contract = _load_json(contract_path)
    cid = contract["$id"]
    registry = Registry().with_resources([(cid, Resource.from_contents(contract))])
    validator = Draft202012Validator({"$ref": f"{cid}#/$defs/run_brief"}, registry=registry)
    errors = sorted(validator.iter_errors(brief), key=lambda e: list(e.path))
    out: list[str] = []
    for err in errors:
        loc = ".".join(str(p) for p in err.path) or "(root)"
        out.append(f"{loc}: {err.message}")
    return out


def render_chat(brief: dict) -> str:
    lines: list[str] = []

    lines.append("INTENT:")
    lines.append(brief.get("intent", ""))
    lines.append("")

    profile = brief.get("profile", "full")
    approach = brief.get("approach") or []
    if profile == "full" and approach:
        lines.append("APPROACH:")
        for bullet in approach[:MAX_APPROACH_BULLETS]:
            lines.append(f"- {bullet}")
        lines.append("")

    if profile == "full" and "decisions" in brief:
        lines.append("DECISIONS:")
        decisions = list(brief.get("decisions") or [])
        shown = decisions[:MAX_DECISION_ROWS]
        for decision in shown:
            qid = decision.get("question_id", "")
            chosen = decision.get("chosen", "")
            lines.append(f"  {qid} → {chosen}")
        overflow = len(decisions) - len(shown)
        if overflow > 0:
            lines.append(f"  (+{overflow} more — see events.jsonl)")
        elif not decisions:
            lines.append("  (none)")
        lines.append("")

    lines.append("OUTCOME:")
    lines.append(brief.get("outcome", ""))
    lines.append("")

    lines.append("NEXT:")
    nxt = brief.get("next") or {}
    lines.append(nxt.get("label", ""))
    lines.append("")

    # Cost summary — injected from --cost-summary-text flag
    cost_text = brief.get("_cost_summary_text") or ""
    if cost_text.strip():
        lines.append(cost_text.strip())
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def render_push(brief: dict) -> str:
    intent = (brief.get("intent") or "")[:80]
    outcome = (brief.get("outcome") or "")[:60]
    next_label = (brief.get("next") or {}).get("label") or ""
    return f"{intent} · {outcome} · Next: {next_label}"


def render_json(brief: dict) -> str:
    return json.dumps(brief, indent=2, ensure_ascii=False) + "\n"


def _brief_path(run_dir: Path) -> Path:
    return run_dir / "run-brief.json"


def _fixtures_base() -> Path:
    return _repo_root() / "tests" / "run-brief-fixtures"


def _compare_chat_golden(fixture_dir: Path) -> tuple[bool, str, list[str]]:
    """Compare render_chat output to chat.golden.txt in fixture_dir."""
    label = fixture_dir.name
    brief_file = _brief_path(fixture_dir)
    golden_file = fixture_dir / "chat.golden.txt"

    for path in (brief_file, golden_file):
        if not path.is_file():
            return False, label, [f"FAIL [{label}]: missing fixture file: {path}\n"]

    brief = _load_json(brief_file)
    actual = render_chat(brief)
    expected = golden_file.read_text(encoding="utf-8")

    if actual == expected:
        return True, label, []

    diff = list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"expected ({label}/chat.golden.txt)",
            tofile=f"actual (render_chat for {label})",
        )
    )
    return False, label, diff


def cmd_self_test() -> int:
    """Run golden and invariant checks against tests/run-brief-fixtures/."""
    fixtures = _fixtures_base()
    overall_pass = True

    passed, label, diff_lines = _compare_chat_golden(fixtures / "full-shipped")
    if passed:
        print(f"PASS [{label}]: chat golden comparison passed")
    else:
        overall_pass = False
        print(f"FAIL [{label}]: chat output differs from golden", file=sys.stderr)
        print("".join(diff_lines), file=sys.stderr)

    max_push_chars = 200
    for name in ("full-shipped", "lite-halted"):
        brief_file = _brief_path(fixtures / name)
        if not brief_file.is_file():
            overall_pass = False
            print(f"FAIL [{name}]: missing {brief_file}", file=sys.stderr)
            continue
        brief = _load_json(brief_file)
        push_line = render_push(brief)
        push_len = len(push_line)
        if push_len <= max_push_chars:
            print(f"PASS [{name}]: push format length {push_len} <= {max_push_chars}")
        else:
            overall_pass = False
            print(
                f"FAIL [{name}]: push format length {push_len} exceeds {max_push_chars}",
                file=sys.stderr,
            )

    events_path = fixtures / "events-sample.jsonl"
    if not events_path.is_file():
        overall_pass = False
        print(f"FAIL [events-sample]: missing {events_path}", file=sys.stderr)
    else:
        rows = aggregate_decisions(events_path)
        if len(rows) >= 2:
            print(f"PASS [events-sample]: aggregate_decisions returned {len(rows)} rows")
        else:
            overall_pass = False
            print(
                f"FAIL [events-sample]: aggregate_decisions returned {len(rows)} rows (need >= 2)",
                file=sys.stderr,
            )

    if overall_pass:
        print("PASS: all run-brief self-tests passed")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render run-brief.json")
    parser.add_argument("--run-dir", help="Archive run directory")
    parser.add_argument(
        "--format",
        choices=("chat", "push", "json"),
        default=None,
        help="Output format (default: chat; omitted with --require alone validates silently)",
    )
    parser.add_argument(
        "--require",
        action="store_true",
        help="Exit 2 if run-brief.json is missing or invalid",
    )
    parser.add_argument(
        "--cost-summary-text",
        default="",
        help="Cost summary Markdown text to append to chat output",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run golden fixture checks and exit",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return cmd_self_test()

    if not args.run_dir:
        parser.error("--run-dir is required unless --self-test is specified")

    run_dir = Path(args.run_dir).resolve()
    brief_file = _brief_path(run_dir)

    if not brief_file.is_file():
        msg = f"render-run-brief.py: missing {brief_file}"
        print(msg, file=sys.stderr)
        return 2 if args.require else 1

    try:
        brief = _load_json(brief_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"render-run-brief.py: invalid JSON in {brief_file}: {exc}", file=sys.stderr)
        return 2 if args.require else 1

    errors = validate_brief(brief)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 2 if args.require else 1

    # Inject cost summary text if provided
    if args.cost_summary_text:
        brief["_cost_summary_text"] = args.cost_summary_text

    if args.require and args.format is None:
        return 0

    fmt = args.format or "chat"
    if fmt == "chat":
        sys.stdout.write(render_chat(brief))
    elif fmt == "push":
        sys.stdout.write(render_push(brief) + "\n")
    else:
        sys.stdout.write(render_json(brief))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
