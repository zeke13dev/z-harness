"""Focused contracts for the non-publishing exact-candidate verifier."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest


REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "release-candidate-verify.py"
SPEC = importlib.util.spec_from_file_location("release_candidate_verify", SCRIPT)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[argparse.Namespace, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Release Test")
    (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "candidate")
    sha = _git(repo, "rev-parse", "HEAD")

    candidate = tmp_path / "candidate"
    (candidate / ".codex-plugin").mkdir(parents=True)
    (candidate / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "z-harness", "version": "0.9.0-beta.2", "candidate_commit": sha}),
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    wheel = artifacts / "z_harness-0.9.0b2-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "z_harness-0.9.0b2.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: z-harness\nVersion: 0.9.0b2\n",
        )
        archive.writestr(
            "z_harness/.codex-plugin/plugin.json",
            json.dumps({"name": "z-harness", "version": "0.9.0-beta.2"}),
        )
    tarball = artifacts / "z-harness-0.9.0-beta.2.tar.gz"
    import io
    import tarfile

    with tarfile.open(tarball, "w:gz") as archive:
        body = json.dumps({"name": "z-harness", "version": "0.9.0-beta.2"}).encode()
        member = tarfile.TarInfo("z-harness/.codex-plugin/plugin.json")
        member.size = len(body)
        archive.addfile(member, io.BytesIO(body))
    (artifacts / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (artifacts / "install-plugin.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    latest = {
        "schema_version": 1,
        "version": "0.9.0-beta.2",
        "wheel_url": f"https://example.invalid/{wheel.name}",
        "sha256": _digest(wheel),
        "plugin_tarball_url": f"https://example.invalid/{tarball.name}",
        "plugin_tarball_sha256": _digest(tarball),
        "cli_schema_version": 1,
        "telemetry_schema_version": 1,
        "min_supported_version": "0.1.0",
    }
    (artifacts / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    assets = {
        "schema_version": 1,
        "candidate_version": "0.9.0-beta.2",
        "candidate_commit": sha,
        "artifacts": {},
    }
    for path in (wheel, tarball, artifacts / "install.sh", artifacts / "install-plugin.sh"):
        assets["artifacts"][path.name] = _digest(path)
    assets_path = artifacts / "release-assets.json"
    assets_path.write_text(json.dumps(assets, sort_keys=True), encoding="utf-8")
    checksum_paths = [
        wheel,
        tarball,
        artifacts / "latest.json",
        assets_path,
        artifacts / "install.sh",
        artifacts / "install-plugin.sh",
    ]
    (artifacts / "SHA256SUMS").write_text(
        "".join(f"{_digest(path)}  {path.name}\n" for path in checksum_paths), encoding="utf-8"
    )
    host_evidence = tmp_path / "host-evidence"
    host_evidence.mkdir()
    (host_evidence / "evidence.json").write_text(
        json.dumps(
            {
                "candidate_sha": sha,
                "provenance": {
                    "artifact_set_fingerprint": verifier._inventory(artifacts)[0],
                },
                "status": "passed",
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence" / "result.json"
    evidence.parent.mkdir()
    return argparse.Namespace(
        candidate_version="0.9.0-beta.2",
        candidate_sha=sha,
        repo_root=str(repo),
        candidate_root=str(candidate),
        artifacts=str(artifacts),
        host_evidence_root=str(host_evidence),
        evidence_out=str(evidence),
    ), evidence


class FakeRunner:
    def __init__(self, *, fail_at: int | None = None, mutate=None):
        self.calls: list[tuple[str, ...]] = []
        self.environments: list[dict[str, str]] = []
        self.fail_at = fail_at
        self.mutate = mutate

    def __call__(self, argv, cwd, env):
        self.calls.append(tuple(argv))
        self.environments.append(dict(env))
        index = len(self.calls) - 1
        if self.mutate is not None:
            self.mutate(index)
        stdout = ""
        if "verify-closure" in argv:
            stdout = json.dumps({"ok": True, "errors": [], "dimensions": sorted(verifier.EXPECTED_CLOSURE_DIMENSIONS)})
        return subprocess.CompletedProcess(
            argv,
            1 if index == self.fail_at else 0,
            stdout,
            "failed" if index == self.fail_at else "",
        )


def test_success_runs_exact_fast_order_and_emits_recomputable_evidence(tmp_path: Path) -> None:
    namespace, evidence = _fixture(tmp_path)
    runner = FakeRunner()
    resolved = verifier._resolve_inputs(namespace)
    before = {
        "repo": verifier._inventory(Path(namespace.repo_root))[0],
        "candidate": verifier._inventory(Path(namespace.candidate_root))[0],
        "artifacts": verifier._inventory(Path(namespace.artifacts))[0],
        "host_evidence": verifier._inventory(Path(namespace.host_evidence_root))[0],
        "refs": verifier._git_snapshot(resolved)[2],
    }

    payload = verifier.verify(namespace, runner=runner)

    assert [lane["id"] for lane in payload["lanes"]] == [
        *verifier.FAST_LANE_IDS,
        *verifier.SLOW_LANE_IDS,
    ]
    assert len(runner.calls) == len(verifier.FAST_LANE_IDS) + len(verifier.SLOW_LANE_IDS)
    assert runner.calls[2][2:7] == (
        "-m",
        "z_harness_cli.release_surface",
        "verify-closure",
        "--root",
        str(Path(namespace.candidate_root).resolve()),
    )
    assert runner.calls[3][-1].endswith(
        "::InstallShIntegrityTest::test_every_fault_step_restores_full_all_host_cli_pre_state"
    )
    assert payload["candidate_sha"] == namespace.candidate_sha
    assert all(lane["input_fingerprint"] for lane in payload["lanes"])
    assert all(lane["platform"]["system"] for lane in payload["lanes"])
    fingerprint = payload.pop("evidence_fingerprint")
    assert fingerprint == verifier._sha256_bytes(verifier._canonical_json(payload))
    assert json.loads(evidence.read_text())["evidence_fingerprint"] == fingerprint
    assert before == {
        "repo": verifier._inventory(Path(namespace.repo_root))[0],
        "candidate": verifier._inventory(Path(namespace.candidate_root))[0],
        "artifacts": verifier._inventory(Path(namespace.artifacts))[0],
        "host_evidence": verifier._inventory(Path(namespace.host_evidence_root))[0],
        "refs": verifier._git_snapshot(resolved)[2],
    }


@pytest.mark.parametrize("failed_lane", range(5))
def test_each_fast_failure_stops_later_work_and_never_promotes_evidence(tmp_path: Path, failed_lane: int) -> None:
    namespace, evidence = _fixture(tmp_path)
    runner = FakeRunner(fail_at=failed_lane)
    with pytest.raises(verifier.VerificationError, match="fast lane failed"):
        verifier.verify(namespace, runner=runner)
    assert len(runner.calls) == failed_lane + 1
    assert not evidence.exists()


@pytest.mark.parametrize("dirty_kind", ["staged", "unstaged", "untracked"])
def test_dirty_repository_fails_before_lane_one(tmp_path: Path, dirty_kind: str) -> None:
    namespace, evidence = _fixture(tmp_path)
    repo = Path(namespace.repo_root)
    if dirty_kind == "staged":
        (repo / "staged.txt").write_text("x")
        _git(repo, "add", "staged.txt")
    elif dirty_kind == "unstaged":
        (repo / "tracked.txt").write_text("changed")
    else:
        (repo / "untracked.txt").write_text("x")
    runner = FakeRunner()
    with pytest.raises(verifier.VerificationError, match="clean"):
        verifier.verify(namespace, runner=runner)
    assert runner.calls == []
    assert not evidence.exists()


def test_wrong_sha_rejected_but_detached_exact_head_accepted(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    original = namespace.candidate_sha
    namespace.candidate_sha = "a" * 40
    with pytest.raises(verifier.VerificationError, match="HEAD"):
        verifier.verify(namespace, runner=FakeRunner())
    namespace.candidate_sha = original
    _git(Path(namespace.repo_root), "checkout", "--detach", "-q", original)
    verifier.verify(namespace, runner=FakeRunner())


@pytest.mark.parametrize("bad", ["v0.9.0-beta.2", "0.9.0b2"])
def test_noncanonical_candidate_alias_rejected(tmp_path: Path, bad: str) -> None:
    namespace, _ = _fixture(tmp_path)
    namespace.candidate_version = bad
    with pytest.raises(verifier.VerificationError, match="canonical"):
        verifier.verify(namespace, runner=FakeRunner())


@pytest.mark.parametrize("bad", ["a" * 39, "A" * 40, "g" * 40])
def test_nonexact_sha_rejected(tmp_path: Path, bad: str) -> None:
    namespace, _ = _fixture(tmp_path)
    namespace.candidate_sha = bad
    with pytest.raises(verifier.VerificationError, match="40 lowercase"):
        verifier.verify(namespace, runner=FakeRunner())


def test_symlinked_and_overlapping_inputs_and_existing_evidence_rejected(tmp_path: Path) -> None:
    namespace, evidence = _fixture(tmp_path)
    linked = Path(namespace.candidate_root) / "linked"
    linked.symlink_to(Path(namespace.repo_root) / "tracked.txt")
    with pytest.raises(verifier.VerificationError, match="symlink"):
        verifier.verify(namespace, runner=FakeRunner())
    linked.unlink()
    namespace.candidate_root = namespace.repo_root
    with pytest.raises(verifier.VerificationError, match="separate"):
        verifier.verify(namespace, runner=FakeRunner())
    namespace, evidence = _fixture(tmp_path / "again")
    evidence.write_text("old")
    with pytest.raises(verifier.VerificationError, match="already exists"):
        verifier.verify(namespace, runner=FakeRunner())


def test_candidate_mutation_between_lanes_rejected_without_evidence(tmp_path: Path) -> None:
    namespace, evidence = _fixture(tmp_path)
    marker = Path(namespace.candidate_root) / "marker.txt"
    runner = FakeRunner(mutate=lambda index: marker.write_text("drift") if index == 0 else None)
    with pytest.raises(verifier.VerificationError, match="changed"):
        verifier.verify(namespace, runner=runner)
    assert len(runner.calls) == 1
    assert not evidence.exists()


@pytest.mark.parametrize("drift", ["artifacts", "status", "head"])
def test_other_candidate_state_drift_rejected_without_evidence(tmp_path: Path, drift: str) -> None:
    namespace, evidence = _fixture(tmp_path)
    repo = Path(namespace.repo_root)
    artifacts = Path(namespace.artifacts)

    def mutate(index: int) -> None:
        if index != 0:
            return
        if drift == "artifacts":
            (artifacts / "install.sh").write_text("drift")
        elif drift == "status":
            (repo / "tracked.txt").write_text("drift")
        else:
            (repo / "next.txt").write_text("next")
            _git(repo, "add", "next.txt")
            _git(repo, "commit", "-qm", "drift")

    runner = FakeRunner(mutate=mutate)
    with pytest.raises(verifier.VerificationError, match="changed|HEAD|clean"):
        verifier.verify(namespace, runner=runner)
    assert len(runner.calls) == 1
    assert not evidence.exists()


def test_ref_drift_between_lanes_rejected_without_evidence(tmp_path: Path) -> None:
    namespace, evidence = _fixture(tmp_path)
    repo = Path(namespace.repo_root)
    runner = FakeRunner(mutate=lambda index: _git(repo, "tag", "drift") if index == 0 else None)
    with pytest.raises(verifier.VerificationError, match="changed"):
        verifier.verify(namespace, runner=runner)
    assert not evidence.exists()


def test_c3_structured_failure_rejects_even_with_zero_exit(tmp_path: Path) -> None:
    namespace, evidence = _fixture(tmp_path)
    runner = FakeRunner()

    def bad_c3(argv, cwd, env):
        result = runner(argv, cwd, env)
        if "verify-closure" in argv:
            result.stdout = json.dumps({"ok": True, "errors": [], "dimensions": ["skill-script"]})
        return result

    with pytest.raises(verifier.VerificationError, match="dimension"):
        verifier.verify(namespace, runner=bad_c3)
    assert not evidence.exists()


def test_command_inventory_contains_no_mutating_or_publication_command(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    inputs = verifier._resolve_inputs(namespace)
    commands = verifier._lane_commands(inputs)
    verifier._validate_lane_commands(commands, inputs)
    forbidden_git = {
        "checkout", "switch", "reset", "clean", "commit", "merge", "tag", "branch",
        "update-ref", "fetch", "pull", "push", "worktree",
    }
    for _, argv in commands:
        assert not ({"gh", "release"} <= set(argv))
        assert not any(token in argv for token in ("upload", "publish"))
        for index, token in enumerate(argv):
            if token == "git" and index + 1 < len(argv):
                assert argv[index + 1] not in forbidden_git


@pytest.mark.parametrize(
    "embedded_mutation",
    [
        "os.system('git tag bad')",
        "from subprocess import run; run(['git', 'push', 'origin'])",
        "__import__('subprocess').run(['gh', 'release', 'create'])",
        "eval(compile('git fetch --force', '<x>', 'exec'))",
        "exec(\"subprocess.run(['git', 'checkout', 'prod'])\")",
    ],
)
def test_dynamic_payload_spellings_are_rejected(tmp_path: Path, embedded_mutation: str) -> None:
    namespace, _ = _fixture(tmp_path)
    inputs = verifier._resolve_inputs(namespace)
    commands = list(verifier._lane_commands(inputs))
    lane_id, argv = commands[-1]
    commands[-1] = (lane_id, (*argv, embedded_mutation))
    with pytest.raises(verifier.VerificationError, match="fixed read-only"):
        verifier._validate_lane_commands(tuple(commands), inputs)


def test_dynamic_python_switch_is_rejected_and_production_has_none(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    inputs = verifier._resolve_inputs(namespace)
    commands = verifier._lane_commands(inputs)
    assert all("-c" not in argv for _, argv in commands)
    mutated = list(commands)
    lane_id, argv = mutated[-1]
    mutated[-1] = (lane_id, (*argv, "-c", "os.system('git tag bad')"))
    with pytest.raises(verifier.VerificationError, match="dynamic Python"):
        verifier._validate_lane_commands(tuple(mutated), inputs)


def test_fixed_internal_lanes_execute_without_dynamic_payload(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    inputs = verifier._resolve_inputs(namespace)
    commands = verifier._lane_commands(inputs)
    environment = {"PYTHONDONTWRITEBYTECODE": "1"}
    for index in (0, 1, 4):
        _, command = commands[index]
        result = verifier._run_command(command, inputs.repo_root, environment)
        assert result.returncode == 0, result.stderr


def test_c5_checks_survive_optimized_python(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    inputs = verifier._resolve_inputs(namespace)
    _, command = verifier._lane_commands(inputs)[-1]
    bad_command = list(command)
    bad_command[2] = "f" * 40
    environment = os.environ.copy()
    environment["PYTHONOPTIMIZE"] = "1"
    result = verifier._run_command(bad_command, inputs.repo_root, environment)
    assert result.returncode != 0
    assert "HEAD mismatch" in result.stderr


def test_verifier_removes_ambient_python_optimization(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    runner = FakeRunner()
    with patch.dict(os.environ, {"PYTHONOPTIMIZE": "2"}):
        verifier.verify(namespace, runner=runner)
    assert all("PYTHONOPTIMIZE" not in environment for environment in runner.environments)


def test_slow_lanes_start_only_after_fast_success_and_fail_closed(tmp_path: Path) -> None:
    namespace, evidence = _fixture(tmp_path)
    first_slow = len(verifier.FAST_LANE_IDS)
    runner = FakeRunner(fail_at=first_slow)
    with pytest.raises(verifier.VerificationError, match="slow lane failed: python-suite"):
        verifier.verify(namespace, runner=runner)
    assert len(runner.calls) == first_slow + 1
    assert not evidence.exists()


def test_slow_lane_inventory_is_blocking_and_has_no_checkout_shape_skip(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    inputs = verifier._resolve_inputs(namespace)
    commands = verifier._slow_lane_commands(inputs)
    verifier._validate_slow_lane_commands(commands, inputs)
    by_id = dict(commands)
    assert by_id["normal-clone"][:2] == ("internal:checkout-shape", "normal-clone")
    assert by_id["linked-worktree"][:2] == ("internal:checkout-shape", "linked-worktree")
    assert "--allow-missing" not in by_id["claimed-host-evidence"]
    assert "--test-fixture-mode" not in by_id["claimed-host-evidence"]
    assert by_id["claimed-host-evidence"][0] == "internal:claimed-host-evidence"
    assert by_id["claimed-host-evidence"][3] == verifier._inventory(inputs.artifacts)[0]
    assert by_id["installed-wheel-outside-checkout"][0] == "internal:installed-wheel"


def test_ambient_home_provider_and_webhook_state_is_not_inherited(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    runner = FakeRunner()
    poisoned = {
        "HOME": "/ambient/home",
        "XDG_CONFIG_HOME": "/ambient/config",
        "Z_HARNESS_REPO_PROVIDERS": "/ambient/providers.json",
        "SLACK_WEBHOOK_URL": "secret",
        "OPENAI_API_KEY": "secret",
        "PYTHONPATH": str(REPO_ROOT),
    }
    with patch.dict(os.environ, poisoned, clear=False):
        verifier.verify(namespace, runner=runner)
    for environment in runner.environments:
        assert environment["HOME"] != poisoned["HOME"]
        assert environment["XDG_CONFIG_HOME"] != poisoned["XDG_CONFIG_HOME"]
        assert "Z_HARNESS_REPO_PROVIDERS" not in environment
        assert "SLACK_WEBHOOK_URL" not in environment
        assert "OPENAI_API_KEY" not in environment
        assert "PYTHONPATH" not in environment


def test_missing_or_mutated_claimed_host_evidence_fails_closed(tmp_path: Path) -> None:
    namespace, evidence = _fixture(tmp_path)
    missing = tmp_path / "missing-host-evidence"
    namespace.host_evidence_root = str(missing)
    with pytest.raises(FileNotFoundError):
        verifier.verify(namespace, runner=FakeRunner())
    namespace, evidence = _fixture(tmp_path / "mutated")
    marker = Path(namespace.host_evidence_root) / "evidence.json"
    runner = FakeRunner(mutate=lambda index: marker.write_text("drift") if index == 0 else None)
    with pytest.raises(verifier.VerificationError, match="changed"):
        verifier.verify(namespace, runner=runner)
    assert not evidence.exists()


def test_installed_wheel_lane_forbids_dev_deps_and_checkout_import_precedence() -> None:
    source = inspect.getsource(verifier._verify_installed_wheel)
    assert '"--no-deps"' in source
    assert 'isolated_env.pop("PYTHONPATH", None)' in source
    assert 'cwd=outside' in source
    assert '"-I"' in source
    assert '"z_harness_cli.mcp_prod_tool_list_smoke"' in source
    smoke_source = (REPO_ROOT / "scripts" / "omp-prod-export-smoke.py").read_text(
        encoding="utf-8"
    )
    assert "cwd=out_dir.parent" in smoke_source
    assert '"PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE"' in smoke_source


@pytest.mark.parametrize("kind", ["normal-clone", "linked-worktree"])
@pytest.mark.parametrize("failing_suite", ["python", "shell"])
def test_each_real_checkout_shape_blocks_on_full_python_and_shell_suite_failure(
    tmp_path: Path, kind: str, failing_suite: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sha = "a" * 40

    def fake_checked(argv, *, cwd, env):
        if argv[:2] == ("git", "clone"):
            clone = Path(argv[-1])
            (clone / ".git").mkdir(parents=True)
            return ""
        if argv[:3] == ("git", "worktree", "add"):
            target = Path(argv[-2])
            target.mkdir(parents=True)
            (target / ".git").write_text("gitdir: disposable\n", encoding="utf-8")
            return ""
        if argv[:3] == ("git", "rev-parse", "HEAD"):
            return sha + "\n"
        if "pytest" in argv and failing_suite == "python":
            raise verifier.VerificationError(f"{kind} python failure")
        if argv[:2] == ("make", "test-sh") and failing_suite == "shell":
            raise verifier.VerificationError(f"{kind} shell failure")
        return ""

    with (
        patch.object(verifier, "_checked", side_effect=fake_checked),
        pytest.raises(verifier.VerificationError, match=f"{kind} {failing_suite} failure"),
    ):
        verifier._verify_checkout_shape(kind, repo, sha, {})


def test_installed_wheel_lane_rejects_failed_import_origin_smoke(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "candidate.whl").write_bytes(b"wheel")
    candidate = tmp_path / "candidate"
    (candidate / "scripts").mkdir(parents=True)
    (candidate / "scripts" / "omp-prod-export-smoke.py").write_text("", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()

    def fail_import_smoke(argv, *, cwd, env):
        if "z_harness_cli.mcp_prod_tool_list_smoke" in argv:
            raise verifier.VerificationError("checkout instead of installed wheel")
        return ""

    with (
        patch.object(verifier, "_checked", side_effect=fail_import_smoke),
        pytest.raises(verifier.VerificationError, match="checkout instead of installed wheel"),
    ):
        verifier._verify_installed_wheel(artifacts, candidate, repo, {})


def test_claimed_host_evidence_rejects_same_sha_different_artifact_set(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    inputs = verifier._resolve_inputs(namespace)
    record_path = Path(namespace.host_evidence_root) / "evidence.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["provenance"]["artifact_set_fingerprint"] = "f" * 64
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with (
        patch.object(verifier, "_checked") as checked,
        pytest.raises(verifier.VerificationError, match="artifact-set mismatch"),
    ):
        verifier._verify_claimed_host_evidence(
            inputs.host_evidence_root,
            inputs.candidate_sha,
            verifier._inventory(inputs.artifacts)[0],
            inputs.repo_root,
            {},
        )
    checked.assert_not_called()


@pytest.mark.parametrize("index", range(7))
def test_claimed_host_evidence_must_match_every_authenticated_producer_field(
    tmp_path: Path, index: int
) -> None:
    namespace, _ = _fixture(tmp_path)
    inputs = verifier._resolve_inputs(namespace)
    record_path = Path(namespace.host_evidence_root) / "evidence.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    producer = (
        "zeke13dev/z-harness", ".github/workflows/release-evidence.yml", "12345",
        "produce", "release-evidence", "workflow_dispatch", inputs.candidate_sha,
    )
    record["producer"] = dict(
        zip(("repository", "workflow", "run_id", "job", "environment", "event", "head_sha"), producer)
    )
    record_path.write_text(json.dumps(record), encoding="utf-8")
    expected = list(producer)
    expected[index] = "mismatch"
    keys = (
        "Z_HARNESS_EVIDENCE_REPOSITORY", "Z_HARNESS_EVIDENCE_WORKFLOW",
        "Z_HARNESS_EVIDENCE_RUN_ID", "Z_HARNESS_EVIDENCE_JOB",
        "Z_HARNESS_EVIDENCE_ENVIRONMENT", "Z_HARNESS_EVIDENCE_EVENT",
        "Z_HARNESS_EVIDENCE_HEAD_SHA",
    )
    with (
        patch.object(verifier, "_checked") as checked,
        pytest.raises(verifier.VerificationError, match="differs from authenticated run"),
    ):
        verifier._verify_claimed_host_evidence(
            inputs.host_evidence_root, inputs.candidate_sha,
            verifier._inventory(inputs.artifacts)[0], inputs.repo_root,
            dict(zip(keys, expected)),
        )
    checked.assert_not_called()


def _assert_no_evidence_or_temporary(evidence: Path) -> None:
    assert not evidence.exists()
    assert list(evidence.parent.glob(f".{evidence.name}.*.tmp")) == []


@pytest.mark.parametrize("failure", ["fdopen", "file-fsync", "reservation", "replace", "dir-open", "dir-fsync"])
def test_atomic_evidence_failures_leave_no_promoted_or_temporary_file(
    tmp_path: Path, failure: str
) -> None:
    evidence = tmp_path / "evidence.json"
    payload = {"schema_version": 1, "status": "passed"}
    real_open = verifier.os.open
    real_fsync = verifier.os.fsync
    open_calls = 0
    fsync_calls = 0

    def injected_open(path, flags, mode=0o777):
        nonlocal open_calls
        open_calls += 1
        if failure == "reservation" and open_calls == 1:
            raise OSError("injected reservation open failure")
        if failure == "dir-open" and open_calls == 2:
            raise OSError("injected directory open failure")
        return real_open(path, flags, mode)

    def injected_fsync(descriptor):
        nonlocal fsync_calls
        fsync_calls += 1
        if failure == "file-fsync" and fsync_calls == 1:
            raise OSError("injected file fsync failure")
        if failure == "dir-fsync" and fsync_calls == 2:
            raise OSError("injected directory fsync failure")
        return real_fsync(descriptor)

    fdopen_effect = OSError("injected fdopen failure") if failure == "fdopen" else None
    replace_effect = OSError("injected replace failure") if failure == "replace" else None
    with (
        patch.object(verifier.os, "open", side_effect=injected_open),
        patch.object(verifier.os, "fsync", side_effect=injected_fsync),
        patch.object(verifier.os, "replace", side_effect=replace_effect, wraps=verifier.os.replace),
        patch.object(verifier.os, "fdopen", side_effect=fdopen_effect, wraps=verifier.os.fdopen),
        pytest.raises(OSError, match="injected"),
    ):
        verifier._write_evidence(evidence, payload)
    _assert_no_evidence_or_temporary(evidence)


def test_exclusive_preexisting_evidence_is_preserved(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text("foreign\n", encoding="utf-8")
    with pytest.raises(verifier.VerificationError, match="appeared"):
        verifier._write_evidence(evidence, {"status": "passed"})
    assert evidence.read_text(encoding="utf-8") == "foreign\n"
    assert list(tmp_path.glob(".evidence.json.*.tmp")) == []


def test_root_symlink_and_missing_input_are_rejected(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path)
    link = tmp_path / "candidate-link"
    link.symlink_to(namespace.candidate_root, target_is_directory=True)
    namespace.candidate_root = str(link)
    with pytest.raises(verifier.VerificationError, match="symlink"):
        verifier.verify(namespace, runner=FakeRunner())

    namespace, _ = _fixture(tmp_path / "missing-case")
    namespace.artifacts = str(tmp_path / "does-not-exist")
    with pytest.raises(FileNotFoundError):
        verifier.verify(namespace, runner=FakeRunner())


def test_dangling_evidence_symlink_is_rejected(tmp_path: Path) -> None:
    namespace, evidence = _fixture(tmp_path)
    evidence.symlink_to(tmp_path / "elsewhere.json")
    with pytest.raises(verifier.VerificationError, match="evidence destination must not be a symlink"):
        verifier.verify(namespace, runner=FakeRunner())


def test_cli_requires_every_explicit_input() -> None:
    with pytest.raises(SystemExit):
        verifier._parser().parse_args([])


def _promotion_fixture(tmp_path: Path, *, promoted_path: str = "README.md"):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "test@example.invalid")
    _git(origin, "config", "user.name", "Promotion Test")
    target = origin / promoted_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("source\n", encoding="utf-8")
    _git(origin, "add", promoted_path)
    _git(origin, "commit", "-qm", "source")
    source_sha = _git(origin, "rev-parse", "HEAD")
    _git(origin, "checkout", "-qb", "prod")
    target.write_text("prod\n", encoding="utf-8")
    _git(origin, "commit", "-qam", "prod")
    prod_sha = _git(origin, "rev-parse", "HEAD")
    _git(origin, "checkout", "-q", "main")

    main_root = tmp_path / "main"
    prod_root = tmp_path / "prod"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(origin), str(main_root)], check=True
    )
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(origin), str(prod_root)], check=True
    )
    _git(main_root, "checkout", "-q", "main")
    _git(prod_root, "checkout", "-q", "prod")
    _git(prod_root, "branch", "watch", source_sha)

    base_namespace, _ = _fixture(tmp_path / "candidate-inputs")
    candidate_root = Path(base_namespace.candidate_root)
    artifacts = Path(base_namespace.artifacts)
    host_evidence_root = Path(base_namespace.host_evidence_root)
    evidence_path = tmp_path / "candidate-evidence.json"
    refs_fingerprint = verifier._promotion_refs_fingerprint(prod_root.resolve())
    fingerprints = {
        "candidate_fingerprint": verifier._inventory(candidate_root)[0],
        "artifacts_fingerprint": verifier._inventory(artifacts)[0],
        "host_evidence_fingerprint": verifier._inventory(host_evidence_root)[0],
    }
    combined = verifier._sha256_bytes(
        verifier._canonical_json(
            {
                "head": prod_sha,
                "refs": refs_fingerprint,
                "candidate": fingerprints["candidate_fingerprint"],
                "artifacts": fingerprints["artifacts_fingerprint"],
                "host_evidence": fingerprints["host_evidence_fingerprint"],
            }
        )
    )
    fingerprints["combined_fingerprint"] = combined
    evidence = {
        "schema_version": 1,
        "status": "passed",
        "candidate_version": "0.9.0-beta.2",
        "candidate_sha": prod_sha,
        "inputs": {
            "repo_root": str(prod_root.resolve()),
            "candidate_root": str(candidate_root.resolve()),
            "artifacts": str(artifacts.resolve()),
            "host_evidence_root": str(host_evidence_root.resolve()),
            **fingerprints,
        },
        "git": {
            "initial_head": prod_sha,
            "final_head": prod_sha,
            "initial_status": "",
            "final_status": "",
            "initial_refs_fingerprint": refs_fingerprint,
            "final_refs_fingerprint": refs_fingerprint,
        },
        "lanes": [
            {
                "id": lane_id,
                "phase": "fast" if lane_id in verifier.FAST_LANE_IDS else "slow",
                "status": "passed",
                "exit_status": 0,
                "input_fingerprint": combined,
            }
            for lane_id in (*verifier.FAST_LANE_IDS, *verifier.SLOW_LANE_IDS)
        ],
    }
    evidence["evidence_fingerprint"] = verifier._sha256_bytes(
        verifier._canonical_json(evidence)
    )
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    authorization = tmp_path / "promotion-authorization.json"
    namespace = argparse.Namespace(
        mode="promotion-preflight",
        source_sha=source_sha,
        prod_sha=prod_sha,
        repo_root=str(main_root),
        prod_root=str(prod_root),
        candidate_root=str(candidate_root),
        artifacts=str(artifacts),
        host_evidence_root=str(host_evidence_root),
        evidence=str(evidence_path),
        authorization_out=str(authorization),
        authorization=None,
    )
    return namespace, authorization, evidence_path


def test_promotion_preflight_and_freshness_bind_exact_refs_diff_and_all_evidence(
    tmp_path: Path,
) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    before = {
        "main": _git(Path(namespace.repo_root), "status", "--porcelain=v1"),
        "prod": _git(Path(namespace.prod_root), "status", "--porcelain=v1"),
        "main_head": _git(Path(namespace.repo_root), "rev-parse", "HEAD"),
        "prod_head": _git(Path(namespace.prod_root), "rev-parse", "HEAD"),
    }
    payload = verifier.promotion_preflight(namespace)
    assert payload["source_sha"] == namespace.source_sha
    assert payload["prod_sha"] == namespace.prod_sha
    assert payload["authoritative_refs"] == {
        "main": "refs/remotes/origin/main",
        "prod": "refs/remotes/origin/prod",
    }
    assert payload["candidate_version"] == "0.9.0-beta.2"
    assert payload["expected_tag"] == "v0.9.0-beta.2"
    assert payload["expected_tag_absent"] is True
    assert payload["verified_lane_ids"] == [
        *verifier.FAST_LANE_IDS,
        *verifier.SLOW_LANE_IDS,
    ]
    assert payload["diff"] == [
        {"status": "M", "path": "README.md", "owner": "public_documents"}
    ]
    saved = json.loads(authorization.read_text(encoding="utf-8"))
    assert saved == payload
    namespace.mode = "publication-freshness"
    namespace.authorization = str(authorization)
    namespace.authorization_out = None
    assert verifier.publication_freshness(namespace) == payload
    assert before == {
        "main": _git(Path(namespace.repo_root), "status", "--porcelain=v1"),
        "prod": _git(Path(namespace.prod_root), "status", "--porcelain=v1"),
        "main_head": _git(Path(namespace.repo_root), "rev-parse", "HEAD"),
        "prod_head": _git(Path(namespace.prod_root), "rev-parse", "HEAD"),
    }


def test_promotion_requires_source_symbolically_checked_out_on_main(tmp_path: Path) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    main_root = Path(namespace.repo_root)
    _git(main_root, "checkout", "--detach", namespace.source_sha)
    with pytest.raises(verifier.VerificationError, match="symbolic-ref|checked out on"):
        verifier.promotion_preflight(namespace)
    assert not authorization.exists()


def test_promotion_rejects_noncanonical_candidate_evidence_version(tmp_path: Path) -> None:
    namespace, authorization, evidence_path = _promotion_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["candidate_version"] = "v0.9.0-beta.2"
    evidence.pop("evidence_fingerprint")
    evidence["evidence_fingerprint"] = verifier._sha256_bytes(
        verifier._canonical_json(evidence)
    )
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(verifier.VerificationError, match="not canonical"):
        verifier.promotion_preflight(namespace)
    assert not authorization.exists()


def test_promotion_rejects_preexisting_exact_derived_release_tag(tmp_path: Path) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    _git(Path(namespace.prod_root), "tag", "v0.9.0-beta.2", namespace.prod_sha)
    with pytest.raises(verifier.VerificationError, match="release tag already exists"):
        verifier.promotion_preflight(namespace)
    assert not authorization.exists()


@pytest.mark.parametrize(
    "promoted_path, message",
    [
        ("skills/z-research/SKILL.md", "excluded experiment"),
        ("unreviewed.txt", "outside C1's positive inventory"),
    ],
)
def test_promotion_default_denies_experiments_and_unowned_paths(
    tmp_path: Path, promoted_path: str, message: str
) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path, promoted_path=promoted_path)
    with pytest.raises(verifier.VerificationError, match=message):
        verifier.promotion_preflight(namespace)
    assert not authorization.exists()


@pytest.mark.parametrize("drift", ["dirty-main", "wrong-main-ref", "wrong-prod-ref"])
def test_promotion_rejects_dirty_or_unexpected_refs(tmp_path: Path, drift: str) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    if drift == "dirty-main":
        (Path(namespace.repo_root) / "dirty.txt").write_text("dirty", encoding="utf-8")
    elif drift == "wrong-main-ref":
        namespace.source_sha = namespace.prod_sha
    else:
        namespace.prod_sha = namespace.source_sha
    with pytest.raises(verifier.VerificationError, match="clean|HEAD|refs/heads"):
        verifier.promotion_preflight(namespace)
    assert not authorization.exists()


@pytest.mark.parametrize("fabricated", ["main", "prod"])
def test_promotion_rejects_fabricated_local_refs_against_authoritative_remote(
    tmp_path: Path, fabricated: str
) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    if fabricated == "main":
        namespace.source_sha = namespace.prod_sha
        _git(Path(namespace.repo_root), "reset", "--hard", namespace.prod_sha)
        expected = "refs/remotes/origin/main"
    else:
        namespace.prod_sha = namespace.source_sha
        _git(Path(namespace.prod_root), "reset", "--hard", namespace.source_sha)
        expected = "refs/remotes/origin/prod"

    with pytest.raises(verifier.VerificationError, match=expected):
        verifier.promotion_preflight(namespace)
    assert not authorization.exists()


def test_promotion_rejects_source_equal_prod_empty_diff_bypass(tmp_path: Path) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    namespace.source_sha = namespace.prod_sha
    _git(Path(namespace.repo_root), "reset", "--hard", namespace.prod_sha)

    assert _git(
        Path(namespace.repo_root), "diff", "--name-only", namespace.source_sha, namespace.prod_sha
    ) == ""
    with pytest.raises(verifier.VerificationError, match="refs/remotes/origin/main"):
        verifier.promotion_preflight(namespace)
    assert not authorization.exists()


def test_promotion_partial_evidence_never_creates_authorization(tmp_path: Path) -> None:
    namespace, authorization, evidence_path = _promotion_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["lanes"].pop()
    evidence["evidence_fingerprint"] = verifier._sha256_bytes(
        verifier._canonical_json({k: v for k, v in evidence.items() if k != "evidence_fingerprint"})
    )
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(verifier.VerificationError, match=r"complete 5 fast \+ 7 slow"):
        verifier.promotion_preflight(namespace)
    assert not authorization.exists()


def test_promotion_rejects_evidence_ref_fingerprint_mismatching_current_prod_refs(
    tmp_path: Path,
) -> None:
    namespace, authorization, evidence_path = _promotion_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    stale_refs = "f" * 64
    evidence["git"]["initial_refs_fingerprint"] = stale_refs
    evidence["git"]["final_refs_fingerprint"] = stale_refs
    combined = verifier._sha256_bytes(
        verifier._canonical_json(
            {
                "head": namespace.prod_sha,
                "refs": stale_refs,
                "candidate": evidence["inputs"]["candidate_fingerprint"],
                "artifacts": evidence["inputs"]["artifacts_fingerprint"],
                "host_evidence": evidence["inputs"]["host_evidence_fingerprint"],
            }
        )
    )
    evidence["inputs"]["combined_fingerprint"] = combined
    for lane in evidence["lanes"]:
        lane["input_fingerprint"] = combined
    evidence["evidence_fingerprint"] = verifier._sha256_bytes(
        verifier._canonical_json({k: v for k, v in evidence.items() if k != "evidence_fingerprint"})
    )
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(verifier.VerificationError, match="prod ref fingerprint is stale"):
        verifier.promotion_preflight(namespace)
    assert not authorization.exists()


@pytest.mark.parametrize("drift", ["artifact", "evidence", "authorization"])
def test_publication_freshness_rejects_every_stale_binding(tmp_path: Path, drift: str) -> None:
    namespace, authorization, evidence_path = _promotion_fixture(tmp_path)
    verifier.promotion_preflight(namespace)
    namespace.mode = "publication-freshness"
    namespace.authorization = str(authorization)
    namespace.authorization_out = None
    if drift == "artifact":
        (Path(namespace.artifacts) / "install.sh").write_text("drift", encoding="utf-8")
    elif drift == "evidence":
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["lanes"].pop()
        evidence["evidence_fingerprint"] = verifier._sha256_bytes(
            verifier._canonical_json({k: v for k, v in evidence.items() if k != "evidence_fingerprint"})
        )
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    else:
        record = json.loads(authorization.read_text(encoding="utf-8"))
        record["prod_sha"] = "f" * 40
        authorization.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(verifier.VerificationError, match="stale|fingerprint|complete"):
        verifier.publication_freshness(namespace)


def test_publication_freshness_rejects_tag_created_after_preflight(tmp_path: Path) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    verifier.promotion_preflight(namespace)
    namespace.authorization = str(authorization)
    namespace.authorization_out = None
    _git(Path(namespace.prod_root), "tag", "v0.9.0-beta.2", namespace.prod_sha)
    with pytest.raises(verifier.VerificationError, match="release tag already exists"):
        verifier.publication_freshness(namespace)


@pytest.mark.parametrize("branch", ["main", "prod"])
def test_publication_freshness_rejects_authoritative_remote_ref_movement(
    tmp_path: Path, branch: str
) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    verifier.promotion_preflight(namespace)
    namespace.authorization = str(authorization)
    namespace.authorization_out = None

    checkout = Path(namespace.repo_root if branch == "main" else namespace.prod_root)
    origin = Path(_git(checkout, "remote", "get-url", "origin"))
    _git(origin, "checkout", "-q", branch)
    moved = origin / "README.md"
    moved.write_text(f"{branch} moved after authorization\n", encoding="utf-8")
    _git(origin, "commit", "-qam", f"move {branch}")
    if branch != "main":
        _git(origin, "checkout", "-q", "main")
    _git(
        checkout,
        "fetch",
        "--force",
        "--no-tags",
        "origin",
        f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
    )

    with pytest.raises(
        verifier.VerificationError, match=f"refs/remotes/origin/{branch}"
    ):
        verifier.publication_freshness(namespace)


def test_publication_assets_emits_only_exact_metadata_validated_names(tmp_path: Path) -> None:
    namespace, _ = _fixture(tmp_path / "candidate")
    github_output = tmp_path / "github-output"
    github_output.write_text("", encoding="utf-8")
    result = verifier.publication_assets(
        argparse.Namespace(
            candidate_version="0.9.0-beta.2",
            artifacts=namespace.artifacts,
            github_output=str(github_output),
        )
    )
    assert result["tag"] == "v0.9.0-beta.2"
    assert Path(result["wheel"]).name.endswith(".whl")
    assert Path(result["tarball"]).name == "z-harness-0.9.0-beta.2.tar.gz"
    output = github_output.read_text(encoding="utf-8")
    assert "*" not in output and "?" not in output and "[" not in output


@pytest.mark.parametrize("ref_drift", ["add", "move", "delete"])
def test_publication_freshness_rejects_branch_ref_drift(
    tmp_path: Path, ref_drift: str
) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    verifier.promotion_preflight(namespace)
    namespace.authorization = str(authorization)
    namespace.authorization_out = None
    prod_root = Path(namespace.prod_root)
    if ref_drift == "add":
        _git(prod_root, "branch", "added-after-preflight", namespace.source_sha)
    elif ref_drift == "move":
        _git(prod_root, "branch", "-f", "watch", namespace.prod_sha)
    else:
        _git(prod_root, "branch", "-D", "watch")
    with pytest.raises(verifier.VerificationError, match="prod ref fingerprint is stale"):
        verifier.publication_freshness(namespace)


def test_promotion_git_allowlist_rejects_mutation_commands(tmp_path: Path) -> None:
    namespace, _, _ = _promotion_fixture(tmp_path)
    for command in (("checkout", "prod"), ("tag", "v1"), ("push", "origin", "prod")):
        with pytest.raises(verifier.VerificationError, match="read-only allowlist"):
            verifier._promotion_git(Path(namespace.repo_root), *command)


def test_cli_modes_require_only_their_explicit_inputs(tmp_path: Path) -> None:
    namespace, authorization, _ = _promotion_fixture(tmp_path)
    args = [
        "--mode", "promotion-preflight",
        "--source-sha", namespace.source_sha,
        "--prod-sha", namespace.prod_sha,
        "--repo-root", namespace.repo_root,
        "--prod-root", namespace.prod_root,
        "--candidate-root", namespace.candidate_root,
        "--artifacts", namespace.artifacts,
        "--host-evidence-root", namespace.host_evidence_root,
        "--evidence", namespace.evidence,
        "--authorization-out", str(authorization),
    ]
    assert verifier._parser().parse_args(args).mode == "promotion-preflight"
    with pytest.raises(SystemExit):
        verifier._parser().parse_args(args[:-2])
