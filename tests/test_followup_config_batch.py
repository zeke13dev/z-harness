"""
tests/test_followup_config_batch.py — Tests for T012 batch-config and background push.

Covers:
  (a) get_config_batch forks config.py at most once regardless of how many keys are fetched.
  (b) _notion_push_entry uses get_config_batch (one fork) instead of per-key forks.
  (c) _notion_push_entry_bg launches the push via Popen (not subprocess.run) so the
      parent returns without waiting on HTTP backoff.
  (d) followup-reconcile-notion-impl.py fetches constant config ONCE before its loop
      (not once per entry).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# Load followup_common (also triggers sys.modules registration)
followup_common_path = REPO_ROOT / "scripts" / "followup_common.py"
followup_common = _load_module("followup_common", str(followup_common_path))

# Get the canonical module object that was registered in sys.modules
followup_common = sys.modules.get("followup_common") or followup_common

# Load reconcile impl (it imports followup_common at the top)
_reconcile_path = REPO_ROOT / "scripts" / "followup-reconcile-notion-impl.py"
reconcile_impl = _load_module("followup_reconcile_notion_impl", _reconcile_path)


# ── Fixtures ────────────────────────────────────────────────────────────────────

ENTRY_ID = "20260101T000000Z-batch-test-entry"
REMOTE_PAGE_ID = "notion-page-batchtest"


def _make_entry(*, notion_remote_id: str | None = None) -> dict:
    return {
        "id": ENTRY_ID,
        "schema_version": 1,
        "priority": "P2",
        "name": "Batch Test Entry",
        "status": "open",
        "sink": "project",
        "notion_remote_id": notion_remote_id,
        "recommended_command": "/z-do \"batch-test\"",
    }


def _make_push_result(returncode: int, stdout: dict) -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = json.dumps(stdout)
    r.stderr = ""
    return r


# ── (a) get_config_batch: exactly one config.py fork regardless of key count ────

class TestGetConfigBatch(unittest.TestCase):
    """get_config_batch(keys, proj_root) must fork config.py exactly once."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.proj_root = Path(self.tmp)

    def test_batch_forks_config_exactly_once_for_multiple_keys(self) -> None:
        """
        Invariant: fetching N keys via get_config_batch must result in exactly one
        config.py subprocess, not one per key.

        Failure class: if get_config_batch falls back to per-key calls, each key
        forks a separate python3 process — the original M6 perf problem.
        """
        batch_response = {
            "followup.notion_database_id": "db-abc",
            "followup.notion_token_path": "~/.z-harness/secrets.toml",
        }
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(batch_response)

        subprocess_call_count = [0]
        original_run = subprocess.run

        def _counting_run(cmd, *args, **kwargs):
            subprocess_call_count[0] += 1
            return mock_result

        with patch.object(followup_common, "subprocess") as mock_subproc:
            mock_subproc.run.side_effect = _counting_run
            result = followup_common.get_config_batch(
                ["followup.notion_database_id", "followup.notion_token_path"],
                self.proj_root,
            )

        self.assertEqual(
            mock_subproc.run.call_count, 1,
            f"Expected exactly 1 subprocess call for batch fetch, got {mock_subproc.run.call_count}",
        )
        self.assertEqual(result.get("followup.notion_database_id"), "db-abc")
        self.assertEqual(result.get("followup.notion_token_path"), "~/.z-harness/secrets.toml")

    def test_batch_uses_get_batch_subcommand(self) -> None:
        """
        get_config_batch must invoke config.py with 'get-batch', not individual 'get' calls.

        Failure class: using individual 'get' calls defeats the purpose of the batch helper.
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"followup.notion_database_id": "xyz"})

        with patch.object(followup_common, "subprocess") as mock_subproc:
            mock_subproc.run.return_value = mock_result
            followup_common.get_config_batch(
                ["followup.notion_database_id"],
                Path(self.tmp),
            )

        self.assertEqual(mock_subproc.run.call_count, 1)
        cmd = mock_subproc.run.call_args[0][0]
        self.assertIn("get-batch", cmd, f"Expected 'get-batch' subcommand in cmd: {cmd}")

    def test_batch_returns_empty_dict_on_subprocess_error(self) -> None:
        """
        On subprocess failure (OSError), get_config_batch must return {} not raise.
        """
        with patch.object(followup_common, "subprocess") as mock_subproc:
            mock_subproc.run.side_effect = OSError("no python")
            result = followup_common.get_config_batch(
                ["followup.notion_database_id"],
                Path(self.tmp),
            )
        self.assertEqual(result, {})

    def test_batch_returns_empty_dict_on_nonzero_exit(self) -> None:
        """
        On non-zero exit from config.py, get_config_batch must return {}.
        """
        mock_result = MagicMock()
        mock_result.returncode = 3
        mock_result.stdout = ""

        with patch.object(followup_common, "subprocess") as mock_subproc:
            mock_subproc.run.return_value = mock_result
            result = followup_common.get_config_batch(["followup.notion_enabled"], Path(self.tmp))
        self.assertEqual(result, {})


# ── (b) _notion_push_entry uses batch fetch (one fork for both config keys) ────

class TestNotionPushEntryUsesBatchFetch(unittest.TestCase):
    """
    _notion_push_entry must fetch followup.notion_database_id and
    followup.notion_token_path in a single get_config_batch call.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp) / "followups"
        self.sink_root.mkdir(parents=True)
        self.proj_root = Path(self.tmp)

    def test_notion_push_entry_calls_get_config_batch_once(self) -> None:
        """
        Invariant: _notion_push_entry must call get_config_batch exactly once
        (not call _get_config_str twice).

        Failure class: if _notion_push_entry calls _get_config_str per key,
        each key forks a separate config.py — the M6 regression.
        """
        push_result = _make_push_result(0, {"action": "created", "remote_id": REMOTE_PAGE_ID})

        get_batch_call_count = [0]
        original_batch = followup_common.get_config_batch

        def _counting_batch(keys, proj_root):
            get_batch_call_count[0] += 1
            return {
                "followup.notion_database_id": "db-id-123",
                "followup.notion_token_path": "",
            }

        with patch.object(followup_common, "get_config_batch", side_effect=_counting_batch), \
             patch("subprocess.run", return_value=push_result):
            followup_common._notion_push_entry(
                _make_entry(), self.sink_root, self.proj_root
            )

        self.assertEqual(
            get_batch_call_count[0], 1,
            f"Expected 1 get_config_batch call, got {get_batch_call_count[0]}",
        )

    def test_notion_push_entry_does_not_call_get_config_str_directly(self) -> None:
        """
        _notion_push_entry must not call _get_config_str directly for its config reads.
        """
        push_result = _make_push_result(0, {"action": "created", "remote_id": REMOTE_PAGE_ID})

        get_str_call_count = [0]

        def _counting_str(key, proj_root):
            get_str_call_count[0] += 1
            return ""

        batch_result = {
            "followup.notion_database_id": "db-id-xyz",
            "followup.notion_token_path": "",
        }

        with patch.object(followup_common, "_get_config_str", side_effect=_counting_str), \
             patch.object(followup_common, "get_config_batch", return_value=batch_result), \
             patch("subprocess.run", return_value=push_result):
            followup_common._notion_push_entry(
                _make_entry(), self.sink_root, self.proj_root
            )

        self.assertEqual(
            get_str_call_count[0], 0,
            f"_notion_push_entry must not call _get_config_str directly; "
            f"got {get_str_call_count[0]} call(s)",
        )


# ── (c) _notion_push_entry_bg uses Popen — parent does not block on backoff ────

class TestNotionPushEntryBackground(unittest.TestCase):
    """
    _notion_push_entry_bg must launch the push via Popen (detached), not subprocess.run.
    The parent must return immediately without waiting for the child.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp) / "followups"
        self.sink_root.mkdir(parents=True)
        self.proj_root = Path(self.tmp)

    def test_bg_uses_popen_not_run(self) -> None:
        """
        Invariant: _notion_push_entry_bg must call subprocess.Popen, not subprocess.run.

        Failure class: if Popen is not used, the parent blocks on the full backoff
        schedule (1+4+16 s) before returning — the M7 regression.
        """
        mock_popen = MagicMock()
        mock_popen.return_value = MagicMock()

        with patch.object(followup_common, "subprocess") as mock_subproc:
            mock_subproc.Popen = mock_popen
            mock_subproc.DEVNULL = subprocess.DEVNULL
            followup_common._notion_push_entry_bg(
                _make_entry(), self.sink_root, self.proj_root
            )

        self.assertTrue(
            mock_popen.called,
            "_notion_push_entry_bg must call subprocess.Popen to detach the push",
        )

    def test_bg_does_not_call_subprocess_run(self) -> None:
        """
        _notion_push_entry_bg must not call subprocess.run (which would block).
        """
        with patch.object(followup_common, "subprocess") as mock_subproc:
            mock_subproc.Popen.return_value = MagicMock()
            mock_subproc.DEVNULL = subprocess.DEVNULL
            followup_common._notion_push_entry_bg(
                _make_entry(), self.sink_root, self.proj_root
            )

        self.assertEqual(
            mock_subproc.run.call_count, 0,
            "_notion_push_entry_bg must not call subprocess.run (that blocks the parent)",
        )

    def test_bg_uses_start_new_session(self) -> None:
        """
        The Popen call must use start_new_session=True to fully detach the child.
        """
        popen_kwargs: dict = {}

        def _capture_popen(cmd, **kwargs):
            popen_kwargs.update(kwargs)
            return MagicMock()

        with patch.object(followup_common, "subprocess") as mock_subproc:
            mock_subproc.Popen.side_effect = _capture_popen
            mock_subproc.DEVNULL = subprocess.DEVNULL
            followup_common._notion_push_entry_bg(
                _make_entry(), self.sink_root, self.proj_root
            )

        self.assertTrue(
            popen_kwargs.get("start_new_session"),
            "Popen must use start_new_session=True to detach the child process",
        )

    def test_bg_does_not_raise_on_popen_failure(self) -> None:
        """
        If Popen raises OSError (e.g. python3 not found), _notion_push_entry_bg
        must not propagate the exception — the caller must always return promptly.
        """
        with patch.object(followup_common, "subprocess") as mock_subproc:
            mock_subproc.Popen.side_effect = OSError("exec failed")
            mock_subproc.DEVNULL = subprocess.DEVNULL
            try:
                followup_common._notion_push_entry_bg(
                    _make_entry(), self.sink_root, self.proj_root
                )
            except Exception as exc:
                self.fail(
                    f"_notion_push_entry_bg raised on Popen failure: {exc}"
                )


# ── (d) reconcile-notion fetches config ONCE before the loop ────────────────────

class TestReconcileConfigFetchedOnceBeforeLoop(unittest.TestCase):
    """
    followup-reconcile-notion-impl.py must call get_config_batch once before the
    sweep loop, not once per pending entry.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp)
        self.proj_root = Path(self.tmp)

    def _write_journal(self, events: list[dict]) -> None:
        journal = self.sink_root / "index.jsonl"
        with journal.open("a") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def _write_view(self, entries: dict) -> None:
        view_path = self.sink_root / "index.view.json"
        view_path.write_text(json.dumps({"entries": entries}))

    def test_config_fetched_once_for_multiple_pending_entries(self) -> None:
        """
        Invariant: with N pending entries, config.py is forked exactly once
        (via get_config_batch), not N times.

        Failure class: if config is fetched per-iteration, each entry forks a
        separate python3 process — the M7 reconciler-loop regression.
        """
        # Set up three distinct pending entries
        entry_ids = [
            "20260101T000001Z-entry-a",
            "20260101T000002Z-entry-b",
            "20260101T000003Z-entry-c",
        ]
        entries = {}
        for eid in entry_ids:
            entries[eid] = {
                "id": eid, "schema_version": 1, "priority": "P2",
                "name": f"Entry {eid}", "status": "open", "sink": "project",
                "notion_remote_id": None, "recommended_command": "/z-do \"test\"",
            }
            self._write_journal([
                {"kind": "notion_sync_pending", "entry_id": eid, "notion_sync_pending": True, "ts": "t1"},
            ])
        self._write_view(entries)

        push_result = MagicMock()
        push_result.returncode = 0
        push_result.stdout = json.dumps({"action": "created", "remote_id": "rmt-id", "attempts": 1})

        get_batch_call_count = [0]

        def _counting_batch(keys, proj_root):
            get_batch_call_count[0] += 1
            return {
                "followup.notion_database_id": "db-test",
                "followup.notion_token_path": "",
            }

        with patch.object(followup_common, "get_config_batch", side_effect=_counting_batch), \
             patch("subprocess.run", return_value=push_result):
            # Use the new signature: pass config values explicitly
            reconcile_impl._sweep_sink(
                self.sink_root, self.proj_root,
                config_database_id="db-test",
                config_token_path="",
            )

        # get_config_batch should NOT have been called inside _sweep_sink at all;
        # the caller (main()) is responsible for the single batch call.
        # This test verifies _sweep_sink does NOT call get_config_batch internally.
        self.assertEqual(
            get_batch_call_count[0], 0,
            "_sweep_sink must not call get_config_batch internally — "
            "config is passed as explicit parameters so main() fetches it once",
        )

    def test_main_calls_get_config_batch_once_regardless_of_sink_count(self) -> None:
        """
        main() must call get_config_batch exactly once total, even when sweeping
        both project and global sinks.

        Failure class: if main() fetches config per sink, it forks config.py twice.
        """
        import io
        import contextlib

        project_sink = Path(self.tmp) / "project"
        global_sink = Path(self.tmp) / "global"
        project_sink.mkdir()
        global_sink.mkdir()

        get_batch_call_count = [0]

        def _counting_batch(keys, proj_root):
            get_batch_call_count[0] += 1
            return {
                "followup.notion_database_id": "",
                "followup.notion_token_path": "",
            }

        out_capture = io.StringIO()

        # Patch get_config_batch at the point where reconcile_impl uses it
        # (it imported the name directly via `from followup_common import get_config_batch`)
        with patch.object(reconcile_impl, "get_config_batch", side_effect=_counting_batch), \
             patch.object(reconcile_impl, "_find_project_root", return_value=Path(self.tmp)):
            with contextlib.redirect_stdout(out_capture):
                reconcile_impl.main([
                    f"--project-sink-root={project_sink}",
                    f"--global-sink-root={global_sink}",
                ])

        self.assertEqual(
            get_batch_call_count[0], 1,
            f"main() must call get_config_batch exactly once; got {get_batch_call_count[0]}",
        )


if __name__ == "__main__":
    unittest.main()
