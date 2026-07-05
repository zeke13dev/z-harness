"""
tests/drivers/test_codex_probe.py — Smoke tests for runtime/drivers/codex/probe.py.

All tests that invoke a real codex binary are decorated with:

    @pytest.mark.skipif(not shutil.which("codex"), reason="codex not on PATH")

Tests that do NOT require codex (unit tests of helpers and outcome logic) run
unconditionally and are kept in separate classes clearly labelled "Unit".

Run:
    pytest tests/drivers/test_codex_probe.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import runtime.drivers.codex.probe as _probe_module
from runtime.drivers.codex.probe import (
    CapabilityResult,
    CapabilityStatus,
    CodexCapabilityContract,
    CodexSupportTier,
    CodexSurface,
    ProbeResults,
    _PROBE_RESULTS_PATH,
    _SESSION_PATTERN,
    _WARNING_PATTERN,
    _classify_codex_support,
    _feature_enabled,
    _probe_codex_capabilities,
    _probe_cross_env_collision,
    _probe_session_resume,
    run_probes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CODEX_AVAILABLE = bool(shutil.which("codex"))

_SKIP_NO_CODEX = pytest.mark.skipif(
    not _CODEX_AVAILABLE, reason="codex not on PATH"
)

_FAKE_HELP_WITH_SESSION = """\
Usage: codex exec [OPTIONS] -

Options:
  --output-format <fmt>   Output format (stream-json, json)
  --session-id <id>       Resume or create a session by ID
  --model <model>         Model to use
  -h, --help              Print help
"""

_FAKE_HELP_WITHOUT_SESSION = """\
Usage: codex exec [OPTIONS] -

Options:
  --output-format <fmt>   Output format (stream-json, json)
  --model <model>         Model to use
  -h, --help              Print help
"""

_FAKE_HELP_WITH_CODEX_CAPABILITIES = """\
Usage: codex exec [OPTIONS] -

Options:
  --agent <name>          Run with a named agent
  --ask-user              Emit AskUser gate prompts
  --output-format <fmt>   Output format (stream-json, json)
  -h, --help              Print help
"""

_FAKE_HELP_WITH_BYPASS_APPROVALS_AND_JSONL = """\
Usage: codex exec [OPTIONS] -

Options:
  --json                              Print events to stdout as JSONL
  --dangerously-bypass-approvals-and-sandbox
                                      Bypass approval prompts and sandboxing
  --dangerously-bypass-hook-trust     Bypass hook trust checks
  -h, --help                          Print help
"""


# ===========================================================================
# Unit tests — ProbeResults dataclass
# ===========================================================================


class TestProbeResultsDataclass:
    """ProbeResults is a plain dataclass; test construction and serialisation."""

    def test_default_fields(self):
        r = ProbeResults(
            session_resume_flag="--session-id",
            session_resume_supported=True,
            cross_env_collision_outcome="non_zero_exit:1",
        )
        assert r.session_resume_flag == "--session-id"
        assert r.session_resume_supported is True
        assert r.cross_env_collision_outcome == "non_zero_exit:1"
        assert r.cross_env_collision_warnings == []
        assert r.codex_path == "codex"
        assert r.codex_capabilities.support_tier == CodexSupportTier.UNKNOWN

    def test_asdict_serialisable_to_json(self):
        r = ProbeResults(
            session_resume_flag=None,
            session_resume_supported=False,
            cross_env_collision_outcome="exit_zero",
            cross_env_collision_warnings=["WARN: something"],
            codex_path="/usr/local/bin/codex",
        )
        data = asdict(r)
        # Must round-trip through JSON without error
        serialised = json.dumps(data)
        parsed = json.loads(serialised)
        assert parsed["session_resume_flag"] is None
        assert parsed["session_resume_supported"] is False
        assert parsed["cross_env_collision_outcome"] == "exit_zero"
        assert parsed["cross_env_collision_warnings"] == ["WARN: something"]
        assert parsed["codex_capabilities"]["support_tier"] == "unknown"

    def test_session_resume_flag_none_means_unsupported(self):
        """When flag is None, supported must be False."""
        r = ProbeResults(
            session_resume_flag=None,
            session_resume_supported=False,
            cross_env_collision_outcome="exit_zero",
        )
        assert r.session_resume_flag is None
        assert r.session_resume_supported is False

    def test_session_resume_flag_set_means_supported(self):
        r = ProbeResults(
            session_resume_flag="--resume",
            session_resume_supported=True,
            cross_env_collision_outcome="exit_zero",
        )
        assert r.session_resume_supported is True


# ===========================================================================
# Unit tests — Codex capability contract
# ===========================================================================


class TestCodexCapabilityContractUnit:
    """Codex capability contract stays JSON-safe and evidence-backed."""

    def test_unknown_contract_shape(self):
        contract = CodexCapabilityContract.unknown()
        assert contract.app_plugin_multi_agent_support.status == CapabilityStatus.UNKNOWN
        assert contract.app_plugin_multi_agent_support.surface == CodexSurface.APP_PLUGIN
        assert contract.cli_visible_agent_support.surface == CodexSurface.CLI
        assert contract.ask_user_gate_support.surface == CodexSurface.CLI
        assert contract.event_frame_support.surface == CodexSurface.CLI_STREAM
        assert contract.support_tier == CodexSupportTier.UNKNOWN

    def test_contract_round_trips_through_json(self):
        contract = CodexCapabilityContract(
            app_plugin_multi_agent_support=CapabilityResult(
                CapabilityStatus.SUPPORTED,
                CodexSurface.APP_PLUGIN,
                "codex features list reports multi_agent enabled",
            ),
            cli_visible_agent_support=CapabilityResult(
                CapabilityStatus.UNSUPPORTED,
                CodexSurface.CLI,
                "no CLI agent flag",
            ),
            ask_user_gate_support=CapabilityResult(
                CapabilityStatus.UNSUPPORTED,
                CodexSurface.CLI,
                "no AskUser marker",
            ),
            event_frame_support=CapabilityResult(
                CapabilityStatus.SUPPORTED,
                CodexSurface.CLI_STREAM,
                "stream-json",
            ),
            support_tier=CodexSupportTier.APP_PLUGIN_MULTI_AGENT_CLI_DEGRADED,
        )
        data = json.loads(json.dumps(asdict(contract)))
        assert data["app_plugin_multi_agent_support"]["status"] == "supported"
        assert data["app_plugin_multi_agent_support"]["surface"] == "app_plugin"
        assert data["support_tier"] == "app_plugin_multi_agent_cli_degraded"

    @pytest.mark.parametrize(
        ("features_text", "expected"),
        [
            ("multi_agent stable true\n", True),
            ("multi-agent stable false\n", False),
            ("multi_agent enabled=true\n", True),
            ("other_feature stable true\n", None),
        ],
    )
    def test_feature_enabled_parses_multi_agent_rows(self, features_text, expected):
        assert _feature_enabled(features_text, "multi_agent") is expected

    def test_classification_distinguishes_app_plugin_from_cli(self):
        supported_app = CapabilityResult(
            CapabilityStatus.SUPPORTED, CodexSurface.APP_PLUGIN, "multi_agent true"
        )
        unsupported_cli = CapabilityResult(
            CapabilityStatus.UNSUPPORTED, CodexSurface.CLI, "no flag"
        )
        supported_events = CapabilityResult(
            CapabilityStatus.SUPPORTED, CodexSurface.CLI_STREAM, "stream-json"
        )

        assert (
            _classify_codex_support(
                supported_app, unsupported_cli, unsupported_cli, supported_events
            )
            == CodexSupportTier.APP_PLUGIN_MULTI_AGENT_CLI_DEGRADED
        )

    def test_classification_full_cli_without_app_plugin_is_cli_native_candidate(self):
        unsupported_app = CapabilityResult(
            CapabilityStatus.UNSUPPORTED, CodexSurface.APP_PLUGIN, "multi_agent false"
        )
        supported_cli = CapabilityResult(
            CapabilityStatus.SUPPORTED, CodexSurface.CLI, "--agent"
        )
        supported_events = CapabilityResult(
            CapabilityStatus.SUPPORTED, CodexSurface.CLI_STREAM, "stream-json"
        )

        assert (
            _classify_codex_support(
                unsupported_app, supported_cli, supported_cli, supported_events
            )
            == CodexSupportTier.CLI_NATIVE_CANDIDATE
        )

    def test_classification_event_frames_alone_remains_flattened_cli(self):
        unsupported_app = CapabilityResult(
            CapabilityStatus.UNSUPPORTED, CodexSurface.APP_PLUGIN, "no multi_agent"
        )
        unsupported_cli = CapabilityResult(
            CapabilityStatus.UNSUPPORTED, CodexSurface.CLI, "no flag"
        )
        supported_events = CapabilityResult(
            CapabilityStatus.SUPPORTED, CodexSurface.CLI_STREAM, "stream-json"
        )

        assert (
            _classify_codex_support(
                unsupported_app, unsupported_cli, unsupported_cli, supported_events
            )
            == CodexSupportTier.FLATTENED_CLI
        )

    def test_probe_codex_capabilities_detects_supported_fields(self):
        def _fake_run(argv, **kwargs):
            if argv[1:] == ["features", "list"]:
                return MagicMock(
                    returncode=0, stdout="multi_agent stable true\n", stderr=""
                )
            if argv[1:] == ["exec", "--help"]:
                return MagicMock(
                    returncode=0,
                    stdout=_FAKE_HELP_WITH_CODEX_CAPABILITIES,
                    stderr="",
                )
            raise AssertionError(f"unexpected argv: {argv!r}")

        with patch("runtime.drivers.codex.probe.subprocess.run", _fake_run):
            contract = _probe_codex_capabilities("codex")

        assert (
            contract.app_plugin_multi_agent_support.status
            == CapabilityStatus.SUPPORTED
        )
        assert contract.cli_visible_agent_support.status == CapabilityStatus.SUPPORTED
        assert contract.ask_user_gate_support.status == CapabilityStatus.SUPPORTED
        assert contract.event_frame_support.status == CapabilityStatus.SUPPORTED
        assert contract.support_tier == CodexSupportTier.FULL_NATIVE_CANDIDATE

    def test_probe_codex_capabilities_keeps_app_plugin_unknown_on_failed_features(self):
        def _fake_run(argv, **kwargs):
            if argv[1:] == ["features", "list"]:
                return MagicMock(returncode=2, stdout="", stderr="unknown command\n")
            if argv[1:] == ["exec", "--help"]:
                return MagicMock(returncode=0, stdout=_FAKE_HELP_WITH_SESSION, stderr="")
            raise AssertionError(f"unexpected argv: {argv!r}")

        with patch("runtime.drivers.codex.probe.subprocess.run", _fake_run):
            contract = _probe_codex_capabilities("codex")

        assert (
            contract.app_plugin_multi_agent_support.status == CapabilityStatus.UNKNOWN
        )
        assert contract.cli_visible_agent_support.status == CapabilityStatus.UNSUPPORTED
        assert contract.ask_user_gate_support.status == CapabilityStatus.UNSUPPORTED
        assert contract.event_frame_support.status == CapabilityStatus.SUPPORTED
        assert contract.support_tier == CodexSupportTier.FLATTENED_CLI

    def test_bypass_approval_flags_do_not_imply_ask_user_gate_support(self):
        def _fake_run(argv, **kwargs):
            if argv[1:] == ["features", "list"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if argv[1:] == ["exec", "--help"]:
                return MagicMock(
                    returncode=0,
                    stdout=_FAKE_HELP_WITH_BYPASS_APPROVALS_AND_JSONL,
                    stderr="",
                )
            raise AssertionError(f"unexpected argv: {argv!r}")

        with patch("runtime.drivers.codex.probe.subprocess.run", _fake_run):
            contract = _probe_codex_capabilities("codex")

        assert contract.ask_user_gate_support.status == CapabilityStatus.UNSUPPORTED
        assert (
            contract.ask_user_gate_support.evidence
            == "codex exec --help has no AskUser/gate markers"
        )
        assert contract.event_frame_support.status == CapabilityStatus.SUPPORTED
        assert "JSONL" in contract.event_frame_support.evidence


# ===========================================================================
# Unit tests — session-resume flag regex
# ===========================================================================


class TestSessionFlagPattern:
    """_SESSION_PATTERN must match expected flag forms and not match unrelated ones."""

    @pytest.mark.parametrize(
        "flag",
        [
            "--session-id",
            "--session",
            "--resume",
            "--resume-session",
            "--continue",
            "--continue-session",
            "--SESSION-ID",  # case-insensitive
        ],
    )
    def test_matches_expected_flags(self, flag: str):
        assert _SESSION_PATTERN.search(flag) is not None, f"Expected match for {flag!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "--output-format",
            "--model",
            "--help",
            "--max-tokens",
        ],
    )
    def test_does_not_match_unrelated_flags(self, text: str):
        assert _SESSION_PATTERN.search(text) is None, f"Did not expect match for {text!r}"


# ===========================================================================
# Unit tests — _probe_session_resume (subprocess mocked)
# ===========================================================================


class TestProbeSessionResumeUnit:
    """_probe_session_resume: mocked subprocess; no codex binary needed."""

    def test_returns_flag_when_found_in_stdout(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(
            stdout=_FAKE_HELP_WITH_SESSION, stderr="", returncode=0
        )
        with patch("runtime.drivers.codex.probe.subprocess.run", mock_run):
            flag = _probe_session_resume("codex")
        assert flag == "--session-id"

    def test_returns_none_when_flag_absent(self, capsys):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(
            stdout=_FAKE_HELP_WITHOUT_SESSION, stderr="", returncode=0
        )
        with patch("runtime.drivers.codex.probe.subprocess.run", mock_run):
            flag = _probe_session_resume("codex")
        assert flag is None
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "session" in captured.err.lower()

    def test_returns_none_on_os_error(self, capsys):
        with patch(
            "runtime.drivers.codex.probe.subprocess.run",
            side_effect=OSError("no such file"),
        ):
            flag = _probe_session_resume("nonexistent-codex")
        assert flag is None
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_returns_none_on_timeout(self, capsys):
        import subprocess as _subprocess

        with patch(
            "runtime.drivers.codex.probe.subprocess.run",
            side_effect=_subprocess.TimeoutExpired(cmd="codex", timeout=15),
        ):
            flag = _probe_session_resume("codex")
        assert flag is None
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_scans_both_stdout_and_stderr(self):
        """Flag in stderr (some CLIs print help to stderr) must also be found."""
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="  --session-id <id>   Resume session\n",
            returncode=1,
        )
        with patch("runtime.drivers.codex.probe.subprocess.run", mock_run):
            flag = _probe_session_resume("codex")
        assert flag == "--session-id"

    def test_unsupported_warning_contains_feature_marker(self, capsys):
        """The warning message must mention 'unsupported' so callers can grep it."""
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(
            stdout="--model gpt4", stderr="", returncode=0
        )
        with patch("runtime.drivers.codex.probe.subprocess.run", mock_run):
            _probe_session_resume("codex")
        captured = capsys.readouterr()
        assert "unsupported" in captured.err.lower()


# ===========================================================================
# Unit tests — _probe_cross_env_collision (subprocess mocked)
# ===========================================================================


class TestProbeCrossEnvCollisionUnit:
    """_probe_cross_env_collision: outcome string formation; no codex binary needed."""

    def test_exit_zero_outcome(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with patch("runtime.drivers.codex.probe.subprocess.run", mock_run):
            outcome, warnings = _probe_cross_env_collision("codex")
        assert outcome == "exit_zero"
        assert warnings == []

    def test_non_zero_exit_outcome(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        with patch("runtime.drivers.codex.probe.subprocess.run", mock_run):
            outcome, warnings = _probe_cross_env_collision("codex")
        assert outcome == "non_zero_exit:1"
        assert warnings == []

    def test_non_zero_exit_with_warnings_in_stderr(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout="",
            stderr="error: something went wrong\nWARNING: env var conflict detected\n",
        )
        with patch("runtime.drivers.codex.probe.subprocess.run", mock_run):
            outcome, warnings = _probe_cross_env_collision("codex")
        assert outcome == "non_zero_exit:2+warnings:1"
        assert len(warnings) == 1
        assert "WARNING" in warnings[0]

    def test_exit_zero_with_warnings_in_stderr(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="Warning: ANTHROPIC_API_KEY set but ignored\n",
        )
        with patch("runtime.drivers.codex.probe.subprocess.run", mock_run):
            outcome, warnings = _probe_cross_env_collision("codex")
        assert outcome == "exit_zero+warnings:1"
        assert len(warnings) == 1

    def test_os_error_returns_probe_error(self):
        with patch(
            "runtime.drivers.codex.probe.subprocess.run",
            side_effect=OSError("not found"),
        ):
            outcome, warnings = _probe_cross_env_collision("nonexistent-codex")
        assert outcome.startswith("probe_error:")
        assert warnings == []

    def test_timeout_returns_probe_error(self):
        import subprocess as _subprocess

        with patch(
            "runtime.drivers.codex.probe.subprocess.run",
            side_effect=_subprocess.TimeoutExpired(cmd="codex", timeout=10),
        ):
            outcome, warnings = _probe_cross_env_collision("codex")
        assert outcome.startswith("probe_error:")

    def test_both_keys_are_set_in_subprocess_env(self):
        """The probe must pass BOTH ANTHROPIC_API_KEY and OPENAI_API_KEY to the subprocess."""
        captured_env: dict = {}

        def _capture_run(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch("runtime.drivers.codex.probe.subprocess.run", _capture_run):
            _probe_cross_env_collision("codex")

        assert "ANTHROPIC_API_KEY" in captured_env
        assert "OPENAI_API_KEY" in captured_env

    def test_multiple_warnings_counted_correctly(self):
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Warning: first\nwarn: second\nWARNING: third\nno match line\n",
        )
        with patch("runtime.drivers.codex.probe.subprocess.run", mock_run):
            outcome, warnings = _probe_cross_env_collision("codex")
        assert outcome == "non_zero_exit:1+warnings:3"
        assert len(warnings) == 3


# ===========================================================================
# Unit tests — run_probes() (end-to-end with mocked subprocess + fs)
# ===========================================================================


class TestRunProbesUnit:
    """run_probes() orchestrates both probes and writes probe_results.json."""

    def _mock_subprocess_run(self, help_text: str = _FAKE_HELP_WITH_SESSION) -> MagicMock:
        """Return a side_effect function that handles both probe subprocess calls."""
        call_count = {"n": 0}

        def _fake_run(argv, **kwargs):
            call_count["n"] += 1
            if "--help" in argv:
                return MagicMock(returncode=0, stdout=help_text, stderr="")
            # cross-env collision call (codex exec -)
            return MagicMock(returncode=1, stdout="", stderr="")

        return _fake_run

    def test_returns_probe_results_instance(self, tmp_path: Path):
        with patch("runtime.drivers.codex.probe.subprocess.run", self._mock_subprocess_run()):
            with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
                result = run_probes("codex")
        assert isinstance(result, ProbeResults)

    def test_session_flag_populated_when_found(self, tmp_path: Path):
        with patch("runtime.drivers.codex.probe.subprocess.run", self._mock_subprocess_run()):
            with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
                result = run_probes("codex")
        assert result.session_resume_flag == "--session-id"
        assert result.session_resume_supported is True

    def test_session_flag_none_when_absent(self, tmp_path: Path, capsys):
        with patch(
            "runtime.drivers.codex.probe.subprocess.run",
            self._mock_subprocess_run(help_text=_FAKE_HELP_WITHOUT_SESSION),
        ):
            with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
                result = run_probes("codex")
        assert result.session_resume_flag is None
        assert result.session_resume_supported is False
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_probe_results_written_to_file(self, tmp_path: Path):
        """run_probes() must write a valid JSON file at _PROBE_RESULTS_PATH."""
        written: list[str] = []

        def _capture_write(results: ProbeResults) -> None:
            import json as _json
            from dataclasses import asdict as _asdict
            written.append(_json.dumps(_asdict(results)))

        with patch("runtime.drivers.codex.probe.subprocess.run", self._mock_subprocess_run()):
            with patch("runtime.drivers.codex.probe._write_results", side_effect=_capture_write):
                run_probes("codex")

        assert len(written) == 1
        data = json.loads(written[0])
        assert "session_resume_flag" in data
        assert "session_resume_supported" in data
        assert "cross_env_collision_outcome" in data
        assert "cross_env_collision_warnings" in data
        assert "codex_path" in data
        assert "codex_capabilities" in data
        assert "support_tier" in data["codex_capabilities"]

    def test_probe_results_json_overwrites_previous(self, tmp_path: Path):
        """Each run_probes() call writes exactly once (overwrite semantics)."""
        write_count = {"n": 0}

        def _count_writes(results: ProbeResults) -> None:
            write_count["n"] += 1

        with patch("runtime.drivers.codex.probe.subprocess.run", self._mock_subprocess_run()):
            with patch("runtime.drivers.codex.probe._write_results", side_effect=_count_writes):
                run_probes("codex")
                run_probes("codex")

        assert write_count["n"] == 2

    def test_codex_path_recorded_in_results(self):
        with patch("runtime.drivers.codex.probe.subprocess.run", self._mock_subprocess_run()):
            with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
                result = run_probes("/usr/local/bin/codex")
        assert result.codex_path == "/usr/local/bin/codex"


# ===========================================================================
# Unit tests — telemetry: codex_env_collision_detected
# ===========================================================================


class TestCollisionTelemetryUnit:
    """codex_env_collision_detected fires iff ANTHROPIC_API_KEY is in parent env."""

    def test_telemetry_fires_when_anthropic_key_in_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anth-test")
        mock_log = MagicMock()

        with patch("runtime.drivers.codex.probe._log_event", mock_log):
            with patch(
                "runtime.drivers.codex.probe.subprocess.run",
                MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr="")),
            ):
                with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
                    run_probes("codex")

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["kind"] == "codex_env_collision_detected"

    def test_telemetry_does_not_fire_when_anthropic_key_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_log = MagicMock()

        with patch("runtime.drivers.codex.probe._log_event", mock_log):
            with patch(
                "runtime.drivers.codex.probe.subprocess.run",
                MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr="")),
            ):
                with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
                    run_probes("codex")

        mock_log.assert_not_called()

    def test_telemetry_failure_does_not_prevent_probe_completion(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A RuntimeError from log_event must not prevent run_probes() from returning."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anth-test")

        with patch(
            "runtime.drivers.codex.probe._log_event",
            side_effect=RuntimeError("log-event.sh down"),
        ):
            with patch(
                "runtime.drivers.codex.probe.subprocess.run",
                MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr="")),
            ):
                with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
                    result = run_probes("codex")

        assert isinstance(result, ProbeResults)


# ===========================================================================
# Integration smoke tests — require codex on PATH
# ===========================================================================


@_SKIP_NO_CODEX
class TestProbeSessionResumeIntegration:
    """Real codex exec --help invocation; skipped when codex not on PATH."""

    def test_help_runs_without_error(self):
        """codex exec --help must exit without exception."""
        import subprocess as _subprocess

        proc = _subprocess.run(
            ["codex", "exec", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Help may exit 0 or 1 (some CLIs exit 1 for --help); either is fine.
        assert proc.returncode in (0, 1)

    def test_probe_returns_probe_results(self, tmp_path: Path):
        """run_probes() with real codex returns a ProbeResults."""
        with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
            result = run_probes("codex")
        assert isinstance(result, ProbeResults)

    def test_probe_session_flag_is_str_or_none(self, tmp_path: Path):
        """session_resume_flag must be a str or None (never some other type)."""
        with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
            result = run_probes("codex")
        assert result.session_resume_flag is None or isinstance(
            result.session_resume_flag, str
        )

    def test_session_supported_consistent_with_flag(self, tmp_path: Path):
        """session_resume_supported must reflect whether flag is set."""
        with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
            result = run_probes("codex")
        if result.session_resume_flag is not None:
            assert result.session_resume_supported is True
        else:
            assert result.session_resume_supported is False


@_SKIP_NO_CODEX
class TestProbeCrossEnvCollisionIntegration:
    """Real codex exec - with both API keys set; skipped when codex not on PATH."""

    def test_collision_outcome_has_expected_prefix(self, monkeypatch: pytest.MonkeyPatch):
        """Outcome must start with 'exit_zero' or 'non_zero_exit'."""
        with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
            result = run_probes("codex")
        assert result.cross_env_collision_outcome.startswith(
            ("exit_zero", "non_zero_exit", "probe_error")
        )

    def test_collision_warnings_is_list(self, monkeypatch: pytest.MonkeyPatch):
        """cross_env_collision_warnings must be a list (possibly empty)."""
        with patch("runtime.drivers.codex.probe._write_results", MagicMock()):
            result = run_probes("codex")
        assert isinstance(result.cross_env_collision_warnings, list)


@_SKIP_NO_CODEX
class TestProbeResultsJsonWriteIntegration:
    """run_probes writes a valid JSON file; skipped when codex not on PATH."""

    def test_json_file_written_with_expected_keys(self, tmp_path: Path):
        """probe_results.json must contain all ProbeResults field names."""
        actual_path = _PROBE_RESULTS_PATH
        backup = None
        if actual_path.exists():
            backup = actual_path.read_text(encoding="utf-8")

        try:
            run_probes("codex")
            assert actual_path.exists()
            data = json.loads(actual_path.read_text(encoding="utf-8"))
            expected_keys = {
                "session_resume_flag",
                "session_resume_supported",
                "cross_env_collision_outcome",
                "cross_env_collision_warnings",
                "codex_path",
                "codex_capabilities",
            }
            assert expected_keys.issubset(data.keys())
        finally:
            if backup is not None:
                actual_path.write_text(backup, encoding="utf-8")
            elif actual_path.exists():
                actual_path.unlink()
