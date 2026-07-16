from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.resolve()
AGENT_PATH = REPO_ROOT / "agents" / "surgical-fixer.md"

STATUSES = {"success", "ineligible", "malformed", "failed"}
REQUIRED_HEADERS = ("STATUS", "TASK", "ATTEMPTS_USED", "ATTEMPT_LIMIT", "FALLBACK")
OUTPUT_RE = re.compile(
    r"\A"
    r"STATUS: (?P<STATUS>[^\n]+)\n"
    r"TASK: (?P<TASK>[^\n]+)\n"
    r"ATTEMPTS_USED: (?P<ATTEMPTS_USED>[^\n]+)\n"
    r"ATTEMPT_LIMIT: (?P<ATTEMPT_LIMIT>[^\n]+)\n"
    r"FALLBACK: (?P<FALLBACK>[^\n]+)\n"
    r"\n"
    r"```json\n(?P<payload>.*?)\n```\n?\Z",
    re.DOTALL,
)


def _fallback() -> dict:
    return {"malformed": True}


def parse_surgical_fixer_output(text: str) -> dict:
    """Reference parser for the machine-checkable surgical-fixer result."""
    match = OUTPUT_RE.fullmatch(text)
    if match is None:
        return _fallback()

    headers = {header: match.group(header).strip() for header in REQUIRED_HEADERS}

    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return _fallback()

    if headers["STATUS"] not in STATUSES or headers["ATTEMPT_LIMIT"] != "1":
        return _fallback()
    if headers["ATTEMPTS_USED"] not in {"0", "1"}:
        return _fallback()
    if headers["FALLBACK"] not in {"deep_retry", "none"} or not isinstance(payload, dict):
        return _fallback()
    if payload.get("schema_version") != "surgical-fixer-result.v1":
        return _fallback()
    if not isinstance(payload.get("changed_paths"), list) or not isinstance(payload.get("finding_ids"), list):
        return _fallback()
    fallback = payload.get("fallback")
    if not isinstance(fallback, dict) or fallback.get("normal_retry_allowance_consumed") is not False:
        return _fallback()

    status = headers["STATUS"]
    if status == "success":
        if headers["ATTEMPTS_USED"] != "1" or headers["FALLBACK"] != "none":
            return _fallback()
        if fallback != {
            "required": False,
            "reason_code": "none",
            "normal_retry_allowance_consumed": False,
        }:
            return _fallback()
    else:
        expected_attempts = "1" if status == "failed" else "0"
        if headers["ATTEMPTS_USED"] != expected_attempts or headers["FALLBACK"] != "deep_retry":
            return _fallback()
        if fallback.get("required") is not True or fallback.get("reason_code") in {None, "", "none"}:
            return _fallback()
        if payload["changed_paths"]:
            return _fallback()

    return {"malformed": False, "status": status, "headers": headers, "json": payload}


def _agent_text() -> str:
    return AGENT_PATH.read_text(encoding="utf-8")


def _output(status: str, *, attempts: int, fallback: str, changed_paths: list[str]) -> str:
    required = status != "success"
    reason = "none" if status == "success" else "undeclared_path"
    return f'''STATUS: {status}
TASK: T001
ATTEMPTS_USED: {attempts}
ATTEMPT_LIMIT: 1
FALLBACK: {fallback}

```json
{json.dumps({"schema_version": "surgical-fixer-result.v1", "changed_paths": changed_paths, "finding_ids": ["F001"], "fallback": {"required": required, "reason_code": reason, "normal_retry_allowance_consumed": False}})}
```
'''


def test_agent_defines_a_fresh_bounded_path_contract() -> None:
    text = _agent_text()

    assert "name: surgical-fixer" in text.split("---", 2)[1]
    assert "fresh surgical repair agent" in text
    assert "at most two unique repository-relative paths" in text
    assert "at most three entries" in text
    assert "`path` is not exactly one of `declared_task_paths`" in text
    for forbidden in ("decision-needed", "public API", "schema", "dependency", "concurrency", "intent-contract"):
        assert forbidden in text


def test_contract_pins_one_attempt_and_retry_preserving_fallback() -> None:
    text = _agent_text()

    assert "exactly one surgical attempt" in text
    assert "ATTEMPT_LIMIT: 1" in text
    assert "normal_retry_allowance_consumed" in text
    assert "normal retry allowance" in text

    for status, attempts, fallback, changed_paths in (
        ("success", 1, "none", ["path/one.py"]),
        ("ineligible", 0, "deep_retry", []),
        ("malformed", 0, "deep_retry", []),
        ("failed", 1, "deep_retry", []),
    ):
        parsed = parse_surgical_fixer_output(
            _output(status, attempts=attempts, fallback=fallback, changed_paths=changed_paths)
        )
        assert parsed["malformed"] is False
        assert parsed["status"] == status
        assert parsed["json"]["fallback"]["normal_retry_allowance_consumed"] is False


def test_parser_rejects_second_attempt_or_retry_consumption() -> None:
    second_attempt = _output("failed", attempts=1, fallback="deep_retry", changed_paths=[]).replace(
        "ATTEMPT_LIMIT: 1", "ATTEMPT_LIMIT: 2"
    )
    consumed_retry = _output("failed", attempts=1, fallback="deep_retry", changed_paths=[]).replace(
        '"normal_retry_allowance_consumed": false', '"normal_retry_allowance_consumed": true'
    )

    assert parse_surgical_fixer_output(second_attempt)["malformed"] is True
    assert parse_surgical_fixer_output(consumed_retry)["malformed"] is True


def test_parser_requires_fallback_for_all_non_success_results() -> None:
    missing_fallback = _output("ineligible", attempts=0, fallback="none", changed_paths=[])

    assert parse_surgical_fixer_output(missing_fallback)["malformed"] is True


def test_parser_rejects_any_content_outside_the_exact_result_shape() -> None:
    valid = _output("success", attempts=1, fallback="none", changed_paths=["path/one.py"])
    cases = (
        "Explanation\n" + valid,
        valid + "trailing prose\n",
        valid.replace("TASK: T001\n", "TASK: T001\nEXTRA: no\n"),
        valid.replace("TASK: T001\n", "TASK: T001\nTASK: duplicate\n"),
    )

    for output in cases:
        assert parse_surgical_fixer_output(output)["malformed"] is True
