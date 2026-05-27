# PLAN — fanout-escalate-primitive v1a

## Goal

Build a pre-dispatch Haiku `scope-probe` subagent and its supporting infrastructure (SCOPE-*.json artifacts, per-host reconcilers, calibration harness), integrated as Phase 0 of `/z-audit` and `/z-brainstorm` only. Validate the structural-axis classification hypothesis via calibration replay against 5–6 historical archive runs. v1b (the aggressive deletions) is gated on this calibration passing the 4 falsifiability tripwires.

## Decisions (with rationale)

| # | Call | Why |
|---|---|---|
| D1 | Hybrid contract (line-prefix routing + fenced JSON chunks) | Matches both planning-router (line-prefix routing) and review-agent (fenced JSON structured payload) precedents simultaneously. Codex won the consult vs Gemini's JSON-only; reasoning was contract-pattern consistency across Haiku agents. |
| D2 | Live + archived SCOPE files; namespaced per host (`SCOPE-audit.json`, `SCOPE-brainstorm.json`); include `last_run_id` + `last_updated`; archive-first atomic write order | Both consultants endorsed. Archive-first ensures crash-between-writes leaves live stale (not archive corrupt). Namespacing prevents `/z-audit` and `/z-brainstorm` clobbering each other on the same slug. |
| D3 | Standalone Haiku agent at `agents/scope-probe.md` | Matches planning-router/complexity-classifier/doc-fetcher pattern. |
| D4 | Hybrid axis discovery: runtime caller-supplied `axis_taxonomy` parameter + structural-seam evidence picks the winning axis. 3-state graceful degradation (high-conf / low-conf-with-warning / refuse) | Both consultants endorsed hybrid. Runtime parameter (not hardcoded) honors open/closed principle. 3-state addresses Codex's "fail-loud may be brittle for ambiguous topics." |
| D5 | Calibrated thresholds (placeholders match BRAINSTORM literals; tuned post-calibration) | Calibration is the v1a deliverable; baking numbers in upfront would force a rework. |
| D6 | Python: `scripts/scope-probe-calibrate.py` | Matches existing convention (extract-dismissals.py, regenerate-memories-flat.py). |
| D7 | LLM-replay all 5–6 historical runs, **3× each** (majority-vote) + epoch tag | Triple-sample mitigates Haiku non-determinism (~18 Haiku calls total — negligible). Epoch tag enables future re-baselining. |
| D8 | Combined rubric (`tasks_total` + `tasks_complexity` + escalation events); documented in `scripts/CALIBRATION.md` with `rubric_version` in frontmatter; tie-break prefers escalation events > tasks_complexity > tasks_total | Both consultants endorsed combined; versioning prevents silent rubric-drift breaking calibration trend lines. |
| D9 | `/z-audit` Phase 0 unconditional; MEDIUM is passthrough no-op | Minimum behavior change for the common case. |
| D10 | `/z-brainstorm` Phase 0 same shape | Validates 2 distinct axis taxonomies in v1a so the design is honestly tested. |
| D11 | Per-host reconcilers: `scope-reconciler-audit`, `scope-reconciler-brainstorm` (NOT a generic reducer) | BRAINSTORM-settled. Generic reducer would smooth over dissent in audit findings and framings in brainstorm. |
| D12 | Probe failure → MEDIUM fallback + logged warning | Graceful degradation. AskUser confirmation defers to v1b. |
| D13 | Event taxonomy: `scope_probe_start`, `scope_probe_classified`, `scope_probe_failed`, `scope_fanout_dispatched`, `scope_fanout_reconciled`, `scope_calibration_replay` | Convention match with existing event names. |
| D14 | Live files namespaced per host command (subsumed into D2) | — |

## Non-goals (v1b territory)

- All deletions: z-plan-light Phase 1 up-route, z-plan pre-Phase-1 Plan Route Check, z-debug architectural bail.
- Retiring/demoting `planning-router`.
- Folding `/z-plan-split` into `/z-plan` HEAVY.
- Integration into other commands (`/z-debug`, `/z-plan`, `/z-review-all`, `/z-implement-all`, `/z-fix`, `/z-do`).
- GC mechanism for stale live SCOPE-*.json files.
- AskUser gate on low-confidence probe results.

## Approved shortcuts

None. The "split v1a + v1b" itself defers the aggressive refactor; within v1a everything is the robust path.

## Ordered phases

### Phase A — Agent definitions and SCOPE.json schema
1. Write `agents/scope-probe.md` with frontmatter + procedure + output contract + REASON_CODES enum + hard rules.
2. Write `agents/scope-reconciler-audit.md` and `agents/scope-reconciler-brainstorm.md` with their respective procedures + dissent-preservation invariants.
3. Define SCOPE-*.json schema. Update `docs/llm/INDEX.json` `agents` entry to include the 3 new agents.

### Phase B — Calibration harness (BEFORE host integration)
1. Write `scripts/CALIBRATION.md` with rubric v1 + frontmatter.
2. Write `scripts/scope-probe-calibrate.py` with:
   - Run discovery (walk `z-harness/*/archive/*/`).
   - `classify_ground_truth(manifest, events)` per CALIBRATION.md rubric.
   - Scope-probe dispatch shim (subprocess-based replay).
   - Confusion matrix + tripwire report.
3. Dry-run the harness against current archive (without scope-probe.md yet existing — should fail cleanly with a "scope-probe not yet defined" error to verify the harness's error handling).

### Phase C — Host command integrations
1. Edit `commands/z-audit.md` to insert Phase 0 block: dispatch scope-probe, parse return, write SCOPE archive+live, branch on MODE. HEAVY branch dispatches N parallel `/z-audit` sub-flows then reconciler.
2. Edit `commands/z-brainstorm.md` to insert Phase 0 block (same shape, different taxonomy).
3. Add `--scope-from <chunk-path>` flag to `/z-audit` for sub-flow narrowing.

### Phase D — Calibration run + threshold tuning

**Ordering note (per Gemini critique):** Phase D runs AFTER Phase C is complete (host integration must exist for end-to-end calibration). Phase B builds the *harness framework*; Phase D *runs* it. The harness framework can be unit-tested in Phase B against synthetic fixtures (a fake SCOPE.json + fake events.jsonl) — that does NOT require Phase C.

1. Run `scripts/scope-probe-calibrate.py --epoch 1 --n-runs 6 --samples-per-run 3` against current archive.
2. Inspect confusion matrix. Tune the LIGHT/MEDIUM/HEAVY thresholds in `agents/scope-probe.md` if mis-classifications cluster.
3. Re-run calibration with tuned thresholds (epoch 2).
4. Verify the two **automated tripwires** (the harness fires these — exit code 1 if either fires):
   - Tripwire 1 (≥70% MEDIUM): MUST NOT FIRE.
   - Tripwire 2 (<20% HEAVY): MUST NOT FIRE.
5. Conduct two **manual review gates** (NOT automated tripwires; documented as gates so v1a→v1b transition can require sign-off):
   - Manual gate A (synthesis quality): review one HEAVY run's reconciler output vs the hypothetical single-MEDIUM output for the same topic. Sign off in `CALIBRATION-EPOCH-N-SIGNOFF.md`.
   - Manual gate B (semantic vs structural axis): inspect Haiku's REASON_CODES for the 5–6 replays. If most picks cite structural reason codes (`named_cluster_dir`, `import_profile_split`, `module_with_subchildren`), gate passes. If most cite `low_confidence_pick` or `axis_evidence_thin`, the structural hypothesis is wrong → gate fails → v1b canceled.
6. If any automated tripwire fires OR a manual gate fails: HALT, document failure mode in `CALIBRATION-FAILURES.md`, surface to user. v1a deemed not-ready-to-ship; v1b is canceled or rescoped.

### Phase E — Docs refresh
1. Update `docs/llm/agents.json` + `docs/human/agents.md` for the 3 new agents.
2. Update `docs/llm/commands.json` + `docs/human/commands.md` for `/z-audit` and `/z-brainstorm` Phase 0 additions.
3. Update `docs/llm/scripts.json` + `docs/human/scripts.md` for `scope-probe-calibrate.py` and CALIBRATION.md.
4. Add new concept entry in INDEX.json for `scope-probe` (or extend the `review-agent` concept pattern — TBD during implementation).
5. Regenerate `docs/llm/MEMORIES-FLAT.md`.

## DRY / KISS / SOLID

- **DRY:** SCOPE.json schema + line-prefix contract shared across both pilot host commands; reuses doc-fetcher; reuses existing log-event.sh + version.sh + plan-path.sh infrastructure. The two per-host reconcilers share their fundamental dedup+dissent-preservation logic but differ only in artifact shape (findings.md vs BRAINSTORM.md).
- **KISS:** v1a ships strictly additive — no deletions; no AskUser; no GC; MEDIUM passthrough is a no-op. The hybrid contract uses two existing patterns rather than inventing a third.
- **SOLID:** taxonomy is runtime input (open/closed); scope-probe classifies, reconcilers synthesize, calibrate.py validates (single responsibility); host commands depend on the scope-probe contract not its implementation (dependency inversion).
