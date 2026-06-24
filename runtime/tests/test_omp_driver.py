from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

import pytest

from runtime.drivers.omp.subprocess_driver import OmpDriverConfigError, OmpHostDriver


def _proc(*, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = BytesIO(stdout)
    proc.stderr = BytesIO(stderr)
    proc.returncode = returncode
    proc.pid = 4242

    def _wait(timeout=None):
        return returncode

    proc.wait.side_effect = _wait
    return proc


def _driver(provider_config: dict | None = None, context: dict | None = None) -> OmpHostDriver:
    driver = OmpHostDriver()
    driver.init(provider_config or {}, context=context)
    return driver


class TestNativeOmpArgv:
    def test_dispatch_invokes_omp_directly_with_prompt_as_final_arg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}

        def fake_popen(argv, *, stdout, stderr, env):
            seen["argv"] = argv
            seen["env"] = env
            return _proc(stdout=b"hello\n")

        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver.subprocess.Popen", fake_popen)
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        driver = _driver()
        handle = driver.dispatch("z-do", ["-p", "--model", "openai-codex/gpt-5.5", "hello world"], {"BASE": "1"})
        events = list(handle.events())
        result = handle.wait()

        assert seen["argv"] == ["omp", "-p", "--model", "openai-codex/gpt-5.5", "hello world"]
        assert "omp-consult.sh" not in " ".join(seen["argv"])
        assert "--no-rules" not in seen["argv"]
        assert "--no-session" not in seen["argv"]
        assert events[-1]["kind"] == "final_result"
        assert events[-1]["payload"]["text"] == "hello"
        assert result.exit_code == 0
        assert result.is_error is False
        assert result.stdout == "hello"

    def test_empty_prompt_rejected_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        popen = MagicMock()
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver.subprocess.Popen", popen)

        driver = _driver()
        with pytest.raises(OmpDriverConfigError, match="empty prompt"):
            driver.dispatch("z-do", ["-p", "--model", "m", "  \t"], {})

        popen.assert_not_called()

    def test_provider_config_adds_model_profile_session_and_plugin_root_without_consult_flags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def fake_popen(argv, *, stdout, stderr, env):
            seen["argv"] = argv
            seen["env"] = env
            return _proc(stdout=b"ok\n")

        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver.subprocess.Popen", fake_popen)
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        driver = _driver(
            {
                "model": "anthropic/claude-opus-4.5",
                "profile": "reviewer",
                "session_id": "sess-123",
                "omp_plugin_root": "/tmp/omp-plugin",
            }
        )
        handle = driver.dispatch("z-review", ["review this"], {"BASE": "1"})
        list(handle.events())
        result = handle.wait()

        argv = seen["argv"]
        assert argv == [
            "omp",
            "-p",
            "--model",
            "anthropic/claude-opus-4.5",
            "--profile",
            "reviewer",
            "--session",
            "sess-123",
            "review this",
        ]
        assert "--no-rules" not in argv
        assert "--no-session" not in argv
        assert seen["env"]["OMP_PLUGIN_ROOT"] == "/tmp/omp-plugin"
        assert result.session_id == "sess-123"

    def test_existing_session_model_and_profile_flags_are_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}

        def fake_popen(argv, *, stdout, stderr, env):
            seen["argv"] = argv
            return _proc(stdout=b"ok\n")

        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver.subprocess.Popen", fake_popen)
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        driver = _driver({"model": "config/model", "profile": "config-profile", "session_id": "config-session"})
        handle = driver.dispatch(
            "z-do",
            [
                "-p",
                "--model",
                "caller/model",
                "--profile=caller-profile",
                "--session",
                "caller-session",
                "prompt",
            ],
            {},
        )
        list(handle.events())
        handle.wait()

        assert seen["argv"] == [
            "omp",
            "-p",
            "--model",
            "caller/model",
            "--profile=caller-profile",
            "--session",
            "caller-session",
            "prompt",
        ]

    def test_omp_consult_command_is_rejected(self) -> None:
        with pytest.raises(OmpDriverConfigError, match="omp-consult"):
            _driver({"command": "scripts/omp-consult.sh"})

    def test_omp_consult_fallback_arg_is_rejected_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        popen = MagicMock()
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver.subprocess.Popen", popen)

        driver = _driver()
        with pytest.raises(OmpDriverConfigError, match="omp-consult"):
            driver.dispatch("z-do", ["--fallback", "scripts/omp-consult.sh", "prompt"], {})
        popen.assert_not_called()


class TestNativeOmpOutputParsing:
    def test_plain_text_and_mapped_json_events_are_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stdout = b"".join(
            [
                b"First line\n",
                b'{"type":"tool","name":"Read","input":{"path":"x"}}\n',
                b'{"type":"AskUserQuestion","question":"Pick one?"}\n',
                b'{"type":"subagent","agent":"explore","status":"started"}\n',
                b'{"type":"final_result","result":"Done"}\n',
            ]
        )
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        driver = _driver({"model": "m"})
        handle = driver.dispatch("z-do", ["prompt"], {})
        events = list(handle.events())
        result = handle.wait()

        assert [event["kind"] for event in events] == [
            "prompt_submitted",
            "assistant_delta",
            "tool_call",
            "ask_user",
            "subagent",
            "final_result",
        ]
        assert events[0]["payload"] == {"prompt_chars": len("prompt")}
        assert events[1]["payload"] == {"text": "First line"}
        assert events[2]["payload"]["name"] == "Read"
        assert events[3]["payload"]["question"] == "Pick one?"
        assert events[4]["payload"]["agent"] == "explore"
        assert events[5]["payload"]["text"] == "Done"
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert all(event["driver"] == "omp" for event in events)
        assert result.stdout_events == events
        assert result.is_error is False
        assert result.stdout == "Done"

    def test_non_zero_exit_returns_error_result_with_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=b"partial\n", stderr=b"boom\n", returncode=7)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        driver = _driver({"model": "m"})
        handle = driver.dispatch("z-do", ["prompt"], {})
        events = list(handle.events())
        result = handle.wait()

        assert events[-1]["kind"] == "final_result"
        assert result.exit_code == 7
        assert result.is_error is True
        assert result.stdout == "partial"
        assert "boom" in result.stderr

    def test_empty_stdout_is_error_even_with_zero_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=b"\n", returncode=0)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        driver = _driver({"model": "m"})
        handle = driver.dispatch("z-do", ["prompt"], {})
        events = list(handle.events())
        result = handle.wait()

        assert [event["kind"] for event in events] == ["prompt_submitted"]
        assert result.exit_code == 0
        assert result.is_error is True
        assert "no usable output" in result.stderr

    def test_telemetry_records_invoke_and_completion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, dict]] = []

        def fake_telemetry(kind, payload, *, run_id, repo_root):
            calls.append((kind, payload))

        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=b"ok\n")),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", fake_telemetry)

        driver = _driver({"model": "m", "profile": "p", "session_id": "s"})
        handle = driver.dispatch("z-do", ["prompt"], {})
        list(handle.events())
        handle.wait()

        assert calls[0][0] == "omp_driver_invoke"
        assert calls[0][1]["command"] == "omp"
        assert calls[0][1]["has_model"] is True
        assert calls[0][1]["has_profile"] is True
        assert calls[0][1]["has_session"] is True
        assert calls[0][1]["args_redacted"] == [
            "omp",
            "-p",
            "--model",
            "<redacted>",
            "--profile",
            "<redacted>",
            "--session",
            "<redacted>",
            "prompt",
        ]
        assert calls[1][0] == "omp_driver_complete"
        assert calls[1][1]["exit_code"] == 0
        assert calls[1][1]["is_error"] is False
