---
description: Dismiss a follow-up entry from any state (terminal transition). Requires a reason.
argument-hint: "<entry-id> --reason='<text>'"
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-followup-dismiss`**. Transitions a follow-up entry from any state to `dismissed` (terminal). A reason is mandatory.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Nest guard

Before doing anything else, check the caller-depth env var:

```bash
if [[ "${Z_HARNESS_FOLLOWUP_CALLER_DEPTH:-0}" -ge 1 ]]; then
  echo "Error: /z-followup-dismiss cannot be invoked from within a running follow-up command." >&2
  echo "       (Z_HARNESS_FOLLOWUP_CALLER_DEPTH=${Z_HARNESS_FOLLOWUP_CALLER_DEPTH})" >&2
  exit 1
fi
```

## Phase 0 — Parse arguments

Parse `$ARGUMENTS`:

- Positional `<entry-id>` — required. The follow-up entry ID to dismiss.
- `--reason='<text>'` — required. Non-empty free-text reason for dismissal.

If `<entry-id>` is missing:

```
Error: entry-id is required.
Usage: /z-followup-dismiss <entry-id> --reason='<text>'
```

If `--reason` is missing or empty:

```
Error: --reason='<text>' is required and must be non-empty.
Usage: /z-followup-dismiss <entry-id> --reason='<text>'
```

If an unrecognized flag is present:

```
Error: unknown flag '<flag>'.
Usage: /z-followup-dismiss <entry-id> --reason='<text>'
```

Store: `ENTRY_ID`, `DISMISS_REASON`.

## Phase 1 — Resolve sink paths

```bash
PROJECT_SINK="$PWD/z-harness/followups"
PROJECT_VIEW="$PROJECT_SINK/index.view.json"

GLOBAL_SINK="${HOME}/.z-harness/followups"
GLOBAL_VIEW="$GLOBAL_SINK/index.view.json"
```

## Phase 2 — Locate the entry

Find which sink the entry lives in by searching both materialized views:

```bash
LOCATE_RESULT="$(python3 "$CLAUDE_PLUGIN_ROOT/scripts/followup-view-lookup.py" \
  --mode=find \
  --id="$ENTRY_ID" \
  --project-view="$PROJECT_VIEW" \
  --global-view="$GLOBAL_VIEW")"
```

The result is stored in `LOCATE_RESULT`. If `found == false`:

```
Error: entry '<entry-id>' not found in project or global sink.
```

Exit 1.

Extract `ENTRY_STATUS` and `ENTRY_SINK` from the result.

## Phase 3 — Guard: already dismissed

If `ENTRY_STATUS == dismissed`:

```
Entry '<entry-id>' is already dismissed. No action taken.
```

Exit 0.

## Phase 4 — Resolve sink root

```bash
if [[ "$ENTRY_SINK" == "project" ]]; then
  SINK_ROOT="$PWD/z-harness/followups"
else
  SINK_ROOT="${HOME}/.z-harness/followups"
fi
```

## Phase 5 — Apply the dismissal

Invoke the status-set primitive. The `dismissed` state is reachable from any non-terminal state per SPEC §State machine:

```bash
bash "${PWD}/scripts/sink-status-set.sh" \
  --entry="$ENTRY_ID" \
  --to=dismissed \
  --by=user-dismiss \
  --reason="$DISMISS_REASON" \
  --sink-root="$SINK_ROOT"
```

On non-zero exit, print the error output and exit with the same code.

## Phase 6 — Log and report

Log the event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
  "${Z_HARNESS_RUN:-followup-dismiss}" \
  followup_status_changed \
  "$(python3 -c "
import json, sys
payload = {
    'entry_id': sys.argv[1],
    'from': sys.argv[2],
    'to': 'dismissed',
    'by': 'user-dismiss',
    'reason': sys.argv[3],
}
print(json.dumps(payload))
" "$ENTRY_ID" "$ENTRY_STATUS" "$DISMISS_REASON")"
```

Print:

```
Entry '<entry-id>' dismissed.
  Previous status: <entry-status>
  Reason: <dismiss-reason>
```

---

## Invariants

- `dismissed` is a **terminal** state — no further transitions are valid after this command.
- `--reason` is mandatory and non-empty; the command refuses to proceed without it.
- This command may dismiss an entry in **any** non-terminal state (open, running, verify, failed, blocked).
- Entries already in `dismissed` state produce a no-op success (idempotent from user's perspective).
- Nest guard fires before any other logic.
- `log-event.sh` is called only on successful transition.

## Reference

- SPEC §commands/z-followup-dismiss.md → `z-harness/notion-followup-sink/SPEC.md`
- SPEC §State machine → `z-harness/notion-followup-sink/SPEC.md` §State machine (any → dismissed)

---

## Runtime contract conformance

| Feature        | Used | Gates |
|----------------|------|-------|
| `subagent`     | no   | —     |
| `ask_user`     | no   | —     |
| `skill_invoke` | no   | —     |

Driver support requirements: see frontmatter `driver_features_required`.
