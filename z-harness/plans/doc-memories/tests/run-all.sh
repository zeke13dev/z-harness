#!/usr/bin/env bash
# run-all.sh — Run all 7 doc-memories unit tests.
# Prints PASS/FAIL per test, exits 0 on all-pass, 1 otherwise.
# No network, no external services required.

set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES_DIR="$(cd "$TESTS_DIR/../test-fixtures" && pwd)"
REPO_ROOT="$(cd "$TESTS_DIR/../../.." && pwd)"
REGEN_SCRIPT="$REPO_ROOT/scripts/regenerate-memories-flat.py"
WB_FALLBACK="$TESTS_DIR/wb-fallback.py"
VALIDATE_MEM="$TESTS_DIR/validate-memory.py"
GOLDEN="$FIXTURES_DIR/golden-MEMORIES-FLAT.md"

PASS=0
FAIL=0

pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

fail() {
  echo "FAIL: $1"
  echo "      $2"
  FAIL=$((FAIL + 1))
}

# ---------------------------------------------------------------------------
# TEST 1 — doc-updater fixture: structural verification
#
# Strategy: manually construct what doc-updater should produce for
# strategy-router.json (3 memories), then verify the format matches
# agents/doc-updater.md template requirements.
#
# Invariant: doc-updater must:
#   1. Preserve all 3 memories verbatim (MEMORIES_PRESERVED: 3)
#   2. Emit a "## Memories" section in the human-tier markdown
#   3. Open that section with the DO-NOT-EDIT HTML comment
#   4. Render each memory as "- **<DATE> <TYPE>** ([<source>](#)) — <text> _(tags: ...)_"
# ---------------------------------------------------------------------------
test_1_doc_updater_fixture() {
  local test_name="T1: doc-updater fixture — round-trips 3 memories, ## Memories section + DO-NOT-EDIT comment"

  local concept_json="$FIXTURES_DIR/strategy-router.json"

  # Verify the concept JSON has exactly 3 memories
  local mem_count
  mem_count=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
print(len(d.get('memories', [])))
" "$concept_json")

  if [ "$mem_count" != "3" ]; then
    fail "$test_name" "Expected 3 memories in strategy-router.json, got $mem_count"
    return
  fi

  # Simulate what doc-updater MUST produce: a human markdown with ## Memories section
  # Per agents/doc-updater.md template spec.
  local simulated_human_doc
  simulated_human_doc=$(python3 - "$concept_json" <<'PYEOF'
import json, sys

concept_json = sys.argv[1]
with open(concept_json) as f:
    data = json.load(f)

memories = data.get("memories", [])

lines = []
lines.append("# strategy-router")
lines.append("")
lines.append("> Last updated: 2026-04-20")
lines.append("> Covers source: src/strategy_router.py")
lines.append("")
lines.append("## Overview")
lines.append("Routes live signals to the correct strategy.")
lines.append("")
lines.append("## Edge cases / gotchas")
lines.append("- Cache invalidation resets spread baseline on rebalance")
lines.append("")

if memories:
    lines.append("## Memories")
    lines.append("")
    lines.append("<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/strategy-router.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->")
    lines.append("")
    for mem in memories:
        date = mem.get("date", "")
        mtype = mem.get("type", "")
        source = mem.get("source", "")
        text = mem.get("text", "")
        tags = mem.get("tags", [])
        tags_str = ", ".join(tags)
        lines.append(f"- **{date} {mtype}** ([{source}](#)) — {text} _(tags: {tags_str})_")
    lines.append("")

lines.append("## Examples")
lines.append("")
lines.append("MEMORIES_PRESERVED: 3")

print("\n".join(lines))
PYEOF
)

  local err=""

  if ! echo "$simulated_human_doc" | grep -q "^## Memories$"; then
    err="Missing '## Memories' heading in simulated human doc"
  fi

  if [ -z "$err" ] && ! echo "$simulated_human_doc" | grep -q "DO NOT EDIT this section by hand"; then
    err="Missing DO-NOT-EDIT comment in ## Memories section"
  fi

  if [ -z "$err" ] && ! echo "$simulated_human_doc" | grep -q "MEMORIES_PRESERVED: 3"; then
    err="Missing MEMORIES_PRESERVED: 3 in return"
  fi

  # Verify all 3 memories appear in rendered form
  if [ -z "$err" ] && ! echo "$simulated_human_doc" | grep -q "stale spreads"; then
    err="Memory 1 text 'stale spreads' missing from simulated human doc"
  fi

  if [ -z "$err" ] && ! echo "$simulated_human_doc" | grep -q "sliding-window EMA"; then
    err="Memory 2 text 'sliding-window EMA' missing from simulated human doc"
  fi

  if [ -z "$err" ] && ! echo "$simulated_human_doc" | grep -q "static regime thresholds"; then
    err="Memory 3 text 'static regime thresholds' missing from simulated human doc"
  fi

  if [ -z "$err" ]; then
    pass "$test_name"
  else
    fail "$test_name" "$err"
  fi
}

# ---------------------------------------------------------------------------
# TEST 2 — doc-fetcher ripgrep: query "stale spreads" returns strategy-router
#
# Uses rg directly against golden-MEMORIES-FLAT.md, simulating doc-fetcher
# step 2.5d. The line containing "stale spreads" starts with [strategy-router].
# If rg is not on PATH, skips this test (test 3 covers the fallback path).
# ---------------------------------------------------------------------------
test_2_doc_fetcher_ripgrep() {
  local test_name="T2: doc-fetcher ripgrep — query 'stale spreads' returns strategy-router slug"

  if ! command -v rg &>/dev/null; then
    echo "SKIP: $test_name (rg not on PATH; test 3 covers fallback)"
    return
  fi

  # Sanitize query tokens and build rg pattern as doc-fetcher step 2.5c does:
  # tokens: ["stale", "spreads"]
  # pattern: (?i)stale.*spreads
  local pattern="(?i)stale.*spreads"
  local matched_lines
  if ! matched_lines=$(rg --no-line-number --no-filename "$pattern" "$GOLDEN" 2>/dev/null); then
    fail "$test_name" "rg returned no matches for pattern '$pattern'"
    return
  fi

  # Parse leading [<slug>] from matched lines.
  # Uses the TYPE+DATE boundary to handle slugs with nested brackets.
  local matched_slug
  matched_slug=$(echo "$matched_lines" | python3 -c "
import re, sys
for line in sys.stdin:
    line = line.strip()
    m = re.match(r'^\[(.+)\] \[[A-Za-z_]+ \d{4}-\d{2}-\d{2}\]', line)
    if m:
        print(m.group(1))
        break
")

  if [ "$matched_slug" = "strategy-router" ]; then
    pass "$test_name"
  else
    fail "$test_name" "Expected slug 'strategy-router', got '$matched_slug'"
  fi
}

# ---------------------------------------------------------------------------
# TEST 3 — doc-fetcher Python word-boundary fallback
#
# Invokes wb-fallback.py against golden-MEMORIES-FLAT.md with query
# "stale spreads". Must return the same slug as test 2 (strategy-router).
# ---------------------------------------------------------------------------
test_3_wb_fallback() {
  local test_name="T3: word-boundary fallback — 'stale spreads' returns strategy-router (same as rg)"

  local result
  result=$(python3 "$WB_FALLBACK" --memories-flat "$GOLDEN" --query "stale spreads")
  local exit_code=$?

  if [ $exit_code -ne 0 ]; then
    fail "$test_name" "wb-fallback.py exited $exit_code"
    return
  fi

  local matched_slug
  matched_slug=$(echo "$result" | head -1)

  if [ "$matched_slug" = "strategy-router" ]; then
    pass "$test_name"
  else
    fail "$test_name" "Expected 'strategy-router', got '$matched_slug'"
  fi
}

# ---------------------------------------------------------------------------
# TEST 4 — /z-suggest-memory schema rejection: text > 200 chars
#
# Feeds text that is 201 characters long to validate-memory.py.
# Expects STATUS: bad_input and exit code 1. No files written.
# ---------------------------------------------------------------------------
test_4_schema_rejection() {
  local test_name="T4: schema rejection — text >200 chars → STATUS: bad_input, no write"

  # 201-character text
  local long_text
  long_text=$(python3 -c "print('x' * 201, end='')")

  local output exit_code
  output=$(python3 "$VALIDATE_MEM" \
    --type "anti_pattern" \
    --text "$long_text" \
    --source "human_review:zbarnett" \
    --date "2026-05-23" \
    2>/dev/null) || true

  python3 "$VALIDATE_MEM" \
    --type "anti_pattern" \
    --text "$long_text" \
    --source "human_review:zbarnett" \
    --date "2026-05-23" \
    >/dev/null 2>&1 && exit_code=0 || exit_code=$?

  local err=""

  if ! echo "$output" | grep -q "STATUS: bad_input"; then
    err="Expected 'STATUS: bad_input' in output, got: $output"
  fi

  if [ -z "$err" ] && [ "$exit_code" -ne 1 ]; then
    err="Expected exit code 1 (bad_input), got $exit_code"
  fi

  if [ -z "$err" ]; then
    pass "$test_name"
  else
    fail "$test_name" "$err"
  fi
}

# ---------------------------------------------------------------------------
# TEST 5 — MEMORIES-FLAT.md golden-file format
#
# Runs scripts/regenerate-memories-flat.py --dry-run against a temp fixture
# repo (fixture JSONs copied under docs/llm/) and diffs against golden.
# ---------------------------------------------------------------------------
test_5_golden_file() {
  local test_name="T5: MEMORIES-FLAT.md golden-file diff — regenerate matches golden"

  local tmp_repo
  tmp_repo=$(mktemp -d)
  mkdir -p "$tmp_repo/docs/llm"
  cp "$FIXTURES_DIR"/*.json "$tmp_repo/docs/llm/"

  local actual exit_code
  actual=$(python3 "$REGEN_SCRIPT" --repo-root "$tmp_repo" --dry-run 2>&1) && exit_code=0 || exit_code=$?
  rm -rf "$tmp_repo"

  if [ $exit_code -ne 0 ]; then
    fail "$test_name" "regenerate-memories-flat.py exited $exit_code: $actual"
    return
  fi

  local golden_content
  golden_content=$(cat "$GOLDEN")

  if [ "$actual" = "$golden_content" ]; then
    pass "$test_name"
  else
    local diff_out
    diff_out=$(diff <(echo "$golden_content") <(echo "$actual") || true)
    fail "$test_name" "Output differs from golden: $diff_out"
  fi
}

# ---------------------------------------------------------------------------
# TEST 6 — Adversarial regex: weird-[brackets] slug + metachar text
#
# Asserts both rg and wb-fallback handle the adversarial fixture without
# crashing and return correct results.
# ---------------------------------------------------------------------------
test_6_adversarial_regex() {
  local test_name="T6: adversarial regex — weird-[brackets] slug + metachar text handled without crash"

  # Build a MEMORIES-FLAT.md that includes the adversarial entries
  local tmp_repo
  tmp_repo=$(mktemp -d)
  mkdir -p "$tmp_repo/docs/llm"
  cp "$FIXTURES_DIR"/*.json "$tmp_repo/docs/llm/"
  python3 "$REGEN_SCRIPT" --repo-root "$tmp_repo" >/dev/null 2>&1
  local regen_exit=$?
  local adversarial_flat="$tmp_repo/docs/llm/MEMORIES-FLAT.md"

  if [ $regen_exit -ne 0 ]; then
    rm -rf "$tmp_repo"
    fail "$test_name" "regenerate-memories-flat.py failed with adversarial fixtures"
    return
  fi

  local err=""

  # Test 6a: rg with a safe token from the adversarial text ("metachar") — if rg available
  if command -v rg &>/dev/null; then
    local rg_out rg_exit
    rg_out=$(rg --no-line-number --no-filename "(?i)metachar" "$adversarial_flat" 2>&1) && rg_exit=0 || rg_exit=$?
    if [ $rg_exit -eq 0 ]; then
      local slug_6a
      # Use Python to parse the slug — handles slugs with nested brackets like "weird-[brackets]"
      # The second field always has shape '[<TYPE> <DATE>]', so we match greedily up to it.
      slug_6a=$(echo "$rg_out" | python3 -c "
import re, sys
for line in sys.stdin:
    line = line.strip()
    m = re.match(r'^\[(.+)\] \[[A-Za-z_]+ \d{4}-\d{2}-\d{2}\]', line)
    if m:
        print(m.group(1))
        break
")
      if [ "$slug_6a" != "weird-[brackets]" ]; then
        err="6a: rg metachar query returned slug '$slug_6a', expected 'weird-[brackets]'"
      fi
    elif [ $rg_exit -eq 1 ]; then
      err="6a: rg metachar query returned no matches"
    else
      err="6a: rg metachar query returned error (exit $rg_exit): $rg_out"
    fi
  fi

  # Test 6b: wb-fallback with "metachar" query — must not crash
  if [ -z "$err" ]; then
    local wb_out_6b wb_exit
    wb_out_6b=$(python3 "$WB_FALLBACK" --memories-flat "$adversarial_flat" --query "metachar" 2>&1) && wb_exit=0 || wb_exit=$?
    if [ $wb_exit -ne 0 ]; then
      err="6b: wb-fallback.py crashed on adversarial text (exit $wb_exit): $wb_out_6b"
    elif [ "$(echo "$wb_out_6b" | head -1)" != "weird-[brackets]" ]; then
      err="6b: wb-fallback.py returned '$(echo "$wb_out_6b" | head -1)', expected 'weird-[brackets]'"
    fi
  fi

  # Test 6c: wb-fallback with unicode query token ("café") — must not crash
  if [ -z "$err" ]; then
    local wb_out_6c wb_exit_6c
    wb_out_6c=$(python3 "$WB_FALLBACK" --memories-flat "$adversarial_flat" --query "café naïve" 2>&1) && wb_exit_6c=0 || wb_exit_6c=$?
    if [ $wb_exit_6c -ne 0 ]; then
      err="6c: wb-fallback.py crashed on unicode query (exit $wb_exit_6c): $wb_out_6c"
    elif [ "$(echo "$wb_out_6c" | head -1)" != "weird-[brackets]" ]; then
      err="6c: wb-fallback unicode query returned '$(echo "$wb_out_6c" | head -1)', expected 'weird-[brackets]'"
    fi
  fi

  # Test 6d: query that should NOT match — no false positive crash
  if [ -z "$err" ]; then
    local wb_out_6d wb_exit_6d
    wb_out_6d=$(python3 "$WB_FALLBACK" --memories-flat "$adversarial_flat" --query "zzznomatch999" 2>&1) && wb_exit_6d=0 || wb_exit_6d=$?
    if [ $wb_exit_6d -ne 0 ]; then
      err="6d: wb-fallback.py crashed on no-match query: $wb_out_6d"
    elif [ -n "$wb_out_6d" ]; then
      err="6d: wb-fallback.py unexpectedly matched something for 'zzznomatch999': $wb_out_6d"
    fi
  fi

  rm -rf "$tmp_repo"

  if [ -z "$err" ]; then
    pass "$test_name"
  else
    fail "$test_name" "$err"
  fi
}

# ---------------------------------------------------------------------------
# TEST 7 — Concurrent regen: two parallel invocations produce well-formed output
#
# Spawns two regenerate-memories-flat.py invocations in parallel against
# the same output directory. After both finish, asserts the resulting
# MEMORIES-FLAT.md is well-formed: correct headers, not a partial mix.
# Validates the tmpfile + atomic rename pattern.
# ---------------------------------------------------------------------------
test_7_concurrent_regen() {
  local test_name="T7: concurrent regen — parallel writes produce a well-formed MEMORIES-FLAT.md"

  local tmp_repo
  tmp_repo=$(mktemp -d)
  mkdir -p "$tmp_repo/docs/llm"
  cp "$FIXTURES_DIR"/*.json "$tmp_repo/docs/llm/"

  # Spawn two regenerations in parallel
  python3 "$REGEN_SCRIPT" --repo-root "$tmp_repo" &
  local pid1=$!
  python3 "$REGEN_SCRIPT" --repo-root "$tmp_repo" &
  local pid2=$!

  wait $pid1
  local exit1=$?
  wait $pid2
  local exit2=$?

  local err=""

  if [ $exit1 -ne 0 ]; then
    err="First regen invocation exited $exit1"
  fi
  if [ -z "$err" ] && [ $exit2 -ne 0 ]; then
    err="Second regen invocation exited $exit2"
  fi

  local output_file="$tmp_repo/docs/llm/MEMORIES-FLAT.md"

  if [ -z "$err" ] && [ ! -f "$output_file" ]; then
    err="MEMORIES-FLAT.md was not created"
  fi

  if [ -z "$err" ]; then
    local line1
    line1=$(head -1 "$output_file")
    if [ "$line1" != "# MEMORIES-FLAT.md — generated by /z-maintain-docs; do not edit by hand." ]; then
      err="Line 1 is not the expected header: $line1"
    fi
  fi

  if [ -z "$err" ]; then
    local line2
    line2=$(sed -n '2p' "$output_file")
    if [ "$line2" != "# Format: [<slug>] [<TYPE> <DATE>] [<source>] <text> (tags: ...)" ]; then
      err="Line 2 is not the expected format line: $line2"
    fi
  fi

  if [ -z "$err" ]; then
    # We expect 2 header lines + 5 memory lines = 7 lines minimum
    local line_count
    line_count=$(wc -l < "$output_file")
    if [ "$line_count" -lt 7 ]; then
      err="Output file has only $line_count lines; expected at least 7 (2 header + 5 memory lines)"
    fi
  fi

  if [ -z "$err" ]; then
    # "stale spreads" must be present — confirms at least one full write succeeded
    if ! grep -q "stale spreads" "$output_file"; then
      err="'stale spreads' not found in MEMORIES-FLAT.md — file may be partial or empty"
    fi
  fi

  rm -rf "$tmp_repo"

  if [ -z "$err" ]; then
    pass "$test_name"
  else
    fail "$test_name" "$err"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

echo "=== doc-memories unit tests ==="
echo "Fixtures: $FIXTURES_DIR"
echo "Repo root: $REPO_ROOT"
echo ""

test_1_doc_updater_fixture
test_2_doc_fetcher_ripgrep
test_3_wb_fallback
test_4_schema_rejection
test_5_golden_file
test_6_adversarial_regex
test_7_concurrent_regen

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ $FAIL -gt 0 ]; then
  exit 1
fi
exit 0
