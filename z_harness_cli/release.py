"""Release candidate identity, manifest parsing, and version comparison.

Spec reference: SPEC.md "Release + update (D4, D9)" + F6.

Manifest schema (latest.json):
    {
        "schema_version": <int>,
        "version": "<semver>",
        "wheel_url": "<url>",
        "sha256": "<hex>",
        "cli_schema_version": <int>,
        "telemetry_schema_version": <int>,
        "min_supported_version": "<semver>",
        "plugin_tarball_url": "<url>",
        "plugin_tarball_sha256": "<hex>"
    }

Invariants:
- Public release identity comes only from an explicit candidate accepted by
  :func:`parse_release_candidate`; Git state is not an identity fallback.
- Stable and beta candidates render deterministically across Git/SemVer and
  Python/PEP 440 ecosystems and compare through ``packaging.version.Version``.
- Publication binds an immutable ``candidate_sha`` to freshly fetched
  ``origin/main`` and requires exact release evidence and authorization through
  publication on protected ``main``.
- Fetch honors Z_HARNESS_RELEASE_URL env var (mirror-safe).
- schema_version newer than SUPPORTED_SCHEMA_VERSION → exit 1 with
  "update z-harness" message (never silently proceed).
- Version comparison: semver vs semver for tagged releases; a dev SHA
  is treated as "newer than latest release only if SHA unknown to manifest"
  (notice, never block).
- No auto-update — all updates are explicitly user-triggered.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from functools import total_ordering
from pathlib import Path

from packaging.version import InvalidVersion, Version

# The maximum schema_version this code understands.
SUPPORTED_SCHEMA_VERSION: int = 1

# Default manifest URL — overridden by Z_HARNESS_RELEASE_URL.
DEFAULT_RELEASE_URL: str = "https://github.com/zeke13dev/z-harness/releases/latest/download/latest.json"

_VERSION_NUMBER = r"(?:0|[1-9]\d*)"
_CANDIDATE_RE = re.compile(
    rf"^v?(?P<major>{_VERSION_NUMBER})\."
    rf"(?P<minor>{_VERSION_NUMBER})\."
    rf"(?P<patch>{_VERSION_NUMBER})"
    rf"(?:(?:-beta\.|b)(?P<beta>{_VERSION_NUMBER}))?$"
)
# Looks like a git short-SHA or SHA256 fragment (hex, 7–40 chars, no dots)
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


@total_ordering
@dataclass(frozen=True)
class ReleaseCandidate:
    """Canonical renderings of one explicit stable or beta release candidate.

    The canonical SemVer spelling is used by Git tags, plugin metadata,
    tarballs, and ``latest.json``. Wheel metadata uses the equivalent PEP 440
    spelling. Ordering and equality are semantic and delegated to the installed
    standards-compliant ``packaging`` parser.
    """

    git_tag: str
    plugin_version: str
    wheel_version: str
    tarball_version: str
    latest_json_version: str
    comparison_version: Version

    def __lt__(self, other: object) -> bool:
        """Order candidates using their canonical PEP 440 identities.

        Args:
            other: Candidate to compare.

        Returns:
            Whether this candidate sorts before ``other``.

        Raises:
            TypeError: When ``other`` is not a release candidate.
        """

        if not isinstance(other, ReleaseCandidate):
            return NotImplemented
        return self.comparison_version < other.comparison_version


def parse_release_candidate(candidate: str) -> ReleaseCandidate:
    """Parse one explicit stable or beta release identity.

    Accepted spellings are ``X.Y.Z``, ``vX.Y.Z``, ``X.Y.Z-beta.N``,
    ``vX.Y.Z-beta.N``, and the equivalent PEP 440 beta form ``X.Y.ZbN``.
    All numeric components are canonical decimal tokens without leading zeros.

    Args:
        candidate: Explicit candidate identity supplied by the release caller.

    Returns:
        Deterministic ecosystem-specific renderings of the candidate.

    Raises:
        ValueError: When the candidate is not a supported canonical spelling.
    """

    if not isinstance(candidate, str):
        raise ValueError("Release candidate must be a string")
    match = _CANDIDATE_RE.fullmatch(candidate)
    if match is None:
        raise ValueError(
            "Release candidate must be X.Y.Z or X.Y.Z-beta.N "
            "(optional v prefix; X.Y.ZbN is accepted for PEP 440 round trips)"
        )

    base = ".".join(match.group(name) for name in ("major", "minor", "patch"))
    beta = match.group("beta")
    plugin_version = base if beta is None else f"{base}-beta.{beta}"
    wheel_version = base if beta is None else f"{base}b{beta}"
    try:
        comparison_version = Version(wheel_version)
    except InvalidVersion as exc:  # pragma: no cover - guarded by the strict regex
        raise ValueError(f"Invalid release candidate: {candidate!r}") from exc

    return ReleaseCandidate(
        git_tag=f"v{plugin_version}",
        plugin_version=plugin_version,
        wheel_version=str(comparison_version),
        tarball_version=plugin_version,
        latest_json_version=plugin_version,
        comparison_version=comparison_version,
    )


@dataclass
class ReleaseManifest:
    """Parsed and validated latest.json."""

    schema_version: int
    version: str
    wheel_url: str
    sha256: str
    cli_schema_version: int
    telemetry_schema_version: int
    min_supported_version: str
    plugin_tarball_url: str
    plugin_tarball_sha256: str


class ManifestSchemaError(Exception):
    """Raised when the manifest schema_version is newer than SUPPORTED_SCHEMA_VERSION."""


class ManifestParseError(Exception):
    """Raised when the manifest is missing required fields or has bad types."""


class FetchError(Exception):
    """Raised when the manifest HTTP fetch fails."""


class ReleaseArtifactError(ValueError):
    """Raised when assembled release outputs diverge from the candidate."""


def _release_comparison_version(version: str) -> Version:
    """Return a comparable tagged release version.

    Raises:
        ValueError: When ``version`` is a development, local, or invalid value.
    """

    try:
        parsed = Version(version)
    except InvalidVersion as exc:
        raise ValueError(f"Not a release version: {version!r}") from exc
    if parsed.is_devrelease or parsed.local is not None:
        raise ValueError(f"Not a tagged release version: {version!r}")
    return parsed


def _semver_lt(a: str, b: str) -> bool:
    """Return whether tagged release ``a`` sorts before ``b``."""

    return _release_comparison_version(a) < _release_comparison_version(b)


def _semver_eq(a: str, b: str) -> bool:
    """Return whether tagged releases ``a`` and ``b`` are equivalent."""

    return _release_comparison_version(a) == _release_comparison_version(b)


def is_dev_sha(version: str) -> bool:
    """Return True when *version* looks like a git short-SHA dev marker."""
    return bool(_SHA_RE.match(version.strip())) and "." not in version


def fetch_manifest(url: str | None = None, *, allow_file_urls: bool = False) -> ReleaseManifest:
    """Fetch and parse the release manifest.

    Args:
        url: Override URL. If None, uses Z_HARNESS_RELEASE_URL env var,
             falling back to DEFAULT_RELEASE_URL.

    Raises:
        FetchError: on network or HTTP errors.
        ManifestParseError: on malformed JSON or missing fields.
        ManifestSchemaError: when schema_version > SUPPORTED_SCHEMA_VERSION.
    """
    effective_url = url or os.environ.get("Z_HARNESS_RELEASE_URL") or DEFAULT_RELEASE_URL

    try:
        with urllib.request.urlopen(effective_url, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} fetching manifest from {effective_url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Network error fetching manifest from {effective_url}: {exc.reason}") from exc
    except OSError as exc:
        raise FetchError(f"I/O error fetching manifest from {effective_url}: {exc}") from exc

    return parse_manifest(raw, allow_file_urls=allow_file_urls)



def _validate_url(field: str, value: str, *, allow_file_urls: bool) -> None:
    if value.startswith("https://"):
        return
    if allow_file_urls and value.startswith("file://"):
        return
    expected = "https:// or file://" if allow_file_urls else "https://"
    raise ManifestParseError(
        f"Manifest field {field!r} must use {expected} (got {value!r})"
    )


def _validate_sha256(field: str, value: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ManifestParseError(
            f"Manifest field {field!r} must be a 64-character hexadecimal SHA-256 digest"
        )

def parse_manifest(raw: str, *, allow_file_urls: bool = False) -> ReleaseManifest:
    """Parse and validate a manifest JSON string.

    Raises:
        ManifestParseError: on malformed JSON or missing/wrong-typed fields.
        ManifestSchemaError: when schema_version > SUPPORTED_SCHEMA_VERSION.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestParseError(f"Manifest is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ManifestParseError("Manifest must be a JSON object")

    # Validate schema_version first — reject unsupported schemas before touching other fields.
    schema_ver = data.get("schema_version")
    if not isinstance(schema_ver, int):
        raise ManifestParseError(
            f"Manifest missing integer 'schema_version' field (got {schema_ver!r})"
        )
    if schema_ver > SUPPORTED_SCHEMA_VERSION:
        raise ManifestSchemaError(
            f"Manifest schema_version {schema_ver} is newer than the supported version "
            f"{SUPPORTED_SCHEMA_VERSION}. Please update z-harness before continuing."
        )

    required_str_fields = (
        "version",
        "wheel_url",
        "sha256",
        "min_supported_version",
        "plugin_tarball_url",
        "plugin_tarball_sha256",
    )
    for field in required_str_fields:
        val = data.get(field)
        if not isinstance(val, str) or not val:
            raise ManifestParseError(
                f"Manifest missing or empty string field: {field!r} (got {val!r})"
            )

    _validate_sha256("sha256", data["sha256"])

    _validate_url("wheel_url", data["wheel_url"], allow_file_urls=allow_file_urls)

    plugin_tarball_url = data["plugin_tarball_url"]
    plugin_tarball_sha256 = data["plugin_tarball_sha256"]
    _validate_url(
        "plugin_tarball_url",
        plugin_tarball_url,
        allow_file_urls=allow_file_urls,
    )
    _validate_sha256("plugin_tarball_sha256", plugin_tarball_sha256)

    required_int_fields = ("cli_schema_version", "telemetry_schema_version")
    for field in required_int_fields:
        val = data.get(field)
        if not isinstance(val, int):
            raise ManifestParseError(
                f"Manifest missing integer field: {field!r} (got {val!r})"
            )

    return ReleaseManifest(
        schema_version=schema_ver,
        version=data["version"],
        wheel_url=data["wheel_url"],
        sha256=data["sha256"],
        cli_schema_version=data["cli_schema_version"],
        telemetry_schema_version=data["telemetry_schema_version"],
        min_supported_version=data["min_supported_version"],
        plugin_tarball_url=plugin_tarball_url,
        plugin_tarball_sha256=plugin_tarball_sha256,
    )


def require_plugin_tarball_metadata(manifest: ReleaseManifest) -> tuple[str, str]:
    """Return audited plugin tarball metadata or raise a manifest parse error."""

    if not manifest.plugin_tarball_url:
        raise ManifestParseError(
            "Release manifest does not include plugin_tarball_url. "
            "Pass --tarball explicitly or install from a source checkout."
        )
    if not manifest.plugin_tarball_sha256:
        raise ManifestParseError(
            "Release manifest does not include plugin_tarball_sha256. "
            "Pass --tarball explicitly or install from a source checkout."
        )
    return manifest.plugin_tarball_url, manifest.plugin_tarball_sha256


class VersionComparisonResult:
    """Result of comparing installed version against the release manifest."""

    STALE = "stale"       # installed is older than manifest
    EQUAL = "equal"       # installed matches manifest version exactly
    NEWER = "newer"       # installed is ahead of manifest (dev or tagged)
    DEV_UNKNOWN = "dev_unknown"   # installed is a dev SHA not referenced in manifest


def compare_versions(
    installed: str,
    manifest: ReleaseManifest,
) -> str:
    """Compare installed version against the manifest.

    Rules (F6):
    - If installed is a tagged semver release: compare semver vs manifest.version.
    - If installed looks like a git SHA (dev build): treat as newer than the
      manifest *only if the SHA is unknown to the manifest* → DEV_UNKNOWN (notice,
      never block). A dev SHA equal to the manifest version string is EQUAL.
    - PEP 440 dev/local forms (e.g. ``0.0.0.dev0``, ``1.0.0.dev5+gabcdef``) and
      any other non-semver, non-SHA string are classified as DEV_UNKNOWN — a notice
      is emitted but the command never crashes or blocks.

    Returns one of VersionComparisonResult constants.
    """
    installed = installed.strip()

    if is_dev_sha(installed):
        # Dev SHA: compare against manifest version string literally.
        if installed == manifest.version:
            return VersionComparisonResult.EQUAL
        # SHA not referenced in the manifest → treat as newer (notice only).
        return VersionComparisonResult.DEV_UNKNOWN

    # Exact string match (covers edge cases where manifest version is non-semver).
    if installed == manifest.version:
        return VersionComparisonResult.EQUAL

    # Tagged semver path — guard against PEP 440 dev/local forms and other
    # non-semver strings (e.g. "0.0.0.dev0", "1.0.0.dev5+gabcdef") that would
    # raise ValueError inside _semver_tuple.
    try:
        if _semver_eq(installed, manifest.version):
            return VersionComparisonResult.EQUAL
        if _semver_lt(installed, manifest.version):
            return VersionComparisonResult.STALE
        return VersionComparisonResult.NEWER
    except ValueError:
        # Non-semver, non-SHA version string (PEP 440 dev/local or unknown format).
        # Classify as DEV_UNKNOWN: emit a notice, never crash or block.
        return VersionComparisonResult.DEV_UNKNOWN


def verify_sha256(path: str, expected_hex: str) -> bool:
    """Return True iff the file at *path* matches *expected_hex* (SHA-256)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected_hex.lower()


def _artifact_digest(path: Path) -> str:
    """Return the lowercase SHA-256 digest of one release artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _z_harness_manifest_versions(data: object) -> list[str]:
    """Collect version fields for shipped z-harness plugin records."""

    versions: list[str] = []
    if isinstance(data, dict):
        if data.get("name") == "z-harness" and isinstance(data.get("version"), str):
            versions.append(data["version"])
        for value in data.values():
            versions.extend(_z_harness_manifest_versions(value))
    elif isinstance(data, list):
        for value in data:
            versions.extend(_z_harness_manifest_versions(value))
    return versions


def _assert_plugin_manifest_versions(
    members: dict[str, bytes],
    candidate: ReleaseCandidate,
    *,
    artifact: str,
) -> None:
    """Prove every shipped plugin manifest names the candidate version."""

    manifest_names = [
        name
        for name in members
        if name.removeprefix("./").endswith(("plugin.json", "marketplace.json"))
    ]
    if not manifest_names:
        raise ReleaseArtifactError(f"{artifact} contains no plugin manifest")
    for name in manifest_names:
        try:
            data = json.loads(members[name])
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ReleaseArtifactError(f"{artifact} contains invalid plugin manifest: {name}") from exc
        versions = _z_harness_manifest_versions(data)
        if not versions:
            raise ReleaseArtifactError(f"{artifact} plugin manifest has no z-harness version: {name}")
        for version in versions:
            try:
                equivalent = parse_release_candidate(version) == candidate
            except ValueError as exc:
                raise ReleaseArtifactError(
                    f"{artifact} plugin manifest has invalid version {version!r}: {name}"
                ) from exc
            if not equivalent:
                raise ReleaseArtifactError(
                    f"{artifact} plugin manifest version {version!r} does not match "
                    f"candidate {candidate.plugin_version!r}: {name}"
                )


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    """Load a required release JSON object with artifact-scoped diagnostics."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseArtifactError(f"invalid {label}: {path.name}") from exc
    if not isinstance(data, dict):
        raise ReleaseArtifactError(f"{label} must be a JSON object: {path.name}")
    return data


def verify_release_artifacts(output_dir: str | Path, candidate_version: str) -> None:
    """Verify that a complete assembled release is bound to one candidate.

    The check covers wheel metadata, all shipped plugin manifests, tarball
    basename, update-manifest URLs and digests, the release asset manifest, and
    the checksum inventory. It performs no writes and is intended to run before
    any install, upload, or publication-equivalent action.

    Args:
        output_dir: Directory emitted by the canonical release assembler.
        candidate_version: Explicit stable or beta release candidate.

    Raises:
        ReleaseArtifactError: When any identity, URL, filename, or digest differs.
        ValueError: When ``candidate_version`` is not a supported candidate.
    """

    candidate = parse_release_candidate(candidate_version)
    root = Path(output_dir)
    if not root.is_dir():
        raise ReleaseArtifactError(f"release output directory is missing: {root}")
    wheels = sorted(root.glob("*.whl"))
    tarballs = sorted(root.glob("z-harness-*.tar.gz"))
    if len(wheels) != 1 or len(tarballs) != 1:
        raise ReleaseArtifactError(
            f"expected one wheel and one plugin tarball, found {len(wheels)} and {len(tarballs)}"
        )
    wheel, tarball = wheels[0], tarballs[0]
    if tarball.name != f"z-harness-{candidate.tarball_version}.tar.gz":
        raise ReleaseArtifactError(f"plugin tarball basename does not match candidate: {tarball.name}")

    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise ReleaseArtifactError("wheel must contain exactly one METADATA file")
            metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
            try:
                wheel_matches = Version(metadata.get("Version", "")) == candidate.comparison_version
            except InvalidVersion as exc:
                raise ReleaseArtifactError("wheel metadata contains an invalid version") from exc
            if not wheel_matches:
                raise ReleaseArtifactError(
                    f"wheel metadata version {metadata.get('Version')!r} does not match candidate"
                )
            wheel_members = {
                name: archive.read(name)
                for name in archive.namelist()
                if name.endswith(("plugin.json", "marketplace.json"))
            }
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise ReleaseArtifactError(f"invalid wheel artifact: {wheel.name}") from exc
    _assert_plugin_manifest_versions(wheel_members, candidate, artifact="wheel")

    try:
        with tarfile.open(tarball, mode="r:gz") as archive:
            tar_members: dict[str, bytes] = {}
            for member in archive.getmembers():
                if not member.isfile() or not member.name.endswith(("plugin.json", "marketplace.json")):
                    continue
                source = archive.extractfile(member)
                if source is None:
                    raise ReleaseArtifactError(f"unreadable plugin manifest in tarball: {member.name}")
                tar_members[member.name] = source.read()
    except (OSError, tarfile.TarError) as exc:
        raise ReleaseArtifactError(f"invalid plugin tarball: {tarball.name}") from exc
    _assert_plugin_manifest_versions(tar_members, candidate, artifact="plugin tarball")

    latest_path = root / "latest.json"
    try:
        latest = parse_manifest(latest_path.read_text(encoding="utf-8"))
    except (OSError, ManifestParseError, ManifestSchemaError) as exc:
        raise ReleaseArtifactError("invalid latest.json") from exc
    try:
        latest_matches = parse_release_candidate(latest.version) == candidate
    except ValueError as exc:
        raise ReleaseArtifactError("latest.json contains an invalid candidate version") from exc
    if not latest_matches:
        raise ReleaseArtifactError("latest.json version does not match candidate")
    for label, url, path, digest in (
        ("wheel", latest.wheel_url, wheel, latest.sha256),
        ("plugin tarball", latest.plugin_tarball_url, tarball, latest.plugin_tarball_sha256),
    ):
        if Path(urllib.parse.urlparse(url).path).name != path.name:
            raise ReleaseArtifactError(f"latest.json {label} URL does not name produced artifact")
        if _artifact_digest(path) != digest.lower():
            raise ReleaseArtifactError(f"latest.json {label} digest does not match produced artifact")

    assets = _load_json_object(root / "release-assets.json", label="release asset manifest")
    try:
        assets_match = parse_release_candidate(str(assets.get("candidate_version", ""))) == candidate
    except ValueError as exc:
        raise ReleaseArtifactError("release asset manifest contains an invalid candidate version") from exc
    if not assets_match:
        raise ReleaseArtifactError("release asset manifest version does not match candidate")
    artifact_digests = assets.get("artifacts")
    if not isinstance(artifact_digests, dict):
        raise ReleaseArtifactError("release asset manifest is missing artifact digests")
    expected_asset_paths = (wheel, tarball, root / "install.sh", root / "install-plugin.sh")
    if set(artifact_digests) != {path.name for path in expected_asset_paths}:
        raise ReleaseArtifactError("release asset manifest names the wrong produced artifacts")
    for path in expected_asset_paths:
        if not path.is_file() or artifact_digests[path.name] != _artifact_digest(path):
            raise ReleaseArtifactError(f"release asset digest mismatch: {path.name}")

    checksum_path = root / "SHA256SUMS"
    try:
        checksum_lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReleaseArtifactError("missing SHA256SUMS") from exc
    expected_checksum_paths = (*expected_asset_paths, latest_path, root / "release-assets.json")
    expected_checksums = {path.name: _artifact_digest(path) for path in expected_checksum_paths}
    parsed_checksums: dict[str, str] = {}
    for line in checksum_lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/]+)", line)
        if match is None or match.group(2) in parsed_checksums:
            raise ReleaseArtifactError("SHA256SUMS contains a malformed or duplicate entry")
        parsed_checksums[match.group(2)] = match.group(1)
    if parsed_checksums != expected_checksums:
        raise ReleaseArtifactError("SHA256SUMS does not match the exact produced artifacts")

    expected_names = {*expected_checksums, "SHA256SUMS"}
    actual_names = {path.name for path in root.iterdir()}
    if actual_names != expected_names:
        raise ReleaseArtifactError("release output contains missing or unexpected artifacts")
