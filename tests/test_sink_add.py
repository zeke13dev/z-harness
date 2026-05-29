"""
tests/test_sink_add.py — pytest tests for scripts/sink-add.sh + sink-add-helpers.py

Cases covered:
  happy_path           — full valid invocation; entry written to sink, view rebuilt
  dedup_skip           — same name+command+source invoked twice; second returns exit 3
  depth_exceeded       — env Z_HARNESS_FOLLOWUP_CALLER_DEPTH=2, expect exit 4
  diffuse_cited_paths  — cited paths span repo root; expect exit 6
  command_parse_fail   — raw shell `bash -c "..."` in recommended-command; expect exit 2
  lock_timeout         — synthetic lock contention; expect exit 5
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "sink-add.sh")
HELPERS_PY = str(REPO_ROOT / "scripts" / "sink-add-helpers.py")


# ── Git repo helpers ────────────────────────────────────────────────────────────

def _git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _make_git_repo(path: Path) -> str:
    """Initialise a minimal git repo at path. Returns HEAD sha."""
    td = str(path)
    _git("init", cwd=td)
    _git("config", "user.email", "test@test.com", cwd=td)
    _git("config", "user.name", "Test", cwd=td)
    sentinel = path / "sentinel.txt"
    sentinel.write_text("hello\n")
    _git("add", "sentinel.txt", cwd=td)
    _git("commit", "-m", "initial commit", cwd=td)
    result = _git("rev-parse", "HEAD", cwd=td)
    return result.stdout.strip()


# ── subprocess runner ──────────────────────────────────────────────────────────

def _run_sink_add(
    *extra_args: str,
    env_extra: dict | None = None,
    cwd: str | None = None,
    lock_file: str | None = None,
) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    if lock_file:
        env["Z_HARNESS_FOLLOWUP_GLOBAL_LOCK"] = lock_file
    return subprocess.run(
        ["bash", SCRIPT] + list(extra_args),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


# ── lock-holding helper (synthetic contention) ─────────────────────────────────

def _hold_global_lock(lock_file: Path, duration: float) -> None:
    """Hold the global flock sentinel exclusively for `duration` seconds in a thread."""
    sentinel = Path(str(lock_file) + ".flock")
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
    fd = os.open(str(sentinel), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    time.sleep(duration)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


# ── test cases ─────────────────────────────────────────────────────────────────

class TestSinkAddHappyPath(unittest.TestCase):
    """Happy path: valid inputs, entry created, view rebuilt."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        self.head = _make_git_repo(self.tmp)

        # Create source-artifact file
        self.source = self.tmp / "artifact.diff"
        self.source.write_text("diff content\n")

        # Create a cited path
        self.cited = self.tmp / "README.md"
        self.cited.write_text("# readme\n")

        # Use a local lock file so tests don't interfere with system
        self.lock_file = str(self.tmp / ".followup-vs-implement.lock")

    def test_entry_created(self) -> None:
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Fix the badge",
            "--recommended-command=/z-do \"update badge\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            "--prompt-body=Fix the badge by updating URL",
            env_extra={"Z_HARNESS_FOLLOWUP_CALLER_DEPTH": "0"},
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # Check that the sink directory was created
        sink_root = self.tmp / "z-harness" / "followups"
        self.assertTrue(sink_root.exists(), "sink root should be created")

        # Check index.jsonl has an entry_created event
        index_jsonl = sink_root / "index.jsonl"
        self.assertTrue(index_jsonl.exists(), "index.jsonl should be created")
        events = [json.loads(line) for line in index_jsonl.read_text().splitlines() if line.strip()]
        kinds = [e["kind"] for e in events]
        self.assertIn("entry_created", kinds, "index.jsonl should contain entry_created event")

        # Check view was rebuilt
        view_file = sink_root / "index.view.json"
        self.assertTrue(view_file.exists(), "index.view.json should be rebuilt")
        view = json.loads(view_file.read_text())
        entries = view.get("entries", {})
        self.assertEqual(len(entries), 1, "view should have exactly 1 entry")

        entry = list(entries.values())[0]
        self.assertEqual(entry["priority"], "P2")
        self.assertEqual(entry["name"], "Fix the badge")
        self.assertEqual(entry["status"], "open")
        self.assertEqual(entry["sink"], "project")
        self.assertEqual(entry["depth"], 0)
        self.assertFalse(entry["auto_close_eligible"])
        self.assertFalse(entry["recommended_command_safe_to_retry"])

    def test_page_written(self) -> None:
        result = _run_sink_add(
            "--sink=project",
            "--priority=P1",
            "--name=Write tests",
            "--recommended-command=/z-implement-next",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            "--prompt-body=Write more tests",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        pages_dir = self.tmp / "z-harness" / "followups" / "pages"
        pages = list(pages_dir.glob("*.md"))
        self.assertEqual(len(pages), 1, "exactly one page file should be written")
        content = pages[0].read_text()
        self.assertIn("Write more tests", content)

    def test_auto_close_eligible_flag(self) -> None:
        result = _run_sink_add(
            "--sink=project",
            "--priority=P3",
            "--name=Low risk change",
            "--recommended-command=/z-do \"touch CHANGELOG\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            "--auto-close-eligible",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        sink_root = self.tmp / "z-harness" / "followups"
        view = json.loads((sink_root / "index.view.json").read_text())
        entry = list(view["entries"].values())[0]
        self.assertTrue(entry["auto_close_eligible"])

    def test_safe_to_retry_flag(self) -> None:
        result = _run_sink_add(
            "--sink=project",
            "--priority=P3",
            "--name=Retryable task",
            "--recommended-command=/z-do \"update thing\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            "--safe-to-retry",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        sink_root = self.tmp / "z-harness" / "followups"
        view = json.loads((sink_root / "index.view.json").read_text())
        entry = list(view["entries"].values())[0]
        self.assertTrue(entry["recommended_command_safe_to_retry"])


class TestSinkAddDedupSkip(unittest.TestCase):
    """Dedup: same name + command + source artifact → exit 3 on second call."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.source = self.tmp / "artifact.diff"
        self.source.write_text("diff content\n")
        self.cited = self.tmp / "README.md"
        self.cited.write_text("# readme\n")
        self.lock_file = str(self.tmp / ".followup-vs-implement.lock")

    def test_dedup_exits_3(self) -> None:
        common_args = [
            "--sink=project",
            "--priority=P2",
            "--name=Duplicate entry",
            "--recommended-command=/z-do \"dup test\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
        ]
        # First invocation should succeed
        r1 = _run_sink_add(*common_args, cwd=self.tmpdir, lock_file=self.lock_file)
        self.assertEqual(r1.returncode, 0, msg=f"first call failed: {r1.stderr}")

        # Second identical invocation should exit 3
        r2 = _run_sink_add(*common_args, cwd=self.tmpdir, lock_file=self.lock_file)
        self.assertEqual(r2.returncode, 3, msg=f"expected exit 3, got {r2.returncode}: {r2.stderr}")
        self.assertIn("dedup", r2.stderr.lower(), "stderr should mention dedup")

    def test_dedup_across_different_source_artifacts(self) -> None:
        """Same name + command from a DIFFERENT source_artifact → still exits 3 (dedup).

        This covers the double-routing bug (M9): z-implement-next Phase 3.5 passes
        a per-task diff.patch as source_artifact while z-review-all Phase 3.7.5
        passes findings.md.  The same logical follow-up must not be written twice.
        """
        source2 = self.tmp / "findings.md"
        source2.write_text("findings content\n")

        base_args = [
            "--sink=project",
            "--priority=P2",
            "--name=Duplicate cross-source",
            "--recommended-command=/z-do \"cross-source test\"",
            f"--cited-paths={self.cited}",
        ]

        # First invocation: source = diff.patch
        r1 = _run_sink_add(
            *base_args,
            f"--source-artifact={self.source}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(r1.returncode, 0, msg=f"first call failed: {r1.stderr}")

        # Second invocation: DIFFERENT source_artifact (findings.md) → must be deduped
        r2 = _run_sink_add(
            *base_args,
            f"--source-artifact={source2}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(r2.returncode, 3,
                         msg=f"expected exit 3 (dedup-skip), got {r2.returncode}: {r2.stderr}")
        self.assertIn("dedup", r2.stderr.lower(), "stderr should mention dedup")

        # View must contain exactly one entry
        sink_root = self.tmp / "z-harness" / "followups"
        view = json.loads((sink_root / "index.view.json").read_text())
        self.assertEqual(len(view["entries"]), 1,
                         "only one entry should exist despite two different source_artifacts")

    def test_dedup_different_name_not_blocked(self) -> None:
        base_args = [
            "--sink=project",
            "--priority=P2",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
        ]
        r1 = _run_sink_add(
            *base_args,
            "--name=First unique entry",
            "--recommended-command=/z-do \"first\"",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)

        r2 = _run_sink_add(
            *base_args,
            "--name=Second unique entry",
            "--recommended-command=/z-do \"second\"",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(r2.returncode, 0, msg=f"different name should not be deduped: {r2.stderr}")

        sink_root = self.tmp / "z-harness" / "followups"
        view = json.loads((sink_root / "index.view.json").read_text())
        self.assertEqual(len(view["entries"]), 2, "both entries should be in view")


class TestSinkAddDepthExceeded(unittest.TestCase):
    """depth_exceeded: caller_depth > 1 → exit 4."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.source = self.tmp / "artifact.diff"
        self.source.write_text("diff content\n")
        self.cited = self.tmp / "README.md"
        self.cited.write_text("# readme\n")
        self.lock_file = str(self.tmp / ".followup-vs-implement.lock")

    def test_depth_2_rejected(self) -> None:
        """Z_HARNESS_FOLLOWUP_CALLER_DEPTH=2 must cause exit 4."""
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Deep entry",
            "--recommended-command=/z-do \"deep\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            env_extra={"Z_HARNESS_FOLLOWUP_CALLER_DEPTH": "2"},
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 4, msg=f"expected exit 4, got {result.returncode}: {result.stderr}")
        self.assertIn("depth", result.stderr.lower(), "stderr should mention depth")

    def test_depth_1_allowed(self) -> None:
        """Z_HARNESS_FOLLOWUP_CALLER_DEPTH=1 must be accepted (new_entry_depth=1 == MAX_DEPTH)."""
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Depth 1 entry",
            "--recommended-command=/z-do \"depth1\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            env_extra={"Z_HARNESS_FOLLOWUP_CALLER_DEPTH": "1"},
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 0, msg=f"depth=1 should be allowed: {result.stderr}")

    def test_depth_0_default_allowed(self) -> None:
        """No env var (default 0) must be accepted."""
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Default depth entry",
            "--recommended-command=/z-do \"default\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 0, msg=f"default depth should be allowed: {result.stderr}")


class TestSinkAddDiffuseCitedPaths(unittest.TestCase):
    """diffuse_cited_paths: common ancestor at repo root depth → exit 6."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.source = self.tmp / "artifact.diff"
        self.source.write_text("diff content\n")

        # Create cited paths that span the repo root (shallow common ancestor)
        self.file_a = self.tmp / "README.md"
        self.file_a.write_text("readme\n")
        self.file_b = self.tmp / "Makefile"
        self.file_b.write_text("make\n")

        self.lock_file = str(self.tmp / ".followup-vs-implement.lock")

    def test_diffuse_paths_rejected(self) -> None:
        """Paths with common ancestor at repo root depth < 2 must exit 6."""
        # Create more than 16 files that all share repo root as common ancestor
        # Use files spread across the top-level so commonpath = repo root

        # Create 17 files in different subdirs to trigger the >16 path cap
        # and force the common ancestor check
        dirs = []
        paths = []
        for i in range(17):
            d = self.tmp / f"subdir{i}"
            d.mkdir(exist_ok=True)
            f = d / f"file{i}.txt"
            f.write_text(f"content {i}\n")
            paths.append(str(f))
            dirs.append(str(d))

        cited_csv = ",".join(paths)
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Diffuse entry",
            "--recommended-command=/z-do \"diffuse\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={cited_csv}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 6, msg=f"expected exit 6, got {result.returncode}: {result.stderr}")

    def test_deep_common_ancestor_allowed(self) -> None:
        """Paths with common ancestor at depth >= 2 must NOT exit 6 (even if >16 files)."""
        # Create 17 files under a single deep subdir (depth >= 2 from repo root)
        deep_dir = self.tmp / "level1" / "level2"
        deep_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(17):
            f = deep_dir / f"file{i}.txt"
            f.write_text(f"content {i}\n")
            paths.append(str(f))

        cited_csv = ",".join(paths)
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Deep dir entry",
            "--recommended-command=/z-do \"deep-dir\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={cited_csv}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        # Should succeed (exit 0) because ancestor is at depth >= 2
        self.assertEqual(result.returncode, 0, msg=f"deep ancestor should be accepted: {result.stderr}")


class TestSinkAddCommandParseFail(unittest.TestCase):
    """command_parse_fail: raw shell `bash -c "..."` must fail with exit 2."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.source = self.tmp / "artifact.diff"
        self.source.write_text("diff content\n")
        self.cited = self.tmp / "README.md"
        self.cited.write_text("readme\n")
        self.lock_file = str(self.tmp / ".followup-vs-implement.lock")

    def test_raw_shell_rejected(self) -> None:
        """bash -c "..." doesn't start with /z- → exit 2."""
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Raw shell entry",
            '--recommended-command=bash -c "rm -rf /"',
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 2, msg=f"expected exit 2, got {result.returncode}: {result.stderr}")

    def test_command_with_unquoted_pipe_rejected(self) -> None:
        """Command arg containing unquoted | must fail (rule 6)."""
        # The pipe is inside an unquoted argument token
        # /z-do foo | bar  → shlex.split gives ['/z-do', 'foo', '|', 'bar']
        # 'foo' is fine but '|' is a metachar by itself
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Pipe entry",
            "--recommended-command=/z-do foo | bar",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 2, msg=f"expected exit 2 for unquoted pipe, got {result.returncode}: {result.stderr}")

    def test_valid_command_with_quoted_args_accepted(self) -> None:
        """/z-do with a properly quoted argument must succeed."""
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Quoted args entry",
            '--recommended-command=/z-do "update README badge"',
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 0, msg=f"quoted args should be accepted: {result.stderr}")

    def test_missing_slash_z_prefix_rejected(self) -> None:
        """Command not starting with /z- must fail validation."""
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=No prefix entry",
            "--recommended-command=implement-next",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 2, msg=f"expected exit 2, got {result.returncode}: {result.stderr}")

    def test_pipe_inside_double_quotes_accepted(self) -> None:
        """/z-do "fix a | b" — pipe inside double quotes must NOT be rejected (rule 6)."""
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Quoted pipe entry",
            '--recommended-command=/z-do "fix a | b"',
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"pipe inside double quotes should be accepted: {result.stderr}",
        )

    def test_pipe_inside_single_quotes_accepted(self) -> None:
        """/z-do 'fix a | b' — pipe inside single quotes must NOT be rejected (rule 6)."""
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Single quoted pipe entry",
            "--recommended-command=/z-do 'fix a | b'",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"pipe inside single quotes should be accepted: {result.stderr}",
        )


class TestSinkAddLockTimeout(unittest.TestCase):
    """lock_timeout: synthetic lock held by another process → exit 5."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.source = self.tmp / "artifact.diff"
        self.source.write_text("diff content\n")
        self.cited = self.tmp / "README.md"
        self.cited.write_text("readme\n")
        self.lock_file = str(self.tmp / ".followup-vs-implement.lock")

    def test_lock_timeout_exits_5(self) -> None:
        """Hold the lock externally for longer than the timeout, expect exit 5."""
        lock_path = Path(self.lock_file)

        # Hold the lock for 3s; use 1s timeout via env var so the test is fast.
        holder = threading.Thread(
            target=_hold_global_lock,
            args=(lock_path, 3.0),
            daemon=True,
        )
        holder.start()
        # Give the holder time to acquire the lock before we try
        time.sleep(0.3)

        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Lock timeout test",
            '--recommended-command=/z-do "lock test"',
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            env_extra={
                "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK": self.lock_file,
                # Override timeout to 1s so the test completes quickly
                "Z_HARNESS_FOLLOWUP_LOCK_TIMEOUT": "1",
            },
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )

        self.assertEqual(result.returncode, 5, msg=f"expected exit 5 (lock timeout), got {result.returncode}: {result.stderr}")

        holder.join(timeout=5.0)


class TestSinkAddValidationErrors(unittest.TestCase):
    """Additional validation error cases."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.source = self.tmp / "artifact.diff"
        self.source.write_text("diff content\n")
        self.cited = self.tmp / "README.md"
        self.cited.write_text("readme\n")
        self.lock_file = str(self.tmp / ".followup-vs-implement.lock")

    def test_invalid_sink(self) -> None:
        result = _run_sink_add(
            "--sink=invalid",
            "--priority=P2",
            "--name=Test",
            "--recommended-command=/z-do \"test\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 2)

    def test_invalid_priority(self) -> None:
        result = _run_sink_add(
            "--sink=project",
            "--priority=P9",
            "--name=Test",
            "--recommended-command=/z-do \"test\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 2)

    def test_missing_source_artifact(self) -> None:
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Test",
            "--recommended-command=/z-do \"test\"",
            "--source-artifact=/nonexistent/path.diff",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 2)

    def test_prompt_body_and_file_mutually_exclusive(self) -> None:
        body_file = self.tmp / "body.md"
        body_file.write_text("body content\n")
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Test",
            "--recommended-command=/z-do \"test\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            "--prompt-body=inline body",
            f"--prompt-body-file={body_file}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 2)


def _load_content_hash():
    """Load content_hash from sink-add-helpers.py (hyphenated filename requires importlib)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sink_add_helpers",
        str(REPO_ROOT / "scripts" / "sink-add-helpers.py"),
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.content_hash


class TestContentHashNoBoundaryCollision(unittest.TestCase):
    """Verify that content_hash() uses NUL delimiters to prevent boundary collisions."""

    def test_no_collision_on_boundary_shift(self) -> None:
        """Previously-colliding inputs hash differently with NUL delimiters.

        Without delimiters:
          name="A" + recommended_command="BC" + source_artifact="D"  → raw="ABCD"
          name="AB" + recommended_command="C" + source_artifact="D"  → raw="ABCD"
        Both would have produced the same hash. With NUL delimiters they differ.
        """
        content_hash = _load_content_hash()
        h1 = content_hash("A", "BC", "D")
        h2 = content_hash("AB", "C", "D")
        self.assertNotEqual(h1, h2, "boundary-shifted inputs must produce different hashes")

    def test_same_input_stable_hash(self) -> None:
        """Same inputs always produce the same hash (dedup still works)."""
        content_hash = _load_content_hash()
        h1 = content_hash("Fix the badge", "/z-do \"update badge\"", "artifact.diff")
        h2 = content_hash("Fix the badge", "/z-do \"update badge\"", "artifact.diff")
        self.assertEqual(h1, h2, "identical inputs must always hash to the same value")

    def test_source_artifact_excluded_from_hash(self) -> None:
        """source_artifact must NOT affect the hash (M9 fix — double-routing dedup).

        The same name+command coming from two different artifacts (a per-task
        diff.patch vs. a cumulative findings.md) must produce the same hash so the
        dedup logic fires correctly.
        """
        content_hash = _load_content_hash()
        h_diff = content_hash("Fix the badge", "/z-do \"update\"", "archive/tasks/T001/diff.patch")
        h_findings = content_hash("Fix the badge", "/z-do \"update\"", "archive/rrun-abc/findings.md")
        self.assertEqual(h_diff, h_findings,
                         "different source_artifacts must NOT produce different hashes")


def _load_helpers_module():
    """Load sink-add-helpers module via importlib (hyphenated filename)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sink_add_helpers",
        str(REPO_ROOT / "scripts" / "sink-add-helpers.py"),
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestHashComputeFailureHardRejects(unittest.TestCase):
    """M12 regression: hash/tree-hash failure must hard-error and reject the entry.

    No sentinel string ("unknown" or similar) may be persisted as a hash value.
    The create path must exit non-zero and write NO entry when hashing fails.
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.source = self.tmp / "artifact.diff"
        self.source.write_text("diff content\n")
        self.cited = self.tmp / "README.md"
        self.cited.write_text("readme\n")
        self.lock_file = str(self.tmp / ".followup-vs-implement.lock")

    # ── unit-level: git_head raises RuntimeError on failure ────────────────────

    def test_git_head_raises_on_subprocess_failure(self) -> None:
        """git_head() must raise RuntimeError, not return 'unknown', on git failure."""
        mod = _load_helpers_module()
        original = mod.subprocess.run

        def _fail(*args, **kwargs):
            import subprocess as sp
            raise sp.CalledProcessError(128, "git", stderr="not a git repo")

        mod.subprocess.run = _fail
        try:
            with self.assertRaises(RuntimeError) as ctx:
                mod.git_head()
            self.assertNotEqual(str(ctx.exception), "unknown",
                                "RuntimeError message must not be the sentinel string")
            self.assertNotIn("unknown", str(ctx.exception).lower(),
                             "error message must describe the actual failure")
        finally:
            mod.subprocess.run = original

    def test_git_head_raises_on_file_not_found(self) -> None:
        """git_head() must raise RuntimeError when git is not in PATH."""
        mod = _load_helpers_module()
        original = mod.subprocess.run

        def _not_found(*args, **kwargs):
            raise FileNotFoundError("git not found")

        mod.subprocess.run = _not_found
        try:
            with self.assertRaises(RuntimeError):
                mod.git_head()
        finally:
            mod.subprocess.run = original

    def test_git_ls_tree_hash_raises_on_subprocess_failure(self) -> None:
        """git_ls_tree_hash() must raise RuntimeError, not return 'unknown', on failure."""
        mod = _load_helpers_module()
        original = mod.subprocess.run

        def _fail(*args, **kwargs):
            import subprocess as sp
            raise sp.CalledProcessError(128, "git", stderr="bad object HEAD")

        mod.subprocess.run = _fail
        try:
            with self.assertRaises(RuntimeError) as ctx:
                mod.git_ls_tree_hash("HEAD", "some/dir")
            self.assertNotIn("unknown", str(ctx.exception).lower(),
                             "error message must describe the actual failure, not be a sentinel")
        finally:
            mod.subprocess.run = original

    def test_git_ls_tree_hash_raises_on_file_not_found(self) -> None:
        """git_ls_tree_hash() must raise RuntimeError when git is not in PATH."""
        mod = _load_helpers_module()
        original = mod.subprocess.run

        def _not_found(*args, **kwargs):
            raise FileNotFoundError("git not found")

        mod.subprocess.run = _not_found
        try:
            with self.assertRaises(RuntimeError):
                mod.git_ls_tree_hash("HEAD", "some/dir")
        finally:
            mod.subprocess.run = original

    # ── integration-level: main() exits non-zero and writes no entry ───────────

    def test_main_exits_nonzero_on_git_head_failure(self) -> None:
        """main() must exit 2 and write no entry when git_head raises RuntimeError."""
        # Run sink-add.sh from a non-git directory so git_head fails
        non_git_dir = tempfile.mkdtemp()
        try:
            non_git_tmp = Path(non_git_dir)
            source = non_git_tmp / "artifact.diff"
            source.write_text("diff\n")
            cited = non_git_tmp / "README.md"
            cited.write_text("readme\n")

            result = _run_sink_add(
                "--sink=project",
                "--priority=P2",
                "--name=Hash fail test",
                "--recommended-command=/z-do \"test hash fail\"",
                f"--source-artifact={source}",
                f"--cited-paths={cited}",
                cwd=non_git_dir,
                lock_file=str(non_git_tmp / ".test.lock"),
            )

            # Must exit non-zero
            self.assertNotEqual(result.returncode, 0,
                                f"must exit non-zero when git_head fails; got {result.returncode}: {result.stderr}")

            # Must not have written any entry
            sink_root_path = non_git_tmp / "z-harness" / "followups"
            index_jsonl = sink_root_path / "index.jsonl"
            if index_jsonl.exists():
                events = [json.loads(l) for l in index_jsonl.read_text().splitlines() if l.strip()]
                kinds = [e["kind"] for e in events]
                self.assertNotIn("entry_created", kinds,
                                 "no entry_created event should be written when git_head fails")

            # Must not persist the sentinel string "unknown" anywhere in the sink
            if sink_root_path.exists():
                for jsonl_file in sink_root_path.glob("*.jsonl"):
                    text = jsonl_file.read_text()
                    self.assertNotIn('"unknown"', text,
                                    f"sentinel 'unknown' must not appear in {jsonl_file.name}")
        finally:
            import shutil
            shutil.rmtree(non_git_dir, ignore_errors=True)

    def test_no_sentinel_in_persisted_hashes(self) -> None:
        """A successfully created entry must never contain the string 'unknown' as a hash value."""
        result = _run_sink_add(
            "--sink=project",
            "--priority=P2",
            "--name=Check no sentinel",
            "--recommended-command=/z-do \"check hashes\"",
            f"--source-artifact={self.source}",
            f"--cited-paths={self.cited}",
            cwd=self.tmpdir,
            lock_file=self.lock_file,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        sink_root_path = self.tmp / "z-harness" / "followups"
        index_jsonl = sink_root_path / "index.jsonl"
        self.assertTrue(index_jsonl.exists())

        for line in index_jsonl.read_text().splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("kind") == "entry_created":
                entry = event["entry"]
                # capture_head must not be the sentinel
                self.assertNotEqual(entry.get("capture_head"), "unknown",
                                    "capture_head must not be the sentinel 'unknown'")
                # file_blob_hashes values must match sha256: format
                fbh = entry.get("file_blob_hashes") or {}
                for path_key, hash_val in fbh.items():
                    self.assertRegex(hash_val, r'^sha256:[0-9a-f]{64}$',
                                    f"file_blob_hashes[{path_key!r}] must be sha256:<hex>")
                # dir_blob_hashes values, if present, must match sha256: format
                dbh = entry.get("dir_blob_hashes") or {}
                for path_key, hash_val in dbh.items():
                    self.assertRegex(hash_val, r'^sha256:[0-9a-f]{64}$',
                                    f"dir_blob_hashes[{path_key!r}] must be sha256:<hex>")


if __name__ == "__main__":
    unittest.main()
