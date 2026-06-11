---
description: "Implement the next pending task from z-harness/TASKS.md, then have Codex scrutinize the diff."
role: workflow
---

You are running the **z-harness `/z-implement-next`** pipeline.

Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).

## Phase 0 — Lock check + Discover plan slug

### Phase 0.0 — Active-plan registration + cross-session overlap scan

Register this run in the shared active-plan registry, seed its file scope, and surface overlap
with any concurrent session. This is advisory by design (registry invariant 1: lockless is safe
ONLY because overlap is advisory) except under `Z_HARNESS_STRICT_OVERLAP`, which adds a single
hard gate. This command never mutates the base or migrates anything (registry invariant 8); it
only register/heartbeat/deregisters its own record (single-writer, invariant 6).

**ORDERING (mandatory).** This phase needs `$BASE` bound (Phase 0.2 slug discovery) and must not
create a record before any structural-validation halt. Therefore run this phase **after Phase 0.2
(slug discovery, which exports `$Z_HARNESS_SLUG` and sets `$BASE`) and BEFORE Phase 0.1
(follow-up lock check)** — so that if Phase 0.1 halts, a record already exists and can be
deregistered. Phase 0.2 must run first even though it appears later in this document; the
execution order is 0.2 → 0.0 → 0.1, mirroring z-implement-all where Setup slug-discovery
runs before Phase 0.0 registration.

**Bind the run id and session id (the two values this phase introduces).** `$Z_HARNESS_SLUG`
and `$BASE` are already bound by Phase 0.2 above; only `RUN` and the session id are
established here:

```bash
# Run id — canonical variable for this command. Every register / heartbeat / overlaps /
# deregister call in this file uses $RUN (never any other variable).
RUN="$(date -u +%Y%m%dT%H%M%SZ)-implement-next"

# Session id (same value Phase 1 stamps onto task_start).
export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"

# Sanity-guard: $BASE must be a real path here. If $BASE is unset, Phase 0.2 did not run yet
# — STOP; this phase is mis-ordered.
: "${BASE:?Phase 0.0 ran before Phase 0.2 bound \$BASE — fix ordering}"
```

**1. Register the run.** Graduated failure policy (registry SPEC): a silent register failure
defeats the whole mechanism, so NEVER silent-continue. Spell out every exit code:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
  --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-implement-next --phase implement \
  --session "$Z_HARNESS_SESSION_ID"
REG_RC=$?
```

- `REG_RC == 0` → registered; a record now exists; run **Run Brief init** (step 1a), then proceed to step 2.
- `REG_RC == 3` (register FAILED — no record was written) → emit a loud `registry_error` event
  (the register subcommand does NOT self-log its own failure; it returns 3 loudly, so the
  orchestrator logs it here), then branch:
  - **Interactive** (not `Z_HARNESS_NO_ASK`) → `AskUserQuestion`: *proceed without coordination* /
    *abort*.
    - **proceed without coordination** → continue WITHOUT a record. Skip step 2 (scope seed) and
      step 3 (overlap scan) entirely — there is no record to scope or scan against — and fall
      through to Phase 1. (No heartbeat/deregister later either; there is nothing to update.)
    - **abort** → because register FAILED there is **NO record**, so do **NOT** call deregister
      (deregistering a nonexistent record is a no-op at best and misleading at worst). Just
      push-notify and `exit 1`.
  - **Unattended (`Z_HARNESS_NO_ASK`)** → proceed without coordination (as the interactive
    *proceed* branch above) and log prominently, UNLESS `Z_HARNESS_STRICT_OVERLAP=1`, in which
    case **halt**: push-notify (this is the only register-failure hard stop) and `exit 1`. Again,
    do **NOT** deregister — register failed, so no record exists.
- **Any OTHER nonzero `REG_RC`** (not 0, not 3 — should not happen, but be defensive) → treat it
  exactly as `REG_RC == 3` (loud `registry_error`, same graduated proceed/abort policy, same
  "no record exists → no deregister" rule).

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
  "$(printf '{"op":"register","run_id":"%s","rc":%d}' "$RUN" "$REG_RC")"
```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the register-failure proceed/abort question via their native channel. Silent omission is forbidden. -->

**1a. Run Brief init (register success only — `init_after: register` per `docs/llm/run-brief-registry.json`).** Skip when register failed and the orchestrator proceeds without a record.

```bash
if [ "$REG_RC" -eq 0 ]; then
  CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
  mkdir -p "$CURRENT_ARCHIVE_DIR"
  RUN_BRIEF_INTENT="Implement next pending task in plan ${Z_HARNESS_SLUG:-$(basename "$BASE")}"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh" init \
    --run "$RUN" --command /z-implement-next \
    --slug "${Z_HARNESS_SLUG:-$(basename "$BASE")}" \
    --profile full --intent "$RUN_BRIEF_INTENT"
  export RUN_BRIEF_PROFILE=full
  export RUN_BRIEF_ARTIFACT="$TASKS_FILE"
fi
```

**2. Seed scope (best-effort, non-fatal).** Dispatch the `scope-extractor` (Haiku) subagent with
`repo_root` + `base` to produce a scope JSON array, write it to a temp file, and feed it to
`update-scope`. Failure here is non-fatal — overlap detection just runs with an empty/own-record
scope. The `update-scope` subcommand returns 0 by design and **self-logs** a `registry_error`
event (op:`update-scope`) internally on any failure, so the orchestrator calls it best-effort
with `|| true` and does NOT add a misleading `|| log` (that would be dead code, since the
subcommand returns 0 by design).

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="scope-extractor",
  description="Scope for /z-implement-next overlap scan",
  prompt="repo_root: <repo root abs path>\nbase: $BASE"
)
```

Write the returned JSON array to `"$(mktemp -t z-scope.XXXXXX.json)"`, then:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" update-scope \
  --run-id "$RUN" --scope-json "$SCOPE_JSON" || true   # CLI self-logs registry_error on failure
```

**3. Overlap scan (graduated advisory).** Add `--strict` when `Z_HARNESS_STRICT_OVERLAP=1`.

```bash
OVL_ARGS=(--run-id "$RUN")
[ "${Z_HARNESS_STRICT_OVERLAP:-}" = "1" ] && OVL_ARGS+=(--strict)
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" overlaps "${OVL_ARGS[@]}"
OVL_RC=$?
```

Handle the exit code (the registry self-emits `active_plan_scan_complete` /
`scope_overlap_detected`, so absence of overlap is observable without an extra event here).
Spell out every code:

- `OVL_RC == 0` (no overlap) → proceed silently (the registry already self-emitted
  `active_plan_scan_complete`).
- `OVL_RC == 10` (advisory overlap) → present the overlapping peers (each peer's `slug`,
  `branch`, `current_task`, `host`, and the shared paths — re-run with `--json` to render them)
  via `AskUserQuestion`: **proceed** / **wait** (re-scan after the peer finishes) / **abort**.
  Under `Z_HARNESS_NO_ASK` → proceed and log (advisory is non-blocking unattended).
  On **abort** → a record EXISTS; set `RB_HALT_REASON`, run halt-finalize, then deregister:
  ```bash
  RB_HALT_REASON="scope overlap abort"
  ```
<!-- Host sets RB_HALT_REASON, BASE, RUN before include -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/TASKS.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-implement-next","command":"/z-implement-next"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  # push-notify + exit 1
  ```
- `OVL_RC == 20` (blocking overlap — only under strict mode AND an `explicit`×`explicit` exact
  path match with a live peer) → **HALT**: a record EXISTS; push-notify (hard pause, fires
  regardless of notify level), then set `RB_HALT_REASON`, run halt-finalize, then deregister:
  ```bash
  RB_HALT_REASON="blocking scope overlap"
  ```
<!-- Host sets RB_HALT_REASON, BASE, RUN before include -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/TASKS.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-implement-next","command":"/z-implement-next"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  # exit 1 without dispatching any task
  ```
  This is the one hard gate (registry invariant 1 permits it only under strict mode).
- **Any OTHER nonzero `OVL_RC` (including `4` — overlaps could not resolve the registry)** → this
  is NOT a hard block and NOT a silent "no overlap". Log a `registry_error` event (op:`overlaps`)
  and **PROCEED** (the scan was inconclusive; overlap is advisory, so an inconclusive scan
  degrades to "ran without coordination" rather than halting):
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
    "$(printf '{"op":"overlaps","run_id":"%s","rc":%d}' "$RUN" "$OVL_RC")"
  ```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the overlap proceed/wait/abort question via their native channel. Silent omission is forbidden. -->

### FINALIZE_STATUS / deregister rule (single source of truth)

One rule governs the record's lifecycle for the entire run:

> **On any abort/halt that ENDS the run AND occurs after a record exists (i.e. after a `REG_RC == 0`
> register), run **Run Brief — halt finalize** (when `run-brief.sh init` ran), set `FINALIZE_STATUS=aborted`, and `deregister --status aborted` before exiting. On a
> normal completion (Phase 5), deregister with the default `complete`. On register failure (no
> record), do NOT deregister.**

Concretely, the run-ending halt paths that MUST set `FINALIZE_STATUS=aborted` and deregister
(each is reached only after `REG_RC == 0`, so a record exists):

- Phase 0.0 overlap abort (`OVL_RC == 10` → abort) and overlap block (`OVL_RC == 20`) — handled inline above.
- Phase 0.1 follow-up-running halt — handled inline below.
- Any other run-ending halt after registration (implementer returns `unable_to_complete` etc. and
  the orchestrator decides to stop entirely) — set `FINALIZE_STATUS=aborted` + deregister.

Paths that must NOT deregister:

- **Register-failure abort/halt (`REG_RC == 3` or other nonzero)** — no record was ever written,
  so there is nothing to deregister; just `exit 1`.

### Phase 0.1 — Global cross-tool lock check

After Phase 0.0 registers the run (or skips on register failure), check for concurrent follow-up
consumer activity in this repo:

```bash
PROJECT_SINK="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" followups_dir)/index.view.json"
if [ -f "$PROJECT_SINK" ]; then
  RUNNING_COUNT="$(python3 -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    entries_obj = data.get('entries', {})
    entries = list(entries_obj.values())
    running = [e for e in entries if e.get('status') == 'running']
    print(len(running))
except (json.JSONDecodeError, OSError, KeyError, AttributeError):
    print(0)
" "$PROJECT_SINK" 2>/dev/null || echo 0)"
  if [ "${RUNNING_COUNT:-0}" -gt 0 ]; then
    echo "halt: follow-up consumer is active ($RUNNING_COUNT running entry/entries in project sink)" >&2
    echo "Run /z-followup-status to see what is running. Wait for it to complete or dismiss before implementing." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" implement_halted_followup_running \
      "$(printf '{"running_count":%d,"sink_path":"%s"}' "$RUNNING_COUNT" "$PROJECT_SINK")" 2>/dev/null || true
    RB_HALT_REASON="follow-up consumer active"
```
<!-- Host sets RB_HALT_REASON, BASE, RUN before include -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/TASKS.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-implement-next","command":"/z-implement-next"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).
```bash
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status "$FINALIZE_STATUS" || true
    exit 1
  fi
fi
```

If there are running follow-up consumer entries, **halt** — do not proceed. Tell the user to check `/z-followup-status` before retrying.

### Phase 0.2 — Discover plan slug

Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. Determine which one to operate on:

1. Enumerate candidates:
   - List immediate subdirs of `z-harness/` that contain a `TASKS.md`.
   - Also check for legacy flat layout: a `TASKS.md` directly under `z-harness/` (no slug).
2. Choose:
   - **One candidate** → use it. If slug-namespaced, `export Z_HARNESS_SLUG=<slug>`. If legacy flat, leave `Z_HARNESS_SLUG` unset.
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug-selection question via their native channel. Silent omission is forbidden. -->
   - **Multiple candidates** → `AskUserQuestion` with each slug as an option. Set `Z_HARNESS_SLUG` to the chosen one.
   - **Zero candidates** → tell the user there's no plan; suggest `/z-plan`. Stop.
3. From here on, **`BASE`** refers to `$Z_HARNESS_PLAN_DIR` (or `z-harness` if legacy). Paths below use `$BASE`.

   **Set the default tasks file now that `BASE` is bound:**
   ```bash
   TASKS_FILE="${TASKS_FILE:-$BASE/TASKS.md}"
   ```

## Phase 1 — Load context

1. Read `$TASKS_FILE`. Find the first task with status `[ ]`. **Store the full task block text in `TASK_BLOCK`** (the verbatim lines from the `## T<id>` heading through the last line before the next heading). This variable is needed in Phase 2 to parse `COMPLEXITY_TIER` from the `**Complexity:**` stamp without re-reading TASKS.md.
2. **Do NOT pre-extract SPEC/PLAN slices in main thread.** Pass `$BASE` to the implementer; the implementer subagent reads `$BASE/SPEC.md` and `$BASE/PLAN.md` itself with its Read tool. Saves main-thread context.
3. (Skip — implementer reads the files it touches.)
4. Create task archive dir: `mkdir -p $BASE/archive/tasks/<task-id>`
5. **Version stamp + task_start:** (`Z_HARNESS_SESSION_ID` was already exported in Phase 0.0; the
   `:-` default below leaves it alone if set.)
   ```bash
   export Z_HARNESS_SESSION_ID="${Z_HARNESS_SESSION_ID:-$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)}"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["id"] = sys.argv[2]; v["session_id"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<task-id>" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start "$START_PAYLOAD"
   ```

6. **Kernel path resolution (once per invocation, immediately after task_start):**
   ```bash
   KERNEL_PATH="$(bash scripts/resolve-kernel.sh 2>/dev/null || true)"
   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

If TASKS.md is missing or has no pending tasks, tell the user and stop.

## Phase 2 — Implement

**Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.

**Heartbeat the registry at task-dispatch boundary** (best-effort, non-fatal — never block dispatch
on a registry error). The `heartbeat` subcommand returns 0 by design and **self-logs** a
`registry_error` event (op:`heartbeat`) internally on any failure, so call it with `|| true` and
do NOT add a misleading `|| log` (that would be dead code since the subcommand returns 0 by
design):

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" heartbeat \
  --run-id "$RUN" --phase implement --current-task "<task-id>" || true   # CLI self-logs registry_error on failure
```

### Phase 2.5 — Per-task lease lifecycle

After the heartbeat and before implementer dispatch, claim the task's explicit-confidence paths,
resolve any concessions via `wait-for` or an interactive menu, then dispatch the implementer.
Release the lease on clean success; on halt mid-task, rely on `deregister`/`reap` to clean up.

**Claim the task's explicit-confidence paths (conservative — explicit only, per SPEC D3).**
`CLAIM` is the `explicit`-confidence entries from the scope-extractor's task-level output
(same extractor invoked in Phase 0.0 but scoped to this task via `task_id`). If the
scope-extractor is unavailable or returns no explicit paths, `CLAIM` is empty — proceed
directly to implementer dispatch (no-op claim).

```bash
# CLAIM = explicit-confidence paths from the task block's Files: list + scope-extractor(task=<id>)
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" claim \
  --run-id "$RUN" --paths "$CLAIM"   # comma-separated repo-relative paths
CLAIM_OUT="$?"   # claim exits 0 always; parse stdout JSON for conceded list
# stdout: {"claimed":[...], "conceded":[{"path":"...","holder_run_id":"..."}]}
```

**Handle each `conceded` entry (senior peer holds the path; eldest-senior = lowest run_id).**
When `conceded` is non-empty, pick the eldest senior (`holder_run_id` from the entry — this
is the lowest run_id among all seniors on that path as returned by `claim`):

**If `Z_HARNESS_AUTO_WAIT=1` (default):**

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" wait-for \
  --run-id "$RUN" --on "$HOLDER_RUN_ID" --paths "$CONCEDED_PATH"
WAIT_RC=$?
```

- `WAIT_RC == 0` (peer cleared / nothing-to-wait-on) → **re-`claim` the freed path** — this
  is a GENUINE acquisition, not a dedup no-op, because the loser never persisted the conceded
  path (claim persists only the won set per SPEC F-claim-wonset). Re-run `claim` with the
  conceded path(s) and add any newly-won paths to `CLAIM`. Then continue to implementer dispatch.
- `WAIT_RC == 10` (wait timeout — LOUD, per SPEC F1):
  <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface this timeout decision (proceed/abort) via their native channel. Silent omission is forbidden. -->
  - **Interactive (not `Z_HARNESS_NO_ASK`):** present `AskUserQuestion`: **proceed anyway** /
    **abort task**. If proceed → continue to dispatch (the contended path is not leased; the
    post-dispatch write-set validation in Phase 2.5 will catch any actual collision). If abort →
    flip `[~]` back to `[ ]`, log `task_halt {reason:"wait_timeout_abort"}`, then:
    ```bash
    RB_HALT_REASON="lease wait timeout (interactive abort)"
    ```
<!-- Host sets RB_HALT_REASON, BASE, RUN before include -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/TASKS.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-implement-next","command":"/z-implement-next"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).
    ```bash
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted 2>/dev/null || true
    exit 1
    ```
  - **Unattended (`Z_HARNESS_NO_ASK`) — ABORT TASK (MAJOR-4).** A held-path `wait-for` exit 10
    in unattended mode MUST abort the current task. It MUST NOT silently proceed (that recreates
    the collision) and MUST NOT automatically re-enter `wait-for` on the same blocker (a re-wait
    is only legitimate after the user re-queues the task). Emit a loud log, flip `[~]` back to
    `[ ]`, apply the FINALIZE_STATUS rule (deregister with `aborted`), and exit:
    ```bash
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_halt \
      "$(printf '{"id":"%s","reason":"wait_timeout_unattended","holder_run_id":"%s","path":"%s"}' \
         "<task-id>" "$HOLDER_RUN_ID" "$CONCEDED_PATH")"
    RB_HALT_REASON="lease wait timeout (unattended)"
    ```
<!-- Host sets RB_HALT_REASON, BASE, RUN before include -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/TASKS.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-implement-next","command":"/z-implement-next"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).
    ```bash
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status "$FINALIZE_STATUS" || true
    # flip [~] → [ ]; exit 1
    ```
    Cross-link: see Phase 0.0 SPEC F1 — this is the same loud-abort-on-timeout invariant.
- `WAIT_RC == 130` (SIGINT during park) → abort the task (same as unattended exit 10: apply the
  FINALIZE_STATUS rule, deregister with `aborted`, propagate the SIGINT to the outer shell).

**If `Z_HARNESS_AUTO_WAIT=0` (interactive wait mode):**

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the conceded-path proceed/wait/abort question via their native channel. Silent omission is forbidden. -->
Present `AskUserQuestion`: **proceed anyway** / **wait** / **abort task**.
- **proceed** → continue to implementer dispatch (the path is not leased; the F5 write-set
  validation below applies as a backstop).
- **wait** → call `wait-for --run-id $RUN --on $HOLDER_RUN_ID --paths $CONCEDED_PATH` (same
  `WAIT_RC` handling as the auto-wait path above).
- **abort task** → flip `[~]` back to `[ ]`, log `task_halt {reason:"user_aborted_lease"}`, then:
  ```bash
  RB_HALT_REASON="user aborted lease wait"
  ```
<!-- Host sets RB_HALT_REASON, BASE, RUN before include -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/TASKS.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-implement-next","command":"/z-implement-next"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  exit 1
  ```

**Dispatch implementer** (Phase 2 implementer dispatch below) with the claimed paths in scope.

Spawn the implementer subagent (fresh context).

**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
  ```

**Persona rotation (implementer dispatch — gated on `experiment.persona_rotation`).** When the knob is ON, draw a persona for this attempt, persist the draw, and prepend the persona body to the implementer prompt. When the knob is OFF, the entire block is a no-op — `PERSONA_PREFIX` is empty, no draw file is written, no draw event is emitted; behavior is identical to before this feature. On a re-invocation (the user runs `/z-implement-next` again for the same task after a prior attempt), a retry counter file is incremented so the new attempt gets a distinct `attempt_id` (`<task-id>-v2`, `<task-id>-v3`, …). Whether a fresh persona draw is performed or the cycle-1 anchor is reused depends on the `personas.implementer_retry` knob (default `"same"`).

**2x2 behavior matrix for `personas.implementer_retry` in `/z-implement-next`:**

| `experiment.persona_rotation` | `personas.implementer_retry` | On re-invocation (CURRENT_COUNTER ≥ 2) |
|-------------------------------|------------------------------|----------------------------------------|
| OFF | any | No-op. Byte-identical vanilla implementer. `implementer_retry` value is irrelevant. |
| ON | `"same"` (default) | Reuse the cycle-1 `persona-draw.json` anchor: same `persona_id` and `PERSONA_PREFIX` across all invocations. No redraw, no `--exclude`, no control-counter increment. **Rationale: lifecycle traceability** — one `persona_id` per task across all retry invocations. |
| ON | `"new"` | Fresh draw excluding the prior invocation's persona (forces diversity). Write the new draw to `persona-draw-v<CURRENT_COUNTER>.json` (per-invocation sidecar); cycle-1 anchor `persona-draw.json` is NOT overwritten. |
| ON | either | If `persona-draw.json` is MISSING on a re-invocation (e.g. older run): fall back to a fresh draw regardless of the knob. |

```bash
PERSONA_ROTATION="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get experiment.persona_rotation 2>/dev/null || echo "true")"

# Initialize ALL stratification fields to safe defaults at attempt start.
# An early-terminal (e.g. unable_to_complete) closes before any review runs;
# emit_persona_outcome's int() casts must not crash on empty strings.
BLOCKER_COUNT=0
WALL_MS=0
REVIEW_CYCLES=1
DIFF_SIZE=0
# Parse COMPLEXITY_TIER from the task block's **Complexity:** stamp, exactly as
# z-implement-all does — read directly from the TASKS file by task-id so there
# is no dependency on the TASK_BLOCK shell variable (which is described in prose
# but never populated by actual bash).  Extracts only the tier token (first word
# after the label — e.g. "low", "medium", or "high"; ignores trailing metadata
# like "· **DOCS:** config").
COMPLEXITY_TIER="$(python3 -c '
import sys, re
content = open(sys.argv[1]).read()
task_id = sys.argv[2]
m = re.search(r"(## " + re.escape(task_id) + r"\b.*?)(?=^## T|\Z)", content, re.M | re.S)
block = m.group(1) if m else ""
cm = re.search(r"\*\*Complexity:\*\*\s*(\S+)", block)
print(cm.group(1) if cm else "")
' "$TASKS_FILE" "<task-id>" 2>/dev/null || echo "")"

# --- Persona draw (only when knob is on) ---
PERSONA_PREFIX=""
PERSONA_ID=""
DRAW_ID=""
SELECTION_SOURCE=""
ATTEMPT_ID="<task-id>-v1"
RETRIES=0
if [ "$PERSONA_ROTATION" = "true" ]; then
  # Read the retry-persona knob only when rotation is on (no persona config I/O on the knob-OFF path).
  IMPLEMENTER_RETRY="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get personas.implementer_retry 2>/dev/null || echo "same")"
  # --- Determine ATTEMPT_ID (distinct per re-invocation) ---
  # The retry counter file persists how many times /z-implement-next has been invoked
  # for this task.  Each fresh invocation (including the very first) bumps the counter
  # exactly once — at the start of Phase 2, before the implementer is dispatched.  A
  # WITHIN-invocation resume (e.g. the user answers a needs_clarification question and
  # the implementer is re-dispatched in the same LLM session) does NOT re-execute this
  # Phase 2 block, so the counter is only bumped once per invocation as required.
  #
  # After bumping: ATTEMPT_ID = "<task-id>-v<counter>".
  # On the very first invocation ATTEMPT_ID = "<task-id>-v1".
  # On re-invocations ATTEMPT_ID = "<task-id>-v2", "<task-id>-v3", etc.
  #
  # The counter file lives at $BASE/archive/tasks/<task-id>/.retry-counter so it is
  # co-located with the other per-task artefacts and automatically scoped per task.
  mkdir -p "$BASE/archive/tasks/<task-id>"
  RETRY_COUNTER_FILE="$BASE/archive/tasks/<task-id>/.retry-counter"
  CURRENT_COUNTER="$(cat "$RETRY_COUNTER_FILE" 2>/dev/null | tr -d '[:space:]' || echo 0)"
  # Validate: must be a non-negative integer; treat garbage as 0.
  case "$CURRENT_COUNTER" in
    ''|*[!0-9]*) CURRENT_COUNTER=0 ;;
  esac
  CURRENT_COUNTER=$((CURRENT_COUNTER + 1))
  printf '%d' "$CURRENT_COUNTER" > "$RETRY_COUNTER_FILE"
  ATTEMPT_ID="<task-id>-v${CURRENT_COUNTER}"
  RETRIES=$((CURRENT_COUNTER - 1))

  CYCLE1_DRAW_FILE="$BASE/archive/tasks/<task-id>/persona-draw.json"

  # Export join keys so resolve-persona.py stamps task_id + attempt_id onto draw events.
  export Z_HARNESS_TASK_ID="<task-id>"
  export Z_HARNESS_ATTEMPT_ID="$ATTEMPT_ID"
  export Z_HARNESS_RUN_ID="$RUN"

  # Determine DRAW_FILE and REUSE based on the implementer_retry knob.
  REUSE=0
  if [ "$CURRENT_COUNTER" -ge 2 ] && [ "$IMPLEMENTER_RETRY" = "same" ] && [ -f "$CYCLE1_DRAW_FILE" ]; then
    # "same" knob on re-invocation: reuse cycle-1 anchor — one persona_id across all
    # invocations for lifecycle traceability. No redraw, no control-counter increment.
    DRAW_FILE="$CYCLE1_DRAW_FILE"
    REUSE=1
  elif [ "$CURRENT_COUNTER" -ge 2 ] && [ "$IMPLEMENTER_RETRY" = "new" ]; then
    # "new" knob on re-invocation: fresh draw into a per-invocation sidecar file;
    # the cycle-1 anchor (persona-draw.json) is never overwritten.
    DRAW_FILE="$BASE/archive/tasks/<task-id>/persona-draw-v${CURRENT_COUNTER}.json"
    # REUSE stays 0; fall through to fresh draw below.
  else
    # First invocation (CURRENT_COUNTER == 1), or "same" with missing anchor (fallback).
    DRAW_FILE="$CYCLE1_DRAW_FILE"
    if [ -f "$DRAW_FILE" ]; then
      EXISTING_ATTEMPT_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("attempt_id",""))' "$DRAW_FILE" 2>/dev/null || echo "")"
      [ "$EXISTING_ATTEMPT_ID" = "$ATTEMPT_ID" ] && REUSE=1
    fi
  fi

  if [ "$REUSE" -eq 0 ]; then
    # Fresh draw: increment control counter and apply forced-control cadence.
    # On a re-invocation with IMPLEMENTER_RETRY == "new" (or missing anchor fallback),
    # exclude the prior attempt's persona to force diversity.
    CONTROL_EVERY_N="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get experiment.control_every_n 2>/dev/null || echo 5)"
    CONTROL_COUNT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-persona.py" control-counter --increment)"
    if [ "$CONTROL_EVERY_N" -gt 0 ] && [ $(( CONTROL_COUNT % CONTROL_EVERY_N )) -eq 0 ]; then
      # Compute the floor-hit parity arm: alternate boring-anchor and no-persona
      # across consecutive forced-control hits (T106). Floor-hit index =
      # CONTROL_COUNT / CONTROL_EVERY_N (integer division); even index →
      # boring-anchor, odd index → no-persona.
      FLOOR_HIT_INDEX=$(( CONTROL_COUNT / CONTROL_EVERY_N ))
      if [ $(( FLOOR_HIT_INDEX % 2 )) -eq 0 ]; then
        FORCED_ARM="boring-anchor"
      else
        FORCED_ARM="no-persona"
      fi
      DRAW_JSON="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-persona.py" forced-control implementer --arm="$FORCED_ARM")"
    else
      # Exclude the prior cycle's persona on a re-invocation fresh draw.
      EXCLUDE_ARG=""
      if [ "$CURRENT_COUNTER" -ge 2 ] && [ -f "$CYCLE1_DRAW_FILE" ]; then
        PRIOR_PERSONA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("persona_id",""))' "$CYCLE1_DRAW_FILE" 2>/dev/null || echo "")"
        [ -n "$PRIOR_PERSONA" ] && EXCLUDE_ARG="--exclude=$PRIOR_PERSONA"
      fi
      DRAW_JSON="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-persona.py" random-for-role implementer $EXCLUDE_ARG)"
    fi
    # Persist the draw. On cycle-1 or fallback, $DRAW_FILE is the anchor (persona-draw.json).
    # On a "new" re-invocation, $DRAW_FILE is the per-invocation sidecar — anchor is untouched.
    python3 -c '
import json, sys
draw = json.loads(sys.argv[1]); attempt_id = sys.argv[2]; out = sys.argv[3]
rec = {"attempt_id": attempt_id, "persona_id": draw.get("persona"),
       "draw_id": draw.get("draw_id"), "selection_source": draw.get("selection_source"),
       "persona_body_path": draw.get("persona_body_path")}
json.dump(rec, open(out, "w"))
' "$DRAW_JSON" "$ATTEMPT_ID" "$DRAW_FILE"
  fi
  # Read attribution from the draw file (works on both fresh draw and resume/reuse).
  PERSONA_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("persona_id",""))' "$DRAW_FILE" 2>/dev/null || echo "")"
  DRAW_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("draw_id",""))' "$DRAW_FILE" 2>/dev/null || echo "")"
  SELECTION_SOURCE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("selection_source",""))' "$DRAW_FILE" 2>/dev/null || echo "")"
  PERSONA_BODY_PATH="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("persona_body_path",""))' "$DRAW_FILE" 2>/dev/null || echo "")"
  # no-persona is a tracked baseline arm: empty prefix, but draw event + outcome event still fire.
  if [ "$PERSONA_ID" != "no-persona" ] && [ -n "$PERSONA_BODY_PATH" ] && [ -f "$PERSONA_BODY_PATH" ]; then
    PERSONA_PREFIX="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/runtime/dispatch/persona_prompt.py" "$PERSONA_BODY_PATH" "" 2>/dev/null | head -c 4096 || true)"
    [ -n "$PERSONA_PREFIX" ] && PERSONA_PREFIX="${PERSONA_PREFIX}

"
  fi
fi

# --- Define emit_persona_outcome (called at every TRUE terminal path) ---
# Emits persona_attempt_outcome exactly once per attempt (idempotence guard).
# The function is a no-op when the knob is off (first guard line).
PERSONA_OUTCOME_EMITTED=0
emit_persona_outcome() {  # $1 = terminal status (done|unable_to_complete|abandoned)
  [ "$PERSONA_ROTATION" = "true" ] || return 0
  [ "$PERSONA_OUTCOME_EMITTED" -eq 1 ] && return 0
  PERSONA_OUTCOME_EMITTED=1
  local status="$1"
  local diff_lines
  diff_lines="$(wc -l < "$BASE/archive/tasks/<task-id>/diff.patch" 2>/dev/null | tr -d ' ')"
  [ -z "$diff_lines" ] && diff_lines=0
  local payload
  payload="$(python3 -c '
import json, sys
print(json.dumps({
  "run_id": sys.argv[1], "command": "z-implement-next", "role": "implementer",
  "task_id": sys.argv[2], "attempt_id": sys.argv[3], "persona_id": sys.argv[4],
  "draw_id": sys.argv[5], "complexity_tier": sys.argv[6], "diff_size": int(sys.argv[7]),
  "review_cycles": int(sys.argv[8]), "retries": int(sys.argv[9]),
  "blocker_count": int(sys.argv[10]), "wall_ms": int(sys.argv[11]), "status": sys.argv[12],
}))' "$RUN" "<task-id>" "$ATTEMPT_ID" "$PERSONA_ID" "$DRAW_ID" "$COMPLEXITY_TIER" \
      "$diff_lines" "$REVIEW_CYCLES" "$RETRIES" "$BLOCKER_COUNT" "$WALL_MS" "$status")"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "tasks/<task-id>" persona_attempt_outcome "$payload"
}
```

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
model label so it can be logged via `log-subagent.sh`. Mirrors the `sonnet`/`opus` selection rules
above: `COMPLEXITY_TIER` was already parsed from the task block earlier in this phase.

```bash
# Resolve effective implementer model label for telemetry.
# Opus when: Complexity: high in task block; otherwise default to sonnet.
IMPL_MODEL="sonnet"
if [[ "${COMPLEXITY_TIER:-}" == "high" ]]; then
  IMPL_MODEL="opus"
fi
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
IMPL_PROMPT_CHARS="${#IMPL_PROMPT}"   # set IMPL_PROMPT to the full prompt string before passing it
```

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="implementer",
  description="Implement <task-id>",
  model="<sonnet|opus per the rules above>",
  prompt="<PERSONA_PREFIX (empty when persona_rotation is off)><task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to $Z_HARNESS_PLAN_DIR>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

```bash
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
IMPL_RESPONSE_CHARS="${#IMPL_RESPONSE}"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-subagent.sh" \
  --run "tasks/<task-id>" \
  --role "implementer" \
  --subagent-type "implementer" \
  --subagent-model "$IMPL_MODEL" \
  --prompt-chars "$IMPL_PROMPT_CHARS" \
  --response-chars "$IMPL_RESPONSE_CHARS" || true
```

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.

Parse the implementer's return `STATUS:`. If `STATUS: unable_to_complete`, call `emit_persona_outcome "unable_to_complete"` (no-op when the knob is off) before surfacing the reason to the user — this is a TRUE terminal for the attempt. `needs_clarification`, `spec_problem`, and `decision_needed` are PAUSES (the same attempt resumes after the user answers) — do NOT call `emit_persona_outcome` on these.

Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.

Obey DRY/KISS/SOLID. No shortcuts unless PLAN.md explicitly approved one for this task.

**Parse the implementer's return.** Handle every STATUS before proceeding to Phase 3:

- `STATUS: ok` → continue to Phase 3 (review).
- `STATUS: unable_to_complete` → a record EXISTS (registered in Phase 0.0). Set `RB_HALT_REASON` from the implementer reason, run halt-finalize, deregister, push-notify, and stop:
  ```bash
  RB_HALT_REASON="${IMPLEMENTER_HALT_REASON:-unable to complete task}"
  ```
<!-- Host sets RB_HALT_REASON, BASE, RUN before include -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/TASKS.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-implement-next","command":"/z-implement-next"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status "$FINALIZE_STATUS" || true   # CLI self-logs registry_error on failure
  # push-notify + exit 1
  ```
- `STATUS: needs_clarification` / `STATUS: spec_problem` / `STATUS: decision_needed` → halt,
  push-notify, escalate to the user. If the orchestrator decides to stop entirely (not re-spawn),
  apply the FINALIZE_STATUS rule (deregister with `aborted`) before exit. If the user resolves
  the issue and the orchestrator re-spawns the implementer, keep the existing record alive (no
  deregister); deregister only on the final terminal exit.

**Write-set validation (F5 backstop — runs on `STATUS: ok`).**

This is the **narrowest** of the three contention detectors (T002 claim-time, T005
scope-inspection, T012 post-task). It gates strictly on **live-peer-lease overlap** so
unclaimed-but-uncontended edits produce **zero** warnings. Only when an undeclared path is ALSO
held by a live peer does a `coordination_warning` fire — one event per colliding path.

```bash
# 1. Compute actual changed paths (repo-relative, newline-separated).
ACTUAL_PATHS="$(git diff --name-only 2>/dev/null)"

# 2. Compute undeclared = actual − CLAIM (paths the implementer touched but did not claim).
#    CLAIM is the comma-separated won-set from Phase 2.5. Convert to newline form for comparison.
CLAIM_NEWLINE="$(printf '%s' "$CLAIM" | tr ',' '\n')"
UNDECLARED_PATHS="$(comm -23 \
  <(printf '%s\n' "$ACTUAL_PATHS" | sort) \
  <(printf '%s\n' "$CLAIM_NEWLINE" | sort))"

# 3. If no undeclared paths, skip entirely — zero warnings, zero noise.
if [ -n "$UNDECLARED_PATHS" ]; then
  # 4. Fetch the current overlaps payload to find live peers with held_paths.
  #    overlaps exits 0/10/20 — we only care about the JSON payload, not the exit code.
  OVL_JSON="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" \
    overlaps --run-id "$RUN" --json 2>/dev/null || echo '{}')"

  # 5. For each undeclared path, check whether any live peer holds it via the held_conflict block.
  #    The held_conflict key (singular) per the overlaps JSON schema (T005/SPEC).
  #    Emit exactly ONE coordination_warning per colliding (undeclared-path × peer) pair.
  while IFS= read -r UNDECLARED_PATH; do
    [ -z "$UNDECLARED_PATH" ] && continue
    PEER_RUN_ID="$(python3 -c '
import json, sys
payload = json.loads(sys.argv[1])
target = sys.argv[2]
for entry in payload.get("held_conflict", []):
    if entry.get("path") == target:
        print(entry.get("peer_run_id", ""))
        break
' "$OVL_JSON" "$UNDECLARED_PATH" 2>/dev/null || true)"

    if [ -n "$PEER_RUN_ID" ]; then
      # Gate: only emit if the peer is live AND holds this specific path.
      # Uncontended undeclared edits (no live peer holds the path) produce ZERO warnings.
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
        "tasks/<task-id>" coordination_warning \
        "$(printf '{"run_id":"%s","path":"%s","peer_run_id":"%s"}' \
           "$RUN" "$UNDECLARED_PATH" "$PEER_RUN_ID")"
      echo "COORDINATION WARNING: undeclared write to '$UNDECLARED_PATH'" \
           "conflicts with live peer lease held by run '$PEER_RUN_ID'." >&2
    fi
    # If PEER_RUN_ID is empty: undeclared but uncontended — emit nothing (zero-noise guarantee).
  done <<< "$UNDECLARED_PATHS"
fi
```

**Zero-noise property (mandatory).** An undeclared path that no live peer currently holds in
`held_paths` produces **zero** `coordination_warning` events. Only the intersection of
(undeclared by this run) AND (held by a live peer lease) triggers a warning.

**T005 `held_conflict` payload note.** The `overlaps --json` payload carries `held_conflict` as a
**top-level flat list** of `{path, peer_run_id, holder_seniority}` entries — key `path` (singular),
not a nested sub-list keyed by peer. The F5 `coordination_warning` step iterates this flat list,
matching each entry's `path` to read `peer_run_id`. (The Phase-2.5 wait decision uses `shared_paths`
+ run_id seniority; `/z-where` renders overlap/peer info from separate registry fields — neither
consumes `held_conflict`.)

The warning is review-blocking (surface it to the reviewer in Phase 3), but does not stop the
Phase 3 dispatch.

**Lease release and halt semantics.**

- **On clean task success (before marking `[x]` in Phase 5):** release the lease:
  ```bash
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" release \
    --run-id "$RUN" --paths "$CLAIM"   # CLI self-logs registry_error on failure; exits 0 always
  ```
- **On review-fail with "patch manually" (user takes over within the same invocation):** KEEP the
  existing lease. Do NOT release until the user signals completion and Phase 5 runs. If the user
  subsequently asks the orchestrator to re-dispatch the implementer (e.g. after patching), expand
  `CLAIM` with any newly-touched paths before re-dispatch. Release only on clean final success.
- **On halt mid-task** (`unable_to_complete` or other terminal halt after implementer dispatch):
  do NOT release. Rely on `deregister` (from the FINALIZE_STATUS rule) or `reap` (stale-timeout)
  to clean up `held_paths`. A partially-applied edit must not release the lease before the task
  resolves.
- **On re-invocation** (user runs `/z-implement-next` again for the same task after a prior attempt
  ended without `[x]`): the previous run's lease was cleaned up by its `deregister`; the new
  invocation runs a fresh `claim` in Phase 2.5 as usual.

## Phase 3 — Codex review

1. Capture the diff: `git diff > $BASE/archive/tasks/<task-id>/diff.patch` (if no git, fall back to listing changed file paths).
2. `PERSONA_ROTATION` and `ATTEMPT_ID` were initialized in Phase 2 before the implementer dispatch; they are already in scope here. No re-read is needed. For reference:
   - `PERSONA_ROTATION` — the `experiment.persona_rotation` knob value (`"true"` or `"false"`).
   - `ATTEMPT_ID` — `"<task-id>-v<N>"` where N is the current invocation counter (1 on first invocation, increments on re-invocations).

3. Spawn the reviewer(s) with the diff, not just file contents.

   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

   **Base codex reviewer** (always the gating reviewer):

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="reviewer",
  description="Codex scrutiny of task <ID>",
  prompt="task id: <id>\nreviewer_participant: base_codex\ntask description: <title>\nacceptance criteria: <verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

   Log the base codex reviewer as `persona_bound` (tag `reviewer_participant=base_codex`). The base reviewer is not a random draw, so its `draw_id` is the deterministic synthetic id `<attempt_id>-base_codex`. Only emit when `experiment.persona_rotation` is on — knob-off must be a true no-op:
   ```bash
   if [ "$PERSONA_ROTATION" = "true" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
       "tasks/<task-id>" persona_bound \
       "$(python3 -c 'import json,sys; print(json.dumps({"command":"z-implement-next","role":"reviewer","task_id":sys.argv[1],"attempt_id":sys.argv[2],"draw_id":sys.argv[2]+"-base_codex","reviewer_participant":"base_codex","cycle":1}))' "<task-id>" "$ATTEMPT_ID")"
   fi
   ```

   **Random-arm reviewer (advisory — only when BOTH `experiment.persona_rotation == "true"` AND `personas.review_eval == "true"`).** Verdict is recorded for data-collection; it must NOT change review outcome. Draw a reviewer persona, prepend it to the prompt:

   ```bash
   REVIEW_EVAL="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get personas.review_eval 2>/dev/null || echo true)"
   if [ "$PERSONA_ROTATION" = "true" ] && [ "$REVIEW_EVAL" = "true" ]; then
     # Re-export join keys so the reviewer draw event carries task_id + attempt_id.
     # ATTEMPT_ID is set above as <task-id>-v1; these exports make it available to
     # resolve-persona.py even if this block runs after a shell scope change.
     export Z_HARNESS_TASK_ID="<task-id>"
     export Z_HARNESS_ATTEMPT_ID="$ATTEMPT_ID"
     export Z_HARNESS_RUN_ID="$RUN"
     REVIEWER_DRAW_JSON="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-persona.py" \
       random-for-role reviewer 2>/dev/null || echo '{}')"
     REVIEWER_PERSONA_BODY_PATH="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("persona_body_path",""))' "$REVIEWER_DRAW_JSON" 2>/dev/null || echo "")"
     REVIEWER_DRAW_ID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("draw_id",""))' "$REVIEWER_DRAW_JSON" 2>/dev/null || echo "")"
     REVIEWER_PERSONA_ID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("persona",""))' "$REVIEWER_DRAW_JSON" 2>/dev/null || echo "")"
     if [ -n "$REVIEWER_PERSONA_BODY_PATH" ] && [ -f "$REVIEWER_PERSONA_BODY_PATH" ]; then
       REVIEWER_PERSONA_PREFIX="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/runtime/dispatch/persona_prompt.py" "$REVIEWER_PERSONA_BODY_PATH" "" 2>/dev/null | head -c 4096 || true)"
       [ -n "$REVIEWER_PERSONA_PREFIX" ] && REVIEWER_PERSONA_PREFIX="${REVIEWER_PERSONA_PREFIX}

"
     else
       REVIEWER_PERSONA_PREFIX=""
     fi
   fi
   ```

<!-- RUNTIME-GATE: subagent; non-supporting drivers may skip the random-arm reviewer — it is advisory only. The base codex reviewer above is the required correctness gate. -->
```
# Only dispatch when PERSONA_ROTATION == "true" AND REVIEW_EVAL == "true":
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="reviewer",
  description="Advisory review (random arm) task <ID>",
  prompt="<REVIEWER_PERSONA_PREFIX><ADVISORY: this review is for data-collection only — verdict is recorded but does not gate the task>\ntask id: <id>\nreviewer_participant: random_arm\ntask description: <title>\nacceptance criteria: <verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

   Log the random-arm reviewer as `persona_bound` (tag `reviewer_participant=random_arm`, same `attempt_id`):
   ```bash
   if [ "$PERSONA_ROTATION" = "true" ] && [ "$REVIEW_EVAL" = "true" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
       "tasks/<task-id>" persona_bound \
       "$(python3 -c 'import json,sys; print(json.dumps({"command":"z-implement-next","role":"reviewer","task_id":sys.argv[1],"attempt_id":sys.argv[2],"reviewer_participant":"random_arm","persona_id":sys.argv[3],"draw_id":sys.argv[4],"cycle":1}))' "<task-id>" "$ATTEMPT_ID" "$REVIEWER_PERSONA_ID" "$REVIEWER_DRAW_ID")"
   fi
   ```

   **Advisory verdict handling.** Capture each reviewer's response into a SEPARATE variable — `BASE_CODEX_RESPONSE` for the base codex reviewer and `RANDOM_ARM_RESPONSE` for the advisory arm. The two responses must NEVER be merged into a single variable. Parse and act on ONLY `BASE_CODEX_RESPONSE` when deciding which findings to apply. `RANDOM_ARM_RESPONSE` is stored for telemetry/logging only; the advisory arm's verdict must NOT change which findings are raised or acted upon.

**Handle review outcome.** Parse `BASE_CODEX_RESPONSE`. Group findings by severity (blockers, majors, minors).

- **No blockers, no majors** → accept. Apply findings that hold up; push back on those that don't and document the pushback. Proceed to Phase 3.5.

- **Has blockers or majors** → `/z-implement-next` is single-shot and does not auto-retry. Present the diff and reviewer findings to the user and push-notify. Before presenting, run the `check-no-ask` resolver for `workflow.implement_all_proceed`:

  ```bash
  NO_ASK_RESULT="$(python3 scripts/config.py check-no-ask --question-id workflow.implement_all_proceed 2>/dev/null || echo '{}')"
  NO_ASK_CHECK="$(printf '%s' "$NO_ASK_RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result","proceed"))' 2>/dev/null || echo proceed)"
  ```

  If `$NO_ASK_CHECK == "halt"`: do NOT invoke `AskUserQuestion`. Call `emit_persona_outcome "abandoned"` (no-op when the knob is off), then flip `[ ]` back on this task and surface the halt reason to the user. This is a TRUE terminal — the emit fires here.

  Otherwise (`$NO_ASK_CHECK == "proceed"`): present the diff + reviewer findings to the user. **Do NOT emit the outcome before the user chooses** — a speculative emit here would mis-record the status and the idempotence guard would block the real terminal emit. After the user answers, emit `emit_persona_outcome` with the status that choice produces (no-op when the knob is off; idempotent so exactly one row lands per attempt):

  <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the review-failure decision (proceed anyway / patch manually / abandon task / re-spec) via their native channel. Silent omission is forbidden. -->
  Use `AskUserQuestion` with options: **proceed anyway / patch manually / abandon task / re-spec**.

  - **proceed anyway** → the attempt is accepted as-is. Call `emit_persona_outcome "done"` (TRUE terminal), then proceed to Phase 3.5 and Phase 5 (mark done).
  - **patch manually** → the user takes over; this is NOT an automated attempt close. Do NOT call `emit_persona_outcome` here. The attempt closes later when the user resumes and reaches a real terminal.
  - **abandon task / re-spec** → the attempt is abandoned. Call `emit_persona_outcome "abandoned"` (TRUE terminal) before halting. Do not mark the task done.

  In all cases apply findings from the base codex reviewer that hold up before presenting; push back on those that don't and document the pushback.

## Phase 3.5 — Parse FOLLOWUPS block and route to sink

After the reviewer returns, parse the `**FOLLOWUPS:**` block from `$RETURN` and route each entry to the follow-up sink:

```bash
FOLLOWUPS_JSON="$(printf '%s' "$RETURN" | python3 scripts/parse-followups-block.py 2>/dev/null || echo '[]')"
FOLLOWUP_COUNT="$(printf '%s' "$FOLLOWUPS_JSON" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)"

if [ "${FOLLOWUP_COUNT:-0}" -gt 0 ]; then
  printf '%s' "$FOLLOWUPS_JSON" | python3 -c "
import json, subprocess, sys

entries = json.load(sys.stdin)
task_id = sys.argv[1]
source_artifact = sys.argv[2]
script = sys.argv[3]

for i, e in enumerate(entries):
    cited = ','.join(e.get('cited_paths', []))
    args = [
        'bash', script,
        '--sink=project',
        f'--priority={e[\"priority\"]}',
        f'--name={e[\"name\"]}',
        f'--recommended-command={e[\"recommended_command\"]}',
        f'--source-artifact={source_artifact}',
        f'--cited-paths={cited}',
    ]
    if e.get('auto_close_eligible'):
        args.append('--auto-close-eligible')
    if e.get('recommended_command_safe_to_retry'):
        args.append('--safe-to-retry')
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode not in (0, 3):  # 3 = dedup-skip (ok)
        print(f'warn: sink-add.sh exit {result.returncode} for entry {i}: {result.stderr[:200]}', file=sys.stderr)
" "$TASK_ID" "$BASE/archive/tasks/$TASK_ID/diff.patch" "scripts/sink-add.sh" 2>/dev/null || true
fi
```

Per-entry errors are logged + skipped. This step never blocks the reviewer return path. If `scripts/sink-add.sh` is not yet present (deps not implemented), this step is silently skipped.

## Phase 4 — Spec retro

If during implementation you discovered `$BASE/SPEC.md` was wrong, incomplete, or ambiguous — update it now so the next task starts from accurate ground truth. Log the retro: `log-event.sh "tasks/<task-id>" spec_retro '{"summary":"..."}'`.

### Defer-to-sink branch

If the implementer's return flags an **out-of-current-SPEC discovery** (a finding that is real but out of scope for this task), consult the resolver before editing SPEC.md inline:

```bash
RESOLVED="$(python3 scripts/config.py resolve-question workflow.spec_retro_discovery 2>/dev/null)"
RESOLVE_EXIT=$?
RESULT="$(printf '%s' "$RESOLVED" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result","ask"))' 2>/dev/null || echo ask)"
```

- **`result == "defer-to-sink"`**: do NOT edit SPEC.md mid-run. Instead, call `scripts/sink-add.sh` to park the finding as a P2 follow-up:

  ```bash
  bash scripts/sink-add.sh \
    --sink=project \
    --priority=P2 \
    --name='<short title from discovery>' \
    --recommended-command='/z-do "amend SPEC.md: <discovery summary>"' \
    --source-artifact="$BASE/archive/tasks/<task-id>/diff.patch" \
    --cited-paths='<affected file paths, comma-separated>' \
    --prompt-body='<implementer discovery text verbatim>'
  ```

  Then log the deferral event and continue to Phase 5 without modifying SPEC.md:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "tasks/<task-id>" followup_deferred_from_resolver \
    "$(printf '{"question_id":"workflow.spec_retro_discovery","task":"<task-id>","summary":"<one-line>"}' )"
  ```

  If `sink-add.sh` exits non-zero, surface the error to the user and fall back to asking interactively — the discovery must not be silently dropped.

- **`result == "ask"` (or resolver error)**: present the discovery to the user with `AskUserQuestion`. If user confirms it needs a spec fix, update `$BASE/SPEC.md` now. If user says it's deferred, call `sink-add.sh` manually.

## Run Brief — halt finalize

Before `deregister --status aborted` on any run-ending halt after `run-brief.sh init` (unless register failed — no deregister). Set `RB_HALT_REASON`, then include the halt-finalize fragment.

<!-- Host sets RB_HALT_REASON, BASE, RUN before include -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/TASKS.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-implement-next","command":"/z-implement-next"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).

Then set `FINALIZE_STATUS=aborted` and deregister:

```bash
FINALIZE_STATUS=aborted
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status aborted 2>/dev/null || true
```

## Phase 5 — Mark done + Run Brief finalize

1. Flip `[ ]` to `[x]` in `$TASKS_FILE`. Add a one-line completion note under the task.
2. Log task end with summary stats.
3. **Emit `persona_attempt_outcome` (attempt close — only when `experiment.persona_rotation == "true"`).** This is a TRUE terminal for the attempt. `REVIEW_CYCLES` and `RETRIES` were initialized from `CURRENT_COUNTER` in Phase 2 (`REVIEW_CYCLES=1`, `RETRIES=CURRENT_COUNTER-1`). Populate `BLOCKER_COUNT` from the base codex reviewer's response (0 if the reviewer was skipped or found none), and `WALL_MS` from the phase timing token if available. Then:
   ```bash
   emit_persona_outcome "done"   # no-op when the knob is off; idempotent
   ```
4. **Release the lease** (best-effort, non-fatal) before marking `[x]`. This unblocks any junior
   peer waiting on a path this task held. The `release` subcommand returns 0 by design and
   self-logs a `registry_error` on internal failure. If `CLAIM` is empty (no paths were claimed),
   this is a harmless no-op.
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" release \
     --run-id "$RUN" --paths "$CLAIM" || true   # CLI self-logs registry_error on failure
   ```
5. **Run Brief — set `outcome` and `next` before the shared finalize fragment.** Primary artifact:
   `$TASKS_FILE` (the task block lives in TASKS.md). Decisions aggregate from events inside the
   fragment.

   ```bash
   RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
   CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
   REMAINING="$(python3 - "$TASKS_FILE" <<'PY'
   import re, sys
   text = open(sys.argv[1]).read()
   print(len(re.findall(r"\[ \]", text)))
   PY
   )"
   OUTCOME="Task <task-id> complete. ${REMAINING} remaining."
   bash "$RB_SH" set-section --run "$RUN" --section outcome --value "$OUTCOME"
   if [ "${REMAINING:-0}" -gt 0 ]; then
     NEXT_LABEL="Run /z-implement-next to continue"
     NEXT_CMD="/z-implement-next"
   else
     NEXT_LABEL="Run /z-review-all for final-gate cross-LLM review"
     NEXT_CMD="/z-review-all"
   fi
   NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
   python3 -c 'import json,sys; print(json.dumps({"label":sys.argv[1],"command":sys.argv[2]}))' \
     "$NEXT_LABEL" "$NEXT_CMD" > "$NEXT_JSON"
   bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
   rm -f "$NEXT_JSON"
   bash "$RB_SH" set-section --run "$RUN" --section status --value "complete"
   export RUN_BRIEF_PROFILE=full
   export RUN_BRIEF_ARTIFACT="$TASKS_FILE"
   export RUN_BRIEF_ARTIFACT_FALLBACKS=""
   ```

6. **Run Brief finalize** — chat and push are renders only; `--require` runs before deregister:

<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).

7. **Deregister this run** only when `--require` passed (`RB_REQUIRE_RC == 0`). Per the single
   FINALIZE_STATUS rule (Phase 0.0): normal completion deregisters with `complete`. On
   `--require` failure the fragment sets `FINALIZE_STATUS=aborted` — do not deregister as
   complete. If register failed earlier (no record was ever written), deregister is a harmless
   no-op.

   ```bash
   if [[ "${RB_REQUIRE_RC:-1}" -eq 0 ]]; then
     python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
       --run-id "$RUN" --status "complete" || true   # CLI self-logs registry_error on failure
   fi
   ```

Do **not** auto-advance. Wait for the user to invoke `/z-implement-next` again — this forces a fresh context per task.

### Git history-rewrite safety

Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream: for each commit being rewritten, run `git branch -r --contains <sha>`. If the upstream ref appears, STOP — recommend rebase or new-commit instead, never silent rewrite. Force-push to main requires explicit per-incident user authorization with (i) list of overwritten commits and (ii) content-equivalence/superset demonstration.

## Decision emission (standing instruction)

After **any** `AskUserQuestion` resolves, emit a normalized decision event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-decision.sh" \
  "$RUN" "<question_id>" "<chosen_label>" \
  --options '["<opt1>","<opt2>",...]' \
  [--tentative "<recommended_option>"]
```

- `<question_id>` — stable kebab-case identifier for this decision point (e.g. `workflow.implement_all_proceed`, `workflow.slug_confirm`).
- `<chosen_label>` — the option label the user selected, verbatim.
- `--options` — full list of offered option labels as a JSON array.
- `--tentative` — the orchestrator's recommended option label; omit when the orchestrator had no recommendation.

Emission is gated by `Z_HARNESS_AXIOM_EXTRACT` (default on); when set to `"0"`, the script exits silently — no guard is needed here. Do **not** modify existing structured gate events (`cost_gate_decision`, `critique_failure_decision`, `map_collision_decision`, `shared_concerns_ack_override`); those are normalized separately by the extractor. This emission **records signal only** — it never approves, overrides, or influences any decision (proposes-only invariant).

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 2 implementer; Phase 3 base codex reviewer (required); Phase 3 random-arm reviewer (advisory, only when `experiment.persona_rotation` is on) |
| `ask_user` | yes | Phase 0 slug selection (multiple candidates); Phase 2.5 lease wait-timeout proceed/abort (interactive, not NO_ASK); Phase 2.5 conceded-path proceed/wait/abort (AUTO_WAIT=0); Phase 3 review-failure decision (proceed anyway / patch manually / abandon task / re-spec) |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
