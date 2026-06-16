"""
test_hermes_config.py — Tests for hermes/config.py ConcurrencyConfig knobs.

Tests: defaults, file override (hermes-config.yaml), and bool parsing.
Concurrency/retry/timeout knobs are file-only; HERMES_* env vars no longer
override them. Discord env vars (HERMES_DISCORD_TOKEN/USER_ID) are unchanged.
"""

import os
import sys
import tempfile
import textwrap
from pathlib import Path
import pytest

# Ensure scripts/ is on sys.path so `from hermes.config import ...` works.
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import ConcurrencyConfig, load_config, _bool_coerce


# ---------------------------------------------------------------------------
# _bool_coerce unit tests
# ---------------------------------------------------------------------------

class TestBoolCoerce:
    def test_zero_is_false(self):
        assert _bool_coerce("0") is False

    def test_false_string_is_false(self):
        assert _bool_coerce("false") is False

    def test_False_string_is_false(self):
        assert _bool_coerce("False") is False

    def test_no_is_false(self):
        assert _bool_coerce("no") is False

    def test_off_is_false(self):
        assert _bool_coerce("off") is False

    def test_one_is_true(self):
        assert _bool_coerce("1") is True

    def test_true_string_is_true(self):
        assert _bool_coerce("true") is True

    def test_yes_is_true(self):
        assert _bool_coerce("yes") is True

    def test_on_is_true(self):
        assert _bool_coerce("on") is True

    def test_empty_string_is_false(self):
        assert _bool_coerce("") is False

    def test_whitespace_only_is_false(self):
        assert _bool_coerce("   ") is False


# ---------------------------------------------------------------------------
# ConcurrencyConfig dataclass defaults
# ---------------------------------------------------------------------------

class TestConcurrencyConfigDefaults:
    def test_max_parallel_workstreams_default_is_1(self):
        cfg = ConcurrencyConfig()
        assert cfg.max_parallel_workstreams == 1, (
            "Default must be 1 (sequential-by-default, INV-5); was changed from 3"
        )

    def test_max_parallel_plans_default_is_1(self):
        cfg = ConcurrencyConfig()
        assert cfg.max_parallel_plans == 1

    def test_serialize_all_default_is_false(self):
        cfg = ConcurrencyConfig()
        assert cfg.serialize_all is False

    def test_serialize_high_severity_default_is_true(self):
        cfg = ConcurrencyConfig()
        assert cfg.serialize_high_severity is True

    def test_no_max_parallel_sessions_attribute(self):
        """Confirm the old field name is gone — T010 must not reference it."""
        cfg = ConcurrencyConfig()
        assert not hasattr(cfg, "max_parallel_sessions"), (
            "max_parallel_sessions was renamed to max_parallel_workstreams; "
            "the old attribute must not exist"
        )


# ---------------------------------------------------------------------------
# load_config: pure defaults (no file, no env)
# ---------------------------------------------------------------------------

class TestLoadConfigDefaults:
    def test_defaults_no_file(self, tmp_path):
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_workstreams == 1
        assert cfg.concurrency.max_parallel_plans == 1
        assert cfg.concurrency.serialize_all is False
        assert cfg.concurrency.serialize_high_severity is True


# ---------------------------------------------------------------------------
# load_config: file override
# ---------------------------------------------------------------------------

class TestLoadConfigFileOverride:
    def _write_yaml(self, tmp_path: Path, content: str) -> Path:
        cfg_file = tmp_path / "hermes-config.yaml"
        cfg_file.write_text(textwrap.dedent(content))
        return tmp_path

    def test_file_overrides_max_parallel_workstreams(self, tmp_path):
        self._write_yaml(tmp_path, """\
            concurrency:
              max_parallel_workstreams: 4
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_workstreams == 4

    def test_file_overrides_max_parallel_plans(self, tmp_path):
        self._write_yaml(tmp_path, """\
            concurrency:
              max_parallel_plans: 3
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_plans == 3

    def test_file_overrides_serialize_all_true(self, tmp_path):
        self._write_yaml(tmp_path, """\
            concurrency:
              serialize_all: true
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_all is True

    def test_file_overrides_serialize_high_severity_false(self, tmp_path):
        self._write_yaml(tmp_path, """\
            concurrency:
              serialize_high_severity: false
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_high_severity is False

    def test_file_overrides_max_retries(self, tmp_path):
        self._write_yaml(tmp_path, """\
            retry:
              max_retries: 5
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.retry.max_retries == 5

    def test_file_overrides_workstream_timeout(self, tmp_path):
        self._write_yaml(tmp_path, """\
            timeouts:
              per_workstream_minutes: 120
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.timeouts.per_workstream_minutes == 120

    def test_malformed_yaml_degrades_to_defaults(self, tmp_path):
        """A config file with invalid YAML must NOT raise; must return defaults."""
        # Write syntactically invalid YAML to the config path load_config reads.
        cfg_file = tmp_path / "hermes-config.yaml"
        cfg_file.write_text("concurrency:\n  max_parallel_workstreams: [unclosed bracket\n")
        # Must not raise — graceful degradation to defaults.
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_workstreams == 1
        assert cfg.concurrency.max_parallel_plans == 1
        assert cfg.concurrency.serialize_all is False
        assert cfg.concurrency.serialize_high_severity is True


# ---------------------------------------------------------------------------
# load_config: confirm HERMES_* env vars are NOT respected for concurrency/
# retry/timeout knobs (file-only since T017)
# ---------------------------------------------------------------------------

class TestLoadConfigEnvIgnored:
    """HERMES_MAX_PARALLEL, _PLANS, SERIALIZE_*, MAX_RETRIES, WORKSTREAM_TIMEOUT_MINUTES
    are no longer read from the environment. These tests assert the env vars
    are silently ignored and the file value (or default) is authoritative.
    """

    def test_hermes_max_parallel_env_ignored(self, tmp_path, monkeypatch):
        """HERMES_MAX_PARALLEL env var must NOT override max_parallel_workstreams."""
        monkeypatch.setenv("HERMES_MAX_PARALLEL", "99")
        cfg = load_config(repo_root=str(tmp_path))
        # Default is 1; env var must be silently ignored.
        assert cfg.concurrency.max_parallel_workstreams == 1

    def test_hermes_max_parallel_plans_env_ignored(self, tmp_path, monkeypatch):
        """HERMES_MAX_PARALLEL_PLANS env var must NOT override max_parallel_plans."""
        monkeypatch.setenv("HERMES_MAX_PARALLEL_PLANS", "99")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_plans == 1

    def test_hermes_serialize_all_env_ignored(self, tmp_path, monkeypatch):
        """HERMES_SERIALIZE_ALL env var must NOT override serialize_all."""
        monkeypatch.setenv("HERMES_SERIALIZE_ALL", "1")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_all is False

    def test_hermes_serialize_high_severity_env_ignored(self, tmp_path, monkeypatch):
        """HERMES_SERIALIZE_HIGH_SEVERITY env var must NOT override serialize_high_severity."""
        monkeypatch.setenv("HERMES_SERIALIZE_HIGH_SEVERITY", "0")
        cfg = load_config(repo_root=str(tmp_path))
        # Default is True; env must be silently ignored.
        assert cfg.concurrency.serialize_high_severity is True

    def test_hermes_max_retries_env_ignored(self, tmp_path, monkeypatch):
        """HERMES_MAX_RETRIES env var must NOT override retry.max_retries."""
        monkeypatch.setenv("HERMES_MAX_RETRIES", "99")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.retry.max_retries == 1  # default

    def test_hermes_workstream_timeout_env_ignored(self, tmp_path, monkeypatch):
        """HERMES_WORKSTREAM_TIMEOUT_MINUTES env var must NOT override timeouts."""
        monkeypatch.setenv("HERMES_WORKSTREAM_TIMEOUT_MINUTES", "999")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.timeouts.per_workstream_minutes == 90  # default

    def test_file_value_wins_env_ignored(self, tmp_path, monkeypatch):
        """File value is authoritative; a conflicting env var is silently ignored."""
        cfg_file = tmp_path / "hermes-config.yaml"
        cfg_file.write_text("concurrency:\n  max_parallel_workstreams: 4\n")
        monkeypatch.setenv("HERMES_MAX_PARALLEL", "7")
        cfg = load_config(repo_root=str(tmp_path))
        # File says 4; env says 7; file must win.
        assert cfg.concurrency.max_parallel_workstreams == 4
