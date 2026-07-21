"""Targeted tests for install.sh tarball checksum and rollback behavior."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from z_harness_cli.__main__ import app
from z_harness_cli.commands import update as update_mod


REPO_ROOT = Path(__file__).parent.parent.resolve()
INSTALL_SH = REPO_ROOT / "install.sh"


class InstallShIntegrityTest(unittest.TestCase):
    def _make_payload_tarball(
        self,
        tmp: Path,
        *,
        version: str = "2.0.0",
        generator_body: str | None = None,
    ) -> Path:
        payload = tmp / "payload" / "z-harness"
        for rel in ("skills", "agents", "runtime", "scripts", "docs"):
            (payload / rel).mkdir(parents=True, exist_ok=True)
        (payload / "VERSION").write_text(version + "\n", encoding="utf-8")
        (payload / "runtime" / "marker.txt").write_text("new install\n", encoding="utf-8")
        generator = payload / "scripts" / "generate-exports.py"
        generator.write_text(
            generator_body
            or (
                "from pathlib import Path\n"
                "out = Path(__file__).parents[1] / 'temp' / 'exports'\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "(out / 'candidate.txt').write_text('generated v2\\n')\n"
            ),
            encoding="utf-8",
        )

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
        shell: str = "/bin/bash",
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["XDG_STATE_HOME"] = str(home / ".local" / "state")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [shell, str(INSTALL_SH), *args],
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )

    def _make_special_tarball(
        self,
        tmp: Path,
        *,
        name: str,
        linkname: str | None = None,
        hardlink: bool = False,
    ) -> Path:
        tarball = tmp / "special.tar.gz"
        with tarfile.open(tarball, "w:gz") as archive:
            member = tarfile.TarInfo(name)
            if linkname is None:
                content = b"unsafe\n"
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            else:
                member.type = tarfile.LNKTYPE if hardlink else tarfile.SYMTYPE
                member.linkname = linkname
                archive.addfile(member)
        return tarball

    def test_repo_mode_preflight_completes_under_apple_and_macports_bash(self) -> None:
        """B2: confinement preflight must not hang in either supported Bash."""

        shells = [Path("/bin/bash")]
        macports_bash = Path("/opt/local/bin/bash")
        if macports_bash.is_file():
            shells.append(macports_bash)

        for shell in shells:
            for target in ("codex", "all"):
                with (
                    self.subTest(shell=str(shell), target=target),
                    tempfile.TemporaryDirectory() as td,
                ):
                    tmp = Path(td)
                    home = tmp / "home"
                    mirror = tmp / "repo"
                    mirror.mkdir()
                    (mirror / ".git").mkdir()
                    for name in (
                        ".codex-plugin",
                        "skills",
                        "agents",
                        "runtime",
                        "scripts",
                        "VERSION",
                    ):
                        (mirror / name).symlink_to(
                            REPO_ROOT / name,
                            target_is_directory=(REPO_ROOT / name).is_dir(),
                        )

                    fake_bin = tmp / "bin"
                    fake_bin.mkdir()
                    registration = tmp / "registered"
                    codex = fake_bin / "codex"
                    codex.write_text(
                        "#!/bin/sh\n"
                        "if [ \"$1 $2\" = \"plugin list\" ]; then\n"
                        "  [ -e \"$REGISTRATION\" ] && printf 'z-harness@personal\\n'\n"
                        "  exit 0\n"
                        "fi\n"
                        "if [ \"$1 $2\" = \"plugin add\" ]; then\n"
                        "  touch \"$REGISTRATION\"; exit 0\n"
                        "fi\n"
                        "if [ \"$1 $2\" = \"plugin remove\" ]; then\n"
                        "  rm -f \"$REGISTRATION\"; exit 0\n"
                        "fi\n"
                        "exit 1\n",
                        encoding="utf-8",
                    )
                    codex.chmod(0o755)
                    environment = {
                        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                        "REGISTRATION": str(registration),
                        "Z_HARNESS_RELEASE_SURFACE": "prod",
                    }
                    try:
                        result = subprocess.run(
                            [str(shell), str(INSTALL_SH), f"--target={target}"],
                            cwd=mirror,
                            env={
                                **os.environ,
                                "HOME": str(home),
                                "XDG_STATE_HOME": str(home / ".local" / "state"),
                                **environment,
                            },
                            text=True,
                            capture_output=True,
                            check=False,
                            timeout=20,
                        )
                    except subprocess.TimeoutExpired as exc:
                        trace = (
                            exc.stderr.decode()
                            if isinstance(exc.stderr, bytes)
                            else (exc.stderr or "")
                        )
                        self.fail(f"installer timed out under {shell}:\n{trace[-8000:]}")

                    self.assertEqual(result.returncode, 0, result.stderr)
                    lifecycle = home / ".local" / "state" / "z-harness" / "lifecycle"
                    self.assertFalse((lifecycle / "current").exists())
                    self.assertFalse((lifecycle / "lock").exists())

    def test_embedded_helpers_are_bound_to_startup_script_image(self) -> None:
        """B1: path replacement keeps the inode snapshot; in-place edits fail closed."""

        shells = [Path("/bin/bash")]
        macports_bash = Path("/opt/local/bin/bash")
        if macports_bash.is_file():
            shells.append(macports_bash)

        for shell in shells:
            for mutation in ("atomic-replace", "in-place"):
                with (
                    self.subTest(shell=str(shell), mutation=mutation),
                    tempfile.TemporaryDirectory() as td,
                ):
                    tmp = Path(td)
                    home = tmp / "home"
                    script_dir = tmp / "installer image with spaces"
                    script_dir.mkdir()
                    script = script_dir / "install plugin.sh"
                    shutil.copy2(INSTALL_SH, script)

                    fake_bin = tmp / "bin"
                    fake_bin.mkdir()
                    registration = tmp / "registered"
                    ready = tmp / "inventory-ready"
                    proceed = tmp / "inventory-proceed"
                    codex = fake_bin / "codex"
                    codex.write_text(
                        "#!/bin/sh\n"
                        "if [ \"$1 $2\" = \"plugin list\" ]; then\n"
                        "  if [ ! -e \"$READY\" ]; then\n"
                        "    touch \"$READY\"\n"
                        "    while [ ! -e \"$PROCEED\" ]; do sleep 0.05; done\n"
                        "  fi\n"
                        "  [ -e \"$REGISTRATION\" ] && printf 'z-harness@personal\\n'\n"
                        "  exit 0\n"
                        "fi\n"
                        "if [ \"$1 $2\" = \"plugin add\" ]; then\n"
                        "  touch \"$REGISTRATION\"; exit 0\n"
                        "fi\n"
                        "if [ \"$1 $2\" = \"plugin remove\" ]; then\n"
                        "  rm -f \"$REGISTRATION\"; exit 0\n"
                        "fi\n"
                        "exit 1\n",
                        encoding="utf-8",
                    )
                    codex.chmod(0o755)
                    environment = {
                        **os.environ,
                        "HOME": str(home),
                        "XDG_STATE_HOME": str(home / ".local" / "state"),
                        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                        "REGISTRATION": str(registration),
                        "READY": str(ready),
                        "PROCEED": str(proceed),
                    }
                    process = subprocess.Popen(
                        [str(shell), str(script), "--target=codex"],
                        cwd=REPO_ROOT,
                        env=environment,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    deadline = time.monotonic() + 10
                    while not ready.exists() and process.poll() is None:
                        if time.monotonic() >= deadline:
                            process.kill()
                            self.fail("installer did not reach registration inventory pause")
                        time.sleep(0.02)
                    if not ready.exists():
                        stdout, stderr = process.communicate(timeout=5)
                        self.fail(
                            "installer exited before registration inventory pause:\n"
                            f"{stdout}\n{stderr}"
                        )

                    if mutation == "atomic-replace":
                        replacement = script_dir / "replacement"
                        replacement.write_text("#!/bin/sh\nexit 91\n", encoding="utf-8")
                        replacement.chmod(0o755)
                        os.replace(replacement, script)
                    else:
                        with script.open("r+b") as handle:
                            handle.seek(0)
                            handle.write(b"X")
                            handle.flush()
                            os.fsync(handle.fileno())
                    proceed.touch()
                    stdout, stderr = process.communicate(timeout=20)

                    lifecycle = home / ".local" / "state" / "z-harness" / "lifecycle"
                    if mutation == "atomic-replace":
                        self.assertEqual(process.returncode, 0, stderr)
                        self.assertTrue(registration.exists())
                        self.assertFalse((lifecycle / "current").exists())
                        self.assertFalse((lifecycle / "lock").exists())
                    else:
                        self.assertNotEqual(process.returncode, 0, stdout)
                        self.assertIn("running installer image changed", stderr)
                        self.assertFalse(registration.exists())
                        self.assertFalse((home / "plugins" / "z-harness").exists())
                        self.assertFalse(
                            (home / ".agents" / "plugins" / "marketplace.json").exists()
                        )

    def test_handoff_child_keeps_startup_image_fd_for_embedded_helpers(self) -> None:
        """B1: the handed-off shell's helper children inherit its image descriptor."""

        shells = [Path("/bin/bash")]
        macports_bash = Path("/opt/local/bin/bash")
        if macports_bash.is_file():
            shells.append(macports_bash)

        for shell in shells:
            with self.subTest(shell=str(shell)), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                home = tmp / "home"
                script_dir = tmp / "handoff installer with spaces"
                script_dir.mkdir()
                script = script_dir / "install plugin.sh"
                shutil.copy2(INSTALL_SH, script)
                fake_bin = tmp / "bin"
                fake_bin.mkdir()
                registration = tmp / "registered"
                codex = fake_bin / "codex"
                codex.write_text(
                    "#!/bin/sh\n"
                    "if [ \"$1 $2\" = \"plugin list\" ]; then\n"
                    "  [ -e \"$REGISTRATION\" ] && printf 'z-harness@personal\\n'\n"
                    "  exit 0\n"
                    "fi\n"
                    "if [ \"$1 $2\" = \"plugin add\" ]; then\n"
                    "  touch \"$REGISTRATION\"; exit 0\n"
                    "fi\n"
                    "if [ \"$1 $2\" = \"plugin remove\" ]; then\n"
                    "  rm -f \"$REGISTRATION\"; exit 0\n"
                    "fi\n"
                    "exit 1\n",
                    encoding="utf-8",
                )
                codex.chmod(0o755)
                state_home = home / ".local" / "state"
                parent_environment = {
                    "HOME": str(home),
                    "XDG_STATE_HOME": str(state_home),
                }
                with patch.dict(os.environ, parent_environment):
                    lock, token = update_mod._acquire_lifecycle_lock_for_pid(os.getpid())
                    child_environment = {
                        **os.environ,
                        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                        "REGISTRATION": str(registration),
                        "Z_HARNESS_HANDOFF_TOKEN": token,
                    }
                    child = subprocess.Popen(
                        [str(shell), str(script), "--target=codex"],
                        cwd=REPO_ROOT,
                        env=child_environment,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    try:
                        update_mod._handoff_lifecycle_lock(lock, token, child.pid)
                        stdout, stderr = child.communicate(timeout=20)
                    finally:
                        if child.poll() is None:
                            child.terminate()
                            child.wait(timeout=5)
                        if lock.exists():
                            update_mod._release_lifecycle_lock_token(lock, token)

                self.assertEqual(child.returncode, 0, f"{stdout}\n{stderr}")
                self.assertTrue(registration.exists())
                self.assertFalse(lock.exists())

    def test_cli_remote_tarball_requires_paired_digest(self) -> None:
        runner = CliRunner()
        with patch("z_harness_cli.commands.install.subprocess.run") as run_mock:
            result = runner.invoke(
                app,
                ["install", "--tarball=https://example.com/z-harness.tar.gz"],
            )

        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("--tarball-sha256 is required", result.output)
        run_mock.assert_not_called()

    def test_cli_remote_tarball_forwards_valid_digest(self) -> None:
        runner = CliRunner()
        completed = MagicMock(returncode=0)
        digest = "a" * 64
        with patch(
            "z_harness_cli.commands.install.subprocess.run",
            return_value=completed,
        ) as run_mock:
            result = runner.invoke(
                app,
                [
                    "install",
                    "--tarball=https://example.com/z-harness.tar.gz",
                    f"--tarball-sha256={digest}",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        args = run_mock.call_args.args[0]
        self.assertIn("--tarball=https://example.com/z-harness.tar.gz", args)
        self.assertIn(f"--tarball-sha256={digest}", args)

    def test_cli_remote_tarball_rejects_malformed_digest(self) -> None:
        runner = CliRunner()
        with patch("z_harness_cli.commands.install.subprocess.run") as run_mock:
            result = runner.invoke(
                app,
                [
                    "install",
                    "--tarball=https://example.com/z-harness.tar.gz",
                    "--tarball-sha256=not-a-digest",
                ],
            )

        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("64-character hexadecimal", result.output)
        run_mock.assert_not_called()

    def test_local_archive_path_installs_without_digest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            tarball = self._make_payload_tarball(tmp)

            result = self._run_install(
                home,
                "--target=claude",
                f"--tarball={tarball}",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            installed = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            self.assertEqual(
                (installed / "runtime" / "marker.txt").read_text(encoding="utf-8"),
                "new install\n",
            )

    def test_direct_remote_tarball_rejects_missing_digest_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            curl_marker = tmp / "curl-called"
            fake_curl = fake_bin / "curl"
            fake_curl.write_text(
                "#!/usr/bin/env bash\n"
                "touch \"$CURL_MARKER\"\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)

            result = self._run_install(
                tmp / "home",
                "--target=claude",
                "--tarball=https://example.com/z-harness.tar.gz",
                extra_env={
                    "CURL_MARKER": str(curl_marker),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--tarball-sha256 is required", result.stderr)
            self.assertFalse(curl_marker.exists())

    def test_rejects_nonportable_or_escaping_member_paths_before_extraction(self) -> None:
        for member_name in ("/tmp/z-harness-escape", "../escape", "root\\escape", "C:/escape"):
            with self.subTest(member_name=member_name), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                home = tmp / "home"
                tarball = self._make_special_tarball(tmp, name=member_name)

                result = self._run_install(
                    home,
                    "--target=claude",
                    f"--tarball={tarball}",
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unsafe archive member path", result.stderr)
                self.assertFalse((home / ".claude" / "plugins" / "z-harness@zeke-tools").exists())

    def test_rejects_unsafe_symlink_and_hardlink_destinations(self) -> None:
        cases = (
            ("root/link", "../../escape", False),
            ("root/link", "../escape", True),
        )
        for name, linkname, hardlink in cases:
            with self.subTest(hardlink=hardlink), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                home = tmp / "home"
                tarball = self._make_special_tarball(
                    tmp,
                    name=name,
                    linkname=linkname,
                    hardlink=hardlink,
                )

                result = self._run_install(
                    home,
                    "--target=claude",
                    f"--tarball={tarball}",
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unsafe archive link destination", result.stderr)
                self.assertFalse((home / ".claude" / "plugins" / "z-harness@zeke-tools").exists())

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
                "printf '%s\\n' \"$*\" >> \"$CODEX_LOG\"\n"
                "if [[ \"$1 $2\" == \"plugin list\" ]]; then [[ -e \"$CODEX_REGISTRATION\" ]] && printf 'z-harness@personal\\n'; exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin add\" ]]; then touch \"$CODEX_REGISTRATION\"; exit 0; fi\n",
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
                    "CODEX_REGISTRATION": str(tmp / "codex-registration"),
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
            fake_codex = fake_bin / "codex"
            fake_codex.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1 $2\" == \"plugin list\" ]]; then exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

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

    def test_every_fault_step_restores_full_all_host_cli_pre_state(self) -> None:
        """C4 criterion #4/#8: every fault restores the full component set."""

        script = INSTALL_SH.read_text(encoding="utf-8")
        declared = script.split('LIFECYCLE_FAULT_STEPS="', 1)[1].split('"', 1)[0].split()
        self.assertEqual(
            declared,
            [
                "payload.claude",
                "payload.codex",
                "marketplace.codex",
                "registration.codex",
                "exports.claude",
                "exports.codex",
                "cli.tool",
                "cli.launcher",
                "coherence",
            ],
        )

        for step in declared:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                home = tmp / "home"
                claude = home / ".claude" / "plugins" / "z-harness@zeke-tools"
                codex = home / "plugins" / "z-harness"
                for root, marker in ((claude, "old claude\n"), (codex, "old codex\n")):
                    (root / "temp" / "exports").mkdir(parents=True)
                    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
                    (root / "KEEP").write_text(marker, encoding="utf-8")
                    (root / "temp" / "exports" / "old.txt").write_text(marker, encoding="utf-8")
                marketplace = home / ".agents" / "plugins" / "marketplace.json"
                marketplace.parent.mkdir(parents=True)
                old_marketplace = '{"name":"personal","plugins":[]}\n'
                marketplace.write_text(old_marketplace, encoding="utf-8")

                fake_bin = tmp / "bin"
                fake_bin.mkdir()
                registration = tmp / "registered"
                fake_codex = fake_bin / "codex"
                fake_codex.write_text(
                    "#!/usr/bin/env bash\n"
                    "if [[ \"$1 $2\" == \"plugin list\" ]]; then [[ -e \"$REGISTRATION\" ]] && printf 'z-harness@personal\\n'; exit 0; fi\n"
                    "if [[ \"$1 $2\" == \"plugin add\" ]]; then touch \"$REGISTRATION\"; exit 0; fi\n"
                    "if [[ \"$1 $2\" == \"plugin remove\" ]]; then rm -f \"$REGISTRATION\"; exit 0; fi\n"
                    "exit 1\n",
                    encoding="utf-8",
                )
                fake_codex.chmod(0o755)
                tool_root = home / ".local" / "share" / "uv" / "tools" / "z-harness"
                tool_root.mkdir(parents=True)
                (tool_root / "old.txt").write_text("old tool\n", encoding="utf-8")
                launcher_dir = home / ".local" / "bin"
                launcher_dir.mkdir(parents=True)
                launcher = launcher_dir / "z-harness"
                launcher_zh = launcher_dir / "zh"
                launcher.write_text("old launcher\n", encoding="utf-8")
                launcher_zh.write_text("old zh\n", encoding="utf-8")
                uv = fake_bin / "uv"
                uv.write_text(
                    "#!/usr/bin/env bash\n"
                    "rm -rf \"$CLI_TOOL_ROOT\"; mkdir -p \"$CLI_TOOL_ROOT\"\n"
                    "printf 'new tool\\n' > \"$CLI_TOOL_ROOT/new.txt\"\n"
                    "cat > \"$CLI_LAUNCHER\" <<'EOF'\n"
                    "#!/usr/bin/env bash\n"
                    "printf 'z-harness 2.0.0\\n'\n"
                    "EOF\n"
                    "chmod +x \"$CLI_LAUNCHER\"\n"
                    "cp \"$CLI_LAUNCHER\" \"$CLI_LAUNCHER_ZH\"\n",
                    encoding="utf-8",
                )
                uv.chmod(0o755)
                wheel = tmp / "candidate.whl"
                wheel.write_bytes(b"wheel")
                tarball = self._make_payload_tarball(tmp)
                digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
                result = self._run_install(
                    home,
                    "--target=all",
                    f"--tarball={tarball}",
                    f"--tarball-sha256={digest}",
                    "--force",
                    "--generate-exports",
                    extra_env={
                        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                        "REGISTRATION": str(registration),
                        "Z_HARNESS_TRANSACTION_CLI_WHEEL": str(wheel),
                        "Z_HARNESS_TRANSACTION_CLI_TOOL_ROOT": str(tool_root),
                        "Z_HARNESS_TRANSACTION_CLI_LAUNCHER": str(launcher),
                        "Z_HARNESS_TRANSACTION_CLI_LAUNCHER_ZH": str(launcher_zh),
                        "CLI_TOOL_ROOT": str(tool_root),
                        "CLI_LAUNCHER": str(launcher),
                        "CLI_LAUNCHER_ZH": str(launcher_zh),
                        "Z_HARNESS_TEST_FAIL_AFTER": step,
                    },
                )

                self.assertEqual(result.returncode, 97, result.stderr)
                self.assertEqual((claude / "KEEP").read_text(encoding="utf-8"), "old claude\n")
                self.assertEqual((codex / "KEEP").read_text(encoding="utf-8"), "old codex\n")
                self.assertEqual(marketplace.read_text(encoding="utf-8"), old_marketplace)
                self.assertFalse(registration.exists())
                self.assertEqual((tool_root / "old.txt").read_text(encoding="utf-8"), "old tool\n")
                self.assertEqual(launcher.read_text(encoding="utf-8"), "old launcher\n")
                self.assertEqual(launcher_zh.read_text(encoding="utf-8"), "old zh\n")
                self.assertFalse((home / ".local" / "state" / "z-harness" / "lifecycle" / "current").exists())
                self.assertFalse((home / ".local" / "state" / "z-harness" / "lifecycle" / "lock").exists())

    def test_cli_fault_steps_restore_tool_and_both_launchers(self) -> None:
        """C4 criterion #4: CLI tool and exposed launchers share host rollback."""

        for step in ("cli.tool", "cli.launcher"):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                home = tmp / "home"
                old = home / ".claude" / "plugins" / "z-harness@zeke-tools"
                old.mkdir(parents=True)
                (old / "VERSION").write_text("1.0.0\n", encoding="utf-8")
                (old / "KEEP").write_text("old payload\n", encoding="utf-8")
                tarball = self._make_payload_tarball(tmp)
                tool_root = home / ".local" / "share" / "uv" / "tools" / "z-harness"
                tool_root.mkdir(parents=True)
                (tool_root / "old.txt").write_text("old tool\n", encoding="utf-8")
                fake_bin = tmp / "bin"
                fake_bin.mkdir()
                launcher_dir = home / ".local" / "bin"
                launcher_dir.mkdir(parents=True)
                launcher = launcher_dir / "z-harness"
                launcher_zh = launcher_dir / "zh"
                launcher.write_text("old launcher\n", encoding="utf-8")
                launcher_zh.write_text("old zh\n", encoding="utf-8")
                fake_uv = fake_bin / "uv"
                fake_uv.write_text(
                    "#!/usr/bin/env bash\n"
                    "rm -rf \"$CLI_TOOL_ROOT\"; mkdir -p \"$CLI_TOOL_ROOT\"\n"
                    "printf 'new tool\\n' > \"$CLI_TOOL_ROOT/new.txt\"\n"
                    "printf 'new launcher\\n' > \"$CLI_LAUNCHER\"\n"
                    "printf 'new zh\\n' > \"$CLI_LAUNCHER_ZH\"\n",
                    encoding="utf-8",
                )
                fake_uv.chmod(0o755)
                wheel = tmp / "candidate.whl"
                wheel.write_bytes(b"wheel")

                result = self._run_install(
                    home,
                    "--target=claude",
                    f"--tarball={tarball}",
                    "--force",
                    extra_env={
                        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                        "Z_HARNESS_TRANSACTION_CLI_WHEEL": str(wheel),
                        "Z_HARNESS_TRANSACTION_CLI_TOOL_ROOT": str(tool_root),
                        "Z_HARNESS_TRANSACTION_CLI_LAUNCHER": str(launcher),
                        "Z_HARNESS_TRANSACTION_CLI_LAUNCHER_ZH": str(launcher_zh),
                        "CLI_TOOL_ROOT": str(tool_root),
                        "CLI_LAUNCHER": str(launcher),
                        "CLI_LAUNCHER_ZH": str(launcher_zh),
                        "Z_HARNESS_TEST_FAIL_AFTER": step,
                    },
                )
                self.assertEqual(result.returncode, 97, result.stderr)
                self.assertEqual((tool_root / "old.txt").read_text(encoding="utf-8"), "old tool\n")
                self.assertEqual(launcher.read_text(encoding="utf-8"), "old launcher\n")
                self.assertEqual(launcher_zh.read_text(encoding="utf-8"), "old zh\n")
                self.assertEqual((old / "KEEP").read_text(encoding="utf-8"), "old payload\n")

    def test_interrupted_apply_and_repeated_recovery_are_idempotent(self) -> None:
        """C4 criterion #5: recovery restores durable pre-state before retry."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            destination = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            destination.mkdir(parents=True)
            (destination / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            (destination / "PARTIAL").write_text("interrupted\n", encoding="utf-8")

            transaction = home / ".local" / "state" / "z-harness" / "lifecycle" / "current"
            backup = transaction / "claude_payload.backup"
            backup.mkdir(parents=True)
            (backup / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (backup / "KEEP").write_text("last known good\n", encoding="utf-8")
            (transaction / "state").write_text("applying\n", encoding="utf-8")
            (transaction / "claude_payload.path").write_text(str(destination) + "\n", encoding="utf-8")
            (transaction / "claude_payload.present").write_text("true\n", encoding="utf-8")
            (transaction / "claude_payload.mutation").write_text("started\n", encoding="utf-8")

            tarball = self._make_payload_tarball(tmp)
            for attempt in range(2):
                result = self._run_install(
                    home,
                    "--target=claude",
                    f"--tarball={tarball}",
                    "--force",
                    extra_env={"Z_HARNESS_TEST_FAIL_AFTER": "payload.claude"},
                )
                self.assertEqual(result.returncode, 97, result.stderr)
                if attempt == 0:
                    self.assertIn("recovering interrupted lifecycle transaction", result.stderr)
                self.assertEqual(
                    (destination / "KEEP").read_text(encoding="utf-8"),
                    "last known good\n",
                )
                self.assertFalse((destination / "PARTIAL").exists())
                self.assertFalse(transaction.exists())

    def test_dual_host_v1_to_v2_commits_one_coherent_release(self) -> None:
        """C4 criterion #7: all selected host finalizers commit the same version."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            for destination in (
                home / ".claude" / "plugins" / "z-harness@zeke-tools",
                home / "plugins" / "z-harness",
            ):
                destination.mkdir(parents=True)
                (destination / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            registration = tmp / "registered"
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1 $2\" == \"plugin list\" ]]; then [[ -e \"$REGISTRATION\" ]] && printf 'z-harness@personal\\n'; exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin add\" ]]; then touch \"$REGISTRATION\"; exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            codex.chmod(0o755)
            tool_root = home / ".local" / "share" / "uv" / "tools" / "z-harness"
            tool_root.mkdir(parents=True)
            (tool_root / "old.txt").write_text("old tool\n", encoding="utf-8")
            launcher_dir = home / ".local" / "bin"
            launcher_dir.mkdir(parents=True)
            launcher = launcher_dir / "z-harness"
            launcher_zh = launcher_dir / "zh"
            launcher.write_text("old launcher\n", encoding="utf-8")
            launcher_zh.write_text("old zh\n", encoding="utf-8")
            uv = fake_bin / "uv"
            uv.write_text(
                "#!/usr/bin/env bash\n"
                "rm -rf \"$CLI_TOOL_ROOT\"; mkdir -p \"$CLI_TOOL_ROOT\"\n"
                "printf 'new tool\\n' > \"$CLI_TOOL_ROOT/new.txt\"\n"
                "cat > \"$CLI_LAUNCHER\" <<'EOF'\n"
                "#!/usr/bin/env bash\n"
                "printf 'z-harness 2.0.0\\n'\n"
                "EOF\n"
                "chmod +x \"$CLI_LAUNCHER\"\n"
                "cp \"$CLI_LAUNCHER\" \"$CLI_LAUNCHER_ZH\"\n",
                encoding="utf-8",
            )
            uv.chmod(0o755)
            wheel = tmp / "candidate.whl"
            wheel.write_bytes(b"wheel")
            tarball = self._make_payload_tarball(tmp)

            result = self._run_install(
                home,
                "--target=all",
                f"--tarball={tarball}",
                "--force",
                "--generate-exports",
                extra_env={
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "REGISTRATION": str(registration),
                    "Z_HARNESS_TRANSACTION_CLI_WHEEL": str(wheel),
                    "Z_HARNESS_TRANSACTION_CLI_TOOL_ROOT": str(tool_root),
                    "Z_HARNESS_TRANSACTION_CLI_LAUNCHER": str(launcher),
                    "Z_HARNESS_TRANSACTION_CLI_LAUNCHER_ZH": str(launcher_zh),
                    "CLI_TOOL_ROOT": str(tool_root),
                    "CLI_LAUNCHER": str(launcher),
                    "CLI_LAUNCHER_ZH": str(launcher_zh),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            claude = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            codex_root = home / "plugins" / "z-harness"
            self.assertEqual((claude / "VERSION").read_text(encoding="utf-8"), "2.0.0\n")
            self.assertEqual((codex_root / "VERSION").read_text(encoding="utf-8"), "2.0.0\n")
            self.assertEqual(
                (claude / "temp" / "exports" / "candidate.txt").read_text(encoding="utf-8"),
                "generated v2\n",
            )
            self.assertEqual(
                (codex_root / "temp" / "exports" / "candidate.txt").read_text(encoding="utf-8"),
                "generated v2\n",
            )
            marketplace = json.loads(
                (home / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
            )
            self.assertEqual([entry["name"] for entry in marketplace["plugins"]], ["z-harness"])
            self.assertTrue(registration.exists())
            self.assertEqual((tool_root / "new.txt").read_text(encoding="utf-8"), "new tool\n")
            self.assertEqual(
                subprocess.run([str(launcher), "--version"], check=True, capture_output=True, text=True).stdout,
                "z-harness 2.0.0\n",
            )

    def test_interrupted_commit_cleanup_never_rolls_back_committed_payload(self) -> None:
        """C4 criterion #5: replay finalizes committed cleanup, not old backup."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            destination = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            destination.mkdir(parents=True)
            (destination / "VERSION").write_text("1.5.0\n", encoding="utf-8")
            (destination / "COMMITTED").write_text("keep committed\n", encoding="utf-8")
            transaction = home / ".local" / "state" / "z-harness" / "lifecycle" / "current"
            backup = transaction / "claude_payload.backup"
            backup.mkdir(parents=True)
            (backup / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (backup / "OLD").write_text("must not return\n", encoding="utf-8")
            (transaction / "state").write_text("committed\n", encoding="utf-8")
            (transaction / "claude_payload.path").write_text(str(destination) + "\n", encoding="utf-8")
            (transaction / "claude_payload.present").write_text("true\n", encoding="utf-8")
            (transaction / "claude_payload.mutation").write_text("started\n", encoding="utf-8")
            tarball = self._make_payload_tarball(tmp)

            result = self._run_install(
                home,
                "--target=claude",
                f"--tarball={tarball}",
                "--force",
                extra_env={"Z_HARNESS_TEST_FAIL_AFTER": "payload.claude"},
            )

            self.assertEqual(result.returncode, 97, result.stderr)
            self.assertEqual(
                (destination / "COMMITTED").read_text(encoding="utf-8"),
                "keep committed\n",
            )
            self.assertFalse((destination / "OLD").exists())
            self.assertFalse(transaction.exists())

    def test_failed_first_dual_install_leaves_no_host_residue(self) -> None:
        """C4 criterion #4: absent pre-state is restored after a late failure."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            registration = tmp / "registered"
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1 $2\" == \"plugin list\" ]]; then [[ -e \"$REGISTRATION\" ]] && printf 'z-harness@personal\\n'; exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin add\" ]]; then touch \"$REGISTRATION\"; exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin remove\" ]]; then rm -f \"$REGISTRATION\"; exit 0; fi\n",
                encoding="utf-8",
            )
            codex.chmod(0o755)
            tarball = self._make_payload_tarball(tmp)
            result = self._run_install(
                home,
                "--target=all",
                f"--tarball={tarball}",
                "--generate-exports",
                extra_env={
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "REGISTRATION": str(registration),
                    "Z_HARNESS_TEST_FAIL_AFTER": "exports.codex",
                },
            )

            self.assertEqual(result.returncode, 97, result.stderr)
            self.assertFalse((home / ".claude" / "plugins" / "z-harness@zeke-tools").exists())
            self.assertFalse((home / "plugins" / "z-harness").exists())
            self.assertFalse((home / ".agents" / "plugins" / "marketplace.json").exists())
            self.assertFalse(registration.exists())

    def test_real_exporter_failure_rolls_back_immediately(self) -> None:
        """B1: generator process failure returns through transaction rollback."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            destination = home / ".claude" / "plugins" / "z-harness@zeke-tools"
            destination.mkdir(parents=True)
            (destination / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (destination / "KEEP").write_text("old payload\n", encoding="utf-8")
            tarball = self._make_payload_tarball(tmp, generator_body="raise SystemExit(23)\n")

            result = self._run_install(
                home,
                "--target=claude",
                f"--tarball={tarball}",
                "--force",
                "--generate-exports",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((destination / "KEEP").read_text(encoding="utf-8"), "old payload\n")
            self.assertFalse(
                (home / ".local" / "state" / "z-harness" / "lifecycle" / "current").exists()
            )

    def test_failed_registration_compensation_retains_then_recovers(self) -> None:
        """B2: failed compensation remains journaled until a later retry succeeds."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            registration = tmp / "registered"
            fail_remove = tmp / "fail-remove"
            fail_remove.touch()
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1 $2\" == \"plugin list\" ]]; then [[ -e \"$REGISTRATION\" ]] && printf 'z-harness@personal\\n'; exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin add\" ]]; then touch \"$REGISTRATION\"; exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin remove\" ]]; then [[ -e \"$FAIL_REMOVE\" ]] && exit 42; rm -f \"$REGISTRATION\"; exit 0; fi\n",
                encoding="utf-8",
            )
            codex.chmod(0o755)
            tarball = self._make_payload_tarball(tmp)
            environment = {
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "REGISTRATION": str(registration),
                "FAIL_REMOVE": str(fail_remove),
            }
            first = self._run_install(
                home,
                "--target=codex",
                f"--tarball={tarball}",
                extra_env={**environment, "Z_HARNESS_TEST_FAIL_AFTER": "registration.codex"},
            )
            journal = home / ".local" / "state" / "z-harness" / "lifecycle" / "current"
            self.assertEqual(first.returncode, 97, first.stderr)
            self.assertTrue(registration.exists())
            self.assertTrue(journal.exists())
            self.assertTrue(journal.parent.joinpath("lock").exists())
            self.assertIn("recovery state retained", first.stderr)

            fail_remove.unlink()
            second = self._run_install(
                home,
                "--target=codex",
                f"--tarball={tarball}",
                extra_env={**environment, "Z_HARNESS_TEST_FAIL_AFTER": "payload.codex"},
            )
            self.assertEqual(second.returncode, 97, second.stderr)
            self.assertFalse(registration.exists())
            self.assertFalse(journal.exists())
            self.assertFalse(journal.parent.joinpath("lock").exists())

    def test_zero_exit_codex_add_without_registration_rolls_back(self) -> None:
        """B3: command success is not registration success without observed state."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1 $2\" == \"plugin list\" ]]; then exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin add\" ]]; then exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin remove\" ]]; then exit 0; fi\n",
                encoding="utf-8",
            )
            codex.chmod(0o755)
            tarball = self._make_payload_tarball(tmp)
            result = self._run_install(
                home,
                "--target=codex",
                f"--tarball={tarball}",
                extra_env={"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("registration is absent", result.stderr)
            self.assertFalse((home / "plugins" / "z-harness").exists())
            self.assertFalse((home / ".agents" / "plugins" / "marketplace.json").exists())
            self.assertFalse(
                (home / ".local" / "state" / "z-harness" / "lifecycle" / "current").exists()
            )

    def test_post_add_query_error_compensates_confirmed_absent_registration(self) -> None:
        """B1: post-state uncertainty cannot erase durable absent pre-state."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            registration = tmp / "registered"
            list_calls = tmp / "list-calls"
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1 $2\" == \"plugin list\" ]]; then\n"
                "  count=0; [[ -f \"$LIST_CALLS\" ]] && count=$(cat \"$LIST_CALLS\")\n"
                "  count=$((count + 1)); printf '%s\\n' \"$count\" > \"$LIST_CALLS\"\n"
                "  [[ \"$count\" -eq 2 ]] && exit 42\n"
                "  [[ -e \"$REGISTRATION\" ]] && printf 'z-harness@personal\\n'\n"
                "  exit 0\n"
                "fi\n"
                "if [[ \"$1 $2\" == \"plugin add\" ]]; then touch \"$REGISTRATION\"; exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin remove\" ]]; then rm -f \"$REGISTRATION\"; exit 0; fi\n",
                encoding="utf-8",
            )
            codex.chmod(0o755)
            tarball = self._make_payload_tarball(tmp)
            result = self._run_install(
                home,
                "--target=codex",
                f"--tarball={tarball}",
                extra_env={
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "REGISTRATION": str(registration),
                    "LIST_CALLS": str(list_calls),
                },
            )

            lifecycle = home / ".local" / "state" / "z-harness" / "lifecycle"
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("registration verification failed", result.stderr)
            self.assertFalse(registration.exists())
            self.assertFalse((home / "plugins" / "z-harness").exists())
            self.assertFalse((lifecycle / "current").exists())
            self.assertFalse((lifecycle / "lock").exists())

    def test_registration_inventory_error_preserves_preexisting_registration(self) -> None:
        """B3: unreadable pre-state aborts before add and can never authorize remove."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            registration = tmp / "registered"
            registration.touch()
            calls = tmp / "calls"
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$CALLS\"\n"
                "if [[ \"$1 $2\" == \"plugin list\" ]]; then exit 42; fi\n"
                "if [[ \"$1 $2\" == \"plugin add\" ]]; then exit 0; fi\n"
                "if [[ \"$1 $2\" == \"plugin remove\" ]]; then rm -f \"$REGISTRATION\"; exit 0; fi\n",
                encoding="utf-8",
            )
            codex.chmod(0o755)
            tarball = self._make_payload_tarball(tmp)
            result = self._run_install(
                home,
                "--target=codex",
                f"--tarball={tarball}",
                extra_env={
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "REGISTRATION": str(registration),
                    "CALLS": str(calls),
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(registration.exists())
            invoked = calls.read_text(encoding="utf-8")
            self.assertIn("plugin list", invoked)
            self.assertNotIn("plugin add", invoked)
            self.assertNotIn("plugin remove", invoked)
            self.assertFalse((home / "plugins" / "z-harness").exists())

    def test_noncanonical_candidate_versions_fail_before_mutation(self) -> None:
        """B5: lifecycle consumes C5's exact release-candidate grammar."""

        for version in ("1.0", "2.0.0+local.1", "2.0.0.dev1"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                home = tmp / "home"
                destination = home / ".claude" / "plugins" / "z-harness@zeke-tools"
                destination.mkdir(parents=True)
                (destination / "KEEP").write_text("old\n", encoding="utf-8")
                tarball = self._make_payload_tarball(tmp, version=version)
                result = self._run_install(
                    home,
                    "--target=claude",
                    f"--tarball={tarball}",
                    "--force",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((destination / "KEEP").read_text(encoding="utf-8"), "old\n")

    def test_active_transaction_owner_fails_closed(self) -> None:
        """M2: a concurrent live owner cannot be recovered or overwritten."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            lock = home / ".local" / "state" / "z-harness" / "lifecycle" / "lock"
            lock.mkdir(parents=True)
            (lock / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
            tarball = self._make_payload_tarball(tmp)
            result = self._run_install(home, "--target=claude", f"--tarball={tarball}")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("owned by active pid", result.stderr)
            self.assertFalse((home / ".claude" / "plugins" / "z-harness@zeke-tools").exists())

    def test_unpublished_candidate_never_occupies_canonical_shell_lock(self) -> None:
        """B5: a populated candidate is invisible until its atomic publication."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            lifecycle = home / ".local" / "state" / "z-harness" / "lifecycle"
            candidate = lifecycle / ".lock.candidate.paused"
            candidate.mkdir(parents=True)
            (candidate / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "started": "paused", "token": "paused"}),
                encoding="utf-8",
            )
            tarball = self._make_payload_tarball(tmp)
            contender = self._run_install(home, "--target=claude", f"--tarball={tarball}")
            self.assertEqual(contender.returncode, 0, contender.stderr)
            self.assertTrue(candidate.exists())

    def test_shell_lock_reclaims_reused_pid_with_wrong_start_identity(self) -> None:
        """B5: PID reuse cannot make a stale owner look live."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            lock = home / ".local" / "state" / "z-harness" / "lifecycle" / "lock"
            lock.mkdir(parents=True)
            (lock / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "started": "not-this-process", "token": "stale"}),
                encoding="utf-8",
            )
            tarball = self._make_payload_tarball(tmp)
            result = self._run_install(home, "--target=claude", f"--tarball={tarball}")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(lock.exists())

    def test_corrupt_recovery_path_is_retained_without_touching_victim(self) -> None:
        """M2: recursive restore rejects journal paths outside known destinations."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            victim = tmp / "victim"
            victim.mkdir()
            (victim / "KEEP").write_text("safe\n", encoding="utf-8")
            journal = home / ".local" / "state" / "z-harness" / "lifecycle" / "current"
            journal.mkdir(parents=True)
            (journal / "state").write_text("applying\n", encoding="utf-8")
            (journal / "claude_payload.path").write_text(str(victim) + "\n", encoding="utf-8")
            (journal / "claude_payload.mutation").write_text("started\n", encoding="utf-8")
            tarball = self._make_payload_tarball(tmp)
            result = self._run_install(home, "--target=claude", f"--tarball={tarball}")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing corrupt or unconfined recovery path", result.stderr.lower())
            self.assertEqual((victim / "KEEP").read_text(encoding="utf-8"), "safe\n")
            self.assertTrue(journal.exists())

    def test_selected_host_paths_with_symlinked_parents_fail_before_mutation(self) -> None:
        """B3: every selected host surface is confined before backup or replacement."""

        for surface in ("claude", "codex", "marketplace", "exports"):
            with self.subTest(surface=surface), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                home = tmp / "home"
                outside = tmp / "outside"
                outside.mkdir()
                target = "claude" if surface in {"claude", "exports"} else "codex"
                args = [f"--target={target}"]

                if surface == "claude":
                    (home / ".claude").mkdir(parents=True)
                    (home / ".claude" / "plugins").symlink_to(outside, target_is_directory=True)
                    victim = outside / "z-harness@zeke-tools"
                elif surface == "codex":
                    home.mkdir(parents=True)
                    (home / "plugins").symlink_to(outside, target_is_directory=True)
                    victim = outside / "z-harness"
                elif surface == "marketplace":
                    victim = home / "plugins" / "z-harness"
                    (home / ".agents").mkdir(parents=True)
                    (home / ".agents" / "plugins").symlink_to(outside, target_is_directory=True)
                    (outside / "marketplace.json").write_text(
                        "victim marketplace\n", encoding="utf-8"
                    )
                else:
                    victim = home / ".claude" / "plugins" / "z-harness@zeke-tools"
                    victim.mkdir(parents=True)
                    (victim / "temp").symlink_to(outside, target_is_directory=True)
                    args.append("--generate-exports")

                victim.mkdir(parents=True, exist_ok=True)
                (victim / "KEEP").write_text("safe\n", encoding="utf-8")
                tarball = self._make_payload_tarball(tmp)
                result = self._run_install(
                    home,
                    *args,
                    f"--tarball={tarball}",
                    "--force",
                )

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((victim / "KEEP").read_text(encoding="utf-8"), "safe\n")
                self.assertFalse((victim / "runtime" / "marker.txt").exists())
                self.assertFalse(
                    (home / ".local" / "state" / "z-harness" / "lifecycle" / "current").exists()
                )
                if surface == "marketplace":
                    self.assertEqual(
                        (outside / "marketplace.json").read_text(encoding="utf-8"),
                        "victim marketplace\n",
                    )

    def test_selected_cli_paths_with_symlinked_parents_fail_before_mutation(self) -> None:
        """B3: exact uv tool and launcher roots reject symlinked ancestors."""

        for surface in ("cli_tool", "cli_launcher"):
            with self.subTest(surface=surface), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                home = tmp / "home"
                host = home / ".claude" / "plugins" / "z-harness@zeke-tools"
                host.mkdir(parents=True)
                (host / "KEEP").write_text("safe host\n", encoding="utf-8")
                outside = tmp / "outside"
                outside.mkdir()
                wheel = tmp / "candidate.whl"
                wheel.write_bytes(b"wheel")
                environment = {"Z_HARNESS_TRANSACTION_CLI_WHEEL": str(wheel)}

                if surface == "cli_tool":
                    data_home = home / ".local" / "share"
                    data_home.mkdir(parents=True)
                    outside_uv = outside / "uv"
                    victim = outside_uv / "tools" / "z-harness"
                    victim.mkdir(parents=True)
                    (data_home / "uv").symlink_to(outside_uv, target_is_directory=True)
                    tool_root = data_home / "uv" / "tools" / "z-harness"
                else:
                    tool_root = home / ".local" / "share" / "uv" / "tools" / "z-harness"
                    tool_root.mkdir(parents=True)
                    bin_parent = home / ".local"
                    bin_parent.mkdir(parents=True, exist_ok=True)
                    outside_bin = outside / "bin"
                    outside_bin.mkdir()
                    (bin_parent / "bin").symlink_to(outside_bin, target_is_directory=True)
                    victim = outside_bin / "z-harness"
                    victim.write_text("safe launcher\n", encoding="utf-8")
                    environment["Z_HARNESS_TRANSACTION_CLI_LAUNCHER"] = str(
                        home / ".local" / "bin" / "z-harness"
                    )
                if victim.is_dir():
                    (victim / "KEEP").write_text("safe cli\n", encoding="utf-8")
                environment["Z_HARNESS_TRANSACTION_CLI_TOOL_ROOT"] = str(tool_root)
                tarball = self._make_payload_tarball(tmp)
                result = self._run_install(
                    home,
                    "--target=claude",
                    f"--tarball={tarball}",
                    "--force",
                    extra_env=environment,
                )

                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((host / "KEEP").read_text(encoding="utf-8"), "safe host\n")
                if victim.is_dir():
                    self.assertEqual((victim / "KEEP").read_text(encoding="utf-8"), "safe cli\n")
                else:
                    self.assertEqual(victim.read_text(encoding="utf-8"), "safe launcher\n")
                self.assertFalse(
                    (home / ".local" / "state" / "z-harness" / "lifecycle" / "current").exists()
                )


if __name__ == "__main__":
    unittest.main()
