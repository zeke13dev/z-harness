"""Contracts for atomic live release-host evidence capture."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import venv
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conformance import test_strict as strict
from tests.test_release_candidate_verify import _fixture
from runtime import release_surface
from z_harness_cli import release_host_evidence as evidence_authority


REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "capture-release-host-evidence.py"
ASSEMBLER = REPO_ROOT / "scripts" / "assemble-release.py"
SPEC = importlib.util.spec_from_file_location("capture_release_host_evidence", SCRIPT)
assert SPEC and SPEC.loader
capture_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capture_mod
SPEC.loader.exec_module(capture_mod)

ASSEMBLER_SPEC = importlib.util.spec_from_file_location(
    "release_host_evidence_assembler", ASSEMBLER
)
assert ASSEMBLER_SPEC and ASSEMBLER_SPEC.loader
assembler_mod = importlib.util.module_from_spec(ASSEMBLER_SPEC)
sys.modules[ASSEMBLER_SPEC.name] = assembler_mod
ASSEMBLER_SPEC.loader.exec_module(assembler_mod)


@pytest.fixture(autouse=True)
def _protected_test_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-protected-anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-protected-openai")


def _artifact_identity(path: Path) -> dict[str, str]:
    return {"name": path.name, "sha256": capture_mod._sha256_bytes(path.read_bytes())}


def _rewrite_checksums(artifacts: Path) -> None:
    paths = [path for path in artifacts.iterdir() if path.name != "SHA256SUMS"]
    (artifacts / "SHA256SUMS").write_text(
        "".join(
            f"{capture_mod._sha256_bytes(path.read_bytes())}  {path.name}\n"
            for path in sorted(paths)
        ),
        encoding="utf-8",
    )


def _live_omp_record(artifacts: Path, candidate_sha: str) -> dict[str, object]:
    record = json.loads((strict.Z_FIX_FIXTURE_ROOT / "omp.json").read_text(encoding="utf-8"))
    wheel = next(artifacts.glob("*.whl"))
    identity = _artifact_identity(wheel)
    record.update(
        {
            "fixture_mode": False,
            "candidate_sha": candidate_sha,
            "artifact": identity,
            "diagnostics": ["Live isolated OMP host execution completed successfully."],
            "provenance": {
                "runner": "live-release-host-recorder-v1",
                "environment": "outside-checkout-installed-wheel",
                "evidence_root_kind": "live-release-host-capture",
            },
        }
    )
    proof = record["proof"]
    proof.update(
        {
            "candidate_sha": candidate_sha,
            "wheel_filename": identity["name"],
            "wheel_sha256": identity["sha256"],
            "import_path": "/isolated/venv/lib/python3.12/site-packages/z_harness_cli/__init__.py",
            "dispatch_probe": evidence_authority.expected_dispatch_probe(candidate_sha),
            "runner": "live omp installed-wheel smoke",
        }
    )
    return record


def _live_record(host: str, artifacts: Path, candidate_sha: str) -> dict[str, object]:
    if host == "omp":
        return _live_omp_record(artifacts, candidate_sha)
    record = json.loads((strict.Z_FIX_FIXTURE_ROOT / f"{host}.json").read_text(encoding="utf-8"))
    artifact_path = (
        next(artifacts.glob("z-harness-*.tar.gz"))
        if host in {"claude", "codex"}
        else next(artifacts.glob("*.whl"))
    )
    record.update(
        {
            "fixture_mode": False,
            "candidate_sha": candidate_sha,
            "artifact": _artifact_identity(artifact_path),
            "diagnostics": [f"Live isolated {host} host execution completed successfully."],
            "provenance": {
                "runner": "live-release-host-recorder-v1",
                "environment": "clean-live-release-host",
                "evidence_root_kind": "live-release-host-capture",
            },
        }
    )
    if host in {"claude", "codex"}:
        record["proof"]["dispatch_probe"] = evidence_authority.expected_dispatch_probe(
            candidate_sha
        )
    return record


def _case(tmp_path: Path):
    verifier_args, _ = _fixture(tmp_path)
    artifacts = Path(verifier_args.artifacts)
    raw = tmp_path / "raw.json"
    raw.write_text(
        json.dumps(_live_omp_record(artifacts, verifier_args.candidate_sha)), encoding="utf-8"
    )
    destination_root = tmp_path / "captured"
    destination_root.mkdir()
    destination = destination_root / "omp.json"
    args = argparse.Namespace(
        candidate_sha=verifier_args.candidate_sha,
        artifacts=str(artifacts),
        destination=str(destination),
        **_capture_identity(tmp_path, verifier_args.candidate_sha, "omp"),
    )
    return args, raw, destination, artifacts


def _capture_identity(tmp_path: Path, candidate_sha: str, host: str) -> dict[str, object]:
    isolated_home = tmp_path / f"{host}-home"
    isolated_home.mkdir(exist_ok=True)
    payload = isolated_home / "plugin"
    payload.mkdir(exist_ok=True)
    (payload / "plugin.json").write_text("{}", encoding="utf-8")
    import_path = isolated_home / "lib" / "python3.13" / "site-packages" / "z_harness_cli" / "__init__.py"
    import_path.parent.mkdir(parents=True, exist_ok=True)
    import_path.write_text("", encoding="utf-8")
    command = [
        sys.executable,
        "-c",
        f"print({evidence_authority.expected_dispatch_probe(candidate_sha)!r})",
    ]
    cli_executable = None
    if host == "cli":
        state = isolated_home / "version"
        state.write_text("0.0.1", encoding="utf-8")
        cli_executable = isolated_home / "z-harness"
        cli_executable.write_text(
            f"#!/bin/sh\nprintf 'z-harness %s\\n' \"$(cat {state})\"\n", encoding="utf-8"
        )
        cli_executable.chmod(0o755)
        command = [sys.executable, "-c", f"from pathlib import Path; Path({str(state)!r}).write_text('0.9.0b2')"]
    if host == "omp":
        command = [
            sys.executable,
            "-c",
            f"print('IMPORT_PATH={import_path}\\n{evidence_authority.expected_dispatch_probe(candidate_sha)}')",
        ]
    omp_plugin_root = isolated_home / "export" / ".omp" / "z-harness"
    omp_plugin_root.mkdir(parents=True, exist_ok=True)
    return {
        "host": host,
        "isolated_home": str(isolated_home),
        "payload_path": str(payload) if host in {"claude", "codex"} else None,
        "cli_executable": str(cli_executable) if cli_executable else None,
        "omp_plugin_root": str(omp_plugin_root) if host == "omp" else None,
        "producer_repository": "zeke13dev/z-harness",
        "producer_workflow": ".github/workflows/release-evidence.yml",
        "producer_run_id": 12345,
        "producer_job": "produce",
        "producer_environment": "release-evidence",
        "producer_event": "workflow_dispatch",
        "producer_head_sha": candidate_sha,
        "execute_command": command,
    }


def test_capture_recomputes_fingerprint_and_produces_strict_valid_record(tmp_path: Path) -> None:
    args, raw, destination, artifacts = _case(tmp_path)
    raw_record = json.loads(raw.read_text(encoding="utf-8"))
    raw_record["provenance"]["artifact_set_fingerprint"] = "f" * 64
    raw.write_text(json.dumps(raw_record), encoding="utf-8")

    stamped = capture_mod.capture(args)

    expected_fingerprint = capture_mod._inventory(artifacts)[0]
    assert stamped["candidate_sha"] == args.candidate_sha
    assert stamped["provenance"]["artifact_set_fingerprint"] == expected_fingerprint
    assert json.loads(destination.read_text(encoding="utf-8")) == stamped
    claims, errors = strict.derive_release_claims()
    assert errors == []
    common_errors = strict._validate_common_record(
        stamped,
        host="omp",
        claim=claims["omp"],
        claims_fingerprint=strict._claim_fingerprint(claims),
        candidate_sha=args.candidate_sha,
        allow_test_fixtures=False,
    )
    assert common_errors == []
    assert strict._validate_omp_proof(stamped["proof"], stamped["artifact"], args.candidate_sha) == []


def test_four_captured_records_pass_strict_and_candidate_verifier(tmp_path: Path) -> None:
    verifier_args, _ = _fixture(tmp_path)
    artifacts = Path(verifier_args.artifacts)
    evidence_root = tmp_path / "live-evidence"
    raw_root = tmp_path / "raw-records"
    evidence_root.mkdir()
    raw_root.mkdir()
    for host in ("claude", "cli", "codex", "omp"):
        raw = raw_root / f"{host}.json"
        raw.write_text(
            json.dumps(_live_record(host, artifacts, verifier_args.candidate_sha)),
            encoding="utf-8",
        )
        capture_mod.capture(
            argparse.Namespace(
                candidate_sha=verifier_args.candidate_sha,
                artifacts=str(artifacts),
                destination=str(evidence_root / f"{host}.json"),
                **_capture_identity(tmp_path, verifier_args.candidate_sha, host),
            )
        )
    assert strict.validate_release_evidence(evidence_root, verifier_args.candidate_sha) == []

    verifier_script = REPO_ROOT / "scripts" / "release-candidate-verify.py"
    verifier_spec = importlib.util.spec_from_file_location("captured_record_verifier", verifier_script)
    assert verifier_spec and verifier_spec.loader
    verifier = importlib.util.module_from_spec(verifier_spec)
    sys.modules[verifier_spec.name] = verifier
    verifier_spec.loader.exec_module(verifier)
    verifier._verify_claimed_host_evidence(
        evidence_root,
        verifier_args.candidate_sha,
        verifier._inventory(artifacts)[0],
        REPO_ROOT,
        os.environ.copy(),
    )


def test_capture_rejects_nonexact_artifact_directory(tmp_path: Path) -> None:
    args, _, destination, artifacts = _case(tmp_path)
    (artifacts / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(capture_mod.CaptureError, match="exact seven-file"):
        capture_mod.capture(args)
    assert not destination.exists()


def test_capture_cli_rejects_caller_authored_record_argument(tmp_path: Path) -> None:
    args, raw, destination, artifacts = _case(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--candidate-sha", args.candidate_sha,
         "--artifacts", str(artifacts), "--host", "omp",
         "--isolated-home", args.isolated_home, "--destination", str(destination),
         "--raw-record", str(raw),
         "--producer-repository", args.producer_repository,
         "--producer-workflow", args.producer_workflow,
         "--producer-run-id", str(args.producer_run_id),
         "--producer-job", args.producer_job,
         "--producer-environment", args.producer_environment,
         "--producer-event", args.producer_event,
         "--producer-head-sha", args.producer_head_sha,
         "--execute-command", *args.execute_command],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert "raw-record" in result.stderr
    assert not destination.exists()


@pytest.mark.parametrize("url_field", ["wheel_url", "plugin_tarball_url"])
def test_capture_rejects_checksum_consistent_non_https_manifest_url(
    tmp_path: Path, url_field: str
) -> None:
    args, _, destination, artifacts = _case(tmp_path)
    latest_path = artifacts / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest[url_field] = latest[url_field].replace("https://", "http://", 1)
    latest_path.write_text(json.dumps(latest), encoding="utf-8")
    _rewrite_checksums(artifacts)
    with pytest.raises(capture_mod.CaptureError, match="canonical HTTPS"):
        capture_mod.capture(args)
    assert not destination.exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is unavailable on this platform")
def test_required_fifo_slot_fails_before_any_blocking_read(tmp_path: Path) -> None:
    args, _, destination, artifacts = _case(tmp_path)
    latest_path = artifacts / "latest.json"
    latest_path.unlink()
    os.mkfifo(latest_path)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--candidate-sha",
            args.candidate_sha,
                "--artifacts",
                str(artifacts),
                "--host", "omp",
                "--isolated-home", args.isolated_home,
            "--destination",
            args.destination,
            "--producer-repository", "zeke13dev/z-harness",
            "--producer-workflow", ".github/workflows/release-evidence.yml",
            "--producer-run-id", "12345",
            "--producer-job", "produce",
            "--producer-environment", "release-evidence",
            "--producer-event", "workflow_dispatch",
            "--producer-head-sha", args.candidate_sha,
                "--execute-command", *args.execute_command,
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 1
    assert "regular non-symlink file: latest.json" in result.stderr
    assert not destination.exists()


def test_capture_never_overwrites_existing_destination(tmp_path: Path) -> None:
    args, _, destination, _ = _case(tmp_path)
    destination.write_text("foreign\n", encoding="utf-8")
    with pytest.raises(capture_mod.CaptureError, match="already exists"):
        capture_mod.capture(args)
    assert destination.read_text(encoding="utf-8") == "foreign\n"


def test_capture_fails_closed_when_owned_execution_fails(tmp_path: Path) -> None:
    args, _, destination, _ = _case(tmp_path)
    args.execute_command = [sys.executable, "-c", "raise SystemExit(17)"]
    with pytest.raises(capture_mod.CaptureError, match="exit code 17"):
        capture_mod.capture(args)
    assert not destination.exists()


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
@pytest.mark.parametrize("output_kind", ["ordinary", "wrong_sha"])
def test_zero_exit_without_exact_dispatch_probe_fails_closed(
    tmp_path: Path, host: str, output_kind: str
) -> None:
    verifier_args, _ = _fixture(tmp_path)
    artifacts = Path(verifier_args.artifacts)
    destination_root = tmp_path / "rejected-evidence"
    destination_root.mkdir()
    identity = _capture_identity(tmp_path, verifier_args.candidate_sha, host)
    output = "host operation passed"
    if output_kind == "wrong_sha":
        output = evidence_authority.expected_dispatch_probe("f" * 40)
    if host == "omp":
        import_path = (
            Path(str(identity["isolated_home"]))
            / "lib/python3.13/site-packages/z_harness_cli/__init__.py"
        )
        output = f"IMPORT_PATH={import_path}\n{output}"
    identity["execute_command"] = [sys.executable, "-c", f"print({output!r})"]
    args = argparse.Namespace(
        candidate_sha=verifier_args.candidate_sha,
        artifacts=str(artifacts),
        destination=str(destination_root / f"{host}.json"),
        **identity,
    )

    with pytest.raises(capture_mod.CaptureError, match="exactly one dispatch probe"):
        capture_mod.capture(args)
    assert not Path(args.destination).exists()


@pytest.mark.parametrize("host", ["claude", "codex", "omp"])
def test_production_dispatch_validator_requires_exact_candidate_marker(host: str) -> None:
    candidate_sha = "a" * 40
    expected = evidence_authority.expected_dispatch_probe(candidate_sha)

    assert evidence_authority.validate_dispatch_probe(
        host, {"dispatch_probe": expected}, candidate_sha
    ) == []
    assert evidence_authority.validate_dispatch_probe(
        host, {"dispatch_probe": evidence_authority.expected_dispatch_probe("b" * 40)}, candidate_sha
    ) == [f"{host}: proof.dispatch_probe does not match the exact candidate SHA"]


def test_capture_does_not_leak_ambient_provider_or_host_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, _, _, _ = _case(tmp_path)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-secret")
    monkeypatch.setenv("CODEX_HOME", "/ambient/codex")
    check = (
        "import os; "
        "assert 'AWS_SECRET_ACCESS_KEY' not in os.environ; "
        "assert os.environ['CODEX_HOME'].startswith(os.environ['HOME']); "
        "assert os.environ['OMP_PLUGIN_ROOT'].startswith(os.environ['HOME']); "
        f"print('IMPORT_PATH={args.isolated_home}/lib/python3.13/site-packages/z_harness_cli/__init__.py\\n"
        f"{evidence_authority.expected_dispatch_probe(args.candidate_sha)}')"
    )
    args.execute_command = [sys.executable, "-c", check]
    stamped = capture_mod.capture(args)
    assert stamped["status"] == "passed"


def test_capture_fails_closed_without_protected_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, _, destination, _ = _case(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(capture_mod.CaptureError, match="required protected credential"):
        capture_mod.capture(args)
    assert not destination.exists()


def test_cli_noop_cannot_claim_update_transition(tmp_path: Path) -> None:
    verifier_args, _ = _fixture(tmp_path)
    artifacts = Path(verifier_args.artifacts)
    destination = tmp_path / "cli-evidence"
    destination.mkdir()
    identity = _capture_identity(tmp_path, verifier_args.candidate_sha, "cli")
    identity["execute_command"] = [sys.executable, "-c", "pass"]
    args = argparse.Namespace(
        candidate_sha=verifier_args.candidate_sha, artifacts=str(artifacts),
        destination=str(destination / "cli.json"), **identity,
    )
    with pytest.raises(capture_mod.CaptureError, match="transition to the exact candidate"):
        capture_mod.capture(args)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("workflow", ".github/workflows/other.yml", "workflow"),
        ("run_id", 0, "run_id"),
        ("event", "push", "event"),
        ("head_sha", "f" * 40, "head SHA"),
        ("execution_digest", "f" * 63, "execution digest"),
    ],
)
def test_production_authority_rejects_untrusted_producer_identity(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    args, _, _, _ = _case(tmp_path)
    stamped = capture_mod.capture(args)
    stamped["producer"][field] = value
    claims, errors = evidence_authority.derive_release_claims()
    assert errors == []
    common_errors = evidence_authority.validate_common_record(
        stamped,
        host="omp",
        claim=claims["omp"],
        claims_fingerprint=evidence_authority.claim_fingerprint(claims),
        candidate_sha=args.candidate_sha,
        allow_test_fixtures=False,
    )
    assert any(message in error for error in common_errors)


@pytest.mark.parametrize("failure", ["file-fsync", "replace", "dir-fsync"])
def test_atomic_failure_leaves_no_destination_or_temporary(
    tmp_path: Path, failure: str
) -> None:
    args, _, destination, _ = _case(tmp_path)
    real_fsync = capture_mod.os.fsync
    calls = 0

    def injected_fsync(fd):
        nonlocal calls
        calls += 1
        if (failure == "file-fsync" and calls == 1) or (failure == "dir-fsync" and calls == 2):
            raise OSError("injected fsync failure")
        return real_fsync(fd)

    replace_effect = OSError("injected replace failure") if failure == "replace" else None
    with (
        patch.object(capture_mod.os, "fsync", side_effect=injected_fsync),
        patch.object(capture_mod.os, "replace", side_effect=replace_effect, wraps=os.replace),
        pytest.raises(OSError, match="injected"),
    ):
        capture_mod.capture(args)
    assert not destination.exists()
    assert list(destination.parent.glob(f".{destination.name}.*.tmp")) == []


def test_capture_source_has_no_git_or_publication_mutation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("git tag", "git push", "gh release", "publish", "upload"):
        assert forbidden not in source


def test_fresh_wheel_runs_real_capture_outside_checkout_without_undeclared_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_sha = "a" * 40
    candidate_version = "0.9.0-beta.2"
    source_root = tmp_path / "archive-source"
    shutil.copytree(
        REPO_ROOT,
        source_root,
        ignore=shutil.ignore_patterns(".git", ".venv", "dist", "__pycache__", "*.pyc"),
    )
    # The assembler's portable shell entry points must exercise the platform
    # system tools, not an unrelated interactive/package-manager Bash from the
    # developer's ambient PATH.
    monkeypatch.setenv("PATH", os.defpath)
    artifacts = tmp_path / "assembled-release"
    assembler_mod.assemble_release(
        source_root,
        artifacts,
        candidate_version=candidate_version,
        candidate_commit=candidate_sha,
        artifact_base_url="https://example.invalid/releases/v0.9.0-beta.2",
    )
    wheel = next(artifacts.glob("*.whl"))
    raw_record = tmp_path / "raw.json"
    raw_record.write_text(
        json.dumps(_live_omp_record(artifacts, candidate_sha)), encoding="utf-8"
    )
    destination = tmp_path / "captured" / "omp.json"
    destination.parent.mkdir()

    documented_commands: set[str] = set()
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        public_documents = release_surface.release_contract()["prod_inventory"][
            "public_documents"
        ]
        for relative in public_documents:
            if relative not in names or Path(relative).suffix not in {".md", ".json"}:
                continue
            body = archive.read(relative).decode("utf-8")
            documented_commands.update(
                re.findall(
                    r"`(?:bash\s+)?(scripts/[A-Za-z0-9][A-Za-z0-9._/-]*\.(?:sh|py))",
                    body,
                )
            )
            documented_commands.update(
                line.strip().removeprefix("bash ")
                for line in body.splitlines()
                if re.fullmatch(
                    r"(?:bash\s+)?scripts/[A-Za-z0-9][A-Za-z0-9._/-]*\.(?:sh|py)",
                    line.strip(),
                )
            )
        assert documented_commands
        assert documented_commands <= names

    environment_root = tmp_path / "wheel-env"
    venv.EnvBuilder(with_pip=True).create(environment_root)
    python = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    install = subprocess.run(
        [str(python), "-I", "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr
    site_packages = next(environment_root.glob("lib/python*/site-packages"))
    installed_script = site_packages / "scripts" / SCRIPT.name
    assert installed_script.is_file()
    assert all((site_packages / command).is_file() for command in documented_commands)
    changelog_installer = site_packages / "scripts" / "install-changelog-hook.sh"
    changelog_worker = site_packages / "scripts" / "changelog-from-commit.sh"
    assert changelog_installer.is_file()
    assert changelog_worker.is_file()
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE"}
    }
    clean_env["GITHUB_WORKSPACE"] = str(source_root)
    dependency_probe = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import importlib.util; assert importlib.util.find_spec('pytest') is None; "
            "assert importlib.util.find_spec('tests') is None; "
            "assert importlib.util.find_spec('packaging') is None",
        ],
        cwd=tmp_path,
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert dependency_probe.returncode == 0, dependency_probe.stderr
    hook_repo = tmp_path / "hook-repo"
    hook_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=hook_repo, env=clean_env, check=True)
    install_hook = subprocess.run(
        ["/bin/bash", str(changelog_installer), "install"],
        cwd=hook_repo,
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert install_hook.returncode == 0, install_hook.stderr
    installed_hook = hook_repo / ".git" / "hooks" / "post-commit"
    assert installed_hook.is_file() and os.access(installed_hook, os.X_OK)
    hook_body = installed_hook.read_text(encoding="utf-8")
    assert str(changelog_worker) in hook_body
    hook_run = subprocess.run(
        ["/bin/bash", str(installed_hook)],
        cwd=hook_repo,
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert hook_run.returncode == 0, hook_run.stderr
    omp_plugin_root = environment_root / "export" / ".omp" / "z-harness"
    omp_plugin_root.mkdir(parents=True)
    capture_result = subprocess.run(
        [
            str(python), "-I", "-B", str(installed_script),
            "--candidate-sha", candidate_sha,
            "--artifacts", str(artifacts),
            "--host", "omp",
            "--isolated-home", str(environment_root),
            "--omp-plugin-root", str(omp_plugin_root),
            "--destination", str(destination),
            "--producer-repository", "zeke13dev/z-harness",
            "--producer-workflow", ".github/workflows/release-evidence.yml",
            "--producer-run-id", "12345",
            "--producer-job", "produce",
            "--producer-environment", "release-evidence",
            "--producer-event", "workflow_dispatch",
            "--producer-head-sha", candidate_sha,
            "--execute-command", str(python), "-I", "-c",
            "import z_harness_cli; print('IMPORT_PATH=' + z_harness_cli.__file__ + '\\nZ_HARNESS_Z_FIX_DISPATCH_V1:" + candidate_sha + "')",
        ],
        cwd=tmp_path,
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert capture_result.returncode == 0, capture_result.stderr
    stamped = json.loads(destination.read_text(encoding="utf-8"))
    assert stamped["provenance"]["artifact_set_fingerprint"] == capture_mod._inventory(artifacts)[0]
    authority_probe = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import z_harness_cli.release_host_evidence as authority; print(authority.__file__)",
        ],
        cwd=tmp_path,
        env=clean_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert authority_probe.returncode == 0, authority_probe.stderr
    assert Path(authority_probe.stdout.strip()).resolve().is_relative_to(
        site_packages.resolve()
    )
    claims, errors = evidence_authority.derive_release_claims()
    assert errors == []
    assert evidence_authority.validate_common_record(
        stamped,
        host="omp",
        claim=claims["omp"],
        claims_fingerprint=evidence_authority.claim_fingerprint(claims),
        candidate_sha=candidate_sha,
        allow_test_fixtures=False,
    ) == []
    assert evidence_authority.validate_omp_proof(
        stamped["proof"], stamped["artifact"], candidate_sha
    ) == []
