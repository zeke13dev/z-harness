---
name: z-plan
description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce INTENT.md + initial TASKS.md (or SPEC.md / PLAN.md / TASKS.md in --full legacy mode).
argument-hint: "<feature or task description> [--full] [--quick] [--standard] [--deep]"
audience: user
driver_features_required: [subagent, ask_user]
---

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What task should I plan?" to the user via their native channel and accept
     a text reply. Silent omission is forbidden. -->
**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-execute`.

## Intent-compiler phase spine

The `/z-plan` default path is now an **intent compiler**: conversation → sharpened problem → optional ideated framing → intent contract → execution DAG. Full SDD remains available only as an explicit compatibility path (`--full`, existing `SPEC.md`, or `workflow.planning_mode=full`); it is no longer the default user-facing model.

Safety mechanics still run where they protect the workflow: slug/collision checks, claim/register, docs/precontext freshness, deterministic artifact inventory, route preflight, the explicit mode gate, and the hard pre-subagent cost gate are preserved. They support the flow below; they do not replace the conversational intent contract.

Canonical intent-compiler flow:

1. **Setup + safety gates** — derive slug, claim/register, scan precontext, run deterministic artifact inventory, run route preflight, choose intent-vs-full compatibility mode, then run the hard pre-subagent cost gate.
2. **Sharpen always first** — run the shared `/z-sharpen` inline contract or consume a fresh `GRILL.md`; clarify goal, motivation, constraints, non-goals, acceptance criteria, and uncertainty before planning.
3. **Brainstorm ask gate** — ask whether the user wants `/z-brainstorm`; recommend it when material alternatives remain, but never auto-dispatch it.
4. **Optional brainstorm** — if the user opts in, consume the selected `BRAINSTORM.md` framing; if the user skips, record the explicit skip and continue.
5. **Watcher checkpoint seam** — after sharpen/optional-brainstorm artifacts are stable, evaluate the shared `check-compaction.sh` / `write-clear-checkpoint.sh` seam before entering high-context planning.
6. **Conversational plan + `INTENT.md` iterations** — restate the sharpened problem/framing, ground only the missing source facts, draft `INTENT.md`, and iterate with the user 1–2 times.
7. **LLM concern flags + optional audit-plan ask** — before final read-through, flag concerns/decisions/assumptions, then ask whether to fold in a `/z-audit-plan` scan.
8. **Final user approval** — the orchestrator renders the full plan brief in prose (problem, approach, decisions with tradeoffs, shortcuts, readthrough flags inline, acceptance criteria), then the user chooses approve, amend, grill the draft, route back to sharpen/brainstorm, or stop — at a single gate.
9. **Execution strategy generation** — produce `TASKS.md`, task-to-intent mapping, safe parallel batches, serial blockers, review gates, checkpoint cadence, and workstream/handoff metadata.
10. **Watcher checkpoint seam** — after execution strategy and handoff artifacts are stable, evaluate the shared checkpoint seam before `/z-execute`.
11. **Fast reviewed `/z-execute`** — execute fresh from `INTENT.md`, flags, audit notes, task-to-intent mapping, and execution strategy; keep review gates and stop for new intent decisions.

Amend/resume routing remains phase-specific: scope or goal changes resume at **Sharpen / Phase 0**, framing changes resume at **Brainstorm ask / optional brainstorm**, primary artifact wording changes resume at **`INTENT.md` iteration**, and task decomposition changes resume at **Execution strategy**.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names across both new and legacy plan layouts. If a matching slug dir is found:
   - **Precontext-only slug dir** (only `MAP.md`, `BRAINSTORM.md`, `RESEARCH.md`, and/or `GRILL.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug-collision
        confirmation question via their native channel. Silent omission is forbidden. -->
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): **collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug. This collision check runs UNCONDITIONALLY and is never bypassed by the resolver below.**

   After the collision check passes (no collision found, or the user confirmed a new slug), apply the soft non-obvious-slug confirmation gate:

   ```bash
   # Only reached after collision check has already passed.
   RESOLVED="$(python3 scripts/config.py resolve-question workflow.slug_confirm)"
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
   - `skip`: accept the derived slug silently — no AskUserQuestion. Emit `askuser_skipped` event with `{question_id: "workflow.slug_confirm", source: "$SOURCE"}`.
   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must present the slug
        recommendation via their native channel when result is "prefill" or "ask". -->
   - `prefill`: present the AskUserQuestion normally, pre-select the derived slug as the recommended option (label suffix: ` (Recommended — your preference)`).
   - `ask`: if the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion` normally. If `$SOURCE == "conflict"`, add to the question header: `(Note: config says <X>, memory says <Y> — your answer below will be offered as a conflict-resolution write target.)` After the user picks an answer that differs from both stored values, surface a one-shot follow-up: "Record your answer as the new preference? (config / memory:very_strong / memory:strong / no)".
   - `halt`: emit `plan_halt` event and exit cleanly — do NOT invoke `AskUserQuestion`:
     ```bash
     if [[ "$RESULT" == "halt" ]]; then
       bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "${RUN:-z-plan}" plan_halt \
         "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.slug_confirm","rule_id":"no_ask_halt"}')"
       echo "halt: no_ask_blocked on workflow.slug_confirm" >&2
       exit 0
     fi
     ```

   **Invariant:** the collision check above is a hard safety prerequisite that runs unconditionally regardless of resolver outcome. The resolver only governs the soft non-obvious-slug confirmation gate.
2. **Preflight ceremony (single call).** `scripts/z-preflight.sh` owns resolve/session-id/RUN-stamp/claim/register/run-brief-init/run_start/kernel-resolve, in that fixed order (contract: script header; LEDGER T005). `/z-plan` is a WRITE command — it claims, so it never passes `--no-claim`:
   ```bash
   PREFLIGHT_OUT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-preflight.sh" \
     --command /z-plan --slug "$Z_HARNESS_SLUG" \
     --intent "<task description from $ARGUMENTS — max 240 chars; not the command name alone>")"
   PREFLIGHT_RC=$?
   [ "$PREFLIGHT_RC" -eq 0 ] && eval "$PREFLIGHT_OUT"
   ```
   On success (`PREFLIGHT_RC==0`), `RUN`, `Z_HARNESS_RUN`, `Z_HARNESS_PLAN_DIR`, `CURRENT_ARCHIVE_DIR`, `Z_HARNESS_SESSION_ID`, `CLAIM_HELD`, `REG_RC`, and `KERNEL_PATH` are all exported (script header is the source of truth for the exact contract). When `KERNEL_PATH` is non-empty, inject `kernel_path: <KERNEL_PATH>` as a line in the `Agent(prompt=...)` of every consultant-primary/consultant-secondary dispatch this run; omit the line when empty (the agent's static fallback self-resolves). Also resolve config and log provider resolution once, guarded against re-emission:
   ```bash
   eval "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" export-env)"
   if [ ! -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
     touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
   fi
   ```

   **Contention (`PREFLIGHT_RC==10`, a live peer holds the slug).** Nothing was created — the script exits before its claim step completes any write. Standard menu (SKILL-STYLE.md §2):
   <!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface this contention question
        via their native channel and await a response. Silent omission is forbidden. -->
   - **Interactive** (not `Z_HARNESS_NO_ASK`): `AskUserQuestion` — **proceed anyway / abort / use a new slug**.
     - `proceed anyway` → re-run the SAME preflight call with `--no-claim` appended (still resolves/registers/run-brief-inits/logs run_start/resolves kernel — only the lock step is skipped) and continue uncoordinated; log a `plan_claim_override` event.
     - `abort` → exit 1. (Nothing was ever created.)
     - `use a new slug` → re-derive a slug **once** (loop-guard: at most 1 re-derive; if the new slug also contends, abort) and re-run the original (claiming) preflight call on it; branch on the new `PREFLIGHT_RC` normally — no further re-derive.
   - **Unattended**: abort (`exit 1`) unless `Z_HARNESS_CLAIM_OVERRIDE=1` → re-run with `--no-claim` (log override).

   **Corrupt lock (`PREFLIGHT_RC==11`).** Same shape as contention; manual-cleanup hint (`rm <claims_dir>/<slug>.lock*` then retry).
   <!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface this corrupt-lock
        question via their native channel and await a response. Default is abort.
        Silent omission is forbidden. -->
   - **Interactive**: `AskUserQuestion` — **abort (default)** / **proceed UNCOORDINATED** (clearly labeled: you and a peer may clobber each other's artifacts).
     - `abort` → exit 1.
     - `proceed UNCOORDINATED` → re-run with `--no-claim`; log a `plan_claim_corrupt_proceed` event.
   - **Unattended**: abort unless `Z_HARNESS_CLAIM_OVERRIDE=1` → proceed uncoordinated (`--no-claim`).

   **Note — stale-takeover is resolved inside the wrapper, not asked here.** When the prior holder's TTL has expired, `plan-claim.sh acquire` (called by z-preflight.sh) takes the lock over silently: `CLAIM_HELD=1`, no ask, a `NOTE:` line on stderr only (see the script header rationale: refusing the takeover would just release it right back for no benefit). This supersedes the pre-wrapper design where stale-takeover was its own interactive gate.

   **Register failure (`REG_RC != 0` on a `PREFLIGHT_RC==0` success).** Graduated failure, not a hard stop — z-preflight.sh already emitted the warning to stderr.
   <!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface this registry-failure
        question via their native channel and await a response. Silent omission is forbidden. -->
   - **Interactive**: `AskUserQuestion` — *proceed without coordination* / *abort*.
     - **proceed** → continue; skip heartbeats and deregister later (no record to update). The claim is still held.
     - **abort** → push-notify, then halt through the funnel — z-preflight.sh's run-brief-init step already ran regardless of register's outcome, so the same `RB_HALT_REASON` + fragment + `z-teardown.sh` shape applies (teardown's deregister step is a harmless no-op when no record exists; its release step still frees the claim we hold):
       ```bash
       RB_HALT_REASON="active-plan registry register failed"
       # include: _fragments/run-brief-halt-finalize-plan.md
       bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
         --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
       exit 1
       ```
   - **Unattended**: proceed without coordination (log prominently) unless `Z_HARNESS_STRICT_OVERLAP=1` → run the same abort funnel above and halt.

   **Teardown funnel (single source of truth for the entire run).** Every controlled exit after a successful preflight funnels through one call — `scripts/z-teardown.sh --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status complete|aborted` — never a bespoke release/deregister sequence (SKILL-STYLE.md §2). On any halt: set `RB_HALT_REASON`, include `_fragments/run-brief-halt-finalize-plan.md` (sets outcome/next, finalizes/renders/requires the brief), then call teardown with `--status aborted`. On normal completion (Phase 9), call it with `--status complete`. Teardown's release and deregister steps are both best-effort no-ops when nothing was ever held/registered, so the same call is safe on every halt path regardless of how far setup got. The one exception: a checkpoint-seam PAUSE is not an exit — no teardown; the next invocation resumes.
6. **Plan-start awareness read (after claim + register; non-fatal read-only).** After a successful claim and register, read the lockless registry to surface concurrent peers as an FYI — never a hard gate (Invariant 1):
   ```bash
   AWARENESS_JSON="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" list --json 2>/dev/null)"
   AWARENESS_RC=$?
   if [[ "$AWARENESS_RC" -ne 0 ]]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" registry_error \
       "$(printf '{"op":"awareness_read_failed","rc":%d}' "$AWARENESS_RC")"
   else
     # Render any record whose session_id != $Z_HARNESS_SESSION_ID as a one-line advisory.
     # Example: "Other active sessions: 20240101T120000Z-other-slug — /z-plan on other-slug (heartbeat 5s)"
     # This is purely informational — never blocks or gates a subsequent phase.
     echo "$AWARENESS_JSON" | python3 -c "
import json, sys, os
records = json.load(sys.stdin)
my_sid = os.environ.get('Z_HARNESS_SESSION_ID', '')
peers = [r for r in records if r.get('session_id') != my_sid]
if peers:
    print('Other active sessions:')
    for p in peers:
        hb = p.get('last_heartbeat', '')
        print(f\"  {p.get('run_id','?')} — {p.get('command','?')} on {p.get('slug','?')} (heartbeat {hb})\")
" 2>/dev/null || true
   fi
   ```
7. Notification policy is resolved from config via the `export-env` step above. See `docs/human/config.md` for knob details (`notify.level`).
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
   ```bash
   if [[ -f "docs/llm/INDEX.json" ]]; then
     DOCS_LLM_INDEX_EXISTS=1
   else
     DOCS_LLM_INDEX_EXISTS=0
   fi
   export DOCS_LLM_INDEX_EXISTS
   ```
9. **Docs-freshness scan (inline, no gate yet).** Initialize signals before scanning: `docs_stale=false`, `research_stale=false`, `map_stale=false`, `explore_stale=false`; `stale_concepts_list=[]`; `stale_research_citations=[]`; `stale_map_citations=[]`; `stale_explore_citations=[]`. If `docs/llm/INDEX.json` exists, compute staleness across all its entries. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is the value from `config.py get docs.staleness_threshold` (default `20` — meaning 20 percent). Record signal: `docs_stale = (stale_pct >= threshold)`. Also record `stale_concepts_list` (list of stale concept slugs) for display. **Do not present any AskUserQuestion here** — the gate fires below in step 10c after all three signals are collected.
10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `MAP.md`, `BRAINSTORM.md`, `RESEARCH.md`, `GRILL.md`, and `EXPLORE.md`.

    **RESEARCH.md artifact_kind dispatch:** If `RESEARCH.md` exists, read its frontmatter `artifact_kind` and `status` fields first to determine the precontext mode:

    - **`artifact_kind: approach_synthesis` + `status: complete`** → **one-way gate active.** RESEARCH.md is canonical precontext. Skip MAP.md + BRAINSTORM.md injection entirely. Phase 1 uses matrix-based skip rules (see Phase 1 — RESEARCH.md one-way gate shortcut).
    - **`artifact_kind: map`** (legacy old-RESEARCH.md not yet renamed) → treat as a MAP.md artifact: apply freshness check (same regex/mtime logic as MAP.md below), then proceed with component-file injection (MAP.md + BRAINSTORM.md mode). Log `legacy_map_artifact_detected`.
    - **No `artifact_kind` field** → treat as legacy MAP.md artifact per above (component-file injection). Log `legacy_map_artifact_detected`.
    - **`status: incomplete`** → halt. Emit `precontext_research_incomplete`. Recommend regenerating or removing the incomplete artifact before proceeding; do not recommend hidden experimental commands in prod. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `RESEARCH.md status incomplete`.

    **Freshness scan — RESEARCH.md (inline, no gate yet)** (when one-way gate is active): parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). Record signal: `research_stale = true` if any citation is stale. Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) and set `research_stale = true`. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open). **Do not present any AskUserQuestion here** — the gate fires below in step 10c.

    **Freshness scan — MAP.md (inline, no gate yet)** (when one-way gate is inactive and MAP.md exists or RESEARCH.md is treated as MAP.md): parse all file citations using the same regex `/[A-Za-z0-9_./-]+\\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\\d+(-\\d+)?)?/` and extensionless allowlist (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to the MAP.md frontmatter `generated_at`; for line-ranges, use min-line mtime. Record signal: `map_stale = true` if any citation is stale. Deleted-source detection: emit `precontext_source_deleted` and set `map_stale = true`. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open). **Do not present any AskUserQuestion here** — the gate fires below in step 10c.

    **Freshness scan — EXPLORE.md (inline, no gate yet)** (when one-way gate is inactive and EXPLORE.md exists, regardless of MAP.md presence): parse all file citations using the same regex and extensionless allowlist as MAP.md. Compare each cited path's mtime to the EXPLORE.md frontmatter `generated_at`. Record signal: `explore_stale = true` if any citation is stale. Deleted-source detection: emit `precontext_source_deleted` and set `explore_stale = true`. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open). If EXPLORE.md's `depth` frontmatter field is `quick`, note that findings are bounded and may be incomplete — inject them as supplementary only, not as authoritative terrain. **Do not present any AskUserQuestion here** — the gate fires below in step 10c.

    **GRILL.md detection** (independent of one-way gate): If `$Z_HARNESS_PLAN_DIR/GRILL.md` exists and its frontmatter `status` is `complete`, note it as a GRILL.md precontext artifact. Read its `## Sharpened problem`, `## Killed scope`, and `## Open branches` sections for injection in Phase 0 and Phase 2. GRILL.md is a problem-statement artifact, not a code-citation artifact — **no mandatory freshness gate applies.** Exception: if GRILL.md contains file citations (matched by the same regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`), apply the same freshness scan as MAP.md (mtime vs GRILL.md frontmatter `generated_at`) and fold any stale signal into `map_stale` for the 10c gate. If `status` is not `complete`, skip GRILL.md silently (treat as absent).

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the consolidated
     freshness gate covering docs / research / map / explore staleness — all signals
     merged into one AskUser call — when stale_pct >= threshold or any precontext
     citation is stale or deleted. Silent omission is forbidden. -->
    **10c. Consolidated freshness gate.** After all four scans complete (docs, RESEARCH.md, MAP.md, EXPLORE.md, GRILL.md citations if present), if `docs_stale OR research_stale OR map_stale OR explore_stale` is true:

    Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`. Build up `reason_codes` from all true signals (e.g. `["docs_stale"]`, `["research_stale"]`, `["map_stale"]`, `["explore_stale"]`, or a combination). Set `to_command` to the most specific release-safe remedy (prefer `"/z-maintain-docs"` if docs_stale; otherwise use `null` and ask the user to refresh/remove stale precontext manually; list all remedies in the route-decision.md body).

    Push-notify (guarded by notify level), then present **ONE** `AskUserQuestion` with:

    - **Header:** "One or more planning inputs are stale. Review and choose how to proceed:"
    - **Per-source bullets** for each true signal (include only bullets for signals that fired):
      - `docs`: "Docs are stale — `stale_pct`% of concepts outdated (affects: `stale_concepts_list`). Remedy: `/z-maintain-docs`."
      - `research`: "RESEARCH.md has stale or deleted citations. Remedy: refresh or remove the stale precontext artifact; experimental synthesis regeneration is dev-only."
      - `map`: "MAP.md has stale or deleted citations. Remedy: refresh or remove the stale terrain artifact; experimental terrain mapping is dev-only."
      - `explore`: "EXPLORE.md has stale or deleted citations. Remedy: refresh or remove the stale terrain artifact; the explore findings are bounded and may be incomplete."
    - **Options** (always include):
      - `re-run /z-maintain-docs` (if `docs_stale`)
      - `proceed with all stale — I accept the risk`
      - `abandon`

    If only one signal fired, the question naturally collapses to a single per-source bullet plus proceed/abandon; the `/z-maintain-docs` remedy appears only for docs staleness.

    On user choice:

    - **Re-run /z-maintain-docs** (docs staleness only): Update `route-decision.md` with the user's chosen remedy. Emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes` (built above), `signals.docs_stale_or_drifted: <docs_stale>`, `signals.research_stale: <research_stale>`, `signals.map_stale: <map_stale>`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and `user_choice: <the user's selection>`. Halt. Do not auto-invoke the remedy command. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `stale inputs — user chose docs remedy re-run`.
    - **Proceed with all stale**: Update `route-decision.md` to record "no remedy command selected — user accepted stale inputs." Emit `plan_route_decision` with `from_command: "/z-plan"`, **`to_command: null`** (omit the field or set it to `null` explicitly — `/z-stats` must be able to distinguish this from a real remedy), `route_class: "contextual"`, `reason_codes` (built above), `signals.docs_stale_or_drifted: <docs_stale>`, `signals.research_stale: <research_stale>`, `signals.map_stale: <map_stale>`, `signals.explore_stale: <explore_stale>`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and `user_choice: "proceed_with_all_stale"`. Then:
      - If `docs_stale=true`: emit a `doc_drift_acknowledged` event. Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
      - If `research_stale=true OR map_stale=true OR explore_stale=true` (regardless of `docs_stale`): emit a `precontext_freshness_acknowledged` event with `sources: ["research"]` / `["map"]` / `["explore"]` / combinations as applicable.
      - Continue to Phase 1.
    - **Abandon**: Emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: null`, `route_class: "contextual"`, `reason_codes` (built above), `signals.docs_stale_or_drifted: <docs_stale>`, `signals.research_stale: <research_stale>`, `signals.map_stale: <map_stale>`, `signals.explore_stale: <explore_stale>`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and `user_choice: "abandon"`. Halt. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `stale inputs — user abandoned`.

    If **no** signal fired, skip the gate entirely — no AskUserQuestion, no route-decision.md write.

    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist (in component-file mode, i.e. one-way gate inactive), scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research/Map found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/SPEC.md`
- `$Z_HARNESS_PLAN_DIR/PLAN.md`
- `$Z_HARNESS_PLAN_DIR/TASKS.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.

## Artifact Scout deterministic inventory (pre-gate, no Agent)

Run this hook after claim/register/awareness and docs/precontext freshness scanning, before Plan Route Check and before the hard cost gate. It is deterministic shell/Python only; it MUST NOT dispatch `artifact-scout` or any other Agent before the hard gate. The resulting inventory facts may feed deterministic route preflight and cost-shape estimates without creating a pre-gate Agent exception.

```bash
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
ARTIFACT_SCOUT_INVENTORY="$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout-inventory.json"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/artifact-scout-inventory.py" \
  --command /z-plan --slug "$Z_HARNESS_SLUG" --run-id "$RUN" \
  --repo-root "$REPO_ROOT" --plan-dir "$Z_HARNESS_PLAN_DIR" \
  --task "$ARGUMENTS" --output "$ARTIFACT_SCOUT_INVENTORY"
ARTIFACT_SCOUT_EVENT_PAYLOAD="$(python3 - "$ARTIFACT_SCOUT_INVENTORY" <<'PYEOF'
import json, sys
path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
print(json.dumps({
  "command": data.get("command"),
  "slug": data.get("slug"),
  "run_id": data.get("run_id"),
  "artifact_path": path,
  "source_status": data.get("source_status", {}),
  "mandatory_candidate_count": len(data.get("mandatory_candidates") or []),
  "historical_candidate_count": len(data.get("historical_candidates") or []),
  "active_record_count": len(data.get("active_records") or []),
  "worktree_count": len(data.get("worktrees") or []),
  "truncated": bool(data.get("truncated")),
}, separators=(",", ":")))
PYEOF
)"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" artifact_scout_inventory_complete "$ARTIFACT_SCOUT_EVENT_PAYLOAD"
```

The `artifact_scout_inventory_complete` payload MUST include `command`, `slug`, `run_id`, `artifact_path`, `source_status`, `mandatory_candidate_count`, `historical_candidate_count`, `active_record_count`, `worktree_count`, and `truncated` from the inventory JSON.

The post-gate classifier consumes the inline JSON printed by this command and archives its raw response as `$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout.md`.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear, and once more in **Phase 8.4** after `INTENT.md`/`SPEC.md`/`PLAN.md` and `TASKS.md` exist. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `asks_what_should_we_do`, `alternatives_unsettled`, `architecture_decision`, `reversibility_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `plan_validation_intent`, `question_heavy_artifacts`, `artifact_unsettled_approach`, `post_artifact_check`, and artifact existence.

**Sharpen-first invariant:** the pre-Phase-0/pre-gate invocation MUST NOT route or recommend `/z-brainstorm`. If `approach_uncertain`, `asks_what_should_we_do`, `alternatives_unsettled`, `architecture_decision`, or `reversibility_uncertain` is present before sharpen, record those signals as `brainstorm_recommendation_deferred_until_after_sharpen` and continue to Phase 0.5. Brainstorm is only offered by the post-sharpen Brainstorm ask gate, after `GRILL.md` exists.

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-plan --quick`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-fix`; if the task is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- For unknown terrain or missing citations, surface the grounding risk and ask the user to narrow/gather facts. Route multiple plausible framings with sufficient terrain to `/z-brainstorm` only in Phase 0.5 or later, never before mandatory sharpen.
- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. During the pre-gate route preflight, this is a **deferred expensive subagent**: do not invoke it before the `/z-plan` hard cost gate below. If deterministic routing cannot decide and the run still needs `/z-plan`, carry the compact signal payload forward, complete the hard cost gate, then invoke `planning-router` after a successful gate and before Phase 1 dispatch. Malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.

**Route-down shortcut surface (route-DOWN routes only).** A route is a *shortcut* only when it routes **DOWN** to a lighter command — i.e. `to_command` is `/z-plan --quick`, `/z-fix`, or `/z-debug`. Lateral or upward routes (`/z-plan-split`, `/z-brainstorm`, `/z-audit-plan`, `/z-amend`, `/z-maintain-docs`) are **not** shortcuts — they do not decline a more-robust alternative for speed — so they must NOT fire the surface. Scope this block to the route-down branch ONLY:

```bash
# Callsite 1 — route-down shortcut surface (route-DOWN routes only).
# RUN is already set/exported by Setup step 2's z-preflight.sh call.
# surface-shortcut.sh reads the RUN env var to attribute the event, so export it here.
export RUN="$RUN"
SURFACE_RC=0
case "$to_command" in
  "/z-plan --quick"|/z-fix|/z-debug)
    # Route-DOWN: declining full /z-plan for a lighter command — a genuine shortcut.
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/surface-shortcut.sh" \
      --chosen "$to_command" \
      --declined "full /z-plan" \
      --why "route signals indicate a lighter command is sufficient" || SURFACE_RC=$?
    ;;
  *)
    # Lateral/upward route — not a shortcut. Leave SURFACE_RC=0 (no-op).
    SURFACE_RC=0
    ;;
esac
```

<!-- RUNTIME-GATE: ask_user; category=shortcut; non-supporting drivers must surface this route-down shortcut question via their native channel before taking the lighter route. Silent omission is forbidden. -->
Handle the three `SURFACE_RC` cases explicitly (per the T009 contract):
- **`SURFACE_RC -eq 1`** — surface the shortcut ask: use `AskUserQuestion` to ask "Shortcut: routing down to `<to_command>` instead of running full /z-plan. The robust alternative is to continue /z-plan in full. Proceed with the lighter route?" with options `["Yes, take the lighter route", "No, continue full /z-plan"]`. On "No": stay in /z-plan (skip the route-down).
- **`SURFACE_RC -eq 0`** — no-op (the route was lateral/upward, or not a shortcut): proceed without the shortcut ask.
- **`SURFACE_RC -eq 2`** — INFRA ERROR (shortcut telemetry failed: RUN unset, wiring bug, or the event was lost). Surface a diagnostic to the user ("shortcut telemetry failed — surfacing the route-down confirmation anyway"), then **fall back to surfacing the same `AskUserQuestion` as the `-eq 1` case** (fail-safe: when in doubt, ASK — never silently take the lighter route).

Present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.

When the user chooses **switch** or **abandon** at the route gate (ending the run), per the FINALIZE_STATUS rule execute **Run Brief — halt finalize** (below) with reason `route gate — user chose switch or abandon`.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Explicit planning mode gate (before hard cost gate)

Read `workflow.planning_mode` and `workflow.intent_level` from config (already exported by Setup step 2's `config.py export-env` call). These two knobs are recommendations for the visible Intent-vs-Full SDD gate, not a silent final decision unless an unattended driver must use the recommended default. Normalize `workflow.intent_level` before the cost gate: only `quick`, `standard`, `deep`, and `auto` are recognized; any unknown value is treated as `auto` for dispatch estimation and later classifier resolution.

```bash
PLANNING_MODE="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get workflow.planning_mode 2>/dev/null || echo "intent")"
INTENT_LEVEL_CONFIG="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get workflow.intent_level 2>/dev/null || echo "auto")"
case "$INTENT_LEVEL_CONFIG" in
  quick|standard|deep|auto) ;;
  *) INTENT_LEVEL_CONFIG="auto" ;;
esac
# Export immediately so downstream phases (3, 6, 8, 9) running in fresh shells can read it.
export PLANNING_MODE INTENT_LEVEL_CONFIG
```

**Flag overrides (parsed from `$ARGUMENTS` before the branch below).** CLI flags take precedence over config:

```bash
# Parse flag overrides from $ARGUMENTS.
# Flags are stripped before the task description is used as the slug.
_ARGS_REMAINING="$ARGUMENTS"
for _flag in "$@"; do
  case "$_flag" in
    --full)
      PLANNING_MODE="full"
      PLANNING_MODE_SOURCE="flag"
      _ARGS_REMAINING="${_ARGS_REMAINING/--full/}"
      ;;
    --quick)
      PLANNING_MODE="intent"
      PLANNING_MODE_SOURCE="flag"
      INTENT_LEVEL="quick"
      INTENT_LEVEL_SOURCE="flag"
      INTENT_LEVEL_REASON="--quick flag: forced L1"
      _ARGS_REMAINING="${_ARGS_REMAINING/--quick/}"
      ;;
    --standard)
      PLANNING_MODE="intent"
      PLANNING_MODE_SOURCE="flag"
      INTENT_LEVEL="standard"
      INTENT_LEVEL_SOURCE="flag"
      INTENT_LEVEL_REASON="--standard flag: forced L2"
      _ARGS_REMAINING="${_ARGS_REMAINING/--standard/}"
      ;;
    --deep)
      PLANNING_MODE="intent"
      PLANNING_MODE_SOURCE="flag"
      INTENT_LEVEL="deep"
      INTENT_LEVEL_SOURCE="flag"
      INTENT_LEVEL_REASON="--deep flag: forced L3"
      _ARGS_REMAINING="${_ARGS_REMAINING/--deep/}"
      ;;
  esac
done
# Trim leading/trailing whitespace from the remaining task description.
_ARGS_REMAINING="${_ARGS_REMAINING#"${_ARGS_REMAINING%%[![:space:]]*}"}"
_ARGS_REMAINING="${_ARGS_REMAINING%"${_ARGS_REMAINING##*[![:space:]]}"}"
# Export so slug derivation and subsequent phases see the stripped task text.
export PLANNING_MODE
```

When `INTENT_LEVEL_SOURCE="flag"`, the intent-level announce + override gate (Step 2) still fires — pre-selecting the flag-forced level as the recommended option — but it MUST obey the pre-subagent cost ceiling recorded in `ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX`: it may not silently offer or accept a level more expensive than the gate estimated. Emit `intent_level_chosen` with `source: "flag"` instead of `"classifier"` or `"config-forced"`.

When any of `--quick`, `--standard`, or `--deep` was parsed, also set `INTENT_LEVEL_CONFIG="$INTENT_LEVEL"` (overwriting the config-read value) so the Step 1 forced-level branch fires and the classifier is bypassed:

```bash
# After flag parse: if a level flag was set, sync INTENT_LEVEL_CONFIG so Step 1 skips the classifier.
if [[ "$INTENT_LEVEL_SOURCE" == "flag" ]]; then
  INTENT_LEVEL_CONFIG="$INTENT_LEVEL"
  export INTENT_LEVEL_CONFIG
fi
```

**Backward-compat SPEC detection (Invariant 4).** Check whether the slug dir already contains a legacy `SPEC.md` — if so, treat the plan as legacy regardless of `PLANNING_MODE` config. This guard runs BEFORE the branch below, after flag parsing:

```bash
# Invariant 4: never overwrite an existing legacy plan with INTENT.md.
if [[ -f "$Z_HARNESS_PLAN_DIR/SPEC.md" ]]; then
  if [[ "$PLANNING_MODE" != "full" ]]; then
    echo "[z-plan] SPEC.md detected in '$Z_HARNESS_PLAN_DIR' — routing to legacy path (Invariant 4)." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" legacy_spec_detected \
      "$(printf '{"slug":"%s","spec_path":"%s","original_planning_mode":"%s"}' \
         "$Z_HARNESS_SLUG" "$Z_HARNESS_PLAN_DIR/SPEC.md" "$PLANNING_MODE")"
    PLANNING_MODE="full"
    export PLANNING_MODE
  fi
  # Additionally, if TASKS.md is present, this is a finished plan — route to amend/implement,
  # not a fresh planning run. Surface this to the user.
  if [[ -f "$Z_HARNESS_PLAN_DIR/TASKS.md" ]]; then
    # <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must
    #      surface this finished-legacy-plan advisory via their native channel.
    #      Silent omission is forbidden. -->
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" legacy_plan_exists \
      "$(printf '{"slug":"%s","has_spec":true,"has_tasks":true}' "$Z_HARNESS_SLUG")"
    AskUserQuestion "This slug already has a finished legacy plan (SPEC.md + TASKS.md). \
What would you like to do?" \
      ["Amend the existing plan (/z-amend)", \
       "Implement the existing plan (/z-execute)", \
       "Continue here — start a fresh legacy plan run (overwrites SPEC/PLAN/TASKS)", \
       "Abort"]
    # On /z-amend or /z-execute: log next_step_choice, execute Run Brief — halt finalize,
    # deregister, then exit 0. Do NOT auto-dispatch the chosen command.
    # On "Continue here": proceed with PLANNING_MODE=full; the user accepts overwrite risk.
    # On Abort: execute Run Brief — halt finalize, deregister, then exit 1.
  fi
fi
```

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the
     Intent-vs-Full SDD mode choice before the hard cost gate. Silent omission is forbidden. -->
**Visible planning-mode choice.** After config, flags, and the `SPEC.md` legacy guard have resolved the recommended mode, surface a visible choice **before** the hard cost gate:

- **Intent mode (recommended default for new plans):** write `INTENT.md` with `frozen_at: pending`, then generate initial `TASKS.md`.
- **Full SDD mode:** write legacy `SPEC.md`, `PLAN.md`, and `TASKS.md`.

Config (`workflow.planning_mode`) and flags (`--full`, `--quick`, `--standard`, `--deep`) only choose the recommended/preselected option. A pre-existing `$Z_HARNESS_PLAN_DIR/SPEC.md` is the only hard override: it forces `PLANNING_MODE=full`, records `planning_mode_source=legacy_spec`, and the mode gate must explain that intent mode is unavailable for this slug to avoid overwriting legacy artifacts.

In unattended/no-ask mode, the visible question cannot be surfaced; bind the explicit choice variable from the resolved recommendation instead. The answer source remains `config` (from `workflow.planning_mode`) unless a CLI flag set `PLANNING_MODE_SOURCE=flag`, and the event reason records that this was the unattended/no-ask config default path.

```bash
PLANNING_MODE_RECOMMENDED="$PLANNING_MODE"
PLANNING_MODE_SOURCE="${PLANNING_MODE_SOURCE:-config}"
if [[ -f "$Z_HARNESS_PLAN_DIR/SPEC.md" ]]; then
  PLANNING_MODE_CHOICE="full"
  PLANNING_MODE="full"
  PLANNING_MODE_SOURCE="legacy_spec"
  PLANNING_MODE_REASON="SPEC.md exists; legacy full SDD mode is forced"
elif [[ -n "${Z_HARNESS_NO_ASK:-}" ]]; then
  # Unattended/no-ask drivers cannot surface the visible gate; bind the
  # already-resolved config/flag recommendation as the explicit answer.
  PLANNING_MODE_CHOICE="$PLANNING_MODE_RECOMMENDED"
  case "$PLANNING_MODE_CHOICE" in
    intent|full) PLANNING_MODE="$PLANNING_MODE_CHOICE" ;;
    *) PLANNING_MODE_CHOICE="intent"; PLANNING_MODE="intent" ;;
  esac
  PLANNING_MODE_REASON="unattended/no-ask config default from workflow.planning_mode or CLI flag"
else
  PLANNING_MODE_CHOICE="$(AskUserQuestion "Choose planning mode for this /z-plan run before cost estimation:" \
    ["intent — Intent mode: adaptive INTENT.md + initial TASKS.md (recommended: ${PLANNING_MODE_RECOMMENDED})", \
     "full — Full SDD mode: SPEC.md + PLAN.md + TASKS.md"])"
  # Capture the visible answer into PLANNING_MODE_CHOICE first, normalize the
  # machine token before the em dash, then map it to PLANNING_MODE.
  PLANNING_MODE_CHOICE="${PLANNING_MODE_CHOICE%% — *}"
  case "$PLANNING_MODE_CHOICE" in
    intent) PLANNING_MODE="intent" ;;
    full) PLANNING_MODE="full" ;;
    *) echo "invalid planning mode choice: $PLANNING_MODE_CHOICE" >&2; exit 1 ;;
  esac
  PLANNING_MODE_SOURCE="user"
  PLANNING_MODE_REASON="explicit mode gate"
fi
export PLANNING_MODE PLANNING_MODE_CHOICE PLANNING_MODE_SOURCE PLANNING_MODE_REASON

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" planning_mode_chosen \
  "$(printf '{"slug":"%s","mode":"%s","choice":"%s","recommended_mode":"%s","source":"%s","reason":"%s","legacy_spec_forced":%s}' \
     "$Z_HARNESS_SLUG" "$PLANNING_MODE" "$PLANNING_MODE_CHOICE" \
     "$PLANNING_MODE_RECOMMENDED" "$PLANNING_MODE_SOURCE" "${PLANNING_MODE_REASON:-}" \
     "$(if [[ "$PLANNING_MODE_SOURCE" == "legacy_spec" ]]; then echo true; else echo false; fi)")"
```

The `planning_mode_chosen` event is mandatory and is emitted exactly once per run, before `cost_gate_decision`. Downstream telemetry must treat it as the source of truth for `planning_mode`.


## Pre-subagent cost gate (hard)

This gate runs after the cheap setup, claim/register, freshness checks, deterministic route preflight, and the **explicit planning mode gate** above. It runs **before every expensive subagent**: `planning-router` (when deferred), `intent-classifier`, Phase 1 `doc-fetcher`, Phase 1 Explore, Phase 3 / Phase 7 consultant panels, the Phase 7 pre-dispatch `task-tree-generator` guard, and any other Agent dispatch.

`workflow.pre_run_cost_gate` remains the single disposition authority: `/z-plan` must call `scripts/pre-run-cost-gate.sh`, and that helper delegates the disposition to `scripts/config.py`. Do not read `cost.token_budget` here and do not reimplement the budget comparison in the skill.

Compute explicit dispatch counts using only the documented `z-plan` keys from `scripts/token-cost-profiles.json`: `planning_mode_full`, `intent_level_depth`, `doc_fetcher`, `explore`, `phase3_consultants`, `phase7_consultants`, and `task_tree_generator`. Counts are conservative pre-gate upper bounds; unknown future fan-out stays at the fail-closed default rather than being guessed downward.

Dispatch-count computation, the `pre-run-cost-gate.sh` call, `GATE_JSON` normalization/parsing, and the sanitized-error mapping are mechanical plumbing delegated to `scripts/zplan-cost-gate-runtime.sh` (SKILL-STYLE.md §2 — a second consumer, the reduction re-estimate below, reuses the same `call-gate` subcommand, so this is a script, not inline bash). Nothing here reimplements `pre-run-cost-gate.sh` or `config.py`'s disposition logic:

```bash
ZPLAN_COST_GATE_RUNTIME="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/zplan-cost-gate-runtime.sh"

eval "$(bash "$ZPLAN_COST_GATE_RUNTIME" compute-dispatch \
  --planning-mode "$PLANNING_MODE" \
  --intent-level-config "${INTENT_LEVEL_CONFIG:-auto}" \
  --docs-index-exists "${DOCS_LLM_INDEX_EXISTS:-unknown}")"
export ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX

eval "$(bash "$ZPLAN_COST_GATE_RUNTIME" call-gate --run "$RUN" \
  --dispatch planning_mode_full="$ZPLAN_DISPATCH_PLANNING_MODE_FULL" \
  --dispatch intent_level_depth="$ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH" \
  --dispatch doc_fetcher="$ZPLAN_DISPATCH_DOC_FETCHER" \
  --dispatch explore="$ZPLAN_DISPATCH_EXPLORE" \
  --dispatch phase3_consultants="$ZPLAN_DISPATCH_PHASE3_CONSULTANTS" \
  --dispatch phase7_consultants="$ZPLAN_DISPATCH_PHASE7_CONSULTANTS" \
  --dispatch task_tree_generator="$ZPLAN_DISPATCH_TASK_TREE_GENERATOR")"

printf '%s\n' "$GATE_HUMAN_BLOCK"
```

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the pre-subagent cost gate via their native channel when the normalized disposition is `ask`. Silent omission is forbidden. -->

### Cost gate telemetry contract

`cost_gate_decision` is reserved for **exactly one terminal `/z-plan` cost-gate decision per run**. It is emitted before any expensive Agent dispatch and never emitted again on later success paths. Every terminal branch uses the same payload builder.

Nonterminal reduction / re-estimate attempts MUST NOT emit `cost_gate_decision`. They emit `cost_gate_reestimate_attempt` instead. Full field-by-field shape for both event kinds: `_fragments/zplan-cost-gate-reference.md` — "Cost gate telemetry field reference" (included below at the terminal cleanup helper, the section that actually consumes it).

Use this logging shape in each terminal branch; bind `ZPLAN_COST_CHOICE`, `ZPLAN_COST_CHOICE_SOURCE`, and optional `ZPLAN_COST_REASON` once, then call it **once**:

```bash
ZPLAN_COST_DECISION_EMITTED=0
ZPLAN_COST_ATTEMPT_COUNT="${ZPLAN_COST_ATTEMPT_COUNT:-0}"
ZPLAN_COST_REESTIMATE_MAX="${ZPLAN_COST_REESTIMATE_MAX:-2}"
ZPLAN_COST_GATE_ID="${RUN}:z-plan:pre-subagent-cost-gate"
emit_zplan_cost_gate_decision_once() {
  if [[ "${ZPLAN_COST_DECISION_EMITTED:-0}" -eq 1 ]]; then
    return 0
  fi
  ZPLAN_COST_DECISION_JSON="$(bash "$ZPLAN_COST_GATE_RUNTIME" build-decision-json \
    "$ZPLAN_COST_CHOICE" "$GATE_EST_TOKENS" "$GATE_CONFIDENCE" "$GATE_BASIS" \
    "$GATE_DISPOSITION" "$GATE_RULE_ID" "$GATE_RANGE_HIGH" "$ZPLAN_COST_CHOICE_SOURCE" \
    "$ZPLAN_COST_ATTEMPT_COUNT" "${ZPLAN_COST_REASON:-}" "$ZPLAN_COST_GATE_ID")"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "$RUN" cost_gate_decision "$ZPLAN_COST_DECISION_JSON"
  ZPLAN_COST_DECISION_EMITTED=1
}
```

### Cost gate reduction / re-estimate UX (bounded)

The interactive `ask` branch offers a bounded chance to lower already-known `/z-plan` cost drivers and re-run the same helper before any expensive Agent dispatch. This is not a budget bypass: every re-estimate still calls `scripts/pre-run-cost-gate.sh`, every terminal path still emits exactly one `cost_gate_decision`, and every nonterminal reduction emits `cost_gate_reestimate_attempt`.

Loop rules:

- `ZPLAN_COST_REESTIMATE_MAX=2`. After two valid reduction attempts, the prompt MUST remove all reduction options; the user can only proceed with the current estimate or abandon.
- Default action: **Proceed with current estimate (default)**. Drivers may bind Enter/Return to this option only when they can distinguish it from cancellation/timeout.
- Invalid, malformed, unavailable, or driver-unknown choices take the conservative path: set `_COST_GATE_CHOICE=interrupted`, emit `user_wait_end` with `disposition=interrupted`, then use the existing interrupted terminal branch (`choice=interrupted`, `choice_source=driver_interrupt`, halt-finalize). Never treat an unrecognized reduction token as proceed.
- If a reduction re-estimate refreshes `GATE_DISPOSITION=auto_proceed`, that helper approval is terminal: emit the single `cost_gate_decision` with `choice=auto_proceed` / `choice_source=helper` and continue without printing another prompt or recording a user proceed.
- Reduction options are shown only in `PLANNING_MODE=intent`. Legacy `planning_mode=full` has no cost-reduction option in this loop because reducing `planning_mode_full` would change the planning paradigm; users must abandon and rerun with an explicit flag/config if they want a different mode.
- Reducible drivers in this loop are limited to:
  - `intent_level_depth`: explicit user downgrade to L2 Standard or L1 Quick.
  - `phase3_consultants`: only through the L1 Quick downgrade, which sets `INTENT_CONSULT_POLICY=skip` and updates the dispatch count to 0.
- Non-reducible here: `doc_fetcher` (required when docs exist), `task_tree_generator` (required for intent runs), `phase7_consultants` (no existing downstream run-state variable controls a per-run skip), and `explore` (Phase 1's cap is config-governed; do not silently mutate config from this gate).

Exact prompt/options while attempts remain:

```text
<GATE_HUMAN_BLOCK>

Current high-end estimate: <GATE_RANGE_HIGH or unknown> tokens
Confidence: <GATE_CONFIDENCE>; basis: <GATE_BASIS>
Reduction attempts remaining: <ZPLAN_COST_REESTIMATE_MAX - ZPLAN_COST_ATTEMPT_COUNT>

Choose a cost-gate action:
1. Proceed with current estimate (default)
2. Reduce: force L2 Standard — full intent, optional Phase-3 consult
3. Reduce: force L1 Quick — thin intent, skip Phase-3 consult
4. Abandon before expensive planning subagents
```

Exact prompt/options after the cap:

```text
<GATE_HUMAN_BLOCK>

Reduction attempt limit reached (2). Choose a terminal action:
1. Proceed with current estimate (default)
2. Abandon before expensive planning subagents
```

Reduction state mutations are authoritative run state, not display-only: the downgrade MUST update the variables consumed by later mode/consult phases and the dispatch variables passed into the next helper call. Each reduction token's (`force_l2_standard` / `force_l1_quick`) state mutation is mechanical — no judgment — so it lives in `scripts/zplan-cost-gate-runtime.sh apply-reduction` (SKILL-STYLE.md §2). This thin wrapper keeps the same name and `return 2` contract for the calling loop:

```bash
zplan_apply_cost_reduction() {
  eval "$(bash "$ZPLAN_COST_GATE_RUNTIME" apply-reduction "$1")" || return 2
}
```

Re-estimate pseudocode (reuse the exact helper invocation and normalization rules from the initial estimate via the same `call-gate` subcommand; raw helper output is still never logged):

```bash
zplan_reestimate_cost_gate_after_reduction() {
  _ZPLAN_PRIOR_RANGE_HIGH="$GATE_RANGE_HIGH"

  eval "$(bash "$ZPLAN_COST_GATE_RUNTIME" call-gate --run "$RUN" \
    --dispatch planning_mode_full="$ZPLAN_DISPATCH_PLANNING_MODE_FULL" \
    --dispatch intent_level_depth="$ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH" \
    --dispatch doc_fetcher="$ZPLAN_DISPATCH_DOC_FETCHER" \
    --dispatch explore="$ZPLAN_DISPATCH_EXPLORE" \
    --dispatch phase3_consultants="$ZPLAN_DISPATCH_PHASE3_CONSULTANTS" \
    --dispatch phase7_consultants="$ZPLAN_DISPATCH_PHASE7_CONSULTANTS" \
    --dispatch task_tree_generator="$ZPLAN_DISPATCH_TASK_TREE_GENERATOR")"
  # Refreshes: GATE_DISPOSITION, GATE_HUMAN_BLOCK, GATE_EST_TOKENS, GATE_CONFIDENCE,
  # GATE_BASIS, GATE_RULE_ID, GATE_RANGE_HIGH, and GATE_SANITIZED_ERROR.

  ZPLAN_COST_ATTEMPT_COUNT=$((ZPLAN_COST_ATTEMPT_COUNT + 1))
  ZPLAN_COST_REESTIMATE_JSON="$(python3 - \
    "$RUN" "$ZPLAN_COST_GATE_ID" "$ZPLAN_COST_ATTEMPT_COUNT" \
    "$ZPLAN_COST_CHANGED_DRIVERS_JSON" "$_ZPLAN_PRIOR_RANGE_HIGH" \
    "$GATE_RANGE_HIGH" "$GATE_DISPOSITION" <<'PY'
import json, sys
run_id, gate_id, attempt, changed, prior, new, disposition = sys.argv[1:8]
def as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default
payload = {
    "command": "z-plan",
    "run_id": run_id,
    "gate_id": gate_id,
    "attempt_index": int(attempt),
    "changed_drivers": json.loads(changed),
    "prior_range_high": as_int(prior, 0),
    "new_range_high": as_int(new, 0),
    "disposition": disposition,
    "terminal_event_kind": "cost_gate_decision",
}
print(json.dumps(payload, separators=(",", ":")))
PY
)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "$RUN" cost_gate_reestimate_attempt "$ZPLAN_COST_REESTIMATE_JSON"
}
```

L3/deep semantics are never reduced implicitly. The only cost-gate paths that lower them are the explicit `force_l2_standard` or `force_l1_quick` options above, both of which set `INTENT_LEVEL_CONFIG`, update `ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX`, and export `INTENT_LEVEL` / `INTENT_CONSULT_POLICY` for downstream phases. Later intent-level override handling MUST treat `ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX` as the maximum already-gated depth; choosing a deeper level requires a fresh hard cost-gate re-estimate before any expensive Agent dispatch.

### Cost gate terminal cleanup helper

The gate runs after preflight (run-brief init + register already happened inside Setup step 2's `z-preflight.sh` call). Every terminal post-register failure (`abandon`, `halt`, `unhandled_gate`, helper failure/malformed/missing-field no-ask halt, or interrupted wait) MUST reuse the same halt-finalize + teardown-funnel sequence as every other halt site in this skill — set outcome/next, finalize/render/require the brief, then release+deregister+run_end via one `z-teardown.sh` call. This sequence (outcome/next + `_fragments/run-brief-finalize.md` + `z-teardown.sh`) is identical mechanics to every other halt site in this file, so it is a `scripts/zplan-cost-gate-runtime.sh halt-finalize` call, not inline bash:

```bash
zplan_cost_gate_halt_finalize() {
  bash "$ZPLAN_COST_GATE_RUNTIME" halt-finalize \
    --run "$RUN" --slug "$Z_HARNESS_SLUG" --reason "$1"
}
```

Cleanup matrix and sanitized helper-error expansion (which terminal event each branch emits, and the allowed outcomes once `GATE_SANITIZED_ERROR` is set): `_fragments/zplan-cost-gate-reference.md` — "Cleanup matrix" and "Sanitized helper-error expansion".

<!-- include: _fragments/zplan-cost-gate-reference.md -->

Branch on normalized `GATE_DISPOSITION` before any Agent dispatch:

```bash
case "$GATE_DISPOSITION" in
  auto_proceed)
    ZPLAN_COST_CHOICE=auto_proceed
    ZPLAN_COST_CHOICE_SOURCE=helper
    emit_zplan_cost_gate_decision_once
    ;;

  ask)
    while :; do
      # Load-bearing heartbeat BEFORE each user wait.
      if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
          --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
          --command /z-plan || true
      fi
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
        '{"phase":"pre-subagent-cost-gate","reason":"cost_gate"}'

      if [[ "${PLANNING_MODE:-intent}" == "intent" && "${ZPLAN_COST_ATTEMPT_COUNT:-0}" -lt "${ZPLAN_COST_REESTIMATE_MAX:-2}" ]]; then
        AskUserQuestion(
          header: "$GATE_HUMAN_BLOCK

Current high-end estimate: ${GATE_RANGE_HIGH:-unknown} tokens
Confidence: ${GATE_CONFIDENCE}; basis: ${GATE_BASIS}
Reduction attempts remaining: $(( ${ZPLAN_COST_REESTIMATE_MAX:-2} - ${ZPLAN_COST_ATTEMPT_COUNT:-0} ))

Choose a cost-gate action:",
          options: [
            "Proceed with current estimate (default)",
            "Reduce: force L2 Standard — full intent, optional Phase-3 consult",
            "Reduce: force L1 Quick — thin intent, skip Phase-3 consult",
            "Abandon before expensive planning subagents"
          ]
        )
      else
        if [[ "${PLANNING_MODE:-intent}" != "intent" ]]; then
          _ZPLAN_COST_TERMINAL_REASON="No cost-reduction options are available for planning_mode=${PLANNING_MODE}."
        else
          _ZPLAN_COST_TERMINAL_REASON="Reduction attempt limit reached (${ZPLAN_COST_REESTIMATE_MAX:-2})."
        fi
        AskUserQuestion(
          header: "$GATE_HUMAN_BLOCK

${_ZPLAN_COST_TERMINAL_REASON} Choose a terminal action:",
          options: [
            "Proceed with current estimate (default)",
            "Abandon before expensive planning subagents"
          ]
        )
      fi

      # _COST_GATE_CHOICE must be captured as one of:
      # proceed, reduce_force_l2_standard, reduce_force_l1_quick, abandon, interrupted.
      # A re-estimate may also set the internal terminal token auto_proceed_after_reestimate.
      # Empty/default UI selection may become proceed; malformed/unknown tokens MUST become interrupted.
      case "$_COST_GATE_CHOICE" in
        reduce_force_l2_standard|reduce_force_l1_quick)
          if [[ "${ZPLAN_COST_ATTEMPT_COUNT:-0}" -ge "${ZPLAN_COST_REESTIMATE_MAX:-2}" ]]; then
            _COST_GATE_CHOICE=interrupted
            bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
              '{"phase":"pre-subagent-cost-gate","reason":"cost_gate","disposition":"interrupted"}'
            break
          fi
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
            "$(printf '{"phase":"pre-subagent-cost-gate","reason":"cost_gate","disposition":"%s"}' "$_COST_GATE_CHOICE")"
          case "$_COST_GATE_CHOICE" in
            reduce_force_l2_standard) zplan_apply_cost_reduction force_l2_standard ;;
            reduce_force_l1_quick)    zplan_apply_cost_reduction force_l1_quick ;;
          esac || { _COST_GATE_CHOICE=interrupted; break; }
          zplan_reestimate_cost_gate_after_reduction
          if [[ "$GATE_DISPOSITION" == "auto_proceed" ]]; then
            _COST_GATE_CHOICE=auto_proceed_after_reestimate
            break
          elif [[ "$GATE_DISPOSITION" == "halt" ]]; then
            _COST_GATE_CHOICE=policy_halt_after_reestimate
            break
          fi
          printf '%s\n' "$GATE_HUMAN_BLOCK"
          continue
          ;;
        proceed|abandon|interrupted)
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
            "$(printf '{"phase":"pre-subagent-cost-gate","reason":"cost_gate","disposition":"%s"}' "$_COST_GATE_CHOICE")"
          break
          ;;
        *)
          _COST_GATE_CHOICE=interrupted
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
            '{"phase":"pre-subagent-cost-gate","reason":"cost_gate","disposition":"interrupted"}'
          break
          ;;
      esac
    done

    case "$_COST_GATE_CHOICE" in
      auto_proceed_after_reestimate)
        ZPLAN_COST_CHOICE=auto_proceed
        ZPLAN_COST_CHOICE_SOURCE=helper
        ZPLAN_COST_REASON=""
        emit_zplan_cost_gate_decision_once
        ;;
      proceed)
        ZPLAN_COST_CHOICE=proceed
        ZPLAN_COST_CHOICE_SOURCE=user
        ZPLAN_COST_REASON="${GATE_SANITIZED_ERROR:-}"
        emit_zplan_cost_gate_decision_once
        ;;
      abandon)
        ZPLAN_COST_CHOICE=abandon
        ZPLAN_COST_CHOICE_SOURCE=user
        ZPLAN_COST_REASON="${GATE_SANITIZED_ERROR:-user_abandoned}"
        emit_zplan_cost_gate_decision_once
        zplan_cost_gate_halt_finalize "cost gate abandoned by user"
        exit 1
        ;;
      policy_halt_after_reestimate)
        ZPLAN_COST_CHOICE=halt
        ZPLAN_COST_CHOICE_SOURCE=policy
        ZPLAN_COST_REASON=gate_policy_halt
        emit_zplan_cost_gate_decision_once
        zplan_cost_gate_halt_finalize "cost gate policy halt"
        exit 1
        ;;
      *)
        ZPLAN_COST_CHOICE=interrupted
        ZPLAN_COST_CHOICE_SOURCE=driver_interrupt
        ZPLAN_COST_REASON=user_wait_interrupted
        emit_zplan_cost_gate_decision_once
        zplan_cost_gate_halt_finalize "cost gate user wait interrupted"
        exit 1
        ;;
    esac
    ;;

  halt)
    ZPLAN_COST_CHOICE=halt
    ZPLAN_COST_CHOICE_SOURCE="${GATE_SANITIZED_ERROR:+sanitized_helper_error}"
    ZPLAN_COST_CHOICE_SOURCE="${ZPLAN_COST_CHOICE_SOURCE:-policy}"
    ZPLAN_COST_REASON="${GATE_SANITIZED_ERROR:-gate_policy_halt}"
    emit_zplan_cost_gate_decision_once
    zplan_cost_gate_halt_finalize "cost gate policy halt"
    exit 1
    ;;

  unhandled_gate|*)
    ZPLAN_COST_CHOICE=halt
    ZPLAN_COST_CHOICE_SOURCE=policy
    ZPLAN_COST_REASON=unhandled_gate
    GATE_DISPOSITION=unhandled_gate
    emit_zplan_cost_gate_decision_once
    zplan_cost_gate_halt_finalize "cost gate unhandled disposition"
    exit 1
    ;;
esac
```

Never emit a generic "successful gate" `cost_gate_decision` after this branch; the successful paths above are already logged once.

## Artifact Scout classifier (post-gate, before first expensive dispatch)

Run this only after the hard cost gate has produced a terminal proceed/auto-proceed event and only when `artifact-scout-inventory.json` has nontrivial candidates, active/worktree overlaps, partial/truncated sources, or exact-slug/precontext signals. If the inventory is a clean no-match, skip the Agent and continue. This is the first allowed `artifact-scout` Agent position for `/z-plan`; it runs before deferred `planning-router`, `intent-classifier`, Phase 1 `doc-fetcher`, Explore, consultants, or task-tree generation.

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this artifact-scout
     requirement and skip the Agent() call. Skipping means continue without scout routing. -->
Agent(
  subagent_type="artifact-scout",
  description="Artifact scout for z-plan <slug>",
  prompt="current_command: /z-plan
task_or_topic: <original task>
route_chain_json: <current route chain JSON>
repo_root: <abs repo root>
inventory_json_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout-inventory.json

Inline inventory JSON:
<contents printed by scripts/artifact-scout-inventory.py>"
)
```

Write the raw classifier response to `$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout.md`. Parse it with the `artifact-scout` contract. Emit `artifact_scout_classified` for every well-formed response, `artifact_scout_warning` for `STATUS: warned` or warning-only findings, and `artifact_scout_route` only when `ROUTE_RECOMMENDATION` is not `continue` and the JSON has `route_chain_effect: "write_route_decision"`.

Route boundary: warning-only output never writes `route-decision.md`, never emits `artifact_scout_route`, and never advances `route_chain`. Only `ask_user` or route recommendations with `route_chain_effect: "write_route_decision"` may write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision`, and append the artifact-scout hop to `route_chain`.


### Branch: `planning_mode=full` (legacy SDD path)

If `PLANNING_MODE == "full"`, set `INTENT_LEVEL=""` and proceed directly to Phase 0. All subsequent phases run exactly as documented below — no classifier dispatch, no INTENT.md write. The legacy SPEC/PLAN/TASKS path is unchanged.

```bash
# Legacy path guard (formalized by T007).
if [[ "$PLANNING_MODE" == "full" ]]; then
  INTENT_LEVEL=""
  INTENT_LEVEL_SOURCE=""
  # Emit a legacy_mode_active event so telemetry can distinguish full vs intent runs.
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" legacy_mode_active \
    "$(printf '{"slug":"%s","reason":"planning_mode=full"}' "$Z_HARNESS_SLUG")"
  # Fall through to Phase 0; all phases produce SPEC/PLAN/TASKS exactly as documented.
fi
```

### Branch: `planning_mode=intent` (adaptive INTENT path — default)

If `PLANNING_MODE == "intent"` (the default), run the intent-classifier to choose a planning depth level, then announce the chosen level and offer an inline override.

**Step 1 — Resolve the level.**

If `INTENT_LEVEL_CONFIG` is one of `quick`, `standard`, or `deep` (i.e. the user forced a level via config, flag, or the pre-subagent cost-reduction gate), skip the classifier and use the forced value directly. `auto` or any unknown value is not a forced level:

```bash
if [[ "$PLANNING_MODE" == "intent" ]]; then
  if [[ "$INTENT_LEVEL_CONFIG" =~ ^(quick|standard|deep)$ ]]; then
    # Forced level: skip classifier entirely. NEVER fall through to parse below.
    # Preserve explicit flag and cost-gate reduction sources; otherwise this is
    # a normal config-forced level.
    INTENT_LEVEL="$INTENT_LEVEL_CONFIG"
    if [[ "$INTENT_LEVEL_SOURCE" != "user-cost-reduction" && "$INTENT_LEVEL_SOURCE" != "flag" ]]; then
      INTENT_LEVEL_SOURCE="config-forced"
      INTENT_LEVEL_REASON="config-forced: workflow.intent_level=$INTENT_LEVEL_CONFIG"
    fi
  else
    # Auto mode: dispatch the intent-classifier (Haiku). Pass forced_level="" so the
    # classifier knows it is in auto mode.
    INTENT_CLASSIFIER_RC=0
    INTENT_CLASSIFIER_OUT=""
```

<!-- RUNTIME-GATE: subagent; non-supporting drivers must skip the intent-classifier
     Agent() call and default INTENT_LEVEL to "standard" with source "fallback". -->
If `INTENT_LEVEL_CONFIG` is not a forced level and `PLANNING_MODE == "intent"`, dispatch the classifier and capture its return into `INTENT_CLASSIFIER_OUT`. A non-zero exit or empty return triggers the fallback path:

```
INTENT_CLASSIFIER_OUT="$(Agent(
  subagent_type="intent-classifier",
  description="Classify planning depth for <slug>",
  prompt="task_prompt: <verbatim contents of $ARGUMENTS — the raw user task text>\nrepo_root: <abs path to repo root>\nforced_level: "
))"
INTENT_CLASSIFIER_RC=$?
```

(Orchestrators that don't support inline Agent() capture must assign the Agent return to `INTENT_CLASSIFIER_OUT` via their native binding mechanism and set `INTENT_CLASSIFIER_RC` accordingly.)

```bash
    # Parse classifier output (INTENT_CLASSIFIER_OUT holds the agent's return).
    # This parse block is inside the `else` (auto-mode) branch — it NEVER runs
    # when INTENT_LEVEL_CONFIG is quick/standard/deep (i.e. forced case above).
    if [[ "$INTENT_CLASSIFIER_RC" -ne 0 || -z "$INTENT_CLASSIFIER_OUT" ]]; then
      INTENT_LEVEL="standard"
      INTENT_LEVEL_SOURCE="fallback"
      INTENT_LEVEL_REASON="classifier returned non-zero or empty; defaulting standard"
    else
      INTENT_LEVEL="$(echo "$INTENT_CLASSIFIER_OUT" | grep '^LEVEL:' | awk '{print $2}' | tr -d '[:space:]')"
      INTENT_LEVEL_REASON="$(echo "$INTENT_CLASSIFIER_OUT" | grep '^REASON:' | sed 's/^REASON: *//')"
      INTENT_LEVEL_SOURCE="classifier"

      # Fallback: if parse fails or level is unrecognized, default to standard.
      if [[ ! "$INTENT_LEVEL" =~ ^(quick|standard|deep)$ ]]; then
        INTENT_LEVEL="standard"
        INTENT_LEVEL_SOURCE="fallback"
        INTENT_LEVEL_REASON="classifier parse failed or returned unrecognized level; defaulting standard"
      fi
    fi
  fi  # end of auto/non-forced else branch (closes the forced-level INTENT_LEVEL_CONFIG check)
fi
```

**Step 2 — Announce the level + offer override.**

Map the level to its human-readable name:
- `quick` → **L1 (Quick)** — thin intent, 2 sections, no consult
- `standard` → **L2 (Standard)** — full intent, 4 sections, optional consult
- `deep` → **L3 (Deep)** — full intent, 4 sections + full Phase-3 cross-LLM consult

Emit an `intent_level_chosen` event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_level_chosen \
  "$(printf '{"level":"%s","source":"%s","reason":%s}' \
     "$INTENT_LEVEL" "$INTENT_LEVEL_SOURCE" \
     "$(printf '%s' "$INTENT_LEVEL_REASON" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
```

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the
     level announcement and offer the override choice via their native channel.
     Silent omission is forbidden — the user must always see the chosen level. -->
Present an `AskUserQuestion` announcing the chosen level and offering an inline override. Pre-select the chosen level as the recommended option. Before building the options, read `ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX` (0=quick, 1=standard, 2=deep; default to 2 only if the variable is absent for a pre-contract resume). The override gate MUST NOT present or accept an option whose rank is greater than this approved maximum. If a driver cannot hide unsupported options and the user selects a too-deep level, it MUST either re-run the hard pre-subagent cost gate with the higher dispatch counts before any expensive Agent dispatch, or treat the selection as invalid/interrupted and halt-finalize; the default `/z-plan` contract is to constrain the options, not to re-gate.

```bash
case "${ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX:-2}" in
  0|1|2) ;;
  *) ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX=2 ;;
esac
zplan_intent_level_rank() {
  case "$1" in
    quick) echo 0 ;;
    standard) echo 1 ;;
    deep) echo 2 ;;
    *) echo 1 ;;  # safe default matches fallback standard
  esac
}
```

Build the options from that ceiling; never display a level above the approved rank:

```bash
ZPLAN_INTENT_LEVEL_OPTIONS=(
  "<INTENT_LEVEL_LABEL> — proceed (recommended)"
  "L1 Quick — thin intent, skip consult"
)
if [[ "$ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX" -ge 1 ]]; then
  ZPLAN_INTENT_LEVEL_OPTIONS+=("L2 Standard — full intent, optional consult")
fi
if [[ "$ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX" -ge 2 ]]; then
  ZPLAN_INTENT_LEVEL_OPTIONS+=("L3 Deep — full intent, full cross-LLM consult")
fi

AskUserQuestion(
  header: "Planning depth: <INTENT_LEVEL_LABEL> (<INTENT_LEVEL>) — <INTENT_LEVEL_REASON>.
           Proceed with this level, or override?",
  options: ZPLAN_INTENT_LEVEL_OPTIONS
)
```

On user selection:
- **Proceed (recommended)**: keep `INTENT_LEVEL` as-is.
- **L1 Quick / L2 Standard / L3 Deep**: first compute `SELECTED_INTENT_LEVEL_RANK="$(zplan_intent_level_rank "$SELECTED_INTENT_LEVEL")"` and verify `SELECTED_INTENT_LEVEL_RANK <= ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX`. If not, do not mutate `INTENT_LEVEL`; either run the fresh hard cost re-gate described above or treat the selection as invalid/interrupted and halt-finalize. Only after the rank check passes, set `INTENT_LEVEL` to `quick` / `standard` / `deep` and set `INTENT_LEVEL_SOURCE="user-override"`. Emit `intent_level_override` event:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_level_override \
    "$(printf '{"level":"%s","prior_level":"%s","source":"user-override"}' \
       "$INTENT_LEVEL" "$PRIOR_INTENT_LEVEL")"
  ```

**Step 3 — Set consult policy from level.**

```bash
# Level→consult policy:
#   L1 (quick)    → skip Phase-3 consult entirely
#   L2 (standard) → Phase-3 consult optional (user may skip)
#   L3 (deep)     → full Phase-3 cross-LLM consult required
case "$INTENT_LEVEL" in
  quick)    INTENT_CONSULT_POLICY="skip"     ;;
  standard) INTENT_CONSULT_POLICY="optional" ;;
  deep)     INTENT_CONSULT_POLICY="full"     ;;
  *)        INTENT_CONSULT_POLICY="optional" ;;  # safe default
esac
export INTENT_LEVEL INTENT_LEVEL_SOURCE INTENT_CONSULT_POLICY ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX
```

**After mode detection, all downstream phases read `PLANNING_MODE` and `INTENT_LEVEL`:**
- `PLANNING_MODE=intent` with a set `INTENT_LEVEL` → intent path; Phase 6 writes INTENT.md, and the Phase 7 pre-dispatch guard generates the initial level-0 `TASKS.md` before reviewer prompts render `tasks_path`.
- `PLANNING_MODE=full` or `INTENT_LEVEL=""` → legacy path; all phases run as documented.
- SPEC.md detected in slug dir → `PLANNING_MODE` forced to `full` by the backward-compat guard above (Invariant 4); legacy path runs as if `--full` was passed.

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 9), stamp the start time to disk and fire a claim heartbeat:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" begin "$RUN" <phase-num>
# Claim heartbeat at phase boundary (guard: only when CLAIM_HELD==1)
if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
  _HB_RC=0
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-plan || _HB_RC=$?
  if [[ "$_HB_RC" -eq 9 ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
      "$(printf '{"slug":"%s","run_id":"%s","phase":"begin-%d"}' "$Z_HARNESS_SLUG" "$RUN" <phase-num>)"
    # URGENT: slug was taken over by another session while this run was active.
    AskUserQuestion "URGENT: The claim on slug '$Z_HARNESS_SLUG' was lost (taken over by another session or freed). \
This run may collide with a peer. Default: abort." \
      ["Abort (safe default)", "Continue uncoordinated (you accept collision risk)"]
    # On abort → CLAIM_HELD=0; set RB_HALT_REASON, include the halt-finalize fragment,
    #            call z-teardown.sh --status aborted, exit 1 (deregister no-ops if unregistered).
    # On continue-uncoordinated → CLAIM_HELD=0 (lock already gone); log plan_claim_override; proceed.
  fi
  # heartbeat_error (exit 0) is a transient read failure — NOT a lost claim; log-event already emitted
  # by plan-claim.sh; no gate fires.
fi
```

At the **end**, emit `phase_end` — `log-phase.sh finish` reads the stamped start time back, computes `wall_ms`, and logs it:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" finish "$RUN" <phase-num> \
  "$(printf '{"phase":%d,"name":"%s","user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$USER_WAIT_MS_THIS_PHASE")"
```

> **Why disk, not a shell variable:** each `Bash` tool call runs in a fresh shell, so a `T0=$(date +%s%3N)` recorded at phase start is gone by the phase-end call in a later turn — `WALL_MS` then resolves against an empty `T0` and logs `wall_ms: 0`. `log-phase.sh begin/finish` persists the start stamp under `${TMPDIR:-/tmp}/z-harness-phase/`, keyed by run+phase, so timing survives across tool-call boundaries. `finish` fail-opens (emits nothing) if `begin` was skipped, rather than logging a bogus zero.

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact. **Immediately before the `user_wait_start` log, fire a claim heartbeat** — this is the load-bearing call that extends the TTL to survive the upcoming human wait:

```bash
# Load-bearing heartbeat BEFORE every user wait (extends TTL to survive the wait).
if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
  _HB_RC=0
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-plan || _HB_RC=$?
  if [[ "$_HB_RC" -eq 9 ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
      "$(printf '{"slug":"%s","run_id":"%s","phase":"pre-gate-%d"}' "$Z_HARNESS_SLUG" "$RUN" <phase-num>)"
    AskUserQuestion "URGENT: The claim on slug '$Z_HARNESS_SLUG' was lost before this gate. \
Another session may now be planning the same slug. Default: abort." \
      ["Abort (safe default)", "Continue uncoordinated (you accept collision risk)"]
    # On abort → CLAIM_HELD=0; set RB_HALT_REASON, include the halt-finalize fragment,
    #            call z-teardown.sh --status aborted, exit 1.
    # On continue-uncoordinated → CLAIM_HELD=0; log plan_claim_override; proceed to gate.
  fi
  # heartbeat_error (exit 0): plan-claim.sh already emitted heartbeat_error event; proceed normally.
fi
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

The AFTER-gate heartbeat (`user_wait_end` bracket) is **optional** — skip it when the next phase's begin-heartbeat is imminent (it would otherwise duplicate the TTL refresh).

This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.

---

## Phase 0 — Premise check

### 0-sharpen. Mandatory conversational sharpen

Run this step **before** the premise check below, immediately after Phase telemetry begins.

**Purpose:** `/z-plan` starts from a sharpened problem statement, not from an unexamined prompt. Invoke the shared `/z-sharpen` inline component contract (not the `/z-sharpen` wrapper lifecycle) or consume an existing fresh `$Z_HARNESS_PLAN_DIR/GRILL.md`. The component clarifies the concrete problem, minimal scope, evidence/pain, non-goals, acceptance signals, and surviving alternatives.

**Surface boundary:** `/z-plan` owns its slug, claim/register state, telemetry, and archive paths. It MUST NOT depend on `/z-sharpen` wrapper-only behavior: wrapper slug derivation, collision prompts, run lifecycle, or advisory handoff.

**Skip / consume existing artifact:** If `$Z_HARNESS_PLAN_DIR/GRILL.md` already exists with a completed `## Sharpened problem`, read it and emit `sharpen_gate` with `decision: "existing_grill"`. Do not re-interview the user unless the existing artifact is stale, question-heavy, or contradicts `$ARGUMENTS`.

**Interactive sharpen procedure (when no usable GRILL.md exists):**

1. Restate the current understanding in 2–3 sentences: actor, pain, approximate scope, constraints, and what "done" appears to mean.
2. Self-serve codebase-answerable gaps via doc-fetcher/Explore only when the answer is in the repo; do not ask the user what tools can answer.
3. Ask at most the highest-signal clarification at a time, with a recommended answer. Keep it conversational prose; this is not a checklist and not a full `/z-grill` interview.
4. Stop when the problem is buildable enough to plan, or when the shared component says material alternatives remain. A `route_to_brainstorm` result becomes the Phase 0.5 Brainstorm ask recommendation; it does not auto-dispatch `/z-brainstorm`.

Write `$Z_HARNESS_PLAN_DIR/GRILL.md` on convergence:

```markdown
## Sharpened problem

<2–4 sentences naming the goal, intended outcome, constraints, and what observable completion means.>

## Open branches

<Unresolved alternatives or "none". Material alternatives feed the Brainstorm ask gate.>
```

Emit a `sharpen_gate` event with `decision` (`existing_grill` or `sharpened`) and `recommendation` (`proceed` or `ask_brainstorm`):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_gate \
  "$(printf '{"decision":"%s","recommendation":"%s","grill_md_existed":%s}' \
    "<existing_grill|sharpened>" "<proceed|ask_brainstorm>" "<true|false>")"
```

### 0.5 Brainstorm ask gate (no auto-route)

After sharpening, decide whether to recommend `/z-brainstorm`. Recommend it when `GRILL.md` has material alternatives, the user is unsure about framing, architecture/product direction matters, or the plan would be expensive to reverse. Recommend skipping when the task is narrow, the approach is already chosen, or remaining forks are minor implementation details.

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the brainstorm choice via their native channel and await a response. Silent omission is forbidden. -->
Ask the user whether to run `/z-brainstorm`:

- **Run brainstorm** — stop this `/z-plan` run after writing a route-decision artifact that points to `/z-brainstorm <slug>`. The user or watcher invokes the command; `/z-plan` never auto-dispatches it.
- **Skip brainstorm** — write `$Z_HARNESS_PLAN_DIR/archive/$RUN/brainstorm-choice.json` with `{"choice":"skipped"}` and continue. This explicit skip prevents repeated route nudges in later route checks.
- **Use existing framing** — if `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists with a selected user framing, record `{"choice":"existing","path":"BRAINSTORM.md"}` and continue.

If brainstorming was run before this `/z-plan` invocation, consume only the user-selected framing from `BRAINSTORM.md`; do not treat raw ideator alternatives as approved scope.

### 0.6 Planning-entry watcher checkpoint seam

After `GRILL.md` and any user-approved `BRAINSTORM.md` choice are stable, evaluate the shared clear-context watcher before entering high-context planning via one `checkpoint-seam.sh` call (SKILL-STYLE.md §2). This seam is an opportunity to checkpoint, not an unconditional `/clear`.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/checkpoint-seam.sh" \
  plan-entry "$Z_HARNESS_PLAN_DIR/GRILL.md" "/z-plan $Z_HARNESS_SLUG" \
  --producer z-plan \
  --next-step "Resume /z-plan for $Z_HARNESS_SLUG from GRILL.md and optional BRAINSTORM.md; continue conversational planning." \
  --hash "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md"
SEAM_RC=$?
case "$SEAM_RC" in
  0) ;;  # below threshold, or already fast-forwarded — continue
  1) exit 0 ;;  # new checkpoint written — pause here, not an error; next invocation resumes
  2)
    RB_HALT_REASON="context pressure estimate failed in strict mode at plan-entry seam"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
    ;;
esac
```

---

**Do not take the prompt's premises for granted.** If precontext artifacts were detected in Setup step 10, **inject their content here** as input to the premise check:
- **One-way gate active** (`artifact_kind: approach_synthesis`): inject RESEARCH.md content only (core hypothesis, approach decision matrix summary, mechanical rank-ordering). Do not inject MAP.md or BRAINSTORM.md.
- **One-way gate inactive** (component-file mode): inject MAP.md (or legacy RESEARCH.md treated as MAP.md) findings and BRAINSTORM.md chosen framing. If EXPLORE.md exists and is non-stale, inject its findings as supplementary terrain context — note the depth level (quick findings are bounded; standard findings are more durable). If both MAP.md and EXPLORE.md exist, prefer MAP.md for authoritative terrain and treat EXPLORE.md as supplementary or bridging context.
- **GRILL.md present** (independent of one-way gate): inject `## Sharpened problem` and `## Killed scope` sections as additional premise framing. Do not re-inject information already covered by MAP.md or RESEARCH.md — if both are present, treat GRILL.md as supplementary problem-statement context only (scope constraints, sharpened goal statement) and skip duplicating factual findings already present in MAP/RESEARCH.

Do not re-derive context already covered by these artifacts.

Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
- Is there a materially better path the user hasn't considered?

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface any premise
     concern to the user via their native channel and await a response before
     proceeding. Silent omission is forbidden. -->
If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.

If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.

Checkpoint: `phase0-premise.md`.

## Phase 1 — Exploration

**RESEARCH.md one-way gate shortcut** (when `artifact_kind: approach_synthesis` + `status: complete` detected in Setup step 10): If RESEARCH.md is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately using the new RESEARCH.md schema (matrix + evidence gaps):

- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `## Approach decision matrix` section has ≥1 cell with `OK` or `RISKY` verdict citing a file in the task's likely-touched set.
- **Skip Explore** iff RESEARCH.md is non-stale AND its `## Evidence gaps` section is empty (no `UNVERIFIED` cells aggregated).

The four resulting cases (one-way gate active):
- **(a) Skip doc-fetcher only** — matrix has OK/RISKY cell citing a touched file but Evidence gaps non-empty → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — matrix has no OK/RISKY cell for touched files but Evidence gaps empty → run doc-fetcher, skip Explore.
- **(c) Skip both** — matrix has OK/RISKY cell for touched files AND Evidence gaps empty → skip both, proceed to Phase 2.
- **(d) Run both** — RESEARCH.md is stale, absent in gate-active mode, or meets neither skip condition → run both doc-fetcher and Explore.

**Legacy RESEARCH.md / component-file shortcut** (when one-way gate is inactive — MAP.md or legacy RESEARCH.md detected in Setup step 10): If MAP.md (or legacy RESEARCH.md treated as MAP.md) is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:

- **Skip doc-fetcher** iff MAP.md (or legacy RESEARCH.md) is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- **Skip Explore** iff MAP.md (or legacy RESEARCH.md) is non-stale AND its `Open questions:` section is empty.

The four resulting cases (gate inactive):
- **(a) Skip doc-fetcher only** — MAP.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — MAP.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
- **(c) Skip both** — MAP.md has findings for touched files AND no open questions → skip both, proceed to Phase 2.
- **(d) Run both** — MAP.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.

**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.

### 1a. Dispatch doc-fetcher (if INDEX.json exists)

If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the Agent() call. The doc-fetcher phase
     cannot proceed without subagent support; skip conditions in Phase 1 still
     apply (command may continue without doc-fetcher grounding). -->
```
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the task>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed to Explore with no grounding. If it returns `STATUS: partial`, Explore must fill the gap it named.

If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
```

### 1b. Explore for gaps (Haiku by default)

Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.

**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the Explore Agent() call. The command
     cannot perform codebase exploration without subagent support; document the
     gap and proceed to Phase 2 with reduced context. -->
```
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Find <thing> related to <slug>",
  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
)
```

**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.

**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore (even Haiku) is a repo-mapping pass that consumes meaningful cache-read context. In the data-overhaul run, 5 Opus Explores ate 13.9 M tokens — ~93% of the entire planning budget. Haiku materially cuts that, but the cap stays: if 3 is not enough, prefer direct Read/Grep/Glob from the orchestrator over a 4th Explore. Override via `workflow.max_explore` in config (default 3) only with explicit user request.

Output a one-paragraph context summary. Checkpoint: `phase1-context.md`.

## Phase 2 — Decisions document

**GRILL.md decision seeding** (if GRILL.md was detected in Setup step 10): before enumerating decisions, inject the `## Open branches` section from GRILL.md as candidate pre-seeded decisions. Each open branch is a decision the user already identified as unresolved — promote it to a decision entry in `decisions.md` with its stated options (if any) and a note that it originated from GRILL.md. Do not duplicate decisions already surfaced by MAP.md or RESEARCH.md analysis; if the same branch appears in multiple artifacts, merge them into one decision entry.

Enumerate **every** decision needed to implement this task — obvious and non-obvious. Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/decisions.md`. For each decision:

- **Decision:** what's being decided
- **Options:** ≥1 candidate, with one-line tradeoffs
- **Tentative call:** your current pick
- **Consult? (yes/no):** apply the rules below
- **Trigger:** which rule made it consult-worthy (if yes)

### Consultation rules

A decision is **non-obvious (consult)** if *any* applies:

- Introduces a new external dependency
- Defines or changes a public API / module boundary / wire format
- Picks an algorithm or data structure where Big-O or memory differ between candidates
- Touches concurrency, shared state, or ordering guarantees
- Touches persistence: schema, migration, indexes, retention
- Names something on a public surface (hard to rename later)
- Affects >1 module or crosses a layer boundary
- **Reversibility:** if wrong, >1 hour to undo
- **Articulation:** you can name ≥2 candidate options with materially different tradeoffs

A decision is **obvious (skip consult)** if:
- Following an existing convention in the same file/module
- Local variable naming, internal helper structure
- Mechanical refactor with no behavior change
- Bug fix with root cause already identified

## Phase 2.5 — User gate

Present `decisions.md` to the user **in prose — a synthesis, not a raw file dump and not a popup volley**. For each decision, state in plain language: what is being decided, your tentative call, why, the strongest rejected alternative, and what would flip it. Then the user is the gate:
- Can flip any decision's consult flag
- Can override your tentative call
- Can kill scope

**Hard cap: 5 consult-flagged decisions per bundle.** If more, ask the user to pick the top 5 or split the plan into multiple `/z-plan` runs.

Before presenting the decisions doc for approval, run the `check-no-ask` resolver for `workflow.plan_decisions_approval`:

```bash
RESOLVED_DECISIONS="$(python3 scripts/config.py resolve-question workflow.plan_decisions_approval)"
RESOLVE_DECISIONS_EXIT=$?

if [[ $RESOLVE_DECISIONS_EXIT -ne 0 ]]; then
  # Exit codes: 2=bad invocation, 3=unknown question_id, 4=I/O error.
  # In all error cases, fall through to ask the user normally — never silently skip.
  echo "resolve-question failed (exit $RESOLVE_DECISIONS_EXIT); falling back to ask" >&2
  RESULT_DECISIONS="ask"; SOURCE_DECISIONS="error"
else
  RESULT_DECISIONS="$(echo "$RESOLVED_DECISIONS" | jq -r .result)"
  SOURCE_DECISIONS="$(echo "$RESOLVED_DECISIONS" | jq -r .source)"
fi
```

Branch on `$RESULT_DECISIONS`:
- `halt`: emit `plan_halt` event — do NOT invoke `AskUserQuestion`. A subsequent `/z-plan` resume re-enters at Phase 2.5. This halt occurs after a successful preflight, so it MUST go through the halt-finalize + teardown funnel (below) — never a bare `exit`:
  ```bash
  if [[ "$RESULT_DECISIONS" == "halt" ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "${RUN:-z-plan}" plan_halt \
      "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.plan_decisions_approval","rule_id":"no_ask_halt"}')"
    echo "halt: no_ask_blocked on workflow.plan_decisions_approval" >&2
    RB_HALT_REASON="no_ask_blocked on workflow.plan_decisions_approval"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
  fi
  ```
- `skip`: accept the decisions doc silently — no AskUserQuestion. Emit `askuser_skipped` event with `{question_id: "workflow.plan_decisions_approval", source: "$SOURCE_DECISIONS"}` and proceed to Phase 3.
<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the decisions doc
     approval question via their native channel when result is "prefill" or "ask".
     Silent omission is forbidden. -->
- `prefill` or `ask`: proceed normally — block here until the user has approved the decisions doc.

Block here until the user has approved the decisions doc.
```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && <PushNotification: decisions ready for approval>
```

## Phase 3 — Bundled cross-LLM consultation

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip all consultant Agent() calls. Phase 3
     cannot complete without subagent support; document the gap in
     phase3-decisions-final.md and proceed to Phase 4 without cross-LLM input. -->

**Intent-level consult policy guard (intent-mode only).** Before any other guard, check `INTENT_CONSULT_POLICY` (set in Mode detection). This guard only fires when `PLANNING_MODE=intent`; in legacy mode (`PLANNING_MODE=full` or `INTENT_LEVEL=""`), it is a no-op.

```bash
# _PHASE3_CONSULT_SKIP is the structural skip flag for Phase 3.
# Set to 1 when L1 forces a skip or L2 user declines; 0 otherwise (default: run consult).
_PHASE3_CONSULT_SKIP=0

if [[ "$PLANNING_MODE" == "intent" ]]; then
  case "${INTENT_CONSULT_POLICY:-optional}" in
    skip)
      # L1 (quick): skip Phase-3 cross-LLM consult entirely.
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
        "$RUN" consult_skipped \
        "$(printf '{"phase":3,"reason":"intent_level_L1_quick","intent_level":"%s"}' "$INTENT_LEVEL")"
      # Copy decisions.md to phase3-decisions-final.md with a note that consult was skipped at L1.
      cp "$Z_HARNESS_PLAN_DIR/archive/$RUN/decisions.md" \
         "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md" 2>/dev/null || true
      printf '\n---\n_Consult skipped: L1 Quick — no cross-LLM review at this level._\n' \
        >> "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md" 2>/dev/null || true
      # Structural skip: set flag so the entire consult body below is bypassed.
      _PHASE3_CONSULT_SKIP=1
      ;;
    optional)
      # L2 (standard): offer the user a one-shot chance to skip consult.
      # Unattended (Z_HARNESS_NO_ASK set): default to skip.
      if [[ -n "${Z_HARNESS_NO_ASK:-}" ]]; then
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
          "$RUN" consult_skipped \
          "$(printf '{"phase":3,"reason":"intent_level_L2_user_skipped","intent_level":"%s","source":"unattended_default"}' "$INTENT_LEVEL")"
        cp "$Z_HARNESS_PLAN_DIR/archive/$RUN/decisions.md" \
           "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md" 2>/dev/null || true
        _PHASE3_CONSULT_SKIP=1
      else
        # Interactive: load-bearing heartbeat before user wait, then ask.
        if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
            --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
            --command /z-plan || true
        fi
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
          '{"phase":3,"reason":"L2_optional_consult_gate"}'
        # <!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must skip this
        #      optional consult gate and treat it as "skip consult". Silent omission is forbidden —
        #      default to skip in unattended mode. -->
        AskUserQuestion "Planning depth is L2 (Standard). Run the cross-LLM consult?
It adds depth for multi-file decisions but costs extra tokens." \
          ["Yes, run consult (recommended for non-trivial changes)", "No, skip consult"]
        # _L2_CONSULT_CHOICE = the user's selection ("Yes..." or "No...")
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
          '{"phase":3,"reason":"L2_optional_consult_gate"}'
        if [[ "$_L2_CONSULT_CHOICE" == No* ]]; then
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
            "$RUN" consult_skipped \
            "$(printf '{"phase":3,"reason":"intent_level_L2_user_skipped","intent_level":"%s"}' "$INTENT_LEVEL")"
          cp "$Z_HARNESS_PLAN_DIR/archive/$RUN/decisions.md" \
             "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md" 2>/dev/null || true
          _PHASE3_CONSULT_SKIP=1
        fi
        # On "Yes": _PHASE3_CONSULT_SKIP stays 0 — fall through to consult body below.
      fi
      ;;
    full)
      # L3 (deep): full consult — fall through to the consult-off guard and panel below.
      # _PHASE3_CONSULT_SKIP remains 0.
      ;;
  esac
fi
```

The entire Phase 3 consult body (consult-off guard + panel dispatch) is wrapped in a single structural guard that skips it entirely when `_PHASE3_CONSULT_SKIP=1` (L1 forced skip or L2 user declined):

```bash
if [[ "${_PHASE3_CONSULT_SKIP:-0}" -eq 0 ]]; then
  # --- Phase 3 consult body begins here ---
```

**Consult-off guard.** Before spawning any consultant, check the runtime signal:

```bash
CONSULT_PROVIDER="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-provider.py" consultant_primary 2>/dev/null)"
```

If `CONSULT_PROVIDER == "none"` (i.e. `runtime.consult = "off"` in config):
- Skip all consultant Agent() calls entirely.
- Record tentative decisions as final in `phase3-decisions-final.md`.
- Emit a `consult_skipped` event:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "$RUN" consult_skipped \
    '{"phase":3,"reason":"Z_HARNESS_CONSULT=off"}'
  ```
- Proceed directly to Phase 4.

**Consultant dispatch.** Spawn **both** consultants in parallel in a single message:

- `Agent(subagent_type="consultant-primary", ..., prompt="...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="consultant-secondary", ..., prompt="...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`

Each gets the **entire approved decisions doc** with the consult-flagged decisions highlighted. Two calls total, regardless of feature size.

When all consultants return:
1. For each recommendation, articulate **one concrete reason it might be wrong** before accepting it. This is mechanical, not optional.
2. Synthesize. Make the final call yourself, citing which inputs you weighed.
3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.

Save transcripts (the consultants do this themselves). Checkpoint: `phase3-decisions-final.md`.

**Degraded-consult disclosure.** If any consultant did not return a normal response — rate-limited, fell back, errored, or was skipped (e.g. `consult_done` carries a `*_status` other than `ok`, such as `rate_limited_fallback`) — prepend a line to the decisions summary you present in Phase 5: "Consult degraded — `<provider>` unavailable (`<reason>`); treated as effectively single-LLM, weigh the cross-check lower." Record the degraded status in the `consult_done` event payload so `/z-stats` and `/z-improve` can see it. Do not silently present a single-LLM consult as if both arms agreed.

```bash
fi  # end of _PHASE3_CONSULT_SKIP guard — L1/L2-declined paths rejoin here after Phase 4.
```

## Phase 4 — Final clarifications

If anything is still unclear about scope, constraints, or success criteria — ask the user. No silent assumptions.

## Phase 5 — Present + approve

**Intent-mode approval model:** keep this phase conversational. For `PLANNING_MODE=intent`, do not present a giant technical decision dossier as the default. Present the sharpened problem, selected brainstorm framing (if any), non-goals, constraints, and any truly high-impact decisions in plain language. Boring implementation defaults are recorded as LLM-derived details, not user gates.

Before writing the final `INTENT.md`, run a bounded 1–2 pass iteration loop:

1. Draft the intent from `GRILL.md`, optional selected `BRAINSTORM.md`, Phase 1 grounding, and approved high-impact decisions.
2. Ask the user: "What feels wrong, missing, over-scoped, or not observable?"
3. Apply corrections and repeat at most once more by default. Stop early when the user says the intent matches.

After the iteration loop and before final approval, run an **LLM concern/decision flagging pass**. The pass reads the draft `INTENT.md`, `GRILL.md`, optional `BRAINSTORM.md`, and grounding notes, then writes `$Z_HARNESS_PLAN_DIR/archive/$RUN/intent-readthrough-flags.md` with:

- concerns and risky assumptions;
- unresolved decisions the user should notice;
- acceptance criteria that may be non-observable;
- possible scope creep;
- irreversible or public API/schema choices;
- places implementation convenience may diverge from user intent.

Then ask whether to fold in an audit-plan scan before the final read-through. Recommend **run audit** for medium/large/risky plans and **skip audit** for narrow obvious plans. This is an ask, not an automatic `/z-audit-plan` handoff. When the user chooses audit, run the audit-plan review inline or as the existing `/z-audit-plan` machinery permits, and append findings to `intent-readthrough-flags.md`. When the user skips, record the skip in the same file.

Final read-through input for intent mode is: final `INTENT.md` draft + `intent-readthrough-flags.md` + optional audit findings. The user chooses approve, amend, run a post-draft grill, route back to sharpen/brainstorm, or stop.

```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && <PushNotification: "Decisions ready for review.">
```

Render the final read-through as a **single prose plan brief**, not a raw artifact dump and not a per-decision popup sequence. The brief must contain, in this order:

1. **Intent in plain language** — the sharpened problem, selected brainstorm framing if any, non-goals, constraints, and the outcome the user is asking for.
2. **Approach** — the chosen approach, why it fits, and the strongest rejected approach with the reason it lost.
3. **High-impact decisions** — each decision with the actual tradeoff, tentative call, strongest rejected alternative, and what would flip the call. Do not include boring implementation defaults.
4. **Shortcuts** — each shortcut as one record: the looser path being taken, the robust alternative it bypasses, and the cost or risk. If there are no shortcuts, say "none".
5. **Read-through flags** — render the contents of `intent-readthrough-flags.md` inline as the investigation agenda: concerns, risky assumptions, unresolved decisions, possible scope creep, non-observable acceptance criteria, irreversible/public API/schema choices, and audit findings if present. Do not leave these only on disk.
6. **Acceptance criteria** — the observable checklist the plan must satisfy.

Keep the brief dense and decision-oriented. It should give the user everything needed to approve or challenge the plan before any gate appears.

**Shortcut telemetry before the single gate.** The **Shortcuts** section presented above is a list, one record per shortcut, each with three fields: the path being taken (what's being skipped), the robust alternative, and the cost. The orchestrator iterates that list and calls `surface-shortcut.sh` **once per shortcut record**, binding `chosen` = the path the shortcut takes (the thing being skipped/the looser route) and `declined` = the named robust alternative that shortcut bypasses. Loop over the actual records — there is no fixed count. This call is telemetry and final-gate preparation; it must not create a separate popup per shortcut.

```bash
# Callsite 2 — Phase-5 shortcut surface: one surface-shortcut.sh call per record.
# RUN is already set/exported by Setup step 2; surface-shortcut.sh reads the RUN
# env var to attribute the shortcut_proposed event, so export it here.
export RUN="$RUN"
# Drive this loop from the Shortcuts section the orchestrator just presented:
# for each record, SHORTCUT_CHOSEN = the looser path this shortcut takes,
# SHORTCUT_DECLINED = the robust alternative it bypasses, SHORTCUT_WHY = its cost note.
# (The orchestrator extracts these three fields per record from the Shortcuts list;
#  iterate over every record — do not assume a single shortcut.)
for_each_shortcut_record() {  # conceptual loop body — run once per Shortcuts record
  SURFACE_RC=0
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/surface-shortcut.sh" \
    --chosen "$SHORTCUT_CHOSEN" \
    --declined "$SHORTCUT_DECLINED" \
    --why "$SHORTCUT_WHY" || SURFACE_RC=$?
  # ... append this record to FINAL_GATE_SHORTCUTS if SURFACE_RC indicates it needs approval ...
}
```

For each shortcut record, handle the three `SURFACE_RC` cases explicitly (per the T009 contract):
- **`SURFACE_RC -eq 1`** — record this shortcut in the final approval gate. It is not approved until the user approves the full brief.
- **`SURFACE_RC -eq 0`** — no-op (`--declined` was empty, so this record names no robust alternative and is not a shortcut): proceed without an ask for this record.
- **`SURFACE_RC -eq 2`** — INFRA ERROR (RUN unset, `--chosen` empty, or telemetry lost). Surface a diagnostic in the final brief ("shortcut telemetry failed for this record — approval is required before proceeding"), then record this shortcut in the final approval gate. Fail-safe: ask in the single final gate rather than silently approve the shortcut.

Default to the robust alternative if the user does not approve the final brief. A shortcut is approved only when the final gate answer explicitly approves the brief that includes that shortcut record.

<!-- RUNTIME-GATE: ask_user; category=shortcut; non-supporting drivers must surface this final plan-brief approval gate via their native channel and await a response before proceeding. This single gate covers high-impact decisions and any listed shortcuts; category=shortcut is intentional because approving the brief may approve a looser path over a robust alternative. Silent omission is forbidden. -->
After presenting the full prose brief, ask once:

```text
Choose how to handle this plan brief:
- Approve as written
- Reject shortcut(s); use robust alternative(s)
- Amend the brief
- Grill the draft
- Return to sharpen/brainstorm
- Stop
```

Branch on the answer:
- **Approve as written** — treat the high-impact decisions and listed shortcuts as approved; proceed to Phase 6.
- **Reject shortcut(s); use robust alternative(s)** — replace each rejected shortcut with its named robust alternative, update the draft `INTENT.md` and `intent-readthrough-flags.md` as needed, then re-render the full prose brief and ask this same gate again. If multiple shortcuts exist and the user wants to reject only some, capture the selected shortcut IDs in prose before revising; do not spawn a separate popup per shortcut.
- **Amend the brief** — collect the requested edits, update the draft `INTENT.md` and `intent-readthrough-flags.md` as needed, then re-render the full prose brief and ask this same gate again.
- **Grill the draft** — run the post-draft grill loop below, fold accepted answers back into the draft `INTENT.md` / flags, then re-render the full prose brief and ask this same gate again.
- **Return to sharpen/brainstorm** — route back to Phase 0 or Phase 0.5 according to what changed; do not proceed to Phase 6.
- **Stop** — halt cleanly through the Run Brief halt-finalize path.

**Post-draft grill loop.** This is an inline `/z-grill`-style interrogation of the drafted plan, not an automatic handoff to the `/z-grill` command. Use `intent-readthrough-flags.md` as the primary question queue:

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface each post-draft grill question via their native channel and await a response before continuing the grill loop. Silent omission is forbidden. -->
- Ask one highest-signal question at a time.
- State the recommended answer before asking.
- Self-serve codebase-answerable questions with existing grounding or Explore before asking the user.
- Prefer questions that would change intent, scope, acceptance criteria, public API/schema choices, or execution ordering.
- Stop when no remaining question would materially change the plan, or when the user says the draft is sufficiently clear.

Write the loop transcript to `$Z_HARNESS_PLAN_DIR/archive/$RUN/post-draft-grill.md`, emit `post_draft_grill` with `question_count`, `source: "intent-readthrough-flags"`, and `transcript_path`, append any accepted corrections to `intent-readthrough-flags.md`, and update the draft `INTENT.md` before returning to the final prose brief.

Block here until the final plan brief is approved or the user chooses a non-approval exit.

## Phase 6 — Write SPEC.md / PLAN.md / TASKS.md (legacy) / INTENT.md (intent-mode)

```bash
if [[ "$PLANNING_MODE" == "intent" ]]; then
  # ---------------------------------------------------------------------------
  # INTENT.md writer (T006).
  # Sections required by level:
  #   quick    (L1): ## Intent  +  ## Acceptance checklist
  #   standard (L2): ## Intent  +  ## Not doing  +  ## Consider for this  +  ## Acceptance checklist
  #   deep     (L3): all four sections (same as L2)
  # ---------------------------------------------------------------------------
```

**INTENT.md writer (intent-mode only).**

Author an `INTENT.md` document at `$Z_HARNESS_PLAN_DIR/INTENT.md`. Populate it from the conversational intent loop: `GRILL.md` `## Sharpened problem`, optional user-selected `BRAINSTORM.md` framing, Phase 1 grounding, approved high-impact decisions, the 1–2 user iteration corrections from Phase 5, and any concerns/audit findings the user accepted. Do not transcribe raw brainstorm alternatives or consultant chatter as approved scope.

**Frontmatter** — all six fields are required:

```markdown
---
artifact: intent
slug: <$Z_HARNESS_SLUG>
level: <$INTENT_LEVEL — quick|standard|deep>
generated_at: <ISO UTC timestamp, e.g. 2026-06-16T12:00:00Z>
frozen_at: pending
planning_mode: intent
---
```

**Sections** — required sections depend on level:

| Level | `## Intent` | `## Not doing` | `## Consider for this` | `## Acceptance checklist` |
|-------|-------------|----------------|------------------------|---------------------------|
| quick (L1) | required | optional | optional | **always required** |
| standard (L2) | required | **required** | **required** | **always required** |
| deep (L3) | required | **required** | **required** | **always required** |

Section content guidance:
- **`## Intent`** — 2–4 sentence narrative: what this effort accomplishes and why. No implementation detail.
- **`## Not doing`** — explicit scope boundaries (one sentence each). Required at L2+; omit entirely at L1 unless needed for clarity.
- **`## Consider for this`** — situational constraints: budget, tier, domain gotchas, risks worth tracking. Required at L2+; omit entirely at L1 unless needed.
- **`## Acceptance checklist`** — observable, verifiable `[ ]` criteria; one per line. Each criterion must be checkable (not vague "runs" or "works" with no observable object). At least one criterion is required.

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface any criterion
     lint failures to the user via their native channel and halt before writing INTENT.md.
     Silent omission is forbidden. -->
**Validation gate (D8) — compose to temp file, validate, then atomically promote.**

After composing the INTENT.md content, write it to a **temp file** (not the final path) so that a failing validation never leaves a bad INTENT.md on disk:

```bash
INTENT_TEMP="$(mktemp /tmp/intent-draft-XXXXXX.md)"
# Write the composed content to the temp file.
# (Orchestrators write their composed string here; shell-mode: cat > "$INTENT_TEMP".)
```

Run both validators on the temp file — `validate-intent` checks frontmatter fields and required per-level sections; `lint-criteria` checks that acceptance criteria are observable:

```bash
INTENT_SCHEMA_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/intent-schema.py" \
  validate-intent "$INTENT_TEMP" "$INTENT_LEVEL" 2>&1)"
INTENT_SCHEMA_RC=$?

INTENT_LINT_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/intent-schema.py" \
  lint-criteria "$INTENT_TEMP" 2>&1)"
INTENT_LINT_RC=$?
```

Combine failures (non-zero from either validator means the gate fires):

```bash
INTENT_GATE_RC=$(( INTENT_SCHEMA_RC != 0 || INTENT_LINT_RC != 0 ))
INTENT_GATE_OUT="${INTENT_SCHEMA_OUT}${INTENT_LINT_OUT}"
```

If `INTENT_GATE_RC != 0` (one or both validators failed):

1. Show the user the combined output from `$INTENT_GATE_OUT`. Schema failures report missing frontmatter fields or missing required sections; lint failures are formatted as `LINE <n>: <criterion text>`.
2. Explain the rules:
   - **Schema**: all six frontmatter fields required; `## Not doing` and `## Consider for this` required at standard/deep.
   - **Criteria**: must be observable — e.g. "exits 0", "outputs N lines", "raises HTTP 400" are observable; bare "runs" or "works" with no object are not.
3. Ask the user to revise via `AskUserQuestion`:

```
AskUserQuestion(
  header: "INTENT.md validation failed — issues found:
           <INTENT_GATE_OUT formatted as bullet list>
           Describe fixes and I will recompose and re-validate, or abandon.",
  options: [
    "I've described fixes — recompose and re-validate",
    "Abandon — I'll fix INTENT.md manually"
  ]
)
```

  - **"I've described fixes — recompose and re-validate"**: apply the user's described edits to the draft, overwrite `$INTENT_TEMP`, then re-run both validators. Repeat until both pass or user abandons. On each retry cycle, emit an `intent_lint_retry` event:
    ```bash
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_lint_retry \
      "$(printf '{"attempt":%d,"failures":%d}' "$_LINT_ATTEMPT" "$_LINT_FAILURE_COUNT")"
    ```
    Discard the temp file on abandon:
  - **"Abandon"**: `rm -f "$INTENT_TEMP"`. Emit `intent_lint_abandoned` event and halt. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `INTENT.md validation abandoned by user`:
    ```bash
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_lint_abandoned \
      "$(printf '{"failures":%d}' "$_LINT_FAILURE_COUNT")"
    ```

If `INTENT_GATE_RC == 0` (both validators pass): emit `intent_lint_passed`, then **atomically promote** the temp file to the final path and clean up:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_lint_passed \
  "$(printf '{"level":"%s","slug":"%s"}' "$INTENT_LEVEL" "$Z_HARNESS_SLUG")"

mv "$INTENT_TEMP" "$Z_HARNESS_PLAN_DIR/INTENT.md"
```

After the atomic move, emit `intent_written`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_written \
  "$(printf '{"level":"%s","slug":"%s","path":"%s"}' \
     "$INTENT_LEVEL" "$Z_HARNESS_SLUG" "$Z_HARNESS_PLAN_DIR/INTENT.md")"
```

```bash
else
  # Legacy path (planning_mode=full, or SPEC.md detected — Invariant 4).
  # T007: backward-compat SPEC detection is handled in Mode detection before this branch.
  # This else-branch runs when PLANNING_MODE=full (set by --full flag, config, or SPEC.md guard).
```

**Legacy path (planning_mode=full):**

Create `$Z_HARNESS_PLAN_DIR/SPEC.md` — per-file detailed spec: paths, exported surface, signatures, behavior, invariants, edge cases, error handling.

The SPEC.md must include a `## Planning Inputs` section near the top (after title/overview, before any per-file sections) listing which precontext artifacts contributed to this plan:

```markdown
## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| MAP.md | $Z_HARNESS_PLAN_DIR/MAP.md | <iso timestamp or "n/a"> |
| BRAINSTORM.md | $Z_HARNESS_PLAN_DIR/BRAINSTORM.md | <iso timestamp or "n/a"> |
| RESEARCH.md | $Z_HARNESS_PLAN_DIR/RESEARCH.md | <iso timestamp or "n/a"> |
| GRILL.md | $Z_HARNESS_PLAN_DIR/GRILL.md | <iso timestamp or "n/a"> |
```

Include only rows for artifacts that were actually present. If none were present, write: `none — fresh /z-plan run.`

Create `$Z_HARNESS_PLAN_DIR/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.

Create the initial legacy `$Z_HARNESS_PLAN_DIR/TASKS.md` in the same full-mode branch, before Phase 7. Break PLAN.md into small, independently-implementable tasks. Each task uses a `T001`-style ID, title, files touched, dependencies, acceptance criteria, and status `[ ]`. Size so each fits a fresh context window, target **10–20 tasks**, and preserve the remote-verify/docs-touched flags described in Phase 8 for any applicable task.

SPEC.md and PLAN.md obey **DRY / KISS / SOLID**. State explicitly how the plan respects each. TASKS.md is the executable task contract that Phase 7 reviews and Phase 8 checkpoints.

```bash
fi  # end of Phase 6 if/else: intent-mode (INTENT.md writer) vs legacy (SPEC/PLAN/TASKS writer)
```

## Phase 7 — Bundled final review

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip all Phase 7 consultant Agent() calls.
     Document the gap in the archive and proceed to Phase 8 without final
     review input. -->

**Pre-dispatch TASKS existence/generation guard.** Phase 7 reviews the primary artifact plus the initial task plan, so the guard below runs before the consult-off branch, prompt rendering, or any Phase 7 Agent dispatch. It guarantees the task plan exists and is not an amended-intent stale batch: Phase 8 still owns TASKS sanity, complexity/checkpoint work, scope seeding, workstreams, and handoff sequencing.

```bash
PHASE7_TASKS_PATH="$Z_HARNESS_PLAN_DIR/TASKS.md"
PHASE7_TASKS_STALE_REASON="$(python3 -c '
import re, sys
path = sys.argv[1]
try:
    text = open(path, encoding="utf-8").read()
except OSError:
    print("")
    raise SystemExit
m = re.search(r"^stale_reason:\s*(.+?)\s*$", text, re.M)
print(m.group(1).strip() if m else "")
' "$PHASE7_TASKS_PATH" 2>/dev/null || echo "")"
if [[ ! -f "$PHASE7_TASKS_PATH" || "$PHASE7_TASKS_STALE_REASON" == "amended-intent" ]]; then
  if [[ "$PLANNING_MODE" == "intent" ]]; then
    if [[ ! -f "$Z_HARNESS_PLAN_DIR/INTENT.md" ]]; then
      echo "ERROR: intent-mode Phase 7 cannot generate TASKS.md before INTENT.md exists." >&2
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
        '{"reason":"intent_missing_before_phase7_tasks"}' 2>/dev/null || true
      RB_HALT_REASON="intent artifact missing before Phase 7 TASKS guard"
      # include: _fragments/run-brief-halt-finalize-plan.md
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
        --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
      exit 1
    fi

    LEVEL_TASKS_FILE="$PHASE7_TASKS_PATH"
    LEDGER_FILE="$Z_HARNESS_PLAN_DIR/LEDGER.md"

    UNMET_CRITERIA_JSON="$(python3 -c "
import re, sys, json
content = open(sys.argv[1]).read()
m = re.search(r'## Acceptance checklist(.*?)(?=\n## |\Z)', content, re.S)
section = m.group(1) if m else ''
items = re.findall(r'- \[ \] (.+)', section)
print(json.dumps(items))
" "$Z_HARNESS_PLAN_DIR/INTENT.md" 2>/dev/null || echo '[]')"

    INTENT_BFS_LEVEL_CAP="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" \
      get workflow.intent_bfs_level_cap 2>/dev/null || echo "")"
    if [ -z "$INTENT_BFS_LEVEL_CAP" ] || [ "$INTENT_BFS_LEVEL_CAP" = "None" ]; then
      INTENT_BFS_LEVEL_CAP=6
    fi

    INTENT_TOKEN_BUDGET="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" \
      get cost.token_budget 2>/dev/null || echo "")"
    [ "$INTENT_TOKEN_BUDGET" = "None" ] && INTENT_TOKEN_BUDGET=""

    # <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface that intent-mode `/z-plan`
    #      requires `task-tree-generator` to create TASKS.md before Phase 7 review. Silent omission
    #      is forbidden; if the driver cannot dispatch subagents, halt with `plan_halt` rather than
    #      continuing to Phase 7 with a nonexistent tasks_path. -->
    GENERATOR_RETURN="$(Agent(
      subagent_type="task-tree-generator",
      description="Generate initial BFS level 0 task batch",
      prompt="intent_snapshot_path: ${Z_HARNESS_PLAN_DIR}/INTENT.md
ledger_path: ${LEDGER_FILE}
intent_readthrough_flags_path: ${Z_HARNESS_PLAN_DIR}/archive/${RUN}/intent-readthrough-flags.md
brainstorm_choice_path: ${Z_HARNESS_PLAN_DIR}/archive/${RUN}/brainstorm-choice.json
level: 0
unmet_criteria: ${UNMET_CRITERIA_JSON}
prior_level_outcomes: none
tasks_output_path: ${LEVEL_TASKS_FILE}
plan_dir: ${Z_HARNESS_PLAN_DIR}
level_cap: ${INTENT_BFS_LEVEL_CAP}
budget_tokens_remaining: ${INTENT_TOKEN_BUDGET:-}
task_id_start: 1
execution_strategy_required: true
task_to_intent_mapping_required: true"
    ))"

    GENERATOR_STATUS="$(printf '%s' "$GENERATOR_RETURN" | grep '^STATUS:' | head -1 | awk '{print $2}')"
    GENERATOR_TASKS_COUNT="$(printf '%s' "$GENERATOR_RETURN" | grep '^TASKS_WRITTEN:' | head -1 | awk '{print $2}')"
    GENERATOR_TERMINATION="$(printf '%s' "$GENERATOR_RETURN" | grep '^TERMINATION_CONDITION:' | head -1 | awk '{print $2}')"

    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_initial_tasks_generated \
      "$(printf '{"slug":"%s","status":"%s","tasks_written":%s,"termination_condition":"%s","path":"%s","phase":"phase7_pre_dispatch"}' \
        "$Z_HARNESS_SLUG" "${GENERATOR_STATUS:-unknown}" "${GENERATOR_TASKS_COUNT:-0}" \
        "${GENERATOR_TERMINATION:-unknown}" "$LEVEL_TASKS_FILE")" 2>/dev/null || true

    if [ "${GENERATOR_STATUS:-}" = "unable_to_complete" ] || [ "${GENERATOR_STATUS:-}" = "termination_guard" ] || [ ! -f "$LEVEL_TASKS_FILE" ]; then
      echo "ERROR: task-tree-generator did not produce initial TASKS.md before Phase 7 review." >&2
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
        "$(printf '{"reason":"phase7_intent_initial_tasks_failed","generator_status":"%s","termination_condition":"%s"}' \
          "${GENERATOR_STATUS:-unknown}" "${GENERATOR_TERMINATION:-unknown}")" 2>/dev/null || true
      RB_HALT_REASON="intent initial task generation failed before Phase 7"
      # include: _fragments/run-brief-halt-finalize-plan.md
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
        --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
      exit 1
    fi
  else
    echo "ERROR: full-mode Phase 7 requires $PHASE7_TASKS_PATH to exist before final review." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      "$(printf '{"reason":"full_mode_tasks_missing_before_phase7","path":"%s"}' "$PHASE7_TASKS_PATH")" 2>/dev/null || true
    RB_HALT_REASON="full-mode TASKS.md missing before Phase 7 review"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
  fi
fi
```

**Consult-off guard.** Before spawning any consultant, check the runtime signal:

```bash
CONSULT_PROVIDER_P7="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-provider.py" consultant_primary 2>/dev/null)"
```

If `CONSULT_PROVIDER_P7 == "none"` (i.e. `runtime.consult = "off"` in config):
- Skip all Phase 7 consultant Agent() calls entirely.
- Document the gap in the archive.
- Emit a `consult_skipped` event:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "$RUN" consult_skipped \
    '{"phase":7,"reason":"Z_HARNESS_CONSULT=off"}'
  ```
- Proceed directly to Phase 8.

**Phase 7 mode-aware input contract.** The final-review prompt always includes decisions and the task plan, but the primary planning artifact depends on `PLANNING_MODE`. This block is a runtime-expanded prompt payload, not a placeholder mapping. Every Phase 7 Agent prompt MUST include `planning_mode: $PLANNING_MODE` plus exactly one concrete artifact set:

- **Intent mode:** pass `INTENT.md` + `TASKS.md` + decisions. Do **not** ask for or synthesize `SPEC.md`/`PLAN.md` in intent mode.
  ```text
  planning_mode: $PLANNING_MODE
  intent_path: $Z_HARNESS_PLAN_DIR/INTENT.md
  tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md
  decisions_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md
  ```
- **Full mode:** pass `SPEC.md` + `PLAN.md` + `TASKS.md` + decisions.
  ```text
  planning_mode: $PLANNING_MODE
  spec_path: $Z_HARNESS_PLAN_DIR/SPEC.md
  plan_path: $Z_HARNESS_PLAN_DIR/PLAN.md
  tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md
  decisions_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md
  ```

Immediately before any Phase 7 Agent dispatch, build the rendered input block from the current mode and pass that same block to every arm:

```bash
if [[ "$PLANNING_MODE" == "intent" ]]; then
  PHASE7_MODE_AWARE_INPUT_BLOCK="$(cat <<EOF
planning_mode: $PLANNING_MODE
intent_path: $Z_HARNESS_PLAN_DIR/INTENT.md
tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md
decisions_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md
EOF
)"
else
  PHASE7_MODE_AWARE_INPUT_BLOCK="$(cat <<EOF
planning_mode: $PLANNING_MODE
spec_path: $Z_HARNESS_PLAN_DIR/SPEC.md
plan_path: $Z_HARNESS_PLAN_DIR/PLAN.md
tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md
decisions_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md
EOF
)"
fi

PHASE7_KERNEL_LINE=""
if [[ -n "${KERNEL_PATH:-}" ]]; then
  PHASE7_KERNEL_LINE=$'\n'"kernel_path: $KERNEL_PATH"
fi
```

**Consultant dispatch.** Spawn **both** consultants in parallel with the same rendered `$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE`:

- `Agent(subagent_type="consultant-primary", ..., prompt="MODE: plan-review\nCritique this plan. What's wrong, missing, or fragile?\n$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE")`
- `Agent(subagent_type="consultant-secondary", ..., prompt="MODE: plan-review\nCritique this plan. What's wrong, missing, or fragile?\n$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE")`

Apply findings that hold up under "one reason this might be wrong" scrutiny. Push back on the rest with documented reasoning.

## Phase 8 — TASKS.md checkpoint, sanity, and workstream finalization

By Phase 8, `$Z_HARNESS_PLAN_DIR/TASKS.md` must already exist: the Phase 7 pre-dispatch guard generated the intent-mode initial level-0 task plan, while full mode authored the legacy TASKS.md in Phase 6 and the guard halted if it was still missing. Phase 8 does not create the first TASKS.md. It performs the intent-mode schema sanity check, then the existing checkpoint work: legacy complexity stamps, scope seeding, workstream generation, post-artifact routing, and handoff sequencing.

```bash
if [[ "$PLANNING_MODE" == "intent" && -f "$Z_HARNESS_PLAN_DIR/INTENT.md" ]]; then
  LEVEL_TASKS_FILE="$Z_HARNESS_PLAN_DIR/TASKS.md"
  if [[ ! -f "$LEVEL_TASKS_FILE" ]]; then
    echo "ERROR: Phase 8 reached intent-mode TASKS sanity before Phase 7 generated TASKS.md." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      '{"reason":"phase8_tasks_missing_after_phase7_guard"}' 2>/dev/null || true
    RB_HALT_REASON="TASKS.md missing after Phase 7 pre-dispatch guard"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
  fi

  TASKS_SANITY_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/intent-schema.py" \
    validate-tasks "$Z_HARNESS_PLAN_DIR/INTENT.md" "$LEVEL_TASKS_FILE" 2>&1)"
  TASKS_SANITY_RC=$?
  if [ "$TASKS_SANITY_RC" -ne 0 ]; then
    printf '%s\n' "$TASKS_SANITY_OUT" >&2
    TASKS_SANITY_JSON="$(printf '%s' "$TASKS_SANITY_OUT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      "$(printf '{"reason":"intent_initial_tasks_sanity_failed","errors":%s}' "$TASKS_SANITY_JSON")" 2>/dev/null || true
    RB_HALT_REASON="intent initial task sanity failed"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
  fi

  # Seed active-plan scope from the initial TASKS.md. Best-effort, same as legacy.
  # <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to
  #      the user and skip the Agent() call. Scope seeding is advisory; the plan proceeds without it. -->
  SCOPE_JSON="$(mktemp)"
  Agent(
    subagent_type="scope-extractor",
    description="Scope for /z-plan intent overlap seed",
    prompt="repo_root: <abs path to repo root>
base: $Z_HARNESS_PLAN_DIR"
  ) > "$SCOPE_JSON" || true
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" update-scope     --run-id "$RUN" --scope-json "$SCOPE_JSON" || true
  rm -f "$SCOPE_JSON"

  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" heartbeat     --run-id "$RUN" --phase phase8 || true

  # Generate and validate workstreams/DAG metadata for all intent-mode plans.
  # This is load-bearing execution-strategy data, not an optional Hermes nicety:
  # if the generator cannot produce a valid manifest, halt before handoff.
  WORKSTREAMS_FILE="$Z_HARNESS_PLAN_DIR/workstreams.json"
  WORKSTREAM_GEN_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/generate-workstreams.py" \
    --slug "$Z_HARNESS_SLUG" --source z-plan --plan-dir "$Z_HARNESS_PLAN_DIR" 2>&1)"
  WORKSTREAM_GEN_RC=$?
  if [ "$WORKSTREAM_GEN_RC" -ne 0 ] || [ ! -s "$WORKSTREAMS_FILE" ]; then
    printf '%s\n' "$WORKSTREAM_GEN_OUT" >&2
    WORKSTREAM_GEN_JSON="$(printf '%s' "$WORKSTREAM_GEN_OUT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      "$(printf '{"reason":"phase8_workstreams_generation_failed","rc":%d,"output":%s,"path":"%s"}' \
        "$WORKSTREAM_GEN_RC" "$WORKSTREAM_GEN_JSON" "$WORKSTREAMS_FILE")" 2>/dev/null || true
    RB_HALT_REASON="intent workstreams generation failed"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
  fi

  WORKSTREAM_VALIDATE_OUT="$(python3 - "$WORKSTREAMS_FILE" 2>&1 <<'PYEOF'
from __future__ import annotations
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    print(f"{path}: cannot read valid JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)

errors = []
if data.get("protocol") != "hermes-v1":
    errors.append("protocol must be hermes-v1")
workstreams = data.get("workstreams")
merge_order = data.get("merge_order")
if not isinstance(workstreams, list) or not workstreams:
    errors.append("workstreams must be a non-empty list")
if not isinstance(merge_order, list):
    errors.append("merge_order must be a list")
workstream_entries = workstreams if isinstance(workstreams, list) else []
ids = [ws.get("id") for ws in workstream_entries if isinstance(ws, dict)]
if len(ids) != len(workstream_entries) or any(not isinstance(wid, str) or not wid for wid in ids):
    errors.append("every workstream must have a non-empty string id")
if isinstance(merge_order, list) and sorted(merge_order) != sorted(ids):
    errors.append("merge_order must be a permutation of workstream ids")
id_set = set(ids)
for ws in workstream_entries:
    if not isinstance(ws, dict):
        continue
    for dep in ws.get("depends_on", []):
        if dep not in id_set:
            errors.append(f"{ws.get('id', '<unknown>')} depends on unknown workstream {dep}")
if errors:
    for err in errors:
        print(err, file=sys.stderr)
    raise SystemExit(1)
print(json.dumps({"workstreams": len(workstreams), "merge_order": len(merge_order)}, separators=(",", ":")))
PYEOF
)"
  WORKSTREAM_VALIDATE_RC=$?
  if [ "$WORKSTREAM_VALIDATE_RC" -ne 0 ]; then
    printf '%s\n' "$WORKSTREAM_VALIDATE_OUT" >&2
    WORKSTREAM_VALIDATE_JSON="$(printf '%s' "$WORKSTREAM_VALIDATE_OUT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      "$(printf '{"reason":"phase8_workstreams_validation_failed","output":%s,"path":"%s"}' \
        "$WORKSTREAM_VALIDATE_JSON" "$WORKSTREAMS_FILE")" 2>/dev/null || true
    RB_HALT_REASON="intent workstreams validation failed"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
  fi
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" workstreams_generated \
    "$(printf '{"slug":"%s","path":"%s","source":"z-plan","validation":%s}' \
      "$Z_HARNESS_SLUG" "$WORKSTREAMS_FILE" "$WORKSTREAM_VALIDATE_OUT")" 2>/dev/null || true

  # Write the initial known-work graph for intent-mode /z-execute.
  # This graph is deliberately a frontier, not a claimed complete task tree:
  # /z-execute appends newly discovered nodes as implementation outcomes make
  # additional work knowable. Levels are scheduler depths over depends_on.
  WORK_GRAPH_FILE="$Z_HARNESS_PLAN_DIR/work-graph.json"
  WORK_GRAPH_OUT="$(python3 - "$Z_HARNESS_PLAN_DIR" "$RUN" "$Z_HARNESS_SLUG" 2>&1 <<'PYEOF'
from __future__ import annotations
import json, re, sys
from datetime import datetime, timezone
from pathlib import Path

plan_dir = Path(sys.argv[1])
run = sys.argv[2]
slug = sys.argv[3]
tasks_path = plan_dir / "TASKS.md"
out_path = plan_dir / "work-graph.json"

try:
    tasks_text = tasks_path.read_text(encoding="utf-8")
except OSError as exc:
    raise SystemExit(f"TASKS.md unreadable while writing work graph: {exc}") from exc

task_blocks = re.findall(r"^## (T\d{3}) — (.*?) `\[ \]`(.*?)(?=^## T\d{3} — |\Z)", tasks_text, re.M | re.S)
nodes = []
for task_id, title, body in task_blocks:
    files_m = re.search(r"^\*\*Files:\*\*\s*(.+)$", body, re.M)
    deps_m = re.search(r"^\*\*Depends on:\*\*\s*(.+)$", body, re.M)
    advances_m = re.search(r"^\*\*Advances:\*\*\s*(.+)$", body, re.M)
    raw_deps = [] if not deps_m else re.findall(r"T\d{3}", deps_m.group(1))
    nodes.append({
        "id": task_id,
        "kind": "implementation",
        "status": "ready" if not raw_deps else "blocked",
        "depends_on": raw_deps,
        "files": [part.strip().strip("`") for part in (files_m.group(1).split(",") if files_m else []) if part.strip()],
        "task_ref": f"TASKS.md#{task_id}",
        "advances": advances_m.group(1).strip() if advances_m else "unknown",
        "origin": {"command": "/z-plan", "run": run, "reason": "initial-known-frontier"},
        "fresh_session_required": False,
        "level_hint": 0,
    })

node_by_id = {node["id"]: node for node in nodes}
def depth(node_id, seen=None):
    seen = set() if seen is None else seen
    if node_id in seen:
        return 0
    seen.add(node_id)
    node = node_by_id.get(node_id)
    if not node or not node["depends_on"]:
        return 0
    return 1 + max((depth(dep, seen) for dep in node["depends_on"] if dep in node_by_id), default=0)
for node in nodes:
    node["level_hint"] = depth(node["id"])

payload = {
    "artifact": "known_work_graph",
    "schema_version": 1,
    "slug": slug,
    "planning_mode": "intent",
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "status": "open",
    "nodes": nodes,
    "append_log": [{
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "trigger": "initial",
        "source_node_id": None,
        "nodes_added": [node["id"] for node in nodes],
        "deferred_criteria": [],
    }],
}
tmp = out_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
tmp.replace(out_path)
print(out_path)
PYEOF
)"
  WORK_GRAPH_RC=$?
  if [ "$WORK_GRAPH_RC" -ne 0 ] || [ ! -s "$WORK_GRAPH_FILE" ]; then
    printf '%s\n' "$WORK_GRAPH_OUT" >&2
    WORK_GRAPH_JSON="$(printf '%s' "$WORK_GRAPH_OUT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      "$(printf '{"reason":"phase8_work_graph_generation_failed","rc":%d,"output":%s,"path":"%s"}' \
        "$WORK_GRAPH_RC" "$WORK_GRAPH_JSON" "$WORK_GRAPH_FILE")" 2>/dev/null || true
    RB_HALT_REASON="intent known-work graph generation failed"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
  fi
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" work_graph_written \
    "$(printf '{"slug":"%s","path":"%s","source":"z-plan","mode":"known_work_graph"}' \
      "$Z_HARNESS_SLUG" "$WORK_GRAPH_FILE")" 2>/dev/null || true

  # Execution strategy metadata for intent-mode /z-execute.
  # This is derived from TASKS.md + validated workstreams.json, with work-graph.json carrying scheduler state.
  EXECUTION_STRATEGY_OUT="$(python3 - "$Z_HARNESS_PLAN_DIR" "$RUN" 2>&1 <<'PYEOF'
from __future__ import annotations
import json, re, sys
from pathlib import Path

plan_dir = Path(sys.argv[1])
run = sys.argv[2]
tasks_path = plan_dir / "TASKS.md"
workstreams_path = plan_dir / "workstreams.json"
work_graph_path = plan_dir / "work-graph.json"
flags_path = plan_dir / "archive" / run / "intent-readthrough-flags.md"
out_path = plan_dir / "execution-strategy.md"

try:
    tasks_text = tasks_path.read_text(encoding="utf-8") if tasks_path.exists() else ""
except OSError as exc:
    raise SystemExit(f"TASKS.md unreadable while writing execution strategy: {exc}") from exc
task_blocks = re.findall(r"^## (T\d{3}) — (.*?) `\[ \]`(.*?)(?=^## T\d{3} — |\Z)", tasks_text, re.M | re.S)
tasks = []
for task_id, title, body in task_blocks:
    files = re.search(r"^\*\*Files:\*\*\s*(.+)$", body, re.M)
    advances = re.search(r"^\*\*Advances:\*\*\s*(.+)$", body, re.M)
    complexity = re.search(r"^\*\*Complexity:\*\*\s*(.+)$", body, re.M)
    tasks.append({
        "id": task_id,
        "title": title.strip(),
        "files": files.group(1).strip() if files else "unknown",
        "advances": advances.group(1).strip() if advances else "unknown",
        "complexity": complexity.group(1).strip() if complexity else "medium",
    })

if not workstreams_path.exists():
    raise SystemExit("workstreams.json missing after Phase 8 validation")
if not work_graph_path.exists():
    raise SystemExit("work-graph.json missing after Phase 8 work graph generation")
try:
    workstreams = json.loads(workstreams_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"workstreams.json became unreadable or invalid after Phase 8 validation: {exc}") from exc
try:
    work_graph = json.loads(work_graph_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"work-graph.json became unreadable or invalid after Phase 8 generation: {exc}") from exc
if not isinstance(workstreams, dict):
    raise SystemExit("workstreams.json root must be an object")
if not isinstance(work_graph, dict) or work_graph.get("artifact") != "known_work_graph":
    raise SystemExit("work-graph.json root must be a known_work_graph object")
parallel_groups = {}
for ws in workstreams.get("workstreams", []) if isinstance(workstreams, dict) else []:
    group = ws.get("parallel_group")
    parallel_groups.setdefault(str(group), []).append(ws.get("id", "<unknown>"))
parallel_groups.pop("None", None)

serial_blockers = []
for conflict in workstreams.get("file_conflicts", []):
    path = conflict.get("file") or conflict.get("path") or "<unknown>"
    serial_blockers.append(f"{path}: {', '.join(conflict.get('workstreams', []))}")

lines = [
    "# Execution strategy",
    "",
    "## Source of truth",
    "",
    "- INTENT.md is the user-approved contract.",
    f"- {flags_path.relative_to(plan_dir) if flags_path.exists() else 'archive/<run>/intent-readthrough-flags.md'} contains concerns, decisions, and optional audit-plan notes the user saw before approval when present.",
    "- TASKS.md maps each task to INTENT acceptance criteria via **Advances:** lines.",
    "- work-graph.json is the append-only known-work DAG. It starts with this frontier and /z-execute appends new nodes as outcomes reveal more work.",
    "- workstreams.json is validated conflict/scope metadata for safe dispatch; it is not the complete task tree.",
    "",
    "## Task-to-intent mapping",
    "",
]
for task in tasks:
    lines.append(f"- {task['id']} — {task['title']}: {task['advances']} (files: {task['files']}; complexity: {task['complexity']})")
if not tasks:
    lines.append("- none — TASKS.md had no pending canonical task blocks")

lines.extend(["", "## Parallel batches", ""])
lines.append("- Scheduler rule: compute ready nodes from work-graph.json (`status=ready` and all `depends_on` done), then dispatch up to the safe fan-out window. When a node returns, append newly knowable nodes before idling.")
if parallel_groups:
    for group, ids in sorted(parallel_groups.items()):
        lines.append(f"- parallel_group {group}: {', '.join(ids)}")
else:
    lines.append("- none declared by the validated workstreams.json; execute in DAG order and do not infer extra parallelism from missing metadata.")

lines.extend(["", "## Serial blockers", ""])
if serial_blockers:
    lines.extend(f"- {item}" for item in serial_blockers)
else:
    lines.append("- none recorded in the validated workstreams.json")

lines.extend([
    "",
    "## Review gates",
    "",
    "- Every task gets a reviewer pass.",
    "- Retry once on review failure.",
    "- Run aggregate review for larger, high-risk, or cross-cutting plans before declaring completion.",
    "",
    "## Checkpoint cadence",
    "",
    "- Use the shared context watcher at durable DAG settle points: all live tracks drained, work-graph.json flushed, TASKS.md updated, and LEDGER.md appended.",
    "- Never checkpoint while a node is in flight or before TASKS.md / LEDGER.md / work-graph.json state is flushed.",
])
try:
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
except OSError as exc:
    raise SystemExit(f"cannot write execution-strategy.md: {exc}") from exc
print(out_path)
PYEOF
)"
  EXECUTION_STRATEGY_RC=$?
  if [ "$EXECUTION_STRATEGY_RC" -ne 0 ] || [ ! -s "$Z_HARNESS_PLAN_DIR/execution-strategy.md" ]; then
    printf '%s\n' "$EXECUTION_STRATEGY_OUT" >&2
    EXECUTION_STRATEGY_JSON="$(printf '%s' "$EXECUTION_STRATEGY_OUT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      "$(printf '{"reason":"phase8_execution_strategy_failed","rc":%d,"output":%s,"path":"%s"}' \
        "$EXECUTION_STRATEGY_RC" "$EXECUTION_STRATEGY_JSON" "$Z_HARNESS_PLAN_DIR/execution-strategy.md")" 2>/dev/null || true
    RB_HALT_REASON="intent execution strategy generation failed"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
  fi
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" execution_strategy_written \
    "$(printf '{"path":"%s","source":"z-plan","planning_mode":"intent","derived_from_tasks":true,"workstreams_path":"%s","workstreams_validated":true}' "$Z_HARNESS_PLAN_DIR/execution-strategy.md" "$Z_HARNESS_PLAN_DIR/workstreams.json")" 2>/dev/null || true
  # T007: backward-compat SPEC detection is resolved upstream in Mode detection (Invariant 4).
  # When SPEC.md is present, PLANNING_MODE is forced to "full" before Phase 6 runs, so
  # INTENT.md is never written and this `if` branch is never entered for legacy slug dirs.
  # --- STRUCTURAL SKIP: the entire legacy SPEC/PLAN/TASKS checkpoint section below is inside the
  # `else` branch of this conditional. Do NOT add code between here and the matching `else` ---
else
  # The `else` closes when the legacy path (TASKS.md checkpoint/finalization) finishes — see the
  # closing `fi` at the end of the scope-seed + workstreams manifest block below.
```

**Legacy path (planning_mode=full, or INTENT.md not yet written):**

Full-mode `$Z_HARNESS_PLAN_DIR/TASKS.md` was authored in Phase 6 and must already have survived Phase 7 review. In Phase 8, finalize that legacy task plan: enforce task-count discipline, add complexity stamps, seed scope, and generate workstreams. If a driver reaches this point without TASKS.md, halt rather than letting post-artifact routing or handoff consume an incomplete plan.

```bash
if [[ ! -f "$Z_HARNESS_PLAN_DIR/TASKS.md" ]]; then
  echo "ERROR: Phase 8 reached full-mode TASKS checkpoint without TASKS.md." >&2
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
    '{"reason":"phase8_full_tasks_missing_after_phase7_guard"}' 2>/dev/null || true
  RB_HALT_REASON="full-mode TASKS.md missing after Phase 7 review"
  # include: _fragments/run-brief-halt-finalize-plan.md
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
    --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
  exit 1
fi
```

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the task-count
     overflow question ("Combine", "Ship as-is", "Restructure") via their native
     channel when >25 tasks are produced. Silent omission is forbidden. -->
**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
- "Combine 2-3 tasks I'll suggest" (you propose candidate merges)
- "Ship as-is — this plan really is that big"
- "Restructure — let me redesign Phase 8"

Sweet spot: each task fits one fresh context window AND produces ~50–500 lines of diff. Too many micro-tasks = orchestration overhead dominates; too few mega-tasks = bad failure isolation.

**Remote-verify tags.** For any task that touches Rust crates or Python scripts intended for the remote host, append a `**REMOTE_VERIFY:** <cargo command>` line to the task block. Example:
```
**REMOTE_VERIFY:** cargo check -p strategies-sports-ml-mispricing
```
The orchestrator dispatches a `remote-runner` (Haiku) to rsync+build in the sandbox; failure halts the task before review.

**Docs-touched flag.** For any task that touches a user-facing surface (CLI flags, public APIs, configs, schemas), append a `**DOCS:** <concept-slug>` line. This is a hint for `/z-maintain-docs`; not a rigid task on its own.

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the complexity-classifier Agent() calls.
     Tasks will lack a Complexity stamp; the orchestrator must treat all
     unstamped tasks as "medium" tier. -->
**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
  "$(printf '{"task":"%s","tier":"%s","reason":%s}' "<task-id>" "<tier>" "$(printf '%s' "<reason>" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
```
If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-execute` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).

**Scope seed (immediately after TASKS.md + complexity stamps are finalized).** Dispatch the `scope-extractor` (Haiku) subagent to seed the plan's file scope into the registry so a concurrent `/z-execute` can see what this plan intends. Best-effort, non-fatal — `update-scope` self-logs `registry_error` on failure:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. Scope seeding is advisory; the plan proceeds without it. -->
```
Agent(
  subagent_type="scope-extractor",
  description="Scope for /z-plan overlap seed",
  prompt="repo_root: <abs path to repo root>\nbase: $Z_HARNESS_PLAN_DIR"
)
```

Write the returned JSON array to a temp file, then:
```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" update-scope \
  --run-id "$RUN" --scope-json "$SCOPE_JSON" || true   # CLI self-logs registry_error on failure
```

**Heartbeat (Phase 8 boundary).** Best-effort, non-fatal:
```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" heartbeat \
  --run-id "$RUN" --phase phase8 || true   # CLI self-logs registry_error on failure
```

**Workstreams manifest (generated from TASKS.md).** After TASKS.md is finalized and all task blocks have their Complexity stamps, generate the plan's `workstreams.json` manifest. This file is the conflict DAG for parallelism — `/z-execute` reads it to decide what's safe to run concurrently. Best-effort, non-fatal — any failure is silent; `/z-execute` falls back to inline `**Files:**` dedup when the file is absent.

```bash
HERMES_ENABLED="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get workflow.hermes_enabled 2>/dev/null || echo false)"
if [ "$HERMES_ENABLED" = "true" ]; then
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/generate-workstreams.py" \
    --slug "$Z_HARNESS_SLUG" --source z-plan --plan-dir "$Z_HARNESS_PLAN_DIR" || true
fi  # hermes_enabled gate (Invariant 6: Hermes machinery never executes unless hermes_enabled=true)
fi  # end of Phase 8 else-branch: legacy SPEC/PLAN/TASKS checkpoint/finalization — skipped when PLANNING_MODE=intent and INTENT.md present
```

## Phase 8.4 — Post-artifact route check

Run this route check after Phase 8 has checkpointed the current artifact set:

- Intent mode: `$Z_HARNESS_PLAN_DIR/INTENT.md` (with `frozen_at: pending`) and canonical `$Z_HARNESS_PLAN_DIR/TASKS.md`.
- Full SDD mode: `$Z_HARNESS_PLAN_DIR/SPEC.md`, `$Z_HARNESS_PLAN_DIR/PLAN.md`, and `$Z_HARNESS_PLAN_DIR/TASKS.md`.

This check reuses the **Plan Route Check** event and route-decision contract. It fires after artifact writing plus TASKS checkpointing, so it can inspect concrete artifact shape instead of estimates:

- Recommend `/z-plan-split` when the produced task count or independent cluster seams show the plan should be split before execution.
- Recommend `/z-sharpen` when artifacts remain question-heavy, acceptance criteria are vague, or task text shows unresolved problem framing.
- Recommend `/z-brainstorm` when approach alternatives remain unsettled or the artifacts still read like "what should we do?" rather than an approved implementation direction.

If a post-artifact route is recommended, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `route_class: "post_artifact"`, include the same `route_chain` loop-prevention fields as the pre-gate route check, and surface an `AskUserQuestion` with **switch / continue here / abandon**. Never auto-dispatch the target command. If no signal fires, record no route artifact and continue to Phase 8.5.

Concrete Phase 8.4 `plan_route_decision` payload example:

```json
{
  "from_command": "/z-plan",
  "to_command": "/z-sharpen",
  "route_class": "post_artifact",
  "reason_codes": ["question_heavy_artifacts", "post_artifact_check"],
  "signals": {
    "plan_validation_intent": false,
    "question_heavy_artifacts": true,
    "artifact_unsettled_approach": false,
    "post_artifact_check": true
  },
  "confidence": "high",
  "classifier_used": false,
  "artifact_path": "$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md",
  "route_chain": [
    {
      "from_command": "/z-plan",
      "to_command": "/z-sharpen",
      "reason_codes": ["question_heavy_artifacts", "post_artifact_check"]
    }
  ],
  "user_choice": "continue_here"
}
```

Recognize both finished-plan artifact sets as complete when deciding whether to route or stop: legacy `SPEC.md` + `PLAN.md` + `TASKS.md`, and intent `INTENT.md` + canonical `TASKS.md`.

## Phase 8.5 — Handoff context producer

The handoff producer runs only after Phase 7 has generated/required `TASKS.md`, the Phase 8 task sanity/checkpoint has passed, and Phase 8.4 post-artifact route checks have either passed or the user explicitly chose to continue here. It must stay before Phase 8.6 and before Phase 9 finalization.

### Archive copies for handoff and finalization

**Intent-mode artifact copy (when `PLANNING_MODE=intent`):** copy `INTENT.md` in addition to (or instead of) `SPEC.md`/`PLAN.md` when INTENT.md is present. If `INTENT.md` is absent, fall back to the legacy artifact set.

```bash
if [[ "$PLANNING_MODE" == "intent" && -f "$Z_HARNESS_PLAN_DIR/INTENT.md" ]]; then
  cp "$Z_HARNESS_PLAN_DIR/INTENT.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/INTENT.md" || true
  # Copy LEDGER.md when it already exists; planning may hand off before execution creates it.
  [[ -f "$Z_HARNESS_PLAN_DIR/LEDGER.md" ]] && \
    cp "$Z_HARNESS_PLAN_DIR/LEDGER.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/LEDGER.md" || true
fi
```

**Legacy artifact copy (planning_mode=full or INTENT.md absent):**

Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).

**Handoff artifact.** Write a curated context slice to `$Z_HARNESS_PLAN_DIR/HANDOFF.md` so the next command can orient itself without re-reading the full planning transcript. This artifact must be written after TASKS sanity and before printing the next-move instruction below. It is a human-readable index and summary, not a second copy of the plan.

```bash
# Determine the primary artifact set for the handoff slice.
_HANDOFF_PRIMARY_ARTIFACTS=("$Z_HARNESS_PLAN_DIR/HANDOFF.md")
if [[ "$PLANNING_MODE" == "intent" && -f "$Z_HARNESS_PLAN_DIR/INTENT.md" ]]; then
  _HANDOFF_PRIMARY_ARTIFACT="$Z_HARNESS_PLAN_DIR/INTENT.md"
  _HANDOFF_ARTIFACT_KIND="INTENT.md"
  _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/INTENT.md" "$Z_HARNESS_PLAN_DIR/TASKS.md")
  [[ -f "$Z_HARNESS_PLAN_DIR/LEDGER.md" ]] && _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/LEDGER.md")
  [[ -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/intent-readthrough-flags.md" ]] && _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/archive/$RUN/intent-readthrough-flags.md")
else
  _HANDOFF_PRIMARY_ARTIFACT="$Z_HARNESS_PLAN_DIR/PLAN.md"
  _HANDOFF_ARTIFACT_KIND="PLAN.md"
  _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/SPEC.md" "$Z_HARNESS_PLAN_DIR/PLAN.md" "$Z_HARNESS_PLAN_DIR/TASKS.md")
fi
[[ -f "$Z_HARNESS_PLAN_DIR/workstreams.json" ]] && _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/workstreams.json")
[[ -f "$Z_HARNESS_PLAN_DIR/work-graph.json" ]] && _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/work-graph.json")
[[ -f "$Z_HARNESS_PLAN_DIR/execution-strategy.md" ]] && _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/execution-strategy.md")
_HANDOFF_PRIMARY_ARTIFACT_LIST="$(printf '%s\n' "${_HANDOFF_PRIMARY_ARTIFACTS[@]}")"
```

Write `$Z_HARNESS_PLAN_DIR/HANDOFF.md` with the following sections:

```markdown
---
artifact: handoff
slug: <$Z_HARNESS_SLUG>
planning_run: <$RUN>
planning_mode: <$PLANNING_MODE>
generated_at: <ISO UTC timestamp>
---

## Slug

<$Z_HARNESS_SLUG>

## Primary artifacts

<One bullet per path in $_HANDOFF_PRIMARY_ARTIFACT_LIST. Use pointers only; do not paste file contents. Include role labels such as "HANDOFF.md — curated context", "INTENT.md — accepted intent contract", "SPEC.md/PLAN.md — full SDD artifacts", "TASKS.md — executable implementation projection", "work-graph.json — append-only known-work DAG used by /z-execute scheduling", "workstreams.json — conflict/scope metadata", and "LEDGER.md — intent-mode decision/outcome ledger" when present. In intent mode, note that `LEDGER.md` is created or finalized by `/z-execute` before it recommends `/z-review-all`; its absence at planning handoff is allowed, but its absence after completed execution is not.>

## Intent / Goal

<2–3 sentence summary of what this plan sets out to accomplish, drawn from INTENT.md §Intent
or PLAN.md goals section — do not invent; quote or lightly paraphrase the approved text.>

## Task batch state

<Summarize the current TASKS.md level and staged groups (base, independent, dependent) in 3–6 bullets. Preserve canonical task ids and status marks from `## TNNN — title \`[ ]\`` headings.>

## Execution strategy

<Summarize `execution-strategy.md`, `work-graph.json`, and `workstreams.json` when present: ready-node scheduling, safe parallel batches, serial blockers, checkpoint cadence, and aggregate review recommendation. Use pointers; do not paste raw JSON.>

## Key decisions

<Bullet list of the top 3–5 approved decisions from decisions.md — one line each:
"Decision: [what was decided] — Rationale: [one-sentence reason]">

## Accepted shortcuts (if any)

<Bullet list of any shortcuts approved in Phase 5, or "none".>

## Concern flags and audit notes

<Pointer to `archive/$RUN/intent-readthrough-flags.md` when present. Summarize only the flags that survived final user approval. Use "none recorded" when no flags or audit scan were produced.>

## Grounding notes

<1–2 sentences summarizing what the codebase exploration (Phases 1–2) found —
key files, key constraints, or notable surprises. Omit if nothing noteworthy.>

## Invariants

<Bullets for non-negotiable constraints the executor must preserve: public API compatibility, data/schema invariants, ordering guarantees, safety gates, or "none".>

## Rejected approaches

<Bullets for approaches explicitly considered and rejected, with the reason. Use "none" if no rejection was recorded.>

## Decisions archive

<Pointer bullets to the durable decision artifacts under `$Z_HARNESS_PLAN_DIR/archive/$RUN/`, especially `phase3-decisions-final.md`, route-decision.md, consultant outputs, and review outputs when present. Do not paste full transcripts.>

## Verification commands

<Commands the executor/reviewer should run after implementation. Include the targeted tests named by the plan; use "none recorded" if the plan did not define commands.>

## Next move

Choose one of the Phase 8.6 gate options (`fresh_session_implementation`, `audit_first`, `stop_with_handoff`, or `amend`). Do not hard-code an audit-first recommendation before `FINAL_HANDOFF_CHOICE` is captured.
```

Machine handoff files (`handoff.json`, when produced by `scripts/write-handoff.sh`) must stay thin: `context_files` contains only `{path, role}` pointers. For a complete plan directory it should point at `HANDOFF.md`, the HANDOFF.md context categories (`invariants`, `rejected_approaches`, `decisions_archive`, `verification_commands`), `INTENT.md` when present, `SPEC.md`/`PLAN.md` when present, `TASKS.md`, `work-graph.json` when present, `workstreams.json` when present, `LEDGER.md` when present, and `SESSION.md`; the schema owns the allowed roles. Intent-mode handoff prose must make the LEDGER lifecycle observable: planning handoff may omit `LEDGER.md`, but completed `/z-execute` must create/snapshot it before `/z-review-all`.

After writing `HANDOFF.md`, call the machine handoff producer before Phase 8.6. Set the required z-plan overrides so the generated `handoff.json` describes a completed planning handoff, not an in-progress execute checkpoint; validate that the file exists and log both the human and machine artifacts:

```bash
export Z_HARNESS_HANDOFF_STATUS="complete"
export Z_HARNESS_HANDOFF_NEXT_STEP="Plan complete for ${Z_HARNESS_SLUG}. Choose the Phase 8.6 next step: fresh-session implementation, audit first, stop with handoff, or amend. Read HANDOFF.md, ${_HANDOFF_ARTIFACT_KIND}, TASKS.md, and work-graph.json before acting; after completed intent-mode /z-execute, LEDGER.md must be present before /z-review-all."
export Z_HARNESS_AGENT="${Z_HARNESS_AGENT:-pi}"

HANDOFF_PRODUCER_OUT="$(Z_HARNESS_PLAN_DIR="$Z_HARNESS_PLAN_DIR" Z_HARNESS_SLUG="$Z_HARNESS_SLUG" bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/write-handoff.sh" 2>&1)"
HANDOFF_PRODUCER_RC=$?
if [[ "$HANDOFF_PRODUCER_RC" -ne 0 || ! -s "$Z_HARNESS_PLAN_DIR/handoff.json" ]]; then
  echo "ERROR: write-handoff.sh failed before Phase 8.6: $HANDOFF_PRODUCER_OUT" >&2
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
    "$(printf '{"reason":"handoff_json_producer_failed","rc":%d}' "$HANDOFF_PRODUCER_RC")" 2>/dev/null || true
  exit 1
fi

HANDOFF_JSON_VALIDATE="$(python3 - "$Z_HARNESS_PLAN_DIR/handoff.json" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
roles = [entry.get("role") for entry in data.get("context_files", []) if isinstance(entry, dict)]
required = {"handoff", "tasks"}
missing = sorted(required.difference(roles))
if missing:
    raise SystemExit(f"missing required handoff context roles: {missing}")
print(json.dumps({"path": path, "roles": roles, "context_file_count": len(roles)}, separators=(",", ":")))
PYEOF
)"

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" handoff_written \
  "$(printf '{"slug":"%s","path":"%s","artifact_kind":"%s","handoff_json":"%s","producer_output":"%s"}' \
     "$Z_HARNESS_SLUG" "$Z_HARNESS_PLAN_DIR/HANDOFF.md" "$_HANDOFF_ARTIFACT_KIND" \
     "$Z_HARNESS_PLAN_DIR/handoff.json" "$(printf '%s' "$HANDOFF_PRODUCER_OUT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])')")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" handoff_json_validated "$HANDOFF_JSON_VALIDATE"
```

### Pre-execute watcher checkpoint seam

After `HANDOFF.md`, `handoff.json`, `TASKS.md`, and execution-strategy metadata are written and validated, evaluate the shared clear-context watcher before offering `/z-execute` via one `checkpoint-seam.sh` call. This replaces unconditional manual `/clear` prose with a watcher-readable checkpoint opportunity.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/checkpoint-seam.sh" \
  pre-execute-handoff "$Z_HARNESS_PLAN_DIR/HANDOFF.md" "/z-execute $Z_HARNESS_SLUG" \
  --producer z-plan \
  --next-step "Run /z-execute $Z_HARNESS_SLUG from HANDOFF.md, INTENT.md, TASKS.md, concern flags, and execution-strategy metadata." \
  --hash "$Z_HARNESS_PLAN_DIR/INTENT.md" --hash "$Z_HARNESS_PLAN_DIR/TASKS.md" --hash "$Z_HARNESS_PLAN_DIR/execution-strategy.md"
SEAM_RC=$?
case "$SEAM_RC" in
  0) ;;  # below threshold, or already fast-forwarded — continue
  1) exit 0 ;;  # new checkpoint written — pause here, not an error; next invocation resumes
  2)
    RB_HALT_REASON="context pressure estimate failed in strict mode at pre-execute handoff seam"
    # include: _fragments/run-brief-halt-finalize-plan.md
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
      --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
    exit 1
    ;;
esac
```

## Phase 8.6 — Final handoff gate

Print the completion summary, then surface one final user gate. This gate occurs **after** Phase 8.5 writes `HANDOFF.md` and **before** Phase 9 finalizes the run:

```text
Plan complete for slug: <$Z_HARNESS_SLUG>

Primary artifact: <$_HANDOFF_PRIMARY_ARTIFACT>

<If PLANNING_MODE=intent: "INTENT.md is the contract for this run. It captures the
 accepted goal, scope boundaries, and acceptance checklist. Read it before auditing.">
<If PLANNING_MODE=full: "SPEC.md + PLAN.md + TASKS.md are the contract for this run.">

Handoff context written to: $Z_HARNESS_PLAN_DIR/HANDOFF.md
```

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface
     the final handoff gate after HANDOFF.md is written and before Phase 9 finalization.
     Silent omission is forbidden. -->
Ask the user to choose exactly one next step:

- **Fresh-session implementation** — let the watcher consume the pre-execute checkpoint when it fired, then run `/z-execute <$Z_HARNESS_SLUG>` from `HANDOFF.md`, `INTENT.md`, `TASKS.md`, concern flags, and execution strategy.
- **Audit first** — ask for `/z-audit-plan <$Z_HARNESS_SLUG>` before execution when the final read-through still needs an external plan audit; do not present this as mandatory when the folded audit gate already ran or was explicitly skipped.
- **Stop with handoff** — leave `HANDOFF.md` as the next-session context and do not start another command.
- **Amend** — run `/z-amend <$Z_HARNESS_SLUG>` and resume from the mapped phase below.

Request-change resume map: scope/goal changes resume at Phase 0; decision changes resume at Phase 2; primary artifact wording changes resume at Phase 6; task decomposition changes resume at Phase 8.

Capture the final gate answer, normalize it into `FINAL_HANDOFF_CHOICE`, and export that machine value before any logging or `case "$FINAL_HANDOFF_CHOICE"` use. The only valid values are `fresh_session_implementation`, `audit_first`, `stop_with_handoff`, and `amend`.

```bash
FINAL_HANDOFF_CHOICE="$(AskUserQuestion "Choose the next step for <$Z_HARNESS_SLUG>:" \
  ["fresh_session_implementation — Fresh-session implementation: run /clear, then /z-execute <$Z_HARNESS_SLUG>", \
   "audit_first — Audit first: run /clear, then /z-audit-plan <$Z_HARNESS_SLUG>", \
   "stop_with_handoff — Stop with handoff: leave HANDOFF.md as next-session context", \
   "amend — Amend: run /z-amend <$Z_HARNESS_SLUG>"])"
FINAL_HANDOFF_CHOICE="${FINAL_HANDOFF_CHOICE%% — *}"
export FINAL_HANDOFF_CHOICE
case "$FINAL_HANDOFF_CHOICE" in
  fresh_session_implementation|audit_first|stop_with_handoff|amend) ;;
  *) echo "invalid final handoff choice: $FINAL_HANDOFF_CHOICE" >&2; exit 1 ;;
esac
```

Log the selected next step:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" next_step_choice \
  "$(printf '{"choice":"%s","source":"phase_8_6_final_handoff_gate"}' "$FINAL_HANDOFF_CHOICE")"
```

Set `$NEXT_JSON` for the run brief from the gate selection:

```bash
case "$FINAL_HANDOFF_CHOICE" in
  fresh_session_implementation)
    NEXT_JSON='{"label":"Implement in a fresh session","command":"/z-execute"}'
    ;;
  audit_first)
    NEXT_JSON='{"label":"Audit the plan first","command":"/z-audit-plan"}'
    ;;
  stop_with_handoff)
    NEXT_JSON='{"label":"Stop with handoff","command":null}'
    ;;
  amend)
    NEXT_JSON='{"label":"Amend the plan","command":"/z-amend"}'
    ;;
esac
```

## Phase 9 — Finalize archive

**Run Brief finalize (registry Phase 9).** Set registry artifact env, pre-seed outcome/status/next, then include the shared fragment. Chat and push text are rendered from `run-brief.json` only — do not author independent completion prose.

```bash
export RUN_BRIEF_PROFILE="full"
export RUN_BRIEF_ARTIFACT="$CURRENT_ARCHIVE_DIR/decisions.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS="PLAN.md:SPEC.md"
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"

RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
TASK_COUNT="$(grep -cE '^[[:space:]]*- \[[[:space:]]\] T[0-9]+' "$Z_HARNESS_PLAN_DIR/TASKS.md" 2>/dev/null || echo 0)"
bash "$RB_SH" set-section --run "$RUN" --section outcome \
  --value "Plan complete. ${TASK_COUNT} tasks queued in TASKS.md."
bash "$RB_SH" set-section --run "$RUN" --section status --value "complete"
NEXT_JSON_FILE="$(mktemp -t z-rb-next.XXXXXX.json)"
printf '%s\n' "$NEXT_JSON" > "$NEXT_JSON_FILE"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON_FILE"
rm -f "$NEXT_JSON_FILE"
```

<!-- include: _fragments/run-brief-finalize.md -->

**Teardown funnel** (best-effort, non-fatal; release-before-deregister + `run_end` all in one call). Normal completion tears down with `complete`; if the fragment's `--require` step set `FINALIZE_STATUS=aborted`, tear down with `aborted` instead. If register never succeeded (no record was ever written), the deregister/release steps inside the funnel are harmless no-ops.
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
  --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status "${FINALIZE_STATUS:-complete}"
```

After planning, prefer the shared watcher-readable clear checkpoint over manual `/compact`: planning (Explore agents, user intent iteration, concern flags, audit notes, and task DAG drafting) is the heaviest context burner in the harness. The `checkpoint-seam.sh` seam lets Oh My Pi/Hermes/MCP or the user clear before implementation starts; implementation subagents are fresh-context already, and `/z-execute` owns later durable checkpoint seams.

## Run Brief — halt finalize

Shared halt shape reused by every mid-file halt site (RB_HALT_REASON + `_fragments/run-brief-halt-finalize-plan.md` include + `z-teardown.sh --status aborted`). Substitute `<reason>` in the outcome line. When no planning artifact exists yet, the shared fragment auto-downgrades to **lite** (Intent + Outcome + Next). If register never succeeded, `z-teardown.sh`'s deregister step is a harmless no-op — no separate "register failed" branch is needed here.

**Known gap:** halts before Setup step 2's `z-preflight.sh` call completes (e.g. the `workflow.slug_confirm` resolver `halt` during slug derivation) skip this block entirely — no brief JSON exists yet, so a bare `exit 0`/`exit 1` is correct there.

```bash
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-PLAN.md:SPEC.md}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Review plan status and retry or escalate", "command": null}
JSON
```

<!-- include: _fragments/run-brief-finalize.md -->

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
  --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --status aborted
```

---

## Telemetry reference

Event kinds emitted by `/z-plan` and its helpers. For full per-task event schema see `z-execute.md`.

| Event kind | When / meaning | Required fields |
|---|---|---|
| `run_start` | Planning run begins | version fields, `task`, `command` |
| `planning_mode_chosen` | Explicit Intent-vs-Full SDD mode gate resolved before the hard cost gate | `slug`, `mode`, `recommended_mode`, `source`, `reason`, `legacy_spec_forced` |
| `plan_route_decision` | Route check fired and a route was chosen | `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, `user_choice` |
| `plan_halt` | Run halted (e.g. `no_ask_blocked` on slug gate) | `reason`, `question_id`, `rule_id` |
| `askuser_skipped` | AskUserQuestion suppressed by resolver | `question_id`, `source` |
| `legacy_map_artifact_detected` | RESEARCH.md had no `artifact_kind` field and was treated as MAP.md terrain | — |
| `precontext_research_incomplete` | RESEARCH.md `status: incomplete`; run halted | — |
| `precontext_source_deleted` | A file cited in precontext artifact no longer exists | `path`, `artifact` |
| `precontext_freshness_check_failed` | Citation-regex parse failed for a precontext artifact | `artifact`, `reason` |
| `precontext_freshness_acknowledged` | User accepted stale precontext after consolidated 10c gate | `sources` (list of `"research"` / `"map"` / `"docs"`), `user_choice` |
| `doc_drift_acknowledged` | User accepted stale docs in the consolidated 10c gate | `stale_pct`, `stale_concepts` |
| `doc_drift` | doc-fetcher returned a DRIFT WARNING for a concept | `concept`, `claim`, `reality`, `file` |
| `task_classified` | complexity-classifier stamped a task block | `task`, `tier`, `reason` |
| `telemetry_anomaly` | `log-phase.sh` detected impossible `wall_ms` | `phase`, `reason` (`wall_ms_overflow` / `wall_ms_negative`), `t_start`, `t_end`, `computed_wall_ms` |
| `next_step_choice` | Phase 8.6 final handoff gate selection emitted (source: `phase_8_6_final_handoff_gate`) | `choice`, `source` |
| `sharpen_gate` | Phase 0 mandatory conversational sharpen decision | `decision` (`existing_grill`\|`sharpened`), `recommendation` (`proceed`\|`ask_brainstorm`), `grill_md_existed` |
| `execution_strategy_written` | Phase 8 wrote intent-mode execution strategy metadata for `/z-execute` | `path`, `source`, `planning_mode` |
| `handoff_written` | Phase 8.5 handoff artifacts written to HANDOFF.md and handoff.json | `slug`, `path`, `artifact_kind`, `handoff_json`, `producer_output` |
| `handoff_json_validated` | Phase 8.5 verified the machine handoff before Phase 8.6 | `path`, `roles`, `context_file_count` |
| `plan_claim_lost_during_gate` | Heartbeat detected ownership change (exit 9) at a phase boundary or before a user gate; URGENT abort/continue-uncoordinated gate fires | `slug`, `run_id`, `phase` |
| `cost_gate_decision` | Exactly one terminal pre-subagent hard cost-gate decision per `/z-plan` run | `command`, `choice`, `estimated_tokens`, `confidence`, `basis`, `disposition`, `rule_id`, `range_high`, `choice_source`, `attempt_count` when known; optional sanitized `reason` |
| `cost_gate_reestimate_attempt` | Nonterminal cost reduction / re-estimate attempt; never counts as the terminal gate decision | `command`, `run_id`, `gate_id`, `attempt_index`, `changed_drivers`, `prior_range_high`, `new_range_high`, `disposition`, `terminal_event_kind`, terminal-correlation `gate_id` |
| `intent_level_chosen` | Mode detection resolved the planning depth level (via classifier, config-forced, flag, cost-gate reduction, or fallback) | `level`, `source` (`classifier` / `config-forced` / `flag` / `user-cost-reduction` / `user-override` / `fallback`), `reason` |
| `intent_level_override` | User overrode the classifier's chosen level via the inline announce gate | `level` (new), `prior_level`, `source` (`user-override`) |
| `consult_skipped` | Phase-3 or Phase-7 consult skipped; `reason` distinguishes `Z_HARNESS_CONSULT=off` / `intent_level_L1_quick` / `intent_level_L2_user_skipped` | `phase`, `reason`, optionally `intent_level` |
| `post_draft_grill` | Phase 5 inline post-draft grill ran before final approval | `question_count`, `source` (`intent-readthrough-flags`), `transcript_path` |
| `legacy_spec_detected` | Backward-compat guard: SPEC.md found in slug dir; `PLANNING_MODE` forced to `full` (Invariant 4) | `slug`, `spec_path`, `original_planning_mode` |
| `legacy_mode_active` | `PLANNING_MODE=full` branch entered (from --full flag, config, or SPEC detection) | `slug`, `reason` |
| `legacy_plan_exists` | Finished legacy plan (SPEC.md + TASKS.md) detected; user prompted to amend/implement/overwrite/abort | `slug`, `has_spec`, `has_tasks` |
| `work_graph_written` | Phase 8 wrote the initial append-only known-work DAG for intent-mode `/z-execute` | `slug`, `path`, `source`, `mode` (`known_work_graph`) |
| `run_end` | Emitted by `scripts/z-teardown.sh` at every controlled exit (complete or aborted) — the teardown-funnel adoption in this rewrite closes a gap where the pre-rewrite skill never emitted a terminal `run_end` | `status`, `command` |

---

## Operating principles

- **Premise first.** Challenge the request before planning around it.
- **Push back is structural** — every accepted recommendation needs an articulated "reason it might be wrong" before you accept it.
- **Always ask** when unclear.
- **Shortcuts only with explicit approval** in the final plan-brief gate.
- **DRY / KISS / SOLID** are non-negotiable.
- **Log everything.** Every consultation, approval, pushback, error — via `scripts/log-event.sh`.

---

Driver support requirements: see frontmatter `driver_features_required`. Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden. Each gated call site carries its own `<!-- RUNTIME-GATE: ... -->` comment immediately before the call; that is the single source of truth for what is gated (SKILL-STYLE.md §1 — the closing conformance table is retired for rewritten skills).
