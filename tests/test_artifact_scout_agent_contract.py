from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.resolve()
AGENT_PATH = REPO_ROOT / "agents" / "artifact-scout.md"

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
MATCH_CLASSES = {
    "exact_slug_finished_plan",
    "exact_slug_precontext",
    "active_same_slug",
    "active_path_overlap",
    "held_paths_overlap",
    "worktree_branch_overlap",
    "historical_similar",
}
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
    # Parser fallback, intentionally host-generated rather than agent-generated.
    "artifact_scout_malformed",
}
REQUIRED_PREFIX_KEYS = (
    "STATUS",
    "ROUTE_RECOMMENDATION",
    "CONFIDENCE",
    "REASON_CODES",
    "REASON",
)
PREFIX_INSIDE_JSON = re.compile(
    r'^\s*"?(STATUS|ROUTE_RECOMMENDATION|CONFIDENCE|REASON_CODES|REASON)"?\s:',
    re.MULTILINE,
)
JSON_FENCE_RE = re.compile(r"^```json\n(.*?)^```$", re.MULTILINE | re.DOTALL)


def _fallback() -> dict:
    return {
        "status": "refused",
        "route_recommendation": "continue",
        "confidence": "low",
        "reason_codes": ["artifact_scout_malformed"],
        "reason": "Malformed artifact-scout output; ignoring route advice.",
        "json": {
            "findings": [],
            "route_chain_effect": "none",
            "unknown_sources": [],
        },
        "malformed": True,
    }


def parse_artifact_scout_output(text: str) -> dict:
    """Reference parser encoded by the agent contract; never calls an LLM."""
    json_fences = list(JSON_FENCE_RE.finditer(text))
    if len(json_fences) != 1:
        return _fallback()

    prefix_text = text[: json_fences[0].start()]
    json_text = json_fences[0].group(1)
    if PREFIX_INSIDE_JSON.search(json_text):
        return _fallback()

    headers: dict[str, str] = {}
    for raw in prefix_text.splitlines():
        if not raw.strip():
            continue
        if ":" not in raw:
            return _fallback()
        key, value = raw.split(":", 1)
        key = key.strip()
        if key in REQUIRED_PREFIX_KEYS:
            headers[key] = value.strip()

    if any(key not in headers for key in REQUIRED_PREFIX_KEYS):
        return _fallback()

    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return _fallback()

    if headers["STATUS"] not in STATUSES:
        return _fallback()
    if headers["ROUTE_RECOMMENDATION"] not in RECOMMENDATIONS:
        return _fallback()
    if headers["CONFIDENCE"] not in CONFIDENCES:
        return _fallback()
    if len(headers["REASON"]) > 160:
        return _fallback()

    reason_codes = [c for c in headers["REASON_CODES"].split(",") if c]
    if not set(reason_codes) <= STABLE_REASON_CODES:
        return _fallback()

    if not isinstance(payload, dict):
        return _fallback()
    if set(payload) < {"findings", "route_chain_effect", "unknown_sources"}:
        return _fallback()
    if payload["route_chain_effect"] not in ROUTE_CHAIN_EFFECTS:
        return _fallback()
    if not isinstance(payload["findings"], list):
        return _fallback()
    if not isinstance(payload["unknown_sources"], list):
        return _fallback()

    if headers["ROUTE_RECOMMENDATION"] == "continue" and payload["route_chain_effect"] != "none":
        return _fallback()
    if payload["route_chain_effect"] == "write_route_decision" and headers["ROUTE_RECOMMENDATION"] == "continue":
        return _fallback()
    if payload["route_chain_effect"] == "write_route_decision" and not payload["findings"]:
        return _fallback()

    for finding in payload["findings"]:
        if not isinstance(finding, dict):
            return _fallback()
        cls = finding.get("class")
        if cls not in MATCH_CLASSES:
            return _fallback()
        if finding.get("confidence") not in CONFIDENCES:
            return _fallback()
        if finding.get("allowed_action") not in ALLOWED_ACTIONS_BY_CLASS[cls]:
            return _fallback()
        if not isinstance(finding.get("evidence"), list) or not finding["evidence"]:
            return _fallback()

    return {
        "status": headers["STATUS"],
        "route_recommendation": headers["ROUTE_RECOMMENDATION"],
        "confidence": headers["CONFIDENCE"],
        "reason_codes": reason_codes,
        "reason": headers["REASON"],
        "json": payload,
        "malformed": False,
    }


def _agent_text() -> str:
    return AGENT_PATH.read_text(encoding="utf-8")


def _example_output(title: str) -> str:
    text = _agent_text()
    marker = f"### Example: {title}"
    start = text.index(marker)
    next_start = text.find("\n### Example:", start + len(marker))
    section = text[start:] if next_start == -1 else text[start:next_start]
    status_start = section.index("STATUS:")
    json_start = section.index("```json", status_start)
    json_end = section.index("\n```", json_start) + len("\n```")
    return section[status_start:json_end] + "\n"


def test_agent_file_exists_and_declares_no_tools_or_filesystem_access() -> None:
    text = _agent_text()
    frontmatter = text.split("---", 2)[1]

    assert "name: artifact-scout" in frontmatter
    assert "model: haiku" in frontmatter
    assert re.search(r"^tools:\s*$", frontmatter, re.MULTILINE), frontmatter
    assert "MUST NOT read files" in text
    assert "MUST NOT read files, browse, run shell commands, call tools, call agents" in text
    assert "do not try to read the path" in text
    assert "classify only inline compact inventory JSON" in text


def test_contract_defines_spec_match_classes_and_allowed_actions() -> None:
    text = _agent_text()
    for cls, actions in ALLOWED_ACTIONS_BY_CLASS.items():
        assert f"`{cls}`" in text
        for action in actions:
            assert f"`{action}`" in text

    for recommendation in RECOMMENDATIONS:
        assert recommendation in text
    for status in STATUSES:
        assert status in text


def test_classified_warned_refused_and_bad_input_examples_parse() -> None:
    classified = parse_artifact_scout_output(
        _example_output("classified exact finished plan with amend intent")
    )
    warned = parse_artifact_scout_output(
        _example_output("warned low-confidence similar plan")
    )
    refused = parse_artifact_scout_output(_example_output("refused missing inline inventory"))
    bad_input = parse_artifact_scout_output(_example_output("bad input malformed inventory"))

    assert classified["malformed"] is False
    assert classified["status"] == "classified"
    assert classified["route_recommendation"] == "route_to_amend"
    assert classified["json"]["route_chain_effect"] == "write_route_decision"
    assert classified["json"]["findings"][0]["class"] == "exact_slug_finished_plan"

    assert warned["malformed"] is False
    assert warned["status"] == "warned"
    assert warned["route_recommendation"] == "continue"
    assert warned["json"]["route_chain_effect"] == "none"

    assert refused["malformed"] is False
    assert refused["status"] == "refused"
    assert refused["json"]["findings"] == []
    assert refused["json"]["unknown_sources"] == ["inventory"]

    assert bad_input["malformed"] is False
    assert bad_input["status"] == "bad_input"
    assert bad_input["confidence"] == "low"
    assert bad_input["json"]["route_chain_effect"] == "none"


def test_malformed_output_falls_back_to_refused_and_never_routes() -> None:
    malformed_cases = [
        "STATUS: classified\nROUTE_RECOMMENDATION: route_to_amend\n",
        """STATUS: classified
ROUTE_RECOMMENDATION: route_to_amend
CONFIDENCE: high
REASON_CODES: exact_slug_finished_plan
REASON: Missing fenced JSON.
{"findings": []}
""",
        """STATUS: classified
ROUTE_RECOMMENDATION: route_to_amend
CONFIDENCE: high
REASON_CODES: exact_slug_finished_plan
REASON: Prefix appears inside JSON.

```json
STATUS: classified
```
""",
        """STATUS: classified
ROUTE_RECOMMENDATION: route_to_amend
CONFIDENCE: high
REASON_CODES: exact_slug_finished_plan
REASON: Broken JSON.

```json
{"findings": [}
```
""",
    ]

    for output in malformed_cases:
        parsed = parse_artifact_scout_output(output)
        assert parsed["malformed"] is True
        assert parsed["status"] == "refused"
        assert parsed["route_recommendation"] == "continue"
        assert parsed["confidence"] == "low"
        assert parsed["reason_codes"] == ["artifact_scout_malformed"]
        assert parsed["json"]["route_chain_effect"] == "none"


def test_low_confidence_similar_is_warning_only_and_does_not_route() -> None:
    parsed = parse_artifact_scout_output(
        _example_output("warned low-confidence similar plan")
    )
    finding = parsed["json"]["findings"][0]

    assert parsed["status"] == "warned"
    assert parsed["confidence"] == "low"
    assert parsed["route_recommendation"] == "continue"
    assert parsed["json"]["route_chain_effect"] == "none"
    assert finding["class"] == "historical_similar"
    assert finding["allowed_action"] == "warning_only"
    assert {"historical_similar", "low_confidence_similar"} <= set(parsed["reason_codes"])
    assert "never sets `has_existing_plan=true`" in _agent_text()


def test_partial_inventory_example_lowers_confidence_and_marks_unknown_sources() -> None:
    parsed = parse_artifact_scout_output(
        _example_output("partial inventory lowers confidence")
    )

    assert parsed["status"] == "classified"
    assert parsed["route_recommendation"] == "continue"
    assert parsed["confidence"] == "low"
    assert "inventory_partial" in parsed["reason_codes"]
    assert "unknown_sources_present" in parsed["reason_codes"]
    assert set(parsed["json"]["unknown_sources"]) == {"registry", "worktrees"}
    assert parsed["json"]["route_chain_effect"] == "none"


def test_unknown_sources_are_not_negative_evidence() -> None:
    text = _agent_text()

    assert "MUST NOT treat missing, partial, corrupt, unavailable, or truncated sources as evidence that no artifact exists" in text
    assert "cap `CONFIDENCE` at `medium`" in text
    assert "use `low`" in text
    assert "No match was found, but registry and worktrees were unavailable" in text
