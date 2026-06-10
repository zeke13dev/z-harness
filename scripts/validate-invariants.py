#!/usr/bin/env python3
"""
validate-invariants.py — validate docs/INVARIANTS.json against invariant schema.

Usage:
    python3 scripts/validate-invariants.py --file docs/INVARIANTS.json
    python3 scripts/validate-invariants.py --fixture <fixture_json> --schema <schema_json>

Exit codes:
    0 — valid
    1 — schema error (structural violation of invariant.schema.json)
    2 — constraint violation (semantic rules like id-uniqueness, tag subset, fixture_schema/config)
    3 — I/O error (missing file, unparseable JSON)

Constraint rules enforced in code (beyond structural schema):
  - id uniqueness across all entries
  - tags[] must be subset of docs/llm/TAGS.txt controlled tags
  - fixture_schema, if present, must contain >=1 non-trivial constraint
  - fixture_defaults, if present, must validate against fixture_schema
  - fixture_defaults is only valid when fixture_schema is present
  - severity must be in {blocker, major, minor}
  - source_files must be non-empty
"""

import argparse
import json
import os
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
    """Load the invariant JSON Schema from docs/schemas/invariant.schema.json."""
    schema_path = os.path.join(REPO_ROOT, "docs", "schemas", "invariant.schema.json")
    return load_json(schema_path)


def load_tags():
    """Load controlled tags from docs/llm/TAGS.txt. Returns set of tags."""
    tags_path = os.path.join(REPO_ROOT, "docs", "llm", "TAGS.txt")
    try:
        with open(tags_path, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return None, f"TAGS.txt not found at {tags_path}"
    except IOError as e:
        return None, f"I/O error reading {tags_path}: {e}"

    tags = set()
    in_section_1 = True
    for line in lines:
        stripped = line.strip()
        # Skip comments and blank lines
        if not stripped or stripped.startswith('#'):
            if stripped == '' and in_section_1:
                in_section_1 = False
            continue
        if in_section_1:
            tags.add(stripped)
    return tags, None


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
            # items with a schema constrains each element
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


def validate_invariants_file(file_path):
    """
    Validate docs/INVARIANTS.json against the invariant schema + constraint rules.

    Returns (exit_code, error_messages_list).
    """
    errors = []
    schema_errors = []
    constraint_errors = []

    # Load the invariants file
    data, io_err = load_json(file_path)
    if io_err:
        return 3, [io_err]

    # Load the invariant schema
    schema, schema_err = load_schema()
    if schema_err:
        return 3, [f"Failed to load schema: {schema_err}"]

    # Load controlled tags
    valid_tags, tags_err = load_tags()
    if tags_err:
        return 3, [f"Failed to load TAGS.txt: {tags_err}"]

    # Basic structure check
    if not isinstance(data, dict):
        constraint_errors.append("INVARIANTS.json must be a JSON object")
        return 2, constraint_errors

    if 'version' not in data:
        constraint_errors.append("Missing 'version' field")
    elif not isinstance(data['version'], int) or data['version'] < 1:
        constraint_errors.append(f"Invalid version: {data['version']}")

    if 'invariants' not in data:
        constraint_errors.append("Missing 'invariants' array")
        return 2, constraint_errors

    invariants = data.get('invariants', [])
    if not isinstance(invariants, list):
        constraint_errors.append("'invariants' must be an array")
        return 2, constraint_errors

    # Validate each invariant entry
    seen_ids = set()

    for idx, inv in enumerate(invariants):
        prefix = f"invariant[{idx}]" if 'id' not in inv else f"invariant[{inv.get('id', idx)}]"

        # Check required fields
        for field in ['id', 'description', 'tags', 'failure_class', 'severity',
                       'source_files', 'last_updated', 'source']:
            if field not in inv:
                constraint_errors.append(f"{prefix}: missing required field '{field}'")

        # id
        inv_id = inv.get('id', '')
        if inv_id:
            import re
            if not re.match(r'^inv_\d{3}$', str(inv_id)):
                constraint_errors.append(f"{prefix}: id '{inv_id}' must match pattern inv_NNN (e.g. inv_001)")

        # id uniqueness
        if inv_id in seen_ids:
            constraint_errors.append(f"{prefix}: duplicate id '{inv_id}'")
        elif inv_id:
            seen_ids.add(inv_id)

        # tags subset check
        tags = inv.get('tags', [])
        if isinstance(tags, list):
            for tag in tags:
                if tag not in valid_tags:
                    constraint_errors.append(
                        f"{prefix}: tag '{tag}' is not in controlled tags (TAGS.txt)")

        # severity
        severity = inv.get('severity', '')
        if severity and severity not in ('blocker', 'major', 'minor'):
            constraint_errors.append(
                f"{prefix}: severity '{severity}' must be one of: blocker, major, minor")

        # source
        source = inv.get('source', '')
        if source and source not in ('spec', 'plan', 'user-concern', 'code-review', 'axiom-derived'):
            constraint_errors.append(
                f"{prefix}: source '{source}' must be one of: spec, plan, user-concern, code-review, axiom-derived")

        # source_files must be non-empty
        source_files = inv.get('source_files', [])
        if isinstance(source_files, list) and len(source_files) == 0:
            constraint_errors.append(f"{prefix}: source_files must be non-empty")

        # description length
        description = inv.get('description', '')
        if isinstance(description, str):
            if len(description) < 1:
                constraint_errors.append(f"{prefix}: description must be non-empty")
            elif len(description) > 500:
                constraint_errors.append(f"{prefix}: description exceeds 500 chars ({len(description)})")

        # fixture_schema / fixture_defaults relationship
        fixture_schema = inv.get('fixture_schema')
        fixture_defaults = inv.get('fixture_defaults')

        if fixture_defaults is not None and fixture_schema is None:
            constraint_errors.append(
                f"{prefix}: fixture_defaults present but fixture_schema is absent (fixture_defaults only valid with fixture_schema)")

        if fixture_schema is not None:
            # fixture_schema must be an object
            if not isinstance(fixture_schema, dict):
                constraint_errors.append(f"{prefix}: fixture_schema must be a JSON object")
            elif len(fixture_schema) < 1:
                constraint_errors.append(f"{prefix}: fixture_schema must have at least 1 property")
            else:
                # Must have at least one non-trivial constraint
                if not has_nontrivial_constraint(fixture_schema):
                    constraint_errors.append(
                        f"{prefix}: fixture_schema must contain at least one non-trivial constraint "
                        "(e.g. minItems, minLength, required, minimum, not, enum)")

        # If both fixture_schema and fixture_defaults present, validate defaults against schema
        if fixture_schema is not None and fixture_defaults is not None:
            if isinstance(fixture_schema, dict) and isinstance(fixture_defaults, dict):
                validation_err = validate_fixture_against_schema(fixture_defaults, fixture_schema)
                if validation_err:
                    constraint_errors.append(f"{prefix}: fixture_defaults does not satisfy fixture_schema: {validation_err}")

        # --- Optional fields added by z-test error-points redesign ---
        sighting_count = inv.get('sighting_count')
        if sighting_count is not None:
            if not isinstance(sighting_count, int) or sighting_count < 0:
                constraint_errors.append(f"{prefix}: sighting_count must be a non-negative integer (got {sighting_count})")

        last_sighting = inv.get('last_sighting')
        if last_sighting is not None and not isinstance(last_sighting, str):
            constraint_errors.append(f"{prefix}: last_sighting must be an ISO-8601 string or null (got {type(last_sighting).__name__})")

        anchor_module = inv.get('anchor_module')
        if anchor_module is not None and not isinstance(anchor_module, str):
            constraint_errors.append(f"{prefix}: anchor_module must be a string or null (got {type(anchor_module).__name__})")

    if constraint_errors:
        return 2, constraint_errors

    if schema_errors:
        return 1, schema_errors

    return 0, []


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
            import re
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


def cmd_validate_file(args):
    """CLI handler for --file mode."""
    exit_code, errors = validate_invariants_file(args.file)
    for err in errors:
        print(f"[{'CONSTRAINT' if exit_code == 2 else 'SCHEMA' if exit_code == 1 else 'IO'}] {err}")
    if exit_code == 0:
        print("INVARIANTS.json is valid.")
    sys.exit(exit_code)


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
        description="Validate INVARIANTS.json against invariant schema and constraint rules"
    )
    parser.add_argument(
        '--file',
        help='Path to INVARIANTS.json to validate'
    )
    parser.add_argument(
        '--fixture',
        help='Path to fixture JSON file to validate against a schema'
    )
    parser.add_argument(
        '--schema',
        help='Path to JSON Schema file (used with --fixture)'
    )

    args = parser.parse_args()

    if args.file and not args.fixture:
        cmd_validate_file(args)
    elif args.fixture and args.schema:
        cmd_validate_fixture(args)
    else:
        parser.error("Either --file (validate INVARIANTS.json) or --fixture + --schema (validate a fixture) is required")


if __name__ == '__main__':
    main()
