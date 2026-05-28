"""
tests/drivers/claude/test_subprocess_driver.py — Unit tests for SubprocessClaudeDriver.

Covers T003 acceptance criteria:
  - SubprocessClaudeDriver implements HostDriver protocol
  - _build_args() always includes --bare, --output-format stream-json, --verbose
  - _spawn() applies env_hygiene (CLAUDECODE="") before Popen; never inherits parent CLAUDECODE
  - Invalid session_id raises ValueError before spawn
  - Valid UUID4 session_id passes --resume <id> in args
  - subprocess_spawn and subprocess_exit telemetry emitted; args_redacted has no API key values
  - On non-zero exit, DriverExecutionError is raised after reading is_error from last stream-json line

No claude binary is required; all subprocess interactions are mocked via
unittest.mock.patch("subprocess.Popen").

Run:
    pytest tests/drivers/claude/test_subprocess_driver.py -v
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from runtime.dispatch.driver import HostDriver
from runtime.drivers.claude.subprocess_driver import (
    DriverExecutionError,
    SubprocessClaudeDriver,
    _extract_is_error,
    _redact_args,
    _validate_uuid4,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROVIDER: dict = {"name": "claude", "kind": "subprocess", "host": "claude"}

_CLEAN_ENV: dict = {"PATH": "/usr/bin", "HOME": "/home/user"}


def _make_mock_proc(
    stdout_lines: list[str] | None = None,
    returncode: int = 0,
    stderr_text: str = "",
) -> MagicMock:
    """Return a MagicMock shaped like subprocess.Popen."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = 99999

    encoded = b"".join(
        (line + "\n").encode("utf-8") for line in (stdout_lines or [])
    )
    proc.stdout = io.BytesIO(encoded)
    proc.stderr = io.BytesIO(stderr_text.encode("utf-8"))
    proc.wait.return_value = returncode
    return proc


def _make_init_driver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mock_fire: MagicMock | None = None,
) -> SubprocessClaudeDriver:
    """Create and init a SubprocessClaudeDriver with telemetry mocked out."""
    if mock_fire is None:
        mock_fire = MagicMock()
    monkeypatch.setattr(
        "runtime.drivers.claude.subprocess_driver._fire_telemetry",
        mock_fire,
    )
    driver = SubprocessClaudeDriver()
    driver.init(_PROVIDER, context={"run_id": "t003-run", "repo_root": "/repo"})
    return driver


# ---------------------------------------------------------------------------
# HostDriver ABC conformance
# ---------------------------------------------------------------------------


class TestHostDriverConformance:
    """SubprocessClaudeDriver must implement all HostDriver abstract methods."""

    def test_is_subclass_of_host_driver(self):
        assert issubclass(SubprocessClaudeDriver, HostDriver)

    def test_has_init_method(self):
        assert callable(getattr(SubprocessClaudeDriver, "init", None))

    def test_has_dispatch_method(self):
        assert callable(getattr(SubprocessClaudeDriver, "dispatch", None))

    def test_has_teardown_method(self):
        assert callable(getattr(SubprocessClaudeDriver, "teardown", None))

    def test_instantiates_without_arguments(self):
        driver = SubprocessClaudeDriver()
        assert driver is not None


# ---------------------------------------------------------------------------
# _build_args — required flags always present
# ---------------------------------------------------------------------------


class TestBuildArgs:
    """_build_args always includes --bare, --output-format stream-json, --verbose."""

    def setup_method(self):
        self.driver = SubprocessClaudeDriver()

    def test_bare_flag_present(self):
        argv = self.driver._build_args("hello")
        assert "--bare" in argv

    def test_output_format_stream_json_present(self):
        argv = self.driver._build_args("hello")
        assert "--output-format" in argv
        idx = argv.index("--output-format")
        assert argv[idx + 1] == "stream-json"

    def test_verbose_flag_present(self):
        argv = self.driver._build_args("hello")
        assert "--verbose" in argv

    def test_starts_with_claude_p(self):
        argv = self.driver._build_args("hello")
        assert argv[0] == "claude"
        assert argv[1] == "-p"

    def test_prompt_appended_at_end(self):
        argv = self.driver._build_args("my prompt text")
        assert argv[-1] == "my prompt text"

    def test_resume_flag_with_valid_session_id(self):
        sid = "12345678-1234-4234-b234-123456789abc"
        argv = self.driver._build_args("hello", session_id=sid)
        assert "--resume" in argv
        idx = argv.index("--resume")
        assert argv[idx + 1] == sid

    def test_no_resume_flag_without_session_id(self):
        argv = self.driver._build_args("hello")
        assert "--resume" not in argv


# ---------------------------------------------------------------------------
# _spawn — env hygiene: CLAUDECODE always cleared
# ---------------------------------------------------------------------------


class TestEnvHygiene:
    """_spawn applies apply_env_hygiene; CLAUDECODE is always "" in child env."""

    def test_claudecode_cleared_when_set_in_parent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CLAUDECODE", "1")
        captured_env: dict = {}

        def _fake_popen(argv, *, stdout, stderr, env):
            captured_env.update(env)
            return _make_mock_proc()

        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            _fake_popen,
        )
        driver = _make_init_driver(monkeypatch)
        # Pass parent env explicitly; _spawn must still clear it
        env_with_claudecode = {"CLAUDECODE": "1", "PATH": "/usr/bin"}
        driver._spawn("prompt", env=env_with_claudecode)

        assert captured_env.get("CLAUDECODE") == ""

    def test_claudecode_cleared_when_absent_in_base_env(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        captured_env: dict = {}

        def _fake_popen(argv, *, stdout, stderr, env):
            captured_env.update(env)
            return _make_mock_proc()

        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            _fake_popen,
        )
        driver = _make_init_driver(monkeypatch)
        driver._spawn("prompt", env={"PATH": "/usr/bin"})

        assert captured_env.get("CLAUDECODE") == ""

    def test_base_env_not_mutated(self, monkeypatch: pytest.MonkeyPatch):
        def _fake_popen(argv, *, stdout, stderr, env):
            return _make_mock_proc()

        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            _fake_popen,
        )
        driver = _make_init_driver(monkeypatch)
        base = {"CLAUDECODE": "parent-value", "HOME": "/home/user"}
        driver._spawn("prompt", env=base)

        assert base["CLAUDECODE"] == "parent-value", "base env must not be mutated"


# ---------------------------------------------------------------------------
# _spawn — UUID4 validation
# ---------------------------------------------------------------------------


class TestSessionIdValidation:
    """Invalid session_id raises ValueError before subprocess.Popen is called."""

    def test_invalid_uuid_raises_value_error(self, monkeypatch: pytest.MonkeyPatch):
        mock_popen = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            mock_popen,
        )
        driver = _make_init_driver(monkeypatch)
        with pytest.raises(ValueError):
            driver._spawn("prompt", session_id="not-a-uuid")

    def test_invalid_uuid_popen_not_called(self, monkeypatch: pytest.MonkeyPatch):
        """subprocess.Popen must NOT be called when session_id is invalid."""
        mock_popen = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            mock_popen,
        )
        driver = _make_init_driver(monkeypatch)
        with pytest.raises(ValueError):
            driver._spawn("prompt", session_id="bad-session-id")
        mock_popen.assert_not_called()

    def test_non_uuid4_version_raises(self, monkeypatch: pytest.MonkeyPatch):
        """UUID version 1 must also raise ValueError (task requires UUID4 strict)."""
        mock_popen = MagicMock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            mock_popen,
        )
        driver = _make_init_driver(monkeypatch)
        # UUID1 format
        with pytest.raises(ValueError):
            driver._spawn("prompt", session_id="12345678-1234-1234-b234-123456789abc")

    def test_valid_uuid4_does_not_raise(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        driver = _make_init_driver(monkeypatch)
        # Must not raise
        driver._spawn("prompt", session_id="12345678-1234-4234-b234-123456789abc")

    def test_valid_uuid4_passes_resume_flag(self, monkeypatch: pytest.MonkeyPatch):
        captured_argv: list = []
        sid = "12345678-1234-4234-b234-123456789abc"

        def _fake_popen(argv, *, stdout, stderr, env):
            captured_argv.extend(argv)
            return _make_mock_proc()

        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            _fake_popen,
        )
        driver = _make_init_driver(monkeypatch)
        driver._spawn("prompt", session_id=sid)

        assert "--resume" in captured_argv
        idx = captured_argv.index("--resume")
        assert captured_argv[idx + 1] == sid


# ---------------------------------------------------------------------------
# Telemetry — subprocess_spawn emitted on dispatch
# ---------------------------------------------------------------------------


class TestSubprocessSpawnTelemetry:
    """subprocess_spawn telemetry emitted with pid and args_redacted."""

    def test_subprocess_spawn_event_fired(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        mock_fire = MagicMock()
        driver = _make_init_driver(monkeypatch, mock_fire=mock_fire)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver._fire_telemetry",
            mock_fire,
        )

        driver._spawn("hello prompt")

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "subprocess_spawn" in fired_kinds

    def test_subprocess_spawn_payload_has_pid(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        mock_fire = MagicMock()
        driver = _make_init_driver(monkeypatch, mock_fire=mock_fire)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver._fire_telemetry",
            mock_fire,
        )

        driver._spawn("hello prompt")

        spawn_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "subprocess_spawn"
        )
        assert "pid" in spawn_call.args[1]

    def test_args_redacted_no_sk_prefix(self, monkeypatch: pytest.MonkeyPatch):
        """args_redacted in telemetry must not expose sk-* values."""
        mock_proc = _make_mock_proc()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        mock_fire = MagicMock()
        driver = _make_init_driver(monkeypatch, mock_fire=mock_fire)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver._fire_telemetry",
            mock_fire,
        )

        # Inject a fake sk- value as an extra arg
        driver._spawn("prompt", extra_args=["sk-ant-very-secret-key"])

        spawn_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "subprocess_spawn"
        )
        redacted = spawn_call.args[1]["args_redacted"]
        assert not any("sk-ant" in a for a in redacted), (
            "sk-* values must be redacted in telemetry payload"
        )


# ---------------------------------------------------------------------------
# Telemetry — subprocess_exit emitted after wait
# ---------------------------------------------------------------------------


class TestSubprocessExitTelemetry:
    """subprocess_exit telemetry emitted from _wait_fn with exit_code, is_error, wall_ms."""

    def test_subprocess_exit_event_fired(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc(returncode=0)
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        mock_fire = MagicMock()
        driver = _make_init_driver(monkeypatch, mock_fire=mock_fire)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver._fire_telemetry",
            mock_fire,
        )

        handle = driver._spawn("prompt")
        list(handle.events())
        # wait raises DriverExecutionError only on non-zero; this is exit 0
        handle.wait()

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "subprocess_exit" in fired_kinds

    def test_subprocess_exit_payload_fields(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc(returncode=0)
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        mock_fire = MagicMock()
        driver = _make_init_driver(monkeypatch, mock_fire=mock_fire)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver._fire_telemetry",
            mock_fire,
        )

        handle = driver._spawn("prompt")
        list(handle.events())
        handle.wait()

        exit_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "subprocess_exit"
        )
        payload = exit_call.args[1]
        assert "exit_code" in payload
        assert "is_error" in payload
        assert "wall_ms" in payload


# ---------------------------------------------------------------------------
# DriverExecutionError on non-zero exit
# ---------------------------------------------------------------------------


class TestDriverExecutionError:
    """On non-zero exit code, DriverExecutionError is raised after reading is_error."""

    def test_raises_driver_execution_error_on_nonzero_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Invariant: non-zero exit raises DriverExecutionError, never silently returns."""
        mock_proc = _make_mock_proc(returncode=1)
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        driver = _make_init_driver(monkeypatch)

        handle = driver._spawn("prompt")
        list(handle.events())  # exhaust the stream first
        with pytest.raises(DriverExecutionError):
            handle.wait()

    def test_reads_is_error_from_last_jsonl_line(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """is_error is read from the last stream-json event (not from exit code alone).

        Per spec: on non-zero exit, driver reads is_error from last stream-json line
        BEFORE raising DriverExecutionError.  DriverExecutionError is only triggered
        by non-zero exit; is_error from the event is reflected in the telemetry payload.
        This test verifies the event is parsed and the is_error field is propagated.
        """
        last_event = json.dumps({"type": "result", "is_error": True})
        # Non-zero exit so DriverExecutionError is raised after reading is_error.
        mock_proc = _make_mock_proc(stdout_lines=[last_event], returncode=1)
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        mock_fire = MagicMock()
        driver = _make_init_driver(monkeypatch, mock_fire=mock_fire)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver._fire_telemetry",
            mock_fire,
        )

        handle = driver._spawn("prompt")
        events = list(handle.events())

        # Verify the event was parsed and contains is_error
        assert len(events) == 1
        assert events[0]["is_error"] is True

        # On non-zero exit, DriverExecutionError is raised; is_error came from the event
        with pytest.raises(DriverExecutionError):
            handle.wait()

        # The subprocess_exit telemetry must reflect is_error=True from the event
        exit_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "subprocess_exit"
        )
        assert exit_call.args[1]["is_error"] is True

    def test_driver_execution_error_not_raised_on_exit_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """No DriverExecutionError when exit code is 0."""
        good_event = json.dumps({"type": "result", "is_error": False})
        mock_proc = _make_mock_proc(stdout_lines=[good_event], returncode=0)
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        driver = _make_init_driver(monkeypatch)

        handle = driver._spawn("prompt")
        list(handle.events())
        result = handle.wait()  # must not raise
        assert result.exit_code == 0
        assert result.is_error is False

    def test_is_error_from_last_event_used_when_nonzero_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """When exit code is non-zero, is_error field from last stream-json event is used."""
        last_event = json.dumps({"type": "result", "is_error": True})
        mock_proc = _make_mock_proc(stdout_lines=[last_event], returncode=1)
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        mock_fire = MagicMock()
        driver = _make_init_driver(monkeypatch, mock_fire=mock_fire)
        mock_fire.reset_mock()
        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver._fire_telemetry",
            mock_fire,
        )

        handle = driver._spawn("prompt")
        list(handle.events())
        with pytest.raises(DriverExecutionError):
            handle.wait()

        # The subprocess_exit event payload must reflect is_error from stream-json
        exit_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "subprocess_exit"
        )
        assert exit_call.args[1]["is_error"] is True


# ---------------------------------------------------------------------------
# _validate_uuid4 unit tests
# ---------------------------------------------------------------------------


class TestValidateUuid4:
    """_validate_uuid4 raises ValueError on non-UUID4 strings."""

    def test_valid_uuid4_does_not_raise(self):
        _validate_uuid4("12345678-1234-4234-b234-123456789abc")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _validate_uuid4("")

    def test_plain_string_raises(self):
        with pytest.raises(ValueError):
            _validate_uuid4("not-a-uuid-at-all")

    def test_uuid1_raises(self):
        # UUID1 — version=4 check must reject it
        with pytest.raises(ValueError):
            _validate_uuid4("12345678-1234-1234-b234-123456789abc")

    def test_uuid4_with_wrong_variant_raises(self):
        # Malformed: variant bits wrong
        with pytest.raises(ValueError):
            _validate_uuid4("12345678-1234-4234-0234-123456789abc")


# ---------------------------------------------------------------------------
# _redact_args unit tests
# ---------------------------------------------------------------------------


class TestRedactArgs:
    """_redact_args replaces secret values in args; does not mutate input."""

    def test_sk_prefix_redacted(self):
        result = _redact_args(["claude", "-p", "--bare", "sk-ant-secret123"])
        assert "<redacted>" in result
        assert "sk-ant-secret123" not in result

    def test_api_key_flag_value_redacted(self):
        result = _redact_args(["--api-key", "sk-ant-secret"])
        assert result[0] == "--api-key"
        assert result[1] == "<redacted>"

    def test_anthropic_api_key_env_redacted(self):
        result = _redact_args(["ANTHROPIC_API_KEY=sk-ant-super-secret"])
        assert result[0] == "ANTHROPIC_API_KEY=<redacted>"

    def test_non_secret_args_unchanged(self):
        args = ["claude", "-p", "--bare", "--output-format", "stream-json"]
        result = _redact_args(args)
        assert result == args

    def test_original_list_not_mutated(self):
        args = ["--api-key", "sk-ant-abc"]
        original = list(args)
        _redact_args(args)
        assert args == original


# ---------------------------------------------------------------------------
# _extract_is_error unit tests
# ---------------------------------------------------------------------------


class TestExtractIsError:
    """_extract_is_error uses last event's is_error field, falls back to exit code."""

    def test_last_event_is_error_true_overrides_exit_zero(self):
        events = [{"is_error": True}]
        assert _extract_is_error(events, exit_code=0) is True

    def test_last_event_is_error_false_overrides_exit_one(self):
        events = [{"is_error": False}]
        assert _extract_is_error(events, exit_code=1) is False

    def test_no_events_falls_back_to_exit_code(self):
        assert _extract_is_error([], exit_code=1) is True
        assert _extract_is_error([], exit_code=0) is False

    def test_last_event_without_is_error_falls_back_to_exit_code(self):
        events = [{"type": "text", "content": "hello"}]
        assert _extract_is_error(events, exit_code=1) is True


# ---------------------------------------------------------------------------
# Integration: dispatch() delegates to _spawn correctly
# ---------------------------------------------------------------------------


class TestDispatch:
    """dispatch() calls _spawn with the first element of args as prompt."""

    def test_dispatch_spawns_with_correct_env(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        captured_env: dict = {}

        def _fake_popen(argv, *, stdout, stderr, env):
            captured_env.update(env)
            return _make_mock_proc()

        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            _fake_popen,
        )
        driver = _make_init_driver(monkeypatch)
        driver.dispatch("z-ask", ["my prompt"], {"CLAUDECODE": "1", "PATH": "/bin"})

        assert captured_env.get("CLAUDECODE") == ""

    def test_dispatch_includes_bare_in_argv(self, monkeypatch: pytest.MonkeyPatch):
        captured_argv: list = []

        def _fake_popen(argv, *, stdout, stderr, env):
            captured_argv.extend(argv)
            return _make_mock_proc()

        monkeypatch.setattr(
            "runtime.drivers.claude.subprocess_driver.subprocess.Popen",
            _fake_popen,
        )
        driver = _make_init_driver(monkeypatch)
        driver.dispatch("z-ask", ["prompt"], _CLEAN_ENV)

        assert "--bare" in captured_argv
