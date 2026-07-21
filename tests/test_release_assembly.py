"""Behavioral coverage for the unified release assembly boundary."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
import tomllib
import zipfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import pytest


REPO_ROOT = Path(__file__).parent.parent.resolve()
ASSEMBLER_PATH = REPO_ROOT / "scripts" / "assemble-release.py"
STAGER_PATH = REPO_ROOT / "scripts" / "stage-release-surface.py"


def _load_assembler():
    spec = importlib.util.spec_from_file_location("assemble_release", ASSEMBLER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_stager():
    spec = importlib.util.spec_from_file_location("stage_release_surface", STAGER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stub_assembly_commands(monkeypatch: pytest.MonkeyPatch, assembler) -> None:
    """Replace expensive subprocesses with their observable artifact outputs."""

    def fake_run(command: list[str], *, cwd: Path, env=None) -> None:
        del cwd, env
        rendered = " ".join(command)
        if "stage-release-surface.py" in rendered:
            stage = Path(command[command.index("--out") + 1])
            (stage / "scripts").mkdir(parents=True)
            (stage / "scripts" / "curl-install.sh").write_text("public\n", encoding="utf-8")
            (stage / "install.sh").write_text("plugin\n", encoding="utf-8")
            (stage / "pyproject.toml").write_text(
                """[project]
name = "z-harness"
description = "test wheel"
license = "MIT"
requires-python = ">=3.11"
dependencies = ["packaging>=24"]
""",
                encoding="utf-8",
            )
            (stage / ".codex-plugin").mkdir()
            (stage / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"name": "z-harness", "version": "ambient"}),
                encoding="utf-8",
            )
            return
        if "--wheel" in command:
            wheel_dir = Path(command[command.index("--outdir") + 1])
            (wheel_dir / "z_harness-9.9.9-py3-none-any.whl").write_bytes(b"wheel")
            return
        if "bundle-plugin.sh" in rendered:
            version = command[command.index("--candidate-version") + 1]
            bundle_root = Path(command[1]).parent.parent
            tarball = bundle_root / "dist" / f"z-harness-{version}.tar.gz"
            tarball.parent.mkdir()
            tarball.write_bytes(b"tarball")
            return
        raise AssertionError(f"unexpected assembly command: {command}")

    monkeypatch.setattr(assembler, "_run", fake_run)
    monkeypatch.setattr(assembler, "_audit_wheel", lambda *args, **kwargs: None)
    monkeypatch.setattr(assembler, "_audit_tarball", lambda *args, **kwargs: None)


def _assert_no_assembly_debris(output: Path, version: str) -> None:
    assert not list(output.parent.glob(f".{output.name}.assembling-*"))
    assert not (REPO_ROOT / "dist" / f"z-harness-{version}.tar.gz").exists()


def _assert_installed_payload_matches_tarball(installed: Path, tarball: Path) -> None:
    """Assert that every regular archive payload file was installed byte-for-byte."""

    with tarfile.open(tarball, mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            source = archive.extractfile(member)
            assert source is not None
            assert (installed / member.name).read_bytes() == source.read()


def _z_harness_versions(value: object) -> list[str]:
    versions: list[str] = []
    if isinstance(value, dict):
        if value.get("name") == "z-harness" and isinstance(value.get("version"), str):
            versions.append(value["version"])
        for child in value.values():
            versions.extend(_z_harness_versions(child))
    elif isinstance(value, list):
        for child in value:
            versions.extend(_z_harness_versions(child))
    return versions


def test_assembler_stamps_every_staged_plugin_manifest_from_candidate(tmp_path: Path) -> None:
    assembler = _load_assembler()
    stage = tmp_path / "stage"
    manifests = {
        ".claude-plugin/plugin.json": {"name": "z-harness", "version": "1.0.406"},
        ".claude-plugin/marketplace.json": {
            "name": "zeke-tools",
            "plugins": [{"name": "z-harness", "version": "1.0.406"}],
        },
        ".codex-plugin/plugin.json": {"name": "z-harness", "version": "1.0.406"},
        "plugin.json": {"name": "z-harness", "version": "1.0.406"},
    }
    for relative, body in manifests.items():
        path = stage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")

    assembler._stamp_staged_plugin_manifests(stage, "2.4.1-beta.10")

    for relative in manifests:
        body = json.loads((stage / relative).read_text(encoding="utf-8"))
        assert _z_harness_versions(body) == ["2.4.1-beta.10"]


def test_wheel_builder_uses_only_the_canonical_stage_and_stdlib(tmp_path: Path) -> None:
    assembler = _load_assembler()
    stage = tmp_path / "stage"
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    (stage / "z_harness_cli").mkdir(parents=True)
    (stage / "z_harness_cli" / "__init__.py").write_text("", encoding="utf-8")
    (stage / "pyproject.toml").write_text(
        """[project]
name = "z-harness"
description = "test wheel"
license = "MIT"
requires-python = ">=3.11"
dependencies = ["packaging>=24"]
""",
        encoding="utf-8",
    )
    (stage / ".codex-plugin").mkdir()
    (stage / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "z-harness",
                "version": "2.4.1-beta.10",
                "candidate_commit": "a" * 40,
            }
        ),
        encoding="utf-8",
    )

    wheel = assembler._build_wheel(stage, wheel_dir, "2.4.1-beta.10")

    assert wheel.name == "z_harness-2.4.1b10-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "z_harness_cli/__init__.py" in names
        assert "z_harness-2.4.1b10.dist-info/RECORD" in names
        metadata = archive.read("z_harness-2.4.1b10.dist-info/METADATA").decode()
    assert "Version: 2.4.1b10\n" in metadata


def test_wheel_preserves_declared_project_metadata_and_installs_cli(tmp_path: Path) -> None:
    """The canonical wheel must retain PEP 621 identity and its runnable entry point."""

    assembler = _load_assembler()
    stage = tmp_path / "stage"
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    shutil.copytree(REPO_ROOT / "z_harness_cli", stage / "z_harness_cli")
    for name in ("pyproject.toml", "README.md"):
        shutil.copyfile(REPO_ROOT / name, stage / name)

    project = tomllib.loads((stage / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    wheel = assembler._build_wheel(stage, wheel_dir, "2.4.1-beta.10")
    with zipfile.ZipFile(wheel) as archive:
        metadata_bytes = archive.read("z_harness-2.4.1b10.dist-info/METADATA")
        entry_points = archive.read(
            "z_harness-2.4.1b10.dist-info/entry_points.txt"
        ).decode("utf-8")
    metadata = BytesParser(policy=policy.default).parsebytes(metadata_bytes)

    assert metadata["Name"] == project["name"]
    assert metadata["Version"] == "2.4.1b10"
    assert metadata["Summary"] == project["description"]
    assert metadata["Description-Content-Type"] == "text/markdown"
    assert metadata.get_payload(decode=True).decode("utf-8") == (
        stage / project["readme"]
    ).read_text(encoding="utf-8")
    assert metadata["License"] == project["license"]
    assert metadata["Author"] == ", ".join(author["name"] for author in project["authors"])
    assert metadata["Keywords"] == ",".join(project["keywords"])
    assert metadata.get_all("Classifier") == project["classifiers"]
    assert metadata["Requires-Python"] == project["requires-python"]
    assert set(metadata.get_all("Project-URL")) == {
        f"{label}, {url}" for label, url in project["urls"].items()
    }
    requirements = [Requirement(value) for value in metadata.get_all("Requires-Dist")]
    runtime = [requirement for requirement in requirements if requirement.marker is None]
    assert {str(requirement) for requirement in runtime} == {
        str(Requirement(value)) for value in project["dependencies"]
    }
    assert set(metadata.get_all("Provides-Extra")) == {
        canonicalize_name(extra) for extra in project["optional-dependencies"]
    }
    for extra, declarations in project["optional-dependencies"].items():
        extra_requirements = [
            requirement
            for requirement in requirements
            if requirement.marker is not None
            and requirement.marker.evaluate({"extra": canonicalize_name(extra)})
        ]
        assert {requirement.name for requirement in extra_requirements} == {
            Requirement(value).name for value in declarations
        }
        assert all(
            not requirement.marker.evaluate({"extra": "not-the-declared-extra"})
            for requirement in extra_requirements
        )
    assert entry_points == "[console_scripts]\nz-harness = z_harness_cli.__main__:app\n"

    install_root = tmp_path / "installed"
    subprocess.run(
        ["uv", "pip", "install", "--no-deps", "--target", str(install_root), str(wheel)],
        cwd=tmp_path,
        check=True,
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(install_root), environment.get("PYTHONPATH")))
    )
    cli = subprocess.run(
        [sys.executable, "-m", "z_harness_cli", "--help"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr
    assert "Usage:" in cli.stdout


def test_assembler_emits_only_verified_public_assets_from_one_stage(tmp_path: Path) -> None:
    assembler = _load_assembler()
    version = "0.9.0b2"
    commit = "0123456789abcdef0123456789abcdef01234567"
    output = tmp_path / "release"
    ambient = REPO_ROOT / "sentinel-secret-release-test.pem"
    ambient.write_text("must never enter release artifacts\n", encoding="utf-8")
    try:
        result = assembler.assemble_release(
            REPO_ROOT,
            output,
            candidate_version=version,
            candidate_commit=commit,
            artifact_base_url="https://example.invalid/releases/v0.9.0b2",
        )
    finally:
        ambient.unlink(missing_ok=True)

    files = set(result["files"])
    wheel = next(output.glob("*.whl"))
    tarball = next(output.glob("*.tar.gz"))
    assert files == {
        wheel.name,
        tarball.name,
        "latest.json",
        "release-assets.json",
        "SHA256SUMS",
        "install.sh",
        "install-plugin.sh",
    }
    assert (output / "install.sh").read_bytes() == (REPO_ROOT / "scripts" / "curl-install.sh").read_bytes()
    assert (output / "install-plugin.sh").read_bytes() == (REPO_ROOT / "install.sh").read_bytes()

    latest = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    assert latest["version"] == "0.9.0-beta.2"
    assert tarball.name == "z-harness-0.9.0-beta.2.tar.gz"
    assert result["candidate_version"] == "0.9.0-beta.2"
    assert latest["sha256"] == _sha256(wheel)
    assert latest["plugin_tarball_sha256"] == _sha256(tarball)
    checksums = (output / "SHA256SUMS").read_text(encoding="utf-8")
    for name in files - {"SHA256SUMS"}:
        assert f"  {name}\n" in checksums

    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
        wheel_skill_bodies = [
            archive.read(name)
            for name in wheel_names
            if name.startswith("skills/") and name.endswith("/SKILL.md")
        ]
    with tarfile.open(tarball) as archive:
        tar_names = [member.name.removeprefix("./") for member in archive.getmembers()]
        tar_skill_bodies = [
            source.read()
            for member in archive.getmembers()
            if member.isfile()
            and member.name.removeprefix("./").startswith("skills/")
            and member.name.endswith("/SKILL.md")
            if (source := archive.extractfile(member)) is not None
        ]
    for names in (wheel_names, tar_names):
        assert "scripts/capture-release-host-evidence.py" in names
        assert "scripts/check-pi-auth.sh" in names
        assert "z_harness_cli/release_host_evidence.py" in names
        assert not any(
            "personas" in name or "sentinel-secret-release-test" in name
            for name in names
        )
        assert not any(name.startswith("_fragments/") for name in names)
        assert ".codex-plugin/plugin.json" in names
    for bodies in (wheel_skill_bodies, tar_skill_bodies):
        assert bodies
        assert all(b"<!-- include:" not in body for body in bodies)


@pytest.mark.parametrize(
    ("candidate_input", "canonical_version"),
    (("2.4.1", "2.4.1"), ("0.9.0b2", "0.9.0-beta.2")),
)
def test_assembled_plugin_installer_accepts_exact_local_and_verified_remote_tarball(
    tmp_path: Path,
    candidate_input: str,
    canonical_version: str,
) -> None:
    """Prove deterministic stable/beta public artifacts install unchanged."""

    assembler = _load_assembler()
    stager = _load_stager()
    commit = "0123456789abcdef0123456789abcdef01234567"
    stage = tmp_path / "stage"
    output = tmp_path / "release"
    repeated_output = tmp_path / "release-repeated"
    source_version_before = (REPO_ROOT / "VERSION").read_bytes()
    stager.stage_release_surface(
        REPO_ROOT,
        stage,
        candidate_version=candidate_input,
        candidate_commit=commit,
    )
    assert (stage / "VERSION").read_bytes() == f"{canonical_version}\n".encode()
    staged_manifest = json.loads(
        (stage / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert staged_manifest["version"] == canonical_version
    assembler.assemble_release(
        REPO_ROOT,
        output,
        candidate_version=candidate_input,
        candidate_commit=commit,
        artifact_base_url=f"https://example.invalid/releases/{canonical_version}",
    )
    assembler.assemble_release(
        REPO_ROOT,
        repeated_output,
        candidate_version=candidate_input,
        candidate_commit=commit,
        artifact_base_url=f"https://example.invalid/releases/{canonical_version}",
    )
    installer = output / "install-plugin.sh"
    tarball = next(output.glob("*.tar.gz"))
    wheel = next(output.glob("*.whl"))
    digest = _sha256(tarball)

    expected_files = {
        wheel.name,
        tarball.name,
        "latest.json",
        "release-assets.json",
        "SHA256SUMS",
        "install.sh",
        "install-plugin.sh",
    }
    assert {path.name for path in output.iterdir()} == expected_files
    assert {path.name for path in repeated_output.iterdir()} == expected_files
    assert {
        path.name: path.read_bytes() for path in output.iterdir()
    } == {
        path.name: path.read_bytes() for path in repeated_output.iterdir()
    }
    assert (REPO_ROOT / "VERSION").read_bytes() == source_version_before
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read("VERSION") == f"{canonical_version}\n".encode()
        wheel_manifest = json.loads(archive.read(".codex-plugin/plugin.json"))
    assert wheel_manifest["version"] == canonical_version
    with tarfile.open(tarball, mode="r:gz") as archive:
        members = {
            member.name.removeprefix("./"): member for member in archive.getmembers()
        }
        version_member = archive.extractfile(members["VERSION"])
        manifest_member = archive.extractfile(members[".codex-plugin/plugin.json"])
        assert version_member is not None
        assert manifest_member is not None
        assert version_member.read() == f"{canonical_version}\n".encode()
        tar_manifest = json.load(manifest_member)
    assert tar_manifest["version"] == canonical_version

    local_home = tmp_path / f"local-home-{canonical_version}"
    local_env = os.environ.copy()
    local_env["HOME"] = str(local_home)
    local_result = subprocess.run(
        ["/bin/bash", str(installer), "--target=claude", f"--tarball={tarball}"],
        cwd=tmp_path,
        env=local_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert local_result.returncode == 0, local_result.stderr
    _assert_installed_payload_matches_tarball(
        local_home / ".claude" / "plugins" / "z-harness@zeke-tools",
        tarball,
    )

    handler = partial(SimpleHTTPRequestHandler, directory=str(output))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        remote_home = tmp_path / f"remote-home-{canonical_version}"
        remote_env = os.environ.copy()
        remote_env["HOME"] = str(remote_home)
        remote_url = f"http://127.0.0.1:{server.server_port}/{tarball.name}"
        remote_result = subprocess.run(
            [
                "/bin/bash",
                str(installer),
                "--target=claude",
                f"--tarball={remote_url}",
                f"--tarball-sha256={digest}",
            ],
            cwd=tmp_path,
            env=remote_env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()

    assert remote_result.returncode == 0, remote_result.stderr
    _assert_installed_payload_matches_tarball(
        remote_home / ".claude" / "plugins" / "z-harness@zeke-tools",
        tarball,
    )


def test_stager_rejects_invalid_candidate_before_replacing_destination(
    tmp_path: Path,
) -> None:
    stager = _load_stager()
    destination = tmp_path / "existing-stage"
    destination.mkdir()
    anchor = destination / "keep.txt"
    anchor.write_bytes(b"preexisting\n")

    with pytest.raises(ValueError, match="Release candidate must be"):
        stager.stage_release_surface(
            REPO_ROOT,
            destination,
            candidate_version="2.4.1-rc.1",
            candidate_commit="a" * 40,
        )

    assert destination.is_dir()
    assert list(destination.iterdir()) == [anchor]
    assert anchor.read_bytes() == b"preexisting\n"


def test_assembler_rejects_unsafe_wheel_member_before_publication(tmp_path: Path) -> None:
    assembler = _load_assembler()
    wheel = tmp_path / "candidate.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("sentinel-secret.pem", "injected")

    with pytest.raises(ValueError, match="retired or secret-like path"):
        assembler._audit_wheel(
            wheel,
            stage_root=tmp_path,
            candidate_version="0.9.0b2",
            candidate_commit="a" * 40,
        )


def test_assembler_rejects_retired_plugin_tar_member_before_publication(tmp_path: Path) -> None:
    assembler = _load_assembler()
    source = tmp_path / "legacy.txt"
    source.write_text("retired\n", encoding="utf-8")
    tarball = tmp_path / "candidate.tar.gz"
    with tarfile.open(tarball, mode="w:gz") as archive:
        archive.add(source, arcname="./personas/legacy.md")

    with pytest.raises(ValueError, match="retired or secret-like path"):
        assembler._audit_tarball(
            tarball,
            stage_root=tmp_path,
            candidate_version="0.9.0b2",
            candidate_commit="a" * 40,
        )


def test_assembler_fails_closed_on_nonempty_output_or_non_https_urls(tmp_path: Path) -> None:
    assembler = _load_assembler()
    output = tmp_path / "release"
    output.mkdir()
    (output / "ambient.txt").write_text("unverified\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must use https"):
        assembler.assemble_release(
            REPO_ROOT,
            tmp_path / "other",
            candidate_version="0.9.0b2",
            candidate_commit="a" * 40,
            artifact_base_url="http://example.invalid/release",
        )
    with pytest.raises(FileExistsError, match="not empty"):
        assembler.assemble_release(
            REPO_ROOT,
            output,
            candidate_version="0.9.0b2",
            candidate_commit="a" * 40,
            artifact_base_url="https://example.invalid/release",
        )


@pytest.mark.parametrize("failure_stage", ["copy", "manifest", "checksum", "allowlist"])
def test_assembler_failure_never_publishes_partial_output_or_debris(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    assembler = _load_assembler()
    _stub_assembly_commands(monkeypatch, assembler)
    version = "9.9.9"
    output = tmp_path / "release"
    original_copyfile = shutil.copyfile
    original_write_text = Path.write_text

    if failure_stage == "copy":
        def fail_copy(source, destination, *args, **kwargs):
            if Path(destination).name == "install-plugin.sh":
                raise OSError("injected asset-copy failure")
            return original_copyfile(source, destination, *args, **kwargs)

        monkeypatch.setattr(assembler.shutil, "copyfile", fail_copy)
    elif failure_stage == "manifest":
        def fail_manifest(path: Path, data: str, *args, **kwargs):
            if path.name == "release-assets.json":
                raise OSError("injected manifest failure")
            return original_write_text(path, data, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", fail_manifest)
    elif failure_stage == "checksum":
        original_sha256 = assembler._sha256

        def fail_checksum(path: Path) -> str:
            if path.name == "latest.json":
                raise OSError("injected checksum failure")
            return original_sha256(path)

        monkeypatch.setattr(assembler, "_sha256", fail_checksum)
    else:
        def inject_unexpected_asset(path: Path, data: str, *args, **kwargs):
            result = original_write_text(path, data, *args, **kwargs)
            if path.name == "SHA256SUMS":
                (path.parent / "unexpected.txt").write_text("injected\n", encoding="utf-8")
            return result

        monkeypatch.setattr(Path, "write_text", inject_unexpected_asset)

    with pytest.raises((OSError, ValueError)):
        assembler.assemble_release(
            REPO_ROOT,
            output,
            candidate_version=version,
            candidate_commit="a" * 40,
            artifact_base_url="https://example.invalid/release",
        )

    assert not output.exists()
    _assert_no_assembly_debris(output, version)


def test_assembler_failure_preserves_preexisting_empty_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assembler = _load_assembler()
    _stub_assembly_commands(monkeypatch, assembler)
    output = tmp_path / "release"
    output.mkdir()
    monkeypatch.setattr(
        assembler,
        "_sha256",
        lambda path: (_ for _ in ()).throw(OSError("injected late failure")),
    )

    with pytest.raises(OSError, match="injected late failure"):
        assembler.assemble_release(
            REPO_ROOT,
            output,
            candidate_version="9.9.8",
            candidate_commit="a" * 40,
            artifact_base_url="https://example.invalid/release",
        )

    assert output.is_dir() and not any(output.iterdir())
    _assert_no_assembly_debris(output, "9.9.8")


def test_assembler_atomically_promotes_complete_verified_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assembler = _load_assembler()
    _stub_assembly_commands(monkeypatch, assembler)
    output = tmp_path / "release"
    output.mkdir()
    version = "9.9.9"

    result = assembler.assemble_release(
        REPO_ROOT,
        output,
        candidate_version=version,
        candidate_commit="a" * 40,
        artifact_base_url="https://example.invalid/release",
    )

    assert set(result["files"]) == {path.name for path in output.iterdir()}
    assert set(result["files"]) == {
        "z_harness-9.9.9-py3-none-any.whl",
        f"z-harness-{version}.tar.gz",
        "latest.json",
        "release-assets.json",
        "SHA256SUMS",
        "install.sh",
        "install-plugin.sh",
    }
    _assert_no_assembly_debris(output, version)
