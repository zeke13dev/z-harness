---
name: z-axiom-reject
disable-model-invocation: false
description: Reject a candidate or approved axiom, moving it to the rejected/ tombstone store. Optionally records a rejection reason.
argument-hint: <id> [--reason <text>] [--scope <global|project>] [--repo-root <path>]
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-axiom-reject`**. Thin command that maps `<id>` to `axiom-store.py reject`. Rejected records are moved to `rejected/<id>.json` as a tombstone (kept for de-dup and audit). If the rejected record was `approved`, the kernel is regenerated.

## Phase 0 — Parse arguments

Parse `$ARGUMENTS`:

- Positional `<id>` — the axiom id to reject (e.g. `ax-1a2b3c4d`). Required.
- `--reason <text>` — optional rejection reason (free text). Passed through to `axiom-store.py reject`.
- `--scope <global|project>` — store scope. Optional; omit to let the store search both.
- `--repo-root <path>` — override repo root. Optional.

If `<id>` is not provided, print usage and exit:

```
Usage: /z-axiom-reject <id> [--reason <text>] [--scope <global|project>] [--repo-root <path>]
```

## Phase 1 — Run axiom-store.py reject

```bash
RESULT="$(python3 scripts/axiom-store.py reject "$ID" \
  ${SCOPE:+--scope "$SCOPE"} \
  ${REASON:+--reason "$REASON"} \
  ${REPO_ROOT:+--repo-root "$REPO_ROOT"})"
EXIT_CODE=$?
```

## Phase 2 — Interpret the result

| Status JSON | Meaning | Action |
|---|---|---|
| `{"status": "ok", "id": "...", "path": "..."}` | Rejected; record moved to `rejected/` | Print confirmation |
| `{"status": "not_found", "id": "..."}` | No record with this id in candidate or approved | Print "not found" and exit |
| `{"status": "rejected_kernel_stale", ...}` | Rejected (was approved); kernel regen failed | Warn; kernel is stale |

On `STATUS: ok`:
```
Rejected: <id>
  Tombstone: <path>
  Reason: <reason | (none)>

The record is tombstoned in rejected/ for de-dup and audit.
To view remaining candidates: /z-axiom-list --status candidate
```

On `STATUS: not_found`:
```
Axiom <id> not found in candidate or approved store.
Use /z-axiom-list to see available axioms.
```

On `STATUS: rejected_kernel_stale`:
```
Rejected: <id>
  Tombstone: <path>
  WARNING: kernel regen failed — kernel is stale.
  The record was moved to rejected/, but the kernel was not updated.
  Run: python3 scripts/build-kernel.py --scope <scope>  to rebuild manually.
  Check events.jsonl for kernel_regen_failed event.
```

On unexpected exit or output, surface the raw output and exit non-zero.

## STATUS lines from axiom-store.py reject

| Status JSON | Meaning |
|---|---|
| `{"status": "ok", "id": "ax-...", "path": "..."}` | Record moved to `rejected/<id>.json` |
| `{"status": "not_found", "id": "ax-..."}` | No matching record found |
| `{"status": "rejected_kernel_stale", ...}` | Record moved to `rejected/` but kernel regen failed |

## Hard rules

- **Tombstoning is permanent within a session.** Rejected records are kept as tombstones and cannot be re-added under the same id (dedup will flag them as duplicate).
- **No confirmation prompt.** Rejection is reversible (the user can re-add a candidate from scratch), so no AskUserQuestion is required.
- **Kernel regen on approved record rejection is handled by `axiom-store.py reject` internally.** The command does not need to invoke the kernel compiler directly.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | no | — |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
