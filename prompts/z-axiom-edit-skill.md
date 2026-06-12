# /z-axiom-edit

You are running **z-harness `/z-axiom-edit`**. Thin command that maps `<id> --set <field>=<value>` to `axiom-store.py edit`. On approved records, the store re-validates the graph and regenerates the kernel automatically.

## Phase 0 — Parse arguments

Parse `$ARGUMENTS`:

- Positional `<id>` — the axiom id to edit (e.g. `ax-1a2b3c4d`). Required.
- `--set <field>=<value>` — one or more field patches. Repeatable. Required (at least one).
  - `<field>` must be a recognized axiom schema field (e.g. `statement`, `confidence`, `boundary_conditions`, `counterexamples`, `discipline`, `applies_to`, `conflicts_with`, `supersedes`, `review_after`).
  - `<value>` is treated as a JSON value if it parses as one; otherwise as a string.
- `--scope <global|project>` — store scope. Optional.
- `--repo-root <path>` — override repo root. Optional.

If `<id>` is not provided or no `--set` is given, print usage and exit:

```
Usage: /z-axiom-edit <id> --set <field>=<value> [--set <field>=<value> ...] [--scope <global|project>] [--repo-root <path>]

Example:
  /z-axiom-edit ax-1a2b3c4d --set boundary_conditions='["does not apply to modifier flags"]'
  /z-axiom-edit ax-1a2b3c4d --set confidence=0.90 --set discipline=engineering
```

Editable fields and their types:
| Field | Type | Notes |
|---|---|---|
| `statement` | string | ≤200 chars, imperative voice, single sentence |
| `confidence` | float 0..1 | Extractor-assigned; user-editable |
| `discipline` | string | Optional free-tag |
| `applies_to` | JSON array | Array of `"<question_id>:<value>"` strings |
| `boundary_conditions` | JSON array | Conditions where the rule does NOT apply |
| `counterexamples` | JSON array | Cases explicitly allowed despite the rule |
| `conflicts_with` | JSON array | Array of axiom ids |
| `supersedes` | string or null | Axiom id this replaces |
| `review_after` | string | Date `YYYY-MM-DD` |

Fields NOT editable via this command: `id`, `status`, `scope`, `evidence`, `source_run`, `created_at`, `approved_at`. Use `/z-axiom-approve` or `/z-axiom-reject` to change status.

## Phase 1 — Run axiom-store.py edit

Build the command from `--set` pairs:

```bash
CMD="python3 scripts/axiom-store.py edit $ID"
for SET_PAIR in "${SET_ARGS[@]}"; do
  CMD="$CMD --set $(printf '%q' "$SET_PAIR")"
done
[[ -n "$SCOPE_ARG" ]]     && CMD="$CMD --scope $SCOPE_ARG"
[[ -n "$REPO_ROOT_ARG" ]] && CMD="$CMD --repo-root $REPO_ROOT_ARG"

RESULT="$(eval "$CMD")"
EXIT_CODE=$?
```

## Phase 2 — Interpret the result

`axiom-store.py edit` performs an atomic rewrite of the record. For approved records it re-runs graph validation then regenerates the kernel. The possible output shapes are:

| Status JSON | Meaning | Action |
|---|---|---|
| `{"status": "ok", "id": "...", "path": "..."}` | Record patched (and kernel regenerated if approved) | Print confirmation |
| `{"status": "not_found", "id": "..."}` | No record with this id | Print "not found" and exit |
| `{"status": "edited_kernel_stale", ...}` | Record patched but kernel regen failed | Warn; kernel is stale |
| `{"status": "graph_validation_failed", ...}` | Graph validation failed on the patched record | Print errors; no write occurred |
| `{"status": "invalid", ...}` | Patched record fails schema validation | Print errors; no write occurred |

On `STATUS: ok`:
```
Edited: <id>
  Path: <path>
  Fields updated: <list of --set field names>
  Kernel: <regenerated if approved | unchanged if candidate>
```

On `STATUS: not_found`:
```
Axiom <id> not found.
Use /z-axiom-list to see available axioms.
```

On `STATUS: edited_kernel_stale`:
```
Edited: <id>
  WARNING: kernel regen failed — kernel is stale.
  Run: python3 scripts/build-kernel.py --scope <scope>  to rebuild manually.
  Check events.jsonl for kernel_regen_failed event.
```

On `STATUS: graph_validation_failed`:
```
Edit blocked: graph validation failed after the proposed patch.
Errors:
  <errors from result>

The record was NOT modified. Correct the conflicts and retry.
```

On `STATUS: invalid`:
```
Edit blocked: patched record fails schema validation.
Errors:
  <errors from result>

The record was NOT modified. Correct the --set values and retry.
```

On unexpected exit or output, surface the raw output and exit non-zero.

## STATUS lines from axiom-store.py edit

| Status JSON | Meaning |
|---|---|
| `{"status": "ok", "id": "ax-...", "path": "..."}` | Record patched atomically |
| `{"status": "not_found", "id": "ax-..."}` | No matching record found |
| `{"status": "invalid", ...}` | Schema validation failed; record unchanged |
| `{"status": "edited_kernel_stale", ...}` | Patched but kernel regen failed |
| `{"status": "graph_validation_failed", ...}` | Graph invalid after patch; record unchanged |

## Hard rules

- **Atomic patch only.** `axiom-store.py edit` uses tmp + `os.replace` internally; the command never writes the store directly.
- **Status transitions are forbidden here.** Use `/z-axiom-approve` or `/z-axiom-reject` for status changes.
- **Graph re-validation on approved records is automatic.** The store runs graph validation before applying the patch to an approved record; a `graph_validation_failed` result means no write occurred.
- **Kernel regen on approved record edit is synchronous.** The store invokes `build-kernel.py` after patching an approved record; `edited_kernel_stale` means the patch landed but the kernel needs manual rebuild.
