"""Tests for runtime/watchdog/notify.py (session-watchdog Discord notify module).

Coverage (T006 acceptance, criteria #4/#5/#7):
- ``needs_input_digest``: identical question+options payloads produce the same
  digest; a changed question, a changed option, or a reordered option list all
  produce a different digest (criterion #5's dedup-across-polls requirement);
- ``escalation_action``: below ``nudge_max`` returns ``"nudge"``, at/above
  returns ``"discord_alert"`` (criterion #4), and invalid inputs hard-fail;
- ``format_reconciliation_payload``: one entry per fanout child, with failed
  children flagged and surfaced in ``failed_entries`` (criterion #7);
- ``send_discord_alert`` (and the ``send_*`` helpers built on it): wraps the
  script via subprocess, is best-effort on timeout/launch failure, and never
  invokes a real webhook — every test points ``script_path`` at a fake local
  script (STYLE.md:T-004 — hermetic; no real Discord webhook is ever hit).
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from runtime.watchdog import notify


# ── (a) needs_input_digest ────────────────────────────────────────────────────

def test_identical_payload_produces_same_digest() -> None:
    d1 = notify.needs_input_digest("Pick a branch?", ["main", "feature-x"])
    d2 = notify.needs_input_digest("Pick a branch?", ["main", "feature-x"])
    assert d1 == d2


def test_changed_question_produces_different_digest() -> None:
    d1 = notify.needs_input_digest("Pick a branch?", ["main", "feature-x"])
    d2 = notify.needs_input_digest("Pick a different branch?", ["main", "feature-x"])
    assert d1 != d2


def test_changed_options_produces_different_digest() -> None:
    d1 = notify.needs_input_digest("Pick a branch?", ["main", "feature-x"])
    d2 = notify.needs_input_digest("Pick a branch?", ["main", "feature-y"])
    assert d1 != d2


def test_reordered_options_produces_different_digest() -> None:
    """Option order is part of the choice the human is presented; a reorder
    is a materially different prompt, not a dedup-equivalent one."""
    d1 = notify.needs_input_digest("Pick a branch?", ["main", "feature-x"])
    d2 = notify.needs_input_digest("Pick a branch?", ["feature-x", "main"])
    assert d1 != d2


def test_no_options_still_produces_stable_digest() -> None:
    d1 = notify.needs_input_digest("Continue?")
    d2 = notify.needs_input_digest("Continue?", [])
    assert d1 == d2


def test_digest_is_hex_sha256() -> None:
    digest = notify.needs_input_digest("q", ["a"])
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex


def test_format_needs_input_message_names_session_question_options() -> None:
    title, body = notify.format_needs_input_message(
        "zw-slug-abcd1234", "Pick a branch?", ["main", "feature-x"]
    )
    assert "zw-slug-abcd1234" in title
    assert "Pick a branch?" in body
    assert "main" in body
    assert "feature-x" in body


# ── (b) escalation_action ────────────────────────────────────────────────────

def test_escalation_below_max_returns_nudge() -> None:
    assert notify.escalation_action(0, 2) == "nudge"
    assert notify.escalation_action(1, 2) == "nudge"


def test_escalation_at_max_returns_discord_alert() -> None:
    assert notify.escalation_action(2, 2) == "discord_alert"


def test_escalation_above_max_returns_discord_alert() -> None:
    assert notify.escalation_action(5, 2) == "discord_alert"


def test_escalation_rejects_negative_nudge_count() -> None:
    with pytest.raises(ValueError):
        notify.escalation_action(-1, 2)


def test_escalation_rejects_non_positive_nudge_max() -> None:
    with pytest.raises(ValueError):
        notify.escalation_action(0, 0)


# ── (c) format_reconciliation_payload ────────────────────────────────────────

def _child(session_id: str, tmux_target: str, state: str) -> dict:
    return {"session_id": session_id, "tmux_target": tmux_target, "state": state}


def test_reconciliation_payload_has_one_entry_per_child() -> None:
    children = [
        _child("ws-1", "zw-slug-aaaa1111", "done"),
        _child("ws-2", "zw-slug-bbbb2222", "failed"),
        _child("ws-3", "zw-slug-cccc3333", "orphaned"),
    ]
    payload = notify.format_reconciliation_payload("session-watchdog", children)
    assert payload["root_slug"] == "session-watchdog"
    assert len(payload["entries"]) == 3
    session_ids = {e["session_id"] for e in payload["entries"]}
    assert session_ids == {"ws-1", "ws-2", "ws-3"}


def test_reconciliation_payload_flags_only_failed_children() -> None:
    children = [
        _child("ws-1", "zw-slug-aaaa1111", "done"),
        _child("ws-2", "zw-slug-bbbb2222", "failed"),
    ]
    payload = notify.format_reconciliation_payload("session-watchdog", children)
    entries_by_id = {e["session_id"]: e for e in payload["entries"]}
    assert entries_by_id["ws-1"]["failed"] is False
    assert entries_by_id["ws-2"]["failed"] is True


def test_reconciliation_payload_failed_entries_is_exact_subset() -> None:
    children = [
        _child("ws-1", "zw-slug-aaaa1111", "done"),
        _child("ws-2", "zw-slug-bbbb2222", "failed"),
        _child("ws-3", "zw-slug-cccc3333", "failed"),
    ]
    payload = notify.format_reconciliation_payload("session-watchdog", children)
    failed_ids = {e["session_id"] for e in payload["failed_entries"]}
    assert failed_ids == {"ws-2", "ws-3"}


def test_reconciliation_payload_no_failures_yields_empty_failed_entries() -> None:
    children = [_child("ws-1", "zw-slug-aaaa1111", "done")]
    payload = notify.format_reconciliation_payload("session-watchdog", children)
    assert payload["failed_entries"] == []


def test_format_failed_child_message_names_root_and_child() -> None:
    entry = {"session_id": "ws-2", "tmux_target": "zw-slug-bbbb2222", "state": "failed"}
    title, body = notify.format_failed_child_message("session-watchdog", entry)
    assert "session-watchdog" in title
    assert "ws-2" in body
    assert "zw-slug-bbbb2222" in body


# ── notify-discord.sh wrapper — hermetic fake-script fixtures ────────────────

@pytest.fixture
def fake_notify_script(tmp_path: Path):
    """Return a factory building a fake ``notify-discord.sh`` stand-in that
    records its argv to a sidecar file and exits with a chosen code — no real
    subprocess ever touches the network (STYLE.md:T-004)."""

    def _make(exit_code: int = 0, *, hang: bool = False) -> tuple[Path, Path]:
        script = tmp_path / "fake-notify-discord.sh"
        calls_log = tmp_path / "calls.log"
        if hang:
            body = "#!/usr/bin/env bash\nsleep 30\n"
        else:
            body = (
                "#!/usr/bin/env bash\n"
                f'printf \'%s\\t%s\\n\' "$1" "$2" >> "{calls_log}"\n'
                f"exit {exit_code}\n"
            )
        script.write_text(body)
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script, calls_log

    return _make


def test_send_discord_alert_returns_true_on_success(fake_notify_script) -> None:
    script, calls_log = fake_notify_script(exit_code=0)
    ok = notify.send_discord_alert("hello", "world", script_path=script)
    assert ok is True
    assert calls_log.read_text() == "hello\tworld\n"


def test_send_discord_alert_returns_false_on_script_failure(fake_notify_script) -> None:
    script, _ = fake_notify_script(exit_code=1)
    ok = notify.send_discord_alert("hello", "world", script_path=script)
    assert ok is False


def test_send_discord_alert_returns_false_on_timeout(fake_notify_script) -> None:
    script, _ = fake_notify_script(hang=True)
    ok = notify.send_discord_alert("hello", "world", script_path=script, timeout=0.2)
    assert ok is False


def test_send_discord_alert_returns_false_on_missing_script(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.sh"
    ok = notify.send_discord_alert("hello", "world", script_path=missing, timeout=2.0)
    assert ok is False


def test_send_needs_input_alert_wraps_send_discord_alert(fake_notify_script) -> None:
    script, calls_log = fake_notify_script(exit_code=0)
    ok = notify.send_needs_input_alert(
        "zw-slug-abcd1234", "Pick a branch?", ["main", "feature-x"], script_path=script
    )
    assert ok is True
    title, body = calls_log.read_text().rstrip("\n").split("\t", 1)
    assert "zw-slug-abcd1234" in title
    assert "main" in body


def test_send_reconciliation_alerts_sends_one_per_failed_child(fake_notify_script) -> None:
    script, calls_log = fake_notify_script(exit_code=0)
    children = [
        _child("ws-1", "zw-slug-aaaa1111", "done"),
        _child("ws-2", "zw-slug-bbbb2222", "failed"),
        _child("ws-3", "zw-slug-cccc3333", "failed"),
    ]
    payload = notify.format_reconciliation_payload("session-watchdog", children)
    sent = notify.send_reconciliation_alerts(payload, script_path=script)
    assert sent == 2
    lines = calls_log.read_text().splitlines()
    assert len(lines) == 2


def test_send_reconciliation_alerts_zero_when_no_failures(fake_notify_script) -> None:
    script, calls_log = fake_notify_script(exit_code=0)
    payload = notify.format_reconciliation_payload(
        "session-watchdog", [_child("ws-1", "zw-slug-aaaa1111", "done")]
    )
    sent = notify.send_reconciliation_alerts(payload, script_path=script)
    assert sent == 0
    assert not calls_log.exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
