"""Production authority for strict C1 release-host evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from runtime import release_surface

SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DISPATCH_PROBE_PREFIX = "Z_HARNESS_Z_FIX_DISPATCH_V1:"
REQUIRED_FIELDS = {
    "schema_version", "fixture_mode", "host", "command", "candidate_sha", "claim",
    "claim_fingerprint", "evidence_kind", "blocking", "status", "exit_code", "artifact",
    "provenance", "producer", "diagnostics", "proof",
}
PRODUCER_WORKFLOW = ".github/workflows/release-evidence.yml"
PRODUCER_EVENTS = frozenset({"workflow_dispatch"})
FORBIDDEN_MARKERS = ("placeholder", "advisory", "warning", "skipped", "skip", "xfail")
TEST_SAMPLE_MARKERS = (
    "checked-test-schema-sample", "deterministic schema sample",
    "conformance-fixture-recorder-v1", "z-fix-c1-regression-v1",
)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=repr)


def claim_fingerprint(claims: Mapping[str, Mapping[str, object]]) -> str:
    return hashlib.sha256(canonical_json(claims).encode()).hexdigest()


def evidence_set_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.json")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def derive_release_claims(
    contract: Mapping[str, object] | None = None,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    source = release_surface.release_contract() if contract is None else contract
    raw_claims = source.get("host_claims")
    if not isinstance(raw_claims, Mapping):
        return {}, ["C1 release contract has no object-valued host_claims"]
    expected_shapes: dict[str, dict[str, object]] = {
        "claude": {"tier": "native", "status": "primary", "evidence": "blocking_clean_plugin"},
        "cli": {"tier": "supported", "status": "release", "scope": ["bootstrap", "install", "update"]},
        "codex": {"tier": "partial", "status": "preview", "evidence": "blocking_clean_plugin"},
        "omp": {"tier": "native", "status": "conditional", "condition": "clean_installed_wheel_proof"},
    }
    claims: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    for host, expected in expected_shapes.items():
        actual = raw_claims.get(host)
        if actual != expected:
            errors.append(
                f"C1 claim {host!r} changed or was downgraded: expected "
                f"{canonical_json(expected)}, got {canonical_json(actual)}"
            )
        else:
            claims[host] = dict(expected)
    statuses = {"primary", "release", "preview", "conditional"}
    unexpected = sorted(
        str(host) for host, claim in raw_claims.items()
        if host not in expected_shapes and isinstance(claim, Mapping) and claim.get("status") in statuses
    )
    if unexpected:
        errors.append(f"unrecognized C1 blocking release claim(s): {unexpected}")
    if not claims:
        errors.append("zero C1 blocking release claims derived")
    return claims, errors


def evidence_kind(host: str, claim: Mapping[str, object]) -> str:
    if host == "cli":
        return "blocking_release_lifecycle:bootstrap,install,update" if claim.get("scope") == ["bootstrap", "install", "update"] else ""
    value = claim.get("evidence") if "evidence" in claim else claim.get("condition")
    return value if isinstance(value, str) else ""


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def expected_dispatch_probe(candidate_sha: str) -> str:
    """Return the candidate-bound marker emitted by the reserved installed z-fix branch."""

    return f"{DISPATCH_PROBE_PREFIX}{candidate_sha}"


def validate_dispatch_probe(host: str, proof: object, candidate_sha: str) -> list[str]:
    """Require live plugin/OMP evidence to carry the exact candidate dispatch proof."""

    if not isinstance(proof, Mapping):
        return [f"{host}: dispatch probe proof is missing or malformed"]
    if proof.get("dispatch_probe") != expected_dispatch_probe(candidate_sha):
        return [f"{host}: proof.dispatch_probe does not match the exact candidate SHA"]
    return []


def validate_trusted_producer(producer: object, candidate_sha: str) -> list[str]:
    """Validate the immutable repository-owned producer identity on one record."""

    if not isinstance(producer, Mapping):
        return ["trusted producer identity is missing or malformed"]
    expected_fields = {
        "schema_version",
        "repository",
        "workflow",
        "run_id",
        "job",
        "environment",
        "event",
        "head_sha",
        "execution_digest",
    }
    missing = sorted(expected_fields - set(producer))
    extra = sorted(set(producer) - expected_fields)
    errors: list[str] = []
    if missing:
        errors.append(f"trusted producer is missing field(s): {missing}")
    if extra:
        errors.append(f"trusted producer has unexpected field(s): {extra}")
    checks = (
        (producer.get("schema_version") == 1, "trusted producer schema_version must be 1"),
        (
            isinstance(producer.get("repository"), str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", producer["repository"]),
            "trusted producer repository must be an exact owner/name",
        ),
        (producer.get("workflow") == PRODUCER_WORKFLOW, "trusted producer workflow is not release-evidence.yml"),
        (
            type(producer.get("run_id")) is int and producer["run_id"] > 0,
            "trusted producer run_id must be a positive integer",
        ),
        (producer.get("job") == "produce", "trusted producer job must be exactly 'produce'"),
        (producer.get("environment") == "release-evidence", "trusted producer environment must be exactly 'release-evidence'"),
        (producer.get("event") in PRODUCER_EVENTS, "trusted producer event is not allowed"),
        (producer.get("head_sha") == candidate_sha, "trusted producer head SHA does not match candidate"),
        (
            isinstance(producer.get("execution_digest"), str)
            and bool(SHA256_RE.fullmatch(producer["execution_digest"])),
            "trusted producer execution digest must be lowercase 64-hex",
        ),
    )
    errors.extend(message for valid, message in checks if not valid)
    return errors


def validate_common_record(
    record: Mapping[str, object], *, host: str, claim: Mapping[str, object],
    claims_fingerprint: str, candidate_sha: str, allow_test_fixtures: bool,
    require_trusted_producer: bool = True,
) -> list[str]:
    errors: list[str] = []
    fields = set(record)
    required_fields = REQUIRED_FIELDS - (
        {"producer"} if allow_test_fixtures or not require_trusted_producer else set()
    )
    allowed_fields = REQUIRED_FIELDS
    missing, extra = sorted(required_fields - fields), sorted(fields - allowed_fields)
    if missing:
        errors.append(f"{host}: missing required field(s): {missing}")
    if extra:
        errors.append(f"{host}: unexpected field(s): {extra}")
    fixture_mode = record.get("fixture_mode")
    checks = (
        (record.get("schema_version") == 1, f"{host}: schema_version must be 1"),
        (fixture_mode is False or (allow_test_fixtures and fixture_mode is True), f"{host}: fixture_mode evidence is test-only and not release proof"),
        (record.get("host") == host, f"{host}: evidence host does not match record identity"),
        (record.get("command") == "z-fix", f"{host}: command must be exactly 'z-fix'"),
        (record.get("candidate_sha") == candidate_sha, f"{host}: evidence is stale or bound to the wrong candidate SHA"),
        (record.get("claim") == claim, f"{host}: claim snapshot differs from current C1 claim"),
        (record.get("claim_fingerprint") == claims_fingerprint, f"{host}: C1 claim fingerprint mismatch"),
        (bool(evidence_kind(host, claim)) and record.get("evidence_kind") == evidence_kind(host, claim), f"{host}: wrong or downgraded evidence kind"),
        (record.get("blocking") is True, f"{host}: evidence must be blocking, not advisory"),
        (record.get("status") == "passed", f"{host}: status must be exactly 'passed' (skip/advisory is invalid)"),
        (type(record.get("exit_code")) is int and record.get("exit_code") == 0, f"{host}: z-fix exit_code must be integer zero"),
    )
    errors.extend(message for valid, message in checks if not valid)
    artifact = record.get("artifact")
    if not isinstance(artifact, Mapping):
        errors.append(f"{host}: artifact identity is missing or malformed")
    else:
        if not _nonempty(artifact.get("name")):
            errors.append(f"{host}: artifact.name is required")
        if not isinstance(artifact.get("sha256"), str) or not SHA256_RE.fullmatch(artifact["sha256"]):
            errors.append(f"{host}: artifact.sha256 must be lowercase 64-hex")
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append(f"{host}: provenance is missing or malformed")
    else:
        for key in ("runner", "environment", "evidence_root_kind"):
            if not _nonempty(provenance.get(key)):
                errors.append(f"{host}: provenance.{key} is required")
        sample = (
            provenance.get("evidence_root_kind") == "checked-test-schema-sample"
            or provenance.get("runner") == "conformance-fixture-recorder-v1"
            or provenance.get("fixture_set_id") == "z-fix-c1-regression-v1"
        )
        if allow_test_fixtures:
            if not (fixture_mode is True and provenance.get("evidence_root_kind") == "checked-test-schema-sample" and provenance.get("runner") == "conformance-fixture-recorder-v1" and provenance.get("fixture_set_id") == "z-fix-c1-regression-v1" and provenance.get("fixture_candidate_sha") == "1" * 40):
                errors.append(f"{host}: invalid checked fixture provenance identity")
        elif sample:
            errors.append(f"{host}: checked schema-sample provenance is not live release proof")
    if require_trusted_producer and not allow_test_fixtures:
        errors.extend(
            f"{host}: {message}"
            for message in validate_trusted_producer(record.get("producer"), candidate_sha)
        )
    diagnostics = record.get("diagnostics")
    if not (isinstance(diagnostics, list) and diagnostics and all(_nonempty(item) for item in diagnostics)):
        errors.append(f"{host}: non-empty diagnostics list is required")
    serialized = canonical_json(record).lower()
    marker = next((item for item in FORBIDDEN_MARKERS if item in serialized), None)
    if marker is not None:
        errors.append(f"{host}: forbidden placeholder/advisory marker {marker!r}")
    if not allow_test_fixtures:
        sample_marker = next((item for item in TEST_SAMPLE_MARKERS if item in serialized), None)
        if sample_marker is not None:
            errors.append(f"{host}: checked test-sample marker {sample_marker!r} is not live proof")
    return errors


def validate_plugin_proof(host: str, proof: object) -> list[str]:
    if not isinstance(proof, Mapping):
        return [f"{host}: clean-plugin proof is missing or malformed"]
    errors: list[str] = []
    if proof.get("kind") != "clean_installed_plugin": errors.append(f"{host}: proof.kind must be 'clean_installed_plugin'")
    if proof.get("clean_home") is not True or proof.get("isolated_config") is not True: errors.append(f"{host}: proof must assert clean_home and isolated_config")
    payload = proof.get("payload")
    if not isinstance(payload, Mapping):
        errors.append(f"{host}: installed plugin payload identity is required")
    else:
        if not _nonempty(payload.get("path")): errors.append(f"{host}: payload.path is required")
        if not isinstance(payload.get("sha256"), str) or not SHA256_RE.fullmatch(payload["sha256"]): errors.append(f"{host}: payload.sha256 must be lowercase 64-hex")
    if not _nonempty(proof.get("runner")): errors.append(f"{host}: proof.runner is required")
    return errors


def validate_cli_proof(proof: object) -> list[str]:
    if not isinstance(proof, Mapping): return ["cli: lifecycle proof is missing or malformed"]
    errors: list[str] = []
    if proof.get("kind") != "clean_release_lifecycle": errors.append("cli: proof.kind must be 'clean_release_lifecycle'")
    phases = proof.get("phases")
    operations = [p.get("operation") for p in phases if isinstance(p, Mapping)] if isinstance(phases, list) else []
    if not isinstance(phases, list) or operations != ["bootstrap", "install", "update"]:
        errors.append("cli: lifecycle must contain ordered bootstrap/install/update phases")
    elif any(p.get("status") != "passed" or type(p.get("exit_code")) is not int or p.get("exit_code") != 0 for p in phases):
        errors.append("cli: every lifecycle phase must pass with exact integer exit_code zero")
    if proof.get("clean_home") is not True or proof.get("isolated_config") is not True: errors.append("cli: lifecycle must assert clean_home and isolated_config")
    if not _nonempty(proof.get("runner")): errors.append("cli: proof.runner is required")
    return errors


def validate_omp_proof(proof: object, artifact: object, candidate_sha: str, *, repo_root: Path | None = None) -> list[str]:
    if not isinstance(proof, Mapping): return ["omp: installed-wheel proof is missing or malformed"]
    errors: list[str] = []
    if proof.get("kind") != "clean_installed_wheel": errors.append("omp: proof.kind must be 'clean_installed_wheel'")
    for key in ("wheel_filename", "distribution", "import_path", "runner"):
        if not _nonempty(proof.get(key)): errors.append(f"omp: proof.{key} is required")
    digest = proof.get("wheel_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest): errors.append("omp: proof.wheel_sha256 must be lowercase 64-hex")
    filename = proof.get("wheel_filename")
    if isinstance(filename, str) and Path(filename).name != filename: errors.append("omp: proof.wheel_filename must be an exact basename")
    if isinstance(artifact, Mapping):
        if filename != artifact.get("name"): errors.append("omp: wheel filename does not match artifact.name")
        if digest != artifact.get("sha256"): errors.append("omp: wheel digest does not match artifact.sha256")
    if proof.get("candidate_sha") != candidate_sha: errors.append("omp: proof candidate SHA does not match canonical candidate")
    import_path = proof.get("import_path")
    if isinstance(import_path, str) and import_path:
        resolved = Path(import_path).resolve(strict=False)
        if not Path(import_path).is_absolute(): errors.append("omp: proof.import_path must be absolute")
        root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
        if resolved == root or root in resolved.parents: errors.append("omp: proof.import_path must be outside the repository checkout")
        if "site-packages" not in resolved.parts: errors.append("omp: proof.import_path must identify installed site-packages")
    if proof.get("installed_outside_checkout") is not True: errors.append("omp: installed_outside_checkout must be true")
    if proof.get("imported_from_installed_wheel") is not True: errors.append("omp: imported_from_installed_wheel must be true")
    if proof.get("dev_dependencies") is not False: errors.append("omp: dev_dependencies must be false")
    return errors


def validate_release_evidence(
    evidence_root: Path, candidate_sha: str, *, contract: Mapping[str, object] | None = None,
    allow_test_fixtures: bool = False, repo_root: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    if not SHA40_RE.fullmatch(candidate_sha): errors.append("candidate SHA must be explicit lowercase 40-hex")
    claims, claim_errors = derive_release_claims(contract)
    errors.extend(claim_errors)
    if not claims: return errors
    fingerprint = claim_fingerprint(claims)
    if not evidence_root.is_dir(): return errors + [f"evidence root is missing or not a directory: {evidence_root}"]
    entries = sorted(evidence_root.iterdir())
    paths = [p for p in entries if p.is_file() and p.suffix == ".json"]
    invalid = [p.name for p in entries if p not in paths]
    if invalid: errors.append(f"unexpected evidence-root entries: {invalid}")
    if not paths: return errors + ["zero evidence records exercised"]
    records: dict[str, list[Mapping[str, object]]] = {}
    for path in paths:
        try: raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"malformed evidence record {path.name}: {exc}"); continue
        if not isinstance(raw, Mapping): errors.append(f"malformed evidence record {path.name}: expected JSON object"); continue
        host = raw.get("host")
        if not isinstance(host, str) or not host: errors.append(f"malformed evidence record {path.name}: host is required"); continue
        records.setdefault(host, []).append(raw)
        if path.name != f"{host}.json": errors.append(f"{host}: evidence filename must be exactly {host}.json")
    for host in sorted(set(claims) - set(records)): errors.append(f"missing blocking evidence for C1 claim {host!r}")
    for host in sorted(set(records) - set(claims)): errors.append(f"unexpected/unclaimed host evidence {host!r}")
    for host, host_records in sorted(records.items()):
        if len(host_records) != 1: errors.append(f"duplicate evidence for host {host!r}: {len(host_records)} records"); continue
        if host not in claims: continue
        record = host_records[0]
        errors.extend(validate_common_record(record, host=host, claim=claims[host], claims_fingerprint=fingerprint, candidate_sha=candidate_sha, allow_test_fixtures=allow_test_fixtures))
        proof = record.get("proof")
        if host in {"claude", "codex", "omp"} and not allow_test_fixtures:
            errors.extend(validate_dispatch_probe(host, proof, candidate_sha))
        if host in {"claude", "codex"}: errors.extend(validate_plugin_proof(host, proof))
        elif host == "cli": errors.extend(validate_cli_proof(proof))
        elif host == "omp": errors.extend(validate_omp_proof(proof, record.get("artifact"), candidate_sha, repo_root=repo_root))
    if not errors and len(records) != len(claims): errors.append("zero or incomplete C1 release claims exercised")
    return errors
