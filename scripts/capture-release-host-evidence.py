#!/usr/bin/env python3
"""Validate and atomically bind one live host record to exact release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from z_harness_cli.release_host_evidence import (
    DISPATCH_PROBE_PREFIX,
    claim_fingerprint,
    derive_release_claims,
    expected_dispatch_probe,
    validate_cli_proof,
    validate_common_record,
    validate_dispatch_probe,
    validate_omp_proof,
    validate_plugin_proof,
    evidence_kind,
)


SHA_RE = re.compile(r"[0-9a-f]{40}")
FIXED_ARTIFACT_NAMES = frozenset(
    {"install.sh", "install-plugin.sh", "latest.json", "release-assets.json", "SHA256SUMS"}
)
CANDIDATE_RE = re.compile(
    r"(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)(?:-beta\.(?P<beta>[1-9][0-9]*))?"
)


class CaptureError(RuntimeError):
    """Raised when a live record cannot be promoted to candidate evidence."""


def _require_dispatch_probe(stdout: str, candidate_sha: str) -> str:
    expected = expected_dispatch_probe(candidate_sha)
    marker_lines = [
        line for line in stdout.splitlines() if line.startswith(DISPATCH_PROBE_PREFIX)
    ]
    if marker_lines != [expected]:
        raise CaptureError(
            "host execution must emit exactly one dispatch probe for the exact candidate SHA"
        )
    return expected


HOST_CREDENTIALS = {
    "claude": ("ANTHROPIC_API_KEY",),
    "cli": (),
    "codex": ("OPENAI_API_KEY",),
    "omp": ("OPENAI_API_KEY",),
}


def _isolated_execution_env(host: str, root: Path, namespace: argparse.Namespace) -> dict[str, str]:
    """Build a closed execution environment; never inherit persistent runner state."""

    paths = {
        "HOME": root,
        "XDG_CONFIG_HOME": root / "xdg-config",
        "XDG_DATA_HOME": root / "xdg-data",
        "XDG_STATE_HOME": root / "xdg-state",
        "XDG_CACHE_HOME": root / "xdg-cache",
        "CODEX_HOME": root / "codex-home",
        "CLAUDE_CONFIG_DIR": root / "claude-config",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    env = {key: str(value) for key, value in paths.items()}
    for key in ("PATH", "RUNNER_TEMP", "TMPDIR", "GITHUB_WORKSPACE", "CI",
                "CANDIDATE_SHA", "CANDIDATE_VERSION", "Z_HARNESS_RELEASE_OUTPUT"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    for key in HOST_CREDENTIALS[host]:
        value = os.environ.get(key)
        if not value:
            raise CaptureError(f"required protected credential is missing: {key}")
        env[key] = value
    if host == "omp":
        plugin_root = Path(namespace.omp_plugin_root).resolve(strict=True)
        if not plugin_root.is_dir() or not plugin_root.is_relative_to(root):
            raise CaptureError("OMP plugin root must be an installed-wheel-derived directory under isolated home")
        env["OMP_PLUGIN_ROOT"] = str(plugin_root)
    return env


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _inventory(root: Path) -> tuple[str, list[dict[str, object]]]:
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        file_stat = path.lstat()
        if stat.S_ISDIR(file_stat.st_mode):
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            raise CaptureError(f"artifact directory contains a symlink or special file: {relative}")
        entries.append(
            {
                "path": relative,
                "type": "file",
                "executable": bool(file_stat.st_mode & 0o111),
                "size": file_stat.st_size,
                "sha256": _sha256_bytes(path.read_bytes()),
            }
        )
    return _sha256_bytes(_canonical_json(entries)), entries


def _load_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaptureError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise CaptureError(f"{label} must be a JSON object")
    return value


def _artifact_identity(path: Path) -> dict[str, str]:
    return {"name": path.name, "sha256": _sha256_bytes(path.read_bytes())}


def _candidate_versions(value: str) -> tuple[str, str]:
    match = CANDIDATE_RE.fullmatch(value)
    if match is None:
        raise CaptureError("release asset manifest candidate_version is not canonical")
    base = f"{match['major']}.{match['minor']}.{match['patch']}"
    pep440 = base + (f"b{match['beta']}" if match["beta"] else "")
    return value, pep440


def _manifest_versions(value: object) -> list[str]:
    versions: list[str] = []
    if isinstance(value, dict):
        if value.get("name") == "z-harness" and isinstance(value.get("version"), str):
            versions.append(value["version"])
        for nested in value.values():
            versions.extend(_manifest_versions(nested))
    elif isinstance(value, list):
        for nested in value:
            versions.extend(_manifest_versions(nested))
    return versions


def _verify_plugin_members(
    members: Mapping[str, bytes], candidate_version: str, label: str
) -> None:
    if not members:
        raise CaptureError(f"{label} contains no plugin manifest")
    for name, body in members.items():
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaptureError(f"{label} contains invalid plugin manifest: {name}") from exc
        versions = _manifest_versions(value)
        if not versions or any(version != candidate_version for version in versions):
            raise CaptureError(f"{label} plugin manifest version does not match candidate")


def _verify_release_artifacts_stdlib(
    root: Path,
    candidate_version: str,
    candidate_sha: str,
    wheel: Path,
    tarball: Path,
) -> None:
    plugin_version, pep440_version = _candidate_versions(candidate_version)
    if tarball.name != f"z-harness-{plugin_version}.tar.gz":
        raise CaptureError("plugin tarball basename does not match candidate")
    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise CaptureError("wheel must contain exactly one METADATA file")
            metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
            if metadata.get("Name") != "z-harness" or metadata.get("Version") != pep440_version:
                raise CaptureError("wheel metadata identity does not match candidate")
            wheel_members = {
                name: archive.read(name)
                for name in archive.namelist()
                if name.endswith(("plugin.json", "marketplace.json"))
            }
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise CaptureError(f"invalid wheel artifact: {wheel.name}") from exc
    _verify_plugin_members(wheel_members, plugin_version, "wheel")
    try:
        with tarfile.open(tarball, "r:gz") as archive:
            tar_members: dict[str, bytes] = {}
            for member in archive.getmembers():
                if member.isfile() and member.name.endswith(("plugin.json", "marketplace.json")):
                    source = archive.extractfile(member)
                    if source is None:
                        raise CaptureError(f"unreadable plugin manifest: {member.name}")
                    tar_members[member.name] = source.read()
    except (OSError, tarfile.TarError) as exc:
        raise CaptureError(f"invalid plugin tarball: {tarball.name}") from exc
    _verify_plugin_members(tar_members, plugin_version, "plugin tarball")

    latest = _load_object(root / "latest.json", "latest manifest")
    required_latest = {
        "schema_version", "version", "wheel_url", "sha256", "plugin_tarball_url",
        "plugin_tarball_sha256", "cli_schema_version", "telemetry_schema_version",
        "min_supported_version",
    }
    if not required_latest.issubset(latest) or latest.get("schema_version") != 1:
        raise CaptureError("latest manifest is missing required schema fields")
    if type(latest.get("cli_schema_version")) is not int or type(
        latest.get("telemetry_schema_version")
    ) is not int:
        raise CaptureError("latest manifest schema versions must be integers")
    if not isinstance(latest.get("min_supported_version"), str) or not latest[
        "min_supported_version"
    ]:
        raise CaptureError("latest manifest min_supported_version is required")
    if latest.get("version") != plugin_version:
        raise CaptureError("latest manifest version does not match candidate")
    for label, url_key, digest_key, path in (
        ("wheel", "wheel_url", "sha256", wheel),
        ("plugin tarball", "plugin_tarball_url", "plugin_tarball_sha256", tarball),
    ):
        url, digest = latest.get(url_key), latest.get(digest_key)
        if not isinstance(url, str) or not url.startswith("https://"):
            raise CaptureError(f"latest manifest {label} URL must use canonical HTTPS")
        if Path(urllib.parse.urlparse(url).path).name != path.name:
            raise CaptureError(f"latest manifest {label} URL does not name produced artifact")
        if not isinstance(digest, str) or digest != _sha256_bytes(path.read_bytes()):
            raise CaptureError(f"latest manifest {label} digest does not match produced artifact")

    assets = _load_object(root / "release-assets.json", "release asset manifest")
    if assets.get("candidate_version") != plugin_version or assets.get("candidate_commit") != candidate_sha:
        raise CaptureError("release asset manifest identity does not match explicit candidate")
    artifact_digests = assets.get("artifacts")
    produced = (wheel, tarball, root / "install.sh", root / "install-plugin.sh")
    expected_assets = {path.name: _sha256_bytes(path.read_bytes()) for path in produced}
    if artifact_digests != expected_assets:
        raise CaptureError("release asset manifest digests do not match exact artifacts")
    checksum_paths = (*produced, root / "latest.json", root / "release-assets.json")
    expected_checksums = {path.name: _sha256_bytes(path.read_bytes()) for path in checksum_paths}
    parsed: dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/]+)", line)
        if match is None or match[2] in parsed:
            raise CaptureError("SHA256SUMS contains a malformed or duplicate entry")
        parsed[match[2]] = match[1]
    if parsed != expected_checksums:
        raise CaptureError("SHA256SUMS does not match exact produced artifacts")


def _resolve_artifacts(
    root_arg: str, candidate_sha: str
) -> tuple[Path, str, dict[str, dict[str, str]]]:
    raw_root = Path(root_arg)
    if raw_root.is_symlink():
        raise CaptureError("artifact directory must not be a symlink")
    root = raw_root.resolve(strict=True)
    if not root.is_dir():
        raise CaptureError("artifact directory is not a directory")
    entries = sorted(root.iterdir())
    names = {path.name for path in entries}
    wheels = [path for path in entries if path.name.endswith(".whl")]
    tarballs = [
        path for path in entries
        if path.name.startswith("z-harness-") and path.name.endswith(".tar.gz")
    ]
    expected = FIXED_ARTIFACT_NAMES | {path.name for path in wheels + tarballs}
    if len(wheels) != 1 or len(tarballs) != 1 or names != expected or len(names) != 7:
        raise CaptureError("artifact directory must contain the exact seven-file release allowlist")
    # This must precede every read/open/archive/hash operation. In particular,
    # opening a caller-supplied FIFO in a required slot would otherwise hang.
    for path in entries:
        try:
            file_stat = path.lstat()
        except OSError as exc:
            raise CaptureError(f"cannot inspect required artifact: {path.name}") from exc
        if not stat.S_ISREG(file_stat.st_mode):
            raise CaptureError(
                f"required artifact must be a regular non-symlink file: {path.name}"
            )

    assets = _load_object(root / "release-assets.json", "release asset manifest")
    candidate_version = assets.get("candidate_version")
    if not isinstance(candidate_version, str) or not candidate_version:
        raise CaptureError("release asset manifest has no candidate_version")
    if assets.get("candidate_commit") != candidate_sha:
        raise CaptureError("release asset manifest candidate commit does not match explicit SHA")
    _verify_release_artifacts_stdlib(
        root, candidate_version, candidate_sha, wheels[0], tarballs[0]
    )

    fingerprint, _ = _inventory(root)
    identities = {
        "wheel": _artifact_identity(wheels[0]),
        "plugin": _artifact_identity(tarballs[0]),
    }
    return root, fingerprint, identities


def _validate_live_record(
    record: dict[str, object],
    candidate_sha: str,
    identities: Mapping[str, dict[str, str]],
) -> str:
    host = record.get("host")
    claims, claim_errors = derive_release_claims()
    if claim_errors:
        raise CaptureError("; ".join(claim_errors))
    if not isinstance(host, str) or host not in claims:
        raise CaptureError(f"unsupported release host: {host!r}")
    if record.get("candidate_sha") != candidate_sha:
        raise CaptureError("raw host record candidate SHA does not match explicit SHA")

    claim = claims[host]
    errors = validate_common_record(
        record,
        host=host,
        claim=claim,
        claims_fingerprint=claim_fingerprint(claims),
        candidate_sha=candidate_sha,
        allow_test_fixtures=False,
        require_trusted_producer=False,
    )
    proof = record.get("proof")
    if host in {"claude", "codex"}:
        errors.extend(validate_plugin_proof(host, proof))
        identity_kind = "plugin"
    elif host == "cli":
        errors.extend(validate_cli_proof(proof))
        identity_kind = "wheel"
    elif host == "omp":
        errors.extend(validate_omp_proof(proof, record.get("artifact"), candidate_sha))
        identity_kind = "wheel"
    else:  # derive_release_claims is the exhaustive release roster.
        raise CaptureError(f"unsupported release host: {host!r}")
    expected_identity = identities[identity_kind]
    if record.get("artifact") != expected_identity:
        raise CaptureError(
            f"{host}: artifact name or digest does not match exact {identity_kind} artifact"
        )
    if errors:
        raise CaptureError("; ".join(errors))
    return host


def _write_exclusive(path: Path, payload: dict[str, object]) -> None:
    descriptor = -1
    reservation = -1
    temporary: Path | None = None
    cleanup_destination = False
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            reservation = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            cleanup_destination = True
        except FileExistsError as exc:
            raise CaptureError(f"destination already exists: {path}") from exc
        os.close(reservation)
        reservation = -1
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        cleanup_destination = False
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if reservation >= 0:
            os.close(reservation)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if cleanup_destination:
            path.unlink(missing_ok=True)
            try:
                cleanup_directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(cleanup_directory_fd)
                finally:
                    os.close(cleanup_directory_fd)
            except OSError:
                pass


def capture(namespace: argparse.Namespace) -> dict[str, object]:
    if SHA_RE.fullmatch(namespace.candidate_sha) is None:
        raise CaptureError("candidate SHA must be exactly 40 lowercase hexadecimal characters")
    host = namespace.host
    claims, claim_errors = derive_release_claims()
    if claim_errors or host not in claims:
        raise CaptureError("; ".join(claim_errors) or f"unsupported release host: {host!r}")
    artifacts_root, artifact_fingerprint, identities = _resolve_artifacts(
        namespace.artifacts, namespace.candidate_sha
    )
    checkout_root = Path(
        os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parents[1])
    ).resolve()
    isolated_home = Path(namespace.isolated_home).resolve(strict=True)
    if not isolated_home.is_dir() or isolated_home.is_relative_to(checkout_root):
        raise CaptureError("isolated home must be an existing directory outside the checkout")
    execution_env = _isolated_execution_env(host, isolated_home, namespace)

    execute_command = list(getattr(namespace, "execute_command", ()) or ())
    if not execute_command:
        raise CaptureError("a repository-owned host execution command is required")
    cli_before = None
    if host == "cli":
        state_executable = Path(namespace.cli_executable).resolve(strict=True)
        cli_before = subprocess.run(
            [state_executable, "--version"], text=True, capture_output=True,
            check=False, env=execution_env,
        )
        if cli_before.returncode != 0:
            raise CaptureError("cannot observe CLI lifecycle pre-update state")
    try:
        execution = subprocess.run(
            execute_command,
            text=True,
            capture_output=True,
            check=False,
            timeout=900,
            env=execution_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CaptureError("host execution command could not complete") from exc
    if execution.returncode != 0:
        raise CaptureError(
            f"host execution failed with exit code {execution.returncode}: "
            f"{(execution.stderr or execution.stdout)[-1000:]}"
        )

    dispatch_probe = (
        _require_dispatch_probe(execution.stdout, namespace.candidate_sha)
        if host in {"claude", "codex", "omp"}
        else None
    )

    identity_kind = "plugin" if host in {"claude", "codex"} else "wheel"
    artifact = identities[identity_kind]
    if host in {"claude", "codex"}:
        payload = Path(namespace.payload_path).resolve(strict=True)
        if payload.is_relative_to(checkout_root):
            raise CaptureError("installed plugin payload must be outside the checkout")
        payload_digest = _inventory(payload)[0] if payload.is_dir() else _sha256_bytes(payload.read_bytes())
        proof = {
            "kind": "clean_installed_plugin", "clean_home": True, "isolated_config": True,
            "payload": {"path": str(payload), "sha256": payload_digest},
            "dispatch_probe": dispatch_probe,
            "runner": " ".join(execute_command),
        }
    elif host == "cli":
        after = subprocess.run([state_executable, "--version"], text=True, capture_output=True,
                               check=False, env=execution_env)
        candidate_version = str(_load_object(artifacts_root / "release-assets.json", "release asset manifest")["candidate_version"])
        _, candidate_cli_version = _candidate_versions(candidate_version)
        assert cli_before is not None
        before_version = cli_before.stdout.strip().split()[-1]
        if before_version == candidate_cli_version:
            raise CaptureError("CLI lifecycle did not begin from an observed stale version")
        if after.returncode != 0 or candidate_cli_version not in after.stdout:
            raise CaptureError("CLI lifecycle did not transition to the exact candidate version")
        proof = {
            "kind": "clean_release_lifecycle", "clean_home": True, "isolated_config": True,
            "phases": [
                {"operation": operation, "status": "passed", "exit_code": 0}
                for operation in ("bootstrap", "install", "update")
            ],
            "before_version": before_version, "after_version": candidate_cli_version,
            "update_applied": True,
            "runner": " ".join(execute_command),
        }
    else:
        matches = re.findall(r"^IMPORT_PATH=(.+)$", execution.stdout, re.MULTILINE)
        if len(matches) != 1:
            raise CaptureError("OMP execution must report exactly one derived IMPORT_PATH")
        import_path = Path(matches[0]).resolve(strict=True)
        if import_path.is_relative_to(checkout_root):
            raise CaptureError("OMP import path must be outside the checkout")
        version = _load_object(artifacts_root / "release-assets.json", "release asset manifest")["candidate_version"]
        _, pep440 = _candidate_versions(str(version))
        proof = {
            "kind": "clean_installed_wheel", "candidate_sha": namespace.candidate_sha,
            "wheel_filename": artifact["name"], "wheel_sha256": artifact["sha256"],
            "distribution": f"z-harness=={pep440}", "import_path": str(import_path),
            "dispatch_probe": dispatch_probe,
            "runner": " ".join(execute_command), "installed_outside_checkout": True,
            "imported_from_installed_wheel": True, "dev_dependencies": False,
        }
    stamped: dict[str, object] = {
        "schema_version": 1, "fixture_mode": False, "host": host, "command": "z-fix",
        "candidate_sha": namespace.candidate_sha, "claim": claims[host],
        "claim_fingerprint": claim_fingerprint(claims), "evidence_kind": evidence_kind(host, claims[host]),
        "blocking": True, "status": "passed", "exit_code": execution.returncode,
        "artifact": artifact,
        "provenance": {
            "runner": "repository-owned-release-evidence-v1",
            "environment": "protected-isolated-host-execution",
            "evidence_root_kind": "trusted-release-host-capture",
            "artifact_set_fingerprint": artifact_fingerprint,
        },
        "diagnostics": [
        "Repository-owned host execution completed with exit code zero.",
        f"stdout_sha256={_sha256_bytes(execution.stdout.encode())}",
        f"stderr_sha256={_sha256_bytes(execution.stderr.encode())}",
        ],
        "proof": proof,
    }
    producer_values = {
        "repository": getattr(namespace, "producer_repository", None),
        "workflow": getattr(namespace, "producer_workflow", None),
        "run_id": getattr(namespace, "producer_run_id", None),
        "job": getattr(namespace, "producer_job", None),
        "environment": getattr(namespace, "producer_environment", None),
        "event": getattr(namespace, "producer_event", None),
        "head_sha": getattr(namespace, "producer_head_sha", None),
    }
    if any(value in (None, "") for value in producer_values.values()):
        raise CaptureError("complete trusted producer identity is required")
    if producer_values["head_sha"] != namespace.candidate_sha:
        raise CaptureError("trusted producer head SHA does not match candidate")
    try:
        producer_values["run_id"] = int(producer_values["run_id"])
    except (TypeError, ValueError) as exc:
        raise CaptureError("trusted producer run ID must be an integer") from exc
    execution_identity = {
        "argv": execute_command,
        "exit_code": execution.returncode,
        "stdout_sha256": _sha256_bytes(execution.stdout.encode()),
        "stderr_sha256": _sha256_bytes(execution.stderr.encode()),
        "artifact_set_fingerprint": artifact_fingerprint,
    }
    stamped["producer"] = {
        "schema_version": 1,
        **producer_values,
        "execution_digest": _sha256_bytes(_canonical_json(execution_identity)),
    }

    trusted_errors = validate_common_record(
        stamped,
        host=host,
        claim=claims[host],
        claims_fingerprint=claim_fingerprint(claims),
        candidate_sha=namespace.candidate_sha,
        allow_test_fixtures=False,
    )
    if host in {"claude", "codex", "omp"}:
        trusted_errors.extend(validate_dispatch_probe(host, proof, namespace.candidate_sha))
    if trusted_errors:
        raise CaptureError("; ".join(trusted_errors))

    destination = Path(namespace.destination)
    if destination.is_symlink() or destination.exists():
        raise CaptureError(f"destination already exists: {destination}")
    if not destination.parent.is_dir():
        raise CaptureError("destination parent must already exist")
    if destination.name != f"{stamped['host']}.json":
        raise CaptureError("destination filename must be exactly <host>.json")
    _write_exclusive(destination, stamped)
    return stamped


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--host", required=True, choices=("claude", "cli", "codex", "omp"))
    parser.add_argument("--isolated-home", required=True)
    parser.add_argument("--payload-path")
    parser.add_argument("--cli-executable")
    parser.add_argument("--omp-plugin-root")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--producer-repository", required=True)
    parser.add_argument("--producer-workflow", required=True)
    parser.add_argument("--producer-run-id", required=True)
    parser.add_argument("--producer-job", required=True)
    parser.add_argument("--producer-environment", required=True)
    parser.add_argument("--producer-event", required=True)
    parser.add_argument("--producer-head-sha", required=True)
    parser.add_argument("--execute-command", nargs=argparse.REMAINDER, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        capture(_parser().parse_args(argv))
    except (CaptureError, OSError, ValueError) as exc:
        print(f"capture-release-host-evidence: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
