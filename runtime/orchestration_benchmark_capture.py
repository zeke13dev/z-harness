"""Host-owned, fail-closed capture for the T012 orchestration benchmark.

The runner executes a frozen nine-node, read-only graph in five alternating
Claude/Codex pairs.  Every model process owns a fresh OS process group.  The
parent continuously enforces the wall deadline and rejects tool use. Native
turn, token, input, and dollar counters exposed only in terminal JSON are
truthfully terminal-verified rather than described as preemptively enforced.

Only derived counters and immutable fingerprints are persisted; model text is
never written to the evidence artifacts.  The public surface is ``main``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, IO

from runtime.orchestration_benchmark import analyze_manifest


_EXPECTED_VERSIONS = {
    "node": "v24.14.0",
    "codex": "codex-cli 0.142.5",
    "claude": "2.1.217 (Claude Code)",
}
_EXPECTED_EXECUTABLE_SHA256 = {
    "node": "20a18709f0154d668f1bd6f6ea8c2a7ae001447b4b2c339732f22e57a8767a55",
    "codex_js": "d3be844c45c4fd89392536e56e1010963f94785592596b50cd0c45bb8a341406",
    "claude": "5840c777fd47115e9ca276e165563c6e121e7c7e2b4d86598e0025f8cc37de56",
}
_OUTPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "temp"
    / "orchestration-benchmark"
    / "codex-z-harness-token-efficiency-root-fix"
)
_ENFORCER_ID = "host_process_group_terminal_verified_v2"
_PROJECTION_ID = "privacy_safe_publication_v1"
_PAIR_COUNT = 5
_NODES = (
    "scope",
    "premise",
    "invariants",
    "implementation",
    "tests",
    "telemetry",
    "security",
    "review",
    "settlement",
)
_EDGES = tuple(zip(_NODES, _NODES[1:]))
_CLAUDE_BUDGET_USD = 0.04
_CLAUDE_AGGREGATE_USD = 2.00
_TOOL_ITEM_TYPES = frozenset(
    {"command_execution", "mcp_tool_call", "computer_tool_use", "tool_use", "tool_result"}
)


class CaptureRejected(RuntimeError):
    """Raised after a model process is killed and reaped for unsafe evidence."""


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved executable inputs admitted by the capture preflight."""

    node: Path
    codex_js: Path
    claude: Path


@dataclass(frozen=True)
class Limits:
    """Per-process externally enforced ceilings."""

    wall_seconds: float = 90.0
    supervisor_turns: int = 1
    root_input_tokens: int = 40_000
    native_total_tokens: int = 50_000
    dollars: float | None = None


@dataclass
class Observation:
    """Privacy-safe counters derived from one native JSON stream."""

    supervisor_turns: int = 0
    root_input_tokens: int = 0
    native_total_tokens: int = 0
    output_tokens: int = 0
    dollars: float = 0.0
    native_events: int = 0
    saw_terminal: bool = False
    quality_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProcessResult:
    """Settled output of one independently capped process."""

    observation: Observation
    wall_seconds: float
    exit_code: int
    pgid: int
    killed: bool
    kill_reason: str | None
    stderr_sha256: str
    verified_logical_node_ids: tuple[str, ...]


def _canonical_hash(value: Any) -> str:
    """Return a deterministic SHA-256 digest; serialization errors hard-fail."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _file_hash(path: str) -> str:
    """Hash an immutable executable input; filesystem failures hard-fail."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _discover_runtime_paths(
    *,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> RuntimePaths:
    """Resolve the frozen runtime shape without persisting machine-local paths.

    Args:
        home: Home directory used to locate the bundled Codex runtime.
        which: PATH lookup seam for CLI launchers.

    Returns:
        Canonical executable paths for the exact version preflight.

    Raises:
        CaptureRejected: If any required executable is absent, non-file, or
            not executable where direct execution is required.
    """
    runtime_home = home if home is not None else Path.home()
    node = (
        runtime_home
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node"
    )
    codex_launcher = which("codex")
    claude_launcher = which("claude")
    if codex_launcher is None or claude_launcher is None:
        missing = "codex" if codex_launcher is None else "claude"
        raise CaptureRejected(f"{missing} executable is not available on PATH")
    codex_js = Path(codex_launcher).resolve()
    claude = Path(claude_launcher).resolve()
    requirements = (
        ("node", node, True),
        ("codex", codex_js, False),
        ("claude", claude, True),
    )
    for name, path, requires_execute in requirements:
        if not path.is_file() or (requires_execute and not os.access(path, os.X_OK)):
            raise CaptureRejected(f"{name} executable input failed preflight")
    if tuple(codex_js.parts[-5:]) != ("node_modules", "@openai", "codex", "bin", "codex.js"):
        raise CaptureRejected("codex executable input has an unexpected installation identity")
    paths = RuntimePaths(node=node.resolve(), codex_js=codex_js, claude=claude)
    observed_hashes = {
        "node": _file_hash(str(paths.node)),
        "codex_js": _file_hash(str(paths.codex_js)),
        "claude": _file_hash(str(paths.claude)),
    }
    if observed_hashes != _EXPECTED_EXECUTABLE_SHA256:
        raise CaptureRejected("runtime executable fingerprint does not match the frozen allowlist")
    return paths


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Durably replace one JSON artifact; filesystem failures hard-fail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _prompt(node_ids: tuple[str, ...]) -> str:
    """Build the frozen content-free work prompt; this helper cannot fail."""
    rows = "\n".join(f"- {node}: return exactly {node}=settled" for node in node_ids)
    return (
        "You are executing a deterministic read-only orchestration benchmark. "
        "Do not use tools, inspect files, delegate, or add commentary. Complete "
        "each listed logical node independently and return the requested lines in order.\n"
        f"{rows}\n"
    )


def _usage_total(usage: dict[str, Any], *, claude: bool) -> tuple[int, int, int]:
    """Derive native root, output, and total tokens; malformed values reject."""
    keys = (
        ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        if claude
        else ("input_tokens",)
    )
    try:
        root = sum(int(usage.get(key, 0)) for key in keys)
        output = int(usage.get("output_tokens", 0))
    except (TypeError, ValueError) as exc:
        raise CaptureRejected("native usage contains a non-integer counter") from exc
    if root < 0 or output < 0:
        raise CaptureRejected("native usage contains a negative counter")
    return root, output, root + output


def _parse_codex(event: dict[str, Any], observed: Observation) -> str | None:
    """Update counters from one Codex JSONL event; unknown structure rejects."""
    observed.native_events += 1
    event_type = event.get("type")
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") in _TOOL_ITEM_TYPES:
        raise CaptureRejected(f"codex attempted forbidden tool item {item.get('type')}")
    completion_text = (
        item.get("text")
        if isinstance(item, dict) and item.get("type") == "agent_message"
        else None
    )
    if completion_text is not None and not isinstance(completion_text, str):
        raise CaptureRejected("codex agent message is not text")
    if event_type == "turn.completed":
        usage = event.get("usage")
        if not isinstance(usage, dict):
            raise CaptureRejected("codex terminal event has no native usage")
        root, output, total = _usage_total(usage, claude=False)
        observed.supervisor_turns += 1
        observed.root_input_tokens += root
        observed.output_tokens += output
        observed.native_total_tokens += total
        observed.saw_terminal = True
    elif event_type == "turn.failed":
        raise CaptureRejected("codex reported turn.failed")
    return completion_text


def _parse_claude(event: dict[str, Any], observed: Observation) -> str | None:
    """Update counters from one Claude stream event; terminal usage is canonical."""
    observed.native_events += 1
    event_type = event.get("type")
    if event_type == "assistant":
        message = event.get("message")
        if isinstance(message, dict):
            content = message.get("content", [])
            if isinstance(content, list) and any(
                isinstance(block, dict) and block.get("type") == "tool_use" for block in content
            ):
                raise CaptureRejected("claude attempted forbidden tool use")
    if event_type != "result":
        return None
    if event.get("is_error") is True:
        raise CaptureRejected("claude reported an error result")
    usage = event.get("usage")
    if not isinstance(usage, dict):
        raise CaptureRejected("claude terminal event has no native usage")
    root, output, total = _usage_total(usage, claude=True)
    try:
        turns = int(event["num_turns"])
        dollars = float(event["total_cost_usd"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CaptureRejected("claude terminal counters are incomplete") from exc
    if turns < 0 or dollars < 0:
        raise CaptureRejected("claude terminal counters are negative")
    observed.supervisor_turns = turns
    observed.root_input_tokens = root
    observed.output_tokens = output
    observed.native_total_tokens = total
    observed.dollars = dollars
    observed.saw_terminal = True
    completion_text = event.get("result")
    if not isinstance(completion_text, str):
        raise CaptureRejected("claude terminal result has no completion text")
    return completion_text


def _verified_markers(texts: list[str], expected_nodes: tuple[str, ...]) -> tuple[str, ...]:
    """Validate content in memory and return only content-free node identities."""
    counts = {node: 0 for node in expected_nodes}
    for text in texts:
        for line in text.splitlines():
            if "=" not in line:
                continue
            node, value = line.split("=", 1)
            if node not in counts or value != "settled":
                raise CaptureRejected("model emitted an unexpected logical completion marker")
            counts[node] += 1
    if any(count != 1 for count in counts.values()):
        raise CaptureRejected("model emitted missing or duplicate logical completion markers")
    return expected_nodes


def _breach(observed: Observation, limits: Limits) -> str | None:
    """Return the first breached cap, or ``None``; this helper cannot fail."""
    checks = (
        (observed.supervisor_turns > limits.supervisor_turns, "supervisor_turns"),
        (observed.root_input_tokens > limits.root_input_tokens, "root_input_tokens"),
        (observed.native_total_tokens > limits.native_total_tokens, "native_total_tokens"),
        (limits.dollars is not None and observed.dollars > limits.dollars, "dollars"),
    )
    return next((name for breached, name in checks if breached), None)


def _kill_and_reap(process: subprocess.Popen[str], grace_seconds: float = 2.0) -> None:
    """Terminate and reap a complete process group; OS failures hard-fail."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _run_process(
    argv: list[str],
    prompt: str,
    limits: Limits,
    parser: Callable[[dict[str, Any], Observation], str | None],
    *,
    expected_nodes: tuple[str, ...],
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    monotonic: Callable[[], float] = time.monotonic,
    read: Callable[[int, int], bytes] = os.read,
    set_blocking: Callable[[int, bool], None] = os.set_blocking,
) -> ProcessResult:
    """Run, continuously monitor, kill on breach, and always reap one process.

    Args:
        argv: Exact executable argument vector.
        prompt: Frozen prompt delivered over stdin.
        limits: Per-process ceilings.
        parser: Native JSON event reducer.
        expected_nodes: Logical completion markers required exactly once.
        popen_factory: Test seam for a subprocess-compatible constructor.
        monotonic: Test seam for a monotonic clock.
        read: Nonblocking byte-read seam.
        set_blocking: File-descriptor mode seam.

    Returns:
        Settled privacy-safe counters and process evidence.

    Raises:
        CaptureRejected: On malformed output, cap breach, timeout, tool use,
            process-group failure, nonzero exit, or missing terminal evidence.
        OSError: If the process cannot be launched or monitored.
    """
    process = popen_factory(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
        start_new_session=True,
        cwd="/tmp",
    )
    selector: selectors.BaseSelector | None = None
    reaped = False
    try:
        if process.stdout is None or process.stderr is None or process.stdin is None:
            raise CaptureRejected("capture pipes were not created")
        if os.getpgid(process.pid) != process.pid:
            raise CaptureRejected("model process does not own an isolated process group")
        process.stdin.write(prompt.encode())
        process.stdin.close()
        selector = selectors.DefaultSelector()
        streams = {"stdout": process.stdout, "stderr": process.stderr}
        buffers = {name: bytearray() for name in streams}
        for name, stream in streams.items():
            descriptor = stream.fileno()
            set_blocking(descriptor, False)
            selector.register(stream, selectors.EVENT_READ, name)
        observed = Observation()
        completion_texts: list[str] = []
        stderr = hashlib.sha256()
        started = monotonic()

        def consume_stdout(line: bytes) -> None:
            try:
                decoded = line.decode("utf-8")
                event = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CaptureRejected("native stdout contains non-JSON output") from exc
            if not isinstance(event, dict):
                raise CaptureRejected("native stdout event is not an object")
            completion = parser(event, observed)
            if completion is not None:
                completion_texts.append(completion)
            breach = _breach(observed, limits)
            if breach is not None:
                raise CaptureRejected(f"process terminal evidence breached {breach} ceiling")

        while selector.get_map():
            elapsed = monotonic() - started
            if elapsed > limits.wall_seconds:
                raise CaptureRejected("process breached wall_seconds ceiling")
            events = selector.select(timeout=min(0.1, limits.wall_seconds - elapsed))
            for key, _ in events:
                stream = key.fileobj
                try:
                    chunk = read(stream.fileno(), 65_536)
                except BlockingIOError:
                    continue
                if chunk == b"":
                    remaining = bytes(buffers[key.data])
                    if key.data == "stdout" and remaining.strip():
                        consume_stdout(remaining)
                    elif key.data == "stderr":
                        stderr.update(remaining)
                    selector.unregister(stream)
                    continue
                if key.data == "stderr":
                    stderr.update(chunk)
                    continue
                buffers["stdout"].extend(chunk)
                while b"\n" in buffers["stdout"]:
                    line, _, remainder = buffers["stdout"].partition(b"\n")
                    buffers["stdout"] = bytearray(remainder)
                    if line.strip():
                        consume_stdout(line)
        exit_code = process.wait()
        wall_seconds = monotonic() - started
        if exit_code != 0:
            raise CaptureRejected(f"model process exited {exit_code}")
        if not observed.saw_terminal:
            raise CaptureRejected("model process emitted no terminal native usage")
        verified_nodes = _verified_markers(completion_texts, expected_nodes)
        reaped = True
        return ProcessResult(
            observation=observed,
            wall_seconds=wall_seconds,
            exit_code=exit_code,
            pgid=process.pid,
            killed=False,
            kill_reason=None,
            stderr_sha256=stderr.hexdigest(),
            verified_logical_node_ids=verified_nodes,
        )
    finally:
        try:
            if selector is not None:
                selector.close()
        finally:
            if not reaped:
                _kill_and_reap(process)


def _versions(paths: RuntimePaths) -> dict[str, str]:
    """Verify exact runtime versions; mismatch or command failure hard-fails."""
    commands = {
        "node": [str(paths.node), "--version"],
        "codex": [str(paths.node), str(paths.codex_js), "--version"],
        "claude": [str(paths.claude), "--version"],
    }
    observed: dict[str, str] = {}
    for name, argv in commands.items():
        value = subprocess.run(argv, check=True, capture_output=True, text=True).stdout.strip()
        if value != _EXPECTED_VERSIONS[name]:
            raise CaptureRejected(f"{name} version {value!r} does not match frozen version")
        observed[name] = value
    return observed


def _codex_argv(paths: RuntimePaths) -> list[str]:
    """Return the frozen Codex invocation; this helper cannot fail."""
    return [
        str(paths.node),
        str(paths.codex_js),
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-C",
        "/tmp",
        "-",
    ]


def _claude_argv(paths: RuntimePaths) -> list[str]:
    """Return the frozen Claude invocation with provider dollar enforcement."""
    return [
        str(paths.claude),
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--safe-mode",
        "--tools",
        "",
        "--max-budget-usd",
        f"{_CLAUDE_BUDGET_USD:.2f}",
        "--model",
        "sonnet",
        "--effort",
        "low",
    ]


def _combine(results: list[ProcessResult]) -> Observation:
    """Add independent native process counters; an empty set hard-fails."""
    if not results:
        raise CaptureRejected("cannot combine an empty arm")
    return Observation(
        supervisor_turns=sum(result.observation.supervisor_turns for result in results),
        root_input_tokens=sum(result.observation.root_input_tokens for result in results),
        native_total_tokens=sum(result.observation.native_total_tokens for result in results),
        output_tokens=sum(result.observation.output_tokens for result in results),
        dollars=sum(result.observation.dollars for result in results),
        native_events=sum(result.observation.native_events for result in results),
        saw_terminal=all(result.observation.saw_terminal for result in results),
    )


def _manifest_arm(host: str, observed: Observation) -> dict[str, Any]:
    """Convert settled counters into the closed T012 arm schema."""
    ceilings = {
        "supervisor_turns": observed.supervisor_turns,
        "root_input_tokens": observed.root_input_tokens,
        "native_total_tokens": observed.native_total_tokens,
    }
    return {
        "posture_key": host,
        "logical_dispatch_ids": list(_NODES),
        "logical_completions_verified": True,
        "metrics": {
            "supervisor_turns": observed.supervisor_turns,
            "root_input_tokens": observed.root_input_tokens,
            "logical_nodes": len(_NODES),
        },
        "native_usage": {
            "known_subtotal": observed.native_total_tokens,
            "unknown_segment_count": 0,
            "unknown_reasons": [],
            "completeness": "complete",
            "quality_flags": [],
            "quota_observation": {
                "availability": "unavailable",
                "source": "native_cli_json",
                "unit": "unknown",
                "value": None,
            },
        },
        "ceiling_observations": {
            name: {"observed": value, "enforced": False, "enforcer_id": _ENFORCER_ID}
            for name, value in ceilings.items()
        },
    }


def _failure_code(exc: BaseException) -> str:
    """Map a bounded capture failure to the closed manifest code set."""
    if isinstance(exc, CaptureRejected):
        return "ceiling_rejection" if "ceiling" in str(exc) else "incomplete_evidence"
    return "host_failure"


def _failed_capture_artifacts(failure_code: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build schema-valid, non-passing artifacts when preflight cannot start.

    The posture hashes are the frozen requested identities, not observations;
    every trial is explicitly failed, so they cannot become promotion evidence.
    """
    graph = {"nodes": list(_NODES), "edges": [list(edge) for edge in _EDGES]}
    schedule = ["claude_first" if index % 2 == 0 else "codex_first" for index in range(_PAIR_COUNT)]
    equivalence_key = _canonical_hash(
        {"graph": graph, "schedule": "serial-terminal-v1", "command": "nine-node-read-only"}
    )
    trials = [
        {
            "pair_id": f"pair-{index + 1}",
            "status": "failed",
            "order": order,
            "graph_id": "nine-node-read-only-v1",
            "schedule_id": "serial-terminal-v1",
            "cache_state": "cold",
            "failure_code": failure_code if index == 0 else "operator_abort",
        }
        for index, order in enumerate(schedule)
    ]
    manifest = {
        "schema_version": 1,
        "protocol_id": "paired-orchestration-v1",
        "postures": {
            "claude": {
                "host": "claude",
                "surface": "claude_cli",
                "runtime_version": _EXPECTED_VERSIONS["claude"].split()[0],
                "build_fingerprint": _EXPECTED_EXECUTABLE_SHA256["claude"],
                "command": "nine-node-read-only",
                "posture": "external_terminal_verified",
                "equivalence_key": equivalence_key,
            },
            "codex": {
                "host": "codex",
                "surface": "codex_cli",
                "runtime_version": "0.142.5",
                "build_fingerprint": _EXPECTED_EXECUTABLE_SHA256["codex_js"],
                "command": "nine-node-read-only",
                "posture": "native_terminal_verified",
                "equivalence_key": equivalence_key,
            },
        },
        "logical_graph": {
            "graph_id": "nine-node-read-only-v1",
            "logical_node_ids": list(_NODES),
            "edges": [{"from": source, "to": target} for source, target in _EDGES],
        },
        "terminal_schedule": {"schedule_id": "serial-terminal-v1", "terminal_node_ids": list(_NODES)},
        "counterbalancing": {
            "method": "alternating_ab_ba",
            "pair_orders": [
                {"pair_id": f"pair-{index + 1}", "order": order}
                for index, order in enumerate(schedule)
            ],
        },
        "cache_control": {"state": "cold", "preparation_id": "fresh-process-no-session-v1"},
        "rules": {
            "inclusion": "completed_pairs_only",
            "failed_trial": "exclude_pair_and_fail_evidence_gate",
            "weighting": "pooled_logical_nodes",
            "confidence": "paired_normal_95",
        },
        "hard_ceilings": {
            "supervisor_turns": len(_NODES),
            "root_input_tokens": len(_NODES) * Limits().root_input_tokens,
            "native_total_tokens": len(_NODES) * Limits().native_total_tokens,
        },
        "native_usage_rules": {
            "required_completeness": "complete",
            "maximum_unknown_segments": 0,
            "allowed_quality_flags": [],
            "quota_interpretation": "observation_only_no_billing_formula",
        },
        "trials": trials,
    }
    evidence = {
        "schema_version": 1,
        "protocol_id": manifest["protocol_id"],
        "capture_status": "failed",
        "failure_code": failure_code,
        "requested_executable_sha256": dict(_EXPECTED_EXECUTABLE_SHA256),
        "pairs": [
            {
                "pair_id": trial["pair_id"],
                "order": trial["order"],
                "status": "failed",
                "failure_code": trial["failure_code"],
            }
            for trial in trials
        ],
    }
    return evidence, manifest


def _publication_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Project private capture state into canonical privacy-safe evidence.

    The source capture fingerprint and implementation digest remain historical:
    they continue to bind the exact in-memory provenance, including argv, used
    for the live run.  The publication projection removes argv and records its
    own independently reproducible contract and payload digests.

    Args:
        evidence: Complete in-memory capture evidence before publication.

    Returns:
        A detached JSON-compatible object with no machine-local argv.

    Raises:
        CaptureRejected: If required historical provenance is absent.
    """
    projected = json.loads(json.dumps(evidence))
    provenance = projected.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.pop("argv", None), dict):
        raise CaptureRejected("capture provenance has no private argv to project")
    enforcer = provenance.get("enforcer")
    if not isinstance(enforcer, dict):
        raise CaptureRejected("capture provenance has no enforcer record")
    capture_implementation = enforcer.pop("implementation_sha256", None)
    source_fingerprint = provenance.get("capture_fingerprint")
    if not isinstance(capture_implementation, str) or not isinstance(source_fingerprint, str):
        raise CaptureRejected("capture provenance fingerprints are incomplete")
    enforcer["capture_implementation_sha256"] = capture_implementation
    contract = {
        "id": _PROJECTION_ID,
        "removed_fields": ["provenance.argv"],
        "retained_fingerprints": [
            "provenance.argv_sha256",
            "provenance.executable_sha256",
            "provenance.capture_fingerprint",
            "provenance.enforcer.capture_implementation_sha256",
        ],
    }
    projected_payload_sha256 = _canonical_hash(projected)
    provenance["publication_projection"] = {
        "id": _PROJECTION_ID,
        "source_capture_fingerprint": source_fingerprint,
        "projection_contract_sha256": _canonical_hash(contract),
        "projected_payload_sha256": projected_payload_sha256,
        "removed_fields": contract["removed_fields"],
    }
    return projected


def _capture() -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute exactly five complete AB/BA pairs; any failure hard-fails."""
    paths = _discover_runtime_paths()
    versions = _versions(paths)
    codex_argv = _codex_argv(paths)
    claude_argv = _claude_argv(paths)
    graph = {"nodes": list(_NODES), "edges": [list(edge) for edge in _EDGES]}
    schedule = ["claude_first" if index % 2 == 0 else "codex_first" for index in range(_PAIR_COUNT)]
    provenance = {
        "runtime_versions": versions,
        "executable_sha256": {
            "node": _file_hash(str(paths.node)),
            "codex_js": _file_hash(str(paths.codex_js)),
            "claude": _file_hash(str(paths.claude)),
        },
        "argv": {"codex": codex_argv, "claude": claude_argv},
        "argv_sha256": {"codex": _canonical_hash(codex_argv), "claude": _canonical_hash(claude_argv)},
        "prompt_sha256": {
            "codex": _canonical_hash(_prompt(_NODES)),
            "claude_by_node": {node: _canonical_hash(_prompt((node,))) for node in _NODES},
        },
        "graph": graph,
        "graph_sha256": _canonical_hash(graph),
        "schedule": schedule,
        "schedule_sha256": _canonical_hash(schedule),
        "enforcer": {
            "id": _ENFORCER_ID,
            "implementation_sha256": _file_hash(__file__),
            "process_group": "start_new_session_and_killpg",
            "claude_provider_budget_usd": _CLAUDE_BUDGET_USD,
            "claude_aggregate_budget_usd": _CLAUDE_AGGREGATE_USD,
        },
    }
    provenance["capture_fingerprint"] = _canonical_hash(provenance)
    records: list[dict[str, Any]] = []
    trials: list[dict[str, Any]] = []
    total_claude_dollars = 0.0
    codex_limits = Limits()
    claude_limits = Limits(dollars=_CLAUDE_BUDGET_USD)

    def run_codex() -> tuple[Observation, list[ProcessResult]]:
        result = _run_process(
            codex_argv, _prompt(_NODES), codex_limits, _parse_codex, expected_nodes=_NODES
        )
        return result.observation, [result]

    def run_claude() -> tuple[Observation, list[ProcessResult]]:
        nonlocal total_claude_dollars
        results: list[ProcessResult] = []
        for node in _NODES:
            if total_claude_dollars + _CLAUDE_BUDGET_USD > _CLAUDE_AGGREGATE_USD:
                raise CaptureRejected("aggregate Claude dollar ceiling cannot admit next invocation")
            result = _run_process(
                claude_argv,
                _prompt((node,)),
                claude_limits,
                _parse_claude,
                expected_nodes=(node,),
            )
            results.append(result)
            total_claude_dollars += result.observation.dollars
            if total_claude_dollars > _CLAUDE_AGGREGATE_USD:
                raise CaptureRejected("aggregate Claude dollar ceiling breached")
        return _combine(results), results

    capture_failed = False
    for index, order in enumerate(schedule, start=1):
        pair_id = f"pair-{index}"
        if capture_failed:
            failure_code = "operator_abort"
            records.append(
                {"pair_id": pair_id, "order": order, "status": "failed", "failure_code": failure_code}
            )
            trials.append(
                {
                    "pair_id": pair_id,
                    "status": "failed",
                    "order": order,
                    "graph_id": "nine-node-read-only-v1",
                    "schedule_id": "serial-terminal-v1",
                    "cache_state": "cold",
                    "failure_code": failure_code,
                }
            )
            continue
        arms: dict[str, Observation] = {}
        process_rows: dict[str, list[dict[str, Any]]] = {}
        try:
            for host in (("claude", "codex") if order == "claude_first" else ("codex", "claude")):
                observed, processes = run_claude() if host == "claude" else run_codex()
                arms[host] = observed
                process_rows[host] = [
                    {
                        "wall_seconds": result.wall_seconds,
                        "exit_code": result.exit_code,
                        "pgid": result.pgid,
                        "reaped": True,
                        "stderr_sha256": result.stderr_sha256,
                        "verified_logical_node_ids": list(result.verified_logical_node_ids),
                        "observation": asdict(result.observation),
                    }
                    for result in processes
                ]
        except (CaptureRejected, OSError, subprocess.SubprocessError) as exc:
            failure_code = _failure_code(exc)
            records.append(
                {"pair_id": pair_id, "order": order, "status": "failed", "failure_code": failure_code}
            )
            trials.append(
                {
                    "pair_id": pair_id,
                    "status": "failed",
                    "order": order,
                    "graph_id": "nine-node-read-only-v1",
                    "schedule_id": "serial-terminal-v1",
                    "cache_state": "cold",
                    "failure_code": failure_code,
                }
            )
            capture_failed = True
            continue
        records.append({"pair_id": pair_id, "order": order, "status": "complete", "processes": process_rows})
        trials.append(
            {
                "pair_id": pair_id,
                "status": "complete",
                "order": order,
                "graph_id": "nine-node-read-only-v1",
                "schedule_id": "serial-terminal-v1",
                "cache_state": "cold",
                "baseline_provenance": {
                    "kind": "terminal_verified_capture",
                    "evidence_id": f"t014-{pair_id}",
                    "capture_fingerprint": provenance["capture_fingerprint"],
                },
                "claude": _manifest_arm("claude", arms["claude"]),
                "codex": _manifest_arm("codex", arms["codex"]),
            }
        )

    equivalence_key = _canonical_hash({"graph": graph, "schedule": "serial-terminal-v1", "command": "nine-node-read-only"})
    manifest = {
        "schema_version": 1,
        "protocol_id": "paired-orchestration-v1",
        "postures": {
            "claude": {
                "host": "claude",
                "surface": "claude_cli",
                "runtime_version": versions["claude"].split()[0],
                "build_fingerprint": provenance["executable_sha256"]["claude"],
                "command": "nine-node-read-only",
                "posture": "external_terminal_verified",
                "equivalence_key": equivalence_key,
            },
            "codex": {
                "host": "codex",
                "surface": "codex_cli",
                "runtime_version": "0.142.5",
                "build_fingerprint": provenance["executable_sha256"]["codex_js"],
                "command": "nine-node-read-only",
                "posture": "native_terminal_verified",
                "equivalence_key": equivalence_key,
            },
        },
        "logical_graph": {
            "graph_id": "nine-node-read-only-v1",
            "logical_node_ids": list(_NODES),
            "edges": [{"from": source, "to": target} for source, target in _EDGES],
        },
        "terminal_schedule": {"schedule_id": "serial-terminal-v1", "terminal_node_ids": list(_NODES)},
        "counterbalancing": {
            "method": "alternating_ab_ba",
            "pair_orders": [
                {"pair_id": f"pair-{index + 1}", "order": order} for index, order in enumerate(schedule)
            ],
        },
        "cache_control": {"state": "cold", "preparation_id": "fresh-process-no-session-v1"},
        "rules": {
            "inclusion": "completed_pairs_only",
            "failed_trial": "exclude_pair_and_fail_evidence_gate",
            "weighting": "pooled_logical_nodes",
            "confidence": "paired_normal_95",
        },
        "hard_ceilings": {
            "supervisor_turns": len(_NODES),
            "root_input_tokens": len(_NODES) * claude_limits.root_input_tokens,
            "native_total_tokens": len(_NODES) * claude_limits.native_total_tokens,
        },
        "native_usage_rules": {
            "required_completeness": "complete",
            "maximum_unknown_segments": 0,
            "allowed_quality_flags": [],
            "quota_interpretation": "observation_only_no_billing_formula",
        },
        "trials": trials,
    }
    evidence = {
        "schema_version": 1,
        "protocol_id": manifest["protocol_id"],
        "provenance": provenance,
        "limits": {
            "codex_per_invocation": asdict(codex_limits),
            "claude_per_invocation": asdict(claude_limits),
            "claude_aggregate_dollars": _CLAUDE_AGGREGATE_USD,
        },
        "actual_claude_cost_usd": total_claude_dollars,
        "pairs": records,
    }
    return evidence, manifest


def main() -> int:
    """Capture five pairs and durably write evidence, manifest, and analysis.

    Returns:
        Zero after all processes are reaped and either complete or failed
        artifacts are written.

    Raises:
        OSError: If an artifact write fails after capture settlement.
    """
    try:
        evidence, manifest = _capture()
        published_evidence = _publication_evidence(evidence)
    except (CaptureRejected, OSError, subprocess.SubprocessError) as exc:
        evidence, manifest = _failed_capture_artifacts(_failure_code(exc))
        published_evidence = evidence
    analysis = analyze_manifest(manifest)
    _atomic_json(_OUTPUT_DIR / "capture-evidence.json", published_evidence)
    _atomic_json(_OUTPUT_DIR / "manifest.json", manifest)
    _atomic_json(_OUTPUT_DIR / "analysis.json", analysis)
    return 0


if __name__ == "__main__":
    sys.exit(main())
