"""
Backward-compat fail-fast test: .z-harness/providers.json must validate
against provider.schema.json via runtime.validate.

This test surfaces schema-too-strict mistakes before T007-T013 work locks in
(per audit MAJOR M5).

Also covers compose_argv (scripts/resolve-provider.py) and the extended
build_env (runtime/dispatch/env.py) added in T004.

To run:
    cd /path/to/repo-root
    python -m pytest runtime/tests/test_compat_providers.py -v
"""

import importlib.util
import json
from pathlib import Path

import pytest

import jsonschema

from runtime.validate import validate
from runtime.dispatch.env import build_env

# ---------------------------------------------------------------------------
# Import scripts/resolve-provider.py as a module so compose_argv is callable.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
_RESOLVE_PROVIDER_SCRIPT = _SCRIPTS_DIR / "resolve-provider.py"
_rp_spec = importlib.util.spec_from_file_location(
    "resolve_provider_script_t004", _RESOLVE_PROVIDER_SCRIPT
)
_rp_module = importlib.util.module_from_spec(_rp_spec)  # type: ignore[arg-type]
_rp_spec.loader.exec_module(_rp_module)  # type: ignore[union-attr]
compose_argv = _rp_module.compose_argv


# Resolve repo root as the directory containing .z-harness/
_REPO_ROOT = Path(__file__).parent.parent.parent
_PROVIDERS_PATH = _REPO_ROOT / ".z-harness" / "providers.json"


def test_providers_json_exists():
    """The providers.json file must be present at .z-harness/providers.json."""
    assert _PROVIDERS_PATH.exists(), (
        f"providers.json not found at {_PROVIDERS_PATH}. "
        "This file is required for backward-compat validation."
    )


def test_providers_json_validates_against_schema():
    """Existing .z-harness/providers.json must conform to provider.schema.json.

    Failure here means provider.schema.json is too strict for the live config
    and must be loosened before T007-T013 work proceeds.
    """
    with _PROVIDERS_PATH.open("r", encoding="utf-8") as fh:
        providers_data = json.load(fh)

    # Should not raise — if it does, the schema is too strict
    validate("provider", providers_data)


def test_validate_command_valid_instance():
    """validate('command', ...) succeeds for a valid command fixture."""
    valid_command = {
        "id": "z-plan",
        "description": "Generate a task plan from a spec file.",
        "body": "## Usage\n\nRun `/z-plan` to generate a plan.",
        "schema_version": 1,
    }
    # Should not raise
    validate("command", valid_command)


def test_validate_command_empty_raises():
    """validate('command', {}) raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        validate("command", {})


def test_validate_unknown_schema_name_raises():
    """validate with an unknown schema name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown schema name"):
        validate("nonexistent", {})


def test_meta_schema_cached():
    """Calling validate twice uses the cached schema (no re-meta-validation)."""
    from runtime.validate import _schema_cache

    # Clear cache to test first-load path
    _schema_cache.clear()

    instance = {
        "id": "z-test",
        "description": "Test command.",
        "body": "Body.",
        "schema_version": 1,
    }
    validate("command", instance)
    assert "command" in _schema_cache

    # Second call must still work (uses cache)
    validate("command", instance)


def test_corrupted_schema_raises_clear_error(tmp_path, monkeypatch):
    """A deliberately corrupted schema file raises SchemaError naming the file."""
    from runtime import validate as validate_module

    # Write a corrupted schema to a temp contract dir
    fake_contract_dir = tmp_path / "contract"
    fake_contract_dir.mkdir()
    corrupted = fake_contract_dir / "command.schema.json"
    # "type" must be a string or array, not an integer — invalid Draft 7
    corrupted.write_text(json.dumps({"type": 42}), encoding="utf-8")

    # Patch the module-level _CONTRACT_DIR and clear cache
    original_dir = validate_module._CONTRACT_DIR
    validate_module._CONTRACT_DIR = fake_contract_dir
    validate_module._schema_cache.clear()

    try:
        with pytest.raises(jsonschema.SchemaError, match="Contract schema"):
            validate_module._load_schema("command")
    finally:
        validate_module._CONTRACT_DIR = original_dir
        validate_module._schema_cache.clear()


def test_schema_invariants_enforced(tmp_path):
    """Spec invariants are enforced: missing schema_version raises RuntimeError naming the file."""
    from runtime import validate as validate_module

    # Write a schema that passes Draft 7 syntax check but is missing schema_version
    fake_contract_dir = tmp_path / "contract"
    fake_contract_dir.mkdir()
    bad_schema = fake_contract_dir / "command.schema.json"
    # Valid JSON Schema Draft 7 syntax, but missing required top-level schema_version field
    bad_schema.write_text(
        json.dumps({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            # schema_version intentionally omitted
        }),
        encoding="utf-8",
    )

    original_dir = validate_module._CONTRACT_DIR
    validate_module._CONTRACT_DIR = fake_contract_dir
    validate_module._schema_cache.clear()

    try:
        with pytest.raises(RuntimeError) as exc_info:
            validate_module._load_schema("command")
        # Error message must name the offending file
        assert str(bad_schema) in str(exc_info.value), (
            f"Expected file path in error message, got: {exc_info.value}"
        )
        assert "schema_version" in str(exc_info.value)
    finally:
        validate_module._CONTRACT_DIR = original_dir
        validate_module._schema_cache.clear()


# ---------------------------------------------------------------------------
# compose_argv tests (T004)
# ---------------------------------------------------------------------------

# Shared provider fixtures
_V2_PROVIDER_WITH_MODEL_ARG = {
    "args_template": ["exec", "-"],
    "model_arg_template": ["--model", "{model}"],
    "model_env_var": None,
    "default_model": "gpt-5-codex",
}

_V1_PROVIDER_NULL_TEMPLATE = {
    "args_template": ["exec", "-"],
    "model_arg_template": None,
    "model_env_var": None,
    "default_model": "gpt-5-codex",
}


def test_compose_argv_v2_returns_args_template_plus_model_arg():
    """compose_argv on a v2 provider returns args_template + rendered model_arg_template."""
    result = compose_argv(_V2_PROVIDER_WITH_MODEL_ARG, "claude-3-opus")
    assert result == ["exec", "-", "--model", "claude-3-opus"], (
        f"Expected args_template + rendered model_arg, got: {result!r}"
    )


def test_compose_argv_v1_null_template_returns_args_template_only():
    """compose_argv on a v1 provider (null template) returns args_template only — no exception."""
    result = compose_argv(_V1_PROVIDER_NULL_TEMPLATE, "claude-3-opus")
    assert result == ["exec", "-"], (
        f"Expected args_template only for v1 provider, got: {result!r}"
    )


def test_compose_argv_empty_model_falls_back_to_default_model():
    """compose_argv with effective_model='' uses default_model from provider."""
    result = compose_argv(_V2_PROVIDER_WITH_MODEL_ARG, "")
    # default_model is "gpt-5-codex"
    assert result == ["exec", "-", "--model", "gpt-5-codex"], (
        f"Expected default_model fallback, got: {result!r}"
    )


def test_compose_argv_none_model_falls_back_to_default_model():
    """compose_argv with effective_model=None uses default_model from provider."""
    result = compose_argv(_V2_PROVIDER_WITH_MODEL_ARG, None)
    assert result == ["exec", "-", "--model", "gpt-5-codex"], (
        f"Expected default_model fallback, got: {result!r}"
    )


def test_compose_argv_both_empty_raises_value_error():
    """compose_argv raises ValueError when both effective_model and default_model are empty/null."""
    provider_no_default = {
        "args_template": ["run"],
        "model_arg_template": ["--model", "{model}"],
        "model_env_var": None,
        "default_model": None,
    }
    with pytest.raises(ValueError):
        compose_argv(provider_no_default, "")


def test_compose_argv_does_not_substitute_partial_placeholder():
    """{models} (not {model}) is NOT substituted — only exact {model} placeholder."""
    provider = {
        "args_template": [],
        "model_arg_template": ["--filter", "{models}", "--model", "{model}"],
        "model_env_var": None,
        "default_model": "gpt-5-codex",
    }
    result = compose_argv(provider, "my-model")
    assert result == ["--filter", "{models}", "--model", "my-model"], (
        f"Partial placeholder {{models}} should not be substituted, got: {result!r}"
    )


def test_compose_argv_returns_new_list_not_mutating_provider():
    """compose_argv returns a new list; the original provider dict is not mutated."""
    provider = dict(_V2_PROVIDER_WITH_MODEL_ARG)
    original_template = list(provider["args_template"])
    compose_argv(provider, "test-model")
    assert provider["args_template"] == original_template, (
        "compose_argv must not mutate provider['args_template']"
    )


# ---------------------------------------------------------------------------
# build_env extended tests (T004)
# ---------------------------------------------------------------------------


def test_build_env_model_env_var_set_when_model_arg_template_null():
    """build_env sets model_env_var when model_arg_template is null and effective_model passed."""
    provider = {
        "model_env_var": "OPENAI_MODEL",
        "model_arg_template": None,
    }
    base = {"OTHER": "value"}
    result = build_env(provider, base_env=base, effective_model="gpt-5-codex")
    assert result["OPENAI_MODEL"] == "gpt-5-codex", (
        f"Expected OPENAI_MODEL='gpt-5-codex', got: {result.get('OPENAI_MODEL')!r}"
    )
    assert result["OTHER"] == "value"


def test_build_env_no_model_env_var_set_when_neither_configured():
    """build_env returns base_env unchanged (plus CLAUDECODE) when neither model field is set."""
    provider: dict = {}
    base = {"SOME_VAR": "val"}
    result = build_env(provider, base_env=base)
    assert result["SOME_VAR"] == "val"
    assert result["CLAUDECODE"] == ""
    # No extra keys beyond what base has + CLAUDECODE
    extra_keys = set(result.keys()) - set(base.keys()) - {"CLAUDECODE"}
    assert not extra_keys, f"Unexpected extra keys: {extra_keys}"


def test_build_env_both_model_arg_and_env_var_does_not_set_env_var(capsys):
    """build_env does NOT set model_env_var when model_arg_template is also set (arg takes precedence)."""
    provider = {
        "model_env_var": "MY_MODEL_VAR",
        "model_arg_template": ["--model", "{model}"],
    }
    base: dict = {}
    result = build_env(provider, base_env=base, effective_model="my-model")
    assert "MY_MODEL_VAR" not in result, (
        "model_env_var must not be set when model_arg_template is also present"
    )
    # The warning must be emitted to stderr.
    captured = capsys.readouterr()
    assert "model_env_var_ignored" in captured.err, (
        f"Expected 'model_env_var_ignored' in stderr; got: {captured.err!r}"
    )


def test_build_env_no_model_injection_when_effective_model_empty():
    """build_env does not inject model_env_var when effective_model is empty string."""
    provider = {
        "model_env_var": "MY_MODEL_VAR",
        "model_arg_template": None,
    }
    base: dict = {}
    result = build_env(provider, base_env=base, effective_model="")
    assert "MY_MODEL_VAR" not in result


def test_build_env_backward_compat_no_effective_model():
    """build_env without effective_model param behaves identically to pre-T004 behavior."""
    provider = {"auth_env": "MY_TOKEN"}
    base = {"MY_TOKEN": "secret", "OTHER": "val"}
    result = build_env(provider, base_env=base)
    assert result["MY_TOKEN"] == "secret"
    assert result["OTHER"] == "val"
    assert result["CLAUDECODE"] == ""
