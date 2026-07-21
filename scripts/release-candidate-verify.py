#!/usr/bin/env python3
"""Verify one immutable release candidate without publishing or mutating Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

# Direct script execution places ``scripts/`` rather than the checkout root on
# sys.path. The verifier imports only candidate-owned release APIs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.release_surface import (
    path_excluded_from_prod,
    prod_owner_for_path,
    release_contract,
    validate_release_contract,
)
from z_harness_cli.release import parse_release_candidate, verify_release_artifacts


SHA_RE = re.compile(r"[0-9a-f]{40}")
EXPECTED_ARTIFACT_FIXED_NAMES = frozenset(
    {"install.sh", "install-plugin.sh", "latest.json", "release-assets.json", "SHA256SUMS"}
)
EXPECTED_CLOSURE_DIMENSIONS = frozenset(
    {
        "skill-script",
        "skill-agent",
        "mcp-handler",
        "export",
        "optional-feature",
        "memory",
        "provider-role",
    }
)
DIAGNOSTIC_LIMIT = 4096
FAST_LANE_IDS = (
    "c1-release-contract",
    "c2-release-artifacts",
    "c3-prod-dependency-closure",
    "c4-transaction-contract",
    "c5-identity-provenance",
)
SLOW_LANE_IDS = (
    "python-suite",
    "shell-suite",
    "normal-clone",
    "linked-worktree",
    "isolated-install-setup-provider-notification",
    "installed-wheel-outside-checkout",
    "claimed-host-evidence",
)
C4_CONTRACT_NODE = (
    "tests/test_install_sh_integrity.py::InstallShIntegrityTest::"
    "test_every_fault_step_restores_full_all_host_cli_pre_state"
)


class VerificationError(RuntimeError):
    """Raised when candidate verification cannot produce passing evidence."""


@dataclass(frozen=True)
class Inputs:
    candidate_version: str
    candidate_sha: str
    repo_root: Path
    candidate_root: Path
    artifacts: Path
    host_evidence_root: Path
    evidence_out: Path


@dataclass(frozen=True)
class Snapshot:
    head: str
    status: str
    refs_fingerprint: str
    candidate_fingerprint: str
    artifacts_fingerprint: str
    host_evidence_fingerprint: str


@dataclass(frozen=True)
class PromotionInputs:
    source_sha: str
    prod_sha: str
    repo_root: Path
    prod_root: Path
    candidate_root: Path
    artifacts: Path
    host_evidence_root: Path
    evidence: Path
    authorization_out: Path | None


CommandRunner = Callable[[Sequence[str], Path, dict[str, str]], subprocess.CompletedProcess[str]]


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _run_command(argv: Sequence[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    if argv and argv[0].startswith("internal:"):
        try:
            if argv[0] == "internal:c1-release-contract" and len(argv) == 1:
                validate_release_contract(release_contract())
            elif argv[0] == "internal:c2-release-artifacts" and len(argv) == 3:
                verify_release_artifacts(argv[1], argv[2])
            elif argv[0] == "internal:c5-identity-provenance" and len(argv) == 6:
                _verify_c5_identity(
                    candidate_version=argv[1],
                    candidate_sha=argv[2],
                    repo_root=Path(argv[3]),
                    candidate_root=Path(argv[4]),
                    artifacts=Path(argv[5]),
                )
            elif argv[0] == "internal:checkout-shape" and len(argv) == 4:
                _verify_checkout_shape(argv[1], Path(argv[2]), argv[3], env)
            elif argv[0] == "internal:installed-wheel" and len(argv) == 4:
                _verify_installed_wheel(
                    Path(argv[1]), Path(argv[2]), Path(argv[3]), env
                )
            elif argv[0] == "internal:claimed-host-evidence" and len(argv) == 5:
                _verify_claimed_host_evidence(
                    Path(argv[1]), argv[2], argv[3], Path(argv[4]), env
                )
            else:
                raise VerificationError("unknown or malformed internal lane command")
        except (OSError, ValueError, VerificationError) as exc:
            return subprocess.CompletedProcess(list(argv), 1, "", str(exc))
        return subprocess.CompletedProcess(list(argv), 0, "", "")
    return subprocess.run(
        list(argv), cwd=cwd, env=env, text=True, capture_output=True, check=False
    )


def _checked(argv: Sequence[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        list(argv), cwd=cwd, env=env, text=True, capture_output=True, check=False
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise VerificationError(f"command failed ({' '.join(argv)}): {detail}")
    return result.stdout


def _verify_checkout_shape(kind: str, repo_root: Path, candidate_sha: str, env: dict[str, str]) -> None:
    """Exercise candidate code through disposable, genuine Git checkout shapes."""

    if kind not in {"normal-clone", "linked-worktree"}:
        raise VerificationError(f"unknown checkout shape: {kind}")
    with tempfile.TemporaryDirectory(prefix="z-release-shape-") as temporary:
        base = Path(temporary)
        clone = base / "clone"
        _checked(
            ("git", "clone", "--quiet", "--no-hardlinks", str(repo_root), str(clone)),
            cwd=base,
            env=env,
        )
        _checked(("git", "checkout", "--quiet", "--detach", candidate_sha), cwd=clone, env=env)
        target = clone
        if kind == "linked-worktree":
            target = base / "linked"
            _checked(
                ("git", "worktree", "add", "--quiet", "--detach", str(target), candidate_sha),
                cwd=clone,
                env=env,
            )
        git_marker = target / ".git"
        if kind == "normal-clone" and not git_marker.is_dir():
            raise VerificationError("normal-clone lane did not create a real .git directory")
        if kind == "linked-worktree" and not git_marker.is_file():
            raise VerificationError("linked-worktree lane did not create a real .git file")
        head = _checked(("git", "rev-parse", "HEAD"), cwd=target, env=env).strip()
        if head != candidate_sha:
            raise VerificationError(f"{kind} lane checked out the wrong candidate")
        _checked(
            (
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-q",
                "tests",
                "scripts",
                "runtime",
            ),
            cwd=target,
            env=env,
        )
        _checked(("make", "test-sh"), cwd=target, env=env)


def _verify_installed_wheel(
    artifacts: Path,
    candidate_root: Path,
    repo_root: Path,
    env: dict[str, str],
) -> None:
    """Install the exact wheel without deps and execute it outside every checkout."""

    wheels = sorted(artifacts.glob("*.whl"))
    if len(wheels) != 1:
        raise VerificationError("installed-wheel lane requires exactly one wheel")
    wheel = wheels[0]
    with tempfile.TemporaryDirectory(prefix="z-release-wheel-") as temporary:
        base = Path(temporary)
        venv = base / "venv"
        outside = base / "outside"
        outside.mkdir()
        _checked((sys.executable, "-m", "venv", str(venv)), cwd=outside, env=env)
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        _checked(
            (str(python), "-I", "-m", "pip", "install", "--no-deps", str(wheel)),
            cwd=outside,
            env=env,
        )
        isolated_env = dict(env)
        isolated_env.pop("PYTHONPATH", None)
        isolated_env["PYTHONNOUSERSITE"] = "1"
        _checked((str(python), "-I", "-B", "-m", "z_harness_cli", "--help"), cwd=outside, env=isolated_env)
        _checked(
            (
                str(python),
                "-I",
                "-B",
                "-m",
                "z_harness_cli.mcp_prod_tool_list_smoke",
                "--repo-root",
                str(repo_root),
            ),
            cwd=outside,
            env=isolated_env,
        )
        export_out = base / "omp-installed-wheel"
        smoke = candidate_root / "scripts" / "omp-prod-export-smoke.py"
        if not smoke.is_file():
            raise VerificationError("candidate is missing scripts/omp-prod-export-smoke.py")
        _checked(
            (
                str(python),
                "-I",
                "-B",
                str(smoke),
                "--cli",
                str(venv / ("Scripts/z-harness.exe" if os.name == "nt" else "bin/z-harness")),
                "--root",
                str(candidate_root),
                "--out",
                str(export_out),
            ),
            cwd=outside,
            env=isolated_env,
        )
        for path in (repo_root, candidate_root):
            if _is_relative_to(python.resolve(), path):
                raise VerificationError("installed-wheel interpreter resolved inside a checkout")


def _verify_claimed_host_evidence(
    evidence_root: Path,
    candidate_sha: str,
    artifacts_fingerprint: str,
    repo_root: Path,
    env: dict[str, str],
) -> None:
    """Bind every strict host record to this exact seven-file artifact set."""

    records = sorted(evidence_root.glob("*.json"))
    if not records:
        raise VerificationError("claimed-host evidence root contains no JSON records")
    producer_runs: set[tuple[object, ...]] = set()
    for record_path in records:
        record = _load_object(record_path, "claimed-host evidence")
        if record.get("candidate_sha") != candidate_sha:
            raise VerificationError(
                f"claimed-host evidence candidate mismatch: {record_path.name}"
            )
        provenance = record.get("provenance")
        bound_fingerprint = (
            provenance.get("artifact_set_fingerprint")
            if isinstance(provenance, dict)
            else None
        )
        if bound_fingerprint != artifacts_fingerprint:
            raise VerificationError(
                f"claimed-host evidence artifact-set mismatch: {record_path.name}"
            )
        producer = record.get("producer")
        if not isinstance(producer, dict):
            raise VerificationError(f"claimed-host evidence producer missing: {record_path.name}")
        producer_runs.add(
            (
                producer.get("repository"), producer.get("workflow"), producer.get("run_id"),
                producer.get("job"), producer.get("environment"), producer.get("event"),
                producer.get("head_sha"),
            )
        )
    if len(producer_runs) != 1:
        raise VerificationError("claimed-host evidence records do not share one trusted producer run")
    producer_context = next(iter(producer_runs))
    expected_keys = (
        "Z_HARNESS_EVIDENCE_REPOSITORY", "Z_HARNESS_EVIDENCE_WORKFLOW",
        "Z_HARNESS_EVIDENCE_RUN_ID", "Z_HARNESS_EVIDENCE_JOB",
        "Z_HARNESS_EVIDENCE_ENVIRONMENT", "Z_HARNESS_EVIDENCE_EVENT",
        "Z_HARNESS_EVIDENCE_HEAD_SHA",
    )
    expected_context = tuple(env.get(key) for key in expected_keys)
    if any(value is not None for value in expected_context):
        if any(value is None for value in expected_context):
            raise VerificationError("authenticated evidence producer context is incomplete")
        actual_context = tuple(str(value) for value in producer_context)
        if actual_context != expected_context:
            raise VerificationError("claimed-host evidence producer differs from authenticated run")
    _checked(
        (
            sys.executable,
            "-B",
            "tests/conformance/run_strict.py",
            "--candidate-sha",
            candidate_sha,
            "--evidence-root",
            str(evidence_root),
        ),
        cwd=repo_root,
        env=env,
    )


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise VerificationError(f"Git inspection failed: {detail}")
    return result.stdout


def _promotion_git(repo_root: Path, *args: str) -> str:
    """Run one allowlisted read-only Git-plumbing query for promotion gates."""

    allowed = {
        ("rev-parse", "--show-toplevel"),
        ("rev-parse", "--verify"),
        ("symbolic-ref", "--quiet", "HEAD"),
        ("status", "--porcelain=v1", "--untracked-files=all"),
        ("for-each-ref", "--format=%(refname)%00%(objectname)"),
        ("diff", "--no-renames", "--name-status", "-z"),
        ("ls-tree", "-r", "--name-only", "-z"),
    }
    if not any(args[: len(prefix)] == prefix for prefix in allowed):
        raise VerificationError("promotion Git query is not in the read-only allowlist")
    return _git(repo_root, *args)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_inputs(namespace: argparse.Namespace) -> Inputs:
    try:
        candidate = parse_release_candidate(namespace.candidate_version)
    except ValueError as exc:
        raise VerificationError(str(exc)) from exc
    if namespace.candidate_version != candidate.plugin_version:
        raise VerificationError("candidate version must use canonical plugin spelling")
    if SHA_RE.fullmatch(namespace.candidate_sha) is None:
        raise VerificationError("candidate SHA must be exactly 40 lowercase hexadecimal characters")

    raw_roots = (
        ("repository root", Path(namespace.repo_root)),
        ("candidate root", Path(namespace.candidate_root)),
        ("artifact directory", Path(namespace.artifacts)),
        ("host evidence root", Path(namespace.host_evidence_root)),
    )
    for label, root in raw_roots:
        if root.is_symlink():
            raise VerificationError(f"{label} must not be a symlink: {root}")
    repo_root = raw_roots[0][1].resolve(strict=True)
    candidate_root = raw_roots[1][1].resolve(strict=True)
    artifacts = raw_roots[2][1].resolve(strict=True)
    host_evidence_root = raw_roots[3][1].resolve(strict=True)
    raw_evidence_out = Path(namespace.evidence_out)
    if raw_evidence_out.is_symlink():
        raise VerificationError(f"evidence destination must not be a symlink: {raw_evidence_out}")
    evidence_out = raw_evidence_out.resolve(strict=False)
    for label, root in (
        ("repository root", repo_root),
        ("candidate root", candidate_root),
        ("artifact directory", artifacts),
        ("host evidence root", host_evidence_root),
    ):
        if not root.is_dir():
            raise VerificationError(f"{label} is not a directory: {root}")
    if evidence_out.exists() or evidence_out.is_symlink():
        raise VerificationError(f"evidence destination already exists: {evidence_out}")
    if not evidence_out.parent.is_dir():
        raise VerificationError(f"evidence parent is not a directory: {evidence_out.parent}")

    roots = (
        ("repository", repo_root),
        ("candidate", candidate_root),
        ("artifacts", artifacts),
        ("host evidence", host_evidence_root),
    )
    for index, (left_label, left) in enumerate(roots):
        for right_label, right in roots[index + 1 :]:
            if _is_relative_to(left, right) or _is_relative_to(right, left):
                raise VerificationError(f"{left_label} and {right_label} roots must be separate")
    for label, root in roots:
        if _is_relative_to(evidence_out, root) or _is_relative_to(root, evidence_out):
            raise VerificationError(f"evidence destination overlaps {label} input")

    return Inputs(
        candidate_version=candidate.plugin_version,
        candidate_sha=namespace.candidate_sha,
        repo_root=repo_root,
        candidate_root=candidate_root,
        artifacts=artifacts,
        host_evidence_root=host_evidence_root,
        evidence_out=evidence_out,
    )


def _inventory(root: Path) -> tuple[str, list[dict[str, object]]]:
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        file_stat = path.lstat()
        if stat.S_ISDIR(file_stat.st_mode):
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            raise VerificationError(
                f"recursive input contains a symlink or special file: {root / relative}"
            )
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


def _git_snapshot(inputs: Inputs) -> tuple[str, str, str]:
    top = Path(_git(inputs.repo_root, "rev-parse", "--show-toplevel").strip()).resolve()
    if top != inputs.repo_root:
        raise VerificationError("repo root must be the exact Git top level")
    head = _git(inputs.repo_root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if head != inputs.candidate_sha:
        raise VerificationError("repository HEAD does not match candidate SHA")
    status = _git(inputs.repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise VerificationError("repository must be clean, including staged and untracked files")
    refs = _git(inputs.repo_root, "for-each-ref", "--format=%(refname)%00%(objectname)")
    return head, status, _sha256_bytes(refs.encode("utf-8"))


def _snapshot(inputs: Inputs) -> Snapshot:
    head, status, refs_fingerprint = _git_snapshot(inputs)
    candidate_fingerprint, _ = _inventory(inputs.candidate_root)
    artifacts_fingerprint, _ = _inventory(inputs.artifacts)
    host_evidence_fingerprint, _ = _inventory(inputs.host_evidence_root)
    return Snapshot(
        head,
        status,
        refs_fingerprint,
        candidate_fingerprint,
        artifacts_fingerprint,
        host_evidence_fingerprint,
    )


def _input_fingerprint(snapshot: Snapshot) -> str:
    return _sha256_bytes(
        _canonical_json(
            {
                "head": snapshot.head,
                "refs": snapshot.refs_fingerprint,
                "candidate": snapshot.candidate_fingerprint,
                "artifacts": snapshot.artifacts_fingerprint,
                "host_evidence": snapshot.host_evidence_fingerprint,
            }
        )
    )


def _require_exact_artifacts(artifacts: Path) -> None:
    names = {path.name for path in artifacts.iterdir()}
    wheels = [name for name in names if name.endswith(".whl")]
    tarballs = [name for name in names if name.startswith("z-harness-") and name.endswith(".tar.gz")]
    expected = EXPECTED_ARTIFACT_FIXED_NAMES | set(wheels) | set(tarballs)
    if len(wheels) != 1 or len(tarballs) != 1 or names != expected or len(names) != 7:
        raise VerificationError("artifact directory must contain the exact seven-file release allowlist")


def _load_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be a JSON object")
    return value


def _require_identity(inputs: Inputs) -> None:
    plugin = _load_object(
        inputs.candidate_root / ".codex-plugin" / "plugin.json",
        "staged plugin manifest",
    )
    assets = _load_object(inputs.artifacts / "release-assets.json", "release asset manifest")
    for label, value in (("staged plugin", plugin), ("release assets", assets)):
        if value.get("version", value.get("candidate_version")) != inputs.candidate_version:
            raise VerificationError(f"{label} candidate version does not match")
        if value.get("candidate_commit") != inputs.candidate_sha:
            raise VerificationError(f"{label} candidate commit does not match")


def _verify_c5_identity(
    *,
    candidate_version: str,
    candidate_sha: str,
    repo_root: Path,
    candidate_root: Path,
    artifacts: Path,
) -> None:
    """Run the fixed internal C5 identity, HEAD, status, and ref inspection."""

    candidate = parse_release_candidate(candidate_version)
    if candidate.plugin_version != candidate_version:
        raise VerificationError("C5 candidate version is not canonical")
    if SHA_RE.fullmatch(candidate_sha) is None:
        raise VerificationError("C5 candidate SHA is not exact lowercase 40-hex")
    top = Path(_git(repo_root, "rev-parse", "--show-toplevel").strip()).resolve()
    if top != repo_root:
        raise VerificationError("C5 repository root is not the exact Git top level")
    head = _git(repo_root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if head != candidate_sha:
        raise VerificationError("C5 candidate HEAD mismatch")
    if _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise VerificationError("C5 repository status is not clean")
    _git(repo_root, "for-each-ref", "--format=%(refname)%00%(objectname)")
    plugin = _load_object(candidate_root / ".codex-plugin" / "plugin.json", "staged plugin manifest")
    assets = _load_object(artifacts / "release-assets.json", "release asset manifest")
    if plugin.get("version") != candidate_version or plugin.get("candidate_commit") != candidate_sha:
        raise VerificationError("C5 staged plugin identity mismatch")
    if (
        assets.get("candidate_version") != candidate_version
        or assets.get("candidate_commit") != candidate_sha
    ):
        raise VerificationError("C5 release asset identity mismatch")


def _lane_commands(inputs: Inputs) -> tuple[tuple[str, tuple[str, ...]], ...]:
    python = sys.executable
    c1 = ("internal:c1-release-contract",)
    c2 = (
        "internal:c2-release-artifacts",
        str(inputs.artifacts),
        inputs.candidate_version,
    )
    c3 = (
        python,
        "-B",
        "-m",
        "z_harness_cli.release_surface",
        "verify-closure",
        "--root",
        str(inputs.candidate_root),
    )
    c4 = (
        python,
        "-B",
        "-m",
        "pytest",
        "-q",
        C4_CONTRACT_NODE,
    )
    c5 = (
        "internal:c5-identity-provenance",
        inputs.candidate_version,
        inputs.candidate_sha,
        str(inputs.repo_root),
        str(inputs.candidate_root),
        str(inputs.artifacts),
    )
    return tuple(zip(FAST_LANE_IDS, (c1, c2, c3, c4, c5), strict=True))


def _slow_lane_commands(inputs: Inputs) -> tuple[tuple[str, tuple[str, ...]], ...]:
    python = sys.executable
    commands = (
        (python, "-B", "-m", "pytest", "-q", "tests", "scripts", "runtime"),
        ("make", "test-sh"),
        ("internal:checkout-shape", "normal-clone", str(inputs.repo_root), inputs.candidate_sha),
        ("internal:checkout-shape", "linked-worktree", str(inputs.repo_root), inputs.candidate_sha),
        (
            python,
            "-B",
            "-m",
            "pytest",
            "-q",
            "tests/test_setup_command.py",
            "tests/test_resolve_provider.py",
            "tests/test_release.py",
            "tests/test_release_gates.py",
        ),
        (
            "internal:installed-wheel",
            str(inputs.artifacts),
            str(inputs.candidate_root),
            str(inputs.repo_root),
        ),
        (
            "internal:claimed-host-evidence",
            str(inputs.host_evidence_root),
            inputs.candidate_sha,
            _inventory(inputs.artifacts)[0],
            str(inputs.repo_root),
        ),
    )
    return tuple(zip(SLOW_LANE_IDS, commands, strict=True))


def _validate_slow_lane_commands(
    commands: tuple[tuple[str, tuple[str, ...]], ...], inputs: Inputs
) -> None:
    if commands != _slow_lane_commands(inputs):
        raise VerificationError("slow-lane command inventory is not the fixed release contract")
    if tuple(lane_id for lane_id, _ in commands) != SLOW_LANE_IDS:
        raise VerificationError("slow-lane ordering changed")


def _hermetic_environment(home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        upper = name.upper()
        if (
            upper.startswith("Z_HARNESS_")
            or "WEBHOOK" in upper
            or upper.endswith("_API_KEY")
            or upper.endswith("_AUTH_TOKEN")
            or upper in {"PYTHONPATH", "PYTHONHOME", "PYTHONOPTIMIZE"}
        ):
            environment.pop(name, None)
    environment.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
        }
    )
    for name in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        Path(environment[name]).mkdir(parents=True, exist_ok=True)
    return environment


def _validate_lane_commands(
    commands: tuple[tuple[str, tuple[str, ...]], ...], inputs: Inputs
) -> None:
    """Reject any lane payload outside the fixed read-only operation map."""

    expected = (
        ("c1-release-contract", ("internal:c1-release-contract",)),
        (
            "c2-release-artifacts",
            (
                "internal:c2-release-artifacts",
                str(inputs.artifacts),
                inputs.candidate_version,
            ),
        ),
        (
            "c3-prod-dependency-closure",
            (
                sys.executable,
                "-B",
                "-m",
                "z_harness_cli.release_surface",
                "verify-closure",
                "--root",
                str(inputs.candidate_root),
            ),
        ),
        (
            "c4-transaction-contract",
            (sys.executable, "-B", "-m", "pytest", "-q", C4_CONTRACT_NODE),
        ),
        (
            "c5-identity-provenance",
            (
                "internal:c5-identity-provenance",
                inputs.candidate_version,
                inputs.candidate_sha,
                str(inputs.repo_root),
                str(inputs.candidate_root),
                str(inputs.artifacts),
            ),
        ),
    )
    if any("-c" in argv for _, argv in commands):
        raise VerificationError("dynamic Python payloads are forbidden in fast lanes")
    if commands != expected:
        raise VerificationError("fast-lane command inventory is not the fixed read-only contract")


def _diagnostic(value: str) -> dict[str, object]:
    encoded = value.encode("utf-8", errors="replace")
    return {
        "text": encoded[:DIAGNOSTIC_LIMIT].decode("utf-8", errors="replace"),
        "truncated": len(encoded) > DIAGNOSTIC_LIMIT,
        "sha256": _sha256_bytes(encoded),
    }


def _validate_c3_output(stdout: str) -> None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError("C3 closure lane did not emit valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("errors") != []:
        raise VerificationError("C3 closure lane reported a failed result")
    if set(payload.get("dimensions", [])) != EXPECTED_CLOSURE_DIMENSIONS:
        raise VerificationError("C3 closure lane omitted an accepted closure dimension")


def _assert_unchanged(inputs: Inputs, initial: Snapshot) -> None:
    if _snapshot(inputs) != initial:
        raise VerificationError("candidate inputs, Git state, HEAD, or refs changed during verification")


def _write_evidence(path: Path, payload: dict[str, object]) -> None:
    descriptor = -1
    reservation = -1
    temporary: Path | None = None
    destination_cleanup_armed = False
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            reservation = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            destination_cleanup_armed = True
        except FileExistsError as exc:
            raise VerificationError(f"evidence destination appeared during verification: {path}") from exc
        os.close(reservation)
        reservation = -1
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        destination_cleanup_armed = False
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if reservation >= 0:
            os.close(reservation)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if destination_cleanup_armed:
            path.unlink(missing_ok=True)
            try:
                cleanup_directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(cleanup_directory_fd)
                finally:
                    os.close(cleanup_directory_fd)
            except OSError:
                pass


def verify(
    namespace: argparse.Namespace, *, runner: CommandRunner = _run_command
) -> dict[str, object]:
    inputs = _resolve_inputs(namespace)
    _require_exact_artifacts(inputs.artifacts)
    initial = _snapshot(inputs)
    _require_identity(inputs)
    lane_results: list[dict[str, object]] = []

    input_fingerprint = _input_fingerprint(initial)
    machine = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    with tempfile.TemporaryDirectory(prefix="z-release-home-") as temporary_home:
        environment = _hermetic_environment(Path(temporary_home))
        fast_commands = _lane_commands(inputs)
        _validate_lane_commands(fast_commands, inputs)
        slow_commands = _slow_lane_commands(inputs)
        _validate_slow_lane_commands(slow_commands, inputs)
        for phase, commands in (("fast", fast_commands), ("slow", slow_commands)):
            for lane_id, argv in commands:
                result = runner(argv, inputs.repo_root, environment)
                lane = {
                    "id": lane_id,
                    "phase": phase,
                    "argv": list(argv),
                    "platform": machine,
                    "input_fingerprint": input_fingerprint,
                    "exit_status": result.returncode,
                    "status": "passed" if result.returncode == 0 else "failed",
                    "stdout": _diagnostic(result.stdout or ""),
                    "stderr": _diagnostic(result.stderr or ""),
                }
                lane_results.append(lane)
                if result.returncode != 0:
                    raise VerificationError(f"{phase} lane failed: {lane_id}")
                if lane_id == "c3-prod-dependency-closure":
                    _validate_c3_output(result.stdout or "")
                _assert_unchanged(inputs, initial)

    _require_identity(inputs)
    _assert_unchanged(inputs, initial)
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "passed",
        "candidate_version": inputs.candidate_version,
        "candidate_sha": inputs.candidate_sha,
        "inputs": {
            "repo_root": str(inputs.repo_root),
            "candidate_root": str(inputs.candidate_root),
            "artifacts": str(inputs.artifacts),
            "candidate_fingerprint": initial.candidate_fingerprint,
            "artifacts_fingerprint": initial.artifacts_fingerprint,
            "host_evidence_root": str(inputs.host_evidence_root),
            "host_evidence_fingerprint": initial.host_evidence_fingerprint,
            "combined_fingerprint": input_fingerprint,
        },
        "git": {
            "initial_head": initial.head,
            "final_head": initial.head,
            "initial_status": initial.status,
            "final_status": initial.status,
            "initial_refs_fingerprint": initial.refs_fingerprint,
            "final_refs_fingerprint": initial.refs_fingerprint,
        },
        "lanes": lane_results,
    }
    payload["evidence_fingerprint"] = _sha256_bytes(_canonical_json(payload))
    _write_evidence(inputs.evidence_out, payload)
    return payload


def _exact_sha(value: str | None, label: str) -> str:
    if value is None or SHA_RE.fullmatch(value) is None:
        raise VerificationError(f"{label} must be exactly 40 lowercase hexadecimal characters")
    return value


def _plain_file(path_value: str | None, label: str, *, must_exist: bool = True) -> Path:
    if path_value is None:
        raise VerificationError(f"{label} is required")
    raw = Path(path_value)
    if raw.is_symlink():
        raise VerificationError(f"{label} must not be a symlink: {raw}")
    path = raw.resolve(strict=must_exist)
    if must_exist and not path.is_file():
        raise VerificationError(f"{label} is not a file: {path}")
    return path


def _plain_directory(path_value: str | None, label: str) -> Path:
    if path_value is None:
        raise VerificationError(f"{label} is required")
    raw = Path(path_value)
    if raw.is_symlink():
        raise VerificationError(f"{label} must not be a symlink: {raw}")
    path = raw.resolve(strict=True)
    if not path.is_dir():
        raise VerificationError(f"{label} is not a directory: {path}")
    return path


def _resolve_promotion_inputs(
    namespace: argparse.Namespace, *, require_authorization_out: bool
) -> PromotionInputs:
    source_sha = _exact_sha(namespace.source_sha, "reviewed source SHA")
    prod_sha = _exact_sha(namespace.prod_sha, "resulting prod SHA")
    repo_root = _plain_directory(namespace.repo_root, "main repository root")
    prod_root = _plain_directory(namespace.prod_root, "prod checkout root")
    candidate_root = _plain_directory(namespace.candidate_root, "candidate root")
    artifacts = _plain_directory(namespace.artifacts, "artifact directory")
    host_evidence_root = _plain_directory(namespace.host_evidence_root, "host evidence root")
    evidence = _plain_file(namespace.evidence, "candidate evidence")
    if repo_root == prod_root:
        raise VerificationError("main and prod must use separate exact checkouts")
    inputs = (repo_root, prod_root, candidate_root, artifacts, host_evidence_root)
    for index, left in enumerate(inputs):
        for right in inputs[index + 1 :]:
            if _is_relative_to(left, right) or _is_relative_to(right, left):
                raise VerificationError("promotion input roots must be separate")

    authorization_out: Path | None = None
    if require_authorization_out:
        authorization_out = _plain_file(
            namespace.authorization_out, "promotion authorization destination", must_exist=False
        )
        if authorization_out.exists() or authorization_out.is_symlink():
            raise VerificationError(
                f"promotion authorization destination already exists: {authorization_out}"
            )
        if not authorization_out.parent.is_dir():
            raise VerificationError(
                f"promotion authorization parent is not a directory: {authorization_out.parent}"
            )
        for root in inputs:
            if _is_relative_to(authorization_out, root) or _is_relative_to(root, authorization_out):
                raise VerificationError("promotion authorization destination overlaps an input")
    return PromotionInputs(
        source_sha,
        prod_sha,
        repo_root,
        prod_root,
        candidate_root,
        artifacts,
        host_evidence_root,
        evidence,
        authorization_out,
    )


def _require_clean_exact_checkout(
    root: Path,
    *,
    expected_sha: str,
    branch_ref: str,
    label: str,
    require_symbolic_head: bool = False,
) -> None:
    top = Path(_promotion_git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    if top != root:
        raise VerificationError(f"{label} root must be the exact Git top level")
    head = _promotion_git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if head != expected_sha:
        raise VerificationError(f"{label} HEAD does not match the explicit SHA")
    ref_sha = _promotion_git(root, "rev-parse", "--verify", f"{branch_ref}^{{commit}}").strip()
    if ref_sha != expected_sha:
        raise VerificationError(f"{branch_ref} does not match the explicit SHA")
    if require_symbolic_head:
        try:
            symbolic = _promotion_git(root, "symbolic-ref", "--quiet", "HEAD").strip()
        except VerificationError as exc:
            raise VerificationError(f"{label} must be checked out on {branch_ref}") from exc
        if symbolic != branch_ref:
            raise VerificationError(f"{label} must be checked out on {branch_ref}")
    if _promotion_git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise VerificationError(f"{label} checkout must be clean")


def _require_authoritative_remote_ref(
    root: Path, *, expected_sha: str, branch_ref: str, label: str
) -> None:
    """Require an independently fetched remote-tracking ref at the explicit SHA."""

    ref_sha = _promotion_git(
        root, "rev-parse", "--verify", f"{branch_ref}^{{commit}}"
    ).strip()
    if ref_sha != expected_sha:
        raise VerificationError(
            f"authoritative {label} {branch_ref} does not match the explicit SHA"
        )


def _promotion_refs_fingerprint(prod_root: Path) -> str:
    refs = _promotion_git(
        prod_root, "for-each-ref", "--format=%(refname)%00%(objectname)"
    )
    return _sha256_bytes(refs.encode("utf-8"))


def _promotion_diff(inputs: PromotionInputs) -> tuple[list[dict[str, str]], str]:
    raw = _promotion_git(
        inputs.repo_root,
        "diff",
        "--no-renames",
        "--name-status",
        "-z",
        inputs.source_sha,
        inputs.prod_sha,
    )
    tokens = raw.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    if len(tokens) % 2:
        raise VerificationError("promotion diff emitted malformed name-status data")
    changes: list[dict[str, str]] = []
    for index in range(0, len(tokens), 2):
        status, path = tokens[index], tokens[index + 1]
        if status not in {"A", "M", "D"} or not path:
            raise VerificationError("promotion diff contains an unsupported change type")
        if status != "D":
            if path_excluded_from_prod(path):
                raise VerificationError(f"promotion includes excluded experiment path: {path}")
            owner = prod_owner_for_path(path)
            if owner is None:
                raise VerificationError(f"promotion path is outside C1's positive inventory: {path}")
        else:
            owner = prod_owner_for_path(path) or "deleted"
        changes.append({"status": status, "path": path, "owner": owner})

    prod_paths = _promotion_git(
        inputs.prod_root, "ls-tree", "-r", "--name-only", "-z", inputs.prod_sha
    ).split("\0")
    excluded = sorted(path for path in prod_paths if path and path_excluded_from_prod(path))
    if excluded:
        raise VerificationError(f"resulting prod tree retains excluded experiment path: {excluded[0]}")
    return changes, _sha256_bytes(_canonical_json(changes))


def _validated_candidate_evidence(
    inputs: PromotionInputs, *, current_refs_fingerprint: str
) -> dict[str, object]:
    payload = _load_object(inputs.evidence, "candidate evidence")
    supplied_fingerprint = payload.get("evidence_fingerprint")
    unsigned = dict(payload)
    unsigned.pop("evidence_fingerprint", None)
    if supplied_fingerprint != _sha256_bytes(_canonical_json(unsigned)):
        raise VerificationError("candidate evidence fingerprint is invalid")
    if payload.get("schema_version") != 1 or payload.get("status") != "passed":
        raise VerificationError("candidate evidence is not an accepted passing record")
    if payload.get("candidate_sha") != inputs.prod_sha:
        raise VerificationError("candidate evidence is for a different prod SHA")
    try:
        candidate = parse_release_candidate(str(payload.get("candidate_version", "")))
    except ValueError as exc:
        raise VerificationError("candidate evidence has an invalid candidate version") from exc
    if payload.get("candidate_version") != candidate.plugin_version:
        raise VerificationError("candidate evidence version is not canonical")
    lanes = payload.get("lanes")
    expected_lanes = (*FAST_LANE_IDS, *SLOW_LANE_IDS)
    if not isinstance(lanes, list) or tuple(
        lane.get("id") if isinstance(lane, dict) else None for lane in lanes
    ) != expected_lanes:
        raise VerificationError("candidate evidence does not contain the complete 5 fast + 7 slow lanes")
    if any(
        lane.get("status") != "passed" or lane.get("exit_status") != 0
        for lane in lanes
        if isinstance(lane, dict)
    ):
        raise VerificationError("candidate evidence contains a non-passing lane")
    evidence_inputs = payload.get("inputs")
    if not isinstance(evidence_inputs, dict):
        raise VerificationError("candidate evidence inputs are malformed")
    current = {
        "repo_root": str(inputs.prod_root),
        "candidate_root": str(inputs.candidate_root),
        "artifacts": str(inputs.artifacts),
        "host_evidence_root": str(inputs.host_evidence_root),
        "candidate_fingerprint": _inventory(inputs.candidate_root)[0],
        "artifacts_fingerprint": _inventory(inputs.artifacts)[0],
        "host_evidence_fingerprint": _inventory(inputs.host_evidence_root)[0],
    }
    for key, value in current.items():
        if evidence_inputs.get(key) != value:
            raise VerificationError(f"candidate evidence has stale or different {key}")
    git_record = payload.get("git")
    if not isinstance(git_record, dict):
        raise VerificationError("candidate evidence Git record is malformed")
    if any(
        git_record.get(key) != current_refs_fingerprint
        for key in ("initial_refs_fingerprint", "final_refs_fingerprint")
    ):
        raise VerificationError("candidate evidence prod ref fingerprint is stale")
    combined = _sha256_bytes(
        _canonical_json(
            {
                "head": inputs.prod_sha,
                "refs": current_refs_fingerprint,
                "candidate": current["candidate_fingerprint"],
                "artifacts": current["artifacts_fingerprint"],
                "host_evidence": current["host_evidence_fingerprint"],
            }
        )
    )
    if evidence_inputs.get("combined_fingerprint") != combined:
        raise VerificationError("candidate evidence combined fingerprint is stale")
    if any(lane.get("input_fingerprint") != combined for lane in lanes):
        raise VerificationError("candidate evidence lane fingerprint is stale")
    if any(
        git_record.get(key) != inputs.prod_sha for key in ("initial_head", "final_head")
    ):
        raise VerificationError("candidate evidence Git identity is stale")
    if any(git_record.get(key) != "" for key in ("initial_status", "final_status")):
        raise VerificationError("candidate evidence was not captured from a clean prod checkout")
    return payload


def _canonical_evidence_version(inputs: PromotionInputs) -> str:
    """Read the signed identity needed to derive the one permissible new tag."""

    payload = _load_object(inputs.evidence, "candidate evidence")
    supplied_fingerprint = payload.get("evidence_fingerprint")
    unsigned = dict(payload)
    unsigned.pop("evidence_fingerprint", None)
    if supplied_fingerprint != _sha256_bytes(_canonical_json(unsigned)):
        raise VerificationError("candidate evidence fingerprint is invalid")
    if payload.get("candidate_sha") != inputs.prod_sha:
        raise VerificationError("candidate evidence is for a different prod SHA")
    try:
        candidate = parse_release_candidate(str(payload.get("candidate_version", "")))
    except ValueError as exc:
        raise VerificationError("candidate evidence has an invalid candidate version") from exc
    if payload.get("candidate_version") != candidate.plugin_version:
        raise VerificationError("candidate evidence version is not canonical")
    return candidate.plugin_version


def _promotion_payload(inputs: PromotionInputs) -> dict[str, object]:
    _require_clean_exact_checkout(
        inputs.repo_root,
        expected_sha=inputs.source_sha,
        branch_ref="refs/heads/main",
        label="main source",
        require_symbolic_head=True,
    )
    _require_clean_exact_checkout(
        inputs.prod_root,
        expected_sha=inputs.prod_sha,
        branch_ref="refs/heads/prod",
        label="prod result",
    )
    _require_authoritative_remote_ref(
        inputs.repo_root,
        expected_sha=inputs.source_sha,
        branch_ref="refs/remotes/origin/main",
        label="main source",
    )
    _require_authoritative_remote_ref(
        inputs.prod_root,
        expected_sha=inputs.prod_sha,
        branch_ref="refs/remotes/origin/prod",
        label="prod result",
    )
    validate_release_contract(release_contract())
    changes, diff_fingerprint = _promotion_diff(inputs)
    candidate_version = _canonical_evidence_version(inputs)
    expected_tag = f"v{candidate_version}"
    tag_ref = f"refs/tags/{expected_tag}"
    if _promotion_git(
        inputs.prod_root,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
        tag_ref,
    ):
        raise VerificationError(f"expected release tag already exists: {tag_ref}")
    prod_refs_fingerprint = _promotion_refs_fingerprint(inputs.prod_root)
    evidence = _validated_candidate_evidence(
        inputs, current_refs_fingerprint=prod_refs_fingerprint
    )
    evidence_inputs = evidence["inputs"]
    if not isinstance(evidence_inputs, dict):
        raise VerificationError("candidate evidence inputs are malformed")
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "authorized",
        "source_sha": inputs.source_sha,
        "prod_sha": inputs.prod_sha,
        "authoritative_refs": {
            "main": "refs/remotes/origin/main",
            "prod": "refs/remotes/origin/prod",
        },
        "candidate_version": candidate_version,
        "expected_tag": expected_tag,
        "expected_tag_absent": True,
        "inputs": {
            "repo_root": str(inputs.repo_root),
            "prod_root": str(inputs.prod_root),
            "candidate_root": str(inputs.candidate_root),
            "artifacts": str(inputs.artifacts),
            "host_evidence_root": str(inputs.host_evidence_root),
            "candidate_fingerprint": evidence_inputs["candidate_fingerprint"],
            "artifacts_fingerprint": evidence_inputs["artifacts_fingerprint"],
            "host_evidence_fingerprint": evidence_inputs["host_evidence_fingerprint"],
            "combined_fingerprint": evidence_inputs["combined_fingerprint"],
        },
        "release_contract_fingerprint": _sha256_bytes(_canonical_json(release_contract())),
        "prod_refs_fingerprint": prod_refs_fingerprint,
        "diff": changes,
        "diff_fingerprint": diff_fingerprint,
        "candidate_evidence_fingerprint": evidence["evidence_fingerprint"],
        "verified_lane_ids": [*FAST_LANE_IDS, *SLOW_LANE_IDS],
    }
    # Close the preflight time-of-check/time-of-use window before authorizing.
    _require_clean_exact_checkout(
        inputs.repo_root,
        expected_sha=inputs.source_sha,
        branch_ref="refs/heads/main",
        label="main source",
        require_symbolic_head=True,
    )
    _require_clean_exact_checkout(
        inputs.prod_root,
        expected_sha=inputs.prod_sha,
        branch_ref="refs/heads/prod",
        label="prod result",
    )
    _require_authoritative_remote_ref(
        inputs.repo_root,
        expected_sha=inputs.source_sha,
        branch_ref="refs/remotes/origin/main",
        label="main source",
    )
    _require_authoritative_remote_ref(
        inputs.prod_root,
        expected_sha=inputs.prod_sha,
        branch_ref="refs/remotes/origin/prod",
        label="prod result",
    )
    final_changes, final_diff_fingerprint = _promotion_diff(inputs)
    final_prod_refs_fingerprint = _promotion_refs_fingerprint(inputs.prod_root)
    final_evidence = _validated_candidate_evidence(
        inputs, current_refs_fingerprint=final_prod_refs_fingerprint
    )
    if _promotion_git(
        inputs.prod_root,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
        tag_ref,
    ):
        raise VerificationError(f"expected release tag appeared during preflight: {tag_ref}")
    if final_changes != changes or final_diff_fingerprint != diff_fingerprint:
        raise VerificationError("promotion diff changed during preflight")
    if final_evidence.get("evidence_fingerprint") != evidence.get("evidence_fingerprint"):
        raise VerificationError("candidate evidence changed during preflight")
    if final_prod_refs_fingerprint != prod_refs_fingerprint:
        raise VerificationError("prod refs changed during preflight")
    payload["authorization_fingerprint"] = _sha256_bytes(_canonical_json(payload))
    return payload


def promotion_preflight(namespace: argparse.Namespace) -> dict[str, object]:
    inputs = _resolve_promotion_inputs(namespace, require_authorization_out=True)
    payload = _promotion_payload(inputs)
    if inputs.authorization_out is None:
        raise VerificationError("promotion authorization destination is required")
    _write_evidence(inputs.authorization_out, payload)
    return payload


def publication_freshness(namespace: argparse.Namespace) -> dict[str, object]:
    inputs = _resolve_promotion_inputs(namespace, require_authorization_out=False)
    authorization_path = _plain_file(namespace.authorization, "promotion authorization")
    authorization = _load_object(authorization_path, "promotion authorization")
    supplied_fingerprint = authorization.get("authorization_fingerprint")
    unsigned = dict(authorization)
    unsigned.pop("authorization_fingerprint", None)
    if supplied_fingerprint != _sha256_bytes(_canonical_json(unsigned)):
        raise VerificationError("promotion authorization fingerprint is invalid")
    current = _promotion_payload(inputs)
    if authorization != current:
        raise VerificationError("promotion authorization is stale for current refs, diff, or evidence")
    return current


def publication_assets(namespace: argparse.Namespace) -> dict[str, str]:
    """Emit exact, validated publication names for GitHub Actions."""

    try:
        candidate = parse_release_candidate(namespace.candidate_version)
    except ValueError as exc:
        raise VerificationError(str(exc)) from exc
    if namespace.candidate_version != candidate.plugin_version:
        raise VerificationError("candidate version must use canonical plugin spelling")
    artifacts = _plain_directory(namespace.artifacts, "artifact directory")
    verify_release_artifacts(artifacts, candidate.plugin_version)
    wheels = sorted(path for path in artifacts.iterdir() if path.name.endswith(".whl"))
    tarballs = sorted(
        path
        for path in artifacts.iterdir()
        if path.name.startswith("z-harness-") and path.name.endswith(".tar.gz")
    )
    if len(wheels) != 1 or len(tarballs) != 1:
        raise VerificationError("validated publication requires exactly one wheel and tarball")
    safe_name = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
    for path in (*wheels, *tarballs):
        if safe_name.fullmatch(path.name) is None:
            raise VerificationError(f"publication artifact has unsafe basename: {path.name}")
    output = _plain_file(namespace.github_output, "GitHub output file")
    values = {
        "wheel": str(wheels[0]),
        "tarball": str(tarballs[0]),
        "tag": f"v{candidate.plugin_version}",
    }
    with output.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return values


class _ModeArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        common = (
            "candidate_root",
            "artifacts",
            "host_evidence_root",
        )
        required = {
            "verify": (
                "candidate_version",
                "candidate_sha",
                "repo_root",
                *common,
                "evidence_out",
            ),
            "promotion-preflight": (
                "source_sha",
                "prod_sha",
                "repo_root",
                "prod_root",
                *common,
                "evidence",
                "authorization_out",
            ),
            "publication-freshness": (
                "source_sha",
                "prod_sha",
                "repo_root",
                "prod_root",
                *common,
                "evidence",
                "authorization",
            ),
            "publication-assets": (
                "candidate_version",
                "artifacts",
                "github_output",
            ),
        }[parsed.mode]
        missing = [f"--{name.replace('_', '-')}" for name in required if getattr(parsed, name) is None]
        if missing:
            self.error(f"mode {parsed.mode} requires: {' '.join(missing)}")
        return parsed


def _parser() -> argparse.ArgumentParser:
    parser = _ModeArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("verify", "promotion-preflight", "publication-freshness", "publication-assets"),
        default="verify",
    )
    parser.add_argument("--candidate-version")
    parser.add_argument("--candidate-sha")
    parser.add_argument("--source-sha")
    parser.add_argument("--prod-sha")
    parser.add_argument("--repo-root")
    parser.add_argument("--prod-root")
    parser.add_argument("--candidate-root")
    parser.add_argument("--artifacts")
    parser.add_argument("--host-evidence-root")
    parser.add_argument("--evidence-out")
    parser.add_argument("--evidence")
    parser.add_argument("--authorization-out")
    parser.add_argument("--authorization")
    parser.add_argument("--github-output")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        namespace = _parser().parse_args(argv)
        if namespace.mode == "verify":
            verify(namespace)
        elif namespace.mode == "promotion-preflight":
            promotion_preflight(namespace)
        elif namespace.mode == "publication-freshness":
            publication_freshness(namespace)
        else:
            publication_assets(namespace)
    except (OSError, VerificationError, ValueError) as exc:
        print(f"release-candidate-verify: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
