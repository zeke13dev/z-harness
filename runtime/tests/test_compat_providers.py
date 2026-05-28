"""
Backward-compat fail-fast test: .z-harness/providers.json must validate
against provider.schema.json via runtime.validate.

This test surfaces schema-too-strict mistakes before T007-T013 work locks in
(per audit MAJOR M5).

To run:
    cd /path/to/repo-root
    python -m pytest runtime/tests/test_compat_providers.py -v
"""

import json
from pathlib import Path

import pytest

import jsonschema

from runtime.validate import validate


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
