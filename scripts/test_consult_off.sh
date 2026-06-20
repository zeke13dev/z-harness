#!/usr/bin/env bash
# test_consult_off.sh — Tests for Z_HARNESS_CONSULT=off single-model mode
#
# Run with:
#   bash scripts/test_consult_off.sh
#
# Tests:
#   1. Z_HARNESS_CONSULT=off → resolve-provider.py prints "none" and exits 0
#      for consultant_primary, consultant_secondary, and reviewer roles
#   2. Z_HARNESS_CONSULT=off → no distinctness error even with identical
#      consultant_primary and consultant_secondary providers
#   3. Z_HARNESS_CONSULT=on (explicit) → resolve-provider.py does NOT short-circuit
#      (falls through to normal resolution; exits non-zero when no config is present)
#   4. Z_HARNESS_CONSULT unset → same behavior as "on"; no sentinel returned
#   8. TOML path: [runtime] consult = "off" → config.py export-env emits Z_HARNESS_CONSULT=off
#   9. TOML path end-to-end: sourcing export-env from TOML config causes resolve-provider.py
#      to return "none" for consultant/reviewer roles

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
RESOLVE_PY="$SCRIPTS_DIR/resolve-provider.py"
CONFIG_PY="$SCRIPTS_DIR/config.py"

# Hermetic isolation of the user-global config layer. resolve-provider.py and
# config.py read $XDG_CONFIG_HOME/z-harness/{providers,config}.* as the global
# layer (falling back to ~/.config). The tests below set Z_HARNESS_REPO_PROVIDERS
# to an empty repo-layer file to assert "unbound role" / sentinel behavior — but
# that only isolates the *repo* layer. Without isolating the global layer too,
# the developer's real ~/.config/z-harness/providers.json (which binds
# consultant_primary→codex etc.) leaks in and resolution succeeds, breaking
# TEST-005/006/009. Point XDG_CONFIG_HOME at an empty dir for the whole run.
_XDG_ISOLATED="$(mktemp -d "${TMPDIR:-/tmp}/test_consult_xdg_XXXXXX")"
export XDG_CONFIG_HOME="$_XDG_ISOLATED"
trap 'rm -rf "$_XDG_ISOLATED"' EXIT

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    echo "        expected: $(printf '%q' "$expected")"
    echo "        actual:   $(printf '%q' "$actual")"
    FAIL=$((FAIL + 1))
  fi
}

assert_exit_zero() {
  local label="$1" exit_code="$2"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "  PASS: $label (exit 0)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — expected exit 0, got $exit_code"
    FAIL=$((FAIL + 1))
  fi
}

assert_exit_nonzero() {
  local label="$1" exit_code="$2"
  if [[ "$exit_code" -ne 0 ]]; then
    echo "  PASS: $label (exit $exit_code)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — expected non-zero exit, got 0"
    FAIL=$((FAIL + 1))
  fi
}

# Run resolve-provider.py with an empty providers config so the only thing
# that could return "none" is the Z_HARNESS_CONSULT=off path.
# Z_HARNESS_REPO_PROVIDERS points to an empty temp file.
_empty_providers_json() {
  local tmp
  tmp="$(mktemp /tmp/test_consult_providers_XXXXXX.json)"
  echo '{"version":2,"providers":{},"roles":{}}' > "$tmp"
  echo "$tmp"
}

# ---------------------------------------------------------------------------
# TEST-001: Z_HARNESS_CONSULT=off → "none" + exit 0 for consultant_primary
# ---------------------------------------------------------------------------
echo ""
echo "TEST-001: Z_HARNESS_CONSULT=off → consultant_primary returns 'none' (exit 0)"

EMPTY_PROVIDERS="$(_empty_providers_json)"

EXIT_001=0
OUTPUT_001="$(Z_HARNESS_CONSULT=off Z_HARNESS_REPO_PROVIDERS="$EMPTY_PROVIDERS" \
  python3 "$RESOLVE_PY" consultant_primary 2>/dev/null)" || EXIT_001=$?

assert_eq    "TEST-001: stdout is 'none'" "none" "$OUTPUT_001"
assert_exit_zero "TEST-001: exit code is 0" "$EXIT_001"

rm -f "$EMPTY_PROVIDERS"

# ---------------------------------------------------------------------------
# TEST-002: Z_HARNESS_CONSULT=off → "none" + exit 0 for consultant_secondary
# ---------------------------------------------------------------------------
echo ""
echo "TEST-002: Z_HARNESS_CONSULT=off → consultant_secondary returns 'none' (exit 0)"

EMPTY_PROVIDERS="$(_empty_providers_json)"

EXIT_002=0
OUTPUT_002="$(Z_HARNESS_CONSULT=off Z_HARNESS_REPO_PROVIDERS="$EMPTY_PROVIDERS" \
  python3 "$RESOLVE_PY" consultant_secondary 2>/dev/null)" || EXIT_002=$?

assert_eq    "TEST-002: stdout is 'none'" "none" "$OUTPUT_002"
assert_exit_zero "TEST-002: exit code is 0" "$EXIT_002"

rm -f "$EMPTY_PROVIDERS"

# ---------------------------------------------------------------------------
# TEST-003: Z_HARNESS_CONSULT=off → "none" + exit 0 for reviewer
# ---------------------------------------------------------------------------
echo ""
echo "TEST-003: Z_HARNESS_CONSULT=off → reviewer returns 'none' (exit 0)"

EMPTY_PROVIDERS="$(_empty_providers_json)"

EXIT_003=0
OUTPUT_003="$(Z_HARNESS_CONSULT=off Z_HARNESS_REPO_PROVIDERS="$EMPTY_PROVIDERS" \
  python3 "$RESOLVE_PY" reviewer 2>/dev/null)" || EXIT_003=$?

assert_eq    "TEST-003: stdout is 'none'" "none" "$OUTPUT_003"
assert_exit_zero "TEST-003: exit code is 0" "$EXIT_003"

rm -f "$EMPTY_PROVIDERS"

# ---------------------------------------------------------------------------
# TEST-004: Z_HARNESS_CONSULT=off → no distinctness error (same provider for both)
#
# Invariant: check_consultant_distinctness is bypassed when consult=off.
# With consult=on and both consultant roles bound to the same provider,
# resolve-provider.py would exit 1.  With consult=off, it exits 0.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-004: Z_HARNESS_CONSULT=off → no distinctness error for identical consultants"

# Providers config where both consultant roles map to the SAME provider.
# Without the consult=off guard, this would trigger the distinctness check
# and exit 1.  With consult=off, we never reach that check.
SAME_PROVIDERS="$(mktemp /tmp/test_consult_same_providers_XXXXXX.json)"
cat > "$SAME_PROVIDERS" <<'EOF'
{
  "version": 2,
  "providers": {
    "claude": {
      "kind": "cli",
      "command": "claude",
      "args_template": [],
      "stdin": true,
      "timeout_s": 300,
      "model_label": "claude",
      "model_arg_template": null,
      "model_env_var": null,
      "default_model": null
    }
  },
  "roles": {
    "consultant_primary": "claude",
    "consultant_secondary": "claude"
  }
}
EOF

EXIT_004=0
OUTPUT_004="$(Z_HARNESS_CONSULT=off Z_HARNESS_REPO_PROVIDERS="$SAME_PROVIDERS" \
  python3 "$RESOLVE_PY" consultant_primary 2>/dev/null)" || EXIT_004=$?

assert_eq    "TEST-004: stdout is 'none'" "none" "$OUTPUT_004"
assert_exit_zero "TEST-004: exit code is 0 (distinctness check skipped)" "$EXIT_004"

rm -f "$SAME_PROVIDERS"

# ---------------------------------------------------------------------------
# TEST-005: Z_HARNESS_CONSULT=on → falls through to normal resolution
#
# Invariant: with consult=on (or unset), the sentinel path is NOT taken.
# With an empty providers config, the normal resolution path is taken and
# exits non-zero (role unbound / no matching provider).
# ---------------------------------------------------------------------------
echo ""
echo "TEST-005: Z_HARNESS_CONSULT=on → normal resolution attempted (exits non-zero when unbound)"

EMPTY_PROVIDERS="$(_empty_providers_json)"

EXIT_005=0
OUTPUT_005="$(Z_HARNESS_CONSULT=on Z_HARNESS_REPO_PROVIDERS="$EMPTY_PROVIDERS" \
  python3 "$RESOLVE_PY" consultant_primary 2>/dev/null)" || EXIT_005=$?

assert_exit_nonzero "TEST-005: exits non-zero (normal resolution, unbound role)" "$EXIT_005"

# Critical: stdout must NOT be "none" — the sentinel was not returned.
if [[ "$OUTPUT_005" == "none" ]]; then
  echo "  FAIL: TEST-005: stdout was 'none' but sentinel should not fire on consult=on"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: TEST-005: stdout is not 'none' (normal path taken)"
  PASS=$((PASS + 1))
fi

rm -f "$EMPTY_PROVIDERS"

# ---------------------------------------------------------------------------
# TEST-006: Z_HARNESS_CONSULT unset → same as "on"; no sentinel returned
# ---------------------------------------------------------------------------
echo ""
echo "TEST-006: Z_HARNESS_CONSULT unset → normal resolution attempted (exits non-zero when unbound)"

EMPTY_PROVIDERS="$(_empty_providers_json)"

EXIT_006=0
OUTPUT_006="$(Z_HARNESS_REPO_PROVIDERS="$EMPTY_PROVIDERS" \
  python3 "$RESOLVE_PY" consultant_primary 2>/dev/null)" || EXIT_006=$?

assert_exit_nonzero "TEST-006: exits non-zero (unset consult, unbound role)" "$EXIT_006"

if [[ "$OUTPUT_006" == "none" ]]; then
  echo "  FAIL: TEST-006: stdout was 'none' but sentinel should not fire when var is unset"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: TEST-006: stdout is not 'none' (normal path taken)"
  PASS=$((PASS + 1))
fi

rm -f "$EMPTY_PROVIDERS"

# ---------------------------------------------------------------------------
# TEST-007: Z_HARNESS_CONSULT=off does NOT affect unrelated roles (e.g. "implementer")
# ---------------------------------------------------------------------------
echo ""
echo "TEST-007: Z_HARNESS_CONSULT=off does NOT return 'none' for unrelated roles"

EMPTY_PROVIDERS="$(_empty_providers_json)"

EXIT_007=0
OUTPUT_007="$(Z_HARNESS_CONSULT=off Z_HARNESS_REPO_PROVIDERS="$EMPTY_PROVIDERS" \
  python3 "$RESOLVE_PY" implementer 2>/dev/null)" || EXIT_007=$?

assert_exit_nonzero "TEST-007: exits non-zero (implementer role unbound, normal path)" "$EXIT_007"

if [[ "$OUTPUT_007" == "none" ]]; then
  echo "  FAIL: TEST-007: stdout was 'none' but 'implementer' is not a consult role"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: TEST-007: stdout is not 'none' (implementer not affected by consult=off)"
  PASS=$((PASS + 1))
fi

rm -f "$EMPTY_PROVIDERS"

# ---------------------------------------------------------------------------
# TEST-008: TOML path — [runtime] consult = "off" → export-env emits Z_HARNESS_CONSULT=off
#
# Invariant (B2 fix): config.py export-env must export 'runtime.consult' as
# Z_HARNESS_CONSULT (not Z_HARNESS_RUNTIME_CONSULT). Setting consult="off" in
# TOML must produce 'export Z_HARNESS_CONSULT=off' in the export-env output.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-008: TOML [runtime] consult = \"off\" → config.py export-env emits Z_HARNESS_CONSULT=off"

TOML_CONFIG_008="$(mktemp /tmp/test_consult_config_XXXXXX.toml)"
cat > "$TOML_CONFIG_008" <<'EOF'
schema_version = 1
[runtime]
consult = "off"
EOF

EXIT_008=0
OUTPUT_008="$(Z_HARNESS_REPO_CONFIG="$TOML_CONFIG_008" python3 "$CONFIG_PY" export-env 2>/dev/null \
  | grep 'Z_HARNESS_CONSULT')" || EXIT_008=$?

# Must contain 'export Z_HARNESS_CONSULT=off' (not Z_HARNESS_RUNTIME_CONSULT)
if echo "$OUTPUT_008" | grep -q "^export Z_HARNESS_CONSULT='off'$\|^export Z_HARNESS_CONSULT=off$"; then
  echo "  PASS: TEST-008: export-env emits Z_HARNESS_CONSULT=off"
  PASS=$((PASS + 1))
else
  echo "  FAIL: TEST-008: export-env did not emit Z_HARNESS_CONSULT=off"
  echo "        actual output: $(printf '%q' "$OUTPUT_008")"
  FAIL=$((FAIL + 1))
fi

# Must NOT emit Z_HARNESS_RUNTIME_CONSULT
if echo "$OUTPUT_008" | grep -q "Z_HARNESS_RUNTIME_CONSULT"; then
  echo "  FAIL: TEST-008: export-env emitted Z_HARNESS_RUNTIME_CONSULT (wrong var name)"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: TEST-008: export-env does not emit Z_HARNESS_RUNTIME_CONSULT"
  PASS=$((PASS + 1))
fi

rm -f "$TOML_CONFIG_008"

# ---------------------------------------------------------------------------
# TEST-009: TOML end-to-end — sourcing export-env from TOML config causes
# resolve-provider.py to return "none" for reviewer role
#
# Invariant: the full TOML→export-env→resolve-provider chain must honor
# runtime.consult=off. This tests that the env alias is correctly wired.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-009: TOML end-to-end → sourcing export-env causes resolve-provider.py to return 'none'"

TOML_CONFIG_009="$(mktemp /tmp/test_consult_config_XXXXXX.toml)"
cat > "$TOML_CONFIG_009" <<'EOF'
schema_version = 1
[runtime]
consult = "off"
EOF

EMPTY_PROVIDERS_009="$(_empty_providers_json)"

EXIT_009=0
# Export-env emits 'export Z_HARNESS_CONSULT=off'; eval it so resolve-provider sees it.
OUTPUT_009="$(
  eval "$(Z_HARNESS_REPO_CONFIG="$TOML_CONFIG_009" python3 "$CONFIG_PY" export-env 2>/dev/null)"
  Z_HARNESS_REPO_PROVIDERS="$EMPTY_PROVIDERS_009" python3 "$RESOLVE_PY" reviewer 2>/dev/null
)" || EXIT_009=$?

assert_eq    "TEST-009: resolve-provider.py returns 'none' via TOML path" "none" "$OUTPUT_009"
assert_exit_zero "TEST-009: exit code is 0" "$EXIT_009"

rm -f "$TOML_CONFIG_009" "$EMPTY_PROVIDERS_009"

# ---------------------------------------------------------------------------
# TEST-010: consult=off review path in z-implement-all.md references
#           subagent_type="self-reviewer" (not "reviewer")
#
# Invariant: when Z_HARNESS_CONSULT=off, the orchestrator must dispatch a
# dedicated self-reviewer subagent that does not call resolve-provider.
# Using subagent_type="reviewer" would crash because reviewer.md calls
# resolve-provider.sh, which returns the plaintext sentinel "none", and
# the reviewer then tries to json.load("none") → crash.
# This is a doc-level assertion (the orchestration instructions are .md).
# ---------------------------------------------------------------------------
echo ""
echo "TEST-010: z-implement-all.md consult=off branches use subagent_type=\"self-reviewer\""

Z_IMPLEMENT_ALL="$(dirname "$SCRIPTS_DIR")/skills/z-implement-all/SKILL.md"

if [ ! -f "$Z_IMPLEMENT_ALL" ]; then
  echo "  FAIL: TEST-010: cannot find $Z_IMPLEMENT_ALL"
  FAIL=$((FAIL + 1))
else
  # Count occurrences of subagent_type="self-reviewer" in the consult-off blocks.
  SELF_REVIEWER_COUNT="$(grep -c 'subagent_type="self-reviewer"' "$Z_IMPLEMENT_ALL" 2>/dev/null || true)"

  if [[ "$SELF_REVIEWER_COUNT" -ge 2 ]]; then
    echo "  PASS: TEST-010: found $SELF_REVIEWER_COUNT occurrences of subagent_type=\"self-reviewer\" (≥2 required)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: TEST-010: expected ≥2 occurrences of subagent_type=\"self-reviewer\" in z-implement-all.md, found $SELF_REVIEWER_COUNT"
    FAIL=$((FAIL + 1))
  fi

  # Additionally confirm self-reviewer.md exists and does NOT reference resolve-provider.sh as a call.
  SELF_REVIEWER_AGENT="$(dirname "$SCRIPTS_DIR")/agents/self-reviewer.md"

  if [ ! -f "$SELF_REVIEWER_AGENT" ]; then
    echo "  FAIL: TEST-010b: agents/self-reviewer.md does not exist"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: TEST-010b: agents/self-reviewer.md exists"
    PASS=$((PASS + 1))
  fi

  # Confirm self-reviewer.md does not INVOKE resolve-provider (it may only mention it in prohibition text).
  # We check that there's no bash call pattern like: bash scripts/resolve-provider.sh or $(...resolve-provider.sh...)
  if grep -E 'bash .*resolve-provider\.sh|scripts/resolve-provider\.sh [a-z]' "$SELF_REVIEWER_AGENT" 2>/dev/null | grep -qv '^\s*#\|MUST NOT\|does not\|do NOT\|NOT call'; then
    echo "  FAIL: TEST-010c: agents/self-reviewer.md appears to invoke resolve-provider.sh"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: TEST-010c: agents/self-reviewer.md does not invoke resolve-provider.sh"
    PASS=$((PASS + 1))
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
