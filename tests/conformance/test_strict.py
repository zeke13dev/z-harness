"""Strict C1 release-claim evidence and development-driver regressions.

The release verdict in this module is deliberately separate from the broader
development driver matrix.  Blocking claims are derived from
``runtime.release_surface.release_contract()`` and every claim must have one
candidate-bound ``z-fix`` proof.  Checked-in records are schema/regression
samples only; production validation rejects them unless fixture mode is
explicitly enabled by a test.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import pytest

from runtime import release_surface
from runtime.dispatch.driver import HostDriver
from runtime.drivers import DriverNotFoundError, select_driver
from z_harness_cli.release_host_evidence import (
    claim_fingerprint as _claim_fingerprint,
    derive_release_claims,
    evidence_set_digest as z_fix_fixture_digest,
    expected_dispatch_probe,
    validate_cli_proof as _validate_cli_proof,
    validate_common_record as _validate_common_record,
    validate_omp_proof as _validate_omp_proof,
    validate_plugin_proof as _validate_plugin_proof,
    validate_release_evidence,
)

SUPPORTED_HOSTS: list[str] = ["claude", "cursor", "codex", "antigravity", "omp"]
EXPECTED_DRIVER_CLASS: dict[str, str] = {
    "claude": "SubprocessClaudeDriver",
    "cursor": "CursorCLIDriver",
    "codex": "CodexDriver",
    "antigravity": "AntigravityHostDriverShim",
    "omp": "OmpHostDriver",
}

_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parent.parent
_FIXTURES_ROOT = _HERE / "fixtures"
Z_FIX_FIXTURE_ROOT = _FIXTURES_ROOT / "z-fix"
SAMPLE_CANDIDATE_SHA = "1" * 40
SAMPLE_FIXTURE_SET_ID = "z-fix-c1-regression-v1"
SAMPLE_FIXTURE_DIGEST = "db3a27d1ef0a62d67ab27719f7ea19aea1dc16c5e0ef61e2dcd5147408dc12d1"
_MINIMAL_PROVIDER_CONFIG: dict[str, Any] = {"host": "<probe>", "args_template": []}
_CRASH_EXCEPTIONS: tuple[type[BaseException], ...] = (
    KeyError,
    AttributeError,
    TypeError,
    IndexError,
)


def _resolve_clear_config_errors() -> tuple[type[BaseException], ...]:
    errors: list[type[BaseException]] = []
    try:
        from runtime.drivers.cursor.cli_driver import DriverConfigError, DriverInitError

        errors.extend([DriverConfigError, DriverInitError])
    except ImportError:
        pass
    try:
        from runtime.drivers.codex.auth import AuthResolutionError

        errors.append(AuthResolutionError)
    except ImportError:
        pass
    try:
        from runtime.drivers.antigravity.preflight import DriverUnavailableError

        errors.append(DriverUnavailableError)
    except ImportError:
        pass
    errors.append(NotImplementedError)
    return tuple(errors)


_CLEAR_CONFIG_ERRORS = _resolve_clear_config_errors()


@pytest.mark.parametrize("host", SUPPORTED_HOSTS)
def test_supported_host_returns_live_driver(host: str) -> None:
    driver = select_driver(host)
    assert isinstance(driver, HostDriver)
    assert type(driver).__name__ == EXPECTED_DRIVER_CLASS[host]


def test_all_supported_hosts_route_to_distinct_drivers() -> None:
    classes = {host: type(select_driver(host)).__name__ for host in SUPPORTED_HOSTS}
    assert len(set(classes.values())) == len(SUPPORTED_HOSTS), classes


def test_codex_multi_agent_claims_stay_blocked_when_runtime_path_is_missing() -> None:
    from runtime.drivers.codex.driver import CodexDriver
    from z_harness_cli.adapters.base import command_tier
    from z_harness_cli.adapters.codex_parity_gate import (
        NATIVE_CANDIDATE_FAMILIES,
        codex_native_subagent_dispatch_available,
    )

    if codex_native_subagent_dispatch_available() and hasattr(
        CodexDriver, "dispatch_native_subagent"
    ):
        return
    assert {
        command: command_tier("codex", command)
        for command in NATIVE_CANDIDATE_FAMILIES
    } == {command: "blocked" for command in NATIVE_CANDIDATE_FAMILIES}


def test_codex_native_claims_require_primitive_and_driver_hook() -> None:
    from runtime.drivers.codex.driver import CodexDriver
    from z_harness_cli.adapters.base import command_tier
    from z_harness_cli.adapters.codex_parity_gate import (
        NATIVE_CANDIDATE_FAMILIES,
        codex_native_subagent_dispatch_available,
    )

    native_claims = [
        command
        for command in NATIVE_CANDIDATE_FAMILIES
        if command_tier("codex", command) == "native"
    ]
    if not native_claims:
        return
    assert codex_native_subagent_dispatch_available()
    assert hasattr(CodexDriver, "dispatch_native_subagent")


def test_unknown_host_raises_driver_not_found() -> None:
    with pytest.raises(DriverNotFoundError) as excinfo:
        select_driver("unknown")
    assert "unknown" in str(excinfo.value)


@pytest.mark.parametrize("bad_host", ["", "claude-code", "gpt", "gemini", "self"])
def test_other_unsupported_hosts_raise_driver_not_found(bad_host: str) -> None:
    with pytest.raises(DriverNotFoundError):
        select_driver(bad_host)


@pytest.mark.parametrize("host", SUPPORTED_HOSTS)
def test_init_does_not_crash_with_unset_auth(host: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "CURSOR_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTIGRAVITY_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    driver = select_driver(host)
    try:
        driver.init(dict(_MINIMAL_PROVIDER_CONFIG))
    except _CRASH_EXCEPTIONS as exc:
        pytest.fail(f"{type(driver).__name__}.init() crashed: {exc!r}")
    except _CLEAR_CONFIG_ERRORS as exc:
        assert str(exc).strip()


def _read_samples() -> dict[str, dict[str, object]]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Z_FIX_FIXTURE_ROOT.glob("*.json"))
    }


def _write_records(root: Path, records: Mapping[str, Mapping[str, object]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, record in records.items():
        (root / f"{name}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def test_checked_samples_cover_exact_c1_roster() -> None:
    claims, errors = derive_release_claims()
    assert not errors
    assert set(_read_samples()) == set(claims) == {"claude", "cli", "codex", "omp"}
    assert z_fix_fixture_digest(Z_FIX_FIXTURE_ROOT) == SAMPLE_FIXTURE_DIGEST
    assert not validate_release_evidence(
        Z_FIX_FIXTURE_ROOT,
        SAMPLE_CANDIDATE_SHA,
        allow_test_fixtures=True,
    )


def test_checked_samples_are_rejected_as_live_release_proof() -> None:
    errors = validate_release_evidence(Z_FIX_FIXTURE_ROOT, SAMPLE_CANDIDATE_SHA)
    assert errors
    for host in ("claude", "cli", "codex", "omp"):
        assert any(host in error and "fixture_mode" in error for error in errors)
        assert any(host in error and "not live release proof" in error for error in errors)


def test_copied_samples_cannot_be_relabelled_as_live_evidence(tmp_path: Path) -> None:
    records = _read_samples()
    for record in records.values():
        record["fixture_mode"] = False
    _write_records(tmp_path, records)
    errors = validate_release_evidence(tmp_path, SAMPLE_CANDIDATE_SHA)
    assert errors
    for host in records:
        assert any(host in error and "not live release proof" in error for error in errors)
        assert any(host in error and "test-sample marker" in error for error in errors)


def test_standalone_rejects_copied_relabelled_samples(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tests.conformance import run_strict

    records = _read_samples()
    for record in records.values():
        record["fixture_mode"] = False
    _write_records(tmp_path, records)
    result = run_strict.main(
        [
            "--candidate-sha",
            SAMPLE_CANDIDATE_SHA,
            "--evidence-root",
            str(tmp_path),
        ]
    )
    assert result == 1
    stderr = capsys.readouterr().err
    assert "checked schema-sample provenance is not live release proof" in stderr


def test_live_evidence_with_nonfixture_provenance_remains_valid(tmp_path: Path) -> None:
    records = _read_samples()
    for host, record in records.items():
        record["fixture_mode"] = False
        record["diagnostics"] = [f"Candidate-bound z-fix evidence recorded for {host}."]
        if host in {"claude", "codex", "omp"}:
            proof = record["proof"]
            assert isinstance(proof, dict)
            proof["dispatch_probe"] = expected_dispatch_probe(SAMPLE_CANDIDATE_SHA)
        provenance = record["provenance"]
        assert isinstance(provenance, dict)
        provenance["runner"] = "candidate-verifier-v1"
        provenance["evidence_root_kind"] = "immutable-candidate-evidence"
        provenance.pop("fixture_candidate_sha")
        provenance.pop("fixture_set_id")
        record["producer"] = {
            "schema_version": 1,
            "repository": "zeke13dev/z-harness",
            "workflow": ".github/workflows/release-evidence.yml",
            "run_id": 12345,
            "job": "produce",
            "environment": "release-evidence",
            "event": "workflow_dispatch",
            "head_sha": SAMPLE_CANDIDATE_SHA,
            "execution_digest": "a" * 64,
        }
    _write_records(tmp_path, records)
    assert not validate_release_evidence(tmp_path, SAMPLE_CANDIDATE_SHA)


def test_runner_and_pytest_share_identical_evidence_interpretation(tmp_path: Path) -> None:
    from tests.conformance import run_strict

    records = _read_samples()
    records["claude"]["command"] = "z-do"
    _write_records(tmp_path, records)
    direct = validate_release_evidence(
        tmp_path, SAMPLE_CANDIDATE_SHA, allow_test_fixtures=True
    )
    runner = run_strict.evaluate_release_evidence(
        tmp_path, SAMPLE_CANDIDATE_SHA, test_fixture_mode=True
    )
    assert runner == direct


def test_runner_allow_missing_is_always_a_hard_failure(capsys: pytest.CaptureFixture[str]) -> None:
    from tests.conformance import run_strict

    result = run_strict.main(
        [
            "--candidate-sha",
            SAMPLE_CANDIDATE_SHA,
            "--evidence-root",
            str(Z_FIX_FIXTURE_ROOT),
            "--test-fixture-mode",
            "--allow-missing",
        ]
    )
    assert result == 1
    assert "cannot relax blocking C1 release claims" in capsys.readouterr().err


def test_runner_fixture_mode_requires_exact_fixture_digest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tests.conformance import run_strict

    monkeypatch.setattr(run_strict, "evidence_set_digest", lambda _root: "0" * 64)
    result = run_strict.main(
        [
            "--candidate-sha",
            SAMPLE_CANDIDATE_SHA,
            "--evidence-root",
            str(Z_FIX_FIXTURE_ROOT),
            "--test-fixture-mode",
        ]
    )
    assert result == 1
    assert "exact digest" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        ("missing", "missing blocking evidence"),
        ("duplicate", "duplicate evidence"),
        ("extra", "unexpected/unclaimed"),
        ("wrong_host", "unexpected/unclaimed"),
        ("wrong_command", "command must be exactly"),
        ("placeholder", "forbidden placeholder"),
        ("advisory", "must be blocking"),
        ("skipped", "status must be exactly"),
        ("nonzero", "exit_code must be integer zero"),
        ("top_exit_bool", "exit_code must be integer zero"),
        ("missing_diagnostics", "diagnostics list is required"),
        ("missing_provenance", "provenance is missing"),
        ("missing_payload", "payload identity is required"),
        ("unknown_field", "unexpected field"),
        ("candidate_missing", "wrong candidate SHA"),
        ("candidate_malformed", "wrong candidate SHA"),
        ("candidate_mismatch", "wrong candidate SHA"),
        ("fingerprint", "fingerprint mismatch"),
        ("downgraded", "wrong or downgraded evidence kind"),
        ("cli_bootstrap", "ordered bootstrap/install/update"),
        ("cli_install", "ordered bootstrap/install/update"),
        ("cli_update", "ordered bootstrap/install/update"),
        ("omp_wheel", "wheel_filename is required"),
        ("omp_filename_mismatch", "filename does not match artifact.name"),
        ("omp_filename_path", "must be an exact basename"),
        ("omp_digest_mismatch", "digest does not match artifact.sha256"),
        ("omp_candidate_mismatch", "does not match canonical candidate"),
        ("omp_repo_import", "must be outside the repository checkout"),
        ("omp_origin", "installed_outside_checkout must be true"),
    ],
)
def test_release_evidence_negative_matrix(tmp_path: Path, mutation: str, needle: str) -> None:
    records = _read_samples()
    if mutation == "missing":
        del records["claude"]
    elif mutation == "duplicate":
        records["duplicate"] = dict(records["claude"])
    elif mutation == "extra":
        records["cursor"] = {**records["claude"], "host": "cursor"}
    elif mutation == "wrong_host":
        records["claude"]["host"] = "cursor"
    elif mutation == "wrong_command":
        records["claude"]["command"] = "z-do"
    elif mutation == "placeholder":
        records["claude"]["diagnostics"] = ["PLACEHOLDER"]
    elif mutation == "advisory":
        records["claude"]["blocking"] = False
    elif mutation == "skipped":
        records["claude"]["status"] = "skipped"
    elif mutation == "nonzero":
        records["claude"]["exit_code"] = 1
    elif mutation == "top_exit_bool":
        records["claude"]["exit_code"] = False
    elif mutation == "missing_diagnostics":
        del records["claude"]["diagnostics"]
    elif mutation == "missing_provenance":
        del records["claude"]["provenance"]
    elif mutation == "missing_payload":
        proof = records["claude"]["proof"]
        assert isinstance(proof, dict)
        del proof["payload"]
    elif mutation == "unknown_field":
        records["claude"]["success_token"] = "passed"
    elif mutation == "candidate_missing":
        del records["claude"]["candidate_sha"]
    elif mutation == "candidate_malformed":
        records["claude"]["candidate_sha"] = "abc"
    elif mutation == "candidate_mismatch":
        records["claude"]["candidate_sha"] = "2" * 40
    elif mutation == "fingerprint":
        records["claude"]["claim_fingerprint"] = "0" * 64
    elif mutation == "downgraded":
        records["codex"]["evidence_kind"] = "preview_advisory"
    elif mutation.startswith("cli_"):
        operation = mutation.removeprefix("cli_")
        proof = records["cli"]["proof"]
        assert isinstance(proof, dict)
        proof["phases"] = [p for p in proof["phases"] if p["operation"] != operation]
    elif mutation == "omp_wheel":
        proof = records["omp"]["proof"]
        assert isinstance(proof, dict)
        del proof["wheel_filename"]
    elif mutation == "omp_filename_mismatch":
        proof = records["omp"]["proof"]
        assert isinstance(proof, dict)
        proof["wheel_filename"] = "other.whl"
    elif mutation == "omp_filename_path":
        proof = records["omp"]["proof"]
        assert isinstance(proof, dict)
        proof["wheel_filename"] = "/tmp/z_harness-0.1.0b13-py3-none-any.whl"
    elif mutation == "omp_digest_mismatch":
        proof = records["omp"]["proof"]
        assert isinstance(proof, dict)
        proof["wheel_sha256"] = "0" * 64
    elif mutation == "omp_candidate_mismatch":
        proof = records["omp"]["proof"]
        assert isinstance(proof, dict)
        proof["candidate_sha"] = "2" * 40
    elif mutation == "omp_repo_import":
        proof = records["omp"]["proof"]
        assert isinstance(proof, dict)
        proof["import_path"] = str(
            _REPO_ROOT / "site-packages" / "z_harness_cli" / "__init__.py"
        )
    elif mutation == "omp_origin":
        proof = records["omp"]["proof"]
        assert isinstance(proof, dict)
        proof["installed_outside_checkout"] = False
    _write_records(tmp_path, records)
    errors = validate_release_evidence(
        tmp_path, SAMPLE_CANDIDATE_SHA, allow_test_fixtures=True
    )
    assert errors
    assert any(needle in error for error in errors), errors


@pytest.mark.parametrize("bad_exit_code", [False, True, 0.0, "0", None])
def test_cli_lifecycle_requires_exact_integer_zero_exit_code(
    tmp_path: Path,
    bad_exit_code: object,
) -> None:
    records = _read_samples()
    proof = records["cli"]["proof"]
    assert isinstance(proof, dict)
    phases = proof["phases"]
    assert isinstance(phases, list)
    phases[1]["exit_code"] = bad_exit_code
    _write_records(tmp_path, records)
    errors = validate_release_evidence(
        tmp_path, SAMPLE_CANDIDATE_SHA, allow_test_fixtures=True
    )
    assert any("exact integer exit_code zero" in error for error in errors), errors


def test_zero_claims_and_zero_records_fail(tmp_path: Path) -> None:
    contract = release_surface.release_contract()
    contract["host_claims"] = {}
    errors = validate_release_evidence(
        tmp_path,
        SAMPLE_CANDIDATE_SHA,
        contract=contract,
        allow_test_fixtures=True,
    )
    assert any("zero C1 blocking" in error for error in errors)


def test_malformed_and_empty_evidence_fail(tmp_path: Path) -> None:
    assert "zero evidence records exercised" in validate_release_evidence(
        tmp_path, SAMPLE_CANDIDATE_SHA, allow_test_fixtures=True
    )
    (tmp_path / "claude.json").write_text("{broken", encoding="utf-8")
    errors = validate_release_evidence(
        tmp_path, SAMPLE_CANDIDATE_SHA, allow_test_fixtures=True
    )
    assert any("malformed evidence record" in error for error in errors)


def test_candidate_argument_must_be_explicit_lowercase_sha() -> None:
    for candidate in ("", "abc", "A" * 40, "0" * 39):
        errors = validate_release_evidence(
            Z_FIX_FIXTURE_ROOT, candidate, allow_test_fixtures=True
        )
        assert "candidate SHA must be explicit lowercase 40-hex" in errors


def test_unclaimed_development_hosts_stay_out_of_roster() -> None:
    claims, errors = derive_release_claims()
    assert not errors
    assert set(claims).isdisjoint(
        {"antigravity", "cursor", "cline", "copilot", "kiro", "pi", "sterling", "windsurf"}
    )


def test_contract_downgrade_and_unknown_blocking_claim_fail() -> None:
    contract = release_surface.release_contract()
    contract["host_claims"]["codex"]["tier"] = "export_only"
    contract["host_claims"]["newhost"] = {"tier": "native", "status": "primary"}
    _, errors = derive_release_claims(contract)
    assert any("codex" in error and "downgraded" in error for error in errors)
    assert any("newhost" in error for error in errors)


def test_codex_partial_preview_claim_is_preserved() -> None:
    claims, errors = derive_release_claims()
    assert not errors
    assert claims["codex"] == {
        "tier": "partial",
        "status": "preview",
        "evidence": "blocking_clean_plugin",
    }
