"""Unit tests for z_harness_cli/release.py and commands/update.py.

Coverage:
- parse_release_candidate: stable/beta ecosystem renderings, round trips, ordering
- parse_manifest: valid, missing fields, wrong-typed fields
- schema_version newer than SUPPORTED → ManifestSchemaError (exit-1 path)
- compare_versions: stale / equal / newer / dev-SHA-unknown
- verify_sha256: matching and mismatching hash
- fetch_manifest: mocked urllib (success, HTTP 404, URLError)
- update.run: stale notice, equal no-op, newer-schema clean exit-1, sha-mismatch
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import zipfile
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
    ReleaseArtifactError,
    ReleaseManifest,
    ReleaseProvenanceError,
    VersionComparisonResult,
    compare_versions,
    fetch_manifest,
    is_dev_sha,
    parse_release_candidate,
    parse_manifest,
    verify_sha256,
    verify_release_artifacts,
    verify_publication_provenance,
    require_plugin_tarball_metadata,
)


# ---------------------------------------------------------------------------
# explicit release candidates
# ---------------------------------------------------------------------------

class TestReleaseCandidate(unittest.TestCase):

    def test_stable_candidate_renders_every_public_identity(self):
        candidate = parse_release_candidate("0.9.0")
        self.assertEqual(candidate.git_tag, "v0.9.0")
        self.assertEqual(candidate.plugin_version, "0.9.0")
        self.assertEqual(candidate.wheel_version, "0.9.0")
        self.assertEqual(candidate.tarball_version, "0.9.0")
        self.assertEqual(candidate.latest_json_version, "0.9.0")
        self.assertEqual(str(candidate.comparison_version), "0.9.0")

    def test_beta_candidate_renders_semver_and_pep440_identities(self):
        candidate = parse_release_candidate("0.9.0-beta.2")
        self.assertEqual(candidate.git_tag, "v0.9.0-beta.2")
        self.assertEqual(candidate.plugin_version, "0.9.0-beta.2")
        self.assertEqual(candidate.wheel_version, "0.9.0b2")
        self.assertEqual(candidate.tarball_version, "0.9.0-beta.2")
        self.assertEqual(candidate.latest_json_version, "0.9.0-beta.2")

    def test_tag_semver_and_pep440_beta_forms_are_equivalent(self):
        expected = parse_release_candidate("0.9.0-beta.2")
        self.assertEqual(parse_release_candidate("v0.9.0-beta.2"), expected)
        self.assertEqual(parse_release_candidate("0.9.0b2"), expected)

    def test_every_rendered_version_round_trips(self):
        for source in ("2.4.1", "2.4.1-beta.10"):
            candidate = parse_release_candidate(source)
            for rendered in (
                candidate.git_tag,
                candidate.plugin_version,
                candidate.wheel_version,
                candidate.tarball_version,
                candidate.latest_json_version,
            ):
                with self.subTest(source=source, rendered=rendered):
                    self.assertEqual(parse_release_candidate(rendered), candidate)

    def test_beta_numeric_order_precedes_stable(self):
        beta_two = parse_release_candidate("1.0.0-beta.2")
        beta_ten = parse_release_candidate("1.0.0-beta.10")
        stable = parse_release_candidate("1.0.0")
        self.assertLess(beta_two, beta_ten)
        self.assertLess(beta_ten, stable)

    def test_invalid_candidate_spellings_are_rejected(self):
        invalid = (
            "",
            " 1.2.3",
            "1.2",
            "01.2.3",
            "1.02.3",
            "1.2.03",
            "1.2.3-beta",
            "1.2.3-beta.01",
            "1.2.3-alpha.1",
            "1.2.3-rc.1",
            "1.2.3+build.1",
            "1.2.3.dev1",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_release_candidate(value)


class TestPublicationProvenance(unittest.TestCase):

    def test_exact_canonical_tag_checkout_and_prod_tip_are_accepted(self):
        commit = "a" * 40

        candidate = verify_publication_provenance(
            "2.4.1-beta.10",
            "v2.4.1-beta.10",
            commit,
            commit,
            commit,
        )

        self.assertEqual(candidate.plugin_version, "2.4.1-beta.10")

    def test_noncanonical_or_wrong_tag_is_rejected(self):
        commit = "a" * 40

        with self.assertRaisesRegex(ReleaseProvenanceError, "not canonical"):
            verify_publication_provenance("2.4.1", "2.4.1", commit, commit, commit)

    def test_wrong_workflow_sha_is_rejected(self):
        commit = "a" * 40

        with self.assertRaisesRegex(ReleaseProvenanceError, "GITHUB_SHA"):
            verify_publication_provenance(
                "2.4.1",
                "v2.4.1",
                commit,
                "b" * 40,
                commit,
            )

    def test_abbreviated_or_missing_commit_is_rejected(self):
        commit = "a" * 40

        with self.assertRaisesRegex(ReleaseProvenanceError, "full lowercase"):
            verify_publication_provenance(
                "2.4.1",
                "v2.4.1",
                "a" * 12,
                commit,
                commit,
            )

    def test_stale_prod_tip_is_rejected(self):
        commit = "a" * 40

        with self.assertRaisesRegex(ReleaseProvenanceError, "prod tip"):
            verify_publication_provenance(
                "2.4.1",
                "v2.4.1",
                commit,
                commit,
                "b" * 40,
            )


def _write_release_artifact_fixture(
    root: Path,
    version: str,
    *,
    install_script: bytes = b"public installer\n",
) -> tuple[Path, Path]:
    """Write the smallest complete assembled output accepted by the verifier."""

    candidate = parse_release_candidate(version)
    wheel = root / f"z_harness-{candidate.wheel_version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr(
            f"z_harness-{candidate.wheel_version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: z-harness\nVersion: {candidate.wheel_version}\n",
        )
        archive.writestr(
            ".codex-plugin/plugin.json",
            json.dumps({"name": "z-harness", "version": candidate.plugin_version}),
        )
    tarball = root / f"z-harness-{candidate.tarball_version}.tar.gz"
    plugin_body = json.dumps({"name": "z-harness", "version": candidate.plugin_version}).encode()
    with tarfile.open(tarball, mode="w:gz") as archive:
        info = tarfile.TarInfo(".codex-plugin/plugin.json")
        info.size = len(plugin_body)
        archive.addfile(info, io.BytesIO(plugin_body))
    (root / "install.sh").write_bytes(install_script)
    (root / "install-plugin.sh").write_text("plugin installer\n", encoding="utf-8")
    wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    tarball_digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    latest = {
        "schema_version": 1,
        "version": candidate.latest_json_version,
        "wheel_url": f"https://example.invalid/{wheel.name}",
        "sha256": wheel_digest,
        "plugin_tarball_url": f"https://example.invalid/{tarball.name}",
        "plugin_tarball_sha256": tarball_digest,
        "cli_schema_version": 1,
        "telemetry_schema_version": 1,
        "min_supported_version": "0.1.0",
    }
    (root / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    artifact_paths = (wheel, tarball, root / "install.sh", root / "install-plugin.sh")
    assets = {
        "schema_version": 1,
        "candidate_version": candidate.plugin_version,
        "candidate_commit": "a" * 40,
        "artifacts": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifact_paths
        },
    }
    (root / "release-assets.json").write_text(json.dumps(assets), encoding="utf-8")
    checksum_paths = (*artifact_paths, root / "latest.json", root / "release-assets.json")
    (root / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in checksum_paths
        ),
        encoding="utf-8",
    )
    return wheel, tarball


class TestReleaseArtifactVerification(unittest.TestCase):
    def test_stable_and_beta_artifacts_match_explicit_candidate(self):
        for version in ("2.4.1", "2.4.1-beta.10"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_release_artifact_fixture(root, version)
                verify_release_artifacts(root, version)

    def test_wrong_wheel_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel, _ = _write_release_artifact_fixture(root, "2.4.1")
            with zipfile.ZipFile(wheel, mode="w") as archive:
                archive.writestr(
                    "z_harness-9.9.9.dist-info/METADATA",
                    "Metadata-Version: 2.1\nName: z-harness\nVersion: 9.9.9\n",
                )
                archive.writestr(
                    ".codex-plugin/plugin.json",
                    json.dumps({"name": "z-harness", "version": "2.4.1"}),
                )
            with self.assertRaisesRegex(ReleaseArtifactError, "wheel metadata version"):
                verify_release_artifacts(root, "2.4.1")

    def test_wrong_shipped_plugin_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel, _ = _write_release_artifact_fixture(root, "2.4.1-beta.2")
            with zipfile.ZipFile(wheel, mode="w") as archive:
                archive.writestr(
                    "z_harness-2.4.1b2.dist-info/METADATA",
                    "Metadata-Version: 2.1\nName: z-harness\nVersion: 2.4.1b2\n",
                )
                archive.writestr(
                    ".codex-plugin/plugin.json",
                    json.dumps({"name": "z-harness", "version": "2.4.1-beta.3"}),
                )
            with self.assertRaisesRegex(ReleaseArtifactError, "plugin manifest version"):
                verify_release_artifacts(root, "2.4.1-beta.2")

    def test_wrong_tarball_basename_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, tarball = _write_release_artifact_fixture(root, "2.4.1")
            tarball.rename(root / "z-harness-9.9.9.tar.gz")
            with self.assertRaisesRegex(ReleaseArtifactError, "tarball basename"):
                verify_release_artifacts(root, "2.4.1")

    def test_wrong_latest_identity_url_or_digest_is_rejected(self):
        mutations = {
            "version": "9.9.9",
            "wheel_url": "https://example.invalid/wrong.whl",
            "sha256": "0" * 64,
        }
        for field, value in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_release_artifact_fixture(root, "2.4.1")
                path = root / "latest.json"
                latest = json.loads(path.read_text(encoding="utf-8"))
                latest[field] = value
                path.write_text(json.dumps(latest), encoding="utf-8")
                with self.assertRaises(ReleaseArtifactError):
                    verify_release_artifacts(root, "2.4.1")

    def test_wrong_produced_artifact_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_release_artifact_fixture(root, "2.4.1")
            assets_path = root / "release-assets.json"
            assets = json.loads(assets_path.read_text(encoding="utf-8"))
            assets["artifacts"]["install.sh"] = "0" * 64
            assets_path.write_text(json.dumps(assets), encoding="utf-8")
            with self.assertRaisesRegex(ReleaseArtifactError, "asset digest mismatch"):
                verify_release_artifacts(root, "2.4.1")


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
    plugin_tarball_url: str | None = "https://example.com/z-harness-1.2.3.tar.gz",
    plugin_tarball_sha256: str | None = "b" * 64,
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
        self.assertEqual(m.plugin_tarball_url, "https://example.com/z-harness-1.2.3.tar.gz")
        self.assertEqual(m.plugin_tarball_sha256, "b" * 64)

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

    def test_missing_plugin_tarball_url_raises(self):
        raw = _manifest_json(
            plugin_tarball_url=None,
            plugin_tarball_sha256="b" * 64,
        )
        with self.assertRaises(ManifestParseError):
            parse_manifest(raw)

    def test_plugin_tarball_requires_sha(self):
        raw = _manifest_json(
            plugin_tarball_url="https://example.com/z-harness.tar.gz",
            plugin_tarball_sha256=None,
        )
        with self.assertRaises(ManifestParseError):
            parse_manifest(raw)

    def test_plugin_tarball_rejects_malformed_sha(self):
        raw = _manifest_json(plugin_tarball_sha256="not-a-digest")
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
        m = ReleaseManifest(
            schema_version=SUPPORTED_SCHEMA_VERSION,
            version="1.2.3",
            wheel_url="https://example.com/z-harness.whl",
            sha256="a" * 64,
            cli_schema_version=1,
            telemetry_schema_version=1,
            min_supported_version="1.0.0",
            plugin_tarball_url="",
            plugin_tarball_sha256="",
        )
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

    def test_semver_beta_equals_pep440_beta(self):
        m = self._manifest("1.2.3-beta.2")
        self.assertEqual(compare_versions("1.2.3b2", m), VersionComparisonResult.EQUAL)

    def test_beta_numeric_order_is_not_lexical(self):
        m = self._manifest("1.2.3-beta.10")
        self.assertEqual(compare_versions("1.2.3-beta.2", m), VersionComparisonResult.STALE)

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

    def setUp(self):
        """Isolate component discovery from the developer's actual HOME."""

        self._home = tempfile.TemporaryDirectory()
        self._environment = patch.dict(
            os.environ,
            {
                "HOME": self._home.name,
                "XDG_STATE_HOME": str(Path(self._home.name) / ".local" / "state"),
                "CLAUDE_PLUGIN_ROOT": "",
                "ANTIGRAVITY_PLUGIN_ROOT": "",
                "OMP_PLUGIN_ROOT": "",
                "Z_HARNESS_PLUGIN_ROOT": "",
            },
        )
        self._environment.start()

    def tearDown(self):
        """Restore the process environment after each lifecycle test."""

        self._environment.stop()
        self._home.cleanup()

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

    def test_equal_cli_does_not_mask_stale_packaged_payload(self):
        """C4 criterion #6: a current CLI cannot terminate before host comparison."""

        import z_harness_cli.commands.update as update_mod

        manifest = _make_manifest(version="2.0.0")
        components = (
            update_mod.ComponentInventory("cli", "uv-tool", Path("/tool/python"), "2.0.0"),
            update_mod.ComponentInventory("claude", "packaged", Path("/claude"), "1.0.0"),
            update_mod.ComponentInventory("codex", "missing", Path("/codex"), None),
        )
        with patch("z_harness_cli.commands.update._apply_packaged_transaction") as apply:
            update_mod._apply_detected_transaction(manifest, components)

        apply.assert_called_once_with(manifest, [components[1]], replace_cli=False)

    def test_clean_duplicate_symlink_hosts_fast_forward_once(self):
        """C4 criterion #8: aliases resolving to one checkout are deduplicated."""

        import z_harness_cli.commands.update as update_mod

        manifest = _make_manifest(version="2.0.0")
        checkout = Path("/repo/z-harness")
        components = (
            update_mod.ComponentInventory("cli", "executable", Path("/bin/z-harness"), "2.0.0"),
            update_mod.ComponentInventory("claude", "symlink", checkout, "1.0.0"),
            update_mod.ComponentInventory("codex", "symlink", checkout, "1.0.0"),
        )
        with patch("z_harness_cli.commands.update._apply_symlink_update") as apply:
            update_mod._apply_detected_transaction(manifest, components)

        apply.assert_called_once()
        install = apply.call_args.args[0]
        self.assertEqual(install.root, checkout)
        self.assertEqual(install.target, "all")

    def test_stale_executable_cli_and_symlink_host_fail_before_mutation(self):
        """B1: an uncompletable mixed-mode plan cannot mutate its host first."""

        import typer
        import z_harness_cli.commands.update as update_mod

        manifest = _make_manifest(version="2.0.0")
        checkout = Path("/repo/z-harness")
        components = (
            update_mod.ComponentInventory("cli", "executable", Path("/bin/z-harness"), "1.0.0"),
            update_mod.ComponentInventory("claude", "symlink", checkout, "1.0.0"),
            update_mod.ComponentInventory("codex", "missing", Path("/codex"), None),
        )
        with patch("z_harness_cli.commands.update._apply_symlink_update") as apply:
            with self.assertRaises(typer.Exit) as raised:
                update_mod._apply_detected_transaction(manifest, components)

        self.assertEqual(raised.exception.exit_code, 1)
        apply.assert_not_called()

    def test_newer_cli_and_candidate_current_host_fail_closed(self):
        """M1: a mixed newer/current component set is never reported coherent."""

        import typer
        import z_harness_cli.commands.update as update_mod

        manifest = _make_manifest(version="2.0.0")
        components = (
            update_mod.ComponentInventory("cli", "executable", Path("/bin/z-harness"), "3.0.0"),
            update_mod.ComponentInventory("claude", "packaged", Path("/claude"), "2.0.0"),
            update_mod.ComponentInventory("codex", "missing", Path("/codex"), None),
        )
        messages: list[str] = []
        with patch("typer.echo", side_effect=lambda message="", **_: messages.append(str(message))):
            with self.assertRaises(typer.Exit) as raised:
                update_mod._apply_detected_transaction(manifest, components)

        self.assertEqual(raised.exception.exit_code, 1)
        self.assertFalse(any("up to date" in message.lower() for message in messages))
        self.assertTrue(any("downgrade" in message.lower() for message in messages))

    def test_lock_publication_window_has_exactly_one_owner(self):
        """B5: a fresh mkdir without PID is initializing, never stale."""

        import z_harness_cli.commands.update as update_mod

        published = threading.Event()
        release_publication = threading.Event()
        original_write = update_mod._atomic_write_text
        acquired: list[Path] = []
        failures: list[BaseException] = []

        def paused_write(path: Path, value: str) -> None:
            if path.name == "owner.json" and not published.is_set():
                published.set()
                release_publication.wait(timeout=10)
            original_write(path, value)

        def first_acquirer() -> None:
            try:
                acquired.append(update_mod._acquire_lifecycle_lock())
            except BaseException as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        with patch("z_harness_cli.commands.update._atomic_write_text", side_effect=paused_write):
            first = threading.Thread(target=first_acquirer)
            first.start()
            self.assertTrue(published.wait(timeout=10))
            second = threading.Thread(target=first_acquirer)
            second.start()
            release_publication.set()
            first.join(timeout=10)
            second.join(timeout=10)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(failures), 1)
        self.assertEqual(len(acquired), 1)
        update_mod._release_lifecycle_lock(acquired[0])

    def test_parent_to_shell_handoff_preserves_live_child_ownership(self):
        """B2: only a published child identity may retain delegated mutation ownership."""

        import z_harness_cli.commands.update as update_mod

        lock = update_mod._acquire_lifecycle_lock()
        token = update_mod._HELD_LOCK_TOKENS[lock]
        child = subprocess.Popen(["/bin/sleep", "30"])
        try:
            with patch("z_harness_cli.commands.update.time.sleep", return_value=None):
                self.assertFalse(update_mod._accept_lifecycle_handoff(lock, token, child.pid))
            update_mod._handoff_lifecycle_lock(lock, token, child.pid)
            self.assertTrue(update_mod._accept_lifecycle_handoff(lock, token, child.pid))
            update_mod._release_lifecycle_lock(lock)
            self.assertTrue(lock.exists())
            with self.assertRaisesRegex(RuntimeError, "active pid"):
                update_mod._acquire_lifecycle_lock()
        finally:
            child.terminate()
            child.wait()
        replacement = update_mod._acquire_lifecycle_lock()
        update_mod._release_lifecycle_lock(replacement)

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
                ), patch(
                    "z_harness_cli.commands.update.inventory_components",
                    return_value=(
                        update_mod.ComponentInventory("cli", "executable", Path("/bin/z-harness"), "1.0.0"),
                        update_mod.ComponentInventory("claude", "missing", Path("/claude"), None),
                        update_mod.ComponentInventory("codex", "missing", Path("/codex"), None),
                    ),
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

    def test_clean_symlink_path_fast_forwards_real_checkout(self):
        """C4 criterion #8: the accepted source path succeeds via real ff-only git."""

        import subprocess
        import z_harness_cli.commands.update as update_mod

        root = Path(self._home.name) / "git-case"
        root.mkdir()
        try:
            origin = root / "origin.git"
            seed = root / "seed"
            installed = root / "installed"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "config", "user.name", "Lifecycle Test"], check=True)
            subprocess.run(["git", "-C", str(seed), "config", "user.email", "lifecycle@example.invalid"], check=True)
            (seed / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(seed), "add", "VERSION"], check=True)
            subprocess.run(["git", "-C", str(seed), "commit", "-m", "v1"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "push", "origin", "HEAD"], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(origin), str(installed)], check=True, capture_output=True)
            (seed / "VERSION").write_text("2.0.0\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(seed), "commit", "-am", "v2"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "tag", "v2.0.0"], check=True)
            subprocess.run(["git", "-C", str(seed), "push", "origin", "v2.0.0"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "push"], check=True, capture_output=True)

            with patch("typer.echo"):
                update_mod._apply_symlink_update(
                    update_mod.PluginInstall("symlink", installed, "claude"),
                    _make_manifest(version="2.0.0"),
                )

            self.assertEqual((installed / "VERSION").read_text(encoding="utf-8"), "2.0.0\n")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_source_update_rejects_upstream_identity_beyond_candidate(self):
        """B3: remote branch head cannot choose an identity beyond the manifest."""

        import subprocess
        import typer
        import z_harness_cli.commands.update as update_mod

        root = Path(self._home.name) / "mismatch-case"
        root.mkdir()
        origin = root / "origin.git"
        seed = root / "seed"
        installed = root / "installed"
        subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "config", "user.name", "Lifecycle Test"], check=True)
        subprocess.run(["git", "-C", str(seed), "config", "user.email", "lifecycle@example.invalid"], check=True)
        (seed / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(seed), "add", "VERSION"], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "-m", "v1"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "push", "origin", "HEAD"], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(origin), str(installed)], check=True, capture_output=True)
        (seed / "VERSION").write_text("3.0.0\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(seed), "commit", "-am", "v3"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "push"], check=True, capture_output=True)

        with patch("typer.echo"):
            with self.assertRaises(typer.Exit):
                update_mod._apply_symlink_update(
                    update_mod.PluginInstall("symlink", installed, "claude"),
                    _make_manifest(version="2.0.0"),
                )
        self.assertEqual((installed / "VERSION").read_text(encoding="utf-8"), "1.0.0\n")

    def test_source_update_stops_at_exact_tag_before_same_version_branch_commit(self):
        """B2: branch commits after the candidate tag never define release identity."""

        import subprocess
        import z_harness_cli.commands.update as update_mod

        root = Path(self._home.name) / "tag-pin-case"
        root.mkdir()
        origin = root / "origin.git"
        seed = root / "seed"
        installed = root / "installed"
        subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "config", "user.name", "Lifecycle Test"], check=True)
        subprocess.run(["git", "-C", str(seed), "config", "user.email", "lifecycle@example.invalid"], check=True)
        (seed / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(seed), "add", "VERSION"], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "-m", "v1"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "push", "origin", "HEAD"], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(origin), str(installed)], check=True, capture_output=True)
        (seed / "VERSION").write_text("2.0.0\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(seed), "commit", "-am", "release v2"], check=True, capture_output=True)
        tagged_head = subprocess.run(
            ["git", "-C", str(seed), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        subprocess.run(["git", "-C", str(seed), "tag", "v2.0.0"], check=True)
        (seed / "POST_TAG").write_text("must not install\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(seed), "add", "POST_TAG"], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "-m", "post tag"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(seed), "push", "origin", "HEAD", "v2.0.0"], check=True, capture_output=True)

        with patch("typer.echo"):
            update_mod._apply_symlink_update(
                update_mod.PluginInstall("symlink", installed, "claude"),
                _make_manifest(version="2.0.0"),
            )

        installed_head = subprocess.run(
            ["git", "-C", str(installed), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(installed_head, tagged_head)
        self.assertFalse((installed / "POST_TAG").exists())

    def test_codex_inventory_ignores_unrelated_export_roots(self):
        """B4: Codex always binds to the supported HOME mutation destination."""

        import z_harness_cli.commands.update as update_mod

        home = Path(self._home.name)
        actual = home / "plugins" / "z-harness"
        unrelated = home / "antigravity"
        for root, version in ((actual, "1.0.0"), (unrelated, "2.0.0")):
            (root / "skills").mkdir(parents=True)
            (root / "agents").mkdir()
            (root / "VERSION").write_text(version + "\n", encoding="utf-8")
        with patch.dict(
            os.environ,
            {"ANTIGRAVITY_PLUGIN_ROOT": str(unrelated), "OMP_PLUGIN_ROOT": str(unrelated)},
        ):
            _, _, codex = update_mod.inventory_components()
        self.assertEqual(codex.location, actual.resolve())
        self.assertEqual(codex.version, "1.0.0")

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
            result.stdout = "z-harness 2.0.0\n" if cmd[-1] == "--version" else ""
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
            result.stdout = "z-harness 2.0.0\n" if cmd[-1] == "--version" else ""
            return result

        def fake_urlopen(url, timeout=None):
            resp = MagicMock()
            resp.read.return_value = wheel_content
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        tool_root = Path(self._home.name) / ".local" / "share" / "uv" / "tools" / "z-harness"
        tool_root.mkdir(parents=True)
        (tool_root / "old.txt").write_text("old\n", encoding="utf-8")
        launcher = Path(self._home.name) / ".local" / "bin" / "z-harness"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("old launcher\n", encoding="utf-8")

        with patch("z_harness_cli.commands.update.__version__", "1.0.0"):
            with patch("z_harness_cli.commands.update.fetch_manifest",
                       return_value=manifest):
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=True):
                    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                        with patch("subprocess.run", side_effect=fake_subprocess_run), patch.object(
                            update_mod.sys, "prefix", str(tool_root)
                        ), patch("z_harness_cli.commands.update.shutil.which", return_value=str(launcher)):
                            with patch("typer.echo", side_effect=fake_echo):
                                update_mod.run(mock_ctx)

        self.assertEqual(len(subprocess_calls), 2,
                         "uv install and post-install version verification must both run")
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
            result.stdout = "z-harness 2.0.0\n" if cmd[-1] == "--version" else ""
            return result

        mock_ctx = MagicMock()
        tool_root = Path(self._home.name) / ".local" / "share" / "uv" / "tools" / "z-harness"
        tool_root.mkdir(parents=True)
        (tool_root / "old.txt").write_text("old\n", encoding="utf-8")
        launcher = Path(self._home.name) / ".local" / "bin" / "z-harness"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("old launcher\n", encoding="utf-8")

        with patch("z_harness_cli.commands.update.__version__", "1.0.0"):
            with patch("z_harness_cli.commands.update.fetch_manifest",
                       return_value=manifest):
                with patch("z_harness_cli.commands.update._is_uv_tool_install",
                           return_value=True):
                    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                        with patch("subprocess.run", side_effect=fake_subprocess_run), patch.object(
                            update_mod.sys, "prefix", str(tool_root)
                        ), patch("z_harness_cli.commands.update.shutil.which", return_value=str(launcher)):
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

    def test_uv_post_install_candidate_mismatch_restores_backup(self):
        """B3: uv exit zero cannot commit a CLI reporting another candidate."""

        import typer
        import z_harness_cli.commands.update as update_mod

        home = Path(self._home.name)
        tool_root = home / ".local" / "share" / "uv" / "tools" / "z-harness"
        tool_root.mkdir(parents=True)
        (tool_root / "old.txt").write_text("old tool\n", encoding="utf-8")
        launcher = home / ".local" / "bin" / "z-harness"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("old launcher\n", encoding="utf-8")
        wheel = home / "candidate.whl"
        wheel.write_bytes(b"verified")

        def fake_run(command, **kwargs):
            completed = MagicMock(returncode=0, stdout="")
            if command[0] == "uv":
                shutil.rmtree(tool_root)
                tool_root.mkdir()
                (tool_root / "new.txt").write_text("new tool\n", encoding="utf-8")
                launcher.write_text("new launcher\n", encoding="utf-8")
            else:
                completed.stdout = "z-harness 3.0.0\n"
            return completed

        with patch("z_harness_cli.commands.update._download_verified_wheel", return_value=wheel), patch.object(
            update_mod.sys, "prefix", str(tool_root)
        ), patch("z_harness_cli.commands.update.shutil.which", return_value=str(launcher)), patch(
            "z_harness_cli.commands.update.subprocess.run", side_effect=fake_run
        ), patch("typer.echo"):
            with self.assertRaises(typer.Exit):
                update_mod._apply_uv_upgrade(_make_manifest(version="2.0.0"))

        self.assertEqual((tool_root / "old.txt").read_text(encoding="utf-8"), "old tool\n")
        self.assertEqual(launcher.read_text(encoding="utf-8"), "old launcher\n")
        self.assertFalse(update_mod._cli_transaction_path().exists())

    def test_uv_restore_failure_retains_journal_for_later_recovery(self):
        """B2: a failed rollback keeps durable pre-state until recovery succeeds."""

        import z_harness_cli.commands.update as update_mod

        home = Path(self._home.name)
        tool_root = home / ".local" / "share" / "uv" / "tools" / "z-harness"
        tool_root.mkdir(parents=True)
        (tool_root / "old.txt").write_text("old tool\n", encoding="utf-8")
        launcher = home / ".local" / "bin" / "z-harness"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("old launcher\n", encoding="utf-8")
        wheel = home / "candidate.whl"
        wheel.write_bytes(b"verified")

        def fake_run(command, **kwargs):
            completed = MagicMock(returncode=0, stdout="")
            if command[0] == "uv":
                shutil.rmtree(tool_root)
                tool_root.mkdir()
                (tool_root / "new.txt").write_text("new tool\n", encoding="utf-8")
                launcher.write_text("new launcher\n", encoding="utf-8")
            else:
                completed.stdout = "z-harness 3.0.0\n"
            return completed

        with patch("z_harness_cli.commands.update._download_verified_wheel", return_value=wheel), patch.object(
            update_mod.sys, "prefix", str(tool_root)
        ), patch("z_harness_cli.commands.update.shutil.which", return_value=str(launcher)), patch(
            "z_harness_cli.commands.update.subprocess.run", side_effect=fake_run
        ), patch("z_harness_cli.commands.update._restore_cli_transaction", side_effect=RuntimeError("disk failure")), patch(
            "typer.echo"
        ):
            with self.assertRaisesRegex(RuntimeError, "disk failure"):
                update_mod._apply_uv_upgrade(_make_manifest(version="2.0.0"))

        transaction = update_mod._cli_transaction_path()
        self.assertTrue((transaction / "tool").is_dir())
        self.assertTrue((transaction / "tool.path").is_file())
        update_mod._recover_cli_transaction()
        self.assertEqual((tool_root / "old.txt").read_text(encoding="utf-8"), "old tool\n")
        self.assertEqual(launcher.read_text(encoding="utf-8"), "old launcher\n")
        self.assertFalse(transaction.exists())

    def test_uv_mutator_recovers_intervening_cli_journal_under_lock(self):
        """B4: a journal created after public preflight wins over visible partial state."""

        import typer
        import z_harness_cli.commands.update as update_mod

        home = Path(self._home.name)
        tool_root = home / ".local" / "share" / "uv" / "tools" / "z-harness"
        tool_root.mkdir(parents=True)
        (tool_root / "PARTIAL").write_text("interrupted\n", encoding="utf-8")
        transaction = update_mod._cli_transaction_path()
        backup = transaction / "tool"
        backup.mkdir(parents=True)
        (backup / "OLD").write_text("last known good\n", encoding="utf-8")
        (transaction / "tool.path").write_text(str(tool_root), encoding="utf-8")
        wheel = home / "candidate.whl"
        wheel.write_bytes(b"verified")

        with patch("z_harness_cli.commands.update._download_verified_wheel", return_value=wheel), patch.object(
            update_mod.sys, "prefix", str(tool_root)
        ), patch("z_harness_cli.commands.update.shutil.which", return_value=None), patch(
            "z_harness_cli.commands.update.subprocess.run",
            return_value=MagicMock(returncode=1, stdout=""),
        ), patch("typer.echo"):
            with self.assertRaises(typer.Exit):
                update_mod._apply_uv_upgrade(_make_manifest(version="2.0.0"))

        self.assertEqual((tool_root / "OLD").read_text(encoding="utf-8"), "last known good\n")
        self.assertFalse((tool_root / "PARTIAL").exists())
        self.assertFalse(transaction.exists())

    def test_cli_preparation_faults_are_cleanly_recoverable(self):
        """M1: every durable pre-mutation boundary can be discarded safely."""

        import z_harness_cli.commands.update as update_mod

        for step in (
            "cli.prepare.metadata",
            "cli.prepare.tool",
            "cli.prepare.launchers",
            "cli.prepare.ready",
        ):
            with self.subTest(step=step):
                home = Path(self._home.name)
                tool_root = home / ".local" / "share" / "uv" / "tools" / "z-harness"
                shutil.rmtree(tool_root, ignore_errors=True)
                tool_root.mkdir(parents=True)
                (tool_root / "OLD").write_text("visible\n", encoding="utf-8")
                launcher = home / ".local" / "bin" / "z-harness"
                launcher.parent.mkdir(parents=True, exist_ok=True)
                launcher.write_text("old launcher\n", encoding="utf-8")
                wheel = home / f"{step}.whl"
                wheel.write_bytes(b"verified")
                with patch.dict(os.environ, {"Z_HARNESS_TEST_FAIL_AFTER": step}), patch(
                    "z_harness_cli.commands.update._download_verified_wheel", return_value=wheel
                ), patch.object(update_mod.sys, "prefix", str(tool_root)), patch(
                    "z_harness_cli.commands.update.shutil.which", return_value=str(launcher)
                ), patch("typer.echo"):
                    with self.assertRaisesRegex(RuntimeError, step):
                        update_mod._apply_uv_upgrade(_make_manifest(version="2.0.0"))
                self.assertEqual((tool_root / "OLD").read_text(encoding="utf-8"), "visible\n")
                self.assertEqual(launcher.read_text(encoding="utf-8"), "old launcher\n")
                self.assertTrue(update_mod._cli_transaction_path().exists())
                update_mod._recover_cli_transaction()
                self.assertFalse(update_mod._cli_transaction_path().exists())

    def test_source_mutator_recovers_intervening_source_record_under_lock(self):
        """B4: source recovery runs immediately before candidate journal creation."""

        import subprocess
        import z_harness_cli.commands.update as update_mod

        root = Path(self._home.name) / "source-recovery"
        root.mkdir()
        subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Lifecycle Test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "lifecycle@example.invalid"], check=True)
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "VERSION"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "old"], check=True, capture_output=True)
        old_head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        (root / "PARTIAL").write_text("interrupted\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "PARTIAL"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "partial"], check=True, capture_output=True)
        record = update_mod._source_transaction_path()
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"root": str(root), "old_head": old_head}), encoding="utf-8")
        observed: list[str] = []

        def observe_recovered(*_args) -> None:
            head = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            observed.append(head)

        with patch("z_harness_cli.commands.update._apply_candidate_source_update", side_effect=observe_recovered), patch(
            "typer.echo"
        ):
            update_mod._apply_symlink_update(
                update_mod.PluginInstall("symlink", root, "claude"),
                _make_manifest(version="2.0.0"),
            )

        self.assertEqual(observed, [old_head])
        self.assertFalse((root / "PARTIAL").exists())
        self.assertFalse(record.exists())


if __name__ == "__main__":
    unittest.main()
