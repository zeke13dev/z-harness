---
name: z-axiom-scan
description: Mine candidate axioms from z-harness interaction history by dispatching the axiom-extractor agent, then writing returned candidates to the axiom store. Proposes only — never auto-approves.
argument-hint: [--historical] [--scope <global|project>] [--run <run-id>] [--repo-root <path>]
---

You are running **z-harness `/z-axiom-scan`**. Mine candidate axioms by dispatching the `axiom-extractor` agent, collecting the returned fenced JSON array, and writing each candidate to the axiom store via `axiom-store.py add`. This command **proposes only** — it never approves any candidate. Approval is always a separate explicit user step via `/z-axiom-approve`.

## Phase 0 — Parse arguments

Parse `$ARGUMENTS`:

- `--historical` — full `metrics.jsonl` scan. **Warn the user before dispatching:** "Warning: --historical performs a full metrics.jsonl scan and is CPU/token-heavy. Proceeding." Never invoke this mode silently.
- `--scope <global|project>` — store scope for `axiom-store.py add`. Default: `global`.
- `--run <run-id>` — incremental mode: mine only events from this run. Mutually exclusive with `--historical`. If neither `--run` nor `--historical` is provided, default to the most recent run id found in `z-harness/metrics.jsonl` (last `.run` value), else use `--historical` if no run id can be determined.
- `--repo-root <path>` — override the repo root passed to scripts. Default: `$(git rev-parse --show-toplevel)`.

Determine `mode`:
- `--historical` present → `mode: historical`
- `--run <id>` present → `mode: post-run <id>`
- neither present → attempt to read the last run id from metrics.jsonl:
  ```bash
  LAST_RUN="$(jq -r '.run // empty' "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir)/metrics.jsonl" 2>/dev/null | tail -1)"
  ```
  If `$LAST_RUN` is non-empty → `mode: post-run $LAST_RUN`. Otherwise → `mode: historical` (fallback, with the expensive-scan warning).

Resolve `REPO_ROOT`:
```bash
REPO_ROOT="${repo_root_arg:-$(git rev-parse --show-toplevel)}"
SCOPE="${scope_arg:-global}"
```

## Phase 1 — Dispatch axiom-extractor agent

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. Skipping means no candidates are mined this run — warn the user. -->

Dispatch the `axiom-extractor` agent:

```
Agent(
  subagent_type="axiom-extractor",
  description="Axiom mining — <mode>",
  prompt="repo_root: <REPO_ROOT>\nmode: <mode>"
)
```

Where `<mode>` is one of:
- `post-run <run-id>` (incremental)
- `historical` (full scan)

## Phase 2 — Parse the returned candidates

The agent returns one fenced ```json block containing a JSON array (≤5 candidates or empty `[]`).

Extract it:
```python
import re, json
raw = agent_return_text
m = re.search(r'```json\s*([\s\S]*?)```', raw)
if not m:
    # No fenced block — agent may have errored or found nothing
    print("axiom-extractor returned no fenced JSON block.")
    print("Possible reasons: no decision events reached the recurrence threshold, or agent error.")
    exit 0
try:
    candidates = json.loads(m.group(1))
except json.JSONDecodeError as e:
    print(f"axiom-extractor returned a malformed JSON block: {e}")
    exit 0
```

If `candidates` is an empty array (`[]`):
- Print: "No axiom candidates found above the recurrence threshold for this run."
- Exit cleanly (no error).

## Phase 3 — Store-aware dedup and add

For each candidate in the array (index `i`, 0-based):

1. **Assign a prospective id** for dedup check. The store assigns the final id on add, but we can pre-check by running validate on the candidate:
   ```bash
   CANDIDATE_JSON="<json string for this candidate>"
   ```

2. **Write to a temp file and call `axiom-store.py add`:**
   ```bash
   TMPFILE="$(mktemp --suffix=.json)"
   printf '%s\n' "$CANDIDATE_JSON" > "$TMPFILE"
   RESULT="$(python3 scripts/axiom-store.py add \
     --scope "$SCOPE" \
     --from-json "$TMPFILE" \
     ${REPO_ROOT:+--repo-root "$REPO_ROOT"})"
   rm -f "$TMPFILE"
   ```

3. **Interpret the result:**
   - `{"status": "ok", "id": "ax-...", "path": "..."}` → candidate written. Record `id` and mark as `added`.
   - `{"status": "duplicate", "id": "ax-..."}` → a candidate with the same id already exists (approved, candidate, or rejected). Skip silently, mark as `skipped_duplicate`.
   - Any other non-zero exit or unexpected output → mark as `error`, surface the output.

Accumulate counts: `added`, `skipped_duplicate`, `errors`.

## Phase 4 — Print summary

Print a summary table:

```
/z-axiom-scan complete
Mode: <post-run <run-id> | historical>
Scope: <global|project>

Candidates processed: <total>
  Added to store:     <added>
  Skipped (dup):      <skipped_duplicate>
  Errors:             <errors>

Next steps:
  /z-axiom-list --status candidate   — review pending candidates
  /z-axiom-approve <id>              — approve a candidate (regens kernel)
  /z-axiom-reject <id>               — reject a candidate
```

If any errors occurred, show the raw output for each errored candidate below the table.

## STATUS lines from axiom-store.py add

| Status JSON | Meaning |
|---|---|
| `{"status": "ok", "id": "ax-...", "path": "..."}` | Candidate written to `candidates/<id>.json` |
| `{"status": "duplicate", "id": "ax-..."}` | Same id already exists (any status); skipped |

## Hard rules

- **Proposes only.** This command never approves any candidate. It only writes to `candidates/`. Approval is always an explicit user step via `/z-axiom-approve`.
- **`--historical` always warns.** Never invoke the full-history scan silently — warn the user it is token/CPU-expensive before dispatching the agent.
- **Store dedup is command-layer responsibility.** The extractor does not have store access; this command skips ids that already exist.
- **Never auto-approve.** Not even if all candidates are high-confidence. The approval invariant is absolute.
