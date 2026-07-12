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
    "artifact_plan_mode",
    "canonical_tasks_present",
    "artifact_similar_candidates",
    "active_registry_overlap",
    "worktree_overlap",
    "artifact_match_confidence",
    "artifact_match_basis",
    "asks_what_should_we_do",
    "premise_underspecified",
    "alternatives_unsettled",
    "architecture_decision",
    "reversibility_uncertain",
    "approach_uncertain",
    "terrain_uncertain",
    "plan_validation_intent",
    "post_artifact_check",
    "question_heavy_artifacts",
    "artifact_unsettled_approach",
}

PLAN_ROUTE_CHECK_SIGNALS = {
    "plan_validation_intent",
    "question_heavy_artifacts",
    "artifact_unsettled_approach",
    "post_artifact_check",
    "asks_what_should_we_do",
    "alternatives_unsettled",
    "architecture_decision",
    "reversibility_uncertain",
}

REQUIRED_REASON_CODES = {
    "existing_artifact_exact",
    "existing_artifact_similar",
    "existing_plan_audit",
    "existing_plan_amend",
    "active_plan_overlap",
    "worktree_overlap",
    "inventory_partial",
    "inventory_truncated",
    "needs_sharpen",
    "needs_brainstorm",
    "alternatives_unclear",
    "architecture_uncertain",
    "reversibility_uncertain",
    "question_heavy_artifacts",
    "unsettled_approach",
    "post_artifact_recommendation",
    "intent_finished_plan",
    "canonical_tasks_present",
    "route_loop_risk",
    "too_many_tasks",
    "ambiguous_route",
    "premise_underspecified",
}

LEGACY_SIGNAL_NAME_PARTS = {
    ("plan_validation", "requested"),
    ("question_heavy", "artifact"),
    ("unsettled_approach", "signal"),
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
    route_chain = signals.get("route_chain_json")
    if isinstance(route_chain, list) and len(route_chain) >= 2:
        return {
            "STATUS": "ask_user",
            "RECOMMENDED": "ask_user",
            "ROUTE_CLASS": "none",
            "CONFIDENCE": "low",
            "REASON_CODES": "route_loop_risk",
        }

    exact_finished = bool(
        signals.get("artifact_exact_slug_match")
        and signals.get("artifact_finished_plan_match")
    )
    exact_intent_finished = bool(
        exact_finished
        and signals.get("artifact_plan_mode") == "intent"
        and signals.get("canonical_tasks_present")
    )
    post_artifact_primary_recommendation = bool(
        signals.get("post_artifact_check")
        and (
            signals.get("expected_tasks", 0) > 25
            or signals.get("question_heavy_artifacts")
            or signals.get("artifact_unsettled_approach")
        )
    )

    if exact_finished and signals.get("plan_amend_intent"):
        reason_codes = "existing_artifact_exact,existing_plan_amend"
        if exact_intent_finished:
            reason_codes = (
                "existing_artifact_exact,intent_finished_plan,"
                "canonical_tasks_present,existing_plan_amend"
            )
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-amend",
            "ROUTE_CLASS": "contextual",
            "CONFIDENCE": "high",
            "REASON_CODES": reason_codes,
        }

    if (
        exact_finished
        and signals.get("plan_validation_intent")
        and not signals.get("plan_amend_intent")
    ):
        reason_codes = "existing_artifact_exact,existing_plan_audit"
        if exact_intent_finished:
            reason_codes = (
                "existing_artifact_exact,intent_finished_plan,"
                "canonical_tasks_present,existing_plan_audit"
            )
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-audit-plan",
            "ROUTE_CLASS": "contextual",
            "CONFIDENCE": "high",
            "REASON_CODES": reason_codes,
        }

    if exact_finished and not post_artifact_primary_recommendation:
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
            "RECOMMENDED": "/z-plan --quick",
            "ROUTE_CLASS": "primary",
            "CONFIDENCE": "low",
            "REASON_CODES": "inventory_partial,inventory_truncated,tiny_task",
        }

    if signals.get("post_artifact_check") and signals.get("expected_tasks", 0) > 25:
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-plan-split",
            "ROUTE_CLASS": "primary",
            "CONFIDENCE": "high",
            "REASON_CODES": "post_artifact_recommendation,too_many_tasks",
        }

    if signals.get("post_artifact_check") and signals.get("question_heavy_artifacts"):
        reason_codes = "post_artifact_recommendation,question_heavy_artifacts,needs_sharpen"
        if signals.get("worktree_overlap"):
            reason_codes = f"worktree_overlap,{reason_codes}"
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-sharpen",
            "ROUTE_CLASS": "primary",
            "CONFIDENCE": "medium",
            "REASON_CODES": reason_codes,
        }

    if signals.get("post_artifact_check") and signals.get("artifact_unsettled_approach"):
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-brainstorm",
            "ROUTE_CLASS": "primary",
            "CONFIDENCE": "medium",
            "REASON_CODES": "post_artifact_recommendation,unsettled_approach,needs_brainstorm",
        }

    if signals.get("asks_what_should_we_do"):
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-brainstorm",
            "ROUTE_CLASS": "primary",
            "CONFIDENCE": "medium",
            "REASON_CODES": "needs_brainstorm,needs_more_framing",
        }

    if signals.get("premise_underspecified"):
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-sharpen",
            "ROUTE_CLASS": "primary",
            "CONFIDENCE": "medium",
            "REASON_CODES": "needs_sharpen,premise_underspecified",
        }

    if (
        signals.get("alternatives_unsettled")
        or signals.get("architecture_decision")
        or signals.get("reversibility_uncertain")
        or signals.get("approach_uncertain")
    ):
        return {
            "STATUS": "routed",
            "RECOMMENDED": "/z-brainstorm",
            "ROUTE_CLASS": "primary",
            "CONFIDENCE": "high",
            "REASON_CODES": (
                "needs_brainstorm,alternatives_unclear,"
                "architecture_uncertain,reversibility_uncertain"
            ),
        }

    raise AssertionError(f"unhandled T004 example signals: {signals!r}")


def test_declares_typed_artifact_worktree_signals_and_reason_codes() -> None:
    text = _router_text()
    signals = _declared_backtick_names(_section(text, "Expected Signals", "Decision Rules"))
    reason_codes = _declared_backtick_names(_section(text, "Stable Reason Codes", "Expected Signals"))

    assert REQUIRED_SIGNALS <= signals
    assert REQUIRED_REASON_CODES <= reason_codes
    assert PLAN_ROUTE_CHECK_SIGNALS <= signals
    signal_section = _section(text, "Expected Signals", "Decision Rules")
    assert "- `active_registry_overlap`: array" in signal_section
    assert "- `worktree_overlap`: array" in signal_section
    assert "- `artifact_match_basis`: array" in signal_section

    # Check only backtick-wrapped signal tokens so plural stable names do not
    # trigger false positives.
    for prefix, suffix in LEGACY_SIGNAL_NAME_PARTS:
        assert f"`{prefix}_{suffix}`" not in text, (
            f"legacy backtick-wrapped name `{prefix}_{suffix}` still present"
        )

def test_examples_match_deterministic_artifact_signal_rules() -> None:
    titles = [
        "exact finished plan with amend intent routes to /z-amend",
        "exact finished plan with audit intent routes to /z-audit-plan",
        "exact finished plan without amend/audit intent asks the user",
        "historical similar candidates are warning-only for existing-plan state",
        "partial and truncated artifact inventory lowers confidence",
        "intent finished plan with canonical TASKS routes to /z-amend",
        "intent finished plan with canonical TASKS routes to /z-audit-plan",
        "what-should-we-do prompt routes to /z-brainstorm",
        "architecture alternatives route to /z-brainstorm",
        "post-artifact too many tasks recommends /z-plan-split gate",
        "post-artifact exact finished question-heavy artifacts recommend /z-sharpen gate",
        "post-artifact unsettled approach recommends /z-brainstorm gate",
        "route-chain loop risk asks user instead of repeating sharpen",
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

def test_intent_finished_plan_detection_requires_intent_and_canonical_tasks() -> None:
    text = _router_text()
    amend_signals, amend_output = _example("intent finished plan with canonical TASKS routes to /z-amend")
    audit_signals, audit_output = _example("intent finished plan with canonical TASKS routes to /z-audit-plan")

    assert "`INTENT.md` plus canonical `TASKS.md`" in text
    assert "`INTENT.md` alone" in text
    assert "free-form/noncanonical task note" in text
    assert amend_signals["artifact_plan_mode"] == "intent"
    assert amend_signals["canonical_tasks_present"] is True
    assert audit_signals["artifact_plan_mode"] == "intent"
    assert audit_signals["canonical_tasks_present"] is True
    assert amend_output["RECOMMENDED"] == "/z-amend"
    assert audit_output["RECOMMENDED"] == "/z-audit-plan"
    assert {"intent_finished_plan", "canonical_tasks_present"} <= _reason_codes(amend_output)
    assert {"intent_finished_plan", "canonical_tasks_present"} <= _reason_codes(audit_output)


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


def test_what_should_we_do_routes_to_brainstorm_not_sharpen() -> None:
    signals, output = _example("what-should-we-do prompt routes to /z-brainstorm")

    assert signals["asks_what_should_we_do"] is True
    assert output["STATUS"] == "routed"
    assert output["RECOMMENDED"] == "/z-brainstorm"
    assert "needs_brainstorm" in _reason_codes(output)
    assert "needs_sharpen" not in _reason_codes(output)


def test_active_overlap_asks_but_worktree_overlap_is_warning_only() -> None:
    rules = _section(_router_text(), "Decision Rules", "Confidence Guidance")

    assert "`active_registry_overlap` is non-empty" in rules
    assert "include `active_plan_overlap,ambiguous_route`" in rules
    assert "`worktree_overlap` is non-empty" in rules
    assert "warning-only" in rules
    assert "must not by itself return `ask_user` or write a route decision" in rules
    assert "not proof of a reusable plan" in rules


def test_sharpen_brainstorm_and_loop_contracts_are_explicit() -> None:
    text = _router_text()
    signals = _section(text, "Expected Signals", "Decision Rules")
    rules = _section(text, "Decision Rules", "Route Gate and Dispatch Boundaries")

    assert "`question_heavy_artifacts`: boolean" in signals
    assert "`artifact_unsettled_approach`: boolean" in signals
    assert "unresolved placeholders" in signals
    assert "competing approaches" in signals
    assert "`current_command` is not `/z-sharpen`" in rules
    assert "`current_command` is not `/z-brainstorm`" in rules
    assert "return `ask_user` with `route_loop_risk`" in rules
    assert "do not create route ping-pong through `/z-sharpen`, `/z-brainstorm`, `/z-plan`, or `/z-plan-split`" in rules


def test_post_artifact_recommendations_remain_gate_only_not_auto_dispatch() -> None:
    text = _router_text()
    gate = _section(text, "Route Gate and Dispatch Boundaries", "Confidence Guidance")
    rules = _section(text, "Decision Rules", "Route Gate and Dispatch Boundaries")
    signals, output = _example("post-artifact exact finished question-heavy artifacts recommend /z-sharpen gate")

    assert "never means \"execute the recommended command now.\"" in gate
    assert "never auto-dispatched" in gate
    assert "Warning-only artifact/worktree output remains warning-only" in gate
    assert rules.index(
        "If `post_artifact_check` is true and `question_heavy_artifacts`"
    ) < rules.index("If `exact_finished_plan` is true but neither")
    assert signals["post_artifact_check"] is True
    assert signals["question_heavy_artifacts"] is True
    assert signals["artifact_exact_slug_match"] is True
    assert signals["artifact_finished_plan_match"] is True
    assert signals["plan_amend_intent"] is False
    assert signals["plan_validation_intent"] is False
    assert signals["worktree_overlap"]
    assert output["STATUS"] == "routed"
    assert output["RECOMMENDED"] == "/z-sharpen"
    assert output["RECOMMENDED"] != "ask_user"
    assert {"worktree_overlap", "post_artifact_recommendation", "question_heavy_artifacts", "needs_sharpen"} <= _reason_codes(output)


def test_route_chain_loop_example_asks_user_instead_of_repeating_route() -> None:
    signals, output = _example("route-chain loop risk asks user instead of repeating sharpen")

    assert signals["current_command"] == "/z-plan"
    assert len(signals["route_chain_json"]) == 2
    assert output["STATUS"] == "ask_user"
    assert output["RECOMMENDED"] == "ask_user"
    assert output["ROUTE_CLASS"] == "none"
    assert output["CONFIDENCE"] == "low"
    assert _reason_codes(output) == {"route_loop_risk"}

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
