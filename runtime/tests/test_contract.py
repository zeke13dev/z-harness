"""
Contract validation tests for z-harness JSON schemas.

Covers:
  - Meta-schema validation: each of the 5 contract schemas passes Draft 7 check_schema.
  - Valid fixture round-trip: each fixture file validates without error.
  - Invalid fixture: each schema rejects an instance with a required field removed.

To run:
    cd /path/to/repo-root
    python -m pytest runtime/tests/test_contract.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from runtime.validate import validate

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_CONTRACT_DIR = Path(__file__).parent.parent / "contract"

# Mapping of schema name -> fixture filename and a required field to remove for
# the "invalid" test.
_SCHEMA_FIXTURES: list[tuple[str, str, str]] = [
    ("command", "command_valid.json", "id"),
    ("agent", "agent_valid.json", "name"),
    ("provider", "provider_valid.json", "roles"),
    ("event", "event_valid.json", "ts"),
    ("skill", "skill_valid.json", "id"),
]


# ---------------------------------------------------------------------------
# Meta-schema tests
# ---------------------------------------------------------------------------


def test_all_schemas_pass_draft7_meta_schema():
    """Each of the 5 contract schema files is valid Draft 7 JSON Schema."""
    schema_names = ["command", "agent", "provider", "event", "skill"]
    for name in schema_names:
        schema_path = _CONTRACT_DIR / f"{name}.schema.json"
        assert schema_path.exists(), f"Schema file not found: {schema_path}"
        with schema_path.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        # check_schema raises jsonschema.SchemaError if invalid; must not raise here
        jsonschema.Draft7Validator.check_schema(schema)


# ---------------------------------------------------------------------------
# Valid fixture tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema_name,fixture_file,_required_field", _SCHEMA_FIXTURES)
def test_valid_fixture_passes(schema_name, fixture_file, _required_field):
    """Valid fixture for each schema validates without error."""
    fixture_path = _FIXTURES_DIR / fixture_file
    assert fixture_path.exists(), f"Fixture not found: {fixture_path}"
    with fixture_path.open("r", encoding="utf-8") as fh:
        instance = json.load(fh)
    # Must not raise
    validate(schema_name, instance)


# ---------------------------------------------------------------------------
# Invalid fixture tests (missing required field)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema_name,fixture_file,required_field", _SCHEMA_FIXTURES)
def test_invalid_fixture_missing_required_field_raises(
    schema_name, fixture_file, required_field
):
    """Removing a required field causes validate() to raise ValidationError."""
    fixture_path = _FIXTURES_DIR / fixture_file
    with fixture_path.open("r", encoding="utf-8") as fh:
        instance = json.load(fh)

    # Remove the required field — instance is now invalid
    assert required_field in instance, (
        f"Fixture {fixture_file!r} does not contain field {required_field!r}; "
        "update the test's required_field mapping."
    )
    del instance[required_field]

    with pytest.raises(jsonschema.ValidationError):
        validate(schema_name, instance)


# ---------------------------------------------------------------------------
# allow_cross_vendor_env field (added per amendment 20260528T175112Z, T-REV-001)
# ---------------------------------------------------------------------------


def test_allow_cross_vendor_env_optional_accepted():
    """ProviderEntry.allow_cross_vendor_env is optional and validates as boolean."""
    fixture_path = _FIXTURES_DIR / "provider_valid.json"
    with fixture_path.open("r", encoding="utf-8") as fh:
        instance = json.load(fh)
    # Inject the optional field on the single provider entry
    provider = next(iter(instance["providers"].values()))
    provider["allow_cross_vendor_env"] = True
    validate("provider", instance)  # must not raise


def test_allow_cross_vendor_env_rejects_non_boolean():
    """Non-boolean value for allow_cross_vendor_env raises ValidationError."""
    fixture_path = _FIXTURES_DIR / "provider_valid.json"
    with fixture_path.open("r", encoding="utf-8") as fh:
        instance = json.load(fh)
    provider = next(iter(instance["providers"].values()))
    provider["allow_cross_vendor_env"] = "yes"  # wrong type
    with pytest.raises(jsonschema.ValidationError):
        validate("provider", instance)
