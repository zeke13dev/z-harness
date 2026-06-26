"""Deprecated tests for the retired Hermes `so` job registry.

The tmux/job-registry backend was replaced by `hermes.so_mcp`; these tests are
kept for reference only and are not part of active verification.
"""

from pathlib import Path
import json
import sys
import pytest

pytest.skip("deprecated so backend reference tests", allow_module_level=True)



SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import HermesConfig  # noqa: E402
from hermes.so_jobs import SoJobRecord, SoJobRegistry, registry_dir  # noqa: E402


def _record(job_id: str = "so-test") -> SoJobRecord:
    return SoJobRecord(
        job_id=job_id,
        discord_channel_id="chan-1",
        discord_message_id="msg-1",
        discord_thread_id="thread-1",
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
        z_harness_run_id="run-1",
        slug="demo-slug",
        last_pane_digest="sha256:abc",
        last_progress_at="2026-06-26T00:00:00+00:00",
    )


def test_create_read_update_round_trip(tmp_path):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record())

    loaded = registry.get("so-test")
    assert loaded is not None
    assert loaded.task == "fix blah"
    assert loaded.execution_host == "zeke-pc"

    updated = registry.transition("so-test", "running", pid=4321)
    assert updated.status == "running"
    assert updated.pid == 4321
    assert registry.get("so-test").pid == 4321


def test_atomic_rewrite_leaves_no_tmp_and_replaces_content(tmp_path):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record())

    registry.update("so-test", status="waiting_input")

    assert registry.path_for("so-test").exists()
    assert not list(tmp_path.glob("*.tmp"))
    data = json.loads(registry.path_for("so-test").read_text())
    assert data["status"] == "waiting_input"


def test_lookup_by_run_pid_job_slug_and_discord_ids(tmp_path):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record())

    assert registry.resolve(job_id="so-test").job_id == "so-test"
    assert registry.find_by_run_id("run-1").job_id == "so-test"
    by_pid = registry.find_by_pid(1234, execution_host="zeke-pc")
    assert by_pid.job_id == "so-test"
    assert registry.find_by_pid(1234, execution_host="local") is None
    assert registry.find_by_slug("demo-slug").job_id == "so-test"
    assert registry.find_by_discord_message(
        channel_id="chan-1", message_id="msg-1"
    ).job_id == "so-test"
    assert registry.find_by_discord_thread(
        channel_id="chan-1", thread_id="thread-1"
    ).job_id == "so-test"


def test_malformed_job_files_are_skipped(tmp_path):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record())
    (tmp_path / "broken.json").write_text("not json")
    (tmp_path / "missing.json").write_text(json.dumps({"schema_version": 1}))

    assert [record.job_id for record in registry.list()] == ["so-test"]


def test_duplicate_event_id_persists_and_dedups(tmp_path):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record())

    assert registry.mark_watchdog_event_seen("so-test", "evt-1") is True
    assert registry.get("so-test").last_watchdog_event_id == "evt-1"
    assert registry.mark_watchdog_event_seen("so-test", "evt-1") is False
    assert registry.mark_watchdog_event_seen("so-test", "evt-2") is True
    assert registry.get("so-test").last_watchdog_event_id == "evt-2"


def test_tmux_and_pid_operations_use_recorded_execution_target(tmp_path):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record())
    loaded = registry.get("so-test")

    assert loaded.tmux_target == {
        "execution_host": "zeke-pc",
        "transport": "ssh",
        "ssh_target": "zeke-pc",
        "workdir": "/home/zeke/dev/qt-bot",
        "tmux_session": "hermes-so-test",
    }
    assert loaded.pid_target == {
        "execution_host": "zeke-pc",
        "transport": "ssh",
        "ssh_target": "zeke-pc",
        "pid": 1234,
    }


def test_registry_from_config_uses_hermes_state_root(tmp_path):
    cfg = HermesConfig()
    cfg.paths.hermes_state_root = str(tmp_path / "state")

    registry = SoJobRegistry.from_config(cfg)

    assert registry.root == registry_dir(cfg)
    assert registry.root.name == "so-jobs"
