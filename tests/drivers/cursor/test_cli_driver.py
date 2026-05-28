"""
tests/drivers/cursor/test_cli_driver.py — Unit tests for runtime/drivers/cursor/cli_driver.py.

Covers:
  - DriverConfigError raised when CURSOR_API_KEY is absent or empty
  - DriverInitError raised when cursor-agent binary not on PATH
  - driver_selected telemetry emitted on init
  - _build_args maps modes correctly; defaults to 'ask' for unknown modes
  - dispatch spawns cursor-agent -p with --output-format stream-json
  - subprocess_spawn telemetry emitted with pid and redacted args
  - subprocess_exit telemetry emitted with exit_code, is_error, wall_ms
  - handle.events() yields parsed JSON dicts; skips malformed lines
  - handle.wait() returns DispatchResult with correct exit_code / is_error
  - CursorCLIDriver implements the HostDriver ABC (all abstract methods present)

No cursor-agent binary is required; all subprocess interactions are mocked.

Run:
    pytest tests/drivers/cursor/test_cli_driver.py -v
"""

from __future__ import annotations

import io
import json
import subprocess as _subprocess
from unittest.mock import MagicMock, patch

import pytest

from runtime.drivers.cursor.cli_driver import (
    CursorCLIDriver,
    DriverConfigError,
    DriverInitError,
    _fire_telemetry,
)
from runtime.dispatch.driver import HostDriver
from runtime.dispatch.result import DispatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CURSOR_PROVIDER: dict = {
    "name": "cursor",
    "kind": "cli",
    "host": "cursor",
}

_CLEAN_ENV: dict = {
    "PATH": "/usr/bin",
    "HOME": "/home/user",
}


def _make_mock_proc(
    stdout_lines: list[str] | None = None,
    returncode: int = 0,
    stderr_text: str = "",
) -> MagicMock:
    """Return a MagicMock shaped like subprocess.Popen."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = 12345

    encoded = b"".join(
        (line + "\n").encode("utf-8") for line in (stdout_lines or [])
    )
    proc.stdout = io.BytesIO(encoded)
    proc.stderr = io.BytesIO(stderr_text.encode("utf-8"))
    proc.wait.return_value = returncode
    proc.kill.return_value = None
    proc.poll.return_value = returncode
    return proc


def _make_init_driver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str = "cursor-test-key",
    binary_found: bool = True,
) -> CursorCLIDriver:
    """Create and init a CursorCLIDriver with mocked env and binary check."""
    monkeypatch.setenv("CURSOR_API_KEY", api_key)
    if binary_found:
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: f"/usr/local/bin/{name}",
        )
    else:
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: None,
        )
    monkeypatch.setattr(
        "runtime.drivers.cursor.cli_driver._fire_telemetry",
        MagicMock(),
    )
    driver = CursorCLIDriver()
    driver.init(_CURSOR_PROVIDER, context={"run_id": "run-t005", "repo_root": "/repo"})
    return driver


# ---------------------------------------------------------------------------
# HostDriver ABC conformance
# ---------------------------------------------------------------------------


class TestHostDriverConformance:
    """CursorCLIDriver must implement all abstract methods of HostDriver."""

    def test_is_subclass_of_host_driver(self):
        assert issubclass(CursorCLIDriver, HostDriver)

    def test_has_init_method(self):
        assert callable(getattr(CursorCLIDriver, "init", None))

    def test_has_dispatch_method(self):
        assert callable(getattr(CursorCLIDriver, "dispatch", None))

    def test_has_teardown_method(self):
        assert callable(getattr(CursorCLIDriver, "teardown", None))

    def test_instantiates_without_arguments(self):
        driver = CursorCLIDriver()
        assert driver is not None


# ---------------------------------------------------------------------------
# Auth: DriverConfigError when CURSOR_API_KEY is missing
# ---------------------------------------------------------------------------


class TestAuthValidation:
    """DriverConfigError raised when CURSOR_API_KEY is absent or empty."""

    def test_raises_driver_config_error_when_key_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("CURSOR_API_KEY", raising=False)
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: f"/usr/local/bin/{name}",
        )
        driver = CursorCLIDriver()
        with pytest.raises(DriverConfigError):
            driver.init(_CURSOR_PROVIDER)

    def test_raises_driver_config_error_when_key_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CURSOR_API_KEY", "")
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: f"/usr/local/bin/{name}",
        )
        driver = CursorCLIDriver()
        with pytest.raises(DriverConfigError):
            driver.init(_CURSOR_PROVIDER)

    def test_raises_driver_config_error_when_key_whitespace_only(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CURSOR_API_KEY", "   ")
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: f"/usr/local/bin/{name}",
        )
        driver = CursorCLIDriver()
        with pytest.raises(DriverConfigError):
            driver.init(_CURSOR_PROVIDER)

    def test_no_error_when_key_set(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CURSOR_API_KEY", "valid-key")
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: f"/usr/local/bin/{name}",
        )
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", MagicMock()
        )
        driver = CursorCLIDriver()
        driver.init(_CURSOR_PROVIDER)  # must not raise


# ---------------------------------------------------------------------------
# Binary probe: DriverInitError when cursor-agent not on PATH
# ---------------------------------------------------------------------------


class TestBinaryProbe:
    """DriverInitError raised when cursor-agent binary not found on PATH."""

    def test_raises_driver_init_error_when_binary_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CURSOR_API_KEY", "valid-key")
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: None,
        )
        driver = CursorCLIDriver()
        with pytest.raises(DriverInitError):
            driver.init(_CURSOR_PROVIDER)

    def test_error_message_mentions_cursor_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CURSOR_API_KEY", "valid-key")
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: None,
        )
        driver = CursorCLIDriver()
        with pytest.raises(DriverInitError) as exc_info:
            driver.init(_CURSOR_PROVIDER)
        assert "cursor-agent" in str(exc_info.value)

    def test_no_error_when_binary_found(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CURSOR_API_KEY", "valid-key")
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: "/usr/local/bin/cursor-agent",
        )
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", MagicMock()
        )
        driver = CursorCLIDriver()
        driver.init(_CURSOR_PROVIDER)  # must not raise


# ---------------------------------------------------------------------------
# driver_selected telemetry on init
# ---------------------------------------------------------------------------


class TestDriverSelectedTelemetry:
    """driver_selected event emitted with host='cursor', tier='cli' on init."""

    def test_driver_selected_emitted_on_init(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CURSOR_API_KEY", "valid-key")
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: "/usr/local/bin/cursor-agent",
        )
        mock_fire = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )
        driver = CursorCLIDriver()
        driver.init(_CURSOR_PROVIDER, context={"run_id": "r", "repo_root": "/r"})

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "driver_selected" in fired_kinds

    def test_driver_selected_payload_host_cursor(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CURSOR_API_KEY", "valid-key")
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: "/usr/local/bin/cursor-agent",
        )
        mock_fire = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )
        driver = CursorCLIDriver()
        driver.init(_CURSOR_PROVIDER, context={"run_id": "r", "repo_root": "/r"})

        selected_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "driver_selected"
        )
        payload = selected_call.args[1]
        assert payload["host"] == "cursor"
        assert payload["tier"] == "cli"


# ---------------------------------------------------------------------------
# _build_args mode mapping
# ---------------------------------------------------------------------------


class TestBuildArgs:
    """_build_args maps modes correctly; defaults to ask for unknown inputs."""

    def test_ask_mode(self):
        driver = CursorCLIDriver()
        assert driver._build_args("ask") == ["--mode", "ask"]

    def test_plan_mode(self):
        driver = CursorCLIDriver()
        assert driver._build_args("plan") == ["--mode", "plan"]

    def test_agent_mode(self):
        driver = CursorCLIDriver()
        assert driver._build_args("agent") == ["--mode", "agent"]

    def test_unknown_mode_defaults_to_ask(self):
        driver = CursorCLIDriver()
        assert driver._build_args("unknown_mode") == ["--mode", "ask"]

    def test_empty_string_defaults_to_ask(self):
        driver = CursorCLIDriver()
        assert driver._build_args("") == ["--mode", "ask"]


# ---------------------------------------------------------------------------
# dispatch: subprocess launched with correct argv
# ---------------------------------------------------------------------------


class TestDispatchSubprocess:
    """dispatch() launches cursor-agent -p with --output-format stream-json."""

    def _setup_dispatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_proc: MagicMock,
    ) -> tuple[CursorCLIDriver, MagicMock]:
        """Wire up a driver with mocked Popen."""
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.subprocess.Popen", mock_popen
        )
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", MagicMock()
        )
        driver = _make_init_driver(monkeypatch)
        return driver, mock_popen

    def test_popen_uses_cursor_agent_binary(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc()
        driver, mock_popen = self._setup_dispatch(monkeypatch, mock_proc)

        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        argv = mock_popen.call_args[0][0]
        assert "cursor-agent" in argv[0]

    def test_popen_includes_p_flag(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc()
        driver, mock_popen = self._setup_dispatch(monkeypatch, mock_proc)

        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        argv = mock_popen.call_args[0][0]
        assert "-p" in argv

    def test_popen_includes_output_format_stream_json(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc()
        driver, mock_popen = self._setup_dispatch(monkeypatch, mock_proc)

        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        argv = mock_popen.call_args[0][0]
        assert "--output-format" in argv
        idx = argv.index("--output-format")
        assert argv[idx + 1] == "stream-json"

    def test_popen_includes_mode_flag(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc()
        driver, mock_popen = self._setup_dispatch(monkeypatch, mock_proc)

        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        argv = mock_popen.call_args[0][0]
        assert "--mode" in argv

    def test_cursor_api_key_injected_into_env(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        captured_env: dict = {}

        def _fake_popen(argv, *, stdout, stderr, env):
            captured_env.update(env)
            return _make_mock_proc()

        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.subprocess.Popen", _fake_popen
        )
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", MagicMock()
        )
        driver = _make_init_driver(monkeypatch, api_key="my-cursor-key")

        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        assert captured_env.get("CURSOR_API_KEY") == "my-cursor-key"


# ---------------------------------------------------------------------------
# subprocess_spawn telemetry
# ---------------------------------------------------------------------------


class TestSubprocessSpawnTelemetry:
    """subprocess_spawn emitted on dispatch with pid and args_redacted."""

    def test_subprocess_spawn_event_fires_on_dispatch(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc()
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.subprocess.Popen", mock_popen
        )
        mock_fire = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )
        driver = _make_init_driver(monkeypatch)
        # Re-attach fresh mock after init consumed one call
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )

        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "subprocess_spawn" in fired_kinds

    def test_subprocess_spawn_payload_has_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc()
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.subprocess.Popen", mock_popen
        )
        mock_fire = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )
        driver = _make_init_driver(monkeypatch)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )

        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        spawn_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "subprocess_spawn"
        )
        assert "pid" in spawn_call.args[1]


# ---------------------------------------------------------------------------
# handle.events() — stream parsing
# ---------------------------------------------------------------------------


class TestEvents:
    """handle.events() yields parsed JSON dicts; skips malformed lines."""

    def _driver_with_popen(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_proc: MagicMock,
    ) -> CursorCLIDriver:
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", MagicMock()
        )
        return _make_init_driver(monkeypatch)

    def test_yields_parsed_json_dicts(self, monkeypatch: pytest.MonkeyPatch):
        lines = ['{"type":"message","content":"hello"}', '{"type":"done"}']
        mock_proc = _make_mock_proc(stdout_lines=lines)
        driver = self._driver_with_popen(monkeypatch, mock_proc)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        events = list(handle.events())

        assert len(events) == 2
        assert events[0] == {"type": "message", "content": "hello"}
        assert events[1] == {"type": "done"}

    def test_skips_malformed_jsonl_and_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        lines = ["not-json", '{"type":"ok"}']
        mock_proc = _make_mock_proc(stdout_lines=lines)
        driver = self._driver_with_popen(monkeypatch, mock_proc)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        events = list(handle.events())

        assert len(events) == 1
        assert events[0]["type"] == "ok"
        captured = capsys.readouterr()
        assert "malformed" in captured.err

    def test_skips_blank_lines(self, monkeypatch: pytest.MonkeyPatch):
        lines = ['{"type":"msg"}', "", '{"type":"end"}']
        mock_proc = _make_mock_proc(stdout_lines=lines)
        driver = self._driver_with_popen(monkeypatch, mock_proc)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        events = list(handle.events())

        assert len(events) == 2


# ---------------------------------------------------------------------------
# handle.wait() — DispatchResult
# ---------------------------------------------------------------------------


class TestWait:
    """handle.wait() returns DispatchResult with exit_code and is_error."""

    def _driver_with_popen(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_proc: MagicMock,
    ) -> CursorCLIDriver:
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", MagicMock()
        )
        return _make_init_driver(monkeypatch)

    def test_wait_returns_dispatch_result(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc(returncode=0)
        driver = self._driver_with_popen(monkeypatch, mock_proc)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        result = handle.wait()

        assert isinstance(result, DispatchResult)

    def test_wait_exit_code_zero_is_not_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc(returncode=0)
        driver = self._driver_with_popen(monkeypatch, mock_proc)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        result = handle.wait()

        assert result.exit_code == 0
        assert result.is_error is False

    def test_wait_non_zero_exit_is_error(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc(returncode=1)
        driver = self._driver_with_popen(monkeypatch, mock_proc)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        result = handle.wait()

        assert result.exit_code == 1
        assert result.is_error is True

    def test_wait_returns_wall_ms(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc(returncode=0)
        driver = self._driver_with_popen(monkeypatch, mock_proc)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        result = handle.wait()

        assert result.wall_ms >= 0.0


# ---------------------------------------------------------------------------
# subprocess_exit telemetry
# ---------------------------------------------------------------------------


class TestSubprocessExitTelemetry:
    """subprocess_exit emitted from _wait_fn with exit_code, is_error, wall_ms."""

    def test_subprocess_exit_event_fires_after_wait(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc(returncode=0)
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.subprocess.Popen", mock_popen
        )
        mock_fire = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )
        driver = _make_init_driver(monkeypatch)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        handle.wait()

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "subprocess_exit" in fired_kinds

    def test_subprocess_exit_payload_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc(returncode=0)
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.subprocess.Popen", mock_popen
        )
        mock_fire = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )
        driver = _make_init_driver(monkeypatch)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        handle.wait()

        exit_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "subprocess_exit"
        )
        payload = exit_call.args[1]
        assert "exit_code" in payload
        assert "is_error" in payload
        assert "wall_ms" in payload

    def test_subprocess_exit_is_error_true_on_non_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc(returncode=2)
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.subprocess.Popen", mock_popen
        )
        mock_fire = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )
        driver = _make_init_driver(monkeypatch)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver._fire_telemetry", mock_fire
        )

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        handle.wait()

        exit_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "subprocess_exit"
        )
        assert exit_call.args[1]["is_error"] is True
        assert exit_call.args[1]["exit_code"] == 2


# ---------------------------------------------------------------------------
# Invariant: CURSOR_API_KEY absent → DriverConfigError (failure class test)
# ---------------------------------------------------------------------------


class TestAuthInvariant:
    """If CURSOR_API_KEY is removed after construction, init must still raise."""

    def test_driver_config_error_is_raised_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Invariant: absent CURSOR_API_KEY always raises DriverConfigError, never returns None."""
        monkeypatch.delenv("CURSOR_API_KEY", raising=False)
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: f"/usr/local/bin/{name}",
        )
        driver = CursorCLIDriver()
        raised = False
        result = None
        try:
            result = driver.init(_CURSOR_PROVIDER)
        except DriverConfigError:
            raised = True
        assert raised, "DriverConfigError was not raised"
        assert result is None, "init() must not return a value on missing auth"


# ---------------------------------------------------------------------------
# Invariant: cursor-agent binary absent → DriverInitError (failure class test)
# ---------------------------------------------------------------------------


class TestBinaryInvariant:
    """If cursor-agent is not on PATH, DriverInitError must be raised."""

    def test_driver_init_error_is_raised_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Invariant: absent binary always raises DriverInitError."""
        monkeypatch.setenv("CURSOR_API_KEY", "valid-key")
        monkeypatch.setattr(
            "runtime.drivers.cursor.cli_driver.shutil.which",
            lambda name: None,
        )
        driver = CursorCLIDriver()
        with pytest.raises(DriverInitError):
            driver.init(_CURSOR_PROVIDER)
