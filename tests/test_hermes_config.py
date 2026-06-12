"""
test_hermes_config.py — Tests for hermes/config.py ConcurrencyConfig knobs.

Tests: defaults, file override, HERMES_MAX_PARALLEL env override, new fields,
and bool env parsing for "0"/"false" (the Python bool("0")==True trap).
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
    def test_defaults_no_file_no_env(self, tmp_path, monkeypatch):
        # Remove any hermes env vars that might leak in
        for var in (
            "HERMES_MAX_PARALLEL",
            "HERMES_MAX_PARALLEL_PLANS",
            "HERMES_SERIALIZE_ALL",
            "HERMES_SERIALIZE_HIGH_SEVERITY",
        ):
            monkeypatch.delenv(var, raising=False)

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

    def test_file_overrides_max_parallel_workstreams(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HERMES_MAX_PARALLEL", raising=False)
        self._write_yaml(tmp_path, """\
            concurrency:
              max_parallel_workstreams: 4
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_workstreams == 4

    def test_file_overrides_max_parallel_plans(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HERMES_MAX_PARALLEL_PLANS", raising=False)
        self._write_yaml(tmp_path, """\
            concurrency:
              max_parallel_plans: 3
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_plans == 3

    def test_file_overrides_serialize_all_true(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HERMES_SERIALIZE_ALL", raising=False)
        self._write_yaml(tmp_path, """\
            concurrency:
              serialize_all: true
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_all is True

    def test_file_overrides_serialize_high_severity_false(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HERMES_SERIALIZE_HIGH_SEVERITY", raising=False)
        self._write_yaml(tmp_path, """\
            concurrency:
              serialize_high_severity: false
        """)
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_high_severity is False

    def test_malformed_yaml_degrades_to_defaults(self, tmp_path, monkeypatch):
        """A config file with invalid YAML must NOT raise; must return defaults."""
        for var in (
            "HERMES_MAX_PARALLEL",
            "HERMES_MAX_PARALLEL_PLANS",
            "HERMES_SERIALIZE_ALL",
            "HERMES_SERIALIZE_HIGH_SEVERITY",
        ):
            monkeypatch.delenv(var, raising=False)
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
# load_config: env var overrides
# ---------------------------------------------------------------------------

class TestLoadConfigEnvOverride:
    def test_hermes_max_parallel_overrides_workstreams(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_MAX_PARALLEL", "5")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_workstreams == 5

    def test_hermes_max_parallel_plans_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_MAX_PARALLEL_PLANS", "2")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_plans == 2

    def test_hermes_serialize_all_env_true(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_SERIALIZE_ALL", "1")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_all is True

    def test_hermes_serialize_all_env_false_string(self, tmp_path, monkeypatch):
        """Critical: "0" must yield False, not True (Python bool("0") trap)."""
        monkeypatch.setenv("HERMES_SERIALIZE_ALL", "0")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_all is False

    def test_hermes_serialize_all_env_false_word(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_SERIALIZE_ALL", "false")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_all is False

    def test_hermes_serialize_high_severity_env_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_SERIALIZE_HIGH_SEVERITY", "0")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_high_severity is False

    def test_hermes_serialize_high_severity_env_true(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_SERIALIZE_HIGH_SEVERITY", "true")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.serialize_high_severity is True

    def test_env_overrides_file_value(self, tmp_path, monkeypatch):
        """Env must win over file value (env/file precedence)."""
        cfg_file = tmp_path / "hermes-config.yaml"
        cfg_file.write_text("concurrency:\n  max_parallel_workstreams: 4\n")
        monkeypatch.setenv("HERMES_MAX_PARALLEL", "7")
        cfg = load_config(repo_root=str(tmp_path))
        assert cfg.concurrency.max_parallel_workstreams == 7
