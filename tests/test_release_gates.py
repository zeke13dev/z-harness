from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

import pytest

from tests.test_release import _write_release_artifact_fixture
from z_harness_cli import mcp_prod_tool_list_smoke as mcp_smoke

REPO_ROOT = Path(__file__).parent.parent.resolve()
OMP_SMOKE_PATH = REPO_ROOT / "scripts" / "omp-prod-export-smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("omp_prod_export_smoke", OMP_SMOKE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_minimal_valid_export(root: Path) -> Path:
    from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity

    package_root = root / ".omp" / "z-harness"
    package_root.mkdir(parents=True)
    (root / ".omp" / "config.yml").write_text(
        "skills:\n  enableAgentsProject: false\n",
        encoding="utf-8",
    )
    (package_root / "manifest.yml").write_text(
        "name: z-harness\nhost: omp\n"
        f"fidelity: {omp_export_fidelity()}\n",
        encoding="utf-8",
    )
    return package_root


def test_omp_smoke_accepts_minimal_valid_prod_export(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    _write_minimal_valid_export(tmp_path)

    smoke.validate_omp_export(tmp_path)


def test_omp_smoke_rejects_missing_manifest(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    package_root = _write_minimal_valid_export(tmp_path)
    (package_root / "manifest.yml").unlink()

    with pytest.raises(AssertionError, match="missing OMP manifest"):
        smoke.validate_omp_export(tmp_path)


def test_omp_smoke_rejects_config_suppression_mutation(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    _write_minimal_valid_export(tmp_path)
    (tmp_path / ".omp" / "config.yml").write_text(
        "skills:\n  enableAgentsProject: true\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="enableAgentsProject"):
        smoke.validate_omp_export(tmp_path)


def test_omp_smoke_rejects_hidden_skill_axiom_and_agent_resources(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    package_root = _write_minimal_valid_export(tmp_path)
    hidden_skill = package_root / "skills" / "z-explore" / "SKILL.md"
    hidden_skill.parent.mkdir(parents=True)
    hidden_skill.write_text("hidden\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="prod-hidden OMP skill resource leaked"):
        smoke.validate_omp_export(tmp_path)

    hidden_skill.unlink()
    hidden_skill.parent.rmdir()
    hidden_axiom_prompt = package_root / "prompts" / "z-axiom-scan.md"
    hidden_axiom_prompt.parent.mkdir(parents=True, exist_ok=True)
    hidden_axiom_prompt.write_text("hidden\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="prod-hidden OMP axiom resource leaked"):
        smoke.validate_omp_export(tmp_path)

    hidden_axiom_prompt.unlink()
    hidden_agent = package_root / "agents" / "axiom-extractor.md"
    hidden_agent.parent.mkdir(parents=True)
    hidden_agent.write_text("hidden\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="prod-hidden OMP agent leaked"):
        smoke.validate_omp_export(tmp_path)


def test_omp_smoke_rejects_parity_fidelity_mismatch(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    package_root = _write_minimal_valid_export(tmp_path)
    (package_root / "manifest.yml").write_text(
        "name: z-harness\nhost: omp\nfidelity: partial\n",
        encoding="utf-8",
    )

    from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity

    if omp_export_fidelity() == "partial":
        pytest.skip("gate currently resolves to partial; mismatch fixture would be valid")
    with pytest.raises(AssertionError, match="parity gate"):
        smoke.validate_omp_export(tmp_path)


def test_mcp_prod_smoke_rejects_repo_root_import_source(tmp_path: Path) -> None:
    smoke = mcp_smoke
    repo_root = tmp_path / "checkout"
    repo_root.mkdir()
    module_file = repo_root / "z_harness_cli" / "__init__.py"
    module_file.parent.mkdir()
    module_file.write_text("", encoding="utf-8")
    venv_prefix = tmp_path / "venv"
    venv_prefix.mkdir()

    with pytest.raises(AssertionError, match="checkout instead of installed wheel"):
        smoke.assert_installed_import_source(module_file, repo_root, venv_prefix)


def test_mcp_prod_smoke_accepts_venv_site_package_import(tmp_path: Path) -> None:
    smoke = mcp_smoke
    repo_root = tmp_path / "checkout"
    repo_root.mkdir()
    venv_prefix = tmp_path / "venv"
    module_file = (
        venv_prefix / "lib" / "python3.11" / "site-packages" / "z_harness_cli" / "__init__.py"
    )
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")

    smoke.assert_installed_import_source(module_file, repo_root, venv_prefix)


def test_mcp_prod_smoke_rejects_repo_root_cwd(tmp_path: Path) -> None:
    smoke = mcp_smoke
    repo_root = tmp_path / "checkout"
    nested_cwd = repo_root / "subdir"
    nested_cwd.mkdir(parents=True)

    with pytest.raises(AssertionError, match="must run outside the checkout"):
        smoke.assert_non_repo_cwd(repo_root, nested_cwd)


def _workflow(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_release_and_conformance_use_one_exact_candidate_authority_on_both_platforms() -> None:
    for name in ("release.yml", "conformance.yml"):
        workflow = _workflow(name)
        assert "os: ubuntu-24.04" in workflow
        assert "os: macos-14" in workflow
        assert "architecture: x64" in workflow
        assert "architecture: arm64" in workflow
        assert "continue-on-error" not in workflow
        assert "uv run --frozen --no-sync make release-verify" in workflow
        assert "release-candidate-verify.py" not in workflow.split("make release-verify", 1)[0]
        for value in (
            "Z_HARNESS_RELEASE_CANDIDATE",
            "Z_HARNESS_RELEASE_SHA",
            "Z_HARNESS_RELEASE_REPO_ROOT",
            "Z_HARNESS_RELEASE_CANDIDATE_ROOT",
            "Z_HARNESS_RELEASE_ARTIFACTS",
            "Z_HARNESS_RELEASE_HOST_EVIDENCE",
            "Z_HARNESS_RELEASE_EVIDENCE_OUT",
        ):
            assert value in workflow
        assert "--allow-missing" not in workflow
        assert "advisory" not in workflow.lower()


def test_ci_consumes_one_explicit_immutable_artifact_and_live_evidence_run() -> None:
    for name in ("release.yml", "conformance.yml"):
        workflow = _workflow(name)
        assert "evidence_run_id:" in workflow
        assert "run-id: ${{ inputs.evidence_run_id }}" in workflow
        assert "name: release-candidate-root" in workflow
        assert "name: release-artifacts" in workflow
        assert "name: release-host-evidence" in workflow
        assert "github-token: ${{ github.token }}" in workflow
        assert "fixture" not in workflow.lower()
        assert "assemble-release.py" not in workflow


def test_release_publication_depends_on_both_os_and_rechecks_freshness_immediately() -> None:
    workflow = _workflow("release.yml")
    publish = workflow.index("publish:")
    refresh = workflow.index("Refresh authoritative refs immediately before publication", publish)
    freshness = workflow.index("Immediate publication freshness check", publish)
    publication = workflow.index("Create GitHub release from the exact allowlist", publish)
    assert "needs: verify" in workflow[publish:]
    assert refresh < freshness < publication
    between = workflow[refresh:publication]
    assert "--mode publication-freshness" in between
    assert "--authorization" in between
    assert "git fetch --force --no-tags origin" in between
    assert "+refs/heads/main:refs/remotes/origin/main" in between
    assert "+refs/heads/prod:refs/remotes/origin/prod" in between
    assert "uses:" not in between
    assert "push:" not in workflow
    assert "tags:" not in workflow
    assert "target_commitish: ${{ inputs.prod_sha }}" in workflow
    assets = workflow[publication:]
    files = assets.split("files: |", 1)[1]
    file_lines = [line.strip() for line in files.splitlines() if line.strip()]
    assert len(file_lines) == 7
    assert all(not any(character in line for character in "*?[") for line in file_lines)
    assert "${{ steps.assets.outputs.wheel }}" in file_lines
    assert "${{ steps.assets.outputs.tarball }}" in file_lines
    assert "fail_on_unmatched_files: true" in assets
    assert "tag_name:" not in workflow.split("jobs:", 1)[0]
    assert "tag_name: ${{ steps.assets.outputs.tag }}" in assets


def test_release_workflows_pin_every_action_and_install_only_the_lock() -> None:
    for name in ("release.yml", "conformance.yml"):
        workflow = _workflow(name)
        refs = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow, flags=re.MULTILINE)
        assert refs and all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in refs)
        assert 'version: "0.11.3"' in workflow
        checksums = re.findall(r"uv_checksum: ([0-9a-f]{64})", workflow)
        assert checksums == [
            "c0f3236f146e55472663cfbcc9be3042a9f1092275bbe3fe2a56a6cbfd3da5ce",
            "2bc3d0c7bf2bd08325b1e170abac6f7e5b3346e1d4eab3370d17cefec934996f",
        ]
        assert len(set(checksums)) == 2
        assert "checksum: ${{ matrix.uv_checksum }}" in workflow
        assert "uv sync --frozen --all-extras --all-groups --no-install-project" in workflow
        assert "pip install" not in workflow
        assert "uv pip" not in workflow


def test_release_run_blocks_do_not_interpolate_dispatch_inputs_as_shell_code() -> None:
    workflow = _workflow("release.yml")
    run_blocks = re.findall(r"\n\s+run: \|\n((?:\s{10,}.*\n)+)", workflow)
    assert run_blocks
    assert all("${{ inputs." not in block for block in run_blocks)
    assert 'git branch --force prod "$PROD_SHA"' in workflow


def test_release_binds_authoritative_remote_refs_before_privileged_verification() -> None:
    workflow = _workflow("release.yml")
    publish = workflow.index("publish:")
    bind = workflow.index("Fetch and bind authoritative promotion refs", publish)
    verification = workflow.index("Recreate passing evidence", publish)
    preflight = workflow.index("Curated main-to-prod promotion preflight", publish)
    assert bind < verification < preflight
    binding_end = workflow.index("- name: Set up locked Python", bind)
    binding = workflow[bind:binding_end]
    assert "git fetch --force --no-tags origin" in binding
    assert "refs/remotes/origin/main" in binding
    assert "refs/remotes/origin/prod" in binding
    assert '[[ "$SOURCE_SHA" == "$SOURCE_TIP" ]]' in binding
    assert '[[ "$PROD_SHA" == "$PROD_TIP" ]]' in binding
    assert "${{ inputs." not in binding.split("run: |", 1)[1]
    assert '--source-sha "$SOURCE_SHA"' in workflow
    assert '--prod-sha "$PROD_SHA"' in workflow
    assert '--candidate-version "$CANDIDATE_VERSION"' in workflow
    assert "checkout --quiet -B main refs/remotes/origin/main" in workflow


def _git(command: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *command],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _release_remote(tmp_path: Path) -> tuple[Path, Path, str]:
    """Create a real remote with one reviewed prod commit and release tag."""

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    _git(["init", "--bare", str(remote)], tmp_path)
    _git(["init", str(seed)], tmp_path)
    _git(["config", "user.name", "Release Test"], seed)
    _git(["config", "user.email", "release@example.invalid"], seed)
    (seed / "release.txt").write_text("reviewed\n", encoding="utf-8")
    _git(["add", "release.txt"], seed)
    _git(["commit", "-m", "reviewed prod"], seed)
    _git(["branch", "-M", "prod"], seed)
    commit = _git(["rev-parse", "HEAD"], seed)
    _git(["tag", "v2.4.1"], seed)
    _git(["tag", "vv2.4.1"], seed)
    _git(["remote", "add", "origin", str(remote)], seed)
    _git(["push", "origin", "prod", "v2.4.1", "vv2.4.1"], seed)
    _git(["clone", "--no-checkout", str(remote), str(checkout)], tmp_path)
    _git(["checkout", "--detach", commit], checkout)
    return seed, checkout, commit


@pytest.mark.parametrize(
    ("case", "tag", "sha", "expected_success"),
    (
        ("positive", "v2.4.1", "reviewed", True),
        ("missing-tag", "v2.4.2", "reviewed", False),
        ("wrong-tag", "vv2.4.1", "reviewed", False),
        ("wrong-sha", "v2.4.1", "b" * 40, False),
        ("stale-prod", "v2.4.1", "reviewed", False),
    ),
)
def test_real_git_provenance_gate_precedes_side_effect_sentinel(
    tmp_path: Path,
    case: str,
    tag: str,
    sha: str,
    expected_success: bool,
) -> None:
    seed, checkout, reviewed_commit = _release_remote(tmp_path)
    if case == "stale-prod":
        (seed / "release.txt").write_text("unreviewed prod advance\n", encoding="utf-8")
        _git(["add", "release.txt"], seed)
        _git(["commit", "-m", "advance prod"], seed)
        _git(["push", "origin", "prod"], seed)
    workflow_sha = reviewed_commit if sha == "reviewed" else sha
    sentinel = tmp_path / "publication-started"
    script = REPO_ROOT / "scripts" / "verify-release-provenance.sh"
    environment = os.environ.copy()
    environment.update(
        {
            "GITHUB_REF_NAME": tag,
            "GITHUB_SHA": workflow_sha,
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'bash "$1" "$2" && : >"$3"',
            "provenance-test",
            str(script),
            os.sys.executable,
            str(sentinel),
        ],
        cwd=checkout,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode == 0) is expected_success, result.stderr
    assert sentinel.exists() is expected_success


def test_make_release_verify_is_a_thin_explicit_candidate_delegate() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "test: version-check test-suite" in makefile
    release_recipe = makefile.split("release-verify:", 1)[1].split("\nrelease-dry-run:", 1)[0]
    assert release_recipe.count("scripts/release-candidate-verify.py") == 1
    for option, variable in (
        ("--candidate-version", "Z_HARNESS_RELEASE_CANDIDATE"),
        ("--candidate-sha", "Z_HARNESS_RELEASE_SHA"),
        ("--repo-root", "Z_HARNESS_RELEASE_REPO_ROOT"),
        ("--candidate-root", "Z_HARNESS_RELEASE_CANDIDATE_ROOT"),
        ("--artifacts", "Z_HARNESS_RELEASE_ARTIFACTS"),
        ("--host-evidence-root", "Z_HARNESS_RELEASE_HOST_EVIDENCE"),
        ("--evidence-out", "Z_HARNESS_RELEASE_EVIDENCE_OUT"),
    ):
        assert option in release_recipe
        assert variable in release_recipe
        assert f"{variable} is required" in release_recipe
    assert "pytest" not in release_recipe
    assert "test-suite" not in release_recipe
    assert "test-sh" not in release_recipe
    assert "release-dry-run" not in release_recipe


def test_release_candidate_stamping_is_explicit_and_git_version_is_telemetry_only() -> None:
    sync = REPO_ROOT / "scripts" / "sync-version.sh"
    for candidate, expected in (("v2.4.1", "2.4.1"), ("2.4.1b10", "2.4.1-beta.10")):
        result = subprocess.run(
            ["/bin/bash", str(sync), "--print", "--candidate-version", candidate],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected

    missing = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "scripts" / "release-dry-run.sh")],
        cwd=REPO_ROOT,
        env={key: value for key, value in os.environ.items() if not key.startswith("Z_HARNESS_RELEASE_")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing.returncode == 2
    assert "usage:" in missing.stderr

    tag_only_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("Z_HARNESS_RELEASE_")
    }
    tag_only_env["Z_HARNESS_RELEASE_TAG"] = "v2.4.1"
    tag_only = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "scripts" / "release-dry-run.sh")],
        cwd=REPO_ROOT,
        env=tag_only_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tag_only.returncode == 2
    assert "usage:" in tag_only.stderr
    telemetry = (REPO_ROOT / "scripts" / "version.sh").read_text(encoding="utf-8")
    assert "observational only" in telemetry
    assert "explicit candidate" in telemetry


def test_make_release_verify_dry_run_passes_every_explicit_input_unchanged() -> None:
    values = {
        "Z_HARNESS_RELEASE_CANDIDATE": "2.4.1",
        "Z_HARNESS_RELEASE_SHA": "a" * 40,
        "Z_HARNESS_RELEASE_REPO_ROOT": "/tmp/exact-repo",
        "Z_HARNESS_RELEASE_CANDIDATE_ROOT": "/tmp/exact-candidate",
        "Z_HARNESS_RELEASE_ARTIFACTS": "/tmp/exact-artifacts",
        "Z_HARNESS_RELEASE_HOST_EVIDENCE": "/tmp/exact-host-evidence",
        "Z_HARNESS_RELEASE_EVIDENCE_OUT": "/tmp/exact-evidence.json",
    }
    result = subprocess.run(
        ["make", "--dry-run", "release-verify"],
        cwd=REPO_ROOT,
        env={**os.environ, **values},
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.count("scripts/release-candidate-verify.py") == 1
    for value in values.values():
        assert value in result.stdout
    assert "pytest" not in result.stdout
    assert "release-dry-run" not in result.stdout


def test_make_release_verify_rejects_missing_explicit_identity_before_verifier() -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("Z_HARNESS_RELEASE_")}
    result = subprocess.run(
        ["make", "release-verify"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Z_HARNESS_RELEASE_CANDIDATE is required" in result.stderr
    assert "release-candidate-verify.py" not in result.stdout


def test_bundle_plugin_packages_only_the_canonical_candidate_stage(tmp_path: Path) -> None:
    version = "0.9.0-beta.2"
    commit = "0123456789abcdef0123456789abcdef01234567"
    tarball = REPO_ROOT / "dist" / f"z-harness-{version}.tar.gz"
    artifacts = []
    for index, timestamp in enumerate((1_000_000_000, 1_700_000_000)):
        stage = tmp_path / f"stage-{index}"
        (stage / ".codex-plugin").mkdir(parents=True)
        (stage / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "z-harness", "version": version, "candidate_commit": commit}),
            encoding="utf-8",
        )
        (stage / "stage-only.txt").write_text("canonical\n", encoding="utf-8")
        for path in (stage, *stage.rglob("*")):
            os.utime(path, (timestamp, timestamp))
        result = subprocess.run(
            [
                "/bin/bash",
                str(REPO_ROOT / "scripts" / "bundle-plugin.sh"),
                "--stage",
                str(stage),
                "--candidate-version",
                version,
                "--candidate-commit",
                commit,
            ],
            cwd=REPO_ROOT,
            env={**os.environ, "Z_HARNESS_RELEASE_SURFACE": "dev"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        artifacts.append(tarball.read_bytes())

    with tarfile.open(tarball) as archive:
        archive_members = archive.getmembers()
    tarball.unlink()
    members = {member.name.removeprefix("./") for member in archive_members}
    assert artifacts[0] == artifacts[1]
    assert all(member.mtime == 0 and member.uid == 0 and member.gid == 0 for member in archive_members)
    assert "stage-only.txt" in members
    assert ".codex-plugin/plugin.json" in members
    assert ".git/config" not in members


def test_bundle_plugin_rejects_candidate_identity_mismatch(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    (stage / ".codex-plugin").mkdir(parents=True)
    (stage / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "z-harness", "version": "0.9.0", "candidate_commit": "a" * 40}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "/bin/bash",
            str(REPO_ROOT / "scripts" / "bundle-plugin.sh"),
            "--stage",
            str(stage),
            "--candidate-version",
            "0.9.1",
            "--candidate-commit",
            "b" * 40,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "candidate identity mismatch" in result.stderr


def test_bundle_plugin_prod_audits_stage_sources_with_only_generated_metadata_exempted() -> None:
    script = (REPO_ROOT / "scripts" / "bundle-plugin.sh").read_text(encoding="utf-8")

    assert "python3 -m z_harness_cli.release_surface audit-listing --surface prod" in script
    assert "^\\./\\.codex-plugin/plugin\\.json$" in script
    assert "Z_HARNESS_RELEASE_SURFACE=dev bash \"$SCRIPT_DIR/audit-tarball.sh\"" in script


def test_release_evidence_workflow_is_protected_owned_and_exact() -> None:
    producer = (REPO_ROOT / ".github/workflows/release-evidence.yml").read_text(encoding="utf-8")
    assert "runs-on: [self-hosted, linux, x64, z-harness-release-evidence]" in producer
    assert "environment: release-evidence" in producer
    assert "raw-record" not in producer and "RAW_RECORD" not in producer
    assert producer.count("actions/upload-artifact@") == 3
    for name in ("release-candidate-root", "release-artifacts", "release-host-evidence"):
        assert f"name: {name}" in producer
    assert "install-plugin.sh\" --target=claude" in producer
    assert "install-plugin.sh\" --target=codex" in producer
    assert "omp -p --no-session" in producer
    assert "--no-rules" not in producer
    assert producer.count('/z-fix release-evidence-dispatch-probe $CANDIDATE_SHA') == 3
    assert "Z_HARNESS_Z_FIX_DISPATCH_V1:" not in producer
    assert "--model openai/gpt-5.2" in producer
    assert "release-evidence clean-plugin proof" not in producer
    assert "installed-wheel command-specific probe" not in producer
    assert producer.index("bind authoritative prod before checkout") < producer.index("Checkout bound candidate")

    skill = (REPO_ROOT / "skills/z-fix/SKILL.md").read_text(encoding="utf-8")
    probe_index = skill.index("## Reserved release-evidence dispatch probe")
    assert probe_index < skill.index("**If the task above is empty**")
    assert "Z_HARNESS_Z_FIX_DISPATCH_V1:<sha>" in skill


@pytest.mark.parametrize("workflow", ["conformance.yml", "release.yml"])
def test_release_consumers_authenticate_run_before_download_and_export_context(workflow: str) -> None:
    source = (REPO_ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
    assert source.index("Authenticate release evidence producer") < source.index("actions/download-artifact@")
    for marker in (
        'run["repository"]["full_name"]', "run['workflow_id']", 'workflow_meta["path"]', 'run["event"]',
        'run["head_sha"]', 'run["conclusion"]', "release-evidence.yml",
            "execute protected C1 host evidence", 'produce.get("environment")',
        'job["run_id"]', 'job["head_sha"]', "selected protected job is not the exact pinned artifact producer",
        "Z_HARNESS_EVIDENCE_REPOSITORY", "Z_HARNESS_EVIDENCE_WORKFLOW",
        "Z_HARNESS_EVIDENCE_RUN_ID", "Z_HARNESS_EVIDENCE_JOB",
        "Z_HARNESS_EVIDENCE_ENVIRONMENT", "Z_HARNESS_EVIDENCE_EVENT",
        "Z_HARNESS_EVIDENCE_HEAD_SHA",
    ):
        assert marker in source
    assert "deployments?sha=" not in source
