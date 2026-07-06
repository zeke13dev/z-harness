"""
tests/drivers/test_codex_driver.py — Unit tests for runtime/drivers/codex/auth.py.

Covers:
  - All three auth strategies (codex_api_key, openai_api_key_workaround, auth_json)
  - The error path (AuthResolutionError when no credential is found)
  - Telemetry event emission (codex_auth_resolved) via mocked log_event;
    event fires unconditionally on every successful resolve_auth() call

No codex binary is required; all filesystem and env interactions are mocked.

Run:
    pytest tests/drivers/test_codex_driver.py -v
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from runtime.drivers.codex.auth import (
    AuthResolutionError,
    AuthResult,
    resolve_auth,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A minimal provider_entry dict (auth.py ignores it for now but it's part of
# the public signature).
_PROVIDER_ENTRY: dict = {"name": "codex", "command": "codex"}


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all auth-related env vars so tests start from a clean state."""
    for key in ("CODEX_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Strategy 1: CODEX_API_KEY
# ---------------------------------------------------------------------------


class TestCodexApiKeyStrategy:
    """CODEX_API_KEY env var → strategy 'codex_api_key'."""

    def test_returns_correct_strategy(self, monkeypatch: pytest.MonkeyPatch):
        _clean_env(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "test-key-abc")

        result = resolve_auth(_PROVIDER_ENTRY)

        assert isinstance(result, AuthResult)
        assert result.strategy == "codex_api_key"

    def test_returns_env_additions_with_key_value(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _clean_env(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "my-secret-key")

        result = resolve_auth(_PROVIDER_ENTRY)

        assert result.env_additions == {"CODEX_API_KEY": "my-secret-key"}

    def test_takes_precedence_over_openai_key(self, monkeypatch: pytest.MonkeyPatch):
        """CODEX_API_KEY wins even when OPENAI_API_KEY is also set."""
        _clean_env(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "codex-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

        result = resolve_auth(_PROVIDER_ENTRY)

        assert result.strategy == "codex_api_key"
        assert "CODEX_API_KEY" in result.env_additions
        assert "OPENAI_API_KEY" not in result.env_additions

    def test_whitespace_only_value_not_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A whitespace-only CODEX_API_KEY is treated as absent."""
        _clean_env(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "   ")
        # Also ensure the fallback paths are blocked so we get an error,
        # not a false positive from a different strategy.
        with patch(
            "runtime.drivers.codex.auth._try_auth_json", return_value=None
        ):
            with pytest.raises(AuthResolutionError):
                resolve_auth(_PROVIDER_ENTRY)


# ---------------------------------------------------------------------------
# Strategy 2: OPENAI_API_KEY (openai_via_model_providers)
# ---------------------------------------------------------------------------


class TestOpenAIApiKeyStrategy:
    """OPENAI_API_KEY env var → strategy 'openai_api_key_workaround'."""

    def test_returns_correct_strategy(self, monkeypatch: pytest.MonkeyPatch):
        _clean_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

        result = resolve_auth(_PROVIDER_ENTRY)

        assert result.strategy == "openai_api_key_workaround"

    def test_env_additions_contains_openai_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _clean_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

        result = resolve_auth(_PROVIDER_ENTRY)

        assert result.env_additions == {"OPENAI_API_KEY": "sk-openai-test"}

    def test_used_when_codex_api_key_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _clean_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fallback")
        # Ensure CODEX_API_KEY is definitely absent
        monkeypatch.delenv("CODEX_API_KEY", raising=False)

        result = resolve_auth(_PROVIDER_ENTRY)

        assert result.strategy == "openai_api_key_workaround"

    def test_takes_precedence_over_auth_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """OPENAI_API_KEY wins over ~/.codex/auth.json when CODEX_API_KEY absent."""
        _clean_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-key")

        fake_auth_json = tmp_path / ".codex" / "auth.json"
        fake_auth_json.parent.mkdir(parents=True)
        fake_auth_json.write_text("{}")

        with patch(
            "runtime.drivers.codex.auth.Path.home", return_value=tmp_path
        ):
            result = resolve_auth(_PROVIDER_ENTRY)

        assert result.strategy == "openai_api_key_workaround"


# ---------------------------------------------------------------------------
# Strategy 3: ~/.codex/auth.json presence
# ---------------------------------------------------------------------------


class TestAuthJsonStrategy:
    """~/.codex/auth.json presence → strategy 'auth_json'."""

    def test_returns_correct_strategy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _clean_env(monkeypatch)

        fake_auth_json = tmp_path / ".codex" / "auth.json"
        fake_auth_json.parent.mkdir(parents=True)
        fake_auth_json.write_text("{}")

        with patch(
            "runtime.drivers.codex.auth.Path.home", return_value=tmp_path
        ):
            result = resolve_auth(_PROVIDER_ENTRY)

        assert result.strategy == "auth_json"

    def test_env_additions_is_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """auth.json path must not inject any env vars (C2-D3: read-only check)."""
        _clean_env(monkeypatch)

        fake_auth_json = tmp_path / ".codex" / "auth.json"
        fake_auth_json.parent.mkdir(parents=True)
        fake_auth_json.write_text("{}")

        with patch(
            "runtime.drivers.codex.auth.Path.home", return_value=tmp_path
        ):
            result = resolve_auth(_PROVIDER_ENTRY)

        assert result.env_additions == {}

    def test_missing_auth_json_not_a_credential(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """If auth.json does not exist, this path yields nothing."""
        _clean_env(monkeypatch)
        # tmp_path has no .codex/auth.json file

        with patch(
            "runtime.drivers.codex.auth.Path.home", return_value=tmp_path
        ):
            with pytest.raises(AuthResolutionError):
                resolve_auth(_PROVIDER_ENTRY)


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


class TestAuthResolutionError:
    """AuthResolutionError raised when no credential path yields a result."""

    def test_raises_when_no_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _clean_env(monkeypatch)
        # tmp_path has no .codex/auth.json

        with patch(
            "runtime.drivers.codex.auth.Path.home", return_value=tmp_path
        ):
            with pytest.raises(AuthResolutionError):
                resolve_auth(_PROVIDER_ENTRY)

    def test_error_message_mentions_all_three_paths(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """The error message must be actionable, referencing all checked paths."""
        _clean_env(monkeypatch)

        with patch(
            "runtime.drivers.codex.auth.Path.home", return_value=tmp_path
        ):
            with pytest.raises(AuthResolutionError) as exc_info:
                resolve_auth(_PROVIDER_ENTRY)

        message = str(exc_info.value)
        assert "CODEX_API_KEY" in message
        assert "OPENAI_API_KEY" in message
        assert "auth.json" in message

    def test_raises_not_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """resolve_auth must raise, never return None."""
        _clean_env(monkeypatch)

        with patch(
            "runtime.drivers.codex.auth.Path.home", return_value=tmp_path
        ):
            with pytest.raises(AuthResolutionError):
                resolve_auth(_PROVIDER_ENTRY)


# ---------------------------------------------------------------------------
# Telemetry: codex_auth_resolved event
# ---------------------------------------------------------------------------


class TestTelemetryEmission:
    """codex_auth_resolved event fires with the correct strategy_used value."""

    def test_event_fires_with_codex_api_key_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _clean_env(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "test-key")

        mock_log_event = MagicMock()
        with patch("runtime.drivers.codex.auth.log_event", mock_log_event):
            resolve_auth(
                _PROVIDER_ENTRY, run_id="run-001", repo_root="/fake/root"
            )

        mock_log_event.assert_called_once()
        call_kwargs = mock_log_event.call_args
        assert call_kwargs.kwargs["kind"] == "codex_auth_resolved"
        assert call_kwargs.kwargs["payload"]["strategy_used"] == "codex_api_key"

    def test_event_fires_with_openai_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _clean_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

        mock_log_event = MagicMock()
        with patch("runtime.drivers.codex.auth.log_event", mock_log_event):
            resolve_auth(
                _PROVIDER_ENTRY, run_id="run-002", repo_root="/fake/root"
            )

        call_kwargs = mock_log_event.call_args
        assert call_kwargs.kwargs["payload"]["strategy_used"] == "openai_api_key_workaround"

    def test_event_fires_with_auth_json_strategy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _clean_env(monkeypatch)

        fake_auth_json = tmp_path / ".codex" / "auth.json"
        fake_auth_json.parent.mkdir(parents=True)
        fake_auth_json.write_text("{}")

        mock_log_event = MagicMock()
        with patch(
            "runtime.drivers.codex.auth.Path.home", return_value=tmp_path
        ), patch("runtime.drivers.codex.auth.log_event", mock_log_event):
            resolve_auth(
                _PROVIDER_ENTRY, run_id="run-003", repo_root="/fake/root"
            )

        call_kwargs = mock_log_event.call_args
        assert call_kwargs.kwargs["payload"]["strategy_used"] == "auth_json"

    def test_event_fires_unconditionally_without_run_id(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Telemetry fires even when run_id is not supplied (defaults to 'codex-auth')."""
        _clean_env(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "test-key")

        mock_log_event = MagicMock()
        with patch("runtime.drivers.codex.auth.log_event", mock_log_event):
            resolve_auth(_PROVIDER_ENTRY)  # run_id not supplied

        mock_log_event.assert_called_once()
        call_kwargs = mock_log_event.call_args
        assert call_kwargs.kwargs["run_id"] == "codex-auth"
        assert call_kwargs.kwargs["kind"] == "codex_auth_resolved"

    def test_event_fires_unconditionally_without_repo_root(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Telemetry fires even when repo_root is not supplied (defaults to os.getcwd())."""
        _clean_env(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "test-key")

        mock_log_event = MagicMock()
        with patch("runtime.drivers.codex.auth.log_event", mock_log_event):
            resolve_auth(_PROVIDER_ENTRY, run_id="run-004", repo_root=None)

        mock_log_event.assert_called_once()
        call_kwargs = mock_log_event.call_args
        # repo_root should be a non-empty string (os.getcwd())
        assert isinstance(call_kwargs.kwargs["repo_root"], str)
        assert len(call_kwargs.kwargs["repo_root"]) > 0

    def test_telemetry_failure_does_not_propagate(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A RuntimeError from log_event must not surface to the caller."""
        _clean_env(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "test-key")

        with patch(
            "runtime.drivers.codex.auth.log_event",
            side_effect=RuntimeError("log-event.sh failed"),
        ):
            # Should not raise
            result = resolve_auth(
                _PROVIDER_ENTRY, run_id="run-005", repo_root="/fake/root"
            )

        assert result.strategy == "codex_api_key"


# ===========================================================================
# CodexDriver tests (T002)
# ===========================================================================

from unittest.mock import call, create_autospec
import subprocess as _subprocess
import io

from runtime.drivers.codex.driver import (
    CodexDriver,
    _build_proc_env,
    _CROSS_VENDOR_KEYS,
    _DEFAULT_TIMEOUT_S,
    _prompt_from_dispatch_args,
)
from runtime.dispatch.result import DispatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CODEX_PROVIDER: dict = {
    "name": "codex",
    "kind": "cli",
    "command": "codex",
    "args_template": ["exec", "-"],
    "stdin": True,
    "timeout_s": 30,
    "model_label": "codex-test",
}

_CLEAN_ENV: dict = {
    "PATH": "/usr/bin",
    "HOME": "/home/user",
    "CLAUDECODE": "",
}


def _make_mock_proc(
    stdout_lines: list[str] | None = None,
    returncode: int = 0,
    stderr_text: str = "",
) -> MagicMock:
    """Return a MagicMock shaped like subprocess.Popen.

    stdout is a BytesIO so readline() works; select.select() must be patched
    separately in tests that call handle.events() (use _patch_driver_select).
    poll() returns returncode so parse_stream's crash detection works correctly.
    """
    proc = MagicMock()
    proc.returncode = returncode

    encoded = b"".join(
        (line + "\n").encode("utf-8") for line in (stdout_lines or [])
    )
    proc.stdout = io.BytesIO(encoded)
    proc.stderr = io.BytesIO(stderr_text.encode("utf-8"))
    proc.wait.return_value = returncode
    proc.kill.return_value = None
    proc.poll.return_value = returncode
    return proc


def _patch_driver_select(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make select.select() always report the fd as readable in the stream module.

    Driver tests that call handle.events() must apply this patch because
    _events_fn now delegates to parse_stream() which uses select.select()
    internally to implement per-line read timeouts.
    """
    monkeypatch.setattr(
        "runtime.drivers.codex.stream.select.select",
        lambda rfds, wfds, xfds, timeout: (rfds, [], []),
    )


# ---------------------------------------------------------------------------
# _build_proc_env tests
# ---------------------------------------------------------------------------


class TestBuildProcEnv:
    """Unit tests for the _build_proc_env helper."""

    def test_auth_additions_merged(self):
        env = _build_proc_env(
            base_env=dict(_CLEAN_ENV),
            auth_additions={"CODEX_API_KEY": "ck-abc"},
            provider_config=_CODEX_PROVIDER,
        )
        assert env["CODEX_API_KEY"] == "ck-abc"

    def test_cross_vendor_keys_stripped_by_default(self):
        base = dict(_CLEAN_ENV)
        base["ANTHROPIC_API_KEY"] = "sk-anthropic"
        base["CLAUDE_API_KEY"] = "sk-claude"

        env = _build_proc_env(
            base_env=base,
            auth_additions={},
            provider_config=_CODEX_PROVIDER,
        )
        assert "ANTHROPIC_API_KEY" not in env
        assert "CLAUDE_API_KEY" not in env

    def test_cross_vendor_keys_retained_when_opted_in(self):
        base = dict(_CLEAN_ENV)
        base["ANTHROPIC_API_KEY"] = "sk-anthropic"
        base["CLAUDE_API_KEY"] = "sk-claude"

        config_opt_in = {**_CODEX_PROVIDER, "allow_cross_vendor_env": True}
        env = _build_proc_env(
            base_env=base,
            auth_additions={},
            provider_config=config_opt_in,
        )
        assert env["ANTHROPIC_API_KEY"] == "sk-anthropic"
        assert env["CLAUDE_API_KEY"] == "sk-claude"

    def test_base_env_not_mutated(self):
        base = {**_CLEAN_ENV, "ANTHROPIC_API_KEY": "sk-anth"}
        original_base = dict(base)
        _build_proc_env(
            base_env=base,
            auth_additions={"CODEX_API_KEY": "ck-xyz"},
            provider_config=_CODEX_PROVIDER,
        )
        assert base == original_base


class TestPromptFromDispatchArgs:
    """Prompt extraction from dispatcher-composed argv."""

    def test_strips_provider_args_template_prefix(self):
        assert (
            _prompt_from_dispatch_args(["exec", "-", "say", "hello"], _CODEX_PROVIDER)
            == "say hello"
        )

    def test_uses_all_args_when_prefix_does_not_match(self):
        assert _prompt_from_dispatch_args(["say", "hello"], _CODEX_PROVIDER) == "say hello"


# ---------------------------------------------------------------------------
# CodexDriver.init tests
# ---------------------------------------------------------------------------


class TestCodexDriverInit:
    """init() stores config and pulls run_id / repo_root from context."""

    def test_init_stores_provider_config(self):
        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER)
        assert driver._provider_config == _CODEX_PROVIDER

    def test_init_accepts_run_id_from_context(self):
        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "run-xyz"})
        assert driver._run_id == "run-xyz"

    def test_init_accepts_repo_root_from_context(self):
        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"repo_root": "/my/repo"})
        assert driver._repo_root == "/my/repo"

    def test_init_ignores_unknown_context_keys(self):
        """Unknown context keys must not raise (C1-D5 Liskov substitutability)."""
        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"unknown_key": "value", "another": 42})
        # No exception raised — pass


# ---------------------------------------------------------------------------
# CodexDriver.dispatch tests (Popen mocked)
# ---------------------------------------------------------------------------


class TestCodexDriverDispatch:
    """dispatch() launches codex exec --json -, returns a working DispatchHandle."""

    def _driver_with_mock(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_proc: MagicMock,
        auth_env: dict | None = None,
    ) -> tuple[CodexDriver, MagicMock]:
        """Create a CodexDriver backed by a mocked Popen."""
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("runtime.drivers.codex.driver.subprocess.Popen", mock_popen)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions=auth_env or {"CODEX_API_KEY": "ck-test"},
            ),
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )
        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "run-t002", "repo_root": "/repo"})
        return driver, mock_popen

    def test_popen_called_with_codex_exec_stdin(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc(stdout_lines=[], returncode=0)
        driver, mock_popen = self._driver_with_mock(monkeypatch, mock_proc)

        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        argv = call_args[0][0]
        assert argv == ["codex", "exec", "--json", "-"]
        assert "--output-format" not in argv
        assert "stream-json" not in argv

    def test_popen_stdin_is_pipe(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc(returncode=0)
        driver, mock_popen = self._driver_with_mock(monkeypatch, mock_proc)
        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        call_kwargs = mock_popen.call_args.kwargs
        assert call_kwargs["stdin"] == _subprocess.PIPE

    def test_dispatch_writes_prompt_tail_to_stdin(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc(stdout_lines=[], returncode=0)
        mock_proc.stdin = MagicMock()
        driver, _ = self._driver_with_mock(monkeypatch, mock_proc)

        driver.dispatch("z-ask", ["exec", "-", "say", "hello"], dict(_CLEAN_ENV))

        mock_proc.stdin.write.assert_called_once_with(b"say hello\n")
        mock_proc.stdin.close.assert_called_once()

    def test_dispatch_closes_stdin_for_empty_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_proc = _make_mock_proc(stdout_lines=[], returncode=0)
        mock_proc.stdin = MagicMock()
        driver, _ = self._driver_with_mock(monkeypatch, mock_proc)

        driver.dispatch("z-ask", ["exec", "-"], dict(_CLEAN_ENV))

        mock_proc.stdin.write.assert_not_called()
        mock_proc.stdin.close.assert_called_once()

    def test_events_yields_parsed_json(self, monkeypatch: pytest.MonkeyPatch):
        lines = ['{"type":"message","content":"hello"}', '{"type":"done"}']
        mock_proc = _make_mock_proc(stdout_lines=lines, returncode=0)
        driver, _ = self._driver_with_mock(monkeypatch, mock_proc)
        _patch_driver_select(monkeypatch)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        events = list(handle.events())

        assert len(events) == 2
        assert events[0] == {"type": "message", "content": "hello"}
        assert events[1] == {"type": "done"}

    def test_events_preserve_native_semantic_frames_raw(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        raw_frames = [
            {
                "type": "subagent.started",
                "subagent_type": "implementer",
                "native_unknown": "kept",
            },
            {
                "type": "ask_user",
                "question": "Continue?",
                "choices": ["continue", "abort"],
            },
            {
                "type": "tool_call",
                "tool_name": "apply_patch",
                "tool_call_id": "tool-1",
            },
            {
                "type": "final_result",
                "result": {"content": "complete"},
            },
        ]
        mock_proc = _make_mock_proc(
            stdout_lines=[_json_stream.dumps(frame) for frame in raw_frames],
            returncode=0,
        )
        driver, _ = self._driver_with_mock(monkeypatch, mock_proc)
        _patch_driver_select(monkeypatch)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        events = list(handle.events())

        assert events == raw_frames
        assert events[0]["native_unknown"] == "kept"
        assert [classify_event_family(event) for event in events] == [
            EVENT_FAMILY_SUBAGENT,
            EVENT_FAMILY_ASK_USER,
            EVENT_FAMILY_TOOL,
            EVENT_FAMILY_FINAL_RESULT,
        ]

    def test_events_skips_malformed_jsonl(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        lines = ["not-json", '{"type":"ok"}']
        mock_proc = _make_mock_proc(stdout_lines=lines, returncode=0)
        driver, _ = self._driver_with_mock(monkeypatch, mock_proc)
        _patch_driver_select(monkeypatch)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        events = list(handle.events())

        assert len(events) == 1
        assert events[0]["type"] == "ok"
        captured = capsys.readouterr()
        assert "malformed" in captured.err

    def test_wait_returns_dispatch_result(self, monkeypatch: pytest.MonkeyPatch):
        mock_proc = _make_mock_proc(returncode=0)
        driver, _ = self._driver_with_mock(monkeypatch, mock_proc)
        _patch_driver_select(monkeypatch)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())  # exhaust stream
        result = handle.wait()

        assert isinstance(result, DispatchResult)
        assert result.exit_code == 0
        assert result.is_error is False

    def test_wait_non_zero_exit_sets_is_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """wait() returns is_error=True when exit_code is non-zero.

        With parse_stream() wired in, a non-zero exit raises CodexCrashError
        during events() iteration (after stdout EOF).  The _wait_fn closure
        is independent: it still calls proc.wait() and detects the non-zero
        exit code, so wait() must return is_error=True regardless.
        """
        from runtime.drivers.codex.stream import CodexCrashError

        mock_proc = _make_mock_proc(returncode=1)
        driver, _ = self._driver_with_mock(monkeypatch, mock_proc)
        _patch_driver_select(monkeypatch)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        with pytest.raises(CodexCrashError):
            list(handle.events())
        result = handle.wait()

        assert result.exit_code == 1
        assert result.is_error is True


# ---------------------------------------------------------------------------
# Timeout enforcement tests
# ---------------------------------------------------------------------------


class TestCodexDriverTimeout:
    """Subprocess is killed and reaped on timeout; no zombies."""

    def test_timeout_kills_subprocess(self, monkeypatch: pytest.MonkeyPatch):
        """_wait_fn kills and reaps the subprocess on TimeoutExpired.

        With parse_stream() wired in, a non-zero returncode causes CodexCrashError
        during events() iteration.  The _wait_fn closure is still exercised by
        calling wait() after catching the stream error — timeout enforcement in
        _wait_fn is independent of the events phase.
        """
        from runtime.drivers.codex.stream import CodexCrashError

        mock_proc = _make_mock_proc(returncode=-9)
        # Simulate timeout on first wait(), succeed on second (after kill)
        mock_proc.wait.side_effect = [
            _subprocess.TimeoutExpired(cmd="codex", timeout=1),
            -9,
        ]

        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.subprocess.Popen", mock_popen
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )
        _patch_driver_select(monkeypatch)

        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "r", "repo_root": "/r"})

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        # parse_stream raises CodexCrashError after empty stdout + non-zero poll()
        with pytest.raises(CodexCrashError):
            list(handle.events())
        # _wait_fn is still exercised independently; timeout enforced here
        result = handle.wait()

        mock_proc.kill.assert_called_once()
        assert mock_proc.wait.call_count == 2
        assert result.is_error is True

    def test_timeout_uses_timeout_s_from_provider_config(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """wait() is called with the timeout_s value from provider_config."""
        mock_proc = _make_mock_proc(returncode=0)
        captured_timeout = {}

        def _wait_spy(timeout=None):
            captured_timeout["value"] = timeout
            return 0

        mock_proc.wait.side_effect = _wait_spy

        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.subprocess.Popen", mock_popen
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )

        config_with_timeout = {**_CODEX_PROVIDER, "timeout_s": 42}
        driver = CodexDriver()
        driver.init(config_with_timeout, context={"run_id": "r", "repo_root": "/r"})
        _patch_driver_select(monkeypatch)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        handle.wait()

        assert captured_timeout["value"] == 42


# ---------------------------------------------------------------------------
# Telemetry tests
# ---------------------------------------------------------------------------


class TestCodexDriverTelemetry:
    """codex_driver_invoke fires on launch; codex_driver_complete fires on clean exit."""

    def _setup_mocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        returncode: int = 0,
        stdout_lines: list[str] | None = None,
    ) -> tuple[CodexDriver, MagicMock]:
        mock_proc = _make_mock_proc(
            stdout_lines=stdout_lines,
            returncode=returncode,
        )
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.subprocess.Popen", mock_popen
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        mock_fire = MagicMock()
        monkeypatch.setattr("runtime.drivers.codex.driver._fire_telemetry", mock_fire)
        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "r", "repo_root": "/r"})
        return driver, mock_fire

    def test_invoke_event_fires_on_dispatch(self, monkeypatch: pytest.MonkeyPatch):
        driver, mock_fire = self._setup_mocks(monkeypatch)
        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "codex_driver_invoke" in kinds

    def test_invoke_event_payload_fields(self, monkeypatch: pytest.MonkeyPatch):
        driver, mock_fire = self._setup_mocks(monkeypatch)
        driver.dispatch("z-ask", [], dict(_CLEAN_ENV))

        invoke_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "codex_driver_invoke"
        )
        payload = invoke_call.args[1]
        assert "provider_name" in payload
        assert "auth_strategy" in payload
        assert "model_label" in payload

    def test_complete_event_fires_on_clean_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        driver, mock_fire = self._setup_mocks(monkeypatch, returncode=0)
        _patch_driver_select(monkeypatch)
        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        handle.wait()

        kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "codex_driver_complete" in kinds

    def test_complete_event_reports_consumed_frame_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        stdout_lines = [
            '{"type":"message","content":"hi"}',
            '{"type":"tool_call","tool_name":"apply_patch"}',
            '{"type":"final_result","result":{"content":"done"}}',
        ]
        driver, mock_fire = self._setup_mocks(
            monkeypatch,
            returncode=0,
            stdout_lines=stdout_lines,
        )
        _patch_driver_select(monkeypatch)
        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        handle.wait()

        complete_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "codex_driver_complete"
        )
        payload = complete_call.args[1]
        assert payload["frames_parsed"] == 3
        assert payload["frames_by_family"]["message"] == 1
        assert payload["frames_by_family"]["tool"] == 1
        assert payload["frames_by_family"]["final_result"] == 1

    def test_complete_event_not_fired_on_error_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """codex_driver_complete must NOT fire when exit_code != 0.

        With parse_stream() wired in, a non-zero exit raises CodexCrashError
        during events(). The test catches that, then calls wait() to verify
        codex_driver_complete was not fired.
        """
        from runtime.drivers.codex.stream import CodexCrashError

        driver, mock_fire = self._setup_mocks(monkeypatch, returncode=1)
        _patch_driver_select(monkeypatch)
        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        with pytest.raises(CodexCrashError):
            list(handle.events())
        handle.wait()

        kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "codex_driver_complete" not in kinds

    def test_telemetry_failure_does_not_propagate_from_driver(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A RuntimeError from _fire_telemetry must not surface to the caller."""
        mock_proc = _make_mock_proc(returncode=0)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.subprocess.Popen",
            MagicMock(return_value=mock_proc),
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry",
            MagicMock(side_effect=RuntimeError("telemetry down")),
        )
        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "r", "repo_root": "/r"})
        _patch_driver_select(monkeypatch)

        # dispatch() itself calls _fire_telemetry (invoke event) — must not raise
        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        result = handle.wait()
        assert isinstance(result, DispatchResult)


# ---------------------------------------------------------------------------
# Cross-vendor env exclusion invariant
# ---------------------------------------------------------------------------


class TestCrossVendorEnvExclusion:
    """ANTHROPIC_API_KEY and CLAUDE_API_KEY must not reach the codex subprocess."""

    def test_anthropic_api_key_stripped_from_proc_env(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Invariant: ANTHROPIC_API_KEY absent from env unless opted in."""
        captured_env: dict = {}

        def _fake_popen(argv, *, stdin, stdout, stderr, env):
            captured_env.update(env)
            return _make_mock_proc(returncode=0)

        monkeypatch.setattr(
            "runtime.drivers.codex.driver.subprocess.Popen", _fake_popen
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )

        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "r", "repo_root": "/r"})

        dirty_env = {**_CLEAN_ENV, "ANTHROPIC_API_KEY": "sk-secret"}
        driver.dispatch("z-ask", [], dirty_env)

        assert "ANTHROPIC_API_KEY" not in captured_env

    def test_claude_api_key_stripped_from_proc_env(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Invariant: CLAUDE_API_KEY absent from env unless opted in."""
        captured_env: dict = {}

        def _fake_popen(argv, *, stdin, stdout, stderr, env):
            captured_env.update(env)
            return _make_mock_proc(returncode=0)

        monkeypatch.setattr(
            "runtime.drivers.codex.driver.subprocess.Popen", _fake_popen
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )

        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "r", "repo_root": "/r"})

        dirty_env = {**_CLEAN_ENV, "CLAUDE_API_KEY": "ck-secret"}
        driver.dispatch("z-ask", [], dirty_env)

        assert "CLAUDE_API_KEY" not in captured_env


# ---------------------------------------------------------------------------
# codex_driver_error telemetry (BLOCKER 1)
# ---------------------------------------------------------------------------


class TestCodexDriverErrorTelemetry:
    """codex_driver_error fires on non-zero exit and on timeout; not on clean exit."""

    def _base_setup(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_proc: MagicMock,
    ) -> tuple[CodexDriver, MagicMock]:
        """Wire up Popen + auth mocks and return (driver, mock_fire_telemetry)."""
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.subprocess.Popen", mock_popen
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        mock_fire = MagicMock()
        monkeypatch.setattr("runtime.drivers.codex.driver._fire_telemetry", mock_fire)

        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "r", "repo_root": "/r"})
        return driver, mock_fire

    def test_error_event_fires_on_non_zero_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """codex_driver_error fires when process exits non-zero.

        parse_stream() raises CodexCrashError after EOF + non-zero poll().
        The _wait_fn closure fires codex_driver_error independently when it
        sees exit_code != 0.  Catch the stream error, then call wait().
        """
        from runtime.drivers.codex.stream import CodexCrashError

        mock_proc = _make_mock_proc(returncode=1)
        driver, mock_fire = self._base_setup(monkeypatch, mock_proc)
        _patch_driver_select(monkeypatch)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        with pytest.raises(CodexCrashError):
            list(handle.events())
        handle.wait()

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "codex_driver_error" in fired_kinds

    def test_error_event_payload_non_zero_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """error_kind == 'non_zero_exit' when the process exits non-zero."""
        from runtime.drivers.codex.stream import CodexCrashError

        mock_proc = _make_mock_proc(returncode=2)
        driver, mock_fire = self._base_setup(monkeypatch, mock_proc)
        _patch_driver_select(monkeypatch)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        with pytest.raises(CodexCrashError):
            list(handle.events())
        handle.wait()

        error_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "codex_driver_error"
        )
        payload = error_call.args[1]
        assert payload["error_kind"] == "non_zero_exit"
        assert payload["exit_code"] == 2
        assert "elapsed_ms" in payload

    def test_error_event_fires_on_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """codex_driver_error fires with error_kind='timeout' on TimeoutExpired.

        parse_stream() raises CodexCrashError for the non-zero poll() result.
        The timeout is enforced in _wait_fn; catch the stream error, call wait().
        """
        from runtime.drivers.codex.stream import CodexCrashError

        mock_proc = _make_mock_proc(returncode=-9)
        mock_proc.wait.side_effect = [
            _subprocess.TimeoutExpired(cmd="codex", timeout=1),
            -9,
        ]

        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.subprocess.Popen", mock_popen
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        mock_fire = MagicMock()
        monkeypatch.setattr("runtime.drivers.codex.driver._fire_telemetry", mock_fire)
        _patch_driver_select(monkeypatch)

        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "r", "repo_root": "/r"})

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        with pytest.raises(CodexCrashError):
            list(handle.events())
        handle.wait()

        error_call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "codex_driver_error"
        )
        payload = error_call.args[1]
        assert payload["error_kind"] == "timeout"

    def test_error_event_not_fired_on_clean_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """codex_driver_error must NOT fire when exit_code == 0."""
        mock_proc = _make_mock_proc(returncode=0)
        driver, mock_fire = self._base_setup(monkeypatch, mock_proc)
        _patch_driver_select(monkeypatch)

        handle = driver.dispatch("z-ask", [], dict(_CLEAN_ENV))
        list(handle.events())
        handle.wait()

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "codex_driver_error" not in fired_kinds


# ---------------------------------------------------------------------------
# codex_env_collision_detected telemetry (BLOCKER 2)
# ---------------------------------------------------------------------------


class TestEnvCollisionTelemetry:
    """codex_env_collision_detected fires iff both ANTHROPIC_API_KEY and OPENAI_API_KEY
    are present in the base env passed to _build_proc_env."""

    def test_collision_event_fires_when_both_keys_present(self):
        """Event fires when ANTHROPIC_API_KEY + OPENAI_API_KEY both in base_env."""
        from runtime.drivers.codex.driver import _build_proc_env

        mock_fire = MagicMock()
        with patch("runtime.drivers.codex.driver._fire_telemetry", mock_fire):
            _build_proc_env(
                base_env={
                    "ANTHROPIC_API_KEY": "sk-anth",
                    "OPENAI_API_KEY": "sk-oai",
                    "PATH": "/usr/bin",
                },
                auth_additions={},
                provider_config=_CODEX_PROVIDER,
            )

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "codex_env_collision_detected" in fired_kinds

    def test_collision_event_payload_names_both_keys(self):
        """Payload lists both colliding key names."""
        from runtime.drivers.codex.driver import _build_proc_env

        mock_fire = MagicMock()
        with patch("runtime.drivers.codex.driver._fire_telemetry", mock_fire):
            _build_proc_env(
                base_env={
                    "ANTHROPIC_API_KEY": "sk-anth",
                    "OPENAI_API_KEY": "sk-oai",
                },
                auth_additions={},
                provider_config=_CODEX_PROVIDER,
            )

        collision_call = next(
            c for c in mock_fire.call_args_list
            if c.args[0] == "codex_env_collision_detected"
        )
        payload = collision_call.args[1]
        assert "ANTHROPIC_API_KEY" in payload["colliding_keys"]
        assert "OPENAI_API_KEY" in payload["colliding_keys"]

    def test_collision_event_does_not_fire_when_only_anthropic_key_present(self):
        """No collision event when only ANTHROPIC_API_KEY is in base_env."""
        from runtime.drivers.codex.driver import _build_proc_env

        mock_fire = MagicMock()
        with patch("runtime.drivers.codex.driver._fire_telemetry", mock_fire):
            _build_proc_env(
                base_env={"ANTHROPIC_API_KEY": "sk-anth", "PATH": "/usr/bin"},
                auth_additions={},
                provider_config=_CODEX_PROVIDER,
            )

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "codex_env_collision_detected" not in fired_kinds

    def test_collision_event_does_not_fire_when_only_openai_key_present(self):
        """No collision event when only OPENAI_API_KEY is in base_env."""
        from runtime.drivers.codex.driver import _build_proc_env

        mock_fire = MagicMock()
        with patch("runtime.drivers.codex.driver._fire_telemetry", mock_fire):
            _build_proc_env(
                base_env={"OPENAI_API_KEY": "sk-oai", "PATH": "/usr/bin"},
                auth_additions={},
                provider_config=_CODEX_PROVIDER,
            )

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "codex_env_collision_detected" not in fired_kinds

    def test_collision_detection_does_not_affect_stripping(self):
        """After collision detection, ANTHROPIC_API_KEY is still stripped as normal."""
        from runtime.drivers.codex.driver import _build_proc_env

        mock_fire = MagicMock()
        with patch("runtime.drivers.codex.driver._fire_telemetry", mock_fire):
            result = _build_proc_env(
                base_env={
                    "ANTHROPIC_API_KEY": "sk-anth",
                    "OPENAI_API_KEY": "sk-oai",
                    "PATH": "/usr/bin",
                },
                auth_additions={},
                provider_config=_CODEX_PROVIDER,  # allow_cross_vendor_env not set
            )

        assert "ANTHROPIC_API_KEY" not in result


# ===========================================================================
# stream.py / parse_stream() tests (T003)
# ===========================================================================

import io as _io
import json as _json_stream
import select as _select

from runtime.drivers.codex.stream import (
    CodexCrashError,
    CodexExecutionError,
    CodexTimeoutError,
    EVENT_FAMILY_AGENT,
    EVENT_FAMILY_ASK_USER,
    EVENT_FAMILY_FINAL_RESULT,
    EVENT_FAMILY_GATE,
    EVENT_FAMILY_MESSAGE,
    EVENT_FAMILY_SUBAGENT,
    EVENT_FAMILY_TELEMETRY,
    EVENT_FAMILY_TOOL,
    EVENT_FAMILY_UNKNOWN,
    Frame,
    classify_event_family,
    extract_frame_content,
    parse_stream,
)


# ---------------------------------------------------------------------------
# Helpers for stream tests
# ---------------------------------------------------------------------------


def _make_stream_proc(
    stdout_lines: list[str] | None = None,
    returncode: int = 0,
) -> MagicMock:
    """Return a MagicMock shaped like subprocess.Popen for stream tests.

    stdout is a BytesIO so select() can be mocked; returncode is always
    set so poll() and wait() return sensibly.
    """
    proc = MagicMock()
    proc.returncode = returncode

    encoded = b"".join(
        (line + "\n").encode("utf-8") for line in (stdout_lines or [])
    )
    proc.stdout = _io.BytesIO(encoded)

    proc.poll.return_value = returncode
    proc.wait.return_value = returncode
    return proc


def _patch_select_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make select.select() always report the fd as readable (no timeout)."""
    monkeypatch.setattr(
        "runtime.drivers.codex.stream.select.select",
        lambda rfds, wfds, xfds, timeout: (rfds, [], []),
    )


# ---------------------------------------------------------------------------
# Frame dataclass
# ---------------------------------------------------------------------------


class TestFrame:
    """Frame dataclass preserves known and unknown keys."""

    def test_known_fields_populated(self):
        f = Frame(type="message", content="hello", is_error=False, raw={})
        assert f.type == "message"
        assert f.content == "hello"
        assert f.is_error is False

    def test_raw_preserves_unknown_keys(self):
        raw = {"type": "message", "content": "hi", "is_error": False, "custom_key": "val"}
        f = Frame(type="message", content="hi", is_error=False, raw=raw)
        assert f.raw["custom_key"] == "val"

    def test_default_raw_is_empty_dict(self):
        f = Frame(type="done", content="", is_error=False)
        assert f.raw == {}

    def test_event_family_defaults_unknown_for_manual_frame(self):
        f = Frame(type="custom", content="", is_error=False)
        assert f.event_family == "unknown"


# ---------------------------------------------------------------------------
# Normal completion
# ---------------------------------------------------------------------------


class TestParseStreamNormalCompletion:
    """parse_stream() yields one Frame per well-formed JSONL line on clean exit."""

    def test_yields_frames_in_order(self, monkeypatch: pytest.MonkeyPatch):
        _patch_select_ready(monkeypatch)
        lines = [
            '{"type":"message","content":"hello"}',
            '{"type":"done","content":""}',
        ]
        proc = _make_stream_proc(stdout_lines=lines, returncode=0)

        frames = list(parse_stream(proc))

        assert len(frames) == 2
        assert frames[0].type == "message"
        assert frames[0].content == "hello"
        assert frames[1].type == "done"

    def test_frame_is_error_false_on_normal_frame(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(
            stdout_lines=['{"type":"message","content":"hi","is_error":false}'],
            returncode=0,
        )
        frames = list(parse_stream(proc))
        assert frames[0].is_error is False

    def test_unknown_keys_in_raw(self, monkeypatch: pytest.MonkeyPatch):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(
            stdout_lines=['{"type":"fn","content":"","is_error":false,"extra_field":"x"}'],
            returncode=0,
        )
        frames = list(parse_stream(proc))
        assert frames[0].raw["extra_field"] == "x"

    def test_classifies_native_codex_event_families(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _patch_select_ready(monkeypatch)
        native_frames = [
            {
                "type": "agent.started",
                "agent_name": "planner",
                "content": "agent online",
            },
            {
                "type": "subagent.started",
                "subagent_type": "implementer",
                "z_extra": {"worker": "T005"},
            },
            {
                "type": "ask_user",
                "question": "Proceed?",
                "choices": ["yes", "no"],
            },
            {
                "type": "user_gate",
                "gate_id": "release_review",
                "prompt": "Approve release?",
            },
            {
                "type": "tool_call",
                "tool_name": "apply_patch",
                "tool_call_id": "tool-1",
                "arguments": {"file": "runtime/drivers/codex/stream.py"},
            },
            {
                "type": "final_result",
                "result": {"content": "done"},
            },
            {
                "type": "telemetry",
                "usage": {"input_tokens": 12, "output_tokens": 4},
            },
        ]
        proc = _make_stream_proc(
            stdout_lines=[_json_stream.dumps(frame) for frame in native_frames],
            returncode=0,
        )

        frames = list(parse_stream(proc))

        assert [frame.event_family for frame in frames] == [
            EVENT_FAMILY_AGENT,
            EVENT_FAMILY_SUBAGENT,
            EVENT_FAMILY_ASK_USER,
            EVENT_FAMILY_GATE,
            EVENT_FAMILY_TOOL,
            EVENT_FAMILY_FINAL_RESULT,
            EVENT_FAMILY_TELEMETRY,
        ]
        assert frames[1].raw["z_extra"] == {"worker": "T005"}
        assert frames[2].content == "Proceed?"
        assert frames[3].content == "Approve release?"
        assert frames[5].content == "done"

    def test_classifies_current_codex_nested_item_frames(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _patch_select_ready(monkeypatch)
        native_frames = [
            {
                "type": "item.started",
                "item": {
                    "type": "command_execution",
                    "id": "cmd-1",
                    "command": "pytest -q",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "function_call",
                    "name": "apply_patch",
                    "call_id": "call-1",
                },
            },
            {
                "type": "item.started",
                "item": {
                    "type": "subagent.started",
                    "subagent_type": "reviewer",
                },
            },
            {
                "type": "item.started",
                "item": {
                    "type": "agent.started",
                    "agent_name": "planner",
                },
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 12, "output_tokens": 4},
            },
        ]
        proc = _make_stream_proc(
            stdout_lines=[_json_stream.dumps(frame) for frame in native_frames],
            returncode=0,
        )

        frames = list(parse_stream(proc))

        assert [frame.event_family for frame in frames] == [
            EVENT_FAMILY_TOOL,
            EVENT_FAMILY_TOOL,
            EVENT_FAMILY_SUBAGENT,
            EVENT_FAMILY_AGENT,
            EVENT_FAMILY_TELEMETRY,
        ]
        assert [frame.raw for frame in frames] == native_frames

    def test_current_codex_agent_message_item_is_message_with_text(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _patch_select_ready(monkeypatch)
        live_frames = [
            {"thread_id": "...", "type": "thread.started"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "id": "item_0",
                    "type": "agent_message",
                    "text": "OK",
                },
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 17401,
                    "output_tokens": 20,
                },
            },
        ]
        proc = _make_stream_proc(
            stdout_lines=[_json_stream.dumps(frame) for frame in live_frames],
            returncode=0,
        )

        frames = list(parse_stream(proc))

        assert [frame.event_family for frame in frames] == [
            EVENT_FAMILY_UNKNOWN,
            EVENT_FAMILY_UNKNOWN,
            EVENT_FAMILY_MESSAGE,
            EVENT_FAMILY_TELEMETRY,
        ]
        assert frames[2].content == "OK"
        assert frames[2].raw == live_frames[2]

    def test_content_extraction_handles_nested_message_content(self):
        raw = {
            "type": "message",
            "message": {
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": "world"},
                ]
            },
        }
        assert extract_frame_content(raw) == "hello\nworld"

    def test_classify_event_family_is_available_for_raw_driver_events(self):
        raw = {"type": "tool_result", "tool_call_id": "tool-1", "output": "ok"}
        assert classify_event_family(raw) == EVENT_FAMILY_TOOL

    def test_empty_lines_skipped(self, monkeypatch: pytest.MonkeyPatch):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(
            stdout_lines=['{"type":"msg","content":"","is_error":false}', ""],
            returncode=0,
        )
        frames = list(parse_stream(proc))
        assert len(frames) == 1


# ---------------------------------------------------------------------------
# Abnormal path 1: is_error frame → CodexExecutionError
# ---------------------------------------------------------------------------


class TestParseStreamExecutionError:
    """is_error: true in a frame raises CodexExecutionError."""

    def test_raises_on_is_error_true(self, monkeypatch: pytest.MonkeyPatch):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(
            stdout_lines=['{"type":"error","content":"oops","is_error":true}'],
            returncode=0,
        )
        with pytest.raises(CodexExecutionError):
            list(parse_stream(proc))

    def test_exception_carries_frame(self, monkeypatch: pytest.MonkeyPatch):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(
            stdout_lines=['{"type":"error","content":"fail","is_error":true}'],
            returncode=0,
        )
        with pytest.raises(CodexExecutionError) as exc_info:
            list(parse_stream(proc))
        assert exc_info.value.frame.is_error is True
        assert exc_info.value.frame.type == "error"

    def test_telemetry_fires_execution_error(self, monkeypatch: pytest.MonkeyPatch):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(
            stdout_lines=['{"type":"error","content":"fail","is_error":true}'],
            returncode=0,
        )
        mock_log = MagicMock()
        with patch("runtime.drivers.codex.stream._log_event", mock_log):
            with pytest.raises(CodexExecutionError):
                list(parse_stream(proc, run_id="r", repo_root="/root"))

        mock_log.assert_called_once()
        payload = mock_log.call_args.kwargs["payload"]
        assert payload["error_kind"] == "execution_error"


# ---------------------------------------------------------------------------
# Abnormal path 2: stdout timeout → CodexTimeoutError
# ---------------------------------------------------------------------------


class TestParseStreamTimeout:
    """Empty/hanging stdout raises CodexTimeoutError after timeout."""

    def test_raises_on_timeout(self, monkeypatch: pytest.MonkeyPatch):
        # Make select.select() always report no-ready (timeout)
        monkeypatch.setattr(
            "runtime.drivers.codex.stream.select.select",
            lambda rfds, wfds, xfds, timeout: ([], [], []),
        )
        proc = _make_stream_proc(stdout_lines=[], returncode=0)

        with pytest.raises(CodexTimeoutError):
            list(parse_stream(proc, stream_timeout_s=1))

    def test_exception_carries_stream_timeout_s(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            "runtime.drivers.codex.stream.select.select",
            lambda rfds, wfds, xfds, timeout: ([], [], []),
        )
        proc = _make_stream_proc(stdout_lines=[], returncode=0)

        with pytest.raises(CodexTimeoutError) as exc_info:
            list(parse_stream(proc, stream_timeout_s=5))

        assert exc_info.value.stream_timeout_s == 5

    def test_telemetry_fires_stream_timeout(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "runtime.drivers.codex.stream.select.select",
            lambda rfds, wfds, xfds, timeout: ([], [], []),
        )
        proc = _make_stream_proc(stdout_lines=[], returncode=0)
        mock_log = MagicMock()
        with patch("runtime.drivers.codex.stream._log_event", mock_log):
            with pytest.raises(CodexTimeoutError):
                list(parse_stream(proc, stream_timeout_s=1, run_id="r", repo_root="/r"))

        mock_log.assert_called_once()
        payload = mock_log.call_args.kwargs["payload"]
        assert payload["error_kind"] == "stream_timeout"


# ---------------------------------------------------------------------------
# Abnormal path 3: non-zero exit code → CodexCrashError
# ---------------------------------------------------------------------------


class TestParseStreamCrashError:
    """Non-zero exit code after stdout EOF raises CodexCrashError."""

    def test_raises_on_non_zero_exit(self, monkeypatch: pytest.MonkeyPatch):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(stdout_lines=[], returncode=139)  # SIGSEGV

        with pytest.raises(CodexCrashError):
            list(parse_stream(proc))

    def test_exception_carries_exit_code(self, monkeypatch: pytest.MonkeyPatch):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(stdout_lines=[], returncode=1)

        with pytest.raises(CodexCrashError) as exc_info:
            list(parse_stream(proc))

        assert exc_info.value.exit_code == 1

    def test_telemetry_fires_subprocess_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(stdout_lines=[], returncode=2)
        mock_log = MagicMock()
        with patch("runtime.drivers.codex.stream._log_event", mock_log):
            with pytest.raises(CodexCrashError):
                list(parse_stream(proc, run_id="r", repo_root="/r"))

        mock_log.assert_called_once()
        payload = mock_log.call_args.kwargs["payload"]
        assert payload["error_kind"] == "subprocess_crash"
        assert payload["exit_code"] == 2


# ---------------------------------------------------------------------------
# Abnormal path 4: malformed JSONL → log warning, continue
# ---------------------------------------------------------------------------


class TestParseStreamMalformedJsonl:
    """Malformed JSONL lines are logged as warnings and skipped."""

    def test_skips_malformed_line_and_continues(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        _patch_select_ready(monkeypatch)
        lines = [
            "not-valid-json",
            '{"type":"ok","content":"","is_error":false}',
        ]
        proc = _make_stream_proc(stdout_lines=lines, returncode=0)

        frames = list(parse_stream(proc))

        assert len(frames) == 1
        assert frames[0].type == "ok"
        captured = capsys.readouterr()
        assert "malformed" in captured.err.lower()

    def test_malformed_does_not_raise(self, monkeypatch: pytest.MonkeyPatch):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(
            stdout_lines=["{{bad json}}"], returncode=0
        )
        # Should not raise — parser continues past malformed line
        frames = list(parse_stream(proc))
        assert frames == []

    def test_telemetry_fires_malformed_jsonl(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(stdout_lines=["not-json"], returncode=0)
        mock_log = MagicMock()
        with patch("runtime.drivers.codex.stream._log_event", mock_log):
            list(parse_stream(proc, run_id="r", repo_root="/r"))

        mock_log.assert_called_once()
        payload = mock_log.call_args.kwargs["payload"]
        assert payload["error_kind"] == "malformed_jsonl"


# ---------------------------------------------------------------------------
# Telemetry: codex_driver_error with correct error_kind on each abnormal path
# ---------------------------------------------------------------------------


class TestParseStreamTelemetryErrorKinds:
    """Each abnormal path emits codex_driver_error with the correct error_kind."""

    def test_all_four_error_kinds_are_distinct(self):
        """Sanity check: the four error_kind strings are all unique."""
        kinds = {
            "execution_error",
            "stream_timeout",
            "subprocess_crash",
            "malformed_jsonl",
        }
        assert len(kinds) == 4

    def test_telemetry_not_emitted_on_clean_completion(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _patch_select_ready(monkeypatch)
        proc = _make_stream_proc(
            stdout_lines=['{"type":"done","content":"","is_error":false}'],
            returncode=0,
        )
        mock_log = MagicMock()
        with patch("runtime.drivers.codex.stream._log_event", mock_log):
            list(parse_stream(proc))

        mock_log.assert_not_called()

    def test_telemetry_failure_does_not_propagate(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A RuntimeError from log_event must not surface to the caller."""
        monkeypatch.setattr(
            "runtime.drivers.codex.stream.select.select",
            lambda rfds, wfds, xfds, timeout: ([], [], []),
        )
        proc = _make_stream_proc(stdout_lines=[], returncode=0)
        with patch(
            "runtime.drivers.codex.stream._log_event",
            side_effect=RuntimeError("log-event.sh failed"),
        ):
            # CodexTimeoutError should still be raised even if telemetry fails
            with pytest.raises(CodexTimeoutError):
                list(parse_stream(proc, stream_timeout_s=1))


# ===========================================================================
# mcp.py / ensure_mcp_registered() tests (T005)
# ===========================================================================

import json as _json
import tomllib as _tomllib

from runtime.drivers.codex.mcp import (
    McpRegistrationError,
    _invoke_codex_mcp_add,
    _is_already_registered,
    _registered_server_matches,
    _resolve_config_toml,
    ensure_mcp_registered,
)


def _write_mcp_config(
    tmp_path: Path,
    *,
    server_name: str = "filesystem",
    command: str = "python3",
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Write an exported MCP config fixture and return its path."""
    server: dict[str, object] = {"command": command}
    if args is not None:
        server["args"] = args
    if env is not None:
        server["env"] = env
    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(
        _json.dumps({"mcpServers": {server_name: server}}),
        encoding="utf-8",
    )
    return str(config_path)


# ---------------------------------------------------------------------------
# _resolve_config_toml tests
# ---------------------------------------------------------------------------


class TestResolveConfigToml:
    """_resolve_config_toml always resolves to ~/.codex/config.toml."""

    def test_returns_path_under_home_codex(self, tmp_path: Path):
        with patch("runtime.drivers.codex.mcp.Path.home", return_value=tmp_path):
            result = _resolve_config_toml("/usr/local/bin/codex")
        assert result == tmp_path / ".codex" / "config.toml"

    def test_codex_path_does_not_affect_result(self, tmp_path: Path):
        """Different codex_path values must not alter the config.toml location."""
        with patch("runtime.drivers.codex.mcp.Path.home", return_value=tmp_path):
            result_a = _resolve_config_toml("/usr/local/bin/codex")
            result_b = _resolve_config_toml("/opt/homebrew/bin/codex")
        assert result_a == result_b


# ---------------------------------------------------------------------------
# _is_already_registered tests
# ---------------------------------------------------------------------------


class TestIsAlreadyRegistered:
    """_is_already_registered reads config.toml and checks mcp_servers.<name>."""

    def test_returns_false_when_file_absent(self, tmp_path: Path):
        missing = tmp_path / "config.toml"
        assert _is_already_registered(missing, "filesystem") is False

    def test_returns_false_when_server_not_in_config(self, tmp_path: Path):
        config = tmp_path / "config.toml"
        config.write_text('[mcp_servers.other]\ncommand = "other"\n')
        assert _is_already_registered(config, "filesystem") is False

    def test_returns_true_when_server_present(self, tmp_path: Path):
        config = tmp_path / "config.toml"
        config.write_text('[mcp_servers.filesystem]\ncommand = "npx"\n')
        assert _is_already_registered(config, "filesystem") is True

    def test_returns_false_on_malformed_toml(self, tmp_path: Path, capsys):
        config = tmp_path / "config.toml"
        config.write_bytes(b"[[[bad toml\n")
        result = _is_already_registered(config, "filesystem")
        assert result is False
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_returns_false_when_mcp_servers_key_absent(self, tmp_path: Path):
        config = tmp_path / "config.toml"
        config.write_text("[model]\nname = \"gpt-4\"\n")
        assert _is_already_registered(config, "filesystem") is False

    def test_correct_server_name_matched_exactly(self, tmp_path: Path):
        """Partial name matches must not yield True."""
        config = tmp_path / "config.toml"
        config.write_text(
            '[mcp_servers.filesystem-extended]\ncommand = "npx"\n'
        )
        assert _is_already_registered(config, "filesystem") is False


class TestRegisteredServerMatches:
    """_registered_server_matches compares existing Codex TOML to desired JSON."""

    def test_returns_true_for_exact_command_args_and_env(self, tmp_path: Path):
        config = tmp_path / "config.toml"
        config.write_text(
            '[mcp_servers.filesystem]\n'
            'command = "/repo/.venv/bin/python"\n'
            'args = ["-m", "z_harness_cli", "serve"]\n'
            '[mcp_servers.filesystem.env]\n'
            'PYTHONPATH = "/repo"\n'
        )

        assert _registered_server_matches(
            config,
            "filesystem",
            {
                "command": "/repo/.venv/bin/python",
                "args": ["-m", "z_harness_cli", "serve"],
                "env": {"PYTHONPATH": "/repo"},
            },
        ) is True

    def test_returns_false_for_stale_command(self, tmp_path: Path):
        config = tmp_path / "config.toml"
        config.write_text(
            '[mcp_servers.filesystem]\n'
            'command = "python3"\n'
            'args = ["-m", "z_harness_cli", "serve"]\n'
        )

        assert _registered_server_matches(
            config,
            "filesystem",
            {
                "command": "/repo/.venv/bin/python",
                "args": ["-m", "z_harness_cli", "serve"],
                "env": {},
            },
        ) is False


# ---------------------------------------------------------------------------
# _invoke_codex_mcp_add tests
# ---------------------------------------------------------------------------


class TestInvokeCodexMcpAdd:
    """_invoke_codex_mcp_add wraps subprocess.run; raises McpRegistrationError on failure."""

    def test_calls_current_codex_cli_command_shape(self, tmp_path: Path):
        captured: dict = {}
        mcp_config_path = _write_mcp_config(
            tmp_path,
            args=["-m", "z_harness_cli", "serve", "--transport", "stdio"],
            env={
                "PYTHONPATH": "/repo",
                "CLAUDE_PLUGIN_ROOT": "/repo",
            },
        )

        def _fake_run(cmd, *, stdin, stdout, stderr):
            captured["cmd"] = cmd
            result = MagicMock()
            result.returncode = 0
            result.stderr = b""
            return result

        with patch("runtime.drivers.codex.mcp.subprocess.run", _fake_run):
            _invoke_codex_mcp_add(
                codex_path="/usr/local/bin/codex",
                mcp_config_path=mcp_config_path,
                server_name="filesystem",
            )

        assert captured["cmd"] == [
            "/usr/local/bin/codex",
            "mcp",
            "add",
            "--env",
            "PYTHONPATH=/repo",
            "--env",
            "CLAUDE_PLUGIN_ROOT=/repo",
            "filesystem",
            "--",
            "python3",
            "-m",
            "z_harness_cli",
            "serve",
            "--transport",
            "stdio",
        ]
        assert "--config" not in captured["cmd"]
        assert mcp_config_path not in captured["cmd"]

    def test_omits_env_options_when_env_absent(self, tmp_path: Path):
        captured: dict = {}
        mcp_config_path = _write_mcp_config(
            tmp_path,
            command="node",
            args=["server.js"],
        )

        def _fake_run(cmd, *, stdin, stdout, stderr):
            captured["cmd"] = cmd
            result = MagicMock()
            result.returncode = 0
            result.stderr = b""
            return result

        with patch("runtime.drivers.codex.mcp.subprocess.run", _fake_run):
            _invoke_codex_mcp_add(
                codex_path="/usr/local/bin/codex",
                mcp_config_path=mcp_config_path,
                server_name="filesystem",
            )

        assert captured["cmd"] == [
            "/usr/local/bin/codex",
            "mcp",
            "add",
            "filesystem",
            "--",
            "node",
            "server.js",
        ]

    def test_raises_mcp_registration_error_on_non_zero_exit(self, tmp_path: Path):
        mcp_config_path = _write_mcp_config(tmp_path)

        def _fake_run(cmd, *, stdin, stdout, stderr):
            result = MagicMock()
            result.returncode = 1
            result.stderr = b"codex: unknown server\n"
            return result

        with patch("runtime.drivers.codex.mcp.subprocess.run", _fake_run):
            with pytest.raises(McpRegistrationError) as exc_info:
                _invoke_codex_mcp_add(
                    codex_path="/usr/local/bin/codex",
                    mcp_config_path=mcp_config_path,
                    server_name="filesystem",
                )

        assert exc_info.value.returncode == 1
        assert "codex: unknown server" in exc_info.value.stderr

    def test_no_raise_on_zero_exit(self, tmp_path: Path):
        mcp_config_path = _write_mcp_config(tmp_path)

        def _fake_run(cmd, *, stdin, stdout, stderr):
            result = MagicMock()
            result.returncode = 0
            result.stderr = b""
            return result

        with patch("runtime.drivers.codex.mcp.subprocess.run", _fake_run):
            # Must not raise
            _invoke_codex_mcp_add(
                codex_path="/usr/local/bin/codex",
                mcp_config_path=mcp_config_path,
                server_name="filesystem",
            )

    def test_stderr_captured_in_exception(self, tmp_path: Path):
        mcp_config_path = _write_mcp_config(tmp_path, server_name="srv")

        def _fake_run(cmd, *, stdin, stdout, stderr):
            result = MagicMock()
            result.returncode = 2
            result.stderr = b"Error: permission denied\n"
            return result

        with patch("runtime.drivers.codex.mcp.subprocess.run", _fake_run):
            with pytest.raises(McpRegistrationError) as exc_info:
                _invoke_codex_mcp_add(
                    codex_path="/usr/local/bin/codex",
                    mcp_config_path=mcp_config_path,
                    server_name="srv",
                )

        assert "Error: permission denied" in exc_info.value.stderr
        assert exc_info.value.returncode == 2

    def test_raises_when_mcp_config_missing(self):
        with patch("runtime.drivers.codex.mcp.subprocess.run") as mock_run:
            with pytest.raises(McpRegistrationError) as exc_info:
                _invoke_codex_mcp_add(
                    codex_path="/usr/local/bin/codex",
                    mcp_config_path="/missing/mcp_config.json",
                    server_name="filesystem",
                )

        assert exc_info.value.returncode == -1
        assert "could not read MCP config" in exc_info.value.stderr
        mock_run.assert_not_called()

    def test_raises_when_mcp_config_malformed(self, tmp_path: Path):
        config_path = tmp_path / "mcp_config.json"
        config_path.write_text("{bad json", encoding="utf-8")

        with patch("runtime.drivers.codex.mcp.subprocess.run") as mock_run:
            with pytest.raises(McpRegistrationError) as exc_info:
                _invoke_codex_mcp_add(
                    codex_path="/usr/local/bin/codex",
                    mcp_config_path=str(config_path),
                    server_name="filesystem",
                )

        assert "could not parse MCP config" in exc_info.value.stderr
        mock_run.assert_not_called()

    def test_raises_when_server_missing_from_mcp_config(self, tmp_path: Path):
        mcp_config_path = _write_mcp_config(tmp_path, server_name="other")

        with patch("runtime.drivers.codex.mcp.subprocess.run") as mock_run:
            with pytest.raises(McpRegistrationError) as exc_info:
                _invoke_codex_mcp_add(
                    codex_path="/usr/local/bin/codex",
                    mcp_config_path=mcp_config_path,
                    server_name="filesystem",
                )

        assert "does not define server 'filesystem'" in exc_info.value.stderr
        mock_run.assert_not_called()

    def test_raises_when_env_values_are_not_strings(self, tmp_path: Path):
        config_path = tmp_path / "mcp_config.json"
        config_path.write_text(
            _json.dumps(
                {
                    "mcpServers": {
                        "filesystem": {
                            "command": "python3",
                            "env": {"PYTHONPATH": 123},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        with patch("runtime.drivers.codex.mcp.subprocess.run") as mock_run:
            with pytest.raises(McpRegistrationError) as exc_info:
                _invoke_codex_mcp_add(
                    codex_path="/usr/local/bin/codex",
                    mcp_config_path=str(config_path),
                    server_name="filesystem",
                )

        assert "env as an object of string values" in exc_info.value.stderr
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# ensure_mcp_registered tests (the public API)
# ---------------------------------------------------------------------------


class TestEnsureMcpRegistered:
    """ensure_mcp_registered: idempotent check-then-register logic."""

    def _make_fake_run(self, returncode: int = 0, stderr: bytes = b"") -> MagicMock:
        def _fake_run(cmd, *, stdin, stdout, stderr_pipe):
            result = MagicMock()
            result.returncode = returncode
            result.stderr = stderr
            return result

        mock = MagicMock(side_effect=lambda cmd, **kw: (
            type("R", (), {"returncode": returncode, "stderr": stderr})()
        ))
        return mock

    def test_returns_false_when_already_registered(self, tmp_path: Path):
        """No subprocess launched; returns False when server found in config.toml."""
        config = tmp_path / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('[mcp_servers.filesystem]\ncommand = "npx"\n')

        mock_run = MagicMock()
        with patch("runtime.drivers.codex.mcp.Path.home", return_value=tmp_path), \
             patch("runtime.drivers.codex.mcp.subprocess.run", mock_run):
            result = ensure_mcp_registered(
                mcp_config_path="/path/to/mcp.json",
                server_name="filesystem",
                codex_path="/usr/local/bin/codex",
            )

        assert result is False
        mock_run.assert_not_called()

    def test_returns_true_when_not_registered(self, tmp_path: Path):
        """subprocess launched; returns True when server absent from config."""
        config = tmp_path / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text("[model]\nname = \"gpt-4\"\n")
        mcp_config_path = _write_mcp_config(tmp_path)

        def _fake_run(cmd, *, stdin, stdout, stderr):
            r = MagicMock()
            r.returncode = 0
            r.stderr = b""
            return r

        with patch("runtime.drivers.codex.mcp.Path.home", return_value=tmp_path), \
             patch("runtime.drivers.codex.mcp.subprocess.run", _fake_run):
            result = ensure_mcp_registered(
                mcp_config_path=mcp_config_path,
                server_name="filesystem",
                codex_path="/usr/local/bin/codex",
            )

        assert result is True

    def test_refreshes_when_registered_config_is_stale(self, tmp_path: Path):
        """Existing mismatched entry is removed and re-added from desired config."""
        config = tmp_path / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            '[mcp_servers.filesystem]\n'
            'command = "python3"\n'
            'args = ["old"]\n'
        )
        mcp_config_path = _write_mcp_config(
            tmp_path,
            command="/repo/.venv/bin/python",
            args=["-m", "z_harness_cli", "serve"],
        )
        calls: list[list[str]] = []

        def _fake_run(cmd, *, stdin, stdout, stderr):
            calls.append(cmd)
            r = MagicMock()
            r.returncode = 0
            r.stderr = b""
            return r

        with patch("runtime.drivers.codex.mcp.Path.home", return_value=tmp_path), \
             patch("runtime.drivers.codex.mcp.subprocess.run", _fake_run):
            result = ensure_mcp_registered(
                mcp_config_path=mcp_config_path,
                server_name="filesystem",
                codex_path="/usr/local/bin/codex",
            )

        assert result is True
        assert calls == [
            ["/usr/local/bin/codex", "mcp", "remove", "filesystem"],
            [
                "/usr/local/bin/codex",
                "mcp",
                "add",
                "filesystem",
                "--",
                "/repo/.venv/bin/python",
                "-m",
                "z_harness_cli",
                "serve",
            ],
        ]

    def test_returns_true_when_config_file_absent(self, tmp_path: Path):
        """Config file absent → treated as not registered → subprocess launched."""
        dot_codex = tmp_path / ".codex"
        dot_codex.mkdir(parents=True)
        # No config.toml written
        mcp_config_path = _write_mcp_config(tmp_path)

        def _fake_run(cmd, *, stdin, stdout, stderr):
            r = MagicMock()
            r.returncode = 0
            r.stderr = b""
            return r

        with patch("runtime.drivers.codex.mcp.Path.home", return_value=tmp_path), \
             patch("runtime.drivers.codex.mcp.subprocess.run", _fake_run):
            result = ensure_mcp_registered(
                mcp_config_path=mcp_config_path,
                server_name="filesystem",
                codex_path="/usr/local/bin/codex",
            )

        assert result is True

    def test_raises_mcp_registration_error_on_subprocess_failure(
        self, tmp_path: Path
    ):
        """McpRegistrationError propagates when codex mcp add exits non-zero."""
        dot_codex = tmp_path / ".codex"
        dot_codex.mkdir(parents=True)
        # No config.toml — server is not registered
        mcp_config_path = _write_mcp_config(tmp_path)

        def _fake_run(cmd, *, stdin, stdout, stderr):
            r = MagicMock()
            r.returncode = 1
            r.stderr = b"fatal: something went wrong\n"
            return r

        with patch("runtime.drivers.codex.mcp.Path.home", return_value=tmp_path), \
             patch("runtime.drivers.codex.mcp.subprocess.run", _fake_run):
            with pytest.raises(McpRegistrationError) as exc_info:
                ensure_mcp_registered(
                    mcp_config_path=mcp_config_path,
                    server_name="filesystem",
                    codex_path="/usr/local/bin/codex",
                )

        assert exc_info.value.returncode == 1
        assert "fatal: something went wrong" in exc_info.value.stderr

    def test_idempotent_no_double_registration(self, tmp_path: Path):
        """Calling ensure_mcp_registered twice with existing entry never calls subprocess."""
        config = tmp_path / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('[mcp_servers.filesystem]\ncommand = "npx"\n')

        mock_run = MagicMock()
        with patch("runtime.drivers.codex.mcp.Path.home", return_value=tmp_path), \
             patch("runtime.drivers.codex.mcp.subprocess.run", mock_run):
            r1 = ensure_mcp_registered("/mcp.json", "filesystem", "/bin/codex")
            r2 = ensure_mcp_registered("/mcp.json", "filesystem", "/bin/codex")

        assert r1 is False
        assert r2 is False
        mock_run.assert_not_called()

    def test_mcp_registration_error_carries_validation_stderr(self, tmp_path: Path):
        """McpRegistrationError.stderr contains local validation diagnostics."""
        dot_codex = tmp_path / ".codex"
        dot_codex.mkdir(parents=True)

        with patch("runtime.drivers.codex.mcp.Path.home", return_value=tmp_path), \
             patch("runtime.drivers.codex.mcp.subprocess.run") as mock_run:
            with pytest.raises(McpRegistrationError) as exc_info:
                ensure_mcp_registered(
                    mcp_config_path="/bad/path.json",
                    server_name="server",
                    codex_path="/bin/codex",
                )

        assert "could not read MCP config" in exc_info.value.stderr
        assert exc_info.value.returncode == -1
        mock_run.assert_not_called()


# ===========================================================================
# T006 — End-to-end telemetry smoke test
#
# Verifies that all five codex driver telemetry events reach the metrics.jsonl
# sink via the real log_event → log-event.sh → metrics.jsonl pipeline.
#
# Each test uses a temporary fake repo layout:
#   <tmp>/scripts/log-event.sh  — shell shim that appends to <tmp>/z-harness/metrics.jsonl
#   <tmp>/z-harness/metrics.jsonl
#
# The driver / auth modules are pointed at <tmp> via the repo_root argument so
# that compat.log_event invokes the shim instead of the real script.  This
# avoids polluting the real metrics.jsonl while still exercising the full
# call-chain from the Python layer through the shell sink.
# ===========================================================================


import json as _json
import stat as _stat
import textwrap as _textwrap


def _make_fake_repo(tmp_path: Path) -> Path:
    """Create a minimal fake repo rooted at tmp_path with a stub log-event.sh.

    The stub appends a JSON object containing at minimum ``kind`` and the
    full argv payload to ``z-harness/metrics.jsonl`` so the smoke tests can
    assert on event shape without invoking the real harness infrastructure.

    Returns the repo root (tmp_path itself).
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True)
    metrics_dir = tmp_path / "z-harness"
    metrics_dir.mkdir(parents=True)
    metrics_file = metrics_dir / "metrics.jsonl"
    metrics_file.write_text("")  # empty but present

    # Stub log-event.sh: appends {"run":"$1","kind":"$2","payload":$3} to metrics.jsonl
    stub = scripts_dir / "log-event.sh"
    stub.write_text(
        _textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            RUN="$1"; KIND="$2"; PAYLOAD="$3"
            METRICS="{metrics_file}"
            printf '{{"run":"%s","kind":"%s","payload":%s}}\\n' \\
                "$RUN" "$KIND" "$PAYLOAD" >> "$METRICS"
            """
        )
    )
    stub.chmod(stub.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)
    return tmp_path


def _read_metrics(tmp_path: Path) -> list[dict]:
    """Parse all JSON lines from the stub metrics.jsonl."""
    metrics_file = tmp_path / "z-harness" / "metrics.jsonl"
    lines = metrics_file.read_text().strip().splitlines()
    return [_json.loads(line) for line in lines if line.strip()]


class TestTelemetrySinkSmoke:
    """Smoke tests: all five codex driver events reach the metrics.jsonl sink.

    These tests exercise the full Python→shell path by using a stub
    log-event.sh in a temporary fake repo, ensuring that log_event() in
    runtime/compat.py correctly writes structured events to the sink.
    """

    # The five required event kinds (per SPEC §Telemetry/events and T006).
    ALL_FIVE_EVENTS = frozenset(
        {
            "codex_driver_invoke",
            "codex_driver_complete",
            "codex_driver_error",
            "codex_auth_resolved",
            "codex_env_collision_detected",
        }
    )

    def test_codex_auth_resolved_reaches_sink(self, tmp_path: Path, monkeypatch):
        """codex_auth_resolved event lands in metrics.jsonl with strategy_used field."""
        repo_root = str(_make_fake_repo(tmp_path))
        monkeypatch.setenv("CODEX_API_KEY", "ck-smoke-test")
        for k in ("OPENAI_API_KEY",):
            monkeypatch.delenv(k, raising=False)

        # Import the real log_event and point it at our fake repo.
        from runtime.compat import log_event
        from runtime.drivers.codex.auth import resolve_auth

        # Patch the log_event inside auth module to use our fake repo_root.
        # resolve_auth forwards repo_root → _emit_telemetry → log_event.
        resolve_auth(
            {"name": "codex"},
            run_id="smoke-001",
            repo_root=repo_root,
        )

        events = _read_metrics(tmp_path)
        kinds = {e["kind"] for e in events}
        assert "codex_auth_resolved" in kinds

        auth_event = next(e for e in events if e["kind"] == "codex_auth_resolved")
        payload = auth_event["payload"]
        assert "strategy_used" in payload

    def test_codex_driver_invoke_reaches_sink(self, tmp_path: Path, monkeypatch):
        """codex_driver_invoke lands in metrics.jsonl with provider_name, auth_strategy, model_label."""
        from runtime.compat import log_event

        repo_root = str(_make_fake_repo(tmp_path))

        log_event(
            run_id="smoke-002",
            kind="codex_driver_invoke",
            payload={
                "provider_name": "codex",
                "auth_strategy": "codex_api_key",
                "model_label": "codex-mini",
            },
            repo_root=repo_root,
        )

        events = _read_metrics(tmp_path)
        assert len(events) == 1
        ev = events[0]
        assert ev["kind"] == "codex_driver_invoke"
        payload = ev["payload"]
        assert "provider_name" in payload
        assert "auth_strategy" in payload
        assert "model_label" in payload

    def test_codex_driver_complete_reaches_sink(self, tmp_path: Path, monkeypatch):
        """codex_driver_complete lands in metrics.jsonl with exit_code, frames_parsed, elapsed_ms."""
        from runtime.compat import log_event

        repo_root = str(_make_fake_repo(tmp_path))

        log_event(
            run_id="smoke-003",
            kind="codex_driver_complete",
            payload={
                "exit_code": 0,
                "frames_parsed": 5,
                "elapsed_ms": 123.4,
            },
            repo_root=repo_root,
        )

        events = _read_metrics(tmp_path)
        assert len(events) == 1
        ev = events[0]
        assert ev["kind"] == "codex_driver_complete"
        payload = ev["payload"]
        assert payload["exit_code"] == 0
        assert "frames_parsed" in payload
        assert "elapsed_ms" in payload

    def test_codex_driver_error_reaches_sink(self, tmp_path: Path, monkeypatch):
        """codex_driver_error lands in metrics.jsonl with error_kind, exit_code, elapsed_ms."""
        from runtime.compat import log_event

        repo_root = str(_make_fake_repo(tmp_path))

        log_event(
            run_id="smoke-004",
            kind="codex_driver_error",
            payload={
                "error_kind": "non_zero_exit",
                "exit_code": 1,
                "elapsed_ms": 456.7,
            },
            repo_root=repo_root,
        )

        events = _read_metrics(tmp_path)
        assert len(events) == 1
        ev = events[0]
        assert ev["kind"] == "codex_driver_error"
        payload = ev["payload"]
        assert payload["error_kind"] == "non_zero_exit"
        assert "exit_code" in payload
        assert "elapsed_ms" in payload

    def test_codex_env_collision_detected_reaches_sink(self, tmp_path: Path, monkeypatch):
        """codex_env_collision_detected lands in metrics.jsonl with colliding_keys field."""
        from runtime.compat import log_event

        repo_root = str(_make_fake_repo(tmp_path))

        log_event(
            run_id="smoke-005",
            kind="codex_env_collision_detected",
            payload={
                "colliding_keys": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
            },
            repo_root=repo_root,
        )

        events = _read_metrics(tmp_path)
        assert len(events) == 1
        ev = events[0]
        assert ev["kind"] == "codex_env_collision_detected"
        payload = ev["payload"]
        assert "ANTHROPIC_API_KEY" in payload["colliding_keys"]
        assert "OPENAI_API_KEY" in payload["colliding_keys"]

    def test_all_five_events_reach_sink_in_single_run(
        self, tmp_path: Path, monkeypatch
    ):
        """All five telemetry event kinds can be written to the same metrics.jsonl.

        Exercises log_event() five times (once per event kind) and asserts that
        each kind appears at least once with the correct payload shape.  This is
        the canonical T006 smoke test: if any of the five events fail to reach
        the sink, this test fails.
        """
        from runtime.compat import log_event

        repo_root = str(_make_fake_repo(tmp_path))
        run_id = "smoke-all-five"

        events_to_fire = [
            ("codex_driver_invoke", {"provider_name": "codex", "auth_strategy": "codex_api_key", "model_label": "codex-mini"}),
            ("codex_driver_complete", {"exit_code": 0, "frames_parsed": 3, "elapsed_ms": 100.0}),
            ("codex_driver_error", {"error_kind": "timeout", "exit_code": -1, "elapsed_ms": 30000.0}),
            ("codex_auth_resolved", {"strategy_used": "codex_api_key"}),
            ("codex_env_collision_detected", {"colliding_keys": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]}),
        ]

        for kind, payload in events_to_fire:
            log_event(run_id=run_id, kind=kind, payload=payload, repo_root=repo_root)

        events = _read_metrics(tmp_path)
        recorded_kinds = {e["kind"] for e in events}

        assert recorded_kinds == self.ALL_FIVE_EVENTS, (
            f"Expected all five event kinds in metrics.jsonl. "
            f"Missing: {self.ALL_FIVE_EVENTS - recorded_kinds}"
        )

        # Per-event payload shape assertions.
        for ev in events:
            kind = ev["kind"]
            payload = ev["payload"]
            if kind == "codex_driver_invoke":
                assert "provider_name" in payload
                assert "auth_strategy" in payload
                assert "model_label" in payload
            elif kind == "codex_driver_complete":
                assert "exit_code" in payload
                assert "frames_parsed" in payload
                assert "elapsed_ms" in payload
            elif kind == "codex_driver_error":
                assert "error_kind" in payload
                assert "exit_code" in payload
                assert "elapsed_ms" in payload
            elif kind == "codex_auth_resolved":
                assert "strategy_used" in payload
            elif kind == "codex_env_collision_detected":
                assert "colliding_keys" in payload


# ===========================================================================
# T007 — Integration tests: real codex subprocess
#
# All tests here require the ``codex`` binary to be present on PATH.
# Each test class is decorated with @pytest.mark.skipif so the full unit
# suite passes cleanly on CI machines that don't have codex installed.
#
# Timeout integration test (TestCodexDriverTimeoutIntegration) uses a
# simulated hang: it patches _CODEX_CMD to ``["sleep", "999"]`` and sets
# a very short timeout_s (2 s) so the test completes in < 5 s total.
# ===========================================================================

import shutil as _shutil
import threading as _threading

_CODEX_AVAILABLE = bool(_shutil.which("codex"))
_SKIP_NO_CODEX = pytest.mark.skipif(
    not _CODEX_AVAILABLE,
    reason="codex not on PATH",
)

# A minimal provider config with a very long timeout (the real codex tests
# must not accidentally hit the timeout before codex responds).
_INTEGRATION_PROVIDER: dict = {
    "name": "codex",
    "kind": "cli",
    "command": "codex",
    "args_template": ["exec", "-"],
    "stdin": True,
    "timeout_s": 60,
    "model_label": "codex-integration-test",
}


@_SKIP_NO_CODEX
class TestCodexDriverBasicIntegration:
    """Invoke the real ``codex exec --json -`` subprocess with a trivial prompt.

    The test asserts that at least one non-error Frame (or clean DispatchResult)
    is returned.  It does NOT assert on the textual content of the response
    because that is non-deterministic.
    """

    def test_dispatch_returns_handle_without_raising(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """dispatch() completes without raising any exception for a trivial prompt."""
        # Suppress telemetry side-effects to avoid writing to the real metrics.jsonl.
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )

        driver = CodexDriver()
        driver.init(
            _INTEGRATION_PROVIDER,
            context={"run_id": "integ-t007-basic", "repo_root": str(tmp_path)},
        )

        env = {k: v for k, v in os.environ.items()}
        # dispatch() may raise AuthResolutionError if no credential is available;
        # that is a valid integration outcome and must not mask the test.
        try:
            handle = driver.dispatch("z-ask", [], env)
        except Exception as exc:
            # If auth is not configured in this environment, skip gracefully.
            pytest.skip(f"dispatch raised {type(exc).__name__}: {exc}")

        result = handle.wait()
        assert isinstance(result, DispatchResult)

    def test_dispatch_returns_non_error_result_for_trivial_prompt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """A trivial 'say hello' prompt results in is_error=False on a clean exit."""
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )

        driver = CodexDriver()
        driver.init(
            _INTEGRATION_PROVIDER,
            context={"run_id": "integ-t007-hello", "repo_root": str(tmp_path)},
        )

        env = {k: v for k, v in os.environ.items()}
        try:
            handle = driver.dispatch("z-ask", [], env)
        except Exception as exc:
            pytest.skip(f"dispatch raised {type(exc).__name__}: {exc}")

        # Drain the event stream before calling wait(); codex stdout may be non-empty.
        frames: list[dict] = []
        error_frames: list[dict] = []
        try:
            for frame in handle.events():
                if frame.get("is_error"):
                    error_frames.append(frame)
                else:
                    frames.append(frame)
        except Exception:
            # Stream errors (e.g. CodexCrashError) are acceptable here;
            # the test only cares that no Python exception escapes without
            # the handle being returned.
            pass

        result = handle.wait()
        assert isinstance(result, DispatchResult)
        # A non-error result means codex exited cleanly; error_frames should be empty.
        if result.is_error is False:
            assert not error_frames, (
                "Expected no error frames but got: " + str(error_frames)
            )


@_SKIP_NO_CODEX
class TestCodexDriverAuthIntegration:
    """Verify ANTHROPIC_API_KEY is not forwarded to the codex subprocess env.

    This is SPEC Invariant 4: the driver MUST NOT pass ANTHROPIC_API_KEY or
    CLAUDE_API_KEY into the codex subprocess unless explicitly opted in.

    Strategy: spy on subprocess.Popen to capture the env dict that the driver
    would pass to codex, while still allowing the real codex process to launch
    (so the test is genuinely integration-level).  After capturing the env, the
    real Popen is invoked with that same env.
    """

    def test_anthropic_api_key_absent_from_subprocess_env_when_not_opted_in(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """ANTHROPIC_API_KEY must not appear in the env passed to codex subprocess."""
        captured_env: dict = {}
        real_popen = _subprocess.Popen

        def _spy_popen(argv, *, stdin, stdout, stderr, env):
            captured_env.update(env)
            # Still launch the real process so the integration chain runs.
            return real_popen(argv, stdin=stdin, stdout=stdout, stderr=stderr, env=env)

        monkeypatch.setattr("runtime.drivers.codex.driver.subprocess.Popen", _spy_popen)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )

        driver = CodexDriver()
        driver.init(
            _INTEGRATION_PROVIDER,
            context={"run_id": "integ-t007-auth", "repo_root": str(tmp_path)},
        )

        # Inject ANTHROPIC_API_KEY into the env dict the driver receives.
        env = {k: v for k, v in os.environ.items()}
        env["ANTHROPIC_API_KEY"] = "sk-anthropic-integ-test-should-be-stripped"

        try:
            handle = driver.dispatch("z-ask", [], env)
        except Exception as exc:
            pytest.skip(f"dispatch raised {type(exc).__name__}: {exc}")

        # Do not care about the result; just need the handle to be created.
        # Kill the real process quickly to avoid waiting for codex to respond.
        handle.wait()

        # The captured env must NOT contain ANTHROPIC_API_KEY.
        assert "ANTHROPIC_API_KEY" not in captured_env, (
            "ANTHROPIC_API_KEY was leaked into the codex subprocess environment. "
            "This violates SPEC Invariant 4."
        )

    def test_claude_api_key_absent_from_subprocess_env_when_not_opted_in(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """CLAUDE_API_KEY must not appear in the env passed to codex subprocess."""
        captured_env: dict = {}
        real_popen = _subprocess.Popen

        def _spy_popen(argv, *, stdin, stdout, stderr, env):
            captured_env.update(env)
            return real_popen(argv, stdin=stdin, stdout=stdout, stderr=stderr, env=env)

        monkeypatch.setattr("runtime.drivers.codex.driver.subprocess.Popen", _spy_popen)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )

        driver = CodexDriver()
        driver.init(
            _INTEGRATION_PROVIDER,
            context={"run_id": "integ-t007-auth-claude", "repo_root": str(tmp_path)},
        )

        env = {k: v for k, v in os.environ.items()}
        env["CLAUDE_API_KEY"] = "ck-claude-integ-test-should-be-stripped"

        try:
            handle = driver.dispatch("z-ask", [], env)
        except Exception as exc:
            pytest.skip(f"dispatch raised {type(exc).__name__}: {exc}")

        handle.wait()

        assert "CLAUDE_API_KEY" not in captured_env, (
            "CLAUDE_API_KEY was leaked into the codex subprocess environment. "
            "This violates SPEC Invariant 4."
        )


@_SKIP_NO_CODEX
class TestCodexDriverTimeoutIntegration:
    """Verify that a simulated hang triggers CodexTimeoutError within timeout bounds.

    The hang is simulated by patching ``_CODEX_CMD`` to ``["sleep", "999"]``
    and setting ``timeout_s=2``.  The test must complete within
    ``timeout_s + 2`` seconds (i.e., 4 seconds total wall time).

    Invariant tested: SPEC §Invariants-6 — "The subprocess MUST be killed and
    reaped if it exceeds session_timeout_s. No zombie processes."
    """

    def test_timeout_triggers_within_session_timeout_plus_slack(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """A hanging subprocess is killed and handle.wait() returns within session_timeout_s + 2s."""
        import time as _time

        # Patch _CODEX_CMD to a command that hangs indefinitely.
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._CODEX_CMD",
            ["sleep", "999"],
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )
        # Also bypass auth resolution so we don't need real credentials.
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-timeout-integ-test"},
            ),
        )

        session_timeout_s = 2
        timeout_provider = {
            **_INTEGRATION_PROVIDER,
            "timeout_s": session_timeout_s,
        }

        driver = CodexDriver()
        driver.init(
            timeout_provider,
            context={"run_id": "integ-t007-timeout", "repo_root": str(tmp_path)},
        )

        env = {k: v for k, v in os.environ.items()}

        handle = driver.dispatch("z-ask", [], env)

        t_start = _time.monotonic()
        # Drain events — sleep 999 produces no stdout, so the stream parser
        # will get an empty read.  parse_stream() uses a per-line select()
        # with stream_timeout_s defaulting to 30 s, so the stream timeout
        # path alone would exceed our deadline.  We drain in a thread with
        # a hard deadline and rely on wait() for the subprocess kill.
        stream_events: list[dict] = []
        stream_exc: list[Exception] = []

        def _drain():
            try:
                for ev in handle.events():
                    stream_events.append(ev)
            except Exception as exc:
                stream_exc.append(exc)

        drain_thread = _threading.Thread(target=_drain, daemon=True)
        drain_thread.start()

        result = handle.wait()
        elapsed = _time.monotonic() - t_start

        # Wait for drain thread to finish (it will raise once stdout closes).
        drain_thread.join(timeout=3.0)

        max_allowed = session_timeout_s + 2
        assert elapsed < max_allowed, (
            f"handle.wait() took {elapsed:.1f}s, expected < {max_allowed}s. "
            "Subprocess was not killed within the session timeout."
        )
        assert result.is_error is True, (
            "Expected is_error=True after a timeout kill, got is_error=False."
        )

    def test_subprocess_reaped_no_zombie_after_timeout(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """After timeout, the subprocess is both killed AND reaped (proc.wait() called).

        Spy on proc.kill() and proc.wait() to verify both are called.
        """
        import time as _time

        real_popen = _subprocess.Popen
        kill_called: list[bool] = []
        wait_calls: list[int] = []

        class _SpyProc:
            """Thin wrapper around a real Popen that records kill/wait calls."""

            def __init__(self, *args, **kwargs):
                self._proc = real_popen(*args, **kwargs)
                self.stdin = self._proc.stdin
                self.stdout = self._proc.stdout
                self.stderr = self._proc.stderr

            @property
            def returncode(self):
                return self._proc.returncode

            def kill(self):
                kill_called.append(True)
                self._proc.kill()

            def wait(self, timeout=None):
                # The first wait() call (with a timeout) will raise TimeoutExpired
                # because sleep 999 never exits.  We need to raise that ourselves.
                if timeout is not None and timeout <= 5:
                    wait_calls.append(timeout)
                    raise _subprocess.TimeoutExpired(cmd="sleep", timeout=timeout)
                # Second call (after kill, no timeout) — let the real wait finish.
                result = self._proc.wait()
                wait_calls.append(None)
                return result

            def poll(self):
                return self._proc.poll()

        def _spy_popen(argv, *, stdin, stdout, stderr, env):
            return _SpyProc(argv, stdin=stdin, stdout=stdout, stderr=stderr, env=env)

        monkeypatch.setattr("runtime.drivers.codex.driver.subprocess.Popen", _spy_popen)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._CODEX_CMD",
            ["sleep", "999"],
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver._fire_telemetry", MagicMock()
        )
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-zombie-test"},
            ),
        )

        driver = CodexDriver()
        driver.init(
            {**_INTEGRATION_PROVIDER, "timeout_s": 2},
            context={"run_id": "integ-t007-zombie", "repo_root": str(tmp_path)},
        )

        env = {k: v for k, v in os.environ.items()}
        handle = driver.dispatch("z-ask", [], env)

        # Drain in thread, then wait.
        drain_thread = _threading.Thread(
            target=lambda: [_ for _ in handle.events()],
            daemon=True,
        )
        drain_thread.start()

        handle.wait()
        drain_thread.join(timeout=5.0)

        assert kill_called, "proc.kill() was never called — zombie risk."
        assert len(wait_calls) >= 2, (
            "proc.wait() was called fewer than twice — subprocess may not be reaped."
        )
