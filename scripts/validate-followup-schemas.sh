#!/usr/bin/env bash
# validate-followup-schemas.sh — Test runner for followup JSON Schema validation.
#
# Validates 3 followup-entry fixtures (valid, invalid, edge) and 2 audit-evidence
# fixtures (valid, invalid) against their respective JSON Schema (draft-2020-12)
# files using the Python jsonschema library.
#
# Run with:
#   bash scripts/validate-followup-schemas.sh
#
# Exit codes:
#   0 — all assertions passed
#   1 — one or more assertions failed

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPTS_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPTS_DIR/..")"
SCHEMAS_DIR="$REPO_ROOT/docs/schemas"
FIXTURES_DIR="$SCHEMAS_DIR/fixtures"

ENTRY_SCHEMA="$SCHEMAS_DIR/followup-entry.schema.json"
EVIDENCE_SCHEMA="$SCHEMAS_DIR/audit-evidence.schema.json"

PASS=0
FAIL=0

# Declare temp-file variables upfront so the EXIT trap can always reference them.
BAD_HASH_TMP=""
MUTEX_TMP=""
NEITHER_TMP=""
EMPTY_OBJ_TMP=""
VERDICT_TMP=""
EXITCODE_TMP=""
# Per-run private stderr scratch file (replaces the fixed /tmp/schema-validate-err
# path, which was a clobber / symlink-attack risk and was never trapped for cleanup).
ERR_TMP="$(mktemp "${TMPDIR:-/tmp}/schema-validate-err-XXXXXX")"

# Clean up any temp files on exit (handles early exit from set -e as well).
trap 'rm -f "$BAD_HASH_TMP" "$MUTEX_TMP" "$NEITHER_TMP" "$EMPTY_OBJ_TMP" "$VERDICT_TMP" "$EXITCODE_TMP" "$ERR_TMP"' EXIT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_check_python() {
  if ! python3 -c "import jsonschema" 2>/dev/null; then
    echo "ERROR: Python jsonschema library not found. Install with: pip3 install jsonschema" >&2
    exit 2
  fi
}

# validate <schema_file> <instance_file>
# Returns 0 if valid, non-zero if invalid.
_validate() {
  local schema="$1"
  local instance="$2"
  python3 - "$schema" "$instance" <<'PYEOF'
import sys
import json
import jsonschema
from jsonschema import validate, ValidationError

schema_path = sys.argv[1]
instance_path = sys.argv[2]

with open(schema_path) as f:
    schema = json.load(f)
with open(instance_path) as f:
    instance = json.load(f)

try:
    validate(instance=instance, schema=schema)
    sys.exit(0)
except ValidationError as e:
    print(f"  ValidationError: {e.message}", file=sys.stderr)
    sys.exit(1)
PYEOF
}

# assert_valid <label> <schema_file> <instance_file>
assert_valid() {
  local label="$1"
  local schema="$2"
  local instance="$3"
  if _validate "$schema" "$instance" 2>"$ERR_TMP"; then
    echo "PASS  $label (expected valid)"
    PASS=$((PASS + 1))
  else
    echo "FAIL  $label (expected valid, got invalid)"
    cat "$ERR_TMP" >&2
    FAIL=$((FAIL + 1))
  fi
}

# assert_invalid <label> <schema_file> <instance_file>
assert_invalid() {
  local label="$1"
  local schema="$2"
  local instance="$3"
  if _validate "$schema" "$instance" 2>"$ERR_TMP"; then
    echo "FAIL  $label (expected invalid, but passed validation)"
    FAIL=$((FAIL + 1))
  else
    echo "PASS  $label (expected invalid, correctly rejected)"
    PASS=$((PASS + 1))
  fi
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

_check_python

echo "=== validate-followup-schemas.sh ==="
echo "Schema dir: $SCHEMAS_DIR"
echo "Fixtures:   $FIXTURES_DIR"
echo ""

# Verify schema files exist
for f in "$ENTRY_SCHEMA" "$EVIDENCE_SCHEMA"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: Schema file missing: $f" >&2
    exit 2
  fi
done

# Verify fixtures exist
for f in \
  "$FIXTURES_DIR/followup-entry-valid.json" \
  "$FIXTURES_DIR/followup-entry-invalid.json" \
  "$FIXTURES_DIR/followup-entry-edge.json" \
  "$FIXTURES_DIR/audit-evidence-valid.json" \
  "$FIXTURES_DIR/audit-evidence-invalid.json"
do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: Fixture missing: $f" >&2
    exit 2
  fi
done

# ---------------------------------------------------------------------------
# FollowupEntry tests
# ---------------------------------------------------------------------------
echo "--- followup-entry.schema.json ---"

assert_valid \
  "followup-entry / valid fixture (typical open entry with file_blob_hashes)" \
  "$ENTRY_SCHEMA" \
  "$FIXTURES_DIR/followup-entry-valid.json"

assert_invalid \
  "followup-entry / invalid fixture (bad priority P5, sink=notion, depth=5, attempt_count=-1, bad command)" \
  "$ENTRY_SCHEMA" \
  "$FIXTURES_DIR/followup-entry-invalid.json"

assert_valid \
  "followup-entry / edge fixture (dir_blob_hashes, depth=1, verify status, 16 cited_paths)" \
  "$ENTRY_SCHEMA" \
  "$FIXTURES_DIR/followup-entry-edge.json"

# ---------------------------------------------------------------------------
# file_blob_hashes format assertion: all values must match ^sha256:[0-9a-f]{64}$
# ---------------------------------------------------------------------------
echo ""
echo "--- file_blob_hashes sha256: format assertion ---"

FILE_HASH_FORMAT_PASS=true
python3 - "$FIXTURES_DIR/followup-entry-valid.json" <<'PYEOF'
import sys, json, re

with open(sys.argv[1]) as f:
    obj = json.load(f)

pattern = re.compile(r'^sha256:[0-9a-f]{64}$')
hashes = obj.get("file_blob_hashes") or {}
bad = [(k, v) for k, v in hashes.items() if not pattern.match(str(v))]
if bad:
    for k, v in bad:
        print(f"  BAD hash for {k!r}: {v!r}", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
PYEOF
if [[ $? -eq 0 ]]; then
  echo "PASS  file_blob_hashes values all match ^sha256:[0-9a-f]{64}$"
  PASS=$((PASS + 1))
else
  echo "FAIL  file_blob_hashes values in valid fixture do not match ^sha256:[0-9a-f]{64}$"
  FAIL=$((FAIL + 1))
fi

# Bad-format fixture: ensure a raw git SHA (no sha256: prefix) is rejected by schema
BAD_HASH_TMP="$(mktemp /tmp/followup-bad-hash-XXXXXX.json)"
python3 - "$FIXTURES_DIR/followup-entry-valid.json" "$BAD_HASH_TMP" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    obj = json.load(f)
# Replace with a raw 40-char git SHA (no sha256: prefix) — must fail schema validation
obj["file_blob_hashes"] = {"README.md": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"}
with open(sys.argv[2], "w") as f:
    json.dump(obj, f)
PYEOF
assert_invalid \
  "followup-entry / raw git SHA (no sha256: prefix) rejected by file_blob_hashes pattern" \
  "$ENTRY_SCHEMA" \
  "$BAD_HASH_TMP"
rm -f "$BAD_HASH_TMP"

# ---------------------------------------------------------------------------
# Mutual exclusion test: both file_blob_hashes AND dir_blob_hashes set
# ---------------------------------------------------------------------------
echo ""
echo "--- blob_hash mutex test ---"

MUTEX_TMP="$(mktemp /tmp/followup-mutex-XXXXXX.json)"
python3 - "$FIXTURES_DIR/followup-entry-valid.json" "$MUTEX_TMP" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    obj = json.load(f)
# Inject dir_blob_hashes alongside file_blob_hashes to violate the mutex
obj["dir_blob_hashes"] = {"scripts": "sha256:c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"}
with open(sys.argv[2], "w") as f:
    json.dump(obj, f)
PYEOF
assert_invalid \
  "followup-entry / mutex violation (both file_blob_hashes AND dir_blob_hashes non-null)" \
  "$ENTRY_SCHEMA" \
  "$MUTEX_TMP"
rm -f "$MUTEX_TMP"

# Neither-set fixture: both file_blob_hashes and dir_blob_hashes are null — must be rejected
# (sink-add always sets exactly one; an entry with neither is schema-invalid)
NEITHER_TMP="$(mktemp /tmp/followup-neither-hash-XXXXXX.json)"
python3 - "$FIXTURES_DIR/followup-entry-valid.json" "$NEITHER_TMP" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    obj = json.load(f)
obj["file_blob_hashes"] = None
obj["dir_blob_hashes"] = None
with open(sys.argv[2], "w") as f:
    json.dump(obj, f)
PYEOF
assert_invalid \
  "followup-entry / neither-set (both file_blob_hashes AND dir_blob_hashes are null)" \
  "$ENTRY_SCHEMA" \
  "$NEITHER_TMP"
rm -f "$NEITHER_TMP"

# Empty-object fixture: file_blob_hashes={} is treated as absent (not a valid "set")
EMPTY_OBJ_TMP="$(mktemp /tmp/followup-empty-hash-XXXXXX.json)"
python3 - "$FIXTURES_DIR/followup-entry-valid.json" "$EMPTY_OBJ_TMP" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    obj = json.load(f)
obj["file_blob_hashes"] = {}
obj["dir_blob_hashes"] = None
with open(sys.argv[2], "w") as f:
    json.dump(obj, f)
PYEOF
assert_invalid \
  "followup-entry / empty-object file_blob_hashes ({}) treated as absent, rejected by at-least-one" \
  "$ENTRY_SCHEMA" \
  "$EMPTY_OBJ_TMP"
rm -f "$EMPTY_OBJ_TMP"

# ---------------------------------------------------------------------------
# AuditEvidence tests
# ---------------------------------------------------------------------------
echo ""
echo "--- audit-evidence.schema.json ---"

assert_valid \
  "audit-evidence / valid fixture (review_verdict=PASS, test_exit_code=0, schema_version=1)" \
  "$EVIDENCE_SCHEMA" \
  "$FIXTURES_DIR/audit-evidence-valid.json"

assert_invalid \
  "audit-evidence / invalid fixture (schema_version=2, verdict=FAIL, exit_code=1)" \
  "$EVIDENCE_SCHEMA" \
  "$FIXTURES_DIR/audit-evidence-invalid.json"

# ---------------------------------------------------------------------------
# Enum literals test: audit evidence with wrong verdict string
# ---------------------------------------------------------------------------
VERDICT_TMP="$(mktemp /tmp/audit-evidence-verdict-XXXXXX.json)"
python3 - "$FIXTURES_DIR/audit-evidence-valid.json" "$VERDICT_TMP" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    obj = json.load(f)
obj["review_verdict"] = "pass"  # wrong case — must be PASS
with open(sys.argv[2], "w") as f:
    json.dump(obj, f)
PYEOF
assert_invalid \
  "audit-evidence / wrong verdict case (\"pass\" instead of \"PASS\")" \
  "$EVIDENCE_SCHEMA" \
  "$VERDICT_TMP"
rm -f "$VERDICT_TMP"

EXITCODE_TMP="$(mktemp /tmp/audit-evidence-exit-XXXXXX.json)"
python3 - "$FIXTURES_DIR/audit-evidence-valid.json" "$EXITCODE_TMP" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    obj = json.load(f)
obj["test_exit_code"] = 1  # must be 0
with open(sys.argv[2], "w") as f:
    json.dump(obj, f)
PYEOF
assert_invalid \
  "audit-evidence / non-zero exit code (1 instead of 0)" \
  "$EVIDENCE_SCHEMA" \
  "$EXITCODE_TMP"
rm -f "$EXITCODE_TMP"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
