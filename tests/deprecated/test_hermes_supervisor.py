"""Deprecated tests for the retired Hermes `so` tmux supervisor.

The supervisor/watchdog backend was replaced by `hermes.so_mcp`; these tests
are kept for reference only and are not part of active verification.
"""

from pathlib import Path
import sys
import pytest

pytest.skip("deprecated so backend reference tests", allow_module_level=True)


SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.so_jobs import SoJobRecord, SoJobRegistry  # noqa: E402
from hermes.supervisor import (  # noqa: E402
    HermesSupervisor,
    LearnedReplyRules,
    mine_reply_candidates,
    prompt_features,
)


class FakeTmux:
    def __init__(self, pane_text):
        self.pane_text = pane_text
        self.captures = []
        self.sent = []
        self.exists = True
        self.alive = True
        self.aborted = []
        self.restarts = []

    def capture_pane(self, job, *, limit=80):
        self.captures.append((job.job_id, limit))
        return self.pane_text

    def send_keys(self, job, text):
        self.sent.append((job.job_id, text))

    def session_exists(self, job):
        return self.exists

    def pid_alive(self, job):
        return self.alive

    def attach_guidance(self, job):
        return f"Attach on {job.execution_host}: tmux attach -t {job.tmux_session}"

    def abort(self, job):
        self.aborted.append(job.job_id)

    def restart(self, job):
        self.restarts.append(job.job_id)
        return "hermes-so-restarted", 5678


class FakeDiscord:
    def __init__(self):
        self.asks = []
        self.checkups = []

    def ask_user(self, *, channel_id, thread_id, requester_user_id, text):
        self.asks.append(
            {
                "channel_id": channel_id,
                "thread_id": thread_id,
                "requester_user_id": requester_user_id,
                "text": text,
            }
        )

    def post_checkup(self, *, channel_id, thread_id, requester_user_id, text):
        self.checkups.append(
            {
                "channel_id": channel_id,
                "thread_id": thread_id,
                "requester_user_id": requester_user_id,
                "text": text,
            }
        )


def _record(job_id="so-test", thread_id="thread-1", **changes) -> SoJobRecord:
    data = dict(
        job_id=job_id,
        discord_channel_id="chan-1",
        discord_message_id="msg-1",
        discord_thread_id=thread_id,
        requester_user_id="user-1",
        host="omp",
        project="qt-bot",
        repo_root="ssh://zeke-pc/qt-bot",
        execution_host="zeke-pc",
        transport="ssh",
        ssh_target="zeke-pc",
        workdir="/home/zeke/dev/qt-bot",
        z_command="z-debug",
        task="fix blah",
        tmux_session="hermes-so-test",
        pid=1234,
    )
    data.update(changes)
    return SoJobRecord(**data)


def _supervisor(tmp_path, pane_text):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record())
    tmux = FakeTmux(pane_text)
    discord = FakeDiscord()
    supervisor = HermesSupervisor(registry=registry, tmux=tmux, discord=discord)
    return supervisor, registry, tmux, discord


def test_prompts_all_initial_categories_without_sending_keys(tmp_path):
    prompts = [
        "/new is required",
        "Read the handoff and continue?",
        "continue?",
        "This may cost money; proceed?",
        "Delete state file?",
        "Enter token credential",
        "Ambiguous choice: A or B?",
    ]
    for idx, pane_text in enumerate(prompts):
        case_dir = tmp_path / str(idx)
        supervisor, _registry, tmux, discord = _supervisor(case_dir, pane_text)

        result = supervisor.inspect_and_ask("so-test")

        assert result.status == "asked"
        assert len(discord.asks) == 1
        assert pane_text in discord.asks[0]["text"]
        assert tmux.sent == []


def test_reply_sends_exact_user_text_and_records_feedback(tmp_path):
    supervisor, registry, tmux, discord = _supervisor(tmp_path, "continue?")
    supervisor.inspect_and_ask("so-test")

    result = supervisor.handle_discord_reply(
        channel_id="chan-1",
        thread_id="thread-1",
        requester_user_id="user-1",
        text="please continue exactly",
    )

    assert result.status == "sent"
    assert tmux.sent == [("so-test", "please continue exactly")]
    updated = registry.get("so-test")
    assert updated.status == "running"
    record = updated.prompt_records[-1]
    assert record["user_answer"] == "please continue exactly"
    assert record["sent_text"] == "please continue exactly"
    assert updated.prompt_records[-1]["outcome"] == "sent_to_tmux"
    assert discord.asks


def test_unrelated_thread_reply_ignored(tmp_path):
    supervisor, _registry, tmux, _discord = _supervisor(tmp_path, "continue?")
    supervisor.inspect_and_ask("so-test")

    result = supervisor.handle_discord_reply(
        channel_id="chan-1",
        thread_id="other-thread",
        requester_user_id="user-1",
        text="continue",
    )

    assert result.status == "ignored"
    assert tmux.sent == []


def test_duplicate_pane_digest_does_not_spam_repeated_asks(tmp_path):
    supervisor, _registry, tmux, discord = _supervisor(tmp_path, "continue?")

    first = supervisor.inspect_and_ask("so-test")
    second = supervisor.inspect_and_ask("so-test")

    assert first.status == "asked"
    assert second.status == "duplicate_prompt"
    assert len(discord.asks) == 1
    assert len(tmux.captures) == 2


def test_prompt_features_record_future_learning_data(tmp_path):
    supervisor, registry, _tmux, _discord = _supervisor(
        tmp_path, "Delete secret token?"
    )
    supervisor.inspect_and_ask("so-test")
    supervisor.handle_discord_reply(
        channel_id="chan-1",
        thread_id="thread-1",
        requester_user_id="user-1",
        text="no",
    )

    features = registry.get("so-test").prompt_records[-1]["prompt_features"]
    assert features["has_destructive_terms"] is True
    assert features["has_credential_terms"] is True

def test_missing_tmux_marks_dead_and_posts_checkup(tmp_path):
    supervisor, registry, tmux, discord = _supervisor(tmp_path, "running")
    tmux.exists = False

    result = supervisor.check_session_health("so-test")

    assert result.status == "dead"
    assert registry.get("so-test").status == "dead"
    assert "attach, abort, or restart" in discord.checkups[0]["text"]


def test_dead_pid_marks_dead(tmp_path):
    supervisor, registry, tmux, _discord = _supervisor(tmp_path, "running")
    tmux.alive = False

    result = supervisor.check_session_health("so-test")

    assert result.status == "dead"
    assert registry.get("so-test").status == "dead"


def test_unchanged_digest_after_watchdog_posts_checkup_once(tmp_path):
    registry = SoJobRegistry(tmp_path)
    digest_text = "same pane"
    from hermes.supervisor import pane_digest
    registry.create(
        _record(
            last_watchdog_event_id="evt-1",
            last_pane_digest=pane_digest(digest_text),
        )
    )
    tmux = FakeTmux(digest_text)
    discord = FakeDiscord()
    supervisor = HermesSupervisor(registry=registry, tmux=tmux, discord=discord)

    first = supervisor.check_session_health("so-test")
    second = supervisor.check_session_health("so-test")

    assert first.status == "stale"
    assert second.status == "already_checkup"
    assert len(discord.checkups) == 1


def test_live_changing_pane_remains_running(tmp_path):
    supervisor, registry, _tmux, discord = _supervisor(tmp_path, "new pane")

    result = supervisor.check_session_health("so-test")

    assert result.status == "running"
    assert registry.get("so-test").status == "running"
    assert discord.checkups == []


def test_attach_abort_restart_are_explicit_actions(tmp_path):
    supervisor, registry, tmux, discord = _supervisor(tmp_path, "running")

    attach = supervisor.handle_checkup_action("so-test", "attach")
    abort = supervisor.handle_checkup_action("so-test", "abort")
    registry.transition("so-test", "stale")
    restart = supervisor.handle_checkup_action("so-test", "restart")

    assert attach.status == "attach_guidance"
    assert "tmux attach" in discord.checkups[0]["text"]
    assert abort.status == "aborted"
    assert tmux.aborted == ["so-test"]
    assert restart.status == "restarted"
    updated = registry.get("so-test")
    assert updated.status == "running"
    assert updated.tmux_session == "hermes-so-restarted"
    assert updated.pid == 5678
    assert tmux.restarts == ["so-test"]

def _feedback(job_id, prompt, answer, outcome="sent_to_tmux"):
    return {
        "prompt_features": prompt_features(prompt),
        "sent_text": answer,
        "user_answer": answer,
        "outcome": outcome,
        "job_context": {"job_id": job_id},
    }


def test_repeated_feedback_produces_candidate_but_no_auto_reply(tmp_path):
    records = [
        _feedback("so-1", "continue?", "continue"),
        _feedback("so-2", "continue?", "continue"),
    ]
    candidates = mine_reply_candidates(records)
    rules = LearnedReplyRules(candidates)
    supervisor, _registry, tmux, _discord = _supervisor(tmp_path, "continue?")

    result = supervisor.apply_promoted_reply("so-test", rules)

    assert len(candidates) == 1
    assert candidates[0].status == "candidate"
    assert result.status == "no_match"
    assert tmux.sent == []


def test_promoted_candidate_can_answer_and_records_source_evidence(tmp_path):
    candidates = mine_reply_candidates(
        [
            _feedback("so-1", "continue?", "continue"),
            _feedback("so-2", "continue?", "continue"),
        ]
    )
    rules = LearnedReplyRules(candidates)
    rules.promote(candidates[0].candidate_id)
    supervisor, registry, tmux, _discord = _supervisor(tmp_path, "continue?")

    result = supervisor.apply_promoted_reply("so-test", rules)

    assert result.status == "auto_replied"
    assert tmux.sent == [("so-test", "continue")]
    record = registry.get("so-test").prompt_records[-1]
    assert record["candidate_id"] == candidates[0].candidate_id
    assert record["source_evidence"] == ["so-1", "so-2"]


def test_revoked_candidate_stops_answering(tmp_path):
    candidates = mine_reply_candidates(
        [
            _feedback("so-1", "continue?", "continue"),
            _feedback("so-2", "continue?", "continue"),
        ]
    )
    rules = LearnedReplyRules(candidates)
    rules.promote(candidates[0].candidate_id)
    rules.revoke(candidates[0].candidate_id)
    supervisor, _registry, tmux, _discord = _supervisor(tmp_path, "continue?")

    result = supervisor.apply_promoted_reply("so-test", rules)

    assert result.status == "no_match"
    assert tmux.sent == []


def test_negative_examples_and_mismatched_prompts_do_not_match(tmp_path):
    candidates = mine_reply_candidates(
        [
            _feedback("so-1", "continue?", "continue"),
            _feedback("so-2", "continue?", "continue", outcome="user_rejected"),
        ]
    )
    assert candidates == []

    candidates = mine_reply_candidates(
        [
            _feedback("so-1", "continue?", "continue"),
            _feedback("so-2", "continue?", "continue"),
        ]
    )
    rules = LearnedReplyRules(candidates)
    rules.promote(candidates[0].candidate_id)
    supervisor, _registry, tmux, _discord = _supervisor(tmp_path, "delete?")

    result = supervisor.apply_promoted_reply("so-test", rules)

    assert result.status == "no_match"
    assert tmux.sent == []
