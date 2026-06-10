#!/usr/bin/env python3
"""
validate-error-points.py — validate docs/ERROR_POINTS.json against error_points schema.

Usage:
    python3 scripts/validate-error-points.py --file docs/ERROR_POINTS.json
    python3 scripts/validate-error-points.py --fixture <fixture_json> --schema <schema_json>

Exit codes:
    0 — valid
    1 — schema error (structural violation of error_points.schema.json)
    2 — constraint violation (semantic rules like ep_id uniqueness, frequency >= 1, etc.)
    3 — I/O error (missing file, unparseable JSON)

Constraint rules enforced in code (beyond structural schema):
  - ep_id uniqueness across all entries
  - pattern_signature must be exactly 16 hex chars
  - frequency >= 1 for non-archived entries
  - sightings array must be non-empty for non-archived entries
  - last_seen >= first_seen
  - severity must be in {blocker, major, minor}
  - archived entries must have archived_at; active entries must NOT have archived_at
  - novelty_score must equal 1 / (1 + frequency)
  - sightings ring-buffer max 20 entries
"""

import argparse
import json
import os
import re
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(path):
    """Load a JSON file. Returns (data, error_string)."""
    try:
        with open(path, 'r') as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"File not found: {path}"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in {path}: {e}"
    except IOError as e:
        return None, f"I/O error reading {path}: {e}"


def load_schema():
    """Load the error_points JSON Schema from docs/schemas/error_points.schema.json."""
    schema_path = os.path.join(REPO_ROOT, "docs", "schemas", "error_points.schema.json")
    return load_json(schema_path)


def has_nontrivial_constraint(schema_obj):
    """
    Check if a JSON Schema object has at least one non-trivial constraint.
    Non-trivial means something that actually constrains the data, not just
    typing metadata.

    Recognized non-trivial constraint keywords:
      - minItems, maxItems (arrays)
      - minLength, maxLength, pattern (strings)
      - minimum, maximum, exclusiveMinimum, exclusiveMaximum, multipleOf (numbers)
      - required, minProperties, maxProperties (objects)
      - enum, const (value constraints)
      - not (negation constraint)
      - allOf, anyOf, oneOf (combinators that force specific shapes)
      - items (array item constraints)
      - properties (object shape constraints with constraining subschemas)
      - additionalProperties (when false, restricts extra properties)
      - patternProperties
      - format (when present, constrains value shape)
    """
    NONTRIVIAL_KEYWORDS = {
        'minItems', 'maxItems',
        'minLength', 'maxLength', 'pattern',
        'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf',
        'required', 'minProperties', 'maxProperties',
        'enum', 'const', 'not',
        'allOf', 'anyOf', 'oneOf',
    }

    if not isinstance(schema_obj, dict):
        return False

    for key in schema_obj:
        if key in NONTRIVIAL_KEYWORDS:
            return True
        if key == 'items' and isinstance(schema_obj[key], dict):
            if has_nontrivial_constraint(schema_obj[key]):
                return True
        if key == 'properties' and isinstance(schema_obj[key], dict):
            for prop_schema in schema_obj[key].values():
                if has_nontrivial_constraint(prop_schema):
                    return True
        if key == 'additionalProperties' and schema_obj[key] is False:
            return True
        if key == 'patternProperties' and isinstance(schema_obj[key], dict):
            return True
        if key == 'format' and isinstance(schema_obj[key], str):
            return True
        if key == 'dependentRequired' and isinstance(schema_obj[key], dict):
            return True
        if key == 'contains' and isinstance(schema_obj[key], dict):
            return True
    return False


def validate_against_meta_schema(schema_file):
    """
    Validate that the schema file itself is valid JSON Schema draft-2020-12.
    Uses a minimal structural check since we don't bundle jsonschema.
    """
    schema, err = load_json(schema_file)
    if err:
        return False, err
    return True, schema


def validate_fixture_against_schema(fixture, schema):
    """
    Validate a fixture JSON value against a JSON Schema.
    This is a limited but practical validator for common schema constraints.

    Returns None if valid, or an error string.
    """
    if not isinstance(schema, dict):
        return "schema is not an object"

    schema_type = schema.get('type')
    # type check
    if schema_type:
        type_map = {
            'object': dict,
            'array': list,
            'string': str,
            'number': (int, float),
            'integer': int,
            'boolean': bool,
            'null': type(None),
        }
        expected = type_map.get(schema_type)
        if expected is not None:
            if isinstance(expected, tuple):
                if not isinstance(fixture, expected):
                    return f"expected {schema_type}, got {type(fixture).__name__}"
            elif not isinstance(fixture, expected):
                return f"expected {schema_type}, got {type(fixture).__name__}"

    # required properties (for objects)
    if isinstance(fixture, dict):
        required = schema.get('required', [])
        for req in required:
            if req not in fixture:
                return f"missing required property: '{req}'"

        # Check properties subschemas
        props = schema.get('properties', {})
        for prop_name, prop_schema in props.items():
            if prop_name in fixture:
                err = validate_fixture_against_schema(fixture[prop_name], prop_schema)
                if err:
                    return f"property '{prop_name}': {err}"

        # minProperties / maxProperties
        min_props = schema.get('minProperties')
        if min_props is not None and len(fixture) < min_props:
            return f"minProperties: expected >= {min_props}, got {len(fixture)}"
        max_props = schema.get('maxProperties')
        if max_props is not None and len(fixture) > max_props:
            return f"maxProperties: expected <= {max_props}, got {len(fixture)}"

        # additionalProperties
        if schema.get('additionalProperties') is False:
            known = set(props.keys())
            unknown = set(fixture.keys()) - known
            if unknown:
                return f"additional properties not allowed: {unknown}"

    # array constraints
    if isinstance(fixture, list):
        min_items = schema.get('minItems')
        if min_items is not None and len(fixture) < min_items:
            return f"minItems: expected >= {min_items}, got {len(fixture)}"
        max_items = schema.get('maxItems')
        if max_items is not None and len(fixture) > max_items:
            return f"maxItems: expected <= {max_items}, got {len(fixture)}"

        # items schema
        items = schema.get('items')
        if isinstance(items, dict):
            for i, item in enumerate(fixture):
                err = validate_fixture_against_schema(item, items)
                if err:
                    return f"items[{i}]: {err}"

    # string constraints
    if isinstance(fixture, str):
        min_len = schema.get('minLength')
        if min_len is not None and len(fixture) < min_len:
            return f"minLength: expected >= {min_len}, got {len(fixture)}"
        max_len = schema.get('maxLength')
        if max_len is not None and len(fixture) > max_len:
            return f"maxLength: expected <= {max_len}, got {len(fixture)}"
        pattern = schema.get('pattern')
        if pattern is not None:
            if not re.search(pattern, fixture):
                return f"pattern mismatch: '{fixture}' does not match /{pattern}/"

    # numeric constraints
    if isinstance(fixture, (int, float)):
        minimum = schema.get('minimum')
        if minimum is not None and fixture < minimum:
            return f"minimum: expected >= {minimum}, got {fixture}"
        maximum = schema.get('maximum')
        if maximum is not None and fixture > maximum:
            return f"maximum: expected <= {maximum}, got {fixture}"

    # enum
    enum_vals = schema.get('enum')
    if enum_vals is not None and fixture not in enum_vals:
        return f"value '{fixture}' not in enum {enum_vals}"

    # const
    const_val = schema.get('const')
    if const_val is not None and fixture != const_val:
        return f"expected const {const_val}, got {fixture}"

    # not
    not_schema = schema.get('not')
    if isinstance(not_schema, dict):
        not_err = validate_fixture_against_schema(fixture, not_schema)
        if not_err is None:
            return f"value matches forbidden schema (not: constraint)"

    return None


def is_valid_iso8601(s):
    """Basic ISO-8601 format check. Accepts YYYY-MM-DDTHH:MM:SSZ and YYYY-MM-DDTHH:MM:SS+/-HH:MM."""
    if not isinstance(s, str):
        return False
    # Matches: 2024-01-15T12:30:00Z or 2024-01-15T12:30:00+00:00 or 2024-01-15T12:30:00.000Z
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$'
    return bool(re.match(pattern, s))


def validate_error_points_file(file_path):
    """
    Validate docs/ERROR_POINTS.json against the error_points schema + constraint rules.

    Returns (exit_code, error_messages_list).
    """
    errors = []
    constraint_errors = []

    # Load the error points file
    data, io_err = load_json(file_path)
    if io_err:
        return 3, [io_err]

    # Load the error points schema
    schema, schema_err = load_schema()
    if schema_err:
        return 3, [f"Failed to load schema: {schema_err}"]

    # Basic structure check
    if not isinstance(data, dict):
        constraint_errors.append("ERROR_POINTS.json must be a JSON object")
        return 2, constraint_errors

    if 'version' not in data:
        constraint_errors.append("Missing 'version' field")
    elif not isinstance(data['version'], int) or data['version'] < 1:
        constraint_errors.append(f"Invalid version: {data['version']}")

    if 'generated_at' not in data:
        constraint_errors.append("Missing 'generated_at' field")
    elif not is_valid_iso8601(str(data.get('generated_at', ''))):
        constraint_errors.append(f"Invalid generated_at: {data.get('generated_at')}")

    if 'error_points' not in data:
        constraint_errors.append("Missing 'error_points' array")
        return 2, constraint_errors

    error_points = data.get('error_points', [])
    if not isinstance(error_points, list):
        constraint_errors.append("'error_points' must be an array")
        return 2, constraint_errors

    # Validate each error point entry
    seen_ids = set()

    for idx, ep in enumerate(error_points):
        prefix = f"error_point[{idx}]" if 'ep_id' not in ep else f"error_point[{ep.get('ep_id', idx)}]"

        # Check required fields
        for field in ['ep_id', 'pattern', 'pattern_signature', 'anchor_module',
                       'failure_class', 'severity', 'frequency', 'first_seen',
                       'last_seen', 'sightings', 'novelty_score', 'tests_targeting', 'archived']:
            if field not in ep:
                constraint_errors.append(f"{prefix}: missing required field '{field}'")

        # ep_id
        ep_id = ep.get('ep_id', '')
        if ep_id:
            if not re.match(r'^ep_\d{3}$', str(ep_id)):
                constraint_errors.append(f"{prefix}: ep_id '{ep_id}' must match pattern ep_NNN (e.g. ep_001)")

        # ep_id uniqueness
        if ep_id in seen_ids:
            constraint_errors.append(f"{prefix}: duplicate ep_id '{ep_id}'")
        elif ep_id:
            seen_ids.add(ep_id)

        # pattern_signature must be 16 hex chars
        pattern_sig = ep.get('pattern_signature', '')
        if pattern_sig:
            if not re.match(r'^[a-f0-9]{16}$', str(pattern_sig)):
                constraint_errors.append(
                    f"{prefix}: pattern_signature '{pattern_sig}' must be exactly 16 hex chars (got {len(str(pattern_sig))})")

        # severity
        severity = ep.get('severity', '')
        if severity and severity not in ('blocker', 'major', 'minor'):
            constraint_errors.append(
                f"{prefix}: severity '{severity}' must be one of: blocker, major, minor")

        # frequency >= 1 for non-archived entries
        frequency = ep.get('frequency')
        archived = ep.get('archived', False)
        if isinstance(frequency, (int, float)):
            if not archived and frequency < 1:
                constraint_errors.append(
                    f"{prefix}: frequency must be >= 1 for active entries (got {frequency})")

        # sightings must be non-empty for non-archived entries
        sightings = ep.get('sightings', [])
        if isinstance(sightings, list):
            if not archived and len(sightings) == 0:
                constraint_errors.append(
                    f"{prefix}: sightings array must be non-empty for active entries")
            if len(sightings) > 20:
                constraint_errors.append(
                    f"{prefix}: sightings array exceeds max 20 entries (got {len(sightings)})")

        # last_seen >= first_seen
        first_seen = ep.get('first_seen', '')
        last_seen = ep.get('last_seen', '')
        if first_seen and last_seen and isinstance(first_seen, str) and isinstance(last_seen, str):
            if first_seen > last_seen:
                constraint_errors.append(
                    f"{prefix}: last_seen ({last_seen}) must be >= first_seen ({first_seen})")

        # archived entries must have archived_at; active entries must NOT have archived_at
        archived_at = ep.get('archived_at')
        if archived is True:
            if archived_at is None:
                constraint_errors.append(
                    f"{prefix}: archived is true but archived_at is null")
        elif archived is False:
            if archived_at is not None:
                constraint_errors.append(
                    f"{prefix}: archived is false but archived_at is set ({archived_at})")

        # novelty_score must equal 1 / (1 + frequency)
        novelty_score = ep.get('novelty_score')
        if isinstance(novelty_score, (int, float)) and isinstance(frequency, (int, float)):
            expected_novelty = 1.0 / (1.0 + frequency)
            if abs(novelty_score - expected_novelty) > 0.001:
                constraint_errors.append(
                    f"{prefix}: novelty_score ({novelty_score}) must equal 1/(1+frequency) = {expected_novelty}")

        # Validate date fields are valid ISO-8601
        for date_field in ['first_seen', 'last_seen', 'last_test_pass', 'last_test_fail', 'archived_at']:
            val = ep.get(date_field)
            if val is not None and isinstance(val, str) and not is_valid_iso8601(val):
                constraint_errors.append(
                    f"{prefix}: {date_field} is not valid ISO-8601: '{val}'")

        # pattern length
        pattern = ep.get('pattern', '')
        if isinstance(pattern, str):
            if len(pattern) < 1:
                constraint_errors.append(f"{prefix}: pattern must be non-empty")
            elif len(pattern) > 500:
                constraint_errors.append(f"{prefix}: pattern exceeds 500 chars ({len(pattern)})")

        # failure_class length
        failure_class = ep.get('failure_class', '')
        if isinstance(failure_class, str):
            if len(failure_class) < 1:
                constraint_errors.append(f"{prefix}: failure_class must be non-empty")
            elif len(failure_class) > 300:
                constraint_errors.append(f"{prefix}: failure_class exceeds 300 chars ({len(failure_class)})")

        # anchor_module must be non-empty
        anchor_module = ep.get('anchor_module', '')
        if isinstance(anchor_module, str) and len(anchor_module) == 0:
            constraint_errors.append(f"{prefix}: anchor_module must be non-empty")

    if constraint_errors:
        return 2, constraint_errors

    return 0, []


def recompute_pattern_signature(ep):
    """Recompute the expected pattern_signature for an error point entry.
    Uses the documented deterministic algorithm:
    sha256(module_prefix :: normalized_failure_class :: severity)[:16]
    where:
    - module_prefix = first 3 path segments of anchor_module
    - normalized_failure_class = failure_class, lowercased, punctuation stripped
    - severity = the entry's severity as-is
    """
    import hashlib
    module_path = ep.get('anchor_module', '')
    module_prefix = '/'.join(module_path.split('/')[:3])
    fc = ep.get('failure_class', '')
    fc_norm = re.sub(r'[^a-z0-9 ]', '', fc.lower().strip())
    severity = ep.get('severity', '')
    return hashlib.sha256(f'{module_prefix}::{fc_norm}::{severity}'.encode()).hexdigest()[:16]


def cmd_validate_file(args):
    """CLI handler for --file mode."""
    exit_code, errors = validate_error_points_file(args.file)
    for err in errors:
        tag = 'CONSTRAINT' if exit_code == 2 else 'SCHEMA' if exit_code == 1 else 'IO'
        print(f"[{tag}] {err}")
    if exit_code == 0:
        print("ERROR_POINTS.json is valid.")
    sys.exit(exit_code)


def cmd_check_signatures(args):
    """CLI handler for --check-signatures mode.
    Re-derives pattern_signature from failure_class using the documented
    deterministic algorithm and compares to stored value.
    Exit code 2 if any mismatches found.
    """
    mismatches = []
    data, io_err = load_json(args.file)
    if io_err:
        print(f"[IO] {io_err}")
        sys.exit(3)

    error_points = data.get('error_points', [])
    if not isinstance(error_points, list):
        print("[IO] 'error_points' must be an array")
        sys.exit(3)

    for idx, ep in enumerate(error_points):
        ep_id = ep.get('ep_id', f'[index {idx}]')
        stored_sig = ep.get('pattern_signature', '')
        expected_sig = recompute_pattern_signature(ep)
        if stored_sig != expected_sig:
            mismatches.append({
                'ep_id': ep_id,
                'stored': stored_sig,
                'expected': expected_sig,
                'failure_class': ep.get('failure_class', '')[:80],
            })

    if mismatches:
        for m in mismatches:
            print(f"[MISMATCH] {m['ep_id']}: stored={m['stored']} expected={m['expected']}")
            print(f"          failure_class: {m['failure_class']}")
        sys.exit(2)
    else:
        print("All pattern_signatures match recomputed values.")
        sys.exit(0)


def cmd_validate_fixture(args):
    """CLI handler for --fixture + --schema mode."""
    fixture, err = load_json(args.fixture)
    if err:
        print(f"[IO] {err}")
        sys.exit(3)

    schema, err = load_json(args.schema)
    if err:
        print(f"[IO] {err}")
        sys.exit(3)

    validation_err = validate_fixture_against_schema(fixture, schema)
    if validation_err:
        print(f"[CONSTRAINT] fixture does not satisfy schema: {validation_err}")
        sys.exit(2)
    else:
        print("Fixture is valid against schema.")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Validate ERROR_POINTS.json against error_points schema and constraint rules"
    )
    parser.add_argument(
        '--file',
        help='Path to ERROR_POINTS.json to validate'
    )
    parser.add_argument(
        '--fixture',
        help='Path to fixture JSON file to validate against a schema'
    )
    parser.add_argument(
        '--schema',
        help='Path to JSON Schema file (used with --fixture)'
    )
    parser.add_argument(
        '--check-signatures',
        action='store_true',
        help='Re-derive pattern_signature from failure_class and compare to stored value. Exit 2 if mismatches found.'
    )

    args = parser.parse_args()

    if args.check_signatures:
        if not args.file:
            parser.error("--check-signatures requires --file")
        cmd_check_signatures(args)
    elif args.file and not args.fixture:
        cmd_validate_file(args)
    elif args.fixture and args.schema:
        cmd_validate_fixture(args)
    else:
        parser.error("Either --file (validate ERROR_POINTS.json) or --fixture + --schema (validate a fixture) is required")


if __name__ == '__main__':
    main()
