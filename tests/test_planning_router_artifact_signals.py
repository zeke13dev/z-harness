"""Contract tests for planning-router artifact/worktree signal handling.

The router is an agent markdown contract, not executable Python.  These tests
therefore parse the deterministic signal/reason-code declarations and the
contract examples that callers rely on, without invoking an LLM.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROUTER_MD = Path(__file__).resolve().parents[1] / "agents" / "planning-router.md"

REQUIRED_SIGNALS = {
    "artifact_exact_slug_match",
    "artifact_finished_plan_match",
    "artifact_similar_candidates",
    "active_registry_overlap",
    "worktree_overlap",
    "artifact_match_confidence",
    "artifact_match_basis",
}

REQUIRED_REASON_CODES = {
    "existing_artifact_exact",
    "existing_artifact_similar",
    "active_plan_overlap",
    "worktree_overlap",
    "inventory_partial",
    "inventory_truncated",
}


def _router_text() -> str:
    return ROUTER_MD.read_text(encoding="utf-8")


def _section(text: str, heading: str, next_heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n(?P<body>.*?)^## {re.escape(next_heading)}\n",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"missing section {heading!r} before {next_heading!r}"
    return match.group("body")


def _declared_backtick_names(section: str) -> set[str]:
    return set(re.findall(r"^- `([^`]+)`", section, flags=re.MULTILINE))


def _example(title: str) -> tuple[dict[str, object], dict[str, str]]:
    text = _router_text()
    pattern = rf"^### Example: {re.escape(title)}\n\nInput signal sketch:\n\n```json\n(?P<input>.*?)\n```\n\nExpected output:\n\n```text\n(?P<output>.*?)\n```"
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    assert match, f"missing parseable example {title!r}"
    signals = json.loads(match.group("input"))
    output = {}
    for line in match.group("output").splitlines():
        if not line.strip():
            continue
        key, value = line.split(": ", 1)
        output[key] = value
    return signals, output


def _reason_codes(output: dict[str, str]) -> set[str]:
    return set(output["REASON_CODES"].split(","))


def _basis_contains(signals: dict[str, object], tag: str) -> bool:
    basis = signals.get("artifact_match_basis")
    if isinstance(basis, list):
        return tag in basis
    return basis == tag


def _limited_artifact_router(signals: dict[str, object]) -> dict[str, str]:
    """Deterministic subset of the markdown rules covered by T004 examples."""
    exact_finished = bool(
        signals.get("artifact_exact_slug_match")
        and signals.get("artifact_finished_plan_match")
    )

    if exact_finished and signals.get("plan_amend_intent"):
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-amend",
            "ROUTE_CLASS": "contextual",
            "CONFIDENCE": "high",
            "REASON_CODES": "existing_artifact_exact,existing_plan_amend",
        }

    if (
        exact_finished
        and signals.get("plan_validation_intent")
        and not signals.get("plan_amend_intent")
    ):
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-audit-plan",
            "ROUTE_CLASS": "contextual",
            "CONFIDENCE": "high",
            "REASON_CODES": "existing_artifact_exact,existing_plan_audit",
        }

    if exact_finished:
        return {
            "STATUS": "ask_user",
            "RECOMMENDED": "ask_user",
            "ROUTE_CLASS": "none",
            "CONFIDENCE": "medium",
            "REASON_CODES": "existing_artifact_exact,ambiguous_route",
        }

    if _basis_contains(signals, "historical_similar") or signals.get(
        "artifact_similar_candidates"
    ):
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-plan",
            "ROUTE_CLASS": "primary",
            "CONFIDENCE": "medium",
            "REASON_CODES": "existing_artifact_similar,medium_plan",
        }

    if signals.get("artifact_inventory_partial") and signals.get("artifact_inventory_truncated"):
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-do",
            "ROUTE_CLASS": "primary",
            "CONFIDENCE": "low",
            "REASON_CODES": "inventory_partial,inventory_truncated,tiny_task",
        }

    raise AssertionError(f"unhandled T004 example signals: {signals!r}")


def test_declares_typed_artifact_worktree_signals_and_reason_codes() -> None:
    text = _router_text()
    signals = _declared_backtick_names(_section(text, "Expected Signals", "Decision Rules"))
    reason_codes = _declared_backtick_names(_section(text, "Stable Reason Codes", "Expected Signals"))

    assert REQUIRED_SIGNALS <= signals
    assert REQUIRED_REASON_CODES <= reason_codes
    signal_section = _section(text, "Expected Signals", "Decision Rules")
    assert "- `active_registry_overlap`: array" in signal_section
    assert "- `worktree_overlap`: array" in signal_section
    assert "- `artifact_match_basis`: array" in signal_section


def test_examples_match_deterministic_artifact_signal_rules() -> None:
    titles = [
        "exact finished plan with amend intent routes to /z-amend",
        "exact finished plan with audit intent routes to /z-audit-plan",
        "exact finished plan without amend/audit intent asks the user",
        "historical similar candidates are warning-only for existing-plan state",
        "partial and truncated artifact inventory lowers confidence",
    ]

    for title in titles:
        signals, output = _example(title)
        expected = _limited_artifact_router(signals)
        for key, value in expected.items():
            assert output[key] == value, f"{title}: {key}"


def test_exact_finished_with_amend_intent_routes_z_amend() -> None:
    signals, output = _example("exact finished plan with amend intent routes to /z-amend")

    assert signals["artifact_exact_slug_match"] is True
    assert signals["artifact_finished_plan_match"] is True
    assert signals["plan_amend_intent"] is True
    assert output["STATUS"] == "routed"
    assert output["RECOMMENDED"] == "/z-amend"
    assert output["ROUTE_CLASS"] == "contextual"
    assert output["CONFIDENCE"] == "high"
    assert {"existing_artifact_exact", "existing_plan_amend"} <= _reason_codes(output)


def test_exact_finished_with_audit_intent_routes_z_audit_plan() -> None:
    signals, output = _example("exact finished plan with audit intent routes to /z-audit-plan")

    assert signals["artifact_exact_slug_match"] is True
    assert signals["artifact_finished_plan_match"] is True
    assert signals["plan_validation_intent"] is True
    assert signals["plan_amend_intent"] is False
    assert output["STATUS"] == "routed"
    assert output["RECOMMENDED"] == "/z-audit-plan"
    assert output["ROUTE_CLASS"] == "contextual"
    assert output["CONFIDENCE"] == "high"
    assert {"existing_artifact_exact", "existing_plan_audit"} <= _reason_codes(output)


def test_exact_finished_without_intent_asks_user() -> None:
    signals, output = _example("exact finished plan without amend/audit intent asks the user")

    assert signals["artifact_exact_slug_match"] is True
    assert signals["artifact_finished_plan_match"] is True
    assert signals["plan_amend_intent"] is False
    assert signals["plan_validation_intent"] is False
    assert output["STATUS"] == "ask_user"
    assert output["RECOMMENDED"] == "ask_user"
    assert output["ROUTE_CLASS"] == "none"
    assert {"existing_artifact_exact", "ambiguous_route"} <= _reason_codes(output)


def test_historical_similar_never_satisfies_has_existing_plan() -> None:
    text = _router_text()
    signals, output = _example("historical similar candidates are warning-only for existing-plan state")

    assert "Historical similar candidates never satisfy `has_existing_plan`" in text
    assert signals["has_existing_plan"] is False
    assert signals["artifact_exact_slug_match"] is False
    assert signals["artifact_finished_plan_match"] is False
    assert _basis_contains(signals, "historical_similar")
    assert signals["plan_amend_intent"] is True
    assert output["RECOMMENDED"] not in {"/z-amend", "/z-audit-plan"}
    assert "existing_artifact_similar" in _reason_codes(output)


def test_partial_truncated_inventory_lowers_confidence() -> None:
    signals, output = _example("partial and truncated artifact inventory lowers confidence")

    assert signals["artifact_inventory_partial"] is True
    assert signals["artifact_inventory_truncated"] is True
    assert output["CONFIDENCE"] == "low"
    assert {"inventory_partial", "inventory_truncated"} <= _reason_codes(output)


def test_active_overlap_asks_but_worktree_overlap_is_warning_only() -> None:
    rules = _section(_router_text(), "Decision Rules", "Confidence Guidance")

    assert "`active_registry_overlap` is non-empty" in rules
    assert "include `active_plan_overlap,ambiguous_route`" in rules
    assert "`worktree_overlap` is non-empty" in rules
    assert "warning-only" in rules
    assert "must not by itself return `ask_user` or write a route decision" in rules
    assert "not proof of a reusable plan" in rules


def test_examples_use_only_declared_reason_codes() -> None:
    text = _router_text()
    declared = _declared_backtick_names(_section(text, "Stable Reason Codes", "Expected Signals"))
    example_outputs = re.findall(
        r"^Expected output:\n\n```text\n(?P<output>.*?)\n```",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert example_outputs, "expected at least one parseable output example"

    for output_text in example_outputs:
        reason_line = re.search(r"^REASON_CODES: (.*)$", output_text, flags=re.MULTILINE)
        assert reason_line, f"example lacks REASON_CODES:\n{output_text}"
        assert set(reason_line.group(1).split(",")) <= declared
