"""Tests for the Hermes `so` MCP tmux orchestrator."""

from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias, HermesConfig  # noqa: E402
from hermes.mcp_hermes_orchestrator import (  # noqa: E402
    SoMcpError,
    SoSessionStore,
    SoSignalStore,
    SoStartRequest,
    drain_signal_events,
    authorize_so_start,
    build_initial_prompt,
    navigate_so_session,
    read_so_session,
    poll_so_sessions,
    reap_so_sessions,
    send_to_so_session,
    start_so_session,
    tmux_session_name,
)


@pytest.fixture(autouse=True)
def _no_spawn_sleep(monkeypatch):
    """Neutralise the spawn settle/readiness sleeps so tests stay fast."""
    monkeypatch.setattr(
        "hermes.mcp_hermes_orchestrator._sleep", lambda *_a, **_k: None
    )


class FakeRunner:
    def __init__(self, fail_on=None, capture="Proceed?"):
        self.fail_on = fail_on or set()
        self.capture = capture
        self.calls = []

    def run(self, argv, *, cwd=None, env=None, timeout=None):
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "env": dict(env or {}),
                "timeout": timeout,
            }
        )
        text = " ".join(argv)
        if any(token in text for token in self.fail_on):
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        stdout = self.capture if "capture-pane" in text else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")


def _config(tmp_path, *, transport="local"):
    cfg = HermesConfig()
    cfg.paths.hermes_state_root = str(tmp_path)
    alias = DiscordProjectAlias(
        repo_root="ssh://zeke-pc/home/zeke/dev/qt-bot",
        execution_host="zeke-pc" if transport == "ssh" else "local",
        transport=transport,
        ssh_target="zeke-pc" if transport == "ssh" else "",
        workdir=(
            "/home/zeke/dev/qt-bot" if transport == "ssh" else str(tmp_path)
        ),
    )
    cfg.discord.so.project_aliases["qt-bot"] = alias
    return cfg, alias


def _command(alias):
    return SoStartRequest(
        host="omp",
        project="qt-bot",
        project_alias=alias,
        task="fix blah",
        z_command="z-debug",
        requester_user_id="user-1",
        discord_channel_id="chan-1",
        discord_message_id="msg-1",
        discord_thread_id="thread-1",
    )


def test_start_session_creates_tmux_and_sends_initial_prompt(tmp_path):
    cfg, alias = _config(tmp_path)
    runner = FakeRunner()
    record = start_so_session(
        _command(alias), cfg, runner=runner, session_id="so-test"
    )

    assert record.session_id == "so-test"
    assert record.status == "running"
    assert runner.calls[0]["argv"][:3] == ["tmux", "new-session", "-d"]
    # Readiness poll before typing, so the booting TUI has painted a frame.
    assert runner.calls[1]["argv"][:2] == ["tmux", "capture-pane"]
    # Prompt is typed literally (-l), then Enter is a SEPARATE keystroke so the
    # composer's bracketed-paste doesn't swallow the submit.
    submit = runner.calls[2]["argv"]
    assert submit[:3] == ["tmux", "send-keys", "-t"]
    assert submit[4] == "-l"
    prompt = submit[5]
    assert "fix blah" in prompt
    assert "z-debug" in prompt
    assert runner.calls[3]["argv"][:2] == ["tmux", "send-keys"]
    assert runner.calls[3]["argv"][-1] == "Enter"
    assert SoSessionStore.from_config(cfg).get("so-test").tmux_session


def test_ssh_transport_runs_tmux_on_recorded_host(tmp_path):
    cfg, alias = _config(tmp_path, transport="ssh")
    runner = FakeRunner()

    start_so_session(_command(alias), cfg, runner=runner, session_id="so-test")

    assert runner.calls[0]["argv"][:2] == ["ssh", "zeke-pc"]
    remote = runner.calls[0]["argv"][2]
    assert "cd /home/zeke/dev/qt-bot" in remote
    assert "HERMES_SO_SESSION_ID=so-test" in remote
    assert "tmux new-session" in remote


def test_send_uses_existing_tmux_session(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )
    runner = FakeRunner()

    record = send_to_so_session("so-test", "continue", cfg, runner=runner)

    assert record.turn_count == 2
    assert runner.calls[0]["argv"] == [
        "tmux",
        "send-keys",
        "-t",
        tmux_session_name("so-test"),
        "continue",
        "C-m",
    ]


def test_read_captures_on_demand_and_sets_needs_input(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    record = read_so_session(
        "so-test", cfg, runner=FakeRunner(capture="Proceed?\n❯")
    )

    assert record.status == "needs_input"
    assert record.last_output == "Proceed?\n❯"

    events = drain_signal_events(cfg)
    assert events[0]["event"] == "so_needs_input"
    assert events[0]["session_id"] == "so-test"
    assert events[0]["discord_thread_id"] == "thread-1"


def test_read_detects_omp_selection_menu(tmp_path):
    # omp Accept/Defer/Reject-style menus end in a navigation footer (below a
    # separator rule), NOT a prompt char — these must still read as needs_input.
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )
    menu = (
        "│ Defer                                              │\n"
        "│    Keep it in the retro, no edits now.             │\n"
        "│ Reject                                             │\n"
        "│  Other (type your own)                             │\n"
        "──────────────────────────────────────────────────────\n"
        " up/down navigate  enter select  esc cancel\n"
        "──────────────────────────────────────────────────────"
    )
    record = read_so_session("so-test", cfg, runner=FakeRunner(capture=menu))

    assert record.status == "needs_input"
    events = drain_signal_events(cfg)
    assert events[0]["event"] == "so_needs_input"
    assert events[0]["session_id"] == "so-test"
    assert events[0]["options"] == ["Defer", "Reject"]


def test_read_bare_prompt_signal_has_empty_options(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    read_so_session("so-test", cfg, runner=FakeRunner(capture="Proceed?\n❯"))

    events = drain_signal_events(cfg)
    assert events[0]["options"] == []


def test_navigate_sends_down_then_enter_for_option_index(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )
    menu = (
        "│ Accept                                             │\n"
        "│ Defer                                              │\n"
        "│ Reject                                             │\n"
        "──────────────────────────────────────────────────────\n"
        " up/down navigate  enter select  esc cancel\n"
        "──────────────────────────────────────────────────────"
    )
    runner = FakeRunner(capture=menu)

    record = navigate_so_session("so-test", 2, cfg, runner=runner)

    assert runner.calls[0]["argv"][:2] == ["tmux", "capture-pane"]
    tmux = tmux_session_name("so-test")
    assert runner.calls[1]["argv"] == ["tmux", "send-keys", "-t", tmux, "Down"]
    assert runner.calls[2]["argv"] == ["tmux", "send-keys", "-t", tmux, "Down"]
    assert runner.calls[3]["argv"] == ["tmux", "send-keys", "-t", tmux, "Enter"]
    assert len(runner.calls) == 4
    assert record.session_id == "so-test"


def test_navigate_no_op_when_pane_is_not_a_menu(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )
    runner = FakeRunner(capture="just running, no menu\n❯")

    navigate_so_session("so-test", 0, cfg, runner=runner)

    assert runner.calls[0]["argv"][:2] == ["tmux", "capture-pane"]
    assert len(runner.calls) == 1
    sent = [call["argv"] for call in runner.calls if "send-keys" in call["argv"]]
    assert sent == []


def test_extract_needs_input_context_cleans_menu():
    from hermes.mcp_hermes_orchestrator import _extract_needs_input_context

    pane = (
        " Proposal 1: add structured degraded-consult provenance. Decision?\n"
        "\n"
        "────────────────────────────────────────────────────────────────\n"
        "│ Accept (Recommended)                                          │\n"
        "│    Apply edits to the agent instructions now.                 │\n"
        "│ Defer                                                         │\n"
        "│    Keep it in the retro, no edits now.                        │\n"
        "────────────────────────────────────────────────────────────────\n"
        " up/down navigate  enter select  esc cancel\n"
        "────────────────────────────────────────────────────────────────"
    )
    out = _extract_needs_input_context(pane)

    # Question survives; box-drawing rules and nav footer are stripped.
    assert "Proposal 1: add structured degraded-consult provenance. Decision?" in out
    assert "Accept (Recommended)" in out
    assert "Apply edits to the agent instructions now." in out
    assert "─" not in out
    assert "│" not in out
    assert "enter select" not in out
    assert "esc cancel" not in out


def test_extract_needs_input_context_falls_back_on_unknown_shape():
    from hermes.mcp_hermes_orchestrator import _extract_needs_input_context

    # No box rows, no footer — nothing structured to pull, so keep the raw tail.
    raw = "some freeform prompt asking a question ❯"
    assert _extract_needs_input_context(raw) == raw.strip()


def test_extract_menu_options_returns_ordered_labels():
    from hermes.mcp_hermes_orchestrator import _extract_menu_options

    pane = (
        " Proposal 1: add structured degraded-consult provenance. Decision?\n"
        "\n"
        "────────────────────────────────────────────────────────────────\n"
        "│ Accept (Recommended)                                          │\n"
        "│    Apply edits to the agent instructions now.                 │\n"
        "│ Refine                                                        │\n"
        "│    Ask a follow-up question before deciding.                  │\n"
        "│ Defer                                                         │\n"
        "│    Keep it in the retro, no edits now.                        │\n"
        "│ Reject                                                        │\n"
        "│    Drop the proposal entirely.                                │\n"
        "│ Other (type your own)                                         │\n"
        "────────────────────────────────────────────────────────────────\n"
        " up/down navigate  enter select  esc cancel\n"
        "────────────────────────────────────────────────────────────────"
    )

    assert _extract_menu_options(pane) == [
        "Accept (Recommended)",
        "Refine",
        "Defer",
        "Reject",
        "Other (type your own)",
    ]


def test_extract_menu_options_empty_for_bare_prompt():
    from hermes.mcp_hermes_orchestrator import _extract_menu_options

    assert _extract_menu_options("Proceed?\n❯") == []


def test_drain_tolerates_legacy_signal_without_options_key(tmp_path):
    # Simulate a signal line written before `options` existed: no such key at
    # all. drain() must not choke, and downstream consumers reading via
    # dict.get("options", []) must still get a sane default.
    cfg, _alias = _config(tmp_path)
    store = SoSignalStore.from_config(cfg)
    legacy_event = {
        "event": "so_needs_input",
        "session_id": "so-legacy",
        "job_id": "so-legacy",
        "status": "needs_input",
        "project": "qt-bot",
        "task": None,
        "requester_user_id": "user-1",
        "discord_channel_id": "chan-1",
        "discord_thread_id": "thread-1",
        "text": "Proceed?",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    store.append(legacy_event)

    events = store.drain()

    assert events == [legacy_event]
    assert events[0].get("options", []) == []


def test_read_deduplicates_needs_input_signals(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    read_so_session("so-test", cfg, runner=FakeRunner(capture="Proceed?\n❯"))
    read_so_session("so-test", cfg, runner=FakeRunner(capture="Proceed?\n❯"))

    assert len(drain_signal_events(cfg)) == 1


def test_send_allows_next_needs_input_signal(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    read_so_session("so-test", cfg, runner=FakeRunner(capture="Proceed?\n❯"))
    send_to_so_session("so-test", "continue", cfg, runner=FakeRunner())
    read_so_session("so-test", cfg, runner=FakeRunner(capture="Next?\n❯"))

    events = drain_signal_events(cfg)
    assert [event["event"] for event in events] == [
        "so_needs_input",
        "so_needs_input",
    ]


def test_reaper_marks_missing_tmux_session_dead(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    result = reap_so_sessions(cfg, runner=FakeRunner(fail_on={"has-session"}))

    assert result["dead"] == ["so-test"]
    assert SoSessionStore.from_config(cfg).get("so-test").status == "dead"
    assert drain_signal_events(cfg)[0]["event"] == "so_session_dead"


def test_reaper_expires_sessions_past_ttl(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )
    store = SoSessionStore.from_config(cfg)
    record = store.get("so-test")
    record.expires_at = "2000-01-01T00:00:00+00:00"
    store.save(record)

    result = reap_so_sessions(cfg, runner=FakeRunner())

    assert result["expired"] == ["so-test"]
    assert store.get("so-test").status == "expired"
    assert drain_signal_events(cfg)[0]["event"] == "so_session_expired"


def test_failed_tmux_marks_session_failed(tmp_path):
    cfg, alias = _config(tmp_path)

    with pytest.raises(SoMcpError):
        start_so_session(
            _command(alias),
            cfg,
            runner=FakeRunner(fail_on={"new-session"}),
            session_id="so-test",
        )

    assert SoSessionStore.from_config(cfg).get("so-test").status == "failed"


def test_prompt_names_mcp_managed_tmux(tmp_path):
    _cfg, alias = _config(tmp_path)
    prompt = build_initial_prompt(_command(alias), "so-test")

    assert "MCP-managed tmux session" in prompt
    assert "z-debug" in prompt


def test_start_auth_rejects_unallowed_user_channel_and_host(tmp_path):
    cfg, _alias = _config(tmp_path)
    cfg.discord.so.allowed_user_ids = {"user-1"}
    cfg.discord.so.allowed_channel_ids = {"chan-1"}
    cfg.discord.so.allowed_hosts = {"omp"}

    with pytest.raises(SoMcpError):
        authorize_so_start(
            cfg,
            host="omp",
            requester_user_id="user-2",
            discord_channel_id="chan-1",
        )
    with pytest.raises(SoMcpError):
        authorize_so_start(
            cfg,
            host="omp",
            requester_user_id="user-1",
            discord_channel_id="chan-2",
        )
    with pytest.raises(SoMcpError):
        authorize_so_start(
            cfg,
            host="other",
            requester_user_id="user-1",
            discord_channel_id="chan-1",
        )


def test_poll_so_sessions_reads_active_sessions_and_reaps(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    result = poll_so_sessions(
        cfg,
        runner=FakeRunner(capture="Waiting for input\n❯"),
    )

    assert result["checked"] == ["so-test"]
    assert result["needs_input"] == ["so-test"]
    assert result["errors"] == {}
    assert drain_signal_events(cfg)[0]["event"] == "so_needs_input"


def test_so_reaction_index_maps_known_emojis_and_rejects_others():
    from hermes.discord_relay import _so_reaction_index

    assert _so_reaction_index("1️⃣") == 0
    assert _so_reaction_index("2️⃣") == 1
    assert _so_reaction_index("3️⃣") == 2
    assert _so_reaction_index("4️⃣") == 3
    assert _so_reaction_index("🎉") is None
    assert _so_reaction_index("") is None


def test_render_so_feed_with_three_options():
    from hermes.discord_relay import _render_so_feed

    result = _render_so_feed("s1", "Pick a branch", ["main", "dev", "release"])

    assert result["reaction_emojis"] == ["1️⃣", "2️⃣", "3️⃣"]
    assert result["overflow"] is False
    for label in ("main", "dev", "release"):
        assert label in result["body"]
    assert "1." in result["body"]
    assert "2." in result["body"]
    assert "3." in result["body"]


def test_render_so_feed_with_six_options_overflows_and_caps_reactions():
    from hermes.discord_relay import _render_so_feed

    options = ["one", "two", "three", "four", "five", "six"]
    result = _render_so_feed("s1", "Pick a number", options)

    assert len(result["reaction_emojis"]) == 4
    assert result["overflow"] is True
    for label in options:
        assert label in result["body"]
    assert "reply with the option number" in result["body"]


def test_render_so_feed_with_no_options_is_plain_text():
    from hermes.discord_relay import _render_so_feed

    result = _render_so_feed("s1", "What should I do next?", [])

    assert result["reaction_emojis"] == []
    assert result["overflow"] is False
    assert result["body"] == "What should I do next?"
