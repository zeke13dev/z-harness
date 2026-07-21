#!/usr/bin/env python3
"""Build and verify the complete public release output from one canonical stage.

C2 criteria #3, #4, and #8 require this script to be the only release assembly
entry point. It accepts candidate identity rather than deriving it, composes the
positive-surface stager and deterministic plugin bundler, and emits a fixed
publication allowlist.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.release import parse_release_candidate
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


_PUBLIC_FIXED_NAMES = (
    "latest.json",
    "release-assets.json",
    "SHA256SUMS",
    "install.sh",
    "install-plugin.sh",
)
_PLUGIN_MANIFEST_NAMES = frozenset({"plugin.json", "marketplace.json"})
_UNSAFE_NAME = re.compile(
    r"(^|/)(?:personas?|sentinel[^/]*|"
    r"[^/]*(?:secret|credential|private[-_]?key)[^/]*|"
    r"\.env(?:\..*)?|[^/]+\.(?:pem|key))($|/)",
    re.IGNORECASE,
)


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    """Run one mandatory assembly step and preserve its diagnostic output.

    Raises:
        subprocess.CalledProcessError: When the assembly step fails.
    """

    subprocess.run(command, cwd=cwd, env=env, check=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_safe_names(names: list[str], *, artifact: str) -> None:
    for raw_name in names:
        name = raw_name.removeprefix("./").rstrip("/")
        if name and _UNSAFE_NAME.search(name):
            raise ValueError(f"{artifact} contains retired or secret-like path: {name}")


def _stamp_staged_plugin_manifests(stage_root: Path, candidate_version: str) -> None:
    """Stamp every shipped z-harness plugin record from the explicit candidate.

    Raises:
        ValueError: When a shipped plugin manifest has no z-harness record.
        json.JSONDecodeError: When a shipped plugin manifest is invalid JSON.
    """

    def stamp(value: object) -> int:
        stamped = 0
        if isinstance(value, dict):
            if value.get("name") == "z-harness" and "version" in value:
                value["version"] = candidate_version
                stamped += 1
            for child in value.values():
                stamped += stamp(child)
        elif isinstance(value, list):
            for child in value:
                stamped += stamp(child)
        return stamped

    manifests = sorted(
        path
        for path in stage_root.rglob("*.json")
        if path.name in _PLUGIN_MANIFEST_NAMES
    )
    if not manifests:
        raise ValueError("canonical stage contains no shipped plugin manifests")
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if stamp(manifest) == 0:
            raise ValueError(
                "shipped plugin manifest has no z-harness version record: "
                f"{manifest_path.relative_to(stage_root)}"
            )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.utime(manifest_path, (0, 0))


def _wheel_version(candidate_version: str) -> str:
    """Return the standard wheel spelling of the frozen public version."""

    wheel_markers = {"alpha": "a", "beta": "b", "rc": "rc"}
    return re.sub(
        r"-(alpha|beta|rc)[.-]?",
        lambda match: wheel_markers[match.group(1)],
        candidate_version,
    )


def _audit_wheel(
    path: Path,
    *,
    stage_root: Path,
    candidate_version: str,
    candidate_commit: str,
) -> None:
    """Verify wheel identity, generated Codex metadata, and unsafe-name absence.

    Raises:
        ValueError: When the wheel diverges from the candidate contract.
        zipfile.BadZipFile: When the wheel is not a valid ZIP archive.
    """

    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        _assert_safe_names(names, artifact="wheel")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("wheel must contain exactly one distribution METADATA file")
        dist_info_root = metadata_names[0].split("/", maxsplit=1)[0] + "/"
        stage_files = {
            candidate.relative_to(stage_root).as_posix()
            for candidate in stage_root.rglob("*")
            if candidate.is_file()
        }
        divergent = [
            name
            for name in names
            if not name.startswith(dist_info_root) and name not in stage_files
        ]
        if divergent:
            raise ValueError(f"wheel contains path outside canonical stage: {divergent[0]}")
        plugin_names = [name for name in names if name == ".codex-plugin/plugin.json"]
        if plugin_names != [".codex-plugin/plugin.json"]:
            raise ValueError("wheel must contain exactly one generated Codex plugin manifest")
        plugin = json.loads(wheel.read(plugin_names[0]))
        if plugin.get("version") != candidate_version or plugin.get("candidate_commit") != candidate_commit:
            raise ValueError("wheel Codex metadata does not match candidate identity")
        metadata = wheel.read(metadata_names[0]).decode("utf-8")
        if f"\nVersion: {_wheel_version(candidate_version)}\n" not in f"\n{metadata}":
            raise ValueError("wheel distribution version does not match candidate version")


def _wheel_record_digest(data: bytes) -> str:
    """Return the wheel RECORD spelling of one SHA-256 digest."""

    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"sha256={digest.decode('ascii')}"


def _metadata_header(name: str, value: object) -> str:
    """Render one core-metadata header without permitting header injection.

    Raises:
        ValueError: When the declared value contains a line break.
    """

    rendered = str(value)
    if "\n" in rendered or "\r" in rendered:
        raise ValueError(f"project metadata field {name} contains a line break")
    return f"{name}: {rendered}"


def _readme_metadata(project: dict[str, object], stage_root: Path) -> tuple[str, str] | None:
    """Return the declared long description and its core-metadata content type.

    Raises:
        ValueError: When a PEP 621 readme table is incomplete or ambiguous.
        OSError: When a declared readme file cannot be read.
    """

    declaration = project.get("readme")
    if declaration is None:
        return None
    if isinstance(declaration, str):
        suffix = Path(declaration).suffix.lower()
        content_types = {".md": "text/markdown", ".rst": "text/x-rst"}
        if suffix not in content_types:
            raise ValueError("project readme string must name a .md or .rst file")
        return (stage_root / declaration).read_text(encoding="utf-8"), content_types[suffix]
    if not isinstance(declaration, dict) or not isinstance(
        declaration.get("content-type"), str
    ):
        raise ValueError("project readme table requires content-type")
    sources = [key for key in ("file", "text") if key in declaration]
    if len(sources) != 1 or not isinstance(declaration[sources[0]], str):
        raise ValueError("project readme table requires exactly one string file or text")
    description = (
        (stage_root / declaration["file"]).read_text(encoding="utf-8")
        if sources[0] == "file"
        else declaration["text"]
    )
    return description, declaration["content-type"]


def _party_headers(field: str, parties: object) -> list[str]:
    """Render PEP 621 author or maintainer records as core metadata."""

    if not isinstance(parties, list):
        return []
    names: list[str] = []
    addresses: list[str] = []
    for party in parties:
        if not isinstance(party, dict):
            continue
        name = party.get("name")
        email = party.get("email")
        if isinstance(email, str):
            addresses.append(f"{name} <{email}>" if isinstance(name, str) else email)
        elif isinstance(name, str):
            names.append(name)
    headers: list[str] = []
    if names:
        headers.append(_metadata_header(field, ", ".join(names)))
    if addresses:
        headers.append(_metadata_header(f"{field}-email", ", ".join(addresses)))
    return headers


def _license_text(project: dict[str, object], stage_root: Path) -> str | None:
    """Return the declared license text for the core metadata License field."""

    declaration = project.get("license")
    if declaration is None or isinstance(declaration, str):
        return declaration
    if not isinstance(declaration, dict):
        raise ValueError("project license must be a string or table")
    sources = [key for key in ("file", "text") if key in declaration]
    if len(sources) != 1 or not isinstance(declaration[sources[0]], str):
        raise ValueError("project license table requires exactly one string file or text")
    if sources[0] == "file":
        return (stage_root / declaration["file"]).read_text(encoding="utf-8").rstrip("\n")
    return declaration["text"]


def _requires_dist(raw_dependency: str, *, extra: str | None = None) -> str:
    """Render one declared dependency, optionally guarded by an extra marker."""

    requirement = Requirement(raw_dependency)
    if extra is not None:
        extra_marker = f'extra == "{canonicalize_name(extra)}"'
        marker = (
            f"({requirement.marker}) and {extra_marker}"
            if requirement.marker is not None
            else extra_marker
        )
        requirement.marker = Marker(marker)
    return str(requirement)


def _render_wheel_metadata(
    project: dict[str, object], stage_root: Path, wheel_version: str
) -> bytes:
    """Render complete deterministic core metadata from the staged PEP 621 table."""

    headers = [
        "Metadata-Version: 2.3",
        _metadata_header("Name", project["name"]),
        _metadata_header("Version", wheel_version),
    ]
    if "description" in project:
        headers.append(_metadata_header("Summary", project["description"]))
    readme = _readme_metadata(project, stage_root)
    if readme is not None:
        headers.append(_metadata_header("Description-Content-Type", readme[1]))
    license_text = _license_text(project, stage_root)
    if license_text is not None:
        headers.append(_metadata_header("License", license_text))
    headers.extend(_party_headers("Author", project.get("authors")))
    headers.extend(_party_headers("Maintainer", project.get("maintainers")))
    if "keywords" in project:
        headers.append(_metadata_header("Keywords", ",".join(project["keywords"])))
    for classifier in project.get("classifiers", []):
        headers.append(_metadata_header("Classifier", classifier))
    if "requires-python" in project:
        headers.append(_metadata_header("Requires-Python", project["requires-python"]))
    for label, url in sorted(project.get("urls", {}).items()):
        headers.append(_metadata_header("Project-URL", f"{label}, {url}"))
    for dependency in project.get("dependencies", []):
        headers.append(_metadata_header("Requires-Dist", _requires_dist(dependency)))
    optional = project.get("optional-dependencies", {})
    for extra, dependencies in sorted(optional.items()):
        normalized_extra = canonicalize_name(extra)
        headers.append(_metadata_header("Provides-Extra", normalized_extra))
        for dependency in dependencies:
            headers.append(
                _metadata_header(
                    "Requires-Dist",
                    _requires_dist(dependency, extra=normalized_extra),
                )
            )
    body = readme[0] if readme is not None else ""
    return ("\n".join(headers) + "\n\n" + body).encode("utf-8")


def _render_entry_points(project: dict[str, object]) -> bytes:
    """Render every declared PEP 621 script and entry-point group."""

    groups: dict[str, object] = dict(project.get("entry-points", {}))
    if project.get("scripts"):
        groups["console_scripts"] = project["scripts"]
    if project.get("gui-scripts"):
        groups["gui_scripts"] = project["gui-scripts"]
    lines: list[str] = []
    for group, entries in sorted(groups.items()):
        lines.append(f"[{group}]")
        lines.extend(f"{name} = {target}" for name, target in sorted(entries.items()))
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def _build_wheel(stage_root: Path, wheel_dir: Path, candidate_version: str) -> Path:
    """Build the pure-Python wheel using only the frozen interpreter environment.

    The canonical stage is already the positive release surface, so packaging it
    directly avoids a second resolver and an isolated build environment whose
    inputs are not represented in ``uv.lock``.

    Raises:
        OSError: When a staged file cannot be read or the wheel cannot be written.
    """

    wheel_version = _wheel_version(candidate_version)
    dist_info = f"z_harness-{wheel_version}.dist-info"
    wheel_path = wheel_dir / f"z_harness-{wheel_version}-py3-none-any.whl"
    records: list[tuple[str, str, str]] = []
    project = tomllib.loads((stage_root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    metadata = _render_wheel_metadata(project, stage_root, wheel_version)
    generated = {
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: z-harness canonical assembler\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ).encode(),
        f"{dist_info}/entry_points.txt": _render_entry_points(project),
    }

    def write_member(archive: zipfile.ZipFile, name: str, data: bytes, mode: int) -> None:
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (mode & 0xFFFF) << 16
        archive.writestr(info, data)
        records.append((name, _wheel_record_digest(data), str(len(data))))

    with zipfile.ZipFile(wheel_path, mode="w") as archive:
        for source in sorted(path for path in stage_root.rglob("*") if path.is_file()):
            name = source.relative_to(stage_root).as_posix()
            mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
            write_member(archive, name, source.read_bytes(), mode)
        for name, data in generated.items():
            write_member(archive, name, data, 0o644)

        record_name = f"{dist_info}/RECORD"
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerows([*records, (record_name, "", "")])
        info = zipfile.ZipInfo(record_name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, output.getvalue().encode())

    return wheel_path


def _audit_tarball(
    path: Path,
    *,
    stage_root: Path,
    candidate_version: str,
    candidate_commit: str,
) -> None:
    """Verify plugin archive identity and unsafe-name absence.

    Raises:
        ValueError: When the archive diverges from the candidate contract.
        tarfile.TarError: When the archive is malformed.
    """

    with tarfile.open(path, mode="r:gz") as archive:
        names = [member.name for member in archive.getmembers()]
        _assert_safe_names(names, artifact="plugin tarball")
        archive_paths = {name.removeprefix("./").rstrip("/") for name in names}
        stage_paths = {
            candidate.relative_to(stage_root).as_posix()
            for candidate in stage_root.rglob("*")
        }
        if archive_paths != stage_paths:
            difference = sorted(archive_paths ^ stage_paths)
            raise ValueError(f"plugin tarball diverges from canonical stage: {difference[0]}")
        manifests = [
            member
            for member in archive.getmembers()
            if member.name.removeprefix("./") == ".codex-plugin/plugin.json"
        ]
        if len(manifests) != 1:
            raise ValueError("plugin tarball must contain exactly one generated Codex plugin manifest")
        source = archive.extractfile(manifests[0])
        if source is None:
            raise ValueError("plugin tarball Codex manifest is not a regular file")
        plugin = json.load(source)
        if plugin.get("version") != candidate_version or plugin.get("candidate_commit") != candidate_commit:
            raise ValueError("plugin tarball Codex metadata does not match candidate identity")


def _artifact_url(base_url: str, name: str) -> str:
    return f"{base_url.rstrip('/')}/{name}"


def assemble_release(
    repo_root: Path,
    output_dir: Path,
    *,
    candidate_version: str,
    candidate_commit: str,
    artifact_base_url: str,
) -> dict[str, object]:
    """Assemble one verified, allowlisted release directory.

    Args:
        repo_root: Tracked candidate checkout or extracted source archive.
        output_dir: Empty or absent destination for verified public assets.
        candidate_version: Frozen public version supplied by provenance.
        candidate_commit: Frozen source commit supplied by provenance.
        artifact_base_url: HTTPS base used by the emitted release manifest.

    Returns:
        A machine-readable description of the verified output set.

    Raises:
        ValueError: When inputs, contents, or output names violate the contract.
        FileExistsError: When output_dir is non-empty.
        subprocess.CalledProcessError: When staging, building, or auditing fails.
    """

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    if not candidate_version or not candidate_commit:
        raise ValueError("candidate version and commit are required")
    candidate = parse_release_candidate(candidate_version)
    if not artifact_base_url.startswith("https://"):
        raise ValueError("artifact base URL must use https://")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"release output directory is not empty: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    candidate_output = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.assembling-", dir=output_dir.parent)
    )
    try:
        with tempfile.TemporaryDirectory(prefix="z-harness-release-") as temporary:
            temporary_root = Path(temporary)
            stage = temporary_root / "stage"
            wheel_dir = temporary_root / "wheel"
            wheel_dir.mkdir()
            _run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "stage-release-surface.py"),
                    "--repo-root",
                    str(repo_root),
                    "--out",
                    str(stage),
                    "--candidate-version",
                    candidate.plugin_version,
                    "--candidate-commit",
                    candidate_commit,
                ],
                cwd=repo_root,
            )
            _stamp_staged_plugin_manifests(stage, candidate.plugin_version)
            _build_wheel(stage, wheel_dir, candidate.plugin_version)
            wheels = list(wheel_dir.glob("*.whl"))
            if len(wheels) != 1:
                raise ValueError(f"expected one wheel, found {len(wheels)}")
            wheel = wheels[0]
            _audit_wheel(
                wheel,
                stage_root=stage,
                candidate_version=candidate.plugin_version,
                candidate_commit=candidate_commit,
            )

            # bundle-plugin.sh intentionally owns a conventional REPO_ROOT/dist
            # target. Run an unchanged copy from disposable workspace so no
            # unaudited tarball is ever exposed in the candidate checkout.
            bundle_root = temporary_root / "bundle-workspace"
            bundle_scripts = bundle_root / "scripts"
            bundle_scripts.mkdir(parents=True)
            for script_name in ("bundle-plugin.sh", "audit-tarball.sh"):
                shutil.copyfile(
                    repo_root / "scripts" / script_name,
                    bundle_scripts / script_name,
                )
            tarball_source = (
                bundle_root / "dist" / f"z-harness-{candidate.tarball_version}.tar.gz"
            )
            bundle_env = os.environ.copy()
            bundle_env["Z_HARNESS_RELEASE_SURFACE"] = "prod"
            bundle_env["PYTHONPATH"] = os.pathsep.join(
                filter(None, (str(repo_root), bundle_env.get("PYTHONPATH")))
            )
            _run(
                [
                    "/bin/bash",
                    str(bundle_scripts / "bundle-plugin.sh"),
                    "--stage",
                    str(stage),
                    "--candidate-version",
                    candidate.plugin_version,
                    "--candidate-commit",
                    candidate_commit,
                ],
                cwd=bundle_root,
                env=bundle_env,
            )
            if not tarball_source.is_file():
                raise ValueError("plugin bundler did not emit the expected candidate tarball")
            _audit_tarball(
                tarball_source,
                stage_root=stage,
                candidate_version=candidate.plugin_version,
                candidate_commit=candidate_commit,
            )

            wheel_output = candidate_output / wheel.name
            tarball_output = candidate_output / tarball_source.name
            shutil.copyfile(wheel, wheel_output)
            shutil.copyfile(tarball_source, tarball_output)
            shutil.copyfile(stage / "scripts" / "curl-install.sh", candidate_output / "install.sh")
            shutil.copyfile(stage / "install.sh", candidate_output / "install-plugin.sh")

        wheel_sha = _sha256(wheel_output)
        tarball_sha = _sha256(tarball_output)
        latest = {
            "schema_version": 1,
            "version": candidate.latest_json_version,
            "wheel_url": _artifact_url(artifact_base_url, wheel_output.name),
            "sha256": wheel_sha,
            "plugin_tarball_url": _artifact_url(artifact_base_url, tarball_output.name),
            "plugin_tarball_sha256": tarball_sha,
            "cli_schema_version": 1,
            "telemetry_schema_version": 1,
            "min_supported_version": "0.1.0",
        }
        (candidate_output / "latest.json").write_text(
            json.dumps(latest, indent=2) + "\n",
            encoding="utf-8",
        )
        asset_manifest = {
            "schema_version": 1,
            "candidate_version": candidate.plugin_version,
            "candidate_commit": candidate_commit,
            "artifacts": {
                path.name: _sha256(path)
                for path in (
                    wheel_output,
                    tarball_output,
                    candidate_output / "install.sh",
                    candidate_output / "install-plugin.sh",
                )
            },
        }
        (candidate_output / "release-assets.json").write_text(
            json.dumps(asset_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        checksum_paths = [
            wheel_output,
            tarball_output,
            candidate_output / "latest.json",
            candidate_output / "release-assets.json",
            candidate_output / "install.sh",
            candidate_output / "install-plugin.sh",
        ]
        (candidate_output / "SHA256SUMS").write_text(
            "".join(f"{_sha256(path)}  {path.name}\n" for path in checksum_paths),
            encoding="utf-8",
        )
        expected = set(_PUBLIC_FIXED_NAMES) | {wheel_output.name, tarball_output.name}
        actual = {path.name for path in candidate_output.iterdir()}
        if actual != expected:
            raise ValueError(
                f"release output diverged from publication allowlist: {sorted(actual ^ expected)}"
            )
        os.replace(candidate_output, output_dir)
    finally:
        shutil.rmtree(candidate_output, ignore_errors=True)
    return {
        "candidate_version": candidate.plugin_version,
        "candidate_commit": candidate_commit,
        "output_dir": str(output_dir),
        "files": sorted(actual),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--artifact-base-url", required=True)
    args = parser.parse_args(argv)
    result = assemble_release(
        args.repo_root,
        args.out,
        candidate_version=args.candidate_version,
        candidate_commit=args.candidate_commit,
        artifact_base_url=args.artifact_base_url,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
