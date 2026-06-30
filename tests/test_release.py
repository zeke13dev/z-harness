"""Unit tests for z_harness_cli/release.py and commands/update.py.

Coverage:
- parse_manifest: valid, missing fields, wrong-typed fields
- schema_version newer than SUPPORTED → ManifestSchemaError (exit-1 path)
- compare_versions: stale / equal / newer / dev-SHA-unknown
- verify_sha256: matching and mismatching hash
- fetch_manifest: mocked urllib (success, HTTP 404, URLError)
- update.run: stale notice, equal no-op, newer-schema clean exit-1, sha-mismatch
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.release import (
    SUPPORTED_SCHEMA_VERSION,
    FetchError,
    ManifestParseError,
    ManifestSchemaError,
    ReleaseManifest,
    VersionComparisonResult,
    compare_versions,
    fetch_manifest,
    is_dev_sha,
    parse_manifest,
    verify_sha256,
    require_plugin_tarball_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manifest_json(
    schema_version: int = SUPPORTED_SCHEMA_VERSION,
    version: str = "1.2.3",
    wheel_url: str = "https://example.com/z-harness-1.2.3-py3-none-any.whl",
    sha256: str = "a" * 64,
    cli_schema_version: int = 1,
    telemetry_schema_version: int = 1,
    min_supported_version: str = "1.0.0",
    plugin_tarball_url: str | None = None,
    plugin_tarball_sha256: str | None = None,
) -> str:
    data = {
        "schema_version": schema_version,
        "version": version,
        "wheel_url": wheel_url,
        "sha256": sha256,
        "cli_schema_version": cli_schema_version,
        "telemetry_schema_version": telemetry_schema_version,
        "min_supported_version": min_supported_version,
    }
    if plugin_tarball_url is not None:
        data["plugin_tarball_url"] = plugin_tarball_url
    if plugin_tarball_sha256 is not None:
        data["plugin_tarball_sha256"] = plugin_tarball_sha256
    return json.dumps(data)


def _make_manifest(**kwargs) -> ReleaseManifest:
    return parse_manifest(_manifest_json(**kwargs))


# ---------------------------------------------------------------------------
# parse_manifest
# ---------------------------------------------------------------------------

class TestParseManifest(unittest.TestCase):

    def test_valid_manifest_parses(self):
        m = _make_manifest()
        self.assertEqual(m.version, "1.2.3")
        self.assertEqual(m.schema_version, SUPPORTED_SCHEMA_VERSION)
        self.assertEqual(m.wheel_url, "https://example.com/z-harness-1.2.3-py3-none-any.whl")
        self.assertEqual(m.sha256, "a" * 64)

    def test_supported_schema_version_accepted(self):
        m = _make_manifest(schema_version=SUPPORTED_SCHEMA_VERSION)
        self.assertEqual(m.schema_version, SUPPORTED_SCHEMA_VERSION)

    def test_older_schema_version_accepted(self):
        # A manifest with schema_version < supported is fine (forward-compatible reads).
        if SUPPORTED_SCHEMA_VERSION > 1:
            m = _make_manifest(schema_version=SUPPORTED_SCHEMA_VERSION - 1)
            self.assertIsNotNone(m)

    def test_newer_schema_version_raises_manifest_schema_error(self):
        """schema_version newer than supported MUST raise ManifestSchemaError (F6 minor)."""
        raw = _manifest_json(schema_version=SUPPORTED_SCHEMA_VERSION + 1)
        with self.assertRaises(ManifestSchemaError) as cm:
            parse_manifest(raw)
        self.assertIn("update z-harness", str(cm.exception).lower())

    def test_missing_version_field_raises(self):
        data = json.loads(_manifest_json())
        del data["version"]
        with self.assertRaises(ManifestParseError):
            parse_manifest(json.dumps(data))

    def test_missing_wheel_url_raises(self):
        data = json.loads(_manifest_json())
        del data["wheel_url"]
        with self.assertRaises(ManifestParseError):
            parse_manifest(json.dumps(data))

    def test_missing_sha256_raises(self):
        data = json.loads(_manifest_json())
        del data["sha256"]
        with self.assertRaises(ManifestParseError):
            parse_manifest(json.dumps(data))

    def test_non_int_schema_version_raises(self):
        data = json.loads(_manifest_json())
        data["schema_version"] = "1"  # string, not int
        with self.assertRaises(ManifestParseError):
            parse_manifest(json.dumps(data))

    def test_non_int_cli_schema_version_raises(self):
        data = json.loads(_manifest_json())
        data["cli_schema_version"] = "1"
        with self.assertRaises(ManifestParseError):
            parse_manifest(json.dumps(data))

    def test_invalid_json_raises_manifest_parse_error(self):
        with self.assertRaises(ManifestParseError):
            parse_manifest("not json {")

    def test_non_object_raises_manifest_parse_error(self):
        with self.assertRaises(ManifestParseError):
            parse_manifest(json.dumps([1, 2, 3]))

    def test_empty_string_version_raises(self):
        data = json.loads(_manifest_json())
        data["version"] = ""
        with self.assertRaises(ManifestParseError):
            parse_manifest(json.dumps(data))

    def test_bad_sha256_raises(self):
        raw = _manifest_json(sha256="abc123")
        with self.assertRaises(ManifestParseError):
            parse_manifest(raw)

    def test_non_https_wheel_url_raises(self):
        raw = _manifest_json(wheel_url="http://example.com/z-harness.whl")
        with self.assertRaises(ManifestParseError):
            parse_manifest(raw)

    def test_plugin_tarball_fields_parse(self):
        m = _make_manifest(
            plugin_tarball_url="https://example.com/z-harness-1.2.3.tar.gz",
            plugin_tarball_sha256="b" * 64,
        )
        self.assertEqual(m.plugin_tarball_url, "https://example.com/z-harness-1.2.3.tar.gz")
        self.assertEqual(m.plugin_tarball_sha256, "b" * 64)

    def test_plugin_tarball_requires_sha(self):
        raw = _manifest_json(plugin_tarball_url="https://example.com/z-harness.tar.gz")
        with self.assertRaises(ManifestParseError):
            parse_manifest(raw)

    def test_file_urls_require_explicit_allow(self):
        raw = _manifest_json(
            wheel_url="file:///tmp/z-harness.whl",
            plugin_tarball_url="file:///tmp/z-harness.tar.gz",
            plugin_tarball_sha256="b" * 64,
        )
        with self.assertRaises(ManifestParseError):
            parse_manifest(raw)
        m = parse_manifest(raw, allow_file_urls=True)
        self.assertEqual(m.wheel_url, "file:///tmp/z-harness.whl")

    def test_require_plugin_tarball_metadata_returns_audited_tuple(self):
        m = _make_manifest(
            plugin_tarball_url="https://example.com/z-harness-1.2.3.tar.gz",
            plugin_tarball_sha256="c" * 64,
        )
        self.assertEqual(
            require_plugin_tarball_metadata(m),
            ("https://example.com/z-harness-1.2.3.tar.gz", "c" * 64),
        )

    def test_require_plugin_tarball_metadata_rejects_missing_fields(self):
        m = _make_manifest()
        with self.assertRaises(ManifestParseError):
            require_plugin_tarball_metadata(m)


# ---------------------------------------------------------------------------
# is_dev_sha
# ---------------------------------------------------------------------------

class TestIsDevSha(unittest.TestCase):

    def test_7char_hex_is_sha(self):
        self.assertTrue(is_dev_sha("abc1234"))

    def test_40char_hex_is_sha(self):
        self.assertTrue(is_dev_sha("a" * 40))

    def test_semver_is_not_sha(self):
        self.assertFalse(is_dev_sha("1.2.3"))

    def test_semver_with_v_is_not_sha(self):
        self.assertFalse(is_dev_sha("v1.2.3"))

    def test_empty_is_not_sha(self):
        self.assertFalse(is_dev_sha(""))

    def test_mixed_non_hex_is_not_sha(self):
        self.assertFalse(is_dev_sha("xyz1234"))

    def test_dev0_fallback_is_not_sha(self):
        self.assertFalse(is_dev_sha("0.0.0.dev0"))


# ---------------------------------------------------------------------------
# compare_versions
# ---------------------------------------------------------------------------

class TestCompareVersions(unittest.TestCase):

    def _manifest(self, version: str = "1.2.3") -> ReleaseManifest:
        return _make_manifest(version=version)

    # --- semver paths ---

    def test_equal_semver_is_equal(self):
        m = self._manifest("1.2.3")
        self.assertEqual(compare_versions("1.2.3", m), VersionComparisonResult.EQUAL)

    def test_equal_with_v_prefix_is_equal(self):
        m = self._manifest("1.2.3")
        self.assertEqual(compare_versions("v1.2.3", m), VersionComparisonResult.EQUAL)

    def test_stale_install_is_stale(self):
        """Installed older than manifest → STALE (the important upgrade path)."""
        m = self._manifest("2.0.0")
        result = compare_versions("1.9.9", m)
        self.assertEqual(result, VersionComparisonResult.STALE)

    def test_newer_installed_is_newer(self):
        m = self._manifest("1.0.0")
        result = compare_versions("2.0.0", m)
        self.assertEqual(result, VersionComparisonResult.NEWER)

    def test_minor_stale(self):
        m = self._manifest("1.3.0")
        self.assertEqual(compare_versions("1.2.9", m), VersionComparisonResult.STALE)

    def test_patch_stale(self):
        m = self._manifest("1.2.4")
        self.assertEqual(compare_versions("1.2.3", m), VersionComparisonResult.STALE)

    def test_pre_release_older_than_release(self):
        """1.2.3-alpha < 1.2.3 (pre-release < release)."""
        m = self._manifest("1.2.3")
        self.assertEqual(compare_versions("1.2.3-alpha", m), VersionComparisonResult.STALE)

    # --- dev SHA paths ---

    def test_dev_sha_not_in_manifest_is_dev_unknown(self):
        """Dev SHA with no reference in manifest → DEV_UNKNOWN (notice, no block)."""
        m = self._manifest("1.2.3")
        result = compare_versions("abc1234", m)
        self.assertEqual(result, VersionComparisonResult.DEV_UNKNOWN)

    def test_dev_sha_equal_to_manifest_version_is_equal(self):
        """If the manifest version happens to be the exact SHA, that's EQUAL."""
        sha = "abc1234"
        m = _make_manifest(version=sha)
        result = compare_versions(sha, m)
        self.assertEqual(result, VersionComparisonResult.EQUAL)

    def test_dev_sha_never_reported_as_stale(self):
        """A dev SHA must never return STALE — it must be DEV_UNKNOWN or EQUAL."""
        m = self._manifest("99.99.99")  # far-future manifest
        result = compare_versions("abc1234", m)
        self.assertNotEqual(result, VersionComparisonResult.STALE,
                            "Dev SHA must never be reported as STALE — this would block the user")

    # --- PEP 440 dev/local version paths ---

    def test_pep440_dev0_does_not_crash(self):
        """PEP 440 '0.0.0.dev0' must not raise — must return DEV_UNKNOWN."""
        m = self._manifest("1.2.3")
        result = compare_versions("0.0.0.dev0", m)
        self.assertEqual(result, VersionComparisonResult.DEV_UNKNOWN,
                         "PEP 440 dev form must classify as DEV_UNKNOWN, not raise ValueError")

    def test_pep440_dev_plus_sha_does_not_crash(self):
        """PEP 440 '1.0.0.dev5+gabcdef' must not raise — must return DEV_UNKNOWN."""
        m = self._manifest("1.2.3")
        result = compare_versions("1.0.0.dev5+gabcdef", m)
        self.assertEqual(result, VersionComparisonResult.DEV_UNKNOWN,
                         "PEP 440 local form must classify as DEV_UNKNOWN, not raise ValueError")

    def test_pep440_dev_never_reported_as_stale(self):
        """PEP 440 dev versions must never return STALE regardless of manifest version."""
        m = self._manifest("99.99.99")
        result = compare_versions("0.0.0.dev0", m)
        self.assertNotEqual(result, VersionComparisonResult.STALE,
                            "PEP 440 dev version must never be reported as STALE")


# ---------------------------------------------------------------------------
# verify_sha256
# ---------------------------------------------------------------------------

class TestVerifySha256(unittest.TestCase):

    def test_correct_hash_returns_true(self):
        content = b"hello release"
        expected = hashlib.sha256(content).hexdigest()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            fname = f.name
        self.assertTrue(verify_sha256(fname, expected))

    def test_wrong_hash_returns_false(self):
        content = b"hello release"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            fname = f.name
        self.assertFalse(verify_sha256(fname, "0" * 64))

    def test_case_insensitive_comparison(self):
        content = b"case test"
        expected = hashlib.sha256(content).hexdigest().upper()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            fname = f.name
        self.assertTrue(verify_sha256(fname, expected))


# ---------------------------------------------------------------------------
# fetch_manifest (mocked)
# ---------------------------------------------------------------------------

class TestFetchManifest(unittest.TestCase):

    def _mock_urlopen(self, body: str, status: int = 200):
        """Return a context manager mock that yields a file-like object."""
        response = MagicMock()
        response.read.return_value = body.encode("utf-8")
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)
        return response

    def test_successful_fetch_returns_manifest(self):
        raw = _manifest_json()
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(raw)):
            m = fetch_manifest("https://example.com/latest.json")
        self.assertEqual(m.version, "1.2.3")

    def test_http_error_raises_fetch_error(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "https://example.com/latest.json", 404, "Not Found", {}, None
            ),
        ):
            with self.assertRaises(FetchError) as cm:
                fetch_manifest("https://example.com/latest.json")
        self.assertIn("404", str(cm.exception))

    def test_url_error_raises_fetch_error(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(FetchError):
                fetch_manifest("https://example.com/latest.json")

    def test_honors_env_var_url(self):
        raw = _manifest_json()
        captured_urls = []

        def fake_urlopen(url, timeout=None):
            captured_urls.append(url)
            return self._mock_urlopen(raw)

        import os
        orig = os.environ.get("Z_HARNESS_RELEASE_URL")
        try:
            os.environ["Z_HARNESS_RELEASE_URL"] = "https://mirror.example.com/latest.json"
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                fetch_manifest()  # no explicit URL — should use env var
        finally:
            if orig is None:
                os.environ.pop("Z_HARNESS_RELEASE_URL", None)
            else:
                os.environ["Z_HARNESS_RELEASE_URL"] = orig

        self.assertIn("https://mirror.example.com/latest.json", captured_urls)

    def test_newer_schema_in_fetched_manifest_raises_schema_error(self):
        raw = _manifest_json(schema_version=SUPPORTED_SCHEMA_VERSION + 1)
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(raw)):
            with self.assertRaises(ManifestSchemaError):
                fetch_manifest("https://example.com/latest.json")


# ---------------------------------------------------------------------------
# install.run integration (mocked manifest fetch)
# ---------------------------------------------------------------------------

class TestInstallRun(unittest.TestCase):
    """Test the install command wrapper's manifest-backed tarball arguments."""

    def test_manifest_tarball_sha256_passed_to_install_sh(self):
        import z_harness_cli.commands.install as install_mod

        manifest = _make_manifest(
            plugin_tarball_url="https://example.com/z-harness.tar.gz",
            plugin_tarball_sha256="c" * 64,
        )
        completed = MagicMock()
        completed.returncode = 0

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            with patch("z_harness_cli.commands.install._harness_root", return_value=root):
                with patch("z_harness_cli.commands.install._is_source_checkout", return_value=False):
                    with patch("z_harness_cli.commands.install.fetch_manifest", return_value=manifest):
                        with patch("subprocess.run", return_value=completed) as mock_run:
                            install_mod.run(
                                MagicMock(),
                                target="claude",
                                tarball=None,
                                force=False,
                                generate_exports=False,
                            )

        args = mock_run.call_args.args[0]
        self.assertIn("--tarball=https://example.com/z-harness.tar.gz", args)
        self.assertIn("--tarball-sha256=" + ("c" * 64), args)


# ---------------------------------------------------------------------------
# update.run integration (mocked fetch)
# ---------------------------------------------------------------------------

class TestUpdateRun(unittest.TestCase):
    """Test the update command's run() with mocked manifest fetch."""

    def _run_update(self, installed_version: str, manifest_version: str,
                    schema_version: int = SUPPORTED_SCHEMA_VERSION,
                    expect_exit_code: int = 0):
        """Helper: patch __version__ + fetch_manifest, call run(), capture output.

        Mocks _is_uv_tool_install to False and _detect_plugin_install to an
        unknown non-uv payload so stale-notice tests never invoke the real uv
        or git update paths.
        """
        import typer

        raw = _manifest_json(version=manifest_version, schema_version=schema_version)
        manifest = parse_manifest(raw) if schema_version <= SUPPORTED_SCHEMA_VERSION else None

        import z_harness_cli.commands.update as update_mod

        output_lines = []

        def fake_echo(msg="", err=False, **kw):
            output_lines.append(msg)

        mock_ctx = MagicMock()

        with patch.object(update_mod, "__version__", installed_version, create=True):
            with patch("z_harness_cli.commands.update.__version__", installed_version):
                # Always mock install mode so no subprocess is spawned.
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=False), patch(
                    "z_harness_cli.commands.update._detect_plugin_install",
                    return_value=update_mod.PluginInstall("unknown", None, None),
                ):
                    if schema_version > SUPPORTED_SCHEMA_VERSION:
                        exc = ManifestSchemaError(
                            f"schema_version {schema_version} is newer. update z-harness"
                        )
                        with patch("z_harness_cli.commands.update.fetch_manifest",
                                   side_effect=exc):
                            with patch("typer.echo", side_effect=fake_echo):
                                try:
                                    update_mod.run(mock_ctx)
                                except (SystemExit, typer.Exit) as e:
                                    code = e.code if isinstance(e, SystemExit) else e.exit_code
                                    if expect_exit_code != 0:
                                        self.assertEqual(code, expect_exit_code)
                    else:
                        with patch("z_harness_cli.commands.update.fetch_manifest",
                                   return_value=manifest):
                            with patch("typer.echo", side_effect=fake_echo):
                                try:
                                    update_mod.run(mock_ctx)
                                except (SystemExit, typer.Exit) as e:
                                    code = e.code if isinstance(e, SystemExit) else e.exit_code
                                    if expect_exit_code != 0:
                                        self.assertEqual(code, expect_exit_code)
        return output_lines

    def test_equal_version_is_noop(self):
        """Equal installed and manifest version → prints 'up to date', no upgrade."""
        lines = self._run_update("1.2.3", "1.2.3")
        combined = " ".join(lines).lower()
        self.assertIn("up to date", combined)

    def test_stale_install_prints_notice(self):
        """Older installed version → prints a notice about newer version."""
        lines = self._run_update("1.0.0", "2.0.0")
        combined = " ".join(lines).lower()
        self.assertTrue(
            "newer" in combined or "available" in combined or "2.0.0" in combined,
            f"Expected stale notice in output, got: {lines}",
        )

    def test_newer_manifest_schema_exits_1(self):
        """Manifest schema_version > supported → exit 1, not a hang or silent pass."""
        import typer
        mock_ctx = MagicMock()
        import z_harness_cli.commands.update as update_mod

        exc = ManifestSchemaError("schema_version 999 is newer. update z-harness")
        output_lines = []

        def fake_echo(msg="", err=False, **kw):
            output_lines.append(msg)

        with patch("z_harness_cli.commands.update.fetch_manifest", side_effect=exc):
            with patch("typer.echo", side_effect=fake_echo):
                # typer.Exit is a click.exceptions.Exit, not SystemExit.
                with self.assertRaises(typer.Exit) as cm:
                    update_mod.run(mock_ctx)
        self.assertEqual(cm.exception.exit_code, 1,
                         "ManifestSchemaError must cause exit code 1")
        combined = " ".join(str(l) for l in output_lines).lower()
        self.assertIn("update z-harness", combined,
                      "Error message must direct the user to 'update z-harness'")

    def test_dev_sha_gets_notice_not_blocked(self):
        """Dev SHA install → notice printed, never exits non-zero."""
        import typer
        import z_harness_cli.commands.update as update_mod
        mock_ctx = MagicMock()
        output_lines = []

        def fake_echo(msg="", err=False, **kw):
            output_lines.append(str(msg))

        manifest = _make_manifest(version="1.5.0")
        with patch("z_harness_cli.commands.update.__version__", "abc1234"):
            with patch("z_harness_cli.commands.update.fetch_manifest",
                       return_value=manifest):
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=False):
                    with patch("typer.echo", side_effect=fake_echo):
                        # Must not raise typer.Exit with non-zero code.
                        try:
                            update_mod.run(mock_ctx)
                        except typer.Exit as e:
                            self.assertEqual(
                                e.exit_code, 0,
                                f"Dev SHA install must not exit non-zero (got {e.exit_code})",
                            )
        combined = " ".join(output_lines).lower()
        self.assertIn("git pull --ff-only", combined)
        self.assertIn("z-harness install", combined)

    def test_fetch_error_exits_1(self):
        """Network error on fetch → clean exit 1."""
        import typer
        import z_harness_cli.commands.update as update_mod
        mock_ctx = MagicMock()
        output_lines = []

        def fake_echo(msg="", err=False, **kw):
            output_lines.append(str(msg))

        with patch("z_harness_cli.commands.update.fetch_manifest",
                   side_effect=FetchError("connection refused")):
            with patch("typer.echo", side_effect=fake_echo):
                # typer.Exit is a click exception, not SystemExit.
                with self.assertRaises(typer.Exit) as cm:
                    update_mod.run(mock_ctx)
        self.assertEqual(cm.exception.exit_code, 1)

    def test_pep440_dev_version_gets_notice_not_blocked(self):
        """PEP 440 dev version (0.0.0.dev0) → notice printed, never exits non-zero."""
        import typer
        import z_harness_cli.commands.update as update_mod
        mock_ctx = MagicMock()
        output_lines = []

        def fake_echo(msg="", err=False, **kw):
            output_lines.append(str(msg))

        manifest = _make_manifest(version="1.5.0")
        with patch("z_harness_cli.commands.update.__version__", "0.0.0.dev0"):
            with patch("z_harness_cli.commands.update.fetch_manifest",
                       return_value=manifest):
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=False):
                    with patch("typer.echo", side_effect=fake_echo):
                        try:
                            update_mod.run(mock_ctx)
                        except typer.Exit as e:
                            self.assertEqual(
                                e.exit_code, 0,
                                f"PEP 440 dev install must not exit non-zero (got {e.exit_code})",
                            )
        combined = " ".join(output_lines).lower()
        self.assertIn("not a tagged release", combined)
        self.assertIn("git pull --ff-only", combined)
        self.assertIn("z-harness install", combined)

    def test_tarball_install_exits_1_with_manifest_backed_reinstall_path(self):
        """Tarball installs must route to deterministic reinstall, not host self-swap prose."""
        import typer
        import z_harness_cli.commands.update as update_mod
        mock_ctx = MagicMock()
        output_lines = []

        def fake_echo(msg="", err=False, **kw):
            output_lines.append(str(msg))

        manifest = _make_manifest(version="2.0.0")
        install = update_mod.PluginInstall("tarball", Path("/tmp/z-harness"), "claude")
        with patch("z_harness_cli.commands.update.__version__", "1.0.0"):
            with patch("z_harness_cli.commands.update.fetch_manifest",
                       return_value=manifest):
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=False), patch(
                    "z_harness_cli.commands.update._detect_plugin_install",
                    return_value=install,
                ):
                    with patch("typer.echo", side_effect=fake_echo):
                        with self.assertRaises(typer.Exit) as cm:
                            update_mod.run(mock_ctx)
        self.assertEqual(cm.exception.exit_code, 1,
                         "Non-uv install update must exit 1 (not silently no-op)")
        combined = " ".join(output_lines).lower()
        self.assertIn("z-harness install --target=claude --force", combined)
        self.assertIn("deterministic installer", combined)
        self.assertNotIn("run /z-update inside claude", combined)
        self.assertIn("python3 -m z_harness_cli install --target=claude --force", combined)
        self.assertNotIn("curl -fssl <install-url>", combined)

    def test_symlink_install_fast_forwards_clean_checkout(self):
        """Symlink/source installs update via git pull --ff-only in deterministic code."""
        import z_harness_cli.commands.update as update_mod

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        install = update_mod.PluginInstall("symlink", Path("/repo/z-harness"), "claude")
        with patch("subprocess.run", side_effect=fake_run), patch("typer.echo"):
            update_mod._apply_symlink_update(install)

        self.assertEqual(
            calls,
            [
                ["git", "-C", "/repo/z-harness", "status", "--porcelain"],
                ["git", "-C", "/repo/z-harness", "pull", "--ff-only"],
            ],
        )

    def test_symlink_install_dirty_checkout_aborts_before_pull(self):
        """Dirty source installs must be actionable and must not pull."""
        import typer
        import z_harness_cli.commands.update as update_mod

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = " M skills/z-update/SKILL.md\n"
            return result

        output_lines = []

        def fake_echo(msg="", err=False, **kw):
            output_lines.append(str(msg))

        install = update_mod.PluginInstall("symlink", Path("/repo/z-harness"), "claude")
        with patch("subprocess.run", side_effect=fake_run), patch("typer.echo", side_effect=fake_echo):
            with self.assertRaises(typer.Exit) as cm:
                update_mod._apply_symlink_update(install)

        self.assertEqual(cm.exception.exit_code, 1)
        self.assertEqual(calls, [["git", "-C", "/repo/z-harness", "status", "--porcelain"]])
        combined = " ".join(output_lines).lower()
        self.assertIn("uncommitted changes", combined)
        self.assertIn("commit or stash", combined)

    def test_z_update_skill_delegates_security_logic_to_cli(self):
        """Skill prose must not duplicate manifest parsing or checksum implementation."""
        skill = (REPO_ROOT / "skills" / "z-update" / "SKILL.md").read_text(encoding="utf-8")
        forbidden = (
            "checksum",
            "plugin_tarball_sha256",
            "sha256sum",
            "shasum -a 256",
            "curl -fsSL \"$RELEASE_URL\"",
            "tar -xzf \"$TMP_TARBALL\"",
        )
        for needle in forbidden:
            self.assertNotIn(needle, skill)

    def test_uv_upgrade_sha256_mismatch_aborts(self):
        """SHA256 mismatch during uv upgrade → exit 1, wheel NOT installed (F9)."""
        import hashlib
        import typer
        import z_harness_cli.commands.update as update_mod
        mock_ctx = MagicMock()
        output_lines = []

        def fake_echo(msg="", err=False, **kw):
            output_lines.append(str(msg))

        wheel_content = b"fake wheel bytes"
        wrong_sha = "0" * 64  # deliberately wrong
        manifest = _make_manifest(version="2.0.0", sha256=wrong_sha)

        subprocess_calls = []

        def fake_subprocess_run(cmd, **kw):
            subprocess_calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        def fake_urlopen(url, timeout=None):
            resp = MagicMock()
            resp.read.return_value = wheel_content
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("z_harness_cli.commands.update.__version__", "1.0.0"):
            with patch("z_harness_cli.commands.update.fetch_manifest",
                       return_value=manifest):
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=True):
                    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                        with patch("subprocess.run", side_effect=fake_subprocess_run):
                            with patch("typer.echo", side_effect=fake_echo):
                                with self.assertRaises(typer.Exit) as cm:
                                    update_mod.run(mock_ctx)

        self.assertEqual(cm.exception.exit_code, 1,
                         "SHA256 mismatch must exit 1 and abort install")
        self.assertEqual(subprocess_calls, [],
                         "uv must NOT be invoked when sha256 verification fails")
        combined = " ".join(output_lines).lower()
        self.assertTrue(
            "mismatch" in combined or "sha" in combined or "corrupt" in combined
            or "tamper" in combined,
            f"Expected sha256 failure message, got: {output_lines}",
        )

    def test_uv_upgrade_sha256_match_proceeds(self):
        """Correct SHA256 during uv upgrade → uv install is called (F9 happy path)."""
        import hashlib
        import typer
        import z_harness_cli.commands.update as update_mod
        mock_ctx = MagicMock()
        output_lines = []

        def fake_echo(msg="", err=False, **kw):
            output_lines.append(str(msg))

        wheel_content = b"fake wheel bytes"
        correct_sha = hashlib.sha256(wheel_content).hexdigest()
        manifest = _make_manifest(version="2.0.0", sha256=correct_sha)

        subprocess_calls = []

        def fake_subprocess_run(cmd, **kw):
            subprocess_calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        def fake_urlopen(url, timeout=None):
            resp = MagicMock()
            resp.read.return_value = wheel_content
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("z_harness_cli.commands.update.__version__", "1.0.0"):
            with patch("z_harness_cli.commands.update.fetch_manifest",
                       return_value=manifest):
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=True):
                    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                        with patch("subprocess.run", side_effect=fake_subprocess_run):
                            with patch("typer.echo", side_effect=fake_echo):
                                update_mod.run(mock_ctx)

        self.assertEqual(len(subprocess_calls), 1,
                         "uv must be invoked exactly once when sha256 matches")
        cmd = subprocess_calls[0]
        # Must install a local temp file, not the raw URL.
        self.assertTrue(
            cmd[0] == "uv" and "--upgrade" in cmd,
            f"Expected uv tool install --upgrade <local-path>, got: {cmd}",
        )
        installed_path = cmd[-1]
        self.assertTrue(
            installed_path.endswith(".whl") and not installed_path.startswith("http"),
            f"Must install from local file, not URL. Got: {installed_path}",
        )


    def test_uv_upgrade_sha256_mismatch_cleans_up_temp_file(self):
        """SHA256 mismatch → temp .whl file must be removed even though install is aborted."""
        import typer
        import z_harness_cli.commands.update as update_mod

        wheel_content = b"fake wheel bytes for mismatch cleanup test"
        wrong_sha = "0" * 64  # deliberately wrong
        manifest = _make_manifest(version="2.0.0", sha256=wrong_sha)

        captured_tmp_paths = []

        original_ntf = tempfile.NamedTemporaryFile

        def fake_ntf(*args, **kwargs):
            f = original_ntf(*args, **kwargs)
            captured_tmp_paths.append(f.name)
            return f

        def fake_urlopen(url, timeout=None):
            resp = MagicMock()
            resp.read.return_value = wheel_content
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        mock_ctx = MagicMock()

        with patch("z_harness_cli.commands.update.__version__", "1.0.0"):
            with patch("z_harness_cli.commands.update.fetch_manifest",
                       return_value=manifest):
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=True):
                    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                        with patch("tempfile.NamedTemporaryFile", side_effect=fake_ntf):
                            with patch("typer.echo"):
                                try:
                                    update_mod.run(mock_ctx)
                                except typer.Exit:
                                    pass

        self.assertTrue(len(captured_tmp_paths) > 0,
                        "Expected at least one temp file to have been created")
        for tmp_path in captured_tmp_paths:
            self.assertFalse(
                os.path.exists(tmp_path),
                f"Temp file {tmp_path!r} was not cleaned up after sha256 mismatch",
            )

    def test_uv_upgrade_success_cleans_up_temp_file(self):
        """Successful uv upgrade → temp .whl file must be removed after install."""
        import hashlib
        import typer
        import z_harness_cli.commands.update as update_mod

        wheel_content = b"fake wheel bytes for success cleanup test"
        correct_sha = hashlib.sha256(wheel_content).hexdigest()
        manifest = _make_manifest(version="2.0.0", sha256=correct_sha)

        captured_tmp_paths = []

        original_ntf = tempfile.NamedTemporaryFile

        def fake_ntf(*args, **kwargs):
            f = original_ntf(*args, **kwargs)
            captured_tmp_paths.append(f.name)
            return f

        def fake_urlopen(url, timeout=None):
            resp = MagicMock()
            resp.read.return_value = wheel_content
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        def fake_subprocess_run(cmd, **kw):
            result = MagicMock()
            result.returncode = 0
            return result

        mock_ctx = MagicMock()

        with patch("z_harness_cli.commands.update.__version__", "1.0.0"):
            with patch("z_harness_cli.commands.update.fetch_manifest",
                       return_value=manifest):
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=True):
                    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                        with patch("subprocess.run", side_effect=fake_subprocess_run):
                            with patch("tempfile.NamedTemporaryFile", side_effect=fake_ntf):
                                with patch("typer.echo"):
                                    update_mod.run(mock_ctx)

        self.assertTrue(len(captured_tmp_paths) > 0,
                        "Expected at least one temp file to have been created")
        for tmp_path in captured_tmp_paths:
            self.assertFalse(
                os.path.exists(tmp_path),
                f"Temp file {tmp_path!r} was not cleaned up after successful uv install",
            )


if __name__ == "__main__":
    unittest.main()
