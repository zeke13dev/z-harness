"""
tests/test_resolve_kernel.py — hermetic tests for scripts/resolve-kernel.sh
and the --print-hash mode of scripts/build-kernel.py.

Required cases (per T008):
  branch1_explicit          — $Z_HARNESS_KERNEL_PATH set to existing file -> path printed, exit 0
  branch2_project           — project .z-harness/KERNEL.md exists (Z_HARNESS_REPO_ROOT = temp dir) -> printed, exit 0
  branch3_global            — only global XDG kernel exists -> printed, exit 0
  no_kernel                 — no kernel anywhere -> no stdout, exit 1
  staleness_fresh           — real kernel via build-kernel.py, resolve -> no stderr warning
  staleness_tampered        — tamper header source_hash -> stderr warning + path still printed, exit 0
  print_hash_mode           — --print-hash prints 12-hex, exit 0, no KERNEL.md written
  best_effort_degrade       — build-kernel.py non-functional (bad PATH) -> no crash, path printed, exit 0

HERMETICITY: every test uses a temp XDG_CONFIG_HOME and a temp Z_HARNESS_REPO_ROOT
(itself a git repo).  Real ~/.config/z-harness and the repo's own .z-harness are
never touched.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RESOLVE_SH = str(_REPO_ROOT / "scripts" / "resolve-kernel.sh")
_BUILD_KERNEL = str(_REPO_ROOT / "scripts" / "build-kernel.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_git_repo(root: Path) -> None:
    """Make *root* a minimal git repo with one command file."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=root, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=root, check=True
    )
    cmds = root / "commands"
    cmds.mkdir(parents=True, exist_ok=True)
    (cmds / "test-cmd.md").write_text(
        "---\nname: test-cmd\ndescription: a test command\n---\nbody\n",
        encoding="utf-8",
    )


def _write_approved_axiom(store_root: Path, idx: int = 1) -> None:
    """Write a minimal approved axiom into <store_root>/.z-harness/axioms/approved/."""
    d = store_root / ".z-harness" / "axioms" / "approved"
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        "id": f"ax-{idx:08x}",
        "statement": f"Prefer approach {idx} for consistency.",
        "scope": "project",
        "status": "approved",
        "confidence": 0.80,
        "evidence": [{"run": "20260529T000000-test", "event_id": f"e-{idx:04d}"}],
        "source_run": "20260529T000000-test",
        "created_at": f"2026-05-29T00:00:{idx:02d}Z",
        "boundary_conditions": ["only for non-trivial cases"],
        "counterexamples": ["simple overrides are fine"],
    }
    (d / f"{rec['id']}.json").write_text(
        json.dumps(rec, indent=2) + "\n", encoding="utf-8"
    )


def _base_env(xdg: Path, repo_root: Path | None = None) -> dict:
    """Minimal env that keeps the test hermetic."""
    env = {**os.environ}
    env["XDG_CONFIG_HOME"] = str(xdg)
    env.pop("Z_HARNESS_KERNEL_PATH", None)
    env.pop("Z_HARNESS_REPO_ROOT", None)
    if repo_root is not None:
        env["Z_HARNESS_REPO_ROOT"] = str(repo_root)
    return env


def _run_resolve(env: dict, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    merged = {**env, **(extra_env or {})}
    return subprocess.run(
        ["bash", _RESOLVE_SH],
        env=merged,
        capture_output=True,
        text=True,
    )


def _build_kernel(repo_root: Path, xdg: Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "XDG_CONFIG_HOME": str(xdg), "Z_HARNESS_RUN": "test-run"}
    args = [sys.executable, _BUILD_KERNEL, "--scope", "project",
            "--repo-root", str(repo_root)]
    args += extra_args or []
    return subprocess.run(args, env=env, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Branch 1: $Z_HARNESS_KERNEL_PATH set and file exists
# ---------------------------------------------------------------------------

class TestBranch1Explicit(unittest.TestCase):
    def test_explicit_path_printed_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)

            # Create a dummy kernel file somewhere arbitrary.
            kernel = Path(tmp) / "my-kernel.md"
            kernel.write_text(
                "<!-- z-harness-kernel GENERATED — do not edit by hand -->\n"
                "## z-harness kernel\n"
                "generated_at: 2026-01-01T00:00:00Z   |   scope: global\n"
                "source_hash: aabbccddeeff   |   n_axioms: 0   |   drop_count: 0   |   compiler_version: 1\n",
                encoding="utf-8",
            )

            env = _base_env(xdg, repo)
            result = _run_resolve(env, {"Z_HARNESS_KERNEL_PATH": str(kernel)})

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(kernel))


# ---------------------------------------------------------------------------
# Branch 2: project .z-harness/KERNEL.md (Z_HARNESS_REPO_ROOT set)
# ---------------------------------------------------------------------------

class TestBranch2Project(unittest.TestCase):
    def test_project_kernel_printed_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)

            kernel = repo / ".z-harness" / "KERNEL.md"
            kernel.parent.mkdir(parents=True, exist_ok=True)
            kernel.write_text(
                "<!-- z-harness-kernel GENERATED — do not edit by hand -->\n"
                "## z-harness kernel\n"
                "generated_at: 2026-01-01T00:00:00Z   |   scope: project\n"
                "source_hash: 112233445566   |   n_axioms: 0   |   drop_count: 0   |   compiler_version: 1\n",
                encoding="utf-8",
            )

            env = _base_env(xdg, repo)
            result = _run_resolve(env)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(kernel))

    def test_project_takes_priority_over_global(self):
        """Project branch wins even when global kernel also exists."""
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)

            # Global kernel
            global_dir = xdg / "z-harness"
            global_dir.mkdir(parents=True)
            (global_dir / "KERNEL.md").write_text("global kernel\n", encoding="utf-8")

            # Project kernel
            project_kernel = repo / ".z-harness" / "KERNEL.md"
            project_kernel.parent.mkdir(parents=True, exist_ok=True)
            project_kernel.write_text(
                "<!-- z-harness-kernel GENERATED — do not edit by hand -->\n"
                "## z-harness kernel\n"
                "generated_at: 2026-01-01T00:00:00Z   |   scope: project\n"
                "source_hash: 112233445566   |   n_axioms: 0   |   drop_count: 0   |   compiler_version: 1\n",
                encoding="utf-8",
            )

            env = _base_env(xdg, repo)
            result = _run_resolve(env)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(project_kernel))


# ---------------------------------------------------------------------------
# Branch 3: global XDG kernel only
# ---------------------------------------------------------------------------

class TestBranch3Global(unittest.TestCase):
    def test_global_kernel_printed_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)

            global_kernel = xdg / "z-harness" / "KERNEL.md"
            global_kernel.parent.mkdir(parents=True)
            global_kernel.write_text(
                "<!-- z-harness-kernel GENERATED — do not edit by hand -->\n"
                "## z-harness kernel\n"
                "generated_at: 2026-01-01T00:00:00Z   |   scope: global\n"
                "source_hash: ffeeddccbbaa   |   n_axioms: 0   |   drop_count: 0   |   compiler_version: 1\n",
                encoding="utf-8",
            )

            # No project kernel — point repo at a temp dir with no .z-harness
            env = _base_env(xdg, repo)
            result = _run_resolve(env)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(global_kernel))


# ---------------------------------------------------------------------------
# No kernel anywhere
# ---------------------------------------------------------------------------

class TestNoKernel(unittest.TestCase):
    def test_no_stdout_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)

            env = _base_env(xdg, repo)
            result = _run_resolve(env)

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout.strip(), "")


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------

class TestStaleness(unittest.TestCase):
    def _build_real_kernel(self, repo: Path, xdg: Path) -> Path:
        """Build a real kernel via build-kernel.py and return its path."""
        r = _build_kernel(repo, xdg)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        return repo / ".z-harness" / "KERNEL.md"

    def test_fresh_kernel_no_warning(self):
        """A freshly built kernel should produce no staleness warning."""
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            _write_approved_axiom(repo, idx=1)

            kernel_path = self._build_real_kernel(repo, xdg)
            self.assertTrue(kernel_path.exists())

            env = _base_env(xdg, repo)
            result = _run_resolve(env)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(kernel_path))
            # No staleness warning expected.
            self.assertNotIn("WARNING", result.stderr)
            self.assertNotIn("stale", result.stderr)

    def test_tampered_header_emits_warning_path_still_printed(self):
        """
        If the source_hash in the header is tampered, resolve still exits 0 and
        prints the path, but also emits a WARNING: KERNEL.md is stale message to stderr.
        """
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            _write_approved_axiom(repo, idx=1)

            kernel_path = self._build_real_kernel(repo, xdg)
            self.assertTrue(kernel_path.exists())

            # Tamper the source_hash in the header.
            text = kernel_path.read_text(encoding="utf-8")
            tampered = re.sub(
                r"(source_hash: )([0-9a-f]{12})",
                r"\g<1>000000000000",
                text,
                count=1,
            )
            self.assertNotEqual(text, tampered, "tampering did not change the file")
            kernel_path.write_text(tampered, encoding="utf-8")

            env = _base_env(xdg, repo)
            result = _run_resolve(env)

            # Exit 0 and path printed even when stale.
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(kernel_path))
            # Staleness warning present.
            self.assertIn("WARNING", result.stderr)
            self.assertIn("stale", result.stderr)


# ---------------------------------------------------------------------------
# --print-hash mode
# ---------------------------------------------------------------------------

class TestPrintHashMode(unittest.TestCase):
    def test_prints_12hex_exit_0_no_kernel_written(self):
        """--print-hash prints a 12-hex string, exits 0, does not write KERNEL.md."""
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            _write_approved_axiom(repo, idx=1)

            env = {**os.environ, "XDG_CONFIG_HOME": str(xdg)}
            result = subprocess.run(
                [sys.executable, _BUILD_KERNEL, "--print-hash", "--scope", "project",
                 "--repo-root", str(repo)],
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            printed = result.stdout.strip()
            # Must be exactly 12 lowercase hex characters.
            self.assertRegex(printed, r"^[0-9a-f]{12}$",
                             msg=f"expected 12-hex, got: {printed!r}")
            # KERNEL.md must NOT have been written.
            kernel_path = repo / ".z-harness" / "KERNEL.md"
            self.assertFalse(kernel_path.exists(),
                             msg="--print-hash must not write KERNEL.md")

    def test_print_hash_matches_kernel_header(self):
        """
        The value printed by --print-hash must be byte-identical to the
        source_hash: value build-kernel.py writes into KERNEL.md for the
        same inputs.  This is the core validity invariant for resolve-kernel.sh.
        """
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)
            _write_approved_axiom(repo, idx=1)
            _write_approved_axiom(repo, idx=2)

            env = {**os.environ, "XDG_CONFIG_HOME": str(xdg), "Z_HARNESS_RUN": "test"}

            # Build the kernel.
            build_result = subprocess.run(
                [sys.executable, _BUILD_KERNEL, "--scope", "project",
                 "--repo-root", str(repo)],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(build_result.returncode, 0, msg=build_result.stderr)
            kernel_text = (repo / ".z-harness" / "KERNEL.md").read_text(encoding="utf-8")
            m = re.search(r"source_hash: ([0-9a-f]+)", kernel_text)
            self.assertIsNotNone(m, "source_hash not found in kernel header")
            header_hash = m.group(1)

            # Run --print-hash.
            ph_result = subprocess.run(
                [sys.executable, _BUILD_KERNEL, "--print-hash", "--scope", "project",
                 "--repo-root", str(repo)],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(ph_result.returncode, 0, msg=ph_result.stderr)
            printed_hash = ph_result.stdout.strip()

            self.assertEqual(header_hash, printed_hash,
                             msg=f"header has {header_hash!r}, --print-hash returned {printed_hash!r}")


# ---------------------------------------------------------------------------
# Best-effort degrade: recompute impossible -> no crash, path still printed
# ---------------------------------------------------------------------------

class TestBestEffortDegrade(unittest.TestCase):
    def test_bad_python_path_no_crash_path_printed(self):
        """
        When python3 is not on PATH (or build-kernel.py errors), the staleness
        check is silently skipped — no crash, path still printed, exit 0.
        """
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)

            kernel = repo / ".z-harness" / "KERNEL.md"
            kernel.parent.mkdir(parents=True, exist_ok=True)
            kernel.write_text(
                "<!-- z-harness-kernel GENERATED — do not edit by hand -->\n"
                "## z-harness kernel\n"
                "generated_at: 2026-01-01T00:00:00Z   |   scope: project\n"
                "source_hash: 112233445566   |   n_axioms: 0   |   drop_count: 0   |   compiler_version: 1\n",
                encoding="utf-8",
            )

            env = _base_env(xdg, repo)
            # Remove python3 from PATH so the recompute call fails, while
            # keeping bash and git accessible for the shell script itself.
            # We do this by pointing python3 at a path that does not exist.
            env["PATH"] = "/usr/bin:/bin"  # bash/git exist here; no python3 normally
            # If python3 happens to be in /usr/bin on this system, use a temp
            # wrapper that exits non-zero so build-kernel.py --print-hash fails.
            fake_python = Path(tmp) / "bin"
            fake_python.mkdir()
            fake_py3 = fake_python / "python3"
            fake_py3.write_text("#!/usr/bin/env sh\nexit 1\n", encoding="utf-8")
            fake_py3.chmod(0o755)
            env["PATH"] = str(fake_python) + ":/usr/bin:/bin"

            result = _run_resolve(env)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(kernel))
            # No error crash: either no warning or a warning, but definitely no
            # Python traceback on stdout and exit must still be 0.
            self.assertNotIn("Traceback", result.stdout)
            self.assertNotIn("Traceback", result.stderr.split("WARNING")[0]
                             if "WARNING" in result.stderr else result.stderr)

    def test_unparseable_source_hash_skips_check(self):
        """
        A kernel with no source_hash: line means the staleness check cannot
        parse the header hash — it silently skips and still prints the path.
        """
        with tempfile.TemporaryDirectory() as tmp:
            xdg = Path(tmp) / "xdg"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_git_repo(repo)

            kernel = repo / ".z-harness" / "KERNEL.md"
            kernel.parent.mkdir(parents=True, exist_ok=True)
            # Kernel without source_hash: line.
            kernel.write_text(
                "## z-harness kernel\nno hash line here\n",
                encoding="utf-8",
            )

            env = _base_env(xdg, repo)
            result = _run_resolve(env)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(kernel))
            self.assertNotIn("WARNING", result.stderr)


if __name__ == "__main__":
    unittest.main()
