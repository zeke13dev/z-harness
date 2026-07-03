#!/usr/bin/env bats
# tests/test_emit_hermes_marker.bats
#
# Tests for scripts/emit-hermes-marker.sh:
#   (a) No-op + exit 0 when HERMES_MARKER_FILE is unset — file not created, nothing written.
#   (b) When HERMES_MARKER_FILE is set, appends a schema-valid JSON line:
#       v==1 (int), valid kind string, task string, payload dict; round-trips via json.loads.
#   (c) Unknown kind → no-op (file not created, nothing written).
#
# Usage: bats tests/test_emit_hermes_marker.bats

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/emit-hermes-marker.sh"

setup() {
  TMPDIR_TEST="$(mktemp -d)"
  MARKER_FILE="$TMPDIR_TEST/markers.jsonl"
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

# ---------------------------------------------------------------------------
# (a) No-op: HERMES_MARKER_FILE unset — file must not be created
# ---------------------------------------------------------------------------
@test "(a) no-op exit 0 when HERMES_MARKER_FILE unset" {
  run bash -c "
    unset HERMES_MARKER_FILE
    bash '$SCRIPT' status myrun '{\"phase\":\"test\"}' 2>/dev/null
    echo \"exit:\$?\"
    echo \"exists:\$(test -f '$MARKER_FILE' && echo yes || echo no)\"
  "
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit:0"* ]]
  [[ "$output" == *"exists:no"* ]]
}

# ---------------------------------------------------------------------------
# (a) No-op: HERMES_MARKER_FILE empty string — file must not be created
# ---------------------------------------------------------------------------
@test "(a) no-op exit 0 when HERMES_MARKER_FILE empty string" {
  run bash -c "
    HERMES_MARKER_FILE='' bash '$SCRIPT' status myrun '{\"phase\":\"test\"}' 2>/dev/null
    echo \"exit:\$?\"
    echo \"exists:\$(test -f '$MARKER_FILE' && echo yes || echo no)\"
  "
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit:0"* ]]
  [[ "$output" == *"exists:no"* ]]
}

# ---------------------------------------------------------------------------
# (b) Valid line appended when HERMES_MARKER_FILE is set
# ---------------------------------------------------------------------------
@test "(b) appends schema-valid JSON line when HERMES_MARKER_FILE is set" {
  HERMES_MARKER_FILE="$MARKER_FILE" \
    bash "$SCRIPT" "status" "my-slug" '{"phase":"test_event"}' 2>/dev/null
  [ -f "$MARKER_FILE" ]

  # Validate via python3: v==1 int, kind/task/ts are strings, payload is dict
  run python3 - "$MARKER_FILE" <<'PY'
import json, sys
from pathlib import Path

data = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
assert data, "file is empty"
obj = json.loads(data)
assert obj["v"] == 1 and isinstance(obj["v"], int), f"v must be int 1, got {obj['v']!r}"
assert isinstance(obj["ts"], str) and len(obj["ts"]) > 0, "ts must be non-empty str"
assert obj["kind"] == "status", f"kind mismatch: {obj['kind']!r}"
assert obj["task"] == "my-slug", f"task mismatch: {obj['task']!r}"
assert isinstance(obj["payload"], dict), "payload must be dict"
assert obj["payload"].get("phase") == "test_event", f"payload phase mismatch: {obj['payload']}"
print("ok")
PY
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

# ---------------------------------------------------------------------------
# (b) All valid kinds are accepted
# ---------------------------------------------------------------------------
@test "(b) all valid kinds produce output" {
  MARKER="$TMPDIR_TEST/kinds.jsonl"
  for kind in status heartbeat needs_input handoff_continue handoff_decision handoff_fanout done; do
    HERMES_MARKER_FILE="$MARKER" \
      bash "$SCRIPT" "$kind" "slug" '{}' 2>/dev/null
  done

  LINE_COUNT="$(wc -l < "$MARKER" | tr -d ' ')"
  [ "$LINE_COUNT" -eq 7 ]

  # Every line must be valid JSON with the expected kind
  run python3 - "$MARKER" <<'PY'
import json, sys
from pathlib import Path

lines = [l.strip() for l in Path(sys.argv[1]).read_text().splitlines() if l.strip()]
valid_kinds = {"status","heartbeat","needs_input","handoff_continue","handoff_decision","handoff_fanout","done"}
for line in lines:
    obj = json.loads(line)
    assert obj["v"] == 1 and isinstance(obj["v"], int)
    assert obj["kind"] in valid_kinds
    assert isinstance(obj["payload"], dict)
print("ok")
PY
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

# ---------------------------------------------------------------------------
# (b) handoff_fanout kind with payload
# ---------------------------------------------------------------------------
@test "(b) handoff_fanout marker round-trips via json.loads" {
  HERMES_MARKER_FILE="$MARKER_FILE" \
    bash "$SCRIPT" "handoff_fanout" "split-session-fanout" '{"slug":"split-session-fanout","workstreams_path":"z-harness/split-session-fanout/workstreams.json","handoff_paths":["z-harness/split-session-fanout/HANDOFF.md"],"shared_concerns_path":"z-harness/split-session-fanout/SHARED-CONCERNS.md","ack_required":true,"partial_tree":false}' 2>/dev/null

  run python3 - "$MARKER_FILE" <<'PY'
import json, sys
from pathlib import Path
obj = json.loads(Path(sys.argv[1]).read_text().strip())
assert obj["v"] == 1
assert obj["kind"] == "handoff_fanout"
assert obj["task"] == "split-session-fanout"
payload = obj["payload"]
assert payload["slug"] == "split-session-fanout"
assert payload["workstreams_path"].endswith("workstreams.json")
assert payload["handoff_paths"] == ["z-harness/split-session-fanout/HANDOFF.md"]
assert payload["ack_required"] is True
assert payload["partial_tree"] is False
print("ok")
PY
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

@test "(b) malformed handoff_fanout payload falls back to empty dict" {
  HERMES_MARKER_FILE="$MARKER_FILE" \
    bash "$SCRIPT" "handoff_fanout" "split-session-fanout" '{not-json' 2>/dev/null

  run python3 - "$MARKER_FILE" <<'PY'
import json, sys
from pathlib import Path
obj = json.loads(Path(sys.argv[1]).read_text().strip())
assert obj["kind"] == "handoff_fanout"
assert obj["payload"] == {}
print("ok")
PY
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

# ---------------------------------------------------------------------------
# (b) heartbeat kind with payload
# ---------------------------------------------------------------------------
@test "(b) heartbeat marker round-trips via json.loads" {
  HERMES_MARKER_FILE="$MARKER_FILE" \
    bash "$SCRIPT" "heartbeat" "run-id-123" '{"note":"context_pressure"}' 2>/dev/null

  run python3 - "$MARKER_FILE" <<'PY'
import json, sys
from pathlib import Path
obj = json.loads(Path(sys.argv[1]).read_text().strip())
assert obj["v"] == 1
assert obj["kind"] == "heartbeat"
assert obj["task"] == "run-id-123"
assert obj["payload"]["note"] == "context_pressure"
print("ok")
PY
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

# ---------------------------------------------------------------------------
# (c) Unknown kind → no-op, file not created
# ---------------------------------------------------------------------------
@test "(c) unknown kind produces no output and exits 0" {
  run bash -c "
    HERMES_MARKER_FILE='$MARKER_FILE' \
      bash '$SCRIPT' bogus_kind myrun '{}' 2>/dev/null
    echo \"exit:\$?\"
    echo \"exists:\$(test -f '$MARKER_FILE' && echo yes || echo no)\"
  "
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit:0"* ]]
  [[ "$output" == *"exists:no"* ]]
}

# ---------------------------------------------------------------------------
# (c) Another unknown kind variant
# ---------------------------------------------------------------------------
@test "(c) 'compaction_pause' is not a valid kind — no-op" {
  run bash -c "
    HERMES_MARKER_FILE='$MARKER_FILE' \
      bash '$SCRIPT' compaction_pause myrun '{}' 2>/dev/null
    echo \"exit:\$?\"
    echo \"exists:\$(test -f '$MARKER_FILE' && echo yes || echo no)\"
  "
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit:0"* ]]
  [[ "$output" == *"exists:no"* ]]
}

# ---------------------------------------------------------------------------
# (b) Append multiple markers — order preserved, all valid
# ---------------------------------------------------------------------------
@test "(b) multiple appends produce valid sequential lines" {
  HERMES_MARKER_FILE="$MARKER_FILE" \
    bash "$SCRIPT" "status" "slug" '{"phase":"first"}' 2>/dev/null
  HERMES_MARKER_FILE="$MARKER_FILE" \
    bash "$SCRIPT" "done" "slug" '{"summary":"finished"}' 2>/dev/null

  run python3 - "$MARKER_FILE" <<'PY'
import json, sys
from pathlib import Path

lines = [l.strip() for l in Path(sys.argv[1]).read_text().splitlines() if l.strip()]
assert len(lines) == 2, f"expected 2 lines, got {len(lines)}"
first = json.loads(lines[0])
assert first["kind"] == "status"
assert first["payload"]["phase"] == "first"
second = json.loads(lines[1])
assert second["kind"] == "done"
assert second["payload"]["summary"] == "finished"
print("ok")
PY
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

# ---------------------------------------------------------------------------
# (d) --strict happy path: writes a valid line and exits 0
# ---------------------------------------------------------------------------
@test "(d) --strict happy path appends a valid line and exits 0" {
  run bash -c "
    HERMES_MARKER_FILE='$MARKER_FILE' \
      bash '$SCRIPT' --strict handoff_continue my-slug '{\"handoff_text\":\"resume x\"}'
    echo \"exit:\$?\"
  "
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit:0"* ]]
  run python3 - "$MARKER_FILE" <<'PY'
import json, sys
from pathlib import Path
obj = json.loads(Path(sys.argv[1]).read_text().strip())
assert obj["kind"] == "handoff_continue"
assert obj["payload"]["handoff_text"] == "resume x"
print("ok")
PY
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

# ---------------------------------------------------------------------------
# (d) --strict with HERMES_MARKER_FILE unset stays a non-Hermes no-op (exit 0)
# ---------------------------------------------------------------------------
@test "(d) --strict no-op exit 0 when HERMES_MARKER_FILE unset" {
  run bash -c "
    unset HERMES_MARKER_FILE
    bash '$SCRIPT' --strict handoff_continue my-slug '{}'
    echo \"exit:\$?\"
  "
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit:0"* ]]
}

# ---------------------------------------------------------------------------
# (d) --strict returns non-zero on a genuine append failure (unwritable path).
#     A regular file blocks parent-dir creation, so mkdir -p + append both fail.
# ---------------------------------------------------------------------------
@test "(d) --strict fails loud (exit 1) when the marker path is unwritable" {
  BLOCKER="$TMPDIR_TEST/blocker"
  : > "$BLOCKER"                        # regular file, not a directory
  BAD_MARKER="$BLOCKER/sub/markers.jsonl"
  run bash -c "
    HERMES_MARKER_FILE='$BAD_MARKER' \
      bash '$SCRIPT' --strict handoff_continue my-slug '{}'
    echo \"exit:\$?\"
  "
  [[ "$output" == *"exit:1"* ]]
  [[ "$output" == *"append to HERMES_MARKER_FILE failed"* ]]
}

# ---------------------------------------------------------------------------
# (d) --strict returns non-zero on an invalid kind (cannot be emitted)
# ---------------------------------------------------------------------------
@test "(d) --strict fails loud (exit 1) on invalid kind" {
  run bash -c "
    HERMES_MARKER_FILE='$MARKER_FILE' \
      bash '$SCRIPT' --strict bogus_kind my-slug '{}'
    echo \"exit:\$?\"
  "
  [[ "$output" == *"exit:1"* ]]
  [[ "$output" == *"invalid kind"* ]]
}

# ---------------------------------------------------------------------------
# (d) Regression: WITHOUT --strict, the same unwritable path stays best-effort
#     (exit 0). Guards that the default contract is byte-identical to before.
# ---------------------------------------------------------------------------
@test "(d) non-strict stays best-effort exit 0 on an unwritable marker path" {
  BLOCKER="$TMPDIR_TEST/blocker2"
  : > "$BLOCKER"
  BAD_MARKER="$BLOCKER/sub/markers.jsonl"
  run bash -c "
    HERMES_MARKER_FILE='$BAD_MARKER' \
      bash '$SCRIPT' handoff_continue my-slug '{}' 2>/dev/null
    echo \"exit:\$?\"
  "
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit:0"* ]]
}
