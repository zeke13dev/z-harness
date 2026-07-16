"""Planning-skill ingress for future watchdog supervision.

The planning run writes one normalized, versioned manifest for a later
integration to consume. It never enrolls the session producing that artifact:
the authoritative watchdog mutation seam is passed through the production
path solely so contract tests can observe that it receives zero calls.

Public surface:
- ``persist_supervision_manifest`` atomically writes the selected manifest.
- ``begin_choice_wait`` and ``complete_choice`` own shared gate mechanics.
- ``main`` provides the small CLI invoked by ``/z-plan`` and ``/z-plan-split``.

Concurrency (STYLE.md:P-006): writes use a same-directory temporary file plus
``os.replace`` so readers see either the previous complete manifest or the new
complete manifest, never a partial document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from runtime.watchdog import registry as watchdog_registry


MANIFEST_SCHEMA_VERSION = 1
VALID_CHOICES = frozenset({"off", "supervised"})
MANIFEST_NAME = "supervision-manifest.json"
WAIT_TOKEN_PREFIX = ".supervision-wait."
_WAIT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{24}$")
_VALID_SOURCES = frozenset({"/z-plan", "/z-plan-split"})

LockedRegistryMutation = Callable[
    [Path | str, Callable[[dict[str, object]], None]], dict[str, object]
]


def _wait_token_path(plan_dir: Path | str, run_id: str, phase: str, token: str) -> Path:
    """Return the context-bound path for one opaque wait token."""
    context = hashlib.sha256(f"{run_id}\0{phase}".encode()).hexdigest()[:16]
    return Path(plan_dir) / f"{WAIT_TOKEN_PREFIX}{context}.{token}.json"


def _manifest_for(choice: str) -> dict[str, object]:
    """Build the normalized manifest for ``choice``.

    Args:
        choice: ``off`` or ``supervised``.

    Returns:
        The versioned manifest. Both choices have the same schema and differ
        only in the ``enabled`` value.

    Raises:
        ValueError: if ``choice`` is not one of ``VALID_CHOICES``.
    """
    if choice not in VALID_CHOICES:
        raise ValueError(f"unknown supervision choice: {choice!r}")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": "watchdog-supervision",
        "enabled": choice == "supervised",
        "current_planning_session": "excluded",
        "topology": {
            "kind": "coordinator_fanout",
            "child_admission": "approved_policy_only",
            "join": "sealed_group",
        },
        "reconciliation": {"owner": "coordinator", "on_ambiguity": "pause"},
    }


def load_opt_in_manifest(path: Path | str) -> dict[str, object]:
    """Load and validate one normalized, enabled supervision manifest.

    Args:
        path: Manifest written by ``persist_supervision_manifest``.

    Returns:
        The validated manifest object.

    Raises:
        ValueError: if JSON is malformed or the payload is not a normalized
            opt-in shape with an approved child-admission policy.
        OSError: if the manifest cannot be read.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed supervision manifest JSON: {exc}") from exc
    expected = _manifest_for("supervised")
    allowed_admission = {"approved_policy_only", "locked_dynamic"}
    if not isinstance(payload, dict):
        raise ValueError("manifest is not the normalized opt-in supervision payload")
    topology = payload.get("topology")
    admission = topology.get("child_admission") if isinstance(topology, dict) else None
    normalized = dict(payload)
    if isinstance(topology, dict):
        normalized["topology"] = {
            **topology,
            "child_admission": "approved_policy_only",
        }
    if admission not in allowed_admission or normalized != expected:
        raise ValueError("manifest is not the normalized opt-in supervision payload")
    return payload


def _atomic_write_manifest(path: Path, manifest: dict[str, object]) -> None:
    """Atomically write normalized compact JSON to ``path``. Hard-fail.

    Args:
        path: Destination manifest path.
        manifest: JSON-serializable normalized manifest.

    Raises:
        OSError: if the directory, temporary write, fsync, or replacement fails.
        TypeError: if ``manifest`` is not JSON serializable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        replaced = True
    finally:
        if not replaced:
            try:
                temp_path.unlink()
            except OSError:
                pass


def persist_supervision_manifest(
    plan_dir: Path | str,
    choice: str,
    *,
    locked_registry_mutation: LockedRegistryMutation | None = None,
) -> Path:
    """Persist a planning choice without enrolling its producing session.

    Args:
        plan_dir: Managed z-harness plan directory.
        choice: ``off`` or ``supervised``.
        locked_registry_mutation: Authoritative watchdog document-mutation
            seam. It is resolved in this production path but intentionally
            receives zero calls because planning-session enrollment is
            prohibited for both choices.

    Returns:
        The written manifest path.

    Raises:
        ValueError: if ``choice`` is invalid.
        OSError: if atomic persistence fails.
    """
    mutation_seam = (
        locked_registry_mutation
        if locked_registry_mutation is not None
        else watchdog_registry.locked_registry_document_update
    )
    # Keep the authoritative capability attached to this production boundary:
    # a later consumer can enroll only by making an explicit mutation here.
    # This producer's frozen contract deliberately makes no such call.
    del mutation_seam

    manifest_path = Path(plan_dir) / MANIFEST_NAME
    _atomic_write_manifest(manifest_path, _manifest_for(choice))
    return manifest_path


def begin_choice_wait(plan_dir: Path | str, run_id: str, phase: str) -> str:
    """Create a one-use wait token and emit the matching start event.

    Args:
        plan_dir: Managed z-harness plan directory.
        run_id: Current z-harness run identifier.
        phase: Non-secret skill phase label.

    Returns:
        An opaque one-use token, or an empty string when telemetry setup fails.
    """
    token = secrets.token_urlsafe(18)
    token_path = _wait_token_path(plan_dir, run_id, phase, token)
    _atomic_write_manifest(
        token_path,
        {
            "token": token,
            "run_id": run_id,
            "phase": phase,
            "started_ms": time.monotonic_ns() // 1_000_000,
        },
    )
    emitted = _emit_event(
        run_id,
        "user_wait_start",
        {"phase": phase, "reason": "supervision_topology_choice"},
    )
    if emitted:
        return token
    try:
        token_path.unlink()
    except OSError:
        pass
    return ""


def _consume_wait_token(
    plan_dir: Path | str,
    run_id: str,
    phase: str,
    token: str,
) -> int | None:
    """Consume a matching begin-wait token and return its start time."""
    if not _WAIT_TOKEN_RE.fullmatch(token):
        return None
    token_path = _wait_token_path(plan_dir, run_id, phase, token)
    claimed_path = token_path.with_name(f"{token_path.name}.{secrets.token_hex(8)}.claim")
    try:
        os.rename(token_path, claimed_path)
    except OSError:
        return None
    try:
        payload = json.loads(claimed_path.read_text(encoding="utf-8"))
        if (
            payload.get("token") != token
            or payload.get("run_id") != run_id
            or payload.get("phase") != phase
            or not isinstance(payload.get("started_ms"), int)
        ):
            return None
        return payload["started_ms"]
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    finally:
        try:
            claimed_path.unlink()
        except OSError:
            pass


def complete_choice(
    plan_dir: Path | str,
    run_id: str,
    source: str,
    phase: str,
    choice: str,
    wait_token: str = "",
    *,
    locked_registry_mutation: LockedRegistryMutation | None = None,
) -> tuple[str, Path]:
    """Normalize, record, and persist one supervision choice. Hard-fail on persistence only.

    Telemetry is best-effort and never prevents the manifest write. Empty,
    failed, or malformed interactive answers normalize to the default ``off``.

    Args:
        plan_dir: Managed z-harness plan directory.
        run_id: Current z-harness run identifier.
        source: Owning skill, ``/z-plan`` or ``/z-plan-split``.
        phase: Non-secret skill phase label.
        choice: Raw answer token or displayed option.
        wait_token: Opaque token from ``begin_choice_wait``. Empty means the
            unattended/no-ask path did not wait.
        locked_registry_mutation: Watchdog mutation seam retained for the
            non-enrollment contract.

    Returns:
        The normalized choice and written manifest path.

    Raises:
        ValueError: if ``source`` is not a supported planning skill.
        OSError: if atomic persistence fails.
    """
    if source not in _VALID_SOURCES:
        raise ValueError(f"unknown planning source: {source!r}")
    normalized = choice.split(" — ", 1)[0] if choice else "off"
    if normalized not in VALID_CHOICES:
        normalized = "off"

    wait_start_ms = _consume_wait_token(plan_dir, run_id, phase, wait_token)
    if wait_token and wait_start_ms is None:
        raise ValueError("invalid or consumed supervision wait token")
    if wait_start_ms is not None:
        wall_ms = max(0, time.monotonic_ns() // 1_000_000 - wait_start_ms)
        _emit_event(
            run_id,
            "user_wait_end",
            {
                "phase": phase,
                "reason": "supervision_topology_choice",
                "wall_ms": wall_ms,
            },
        )
    _emit_decision(run_id, normalized, source)
    path = persist_supervision_manifest(
        plan_dir,
        normalized,
        locked_registry_mutation=locked_registry_mutation,
    )
    return normalized, path


def _emit_event(run_id: str, kind: str, payload: dict[str, object]) -> bool:
    """Best-effort emit one non-secret structured event."""
    command = [
        "bash",
        str(Path(__file__).resolve().parents[2] / "scripts" / "log-event.sh"),
        run_id,
        kind,
        json.dumps(payload, separators=(",", ":")),
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError:
        return False
    return result.returncode == 0


def _emit_decision(run_id: str, choice: str, source: str) -> None:
    """Best-effort emit the normalized choice decision; never raises."""
    command = [
        "bash",
        str(Path(__file__).resolve().parents[2] / "scripts" / "log-decision.sh"),
        run_id,
        "supervision_topology",
        choice,
        "--options",
        '["off","supervised"]',
        "--tentative",
        "off",
        "--source",
        source,
    ]
    try:
        subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError:
        return


def main(argv: list[str] | None = None) -> int:
    """Run the planning-ingress CLI.

    Args:
        argv: Optional argument vector for tests; defaults to ``sys.argv``.

    Returns:
        Process exit code 0 after successful persistence.
    """
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    begin_parser = subparsers.add_parser("begin-wait")
    begin_parser.add_argument("--plan-dir", type=Path, required=True)
    begin_parser.add_argument("--run", required=True)
    begin_parser.add_argument("--phase", required=True)
    complete_parser = subparsers.add_parser("complete")
    complete_parser.add_argument("--plan-dir", type=Path, required=True)
    complete_parser.add_argument("--run", required=True)
    complete_parser.add_argument("--source", choices=sorted(_VALID_SOURCES), required=True)
    complete_parser.add_argument("--phase", required=True)
    complete_parser.add_argument("--choice", default="off")
    complete_parser.add_argument("--wait-token", default="")
    args = parser.parse_args(argv)
    if args.command == "begin-wait":
        print(begin_choice_wait(args.plan_dir, args.run, args.phase))
        return 0
    choice, path = complete_choice(
        args.plan_dir,
        args.run,
        args.source,
        args.phase,
        args.choice,
        args.wait_token,
    )
    print(json.dumps({"choice": choice, "manifest_path": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
