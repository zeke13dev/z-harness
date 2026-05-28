"""
runtime.validate — JSON Schema validation for z-harness contracts.

Requires jsonschema >= 4.0.

Usage:
    from runtime.validate import validate
    validate("command", {"id": "z-plan", "description": "...", "body": "...", "schema_version": 1})
    # raises jsonschema.ValidationError on failure

Supported schema names: command, agent, provider, event, skill.
Schemas are loaded from runtime/contract/<name>.schema.json relative to this file.

Meta-schema validation (JSON Schema Draft 7) is performed for each schema file
at import time (eager loading). All 5 schemas are pre-loaded into _schema_cache
when this module is first imported.

**Import-time failure:** if any contract schema file fails Draft 7 meta-validation
or violates the spec invariants ($schema declaration or schema_version field),
the import itself will raise — callers should treat an ImportError or RuntimeError
during `import runtime.validate` as a corrupt distribution.

**Thread-safety:** The cache is populated at import time under Python's import lock;
it is safe for concurrent reads thereafter. If we ever switch to lazy loading, add
a threading.Lock around _schema_cache writes. (v1 single-threaded-dispatcher
assumption per SPEC v2 risk N1.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

# Module-level cache: schema_name -> parsed schema dict.
# Populated eagerly at import time for all 5 known contract schemas.
# Cache is read-only after module initialization; thread-safe for concurrent reads.
_schema_cache: dict[str, dict] = {}

_VALID_SCHEMA_NAMES = frozenset({"command", "agent", "provider", "event", "skill"})
_CONTRACT_DIR = Path(__file__).parent / "contract"


def _load_schema(schema_name: str) -> dict:
    """Load and validate a schema file, caching the result.

    Enforces two SPEC invariants beyond Draft 7 meta-schema syntax:
      1. schema["$schema"] must equal "http://json-schema.org/draft-07/schema#"
      2. schema["schema_version"] must equal 1

    Raises:
        jsonschema.SchemaError: if the schema file is syntactically invalid Draft 7.
        RuntimeError: if the schema file violates invariant 1 or 2 (names the file).
        FileNotFoundError: if the schema file does not exist.
    """
    if schema_name in _schema_cache:
        return _schema_cache[schema_name]

    schema_path = _CONTRACT_DIR / f"{schema_name}.schema.json"
    with schema_path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)

    try:
        jsonschema.Draft7Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise jsonschema.SchemaError(
            f"Contract schema '{schema_path}' failed Draft 7 meta-validation: {exc.message}"
        ) from exc

    # Invariant 1: must declare the correct $schema URI
    expected_schema_uri = "http://json-schema.org/draft-07/schema#"
    if schema.get("$schema") != expected_schema_uri:
        raise RuntimeError(
            f"Contract schema '{schema_path}': missing or wrong $schema declaration. "
            f"Expected '{expected_schema_uri}', got {schema.get('$schema')!r}."
        )

    # Invariant 2: must have top-level schema_version == 1
    if schema.get("schema_version") != 1:
        raise RuntimeError(
            f"Contract schema '{schema_path}': missing top-level schema_version: 1. "
            f"Got {schema.get('schema_version')!r}."
        )

    _schema_cache[schema_name] = schema
    return schema


def validate(schema_name: str, instance: Any) -> None:
    """Validate *instance* against the named z-harness contract schema.

    Args:
        schema_name: One of 'command', 'agent', 'provider', 'event', 'skill'.
        instance: The dict (or other JSON-compatible value) to validate.

    Raises:
        ValueError: if schema_name is not a known contract name.
        jsonschema.SchemaError: if the contract schema file itself is syntactically
            malformed (only on first load if cache was cleared; cached thereafter).
        RuntimeError: if the contract schema violates spec invariants
            (only on first load if cache was cleared; cached thereafter).
        jsonschema.ValidationError: if *instance* does not conform to the schema.
    """
    if schema_name not in _VALID_SCHEMA_NAMES:
        raise ValueError(
            f"Unknown schema name {schema_name!r}. "
            f"Must be one of: {sorted(_VALID_SCHEMA_NAMES)}"
        )

    schema = _load_schema(schema_name)
    jsonschema.validate(instance=instance, schema=schema)


# Eager pre-load: populate the cache for all 5 known schemas at import time.
# This ensures malformed or non-conforming schema files are caught immediately
# on `import runtime.validate`, not silently at first use.
# Runs under Python's import lock — thread-safe for all subsequent reads.
for _name in _VALID_SCHEMA_NAMES:
    _load_schema(_name)
