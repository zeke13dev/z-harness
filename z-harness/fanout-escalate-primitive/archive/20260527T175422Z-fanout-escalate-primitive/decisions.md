# Decisions — fanout-escalate-primitive (v1a)

## D1: Output contract shape for scope-probe
- **Decision:** What parseable contract does scope-probe emit?
- **Options:**
  - (a) Strict line-prefix contract like planning-router (`STATUS:`/`MODE:`/`AXIS:`/...) — easy to grep, hard to extend.
  - (b) Fenced JSON block (like review-agent) — extensible, but more parsing.
  - (c) Hybrid: line-prefix headers + a fenced JSON chunks array.
- **Tentative call:** (c) hybrid — `STATUS:`/`MODE:`/`AXIS:`/`CONFIDENCE:`/`REASON_CODES:` line headers for cheap parsing, followed by a fenced JSON block holding the `chunks: [{id, intent, scope_hint}]` array since chunks are arbitrary-length and need structure.
- **Consult? yes**
- **Trigger:** public API / wire format; affects how `/z-audit` and `/z-brainstorm` parse the return; hard to rename.

## D2: SCOPE.json on-disk schema
- **Decision:** Required fields, optional fields, location, ephemerality.
- **Options:**
  - (a) Per-run: `z-harness/<slug>/archive/<RUN>/SCOPE.json` (ephemeral, archived with run).
  - (b) Per-slug live: `z-harness/<slug>/SCOPE.json` (overwritten each run; latest only).
  - (c) Both — live + archived copy.
- **Tentative call:** (c) both. The host command writes to the run archive AND overwrites the live `z-harness/<slug>/SCOPE.json` so `/z-stats` and tools can read the latest classification per slug. Race condition risk per BRAINSTORM is mitigated because each `/z-plan`-family slug is single-writer.
- **Consult? yes**
- **Trigger:** persistence / schema; defines a new on-disk artifact other tools will read; >1 module (writers: scope-probe orchestrator wrapper; readers: host commands, /z-stats, calibration harness).

## D3: Where scope-probe lives (architecturally)
- **Decision:** Agent? Skill? Script lib? Inline in each command?
- **Options:**
  - (a) Standalone Haiku agent (BRAINSTORM-recommended; matches planning-router/complexity-classifier).
  - (b) Inline bash logic in each command (no LLM call).
  - (c) Shared script lib `scripts/scope-probe.sh` that wraps a Haiku Agent() call.
- **Tentative call:** (a) standalone agent at `agents/scope-probe.md` — matches existing pattern, lets the agent reason about ambiguity, fresh-context per call. Host commands dispatch via `Agent(subagent_type="scope-probe", ...)`.
- **Consult? no**
- **Trigger:** none — follows existing convention for planning-router, complexity-classifier, doc-fetcher.

## D4: 5-step axis discovery protocol — concrete heuristics
- **Decision:** How exactly does scope-probe count seams and pick an axis?
- **Options:**
  - (a) BRAINSTORM literal: parse topic → walk dirs 2 levels → count seams → query doc-fetcher → emit manifest.
  - (b) Lookup-table: hardcode known axis taxonomies per host command (audit: dimension/component/risk-domain; brainstorm: vendor/framing).
  - (c) Hybrid: structural seams from dirs (a) PLUS host-command axis hints supplied by caller (b).
- **Tentative call:** (c) hybrid. Caller (host command) passes `axis_taxonomy: [<allowed axes for this command>]` so scope-probe only emits an axis from that list. Structural-seam evidence from dirs determines which axis is picked. Prevents scope-probe from inventing nonsense axes for a given host command.
- **Consult? yes**
- **Trigger:** algorithm with materially different tradeoffs (free-form invention vs constrained); affects whether scope-probe is reusable across new commands or rigid.

## D5: LIGHT/MEDIUM/HEAVY thresholds
- **Decision:** Numeric thresholds for the three modes.
- **Options:**
  - (a) BRAINSTORM literal: LIGHT (≤1 file/component, 0 seams); MEDIUM (2–5 files, ≤2 seams); HEAVY (≥3 seams OR named sub-cluster dir OR module name with ≥4 direct children).
  - (b) Looser: LIGHT (0 seams); MEDIUM (1–2 seams); HEAVY (≥3 seams).
  - (c) Calibrated thresholds (write the harness first, set thresholds from historical-run data).
- **Tentative call:** (c) calibrate. Ship the harness with placeholder thresholds matching (a); after running against 5–6 historical archive runs, tune. Saves us from baking in numbers we'll have to change post-launch.
- **Consult? no**
- **Trigger:** none — calibration is the explicit v1a deliverable; thresholds are output of that process, not an input.

## D6: Calibration harness — implementation language + entry point
- **Decision:** Python script? Bash + jq? Where does it live?
- **Options:**
  - (a) `scripts/scope-probe-calibrate.py` — Python, follows existing convention (`extract-dismissals.py`, `regenerate-memories-flat.py`).
  - (b) `scripts/scope-probe-calibrate.sh` — bash + jq, lighter weight.
  - (c) Both — a thin bash wrapper that calls the Python core.
- **Tentative call:** (a) Python only. JSON parsing + replay + classification comparison are easier in Python and we already require python3.
- **Consult? no**
- **Trigger:** none — convention match.

## D7: Calibration harness — replay protocol
- **Decision:** How does the harness "replay" scope-probe against a historical run?
- **Options:**
  - (a) Re-invoke scope-probe Agent on the historical topic, compare classification to the run's actual mid-flight escalation events.
  - (b) Replay deterministically without LLM (apply scope-probe's heuristics directly in Python), no LLM cost.
  - (c) Sample: LLM-replay for 2 runs, deterministic-replay for remaining 4 to bound cost.
- **Tentative call:** (a) LLM-replay all 5–6 historical runs. We need to validate the Haiku tier's actual classification quality, not just the heuristic. Cost ~6 Haiku calls — negligible.
- **Consult? yes**
- **Trigger:** algorithm-with-tradeoffs (LLM behavior vs deterministic); affects what the calibration data actually proves.

## D8: How "actual classification" is derived from historical runs
- **Decision:** What ground-truth label does the harness compare scope-probe's classification against?
- **Options:**
  - (a) Tasks count from `manifest.json`: ≤5 tasks = LIGHT, 6–15 = MEDIUM, ≥16 = HEAVY.
  - (b) Mid-flight escalation events: presence of `plan_route_decision` → MEDIUM; presence of escalation.md → HEAVY; neither → LIGHT.
  - (c) Combination of both with explicit rubric.
- **Tentative call:** (c) combined rubric. Use `manifest.json.tasks_total` AND `tasks_complexity` AND presence/absence of `plan_route_decision`/escalation events. Document the rubric in the harness so calibration is reproducible.
- **Consult? yes**
- **Trigger:** measurement methodology — wrong ground-truth means tripwires fire on noise.

## D9: Integration into `/z-audit` Phase 0
- **Decision:** How invasive is the /z-audit edit?
- **Options:**
  - (a) Add a Phase 0 block before the existing Phase 1 — write SCOPE.json, then Phase 1 reads it for dimension hints.
  - (b) Add a new Phase before Setup that opts the user into Phase 0 vs skip-classic via env var.
  - (c) Make Phase 0 unconditional but in MEDIUM mode it's a no-op (just records the classification).
- **Tentative call:** (c) unconditional, MEDIUM-passthrough. Always runs scope-probe; LIGHT/MEDIUM proceed to existing Phase 1 unchanged; HEAVY fans out N parallel `/z-audit` sub-runs (one per chunk) and main thread reconciles. This minimizes user-visible behavior change for the common (MEDIUM) case.
- **Consult? yes**
- **Trigger:** changes a public command's pipeline shape; cross-module impact.

## D10: Integration into `/z-brainstorm` Phase 0
- **Decision:** Same as D9 but for brainstorm.
- **Options:**
  - (a) Insert Phase 0 between Plan Route Check and Phase 1 scaffolding.
  - (b) Skip integration in v1a (brainstorm is already cheap; the pilot value is in /z-audit only).
- **Tentative call:** (a). Even though brainstorm is cheap, the integration validates that scope-probe handles a *different* axis taxonomy (vendor framing axis vs audit dimension axis). Without this we don't test the D4 hybrid axis-discovery against two distinct host commands and the v1a calibration is structurally weaker.
- **Consult? no**
- **Trigger:** none — design call already decided in the BRAINSTORM User choice section.

## D11: HEAVY fanout reconciler
- **Decision:** Where does the Sonnet reconciler logic live?
- **Options:**
  - (a) New `agents/scope-reconciler.md` — fresh-context Sonnet, takes N chunk artifacts, emits unified output.
  - (b) Inline in the host command's main thread.
  - (c) Per-host reconciler agents (`scope-reconciler-audit`, `scope-reconciler-brainstorm`) — command-specific synthesis.
- **Tentative call:** (c) per-host reconcilers. The BRAINSTORM Codex framing won the anti-bias check on exactly this point: "command-specific synthesis (not a generic reducer)" preserves dissent in audit/brainstorm. Build two reconcilers for v1a: `scope-reconciler-audit` and `scope-reconciler-brainstorm`. Generic reducer is rejected.
- **Consult? yes**
- **Trigger:** algorithm-with-tradeoffs (generic vs command-specific); >1 module; defines an extension contract for future commands.

## D12: Fallback behavior when scope-probe fails or returns low confidence
- **Decision:** What does the host command do if scope-probe errors, times out, or returns `CONFIDENCE: low`?
- **Options:**
  - (a) Hard fail — refuse to run host command.
  - (b) Fall back to MEDIUM unconditionally with a logged warning.
  - (c) Fall back to MEDIUM, but if HEAVY was *strongly suggested* (≥3 seams) ask user via AskUserQuestion.
- **Tentative call:** (b) MEDIUM fallback with logged warning. Keeps v1a non-disruptive — scope-probe failures degrade gracefully to today's behavior. AskUserQuestion gating waits for v1b.
- **Consult? no**
- **Trigger:** none — graceful-degradation pattern matches existing planning-router fallback (deterministic thresholds win on router failure).

## D13: Telemetry event taxonomy
- **Decision:** What scope-probe events get logged?
- **Tentative call:** `scope_probe_start {host_command, topic, axis_taxonomy}` / `scope_probe_classified {mode, axis, chunks_n, confidence, reason_codes}` / `scope_probe_failed {reason}` / `scope_fanout_dispatched {n_chunks}` / `scope_fanout_reconciled {n_chunks, status}`. Calibration harness emits `scope_calibration_replay {historical_run, classified_mode, ground_truth_mode, match}`.
- **Consult? no**
- **Trigger:** none — follows existing convention.

## D14: Live SCOPE.json overwrite policy across host commands
- **Decision:** If `/z-audit` writes SCOPE.json then `/z-brainstorm` runs on a different topic in the same slug, do we clobber or namespace?
- **Options:**
  - (a) Single live SCOPE.json — clobbered on each run.
  - (b) Namespaced: SCOPE.json contains `last_runs: {z-audit: {...}, z-brainstorm: {...}}` keyed by host command.
- **Tentative call:** (b) namespaced. Slugs frequently have multiple commands run against them (brainstorm → plan → implement-all → review-all). Keeping last-classification per host command means /z-stats can show consistent history.
- **Consult? yes**
- **Trigger:** schema decision; affects readers (/z-stats, calibration harness).

---

## Consult-flagged decisions (5/14)
1. **D1** — output contract shape (line-prefix + fenced JSON hybrid)
2. **D2** — SCOPE.json schema + live+archive policy
3. **D4** — axis discovery: free-form invention vs caller-supplied taxonomy (hybrid recommended)
4. **D7** — calibration replay protocol (LLM-replay all)
5. **D8** — ground-truth derivation rubric for calibration

D11 (reconciler shape) is close to consult-worthy but BRAINSTORM already settled it via anti-bias check; including would push us past the 5-cap. Worth re-raising in Phase 5 if consultants surface a tradeoff.

D9, D14 cross multiple criteria but are skip-consult: D9 follows a "unconditional MEDIUM-passthrough" pattern that's the obvious non-disruptive choice; D14 namespaced schema is a near-mechanical "store per writer key" call.
