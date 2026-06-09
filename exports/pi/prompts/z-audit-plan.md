# /z-audit-plan

You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.

This command is **read-only**. Never edit active codebase files. Plan adjustments happen later via `/z-amend` or `/z-plan` based on the audit report's findings.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.

Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.

Deterministic routes:
- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

---

## Phase 0 — Setup

0. **Initialize no-plan route archive:**
   Before discovering a plan slug, define a route archive for the "no artifacts found" branch:
   ```bash
   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
   NO_PLAN_ARCHIVE_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir)/archive/$NO_PLAN_RUN"
   ```
1. **Discover plan slug:**
   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
   - If single candidate -> use it.
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug
        selection question via their native channel. Silent omission is forbidden. -->
   > [pi] No native tool — handle inline by asking the user / tracking state yourself (see CAPABILITIES.md).
     ```bash
     if [[ "${CLAIM_RC:-1}" -eq 0 ]]; then
       HB_RC=0
       bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
         --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
         --command /z-audit-plan || HB_RC=$?
       if [[ $HB_RC -eq 9 ]]; then
         bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
           "$(printf '{"slug":"%s","run_id":"%s","gate":"slug_select"}' "$Z_HARNESS_SLUG" "$RUN")"
         # Lost-claim gate: abort (default) / continue-uncoordinated.
         # Interactive -> AskUserQuestion: abort / continue-uncoordinated (clearly labeled: peer may clobber).
         # Unattended (Z_HARNESS_NO_ASK) -> abort. Release first (we held the claim), no deregister
         # (nothing registered yet at this point in Phase 0).
         bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
           --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
           --command /z-audit-plan || true
         exit 1
       fi
     fi
     ```
     Then use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
2. **Export variables:**
   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
3. **Pick run ID:**
   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
4. **Create directories:**
   `mkdir -p $BASE/archive/$RUN/transcripts`
5. **Version stamp + log run start:**
   Capture the z-harness plugin version stamp and log the run start:
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
   ```

   **Session id — export ONCE, persist, restore on resume (invariant 7; do this before the claim acquire).** `/z-audit-plan` has no coordination wiring today; resolve the session id exactly once here, persist it to the run archive so a crash-resume reuses the SAME id (the claim's self-reentry guard depends on a stable id), and restore it on resume BEFORE acquiring. `plan-claim.sh` never derives the session id itself — the caller always passes it via `--session`.
   ```bash
   # Restore a persisted session id on resume; otherwise mint one and persist it.
   SID_FILE="$BASE/archive/$RUN/session-id"
   if [[ -z "${Z_HARNESS_SESSION_ID:-}" && -f "$SID_FILE" ]]; then
     export Z_HARNESS_SESSION_ID="$(cat "$SID_FILE")"
   fi
   if [[ -z "${Z_HARNESS_SESSION_ID:-}" ]]; then
     export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"
   fi
   mkdir -p "$BASE/archive/$RUN"
   printf '%s' "$Z_HARNESS_SESSION_ID" > "$SID_FILE"
   ```

   **Claim acquire — CLAIM-FIRST (invariant 2; BEFORE register, BEFORE the Run Brief init, BEFORE any artifact read).** The slug-level hard claim-lock is authoritative; the registry read below is advisory/FYI only. Acquiring before `register` avoids a register-succeeded-but-claim-aborted orphan (a registry record with no claim, needing deregister-without-release). The `--command /z-audit-plan` flag is REQUIRED on this and every later `plan-claim.sh` call (heartbeat, release) — it rebuilds the holder identity string for `--expected-holder` comparisons; omitting it makes those subcommands exit 2 or mis-compare.
   ```bash
   CLAIM_RC=0
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" acquire \
     --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
     --command /z-audit-plan || CLAIM_RC=$?
   ```
   Branch on `CLAIM_RC` (gated; surfaced — never silent). The audit's slug is FIXED to the plan being audited, so contention/takeover offers **proceed / abort only** — there is NO use-new-slug option (unlike `/z-plan`):
   - `0` → claimed (or self-reentry, or `Z_HARNESS_CLAIM_DISABLE=1` no-op) → proceed to register.
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the claim
        contention/takeover gate (proceed / abort) via their native channel.
        Silent omission is forbidden. -->
   - `1` (live peer holds the claim) → show the printed holder JSON (session / command / heartbeat-age). **Interactive** → `AskUserQuestion`: **proceed anyway / abort**. **Unattended** (`Z_HARNESS_NO_ASK`) → abort (`exit 1`) UNLESS `Z_HARNESS_CLAIM_OVERRIDE=1` (then proceed). On abort here: exit WITHOUT register (nothing registered yet) and WITHOUT release (we never acquired the lock).
   - `2` (stale-takeover succeeded — **we now hold the lock**) → show the prior holder + idle age. **Interactive** → `AskUserQuestion`: **proceed / abort** (default ABORT — the prior session's partial artifacts may exist). **Unattended** → abort UNLESS `Z_HARNESS_CLAIM_OVERRIDE=1`. **On abort here, CALL `release` FIRST** (we hold the lock we just took over), then exit WITHOUT register:
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
       --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
       --command /z-audit-plan || true
     exit 1
     ```
   - `3` (corrupt / invalid — **we do NOT hold the lock**) → loud error. Proceeding does NOT acquire the slug. **Interactive** → `AskUserQuestion`: **abort (default)** / **proceed UNCOORDINATED** (clearly labeled: you and a peer may clobber each other; manual-cleanup hint `rm <claims_dir>/<slug>.lock*` then retry). **Unattended** → abort UNLESS `Z_HARNESS_CLAIM_OVERRIDE=1` (proceed uncoordinated). Do NOT call release (we never held it).

   **Teardown contract for the claim gate:** on any abort at `CLAIM_RC` 0/1/3, exit WITHOUT release (we never acquired). At a `CLAIM_RC == 2` abort, release FIRST (shown above) then exit. A claim-gate abort registered NOTHING and (except exit-2) acquired nothing, so there is no deregister-without-release case. (`Z_HARNESS_CLAIM_DISABLE=1` skips claiming entirely; `Z_HARNESS_CLAIM_OVERRIDE=1` is the explicit unattended opt-in to proceed on contention/takeover/corrupt. Both are env-only knobs read inline by `plan-claim.sh`; see [docs/human/config.md](docs/human/config.md).)

   **Active-plan registration — AFTER a successful claim (so a concurrent `/z-plan`'s awareness read can SEE this active audit).** Register lightly with `--phase audit`. Graduated failure policy (same as `/z-plan`) — never silent-continue on failure:
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
     --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-audit-plan --phase audit \
     --session "$Z_HARNESS_SESSION_ID"
   REG_RC=$?
   ```
   - `REG_RC == 0` → registered; proceed.
   - `REG_RC == 3` (register FAILED — no record was written) → emit a loud `registry_error` event, then branch:
     - **Interactive** (not `Z_HARNESS_NO_ASK`) → `AskUserQuestion`: *proceed without coordination* / *abort*.
       - **proceed** → continue; skip heartbeats and deregister later (no record to update). The claim is still held.
       - **abort** → push-notify, **release the claim first** (we hold it — register failed AFTER a successful acquire), do **NOT** call deregister (no record exists), then `exit 1`:
         ```bash
         bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
           --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
           --command /z-audit-plan || true
         exit 1
         ```
     - **Unattended (`Z_HARNESS_NO_ASK`)** → proceed without coordination and log prominently, UNLESS `Z_HARNESS_STRICT_OVERLAP=1` → release the claim (as above) and halt (`exit 1`). No deregister either way (no record).
   - **Any OTHER nonzero** → treat as `REG_RC == 3`.
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
     "$(printf '{"op":"register","run_id":"%s","rc":%d}' "$RUN" "$REG_RC")"
   ```

   **FINALIZE_STATUS / teardown rule (single source of truth for the entire run):** the audit is now claim-first (acquire → register), so teardown is gated per-resource. On any run-ending halt that occurs AFTER a successful **claim**, `release` BEFORE `deregister` (both best-effort `|| true`); release only if the claim was acquired, deregister only if `REG_RC == 0`. Release+deregister teardown is wired into every post-claim exit path below (normal-end after Phase 9, and all halt-finalize paths). Heartbeat is called at each phase boundary and before every AskUserQuestion gate.

   **Plan-start awareness read (advisory; Invariant 1 — never a hard gate).** After a successful claim and register, read the lockless registry and surface concurrent peers. Read-only, deterministic, non-fatal:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" list --json 2>/dev/null
   AWARE_RC=$?
   ```
   Render any record whose `session_id != $Z_HARNESS_SESSION_ID` as a one-line advisory ("Other active sessions: <run_id> — <command> on <slug> (heartbeat <age>)"). On a non-zero `list` exit, emit `registry_error {op:"awareness_read_failed", rc:$AWARE_RC}` and **CONTINUE** — the awareness read never blocks or gates a subsequent phase:
   ```bash
   if [[ $AWARE_RC -ne 0 ]]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
       "$(printf '{"op":"awareness_read_failed","rc":%d}' "$AWARE_RC")"
   fi
   ```

   **Run Brief init (after the claim + register + awareness read).** Registry: `/z-audit-plan`, profile `full`, artifact `PLAN_AUDIT_REPORT.md`.
   ```bash
   CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
   RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
   PLAN_AUDIT_INTENT="Pre-implementation audit of plan ${Z_HARNESS_SLUG}"
   bash "$RB_SH" init --run "$RUN" --command /z-audit-plan --slug "$Z_HARNESS_SLUG" --profile full --intent "$PLAN_AUDIT_INTENT"
   export RUN_BRIEF_PROFILE=full
   export RUN_BRIEF_ARTIFACT="$BASE/PLAN_AUDIT_REPORT.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS=""
   ```
6. **Notification policy:** see [docs/human/config.md](docs/human/config.md) (notify.level key).
7. **Docs Grounding:**
   If `docs/llm/INDEX.json` exists in the repo root, dispatch `doc-fetcher` (Haiku) to identify concepts touched by this plan:
   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement and skip if subagent support is unavailable. The audit can
        proceed without doc grounding at reduced confidence. -->
   > [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
     subagent_type="doc-fetcher",
     description="Doc context for plan audit <slug>",
     prompt="query: which concepts cover <plan files and symbols>?\nrepo_root: <abs path>\ndepth: summary"
   )
   ```
   Use the returned concept slugs to retrieve the appropriate `docs/llm/<concept>.json` files as plan-grounding validation guidelines.

---

## Phase 1 — Reality Check (Reference Verification)

**Heartbeat at phase boundary (before phase work begins):**
```bash
HB_RC=0
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
  --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
  --command /z-audit-plan || HB_RC=$?
if [[ $HB_RC -eq 9 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
    "$(printf '{"slug":"%s","run_id":"%s","gate":"phase1_start"}' "$Z_HARNESS_SLUG" "$RUN")"
  # Lost-claim gate: warn user prominently. Offer abort (default) / continue-uncoordinated.
  # Interactive -> AskUserQuestion: "Another session took over this slug. Abort (default) or continue-uncoordinated (you and the peer may clobber each other)?".
  # Unattended (Z_HARNESS_NO_ASK) -> abort unless Z_HARNESS_CLAIM_OVERRIDE=1 (continue-uncoordinated).
  # On abort: release BEFORE deregister (per invariant); per-resource gating.
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-audit-plan || true
  if [[ "${REG_RC:-1}" -eq 0 ]]; then
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted || true
  fi
  exit 1
fi
```

Parse `$BASE/SPEC.md` and `$BASE/TASKS.md` to identify factual claims made about the active codebase. Scrutinize these references:

1. **Entities to verify:**
   - **Files & Directories:** Ensure paths described as existing or as preconditions actually exist.
   - **Symbols:** Grep for declarations of functions, methods, classes, variables, or types mentioned in the spec.
   - **Configs:** Verify the existence of specific configuration files or specific JSON/YAML/TOML keys referenced in the plan.
   - **Database Elements:** Ensure tables or columns referenced as active database preconditions exist in schema declarations, models, or migration files.
   - **CLI Flags:** Ensure referenced CLI arguments are declared in their respective option-parsing functions.
2. **Bucket division:**
   - **MUST EXIST NOW:** Entities described as present. Run `Read`/`Grep`/`Glob` to verify their existence and declarations exactly.
   - **WILL BE CREATED:** Newly proposed files. Verify that their proposed paths do not clash with existing files in the codebase.
3. **Drift & Hallucination detection:**
   - Flag similar-but-different naming (e.g. `user_id` vs `uid`, or double-suffixes).
   - Flag contract mismatches between proposed specifications and current codebase structures.
   - Flag dependency order violations (e.g., plan relies on a database table that is not created in this or any prior completed plan).

Checkpoint: Write results to `$BASE/archive/$RUN/phase1-reality.md`.

---

## Phase 2 — Best Practices & Design Audit

**Heartbeat at phase boundary (before phase work begins):**
```bash
HB_RC=0
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
  --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
  --command /z-audit-plan || HB_RC=$?
if [[ $HB_RC -eq 9 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
    "$(printf '{"slug":"%s","run_id":"%s","gate":"phase2_start"}' "$Z_HARNESS_SLUG" "$RUN")"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-audit-plan || true
  if [[ "${REG_RC:-1}" -eq 0 ]]; then
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted || true
  fi
  exit 1
fi
```

Audit the plan's architectural, design, and styling choices against best engineering practices:

1. **Standards verification:**
   - **KISS & DRY:** Check for unnecessary complexity, premature abstractions, or code duplication planned across tasks.
   - **SOLID:** Ensure clean single-responsibility components and clear interface boundaries.
   - **Style:** Align proposed changes with `STYLE.md` rules (if it exists).
2. **Defensive Bloat & Over-engineering:**
   - Check if error handling is overly defensive, or if unnecessary abstractions are introduced where simple code would suffice.
3. **Performance & Resources:**
   - Detect potential N+1 database queries, excessive object allocations in loops, locking/deadlock risks, or poor Big-O complexity in algorithms.
4. **Security & Validation:**
   - Ensure all input validation boundaries, sanitization strategies, authentication/authorization checks, and data exposure patterns are secure.

Checkpoint: Write results to `$BASE/archive/$RUN/phase2-design.md`.

---

## Phase 2.5 — Pre-review cycle (opt-in)

**Opt-in gate:** Only runs if `Z_HARNESS_PRE_REVIEW` is set to `1` (env var). Check at phase start:

```bash
if [ "${Z_HARNESS_PRE_REVIEW:-0}" != "1" ]; then
  echo "Pre-review cycle skipped (Z_HARNESS_PRE_REVIEW != 1)"
  # Jump to Phase 3
  return 0
fi
```

When enabled, spawn **3 pre-reviewers in parallel** to do a fast first-pass scan on plan artifacts before the expensive adversarial consultants.

> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).

```
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="pre-reviewer",
  description="Pre-review 1 — reality check (Flash) for <slug>",
  prompt="MODE: plan-audit
slug: <slug>
run_id: <RUN>
Kernel path: <KERNEL_PATH>

SPEC.md: $BASE/SPEC.md
PLAN.md: $BASE/PLAN.md
TASKS.md: $BASE/TASKS.md
phase1_reality: $BASE/archive/$RUN/phase1-reality.md
phase2_design: $BASE/archive/$RUN/phase2-design.md

Focus: REALITY CHECK — reference errors in SPEC.md/PLAN.md/TASKS.md. Files that don't exist, symbols that are wrong, config paths that are hallucinated, naming drift, dependency order violations. Compare plan claims against the actual codebase. Be fast and cheap — surface only clear blockers and majors."
)
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="pre-reviewer",
  description="Pre-review 2 — design & style audit (Flash) for <slug>",
  prompt="MODE: plan-audit
slug: <slug>
run_id: <RUN>
Kernel path: <KERNEL_PATH>

SPEC.md: $BASE/SPEC.md
PLAN.md: $BASE/PLAN.md
TASKS.md: $BASE/TASKS.md
phase1_reality: $BASE/archive/$RUN/phase1-reality.md
phase2_design: $BASE/archive/$RUN/phase2-design.md

Focus: DESIGN & STYLE — DRY/KISS/SOLID violations, premature abstractions, over-engineering, STYLE.md drift, defensive bloat, security concerns in the plan artifacts. Do NOT check reality references (that's pre-review 1's job). Be fast and cheap — surface only clear blockers and majors."
)
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="pre-reviewer",
  description="Pre-review 3 — logic & completeness (Flash) for <slug>",
  prompt="MODE: plan-audit
slug: <slug>
run_id: <RUN>
Kernel path: <KERNEL_PATH>

SPEC.md: $BASE/SPEC.md
PLAN.md: $BASE/PLAN.md
TASKS.md: $BASE/TASKS.md
phase1_reality: $BASE/archive/$RUN/phase1-reality.md
phase2_design: $BASE/archive/$RUN/phase2-design.md

Focus: LOGIC & COMPLETENESS — logic gaps in the plan, missing edge cases in acceptance criteria, task ordering issues, dependency problems, incomplete spec coverage, unstated assumptions that should be made explicit. Do NOT check reality references or design style (those are pre-review 1/2's jobs). Be fast and cheap — surface only clear blockers and majors."
)
```

**Collecting pre-review findings:** After all three return, read their outputs. Write a consolidated pre-review summary to `$BASE/archive/$RUN/pre-review.md`:

```markdown
# Pre-review summary — <slug>
Run: <RUN>

## Pre-review 1 — reality check
<verbatim findings from pre-reviewer 1, or "CLEAN">

## Pre-review 2 — design & style
<verbatim findings from pre-reviewer 2, or "CLEAN">

## Pre-review 3 — logic & completeness
<verbatim findings from pre-reviewer 3, or "CLEAN">
```

**Feeding into Phase 3:** The consolidated `$BASE/archive/$RUN/pre-review.md` path is added as a context item in the Phase 3 adversarial consultant prompts. Each consultant's prompt gains a section:

```
Pre-review findings (3 × DeepSeek V4 Flash fast scan):
<contents of $BASE/archive/$RUN/pre-review.md>

These are cheap pre-screener findings — validate them critically before accepting. The real adversarial review is your own analysis.
```

---

## Phase 3 — Adversarial Cross-LLM Review

**Heartbeat at phase boundary (before phase work begins):**
```bash
HB_RC=0
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
  --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
  --command /z-audit-plan || HB_RC=$?
if [[ $HB_RC -eq 9 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
    "$(printf '{"slug":"%s","run_id":"%s","gate":"phase3_start"}' "$Z_HARNESS_SLUG" "$RUN")"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-audit-plan || true
  if [[ "${REG_RC:-1}" -eq 0 ]]; then
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted || true
  fi
  exit 1
fi
```

Spawn two consultants in parallel to review the plan's artifacts (`SPEC.md`, `PLAN.md`, `TASKS.md`) and Phase 1/2 audit notes with a highly critical, adversarial mindset:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     > [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
     cannot complete without subagent support; document the gap and proceed
     to Phase 4 without adversarial review input. -->
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="consultant-primary",
  description="Adversarial plan audit review (Gemini) for <slug>",
  prompt="MODE: plan-audit-review\n\nSPEC:\n<SPEC.md>\n\nPLAN:\n<PLAN.md>\n\nTASKS:\n<TASKS.md>\n\nReality Check Notes:\n<phase1-reality.md>\n\nDesign Audit Notes:\n<phase2-design.md>\n\nAct as a highly critical, adversarial 'Senior Nitpicker'. Find logic flaws, race conditions, edge cases, missing tests in acceptance criteria, security concerns, style drift, or over-engineering in the plan. Report findings with severity (BLOCKER / MAJOR / MINOR), location, and recommendations."
)
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="consultant-secondary",
  description="Adversarial plan audit review (Codex) for <slug>",
  prompt="MODE: plan-audit-review\n\n<same prompt>"
)
```

Both consultants return structured findings. Transcripts are archived under `$BASE/archive/$RUN/transcripts/`.

---

## Phase 4 — Merge and Synthesize Findings

**Heartbeat at phase boundary (before phase work begins):**
```bash
HB_RC=0
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
  --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
  --command /z-audit-plan || HB_RC=$?
if [[ $HB_RC -eq 9 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
    "$(printf '{"slug":"%s","run_id":"%s","gate":"phase4_start"}' "$Z_HARNESS_SLUG" "$RUN")"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-audit-plan || true
  if [[ "${REG_RC:-1}" -eq 0 ]]; then
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted || true
  fi
  exit 1
fi
```

1. **Aggregation:**
   Merge findings from Reality Check, Design Audit, and both adversarial consultant reviews.
2. **One-Reason-This-Might-Be-Wrong Gate:**
   For every finding, write a brief statement detailing "one reason this finding might be wrong, irrelevant, or pedantic". If the pushback is valid:
   - Drop the finding from the final report.
   - Or demote its severity.
3. **Write final report:**
   Write the unified plan-audit report to `$BASE/PLAN_AUDIT_REPORT.md` (and save a copy in `$BASE/archive/$RUN/PLAN_AUDIT_REPORT.md`):
   ```markdown
   # Plan Audit Report — <slug>
   
   - **Date (UTC):** YYYY-MM-DDTHH:MMZ
   - **Slug:** <slug>
   - **Run ID:** <RUN>
   
   ## Summary
   - <Actionable high-level takeaways>
   
   ## reality-check Reality Check findings
   <Stale references, naming drift, clashing paths>
   
   ## design-check Design & Style findings
   <SOLID/DRY violations, style drift, over-engineering, performance, security>
   
   ## adversarial Adversarial Consult findings
   <Logic gaps, race conditions, unhandled edge cases, missing tests in acceptance>
   
   ## Consensus vs Disagreement
   - consensus: <findings flagged by multiple layers>
   - outlier: <findings worth manual scrutiny>
   
   ## Actionable Recommendations
   <Categorized recommendations with recommended actions>
   ```

---

## Phase 5 — User Gate & Action

**Heartbeat before Phase 5 audit gate (load-bearing — extends TTL before the AskUserQuestion wait):**
```bash
HB_RC=0
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
  --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
  --command /z-audit-plan || HB_RC=$?
if [[ $HB_RC -eq 9 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
    "$(printf '{"slug":"%s","run_id":"%s","gate":"audit_gate"}' "$Z_HARNESS_SLUG" "$RUN")"
  # Lost-claim gate: Interactive -> AskUserQuestion abort (default) / continue-uncoordinated.
  # Unattended (Z_HARNESS_NO_ASK) -> abort. Release BEFORE deregister (per invariant).
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-audit-plan || true
  if [[ "${REG_RC:-1}" -eq 0 ]]; then
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted || true
  fi
  exit 1
fi
```

1. **Resolver pre-check — run before invoking `AskUserQuestion`:**

   ```bash
   # Capture exit code separately — do NOT silence stderr
   RESOLVED="$(python3 scripts/config.py resolve-question workflow.audit_to_amend)"
   RESOLVE_EXIT=$?

   if [[ $RESOLVE_EXIT -ne 0 ]]; then
     # Exit codes: 2=bad invocation, 3=unknown question_id, 4=I/O error.
     # In all error cases, fall through to ask the user normally — never silently skip.
     echo "resolve-question failed (exit $RESOLVE_EXIT); falling back to ask" >&2
     RESULT="ask"; DEFAULT=""; SOURCE="error"
   else
     RESULT="$(echo "$RESOLVED" | jq -r .result)"
     DEFAULT="$(echo "$RESOLVED" | jq -r .default)"
     SOURCE="$(echo "$RESOLVED" | jq -r .source)"
   fi
   ```

   Branch on `$RESULT`:

   - **`skip`:** Skip the `AskUserQuestion` and proceed as if the user picked `$DEFAULT`. Set `AUDIT_GATE_CHOICE="$DEFAULT"`. Emit `askuser_skipped` event:
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" askuser_skipped \
       "$(printf '{"question_id":"workflow.audit_to_amend","source":"%s"}' "$SOURCE")"
     ```
   - **`prefill`:** Present the `AskUserQuestion` normally, pre-select `$DEFAULT` as the recommended option (append label suffix: ` (Recommended — your preference)`).
   - **`ask`:** Present the `AskUserQuestion` normally. If `$SOURCE == "conflict"`, add to the question header text: `(Note: config says <X>, memory says <Y> — your answer below will be offered as a conflict-resolution write target.)` After the user picks an answer, if that answer differs from both config and memory values, surface a one-shot follow-up `AskUserQuestion`: "Record your answer as the new preference? (config / memory:very_strong / memory:strong / no — keep both stored, ask again next time)". Caller writes to config or dispatches `/z-suggest-memory` accordingly.
   - **`halt`:** Emit `audit_halt` event, then execute **Run Brief — halt finalize** (below) with reason `no_ask_blocked on workflow.audit_to_amend` — do NOT invoke `AskUserQuestion`, step 2 success finalize, or Phase 9:
     ```bash
     if [[ "$RESULT" == "halt" ]]; then
       bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" audit_halt \
         "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.audit_to_amend","rule_id":"no_ask_halt"}')"
       echo "halt: no_ask_blocked on workflow.audit_to_amend" >&2
     fi
     ```
     **Stop here when `$RESULT` is `halt`.** Jump to **Run Brief — halt finalize** below (substitute `<reason>`), then `exit 0` — do not fall through to the AskUserQuestion gate or step 2 below.

   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the audit
        gate (Amend Plan / Proceed as-is / Reject & Re-plan) via their native
        channel when resolver result is prefill or ask. Silent omission is forbidden. -->
   **Ask user via `AskUserQuestion`** when resolver result is `prefill` or `ask` only — skip when `$RESULT` is `halt` or `skip`. Store the chosen option label verbatim in `AUDIT_GATE_CHOICE`:
   - **Amend Plan (Run z-amend):** Trigger interactive plan amendment to address findings.
   - **Proceed as-is:** Acknowledge findings as acceptable tradeoffs and start implementation.
   - **Reject & Re-plan:** Discard current plan artifacts and rerun `/z-plan`.
2. **Run Brief finalize (before `plan_audit_end`).** Set outcome/next from audit counts and the resolved user gate choice (`$AUDIT_GATE_CHOICE`). Chat render replaces ad-hoc notify/present prose.

   ```bash
   CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
   export RUN_BRIEF_PROFILE=full
   export RUN_BRIEF_ARTIFACT="$BASE/PLAN_AUDIT_REPORT.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS=""
   RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
   RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"

   case "${AUDIT_GATE_CHOICE:-Proceed as-is}" in
     "Amend Plan (Run z-amend)"|*amend*)
       _RB_NEXT_CMD="/z-amend"; _RB_NEXT_LABEL="Amend plan via /z-amend" ;;
     "Reject & Re-plan"|*re-plan*|*replan*)
       _RB_NEXT_CMD="/z-plan"; _RB_NEXT_LABEL="Re-plan via /z-plan" ;;
     *)
       _RB_NEXT_CMD="/z-implement-all"; _RB_NEXT_LABEL="Proceed to /z-implement-all" ;;
   esac

   bash "$RB_SH" set-section --run "$RUN" --section outcome \
     --value "Plan audit: ${N_FINDINGS} findings (${N_BLOCKERS} blockers, ${N_MAJORS} majors); gate: ${AUDIT_GATE_CHOICE:-Proceed as-is}"
   bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<JSON
   {"label": "${_RB_NEXT_LABEL}", "command": "${_RB_NEXT_CMD}"}
   JSON

   # Pre-seed approach when PLAN_AUDIT_REPORT.md is prose-only (no extractable list bullets)
   if [[ -f "$RUN_BRIEF_ARTIFACT" ]]; then
     _RB_APPROACH_N="$(python3 -c '
   import importlib.util, sys
   spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
   mod = importlib.util.module_from_spec(spec)
   spec.loader.exec_module(mod)
   print(len(mod.extract_approach_bullets(sys.argv[2])))
   ' "$RB_PY" "$RUN_BRIEF_ARTIFACT")"
     if [[ "$_RB_APPROACH_N" -gt 0 ]]; then
       bash "$RB_SH" set-section --run "$RUN" --section approach --file "$RUN_BRIEF_ARTIFACT" || true
     else
       _RB_SEED="$CURRENT_ARCHIVE_DIR/run-brief-approach-seed.md"
       printf '%s\n' \
         "- Reality-check references against the codebase" \
         "- Design and style audit against best practices" \
         "- Adversarial cross-LLM review of plan artifacts" \
         > "$_RB_SEED"
       bash "$RB_SH" set-section --run "$RUN" --section approach --file "$_RB_SEED" || true
     fi
   fi
   bash "$RB_SH" set-section --run "$RUN" --section status --value "complete"
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

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` if still empty:

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

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

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

   3. **Log run end:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_end \
     "$(printf '{"status":"complete","findings":%d,"blockers":%d,"majors":%d}' "$N_FINDINGS" "$N_BLOCKERS" "$N_MAJORS")"
   ```

## Run Brief — halt finalize

Before exit on any halt after `run-brief.sh init` when `PLAN_AUDIT_REPORT.md` is missing or the run aborts early. Substitute `<reason>` in the outcome line. Fragment auto-downgrades to **lite** when the report file is absent.

```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/PLAN_AUDIT_REPORT.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Review plan audit status and retry", "command": null}
JSON
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

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` if still empty:

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

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

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
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_end \
  "$(printf '{"status":"halted","findings":%d,"blockers":%d,"majors":%d}' "${N_FINDINGS:-0}" "${N_BLOCKERS:-0}" "${N_MAJORS:-0}")"
# Halt-finalize teardown: release BEFORE deregister; per-resource gating.
if [[ "${CLAIM_RC:-1}" -eq 0 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-audit-plan || true
fi
if [[ "${REG_RC:-1}" -eq 0 ]]; then
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted || true
fi
exit 0
```

---

---

## Phase 9 — Elevation Proposer

After the user gate in Phase 5 resolves, run the preference elevation check:

```bash
PROPOSE_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/propose-prefs.py" --check z-audit-plan 2>/dev/null)"
```

If `$PROPOSE_OUT` is non-empty, parse it as JSON and surface a one-shot preference proposal:

```python
import json
proposal = json.loads(PROPOSE_OUT)
qid = proposal["question_id"]
val = proposal["proposed_value"]
n   = len(proposal["evidence"])
scope_rec = proposal["scope_recommendation"]
```

Emit `proposal_surfaced`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_surfaced \
  "$(python3 -c '
import json, sys
print(json.dumps({"question_id": sys.argv[1], "proposed_value": sys.argv[2], "n_evidence": int(sys.argv[3]), "scope_recommendation": sys.argv[4]}))
' "$qid" "$val" "$n" "$scope_rec")"
```

> [pi] No native tool — handle inline by asking the user / tracking state yourself (see CAPABILITIES.md).
```bash
HB_RC=0
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
  --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
  --command /z-audit-plan || HB_RC=$?
if [[ $HB_RC -eq 9 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
    "$(printf '{"slug":"%s","run_id":"%s","gate":"phase9_elevation"}' "$Z_HARNESS_SLUG" "$RUN")"
  # Lost-claim gate at Phase 9 elevation: skip elevation proposal and fall through to teardown.
  # Release BEFORE deregister (per invariant); run is effectively complete; Phase 9 is optional.
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-audit-plan || true
  if [[ "${REG_RC:-1}" -eq 0 ]]; then
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted || true
  fi
  exit 0
fi
```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the preference
     elevation proposal question via their native channel and accept a reply.
     Silent omission is forbidden. -->
Present a single `AskUserQuestion`:

> "You've done `<cmd_a> → z-amend` **N times** — add `<val>` as your preference for `<qid>`?"
>
> Options:
> - **config** — write to project config (or global if `scope_recommendation=global`)
> - **memory:very_strong** — store as a very-strong routing-preference memory entry
> - **memory:strong** — store as a strong routing-preference memory entry
> - **no** — suppress this prompt for 30 days

Branch on the user's choice:

**`config` branch:**
```bash
SCOPE_FLAG="--scope=project"
[ "$scope_rec" = "global" ] && SCOPE_FLAG="--scope=global"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" set workflow.audit_to_amend amend $SCOPE_FLAG
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_accepted \
  "$(printf '{"question_id":"%s","via":"config","scope":"%s"}' "$qid" "$scope_rec")"
```

**`memory:very_strong` or `memory:strong` branch:**

Dispatch `/z-suggest-memory` with `--kind routing-preference`:
```
/z-suggest-memory --kind routing-preference \
  --question-id <qid> \
  --value <val> \
  --strength <very_strong|strong> \
  --scope <scope_recommendation>
```

Then emit:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_accepted \
  "$(printf '{"question_id":"%s","via":"memory","strength":"%s","scope":"%s"}' "$qid" "$strength" "$scope_rec")"
```

**`no` branch:**

Write suppression entry with 30-day expiry:
```python
import json, os, time
from pathlib import Path
suppress_path = Path(".z-harness") / ".propose-suppress"
suppress_path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if suppress_path.exists():
    try:
        data = json.loads(suppress_path.read_text())
    except (json.JSONDecodeError, OSError):
        data = {}
expiry = time.time() + 30 * 86400
data[qid] = str(expiry)
suppress_path.write_text(json.dumps(data))
```

Then emit:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_rejected \
  "$(printf '{"question_id":"%s","suppressed_until_epoch":"%s"}' "$qid" "$expiry")"
```

If `$PROPOSE_OUT` is empty, skip this phase entirely — no question is asked.

**Normal-end teardown (after Phase 9 or when Phase 9 is skipped — release BEFORE deregister; per-resource gating):**
```bash
# release only if claim was acquired (CLAIM_RC==0 means acquired or self-reentry or disabled)
if [[ "${CLAIM_RC:-1}" -eq 0 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-audit-plan || true
fi
# deregister only if register succeeded
if [[ "${REG_RC:-1}" -eq 0 ]]; then
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status complete || true
fi
```

---

## Operating Principles

- **Rigorous Verification:** Validate all facts before starting the implementation.
- **Push Back on Reviews:** Apply the "one reason it might be wrong" check to keep reports high-signal.
- **Strictly Read-Only:** Never modify the codebase during the audit.
- **Format Consistency:** No emojis, professional headers, clean Markdown structures.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
| `ask_user` | yes | Phase 0 multiple-candidates slug selection; Phase 0 claim contention/takeover gate (proceed / abort) and register-failure gate (proceed without coordination / abort); Phases 1–5 lost-claim gate (abort default / continue-uncoordinated) on heartbeat exit 9; Phase 5 audit gate (Amend Plan / Proceed as-is / Reject & Re-plan); Phase 9 preference elevation proposal |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
