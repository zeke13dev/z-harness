"""release.py — Release manifest fetch/parse + version comparison.

Spec reference: SPEC.md "Release + update (D4, D9)" + F6.

Manifest schema (latest.json):
    {
        "schema_version": <int>,
        "version": "<semver>",
        "wheel_url": "<url>",
        "sha256": "<hex>",
        "cli_schema_version": <int>,
        "telemetry_schema_version": <int>,
        "min_supported_version": "<semver>"
    }

Invariants:
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
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

# The maximum schema_version this code understands.
SUPPORTED_SCHEMA_VERSION: int = 1

# Default manifest URL — overridden by Z_HARNESS_RELEASE_URL.
DEFAULT_RELEASE_URL: str = "https://releases.zeketools.dev/z-harness/latest.json"

_SEMVER_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[a-zA-Z0-9._-]+))?$"
)
# Looks like a git short-SHA or SHA256 fragment (hex, 7–40 chars, no dots)
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


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


class ManifestSchemaError(Exception):
    """Raised when the manifest schema_version is newer than SUPPORTED_SCHEMA_VERSION."""


class ManifestParseError(Exception):
    """Raised when the manifest is missing required fields or has bad types."""


class FetchError(Exception):
    """Raised when the manifest HTTP fetch fails."""


def _semver_tuple(version: str) -> tuple[int, int, int, str]:
    """Parse a semver string into (major, minor, patch, pre) for comparison.

    Pre-release strings sort *before* the release (None/"" > any pre string).
    """
    m = _SEMVER_RE.match(version.strip())
    if not m:
        raise ValueError(f"Not a semver string: {version!r}")
    major = int(m.group("major"))
    minor = int(m.group("minor"))
    patch = int(m.group("patch"))
    pre = m.group("pre") or ""
    return (major, minor, patch, pre)


def _semver_lt(a: str, b: str) -> bool:
    """Return True if semver a < semver b."""
    ta = _semver_tuple(a)
    tb = _semver_tuple(b)
    # Compare numeric parts first
    if ta[:3] != tb[:3]:
        return ta[:3] < tb[:3]
    # Both have the same numeric version; now compare pre-release.
    # No pre-release ("") > any pre-release string (PEP 440 / semver convention).
    pre_a, pre_b = ta[3], tb[3]
    if pre_a == pre_b:
        return False
    if pre_a == "":
        return False  # a is a release, b has pre → a > b
    if pre_b == "":
        return True   # b is a release, a has pre → a < b
    return pre_a < pre_b


def _semver_eq(a: str, b: str) -> bool:
    """Return True if semver a == semver b."""
    return _semver_tuple(a) == _semver_tuple(b)


def is_dev_sha(version: str) -> bool:
    """Return True when *version* looks like a git short-SHA dev marker."""
    return bool(_SHA_RE.match(version.strip())) and "." not in version


def fetch_manifest(url: Optional[str] = None) -> ReleaseManifest:
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

    return parse_manifest(raw)


def parse_manifest(raw: str) -> ReleaseManifest:
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

    required_str_fields = ("version", "wheel_url", "sha256", "min_supported_version")
    for field in required_str_fields:
        val = data.get(field)
        if not isinstance(val, str) or not val:
            raise ManifestParseError(
                f"Manifest missing or empty string field: {field!r} (got {val!r})"
            )

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
    )


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
