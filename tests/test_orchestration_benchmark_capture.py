"""Behavioral tests for the externally hard-capped benchmark capture."""

from __future__ import annotations

from collections import deque
import io
import hashlib
import json
from pathlib import Path
import re
import subprocess

import pytest

from runtime import orchestration_benchmark_capture as capture
from runtime.orchestration_benchmark import analyze_manifest, validate_manifest


_ARTIFACT_DIR = (
    Path(__file__).resolve().parents[1]
    / "temp"
    / "orchestration-benchmark"
    / "codex-z-harness-token-efficiency-root-fix"
)
_HISTORICAL_CAPTURE_FINGERPRINT = "87fee2204f284bbf2d75188b753d659e9340835c8efa659672f4b88871db1ffe"
_HISTORICAL_IMPLEMENTATION_SHA256 = "9d603040d669b5971fbc9df060b51900333ad0f52d886d94eaac9da8b14a1713"
_HISTORICAL_MEASUREMENTS_SHA256 = "89701270e7b5395367ed99f30708a4d008b670b96bcb2303b416c826ae24c960"


class _Input(io.BytesIO):
    def close(self) -> None:
        """Retain written input so tests can inspect the observable contract."""


class _Stream:
    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor

    def fileno(self) -> int:
        return self.descriptor


class _Process:
    def __init__(self, stdout: list[str], stderr: list[str] | None = None, *, returncode: int = 0) -> None:
        self.pid = 4242
        self.stdin = _Input()
        self.stdout = _Stream(10)
        self.stderr = _Stream(11)
        self.chunks = {
            10: deque([value.encode() for value in stdout] + [b""]),
            11: deque([value.encode() for value in (stderr or [])] + [b""]),
        }
        self.returncode = returncode
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        return self.returncode

    def read(self, descriptor: int, _size: int) -> bytes:
        return self.chunks[descriptor].popleft()


class _Selector:
    def __init__(self) -> None:
        self.streams: dict[object, object] = {}

    def register(self, stream, _events, data) -> None:
        self.streams[stream] = type("Key", (), {"fileobj": stream, "data": data})()

    def unregister(self, stream) -> None:
        del self.streams[stream]

    def get_map(self) -> dict[object, object]:
        return self.streams

    def select(self, timeout: float | None = None):
        return [(key, 1) for key in list(self.streams.values())]

    def close(self) -> None:
        self.streams.clear()


def _codex_line(*, turns: int = 1, root: int = 100, output: int = 5) -> str:
    assert turns == 1
    return "\n".join(
        (
            json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "scope=settled"}}
            ),
            json.dumps(
                {"type": "turn.completed", "usage": {"input_tokens": root, "output_tokens": output}}
            ),
            "",
        )
    )


def _claude_line(*, turns: int = 1, root: int = 100, output: int = 5, dollars: float = 0.01) -> str:
    return json.dumps(
        {
            "type": "result",
            "is_error": False,
            "num_turns": turns,
            "total_cost_usd": dollars,
            "result": "scope=settled",
            "usage": {
                "input_tokens": root,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 20,
                "output_tokens": output,
            },
        }
    ) + "\n"


@pytest.fixture
def process_harness(monkeypatch):
    """Pin process-group and selector seams without touching a real process."""
    monkeypatch.setattr(capture.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(capture.selectors, "DefaultSelector", _Selector)


def test_process_stream_is_continuously_reduced_and_reaped(process_harness) -> None:
    process = _Process([json.dumps({"type": "turn.started"}) + "\n", _codex_line()])
    result = capture._run_process(
        ["codex"],
        "frozen",
        capture.Limits(),
        capture._parse_codex,
        expected_nodes=("scope",),
        popen_factory=lambda *args, **kwargs: process,
        monotonic=lambda: 1.0,
        read=process.read,
        set_blocking=lambda descriptor, blocking: None,
    )
    assert result.observation.root_input_tokens == 100
    assert result.observation.native_total_tokens == 105
    assert result.observation.native_events == 3
    assert process.wait_calls == 1
    assert process.stdin.getvalue() == b"frozen"


@pytest.mark.parametrize(
    ("line", "limits", "reason"),
    [
        (_codex_line(root=101), capture.Limits(root_input_tokens=100), "root_input_tokens"),
        (_codex_line(root=100, output=6), capture.Limits(native_total_tokens=105), "native_total_tokens"),
        (_claude_line(turns=2), capture.Limits(supervisor_turns=1, dollars=0.04), "supervisor_turns"),
        (_claude_line(dollars=0.041), capture.Limits(dollars=0.04), "dollars"),
    ],
)
def test_each_native_cap_kills_and_reaps_whole_group(
    monkeypatch, process_harness, line: str, limits: capture.Limits, reason: str
) -> None:
    process = _Process([line])
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(capture.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    parser = capture._parse_claude if "total_cost_usd" in line else capture._parse_codex
    with pytest.raises(capture.CaptureRejected, match=reason):
        capture._run_process(
            ["model"],
            "frozen",
            limits,
            parser,
            expected_nodes=("scope",),
            popen_factory=lambda *args, **kwargs: process,
            monotonic=lambda: 1.0,
            read=process.read,
            set_blocking=lambda descriptor, blocking: None,
        )
    assert signals == [(process.pid, capture.signal.SIGTERM)]
    assert process.wait_calls == 1


@pytest.mark.parametrize(
    ("line", "parser", "message"),
    [
        ("not-json\n", capture._parse_codex, "non-JSON"),
        (json.dumps({"type": "turn.completed"}) + "\n", capture._parse_codex, "no native usage"),
        (
            json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}) + "\n",
            capture._parse_codex,
            "forbidden tool",
        ),
        (
            json.dumps(
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}}
            )
            + "\n",
            capture._parse_claude,
            "forbidden tool",
        ),
    ],
)
def test_malformed_or_tool_bearing_stream_kills_and_reaps(
    monkeypatch, process_harness, line: str, parser, message: str
) -> None:
    process = _Process([line])
    signals: list[int] = []
    monkeypatch.setattr(capture.os, "killpg", lambda pid, sig: signals.append(sig))
    with pytest.raises(capture.CaptureRejected, match=message):
        capture._run_process(
            ["model"],
            "frozen",
            capture.Limits(),
            parser,
            expected_nodes=("scope",),
            popen_factory=lambda *args, **kwargs: process,
            monotonic=lambda: 1.0,
            read=process.read,
            set_blocking=lambda descriptor, blocking: None,
        )
    assert signals == [capture.signal.SIGTERM]
    assert process.wait_calls == 1


def test_partial_line_cannot_block_wall_cap(monkeypatch, process_harness) -> None:
    process = _Process(['{"type":"turn.started"'])
    ticks = iter([0.0, 2.0])
    signals: list[int] = []
    monkeypatch.setattr(capture.os, "killpg", lambda pid, sig: signals.append(sig))
    with pytest.raises(capture.CaptureRejected, match="wall_seconds"):
        capture._run_process(
            ["codex"],
            "frozen",
            capture.Limits(wall_seconds=1.0),
            capture._parse_codex,
            expected_nodes=("scope",),
            popen_factory=lambda *args, **kwargs: process,
            monotonic=lambda: next(ticks),
            read=process.read,
            set_blocking=lambda descriptor, blocking: None,
        )
    assert signals == [capture.signal.SIGTERM]
    assert process.wait_calls == 1


@pytest.mark.parametrize("failure_point", ["read", "parser", "select", "getpgid"])
def test_every_post_spawn_exception_kills_and_reaps(
    monkeypatch, process_harness, failure_point: str
) -> None:
    process = _Process([_codex_line()])
    signals: list[int] = []
    monkeypatch.setattr(capture.os, "killpg", lambda pid, sig: signals.append(sig))
    parser = capture._parse_codex
    read = process.read
    if failure_point == "read":
        read = lambda descriptor, size: (_ for _ in ()).throw(OSError("read failed"))
    elif failure_point == "parser":
        parser = lambda event, observed: (_ for _ in ()).throw(OSError("parser failed"))
    elif failure_point == "select":
        class BrokenSelector(_Selector):
            def select(self, timeout: float | None = None):
                raise OSError("select failed")

        monkeypatch.setattr(capture.selectors, "DefaultSelector", BrokenSelector)
    else:
        monkeypatch.setattr(
            capture.os, "getpgid", lambda pid: (_ for _ in ()).throw(OSError("getpgid failed"))
        )

    with pytest.raises(OSError):
        capture._run_process(
            ["codex"],
            "frozen",
            capture.Limits(),
            parser,
            expected_nodes=("scope",),
            popen_factory=lambda *args, **kwargs: process,
            monotonic=lambda: 1.0,
            read=read,
            set_blocking=lambda descriptor, blocking: None,
        )
    assert signals == [capture.signal.SIGTERM]
    assert process.wait_calls == 1


def test_sigkill_fallback_reaps_after_term_timeout(monkeypatch) -> None:
    class SlowProcess(_Process):
        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            if timeout is not None:
                raise subprocess.TimeoutExpired("model", timeout)
            return 137

    process = SlowProcess([])
    signals: list[int] = []
    monkeypatch.setattr(capture.os, "killpg", lambda pid, sig: signals.append(sig))
    capture._kill_and_reap(process)
    assert signals == [capture.signal.SIGTERM, capture.signal.SIGKILL]
    assert process.wait_calls == 2


def test_capture_freezes_provenance_executes_exact_pairs_and_manifest_math(monkeypatch) -> None:
    calls: list[str] = []

    def fake_run(argv, prompt, limits, parser, **kwargs):
        host = "claude" if parser is capture._parse_claude else "codex"
        calls.append(host)
        observed = (
            capture.Observation(1, 1_000, 1_100, 100, 0.01, 2, True)
            if host == "claude"
            else capture.Observation(1, 10_000, 10_500, 500, 0.0, 2, True)
        )
        return capture.ProcessResult(
            observed, 1.0, 0, len(calls), False, None, "0" * 64, ("scope",)
        )

    monkeypatch.setattr(capture, "_run_process", fake_run)
    paths = capture.RuntimePaths(Path("node"), Path("codex.js"), Path("claude"))
    monkeypatch.setattr(capture, "_discover_runtime_paths", lambda: paths)
    monkeypatch.setattr(capture, "_versions", lambda value: dict(capture._EXPECTED_VERSIONS))
    monkeypatch.setattr(capture, "_file_hash", lambda path: capture._canonical_hash(path))
    evidence, manifest = capture._capture()
    published = capture._publication_evidence(evidence)
    validate_manifest(manifest)
    analysis = analyze_manifest(manifest)

    assert len(calls) == 50
    assert calls[:10] == ["claude"] * 9 + ["codex"]
    assert calls[10:20] == ["codex"] + ["claude"] * 9
    assert calls[20:30] == ["claude"] * 9 + ["codex"]
    assert calls[30:40] == ["codex"] + ["claude"] * 9
    assert calls[40:] == ["claude"] * 9 + ["codex"]
    assert evidence["actual_claude_cost_usd"] == pytest.approx(0.45)
    assert len(evidence["pairs"]) == 5
    assert "argv" not in published["provenance"]
    assert published["provenance"]["argv_sha256"] == evidence["provenance"]["argv_sha256"]
    assert "capture_implementation_sha256" in published["provenance"]["enforcer"]
    assert all(len(pair["processes"]["claude"]) == 9 for pair in evidence["pairs"])
    assert all(len(pair["processes"]["codex"]) == 1 for pair in evidence["pairs"])
    assert manifest["trials"][0]["claude"]["metrics"]["supervisor_turns"] == 9
    assert manifest["trials"][0]["codex"]["metrics"]["supervisor_turns"] == 1
    assert analysis["hard_gates"]["all_hard_ceilings_enforced"] is False
    assert analysis["passed"] is False
    assert analysis["aggregate"]["root_input_per_logical_node"]["codex_to_claude_ratio"] == pytest.approx(
        10 / 9
    )


def test_aggregate_dollar_preflight_fails_closed_without_launch(monkeypatch) -> None:
    monkeypatch.setattr(capture, "_CLAUDE_AGGREGATE_USD", 0.03)
    paths = capture.RuntimePaths(Path("node"), Path("codex.js"), Path("claude"))
    monkeypatch.setattr(capture, "_discover_runtime_paths", lambda: paths)
    monkeypatch.setattr(capture, "_versions", lambda value: dict(capture._EXPECTED_VERSIONS))
    monkeypatch.setattr(capture, "_file_hash", lambda path: capture._canonical_hash(path))
    launches: list[int] = []
    monkeypatch.setattr(capture, "_run_process", lambda *args, **kwargs: launches.append(1))
    evidence, manifest = capture._capture()
    assert launches == []
    assert [pair["status"] for pair in evidence["pairs"]] == ["failed"] * 5
    assert manifest["trials"][0]["failure_code"] == "ceiling_rejection"
    assert [trial["failure_code"] for trial in manifest["trials"][1:]] == ["operator_abort"] * 4
    result = analyze_manifest(manifest)
    assert result["admissible_pairs"] == 0
    assert result["passed"] is False


def test_failed_invocation_emits_schema_valid_nonpassing_evidence(monkeypatch) -> None:
    paths = capture.RuntimePaths(Path("node"), Path("codex.js"), Path("claude"))
    monkeypatch.setattr(capture, "_discover_runtime_paths", lambda: paths)
    monkeypatch.setattr(capture, "_versions", lambda value: dict(capture._EXPECTED_VERSIONS))
    monkeypatch.setattr(capture, "_file_hash", lambda path: capture._canonical_hash(path))
    monkeypatch.setattr(
        capture,
        "_run_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("simulated host failure")),
    )

    evidence, manifest = capture._capture()
    validate_manifest(manifest)
    analysis = analyze_manifest(manifest)
    assert evidence["pairs"][0]["failure_code"] == "host_failure"
    assert manifest["trials"][0]["failure_code"] == "host_failure"
    assert analysis["hard_gates"]["minimum_five_complete_pairs"] is False
    assert analysis["hard_gates"]["no_failed_pairs"] is False
    assert analysis["passed"] is False


def test_main_persists_preflight_failure_as_nonpassing_artifacts(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(capture, "_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        capture,
        "_capture",
        lambda: (_ for _ in ()).throw(capture.CaptureRejected("runtime identity mismatch")),
    )
    assert capture.main() == 0
    evidence = json.loads((tmp_path / "capture-evidence.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    analysis = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    validate_manifest(manifest)
    assert evidence["capture_status"] == "failed"
    assert evidence["failure_code"] == "incomplete_evidence"
    assert analysis == analyze_manifest(manifest)
    assert analysis["passed"] is False


def test_atomic_json_is_complete_and_replaces_existing_file(tmp_path) -> None:
    target = tmp_path / "evidence.json"
    target.write_text("stale", encoding="utf-8")
    capture._atomic_json(target, {"complete": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"complete": True}
    assert list(tmp_path.glob(".*.tmp")) == []


def test_runtime_discovery_is_portable_and_fails_closed(monkeypatch, tmp_path) -> None:
    home = tmp_path / "portable-home"
    node = home / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
    codex = tmp_path / "install/lib/node_modules/@openai/codex/bin/codex.js"
    claude = tmp_path / "install/share/claude/versions/frozen"
    for path in (node, codex, claude):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("runtime", encoding="utf-8")
    node.chmod(0o755)
    claude.chmod(0o755)
    launchers = {"codex": str(codex), "claude": str(claude)}
    monkeypatch.setattr(
        capture,
        "_EXPECTED_EXECUTABLE_SHA256",
        {
            "node": capture._file_hash(str(node)),
            "codex_js": capture._file_hash(str(codex)),
            "claude": capture._file_hash(str(claude)),
        },
    )

    paths = capture._discover_runtime_paths(home=home, which=launchers.get)
    assert paths == capture.RuntimePaths(node.resolve(), codex.resolve(), claude.resolve())

    node.chmod(0o644)
    with pytest.raises(capture.CaptureRejected, match="node executable input failed preflight"):
        capture._discover_runtime_paths(home=home, which=launchers.get)
    with pytest.raises(capture.CaptureRejected, match="codex executable is not available"):
        capture._discover_runtime_paths(home=home, which=lambda name: None)


def test_runtime_discovery_rejects_wrapper_and_hash_mismatch(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    node = home / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
    wrapper = tmp_path / "bin/codex"
    claude = tmp_path / "bin/claude"
    for path in (node, wrapper, claude):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unexpected", encoding="utf-8")
        path.chmod(0o755)
    launchers = {"codex": str(wrapper), "claude": str(claude)}
    with pytest.raises(capture.CaptureRejected, match="installation identity"):
        capture._discover_runtime_paths(home=home, which=launchers.get)

    codex = tmp_path / "lib/node_modules/@openai/codex/bin/codex.js"
    codex.parent.mkdir(parents=True)
    codex.write_text("unexpected", encoding="utf-8")
    launchers["codex"] = str(codex)
    monkeypatch.setattr(capture, "_EXPECTED_EXECUTABLE_SHA256", {key: "0" * 64 for key in ("node", "codex_js", "claude")})
    with pytest.raises(capture.CaptureRejected, match="frozen allowlist"):
        capture._discover_runtime_paths(home=home, which=launchers.get)


@pytest.mark.parametrize(
    ("texts", "message"),
    [
        ([], "missing or duplicate"),
        (["scope=settled\nscope=settled"], "missing or duplicate"),
        (["other=settled"], "unexpected"),
        (["scope=wrong"], "unexpected"),
    ],
)
def test_completion_markers_fail_closed(texts: list[str], message: str) -> None:
    with pytest.raises(capture.CaptureRejected, match=message):
        capture._verified_markers(texts, ("scope",))


def test_missing_completion_marker_rejects_and_settles_group(monkeypatch, process_harness) -> None:
    terminal = json.dumps(
        {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 5}}
    ) + "\n"
    process = _Process([terminal])
    signals: list[int] = []
    monkeypatch.setattr(capture.os, "killpg", lambda pid, sig: signals.append(sig))
    with pytest.raises(capture.CaptureRejected, match="missing or duplicate"):
        capture._run_process(
            ["codex"],
            "frozen",
            capture.Limits(),
            capture._parse_codex,
            expected_nodes=("scope",),
            popen_factory=lambda *args, **kwargs: process,
            monotonic=lambda: 1.0,
            read=process.read,
            set_blocking=lambda descriptor, blocking: None,
        )
    assert signals == [capture.signal.SIGTERM]
    assert process.wait_calls == 2


def test_canonical_artifacts_preserve_capture_and_exclude_private_content() -> None:
    evidence = json.loads((_ARTIFACT_DIR / "capture-evidence.json").read_text(encoding="utf-8"))
    manifest = json.loads((_ARTIFACT_DIR / "manifest.json").read_text(encoding="utf-8"))
    analysis = json.loads((_ARTIFACT_DIR / "analysis.json").read_text(encoding="utf-8"))
    provenance = evidence["provenance"]
    measurements = {
        "actual_claude_cost_usd": evidence["actual_claude_cost_usd"],
        "limits": evidence["limits"],
        "pairs": evidence["pairs"],
    }
    measurement_digest = hashlib.sha256(
        json.dumps(measurements, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert measurement_digest == _HISTORICAL_MEASUREMENTS_SHA256
    assert provenance["capture_fingerprint"] == _HISTORICAL_CAPTURE_FINGERPRINT
    assert provenance["enforcer"]["capture_implementation_sha256"] == _HISTORICAL_IMPLEMENTATION_SHA256
    assert "argv" not in provenance
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in provenance["argv_sha256"].values())
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", digest)
        for digest in provenance["executable_sha256"].values()
    )
    serialized = json.dumps({"evidence": evidence, "manifest": manifest, "analysis": analysis})
    assert "/Users/" not in serialized
    assert "/home/" not in serialized
    assert "=settled" not in serialized
    assert not re.search(r"(?:sk|api)[-_][A-Za-z0-9]{12,}", serialized, re.IGNORECASE)
    forbidden_content_keys = {"argv", "content", "message", "prompt", "tool_arguments", "tool_output"}

    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert forbidden_content_keys.isdisjoint(keys(evidence))
    projection = provenance.pop("publication_projection")
    assert capture._canonical_hash(evidence) == projection["projected_payload_sha256"]
    contract = {
        "id": projection["id"],
        "removed_fields": projection["removed_fields"],
        "retained_fingerprints": [
            "provenance.argv_sha256",
            "provenance.executable_sha256",
            "provenance.capture_fingerprint",
            "provenance.enforcer.capture_implementation_sha256",
        ],
    }
    assert capture._canonical_hash(contract) == projection["projection_contract_sha256"]
    assert projection["source_capture_fingerprint"] == _HISTORICAL_CAPTURE_FINGERPRINT
    validate_manifest(manifest)
    assert analyze_manifest(manifest) == analysis
    assert analysis["hard_gates"]["all_hard_ceilings_enforced"] is False
    assert analysis["hard_gates"]["all_logical_completions_verified"] is False
    assert analysis["passed"] is False
