"""Targeted tests for install.sh tarball checksum and rollback behavior."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.resolve()
INSTALL_SH = REPO_ROOT / "install.sh"


class InstallShIntegrityTest(unittest.TestCase):
    def _make_payload_tarball(self, tmp: Path) -> Path:
        payload = tmp / "payload" / "z-harness"
        for rel in ("skills", "agents", "runtime", "scripts", "docs"):
            (payload / rel).mkdir(parents=True, exist_ok=True)
        (payload / "VERSION").write_text("2.0.0\n", encoding="utf-8")
        (payload / "runtime" / "marker.txt").write_text("new install\n", encoding="utf-8")

        tarball = tmp / "z-harness.tar.gz"
        subprocess.run(
            ["tar", "-czf", str(tarball), "-C", str(payload.parent), payload.name],
            check=True,
        )
        return tarball

    def _run_install(
        self,
        home: Path,
        *args: str,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(INSTALL_SH), *args],
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_corrupt_sha_exits_before_extraction_or_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            existing = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            existing.mkdir(parents=True)
            (existing / "KEEP").write_text("old install\n", encoding="utf-8")

            bad_download = tmp / "not-a-tarball.tar.gz"
            bad_download.write_bytes(b"not a gzip tarball")
            wrong_sha = "0" * 64

            result = self._run_install(
                home,
                "--target=claude",
                f"--tarball={bad_download.as_uri()}",
                f"--tarball-sha256={wrong_sha}",
                "--force",
            )

            self.assertNotEqual(result.returncode, 0)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertIn("SHA-256 mismatch", combined)
            self.assertNotIn("tarball extraction failed", combined)
            self.assertEqual((existing / "KEEP").read_text(encoding="utf-8"), "old install\n")

    def test_failed_extraction_leaves_existing_install_intact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            existing = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            existing.mkdir(parents=True)
            (existing / "KEEP").write_text("old install\n", encoding="utf-8")

            corrupt_tarball = tmp / "corrupt.tar.gz"
            corrupt_tarball.write_bytes(b"checksum matches but extraction must fail")
            expected_sha = hashlib.sha256(corrupt_tarball.read_bytes()).hexdigest()

            result = self._run_install(
                home,
                "--target=claude",
                f"--tarball={corrupt_tarball.as_uri()}",
                f"--tarball-sha256={expected_sha}",
                "--force",
            )

            self.assertNotEqual(result.returncode, 0)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertIn("tarball extraction failed", combined)
            self.assertEqual((existing / "KEEP").read_text(encoding="utf-8"), "old install\n")

    def test_valid_sha_installs_claude_tarball(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            tarball = self._make_payload_tarball(tmp)
            expected_sha = hashlib.sha256(tarball.read_bytes()).hexdigest()

            result = self._run_install(
                home,
                "--target=claude",
                f"--tarball={tarball.as_uri()}",
                f"--tarball-sha256={expected_sha}",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            installed = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            self.assertEqual(
                (installed / "runtime" / "marker.txt").read_text(encoding="utf-8"),
                "new install\n",
            )
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertIn("reinstall from the audited release manifest/tarball", combined)
            self.assertIn("z-harness install --target=claude --force", combined)
            self.assertNotIn("Run /z-update", combined)

    def test_valid_sha_installs_codex_tarball(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            tarball = self._make_payload_tarball(tmp)
            expected_sha = hashlib.sha256(tarball.read_bytes()).hexdigest()
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            codex_log = tmp / "codex.log"
            fake_codex = fake_bin / "codex"
            fake_codex.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$CODEX_LOG\"\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            result = self._run_install(
                home,
                "--target=codex",
                f"--tarball={tarball.as_uri()}",
                f"--tarball-sha256={expected_sha}",
                extra_env={
                    "CODEX_LOG": str(codex_log),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            installed = home / "plugins" / "z-harness"
            self.assertEqual(
                (installed / "runtime" / "marker.txt").read_text(encoding="utf-8"),
                "new install\n",
            )
            self.assertIn(
                "plugin add z-harness@personal",
                codex_log.read_text(encoding="utf-8"),
            )
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertIn("reinstall from the audited release manifest/tarball", combined)
            self.assertIn("z-harness install --target=codex --force", combined)
            self.assertNotIn("Run /z-update", combined)

    def test_target_all_rolls_back_claude_when_codex_replacement_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            claude_existing = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            codex_existing = home / "plugins" / "z-harness"
            claude_existing.mkdir(parents=True)
            codex_existing.mkdir(parents=True)
            (claude_existing / "KEEP").write_text("old claude\n", encoding="utf-8")
            (codex_existing / "KEEP").write_text("old codex\n", encoding="utf-8")

            tarball = self._make_payload_tarball(tmp)
            expected_sha = hashlib.sha256(tarball.read_bytes()).hexdigest()
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            fail_once = tmp / "mv-failed-once"
            fake_mv = fake_bin / "mv"
            fake_mv.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$#\" -eq 2 && \"$2\" == \"$CODEX_FAIL_DEST\" && ! -e \"$CODEX_FAIL_ONCE\" ]]; then\n"
                "  touch \"$CODEX_FAIL_ONCE\"\n"
                "  exit 1\n"
                "fi\n"
                "exec /bin/mv \"$@\"\n",
                encoding="utf-8",
            )
            fake_mv.chmod(0o755)

            result = self._run_install(
                home,
                "--target=all",
                f"--tarball={tarball.as_uri()}",
                f"--tarball-sha256={expected_sha}",
                "--force",
                extra_env={
                    "CODEX_FAIL_DEST": str(codex_existing),
                    "CODEX_FAIL_ONCE": str(fail_once),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            self.assertNotEqual(result.returncode, 0)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertIn("could not move staged Codex install into place", combined)
            self.assertEqual(
                (claude_existing / "KEEP").read_text(encoding="utf-8"),
                "old claude\n",
            )
            self.assertEqual(
                (codex_existing / "KEEP").read_text(encoding="utf-8"),
                "old codex\n",
            )
            self.assertFalse((claude_existing / "runtime" / "marker.txt").exists())
            self.assertFalse((codex_existing / "runtime" / "marker.txt").exists())

    def test_target_all_second_download_failure_leaves_prior_installs_intact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            claude_existing = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            codex_existing = home / "plugins" / "z-harness"
            claude_existing.mkdir(parents=True)
            codex_existing.mkdir(parents=True)
            (claude_existing / "KEEP").write_text("old claude\n", encoding="utf-8")
            (codex_existing / "KEEP").write_text("old codex\n", encoding="utf-8")

            tarball = self._make_payload_tarball(tmp)
            expected_sha = hashlib.sha256(tarball.read_bytes()).hexdigest()
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            curl_count = tmp / "curl-count"
            fake_curl = fake_bin / "curl"
            fake_curl.write_text(
                "#!/usr/bin/env bash\n"
                "count=0\n"
                "if [[ -f \"$CURL_COUNT\" ]]; then count=$(cat \"$CURL_COUNT\"); fi\n"
                "count=$((count + 1))\n"
                "printf '%s' \"$count\" > \"$CURL_COUNT\"\n"
                "output=''\n"
                "while [[ \"$#\" -gt 0 ]]; do\n"
                "  case \"$1\" in\n"
                "    -o) output=\"$2\"; shift 2 ;;\n"
                "    *) shift ;;\n"
                "  esac\n"
                "done\n"
                "if [[ \"$count\" -eq 2 ]]; then exit 22; fi\n"
                "cp \"$CURL_SOURCE\" \"$output\"\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)

            result = self._run_install(
                home,
                "--target=all",
                f"--tarball={tarball.as_uri()}",
                f"--tarball-sha256={expected_sha}",
                "--force",
                extra_env={
                    "CURL_COUNT": str(curl_count),
                    "CURL_SOURCE": str(tarball),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            self.assertNotEqual(result.returncode, 0)
            combined = f"{result.stdout}\n{result.stderr}"
            self.assertIn("failed to download tarball", combined)
            self.assertEqual(
                (claude_existing / "KEEP").read_text(encoding="utf-8"),
                "old claude\n",
            )
            self.assertEqual(
                (codex_existing / "KEEP").read_text(encoding="utf-8"),
                "old codex\n",
            )
            self.assertFalse((claude_existing / "runtime" / "marker.txt").exists())
            self.assertFalse((codex_existing / "runtime" / "marker.txt").exists())


if __name__ == "__main__":
    unittest.main()
