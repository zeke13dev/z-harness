from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "artifact_scout" / "route_semantics_cases.json"

STATUSES = {"classified", "warned", "refused", "bad_input"}
RECOMMENDATIONS = {
    "continue",
    "ask_user",
    "route_to_amend",
    "route_to_audit_plan",
    "route_to_execute",
    "choose_new_slug",
}
CONFIDENCES = {"high", "medium", "low"}
ROUTE_CHAIN_EFFECTS = {"none", "write_route_decision"}
ALLOWED_ACTIONS_BY_CLASS = {
    "exact_slug_finished_plan": {"ask_user_route"},
    "exact_slug_precontext": {"continue_with_precontext"},
    "active_same_slug": {"warning_only"},
    "active_path_overlap": {"warning_or_existing_strict_overlap"},
    "held_paths_overlap": {"warning_or_existing_strict_overlap"},
    "worktree_branch_overlap": {"warning_only"},
    "historical_similar": {"warning_only", "ask_user_route"},
}
STABLE_REASON_CODES = {
    "exact_slug_finished_plan",
    "exact_slug_precontext",
    "active_same_slug",
    "active_path_overlap",
    "held_paths_overlap",
    "worktree_branch_overlap",
    "historical_similar",
    "low_confidence_similar",
    "inventory_partial",
    "inventory_truncated",
    "unknown_sources_present",
    "no_match_within_caps",
    "inventory_missing",
    "route_loop_risk",
    "bad_input",
}
REQUIRED_CASES = {
    "exact_finished_plan_ask_user",
    "exact_precontext_continue",
    "active_same_slug_warning",
    "held_paths_overlap_warning_or_strict",
    "worktree_branch_overlap_warning",
    "historical_similar_warning_only",
    "partial_inventory_unknown_no_match",
    "no_match_within_caps_complete_inventory",
}
JSON_FENCE_RE = re.compile(r"^```json\n(.*?)^```$", re.MULTILINE | re.DOTALL)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    cases = _fixture()["cases"]
    return sorted(cases, key=lambda case: case["name"])


def _case_by_name(name: str) -> dict:
    return {case["name"]: case for case in _cases()}[name]


def _parse_scout_output(text: str) -> dict:
    json_fences = list(JSON_FENCE_RE.finditer(text))
    assert len(json_fences) == 1, text
    prefix = text[: json_fences[0].start()]
    payload = json.loads(json_fences[0].group(1))

    headers: dict[str, str] = {}
    for raw in prefix.splitlines():
        if not raw.strip():
            continue
        key, value = raw.split(":", 1)
        headers[key.strip()] = value.strip()

    required = {"STATUS", "ROUTE_RECOMMENDATION", "CONFIDENCE", "REASON_CODES", "REASON"}
    assert required <= set(headers), headers
    reason_codes = [code for code in headers["REASON_CODES"].split(",") if code]

    assert headers["STATUS"] in STATUSES
    assert headers["ROUTE_RECOMMENDATION"] in RECOMMENDATIONS
    assert headers["CONFIDENCE"] in CONFIDENCES
    assert set(reason_codes) <= STABLE_REASON_CODES
    assert len(headers["REASON"]) <= 160
    assert payload["route_chain_effect"] in ROUTE_CHAIN_EFFECTS
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["unknown_sources"], list)

    for finding in payload["findings"]:
        assert finding["class"] in ALLOWED_ACTIONS_BY_CLASS
        assert finding["confidence"] in CONFIDENCES
        assert finding["allowed_action"] in ALLOWED_ACTIONS_BY_CLASS[finding["class"]]
        assert finding["evidence"]

    return {
        "status": headers["STATUS"],
        "route_recommendation": headers["ROUTE_RECOMMENDATION"],
        "confidence": headers["CONFIDENCE"],
        "reason_codes": reason_codes,
        "reason": headers["REASON"],
        "json": payload,
    }


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_route_semantics_smoke_fixtures_parse_and_match_expectations(case: dict) -> None:
    inventory = case["inventory"]
    expected = case["expected"]
    parsed = _parse_scout_output(case["scout_output"])

    assert inventory["schema_version"] == "artifact-scout-inventory.v1"
    assert inventory["signals"]["unknown_due_to_partial_sources"] == any(
        status not in {"ok", "missing"} for status in inventory["source_status"].values()
    )
    assert parsed["status"] == expected["status"]
    assert parsed["route_recommendation"] == expected["route_recommendation"]
    assert parsed["confidence"] == expected["confidence"]
    assert parsed["reason_codes"] == expected["reason_codes"]
    assert parsed["json"]["route_chain_effect"] == expected["route_chain_effect"]
    assert parsed["json"]["unknown_sources"] == expected["unknown_sources"]

    actual_findings = [
        {"class": finding["class"], "allowed_action": finding["allowed_action"]}
        for finding in parsed["json"]["findings"]
    ]
    assert actual_findings == expected["findings"]


def test_required_end_to_end_smoke_fixture_set_is_present() -> None:
    names = {case["name"] for case in _cases()}

    assert REQUIRED_CASES <= names


def test_allowed_action_matrix_from_spec_is_exercised_without_extra_actions() -> None:
    seen: dict[str, set[str]] = {match_class: set() for match_class in ALLOWED_ACTIONS_BY_CLASS}
    for case in _cases():
        parsed = _parse_scout_output(case["scout_output"])
        for finding in parsed["json"]["findings"]:
            match_class = finding["class"]
            allowed_action = finding["allowed_action"]
            assert allowed_action in ALLOWED_ACTIONS_BY_CLASS[match_class]
            seen[match_class].add(allowed_action)

    assert seen["exact_slug_finished_plan"] == {"ask_user_route"}
    assert seen["exact_slug_precontext"] == {"continue_with_precontext"}
    assert seen["active_same_slug"] == {"warning_only"}
    assert seen["active_path_overlap"] == {"warning_or_existing_strict_overlap"}
    assert seen["held_paths_overlap"] == {"warning_or_existing_strict_overlap"}
    assert seen["worktree_branch_overlap"] == {"warning_only"}
    assert seen["historical_similar"] == {"warning_only"}


def test_exact_finished_plan_without_intent_is_an_ask_user_route() -> None:
    case = _case_by_name("exact_finished_plan_ask_user")
    parsed = _parse_scout_output(case["scout_output"])
    finding = parsed["json"]["findings"][0]

    assert case["inventory"]["signals"]["exact_slug_finished_plan"] is True
    assert parsed["status"] == "classified"
    assert parsed["route_recommendation"] == "ask_user"
    assert parsed["json"]["route_chain_effect"] == "write_route_decision"
    assert finding["class"] == "exact_slug_finished_plan"
    assert finding["allowed_action"] == "ask_user_route"


def test_historical_similar_is_warning_only_and_never_existing_plan() -> None:
    case = _case_by_name("historical_similar_warning_only")
    parsed = _parse_scout_output(case["scout_output"])
    signals = case["inventory"]["signals"]
    finding = parsed["json"]["findings"][0]

    assert signals["historical_similar_count"] == 1
    assert signals["exact_slug_finished_plan"] is False
    assert parsed["status"] == "warned"
    assert parsed["route_recommendation"] == "continue"
    assert parsed["json"]["route_chain_effect"] == "none"
    assert finding["class"] == "historical_similar"
    assert finding["allowed_action"] == "warning_only"


def test_partial_and_truncated_inventory_are_unknown_not_negative_evidence() -> None:
    partial = _case_by_name("partial_inventory_unknown_no_match")
    no_match = _case_by_name("no_match_within_caps_complete_inventory")
    partial_parsed = _parse_scout_output(partial["scout_output"])
    no_match_parsed = _parse_scout_output(no_match["scout_output"])

    assert partial["inventory"]["truncated"] is True
    assert partial["inventory"]["signals"]["unknown_due_to_partial_sources"] is True
    assert partial_parsed["confidence"] == "low"
    assert partial_parsed["route_recommendation"] == "continue"
    assert partial_parsed["json"]["findings"] == []
    assert {
        "no_match_within_caps",
        "inventory_partial",
        "inventory_truncated",
        "unknown_sources_present",
    } == set(partial_parsed["reason_codes"])
    assert partial_parsed["json"]["unknown_sources"] == ["plans", "registry"]

    assert no_match["inventory"]["truncated"] is False
    assert no_match["inventory"]["signals"]["unknown_due_to_partial_sources"] is False
    assert no_match_parsed["reason_codes"] == ["no_match_within_caps"]
    assert no_match_parsed["confidence"] in {"high", "medium"}
    assert no_match_parsed["json"]["unknown_sources"] == []
