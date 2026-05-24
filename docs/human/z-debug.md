# z-debug

> Last updated: 2026-05-24
> Covers source: commands/z-debug.md

## What it does

`/z-debug` is the heavy-path debugging pipeline for bugs whose root cause is **unknown**. You bring a symptom; the command runs an adversarial multi-LLM hypothesis tournament — two rounds of independent generation across three sources (Claude orchestrator, Codex, Gemini), a discriminating-test matrix, and discrete Bayesian ordinal scoring — to converge on the highest-confidence root cause before writing a single line of fix code. Post-mortem is mandatory. It is explicitly **not** for situations where you already have a diagnosis: if you can name a concrete hypothesis before Phase 0 completes, the command exits and recommends `/z-fix` instead.

`/z-debug` produces a single unified artifact: `DEBUG.md`. There are no separate PROBLEM.md, EVIDENCE.md, or ISOLATION files — every section (Problem, Evidence Inventory, Hypothesis Pool, Test Matrix, Experiment Log, Score Updates, Eliminated Alternatives, Root Cause, Fix Plan, Verification, Post-mortem) lives in one file, appended as the run progresses.

## Phases at a glance

| Phase | What happens |
|---|---|
| **Setup** | Derive slug (`debug-<symptom>`), create run directory, version-stamp, log `debug_run_start`, record `T0_DEBUG`. |
| **Phase 0 — Wrong-tool gate** | Non-skippable `AskUserQuestion`: do you already have a hypothesis? Yes → exits with `/z-fix` recommendation. |
| **Phase 1 — Problem statement** | Clarifying questions; open `DEBUG.md` with `## Problem` section (expected/actual behavior, reproducibility, suspected scope, recent changes). |
| **Phase 2 — Reproduce + Evidence Inventory** | Attempt repro; append `## Evidence Inventory` section. Each evidence entry assigned a stable `EVID-NNN` ID at capture time — never renumbered, never reused. |
| **Phase 3a — Round 1 hypothesis generation** | Orchestrator checkpoints own hypotheses to disk BEFORE dispatching consultants. Codex and Gemini receive Problem + Evidence only; each returns 3-5 independent hypotheses. Merge all three sources with semantic dedup into `## Hypothesis Pool`; assign stable `H<NNN>` IDs and `overlap_count`. |
| **Phase 3b — Round 2 adversarial** | Both consultants receive only the merged Hypothesis Pool. Each returns NEW hypotheses (orthogonality hunt) and CRITIQUES of existing rows (non-discriminating tests, false parallel-safe tags, duplicates). Orchestrator filters and applies surviving changes. |
| **Phase 4 — Build Test Matrix** | Append `## Test Matrix`. Prior assigned mechanically: `overlap=3 → high`, `overlap=2 → med`, `overlap=1 → low`. |
| **Phase 5 — Compute test order** | Sort by `overlap` descending (consensus-first). Force top 2 `overlap=1` hypotheses near the front (outlier carve-out, groupthink mitigation). |
| **Phase 6 — Batch isolation cycle (loop)** | Run discriminating tests (parallel-safe in batch, non-parallel-safe serially). Orchestrator alone assigns likelihood bucket. Apply posterior lookup table. Update Test Matrix. Append `## Experiment Log` and `## Score Updates`. Loop until fix-gate opens (any `posterior=very_high` with full evidence coverage) or cycle cap reached (soft warning at 3, hard halt at 6). |
| **Phase 7 — Root cause + fix** | Promote winning hypothesis to `## Root Cause`. Complete Evidence coverage table (one row per `EVID-NNN`; fix-gate requires zero `unexplained` rows). Bundled `light-fix` consult (both consultants in parallel). Inline implementation with self-check. Non-negotiable Codex review. |
| **Phase 8 — Verification** | Append `## Verification`. Two mandatory items: regression test tied to winning hypothesis; coincidence check re-running top eliminated alternative's discriminating test to confirm it still falsifies. |
| **Phase 9 — Post-mortem (mandatory)** | Append `## Post-mortem` (Summary, Timeline, Root cause, Fix, Why we didn't catch it, Action items, Confidence). Optional `/z-mr-review` integration. Action items can be converted to follow-up tasks or `/z-test` seeds. |
| **Phase 10 — Finalize** | Log `debug_run_end`. Push-notify. |

## Auto-bail thresholds (softened — heavy path)

Unlike `/z-fix`, `/z-debug` has relaxed auto-bail thresholds. Bail triggers only on:

- **Multiple modules** — cross-module impact.
- **Architectural change** — redesign required, not just localized edit.
- **New public surface** — new wire format, new schema, new public API.

The old `>5 files` trigger is dropped: the heavy path expects larger localized fixes. When a threshold fires, the command writes `escalation.md` and recommends `/z-plan`.

## Posterior lookup table (locked)

This table is the sole scoring rule. The orchestrator applies it mechanically — no subjective adjustment, no consultant input.

| prior \ likelihood | strongly_falsified | weakly_falsified | inconclusive | weakly_supported | strongly_supported |
|---|---|---|---|---|---|
| **high** (overlap=3) | eliminated | low | high | high | very_high |
| **med** (overlap=2) | eliminated | very_low | med | high | very_high |
| **low** (overlap=1) | eliminated | very_low | low | med | high |

Posterior order: `very_high > high > med > low > very_low > eliminated`.

**Prior comes from overlap count alone** (how many of the three independent sources — orchestrator, Codex, Gemini — proposed the same hypothesis). **Likelihood is assigned by the orchestrator alone** after reading raw test output. No consultant ever sees raw test output or assigns a likelihood bucket.

## Phase-visibility matrix (consultant context discipline)

This table is the source of truth for what each subagent dispatch sees. Subagent prompts must never include sections outside the listed scope, and must never receive likelihood buckets or posteriors.

| Phase | Consultant call | Sections passed | Forbidden | Raw test output? |
|---|---|---|---|---|
| 3a (Round 1) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; doc-fetcher synthesis | Hypothesis Pool (doesn't exist yet); any orchestrator-internal block | No |
| 3b (Round 2) | both, MODE `generate-hypotheses-round2-adversarial` | Problem; Evidence Inventory; Hypothesis Pool (full) | Test Matrix; Experiment Log; Score Updates | No |
| 6 (optional Round 3) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; eliminated `claim` text + falsifying `discriminating_test` only | priors, likelihoods, posteriors, full Eliminated Alternatives section | No |
| 7 (fix consult) | both, MODE `light-fix` | Problem; Evidence Inventory; winning Hypothesis Pool rows; Experiment Log; draft Root Cause; draft Evidence coverage table | Eliminated Alternatives; Score Updates history | No |

Orchestrator alone reads raw test output and assigns likelihood buckets (Phase 6, step 2). This row never appears in the table.

## Sidebar: Why orchestrator interprets likelihood, not consultants

The most tempting shortcut in the hypothesis tournament is asking a consultant to read the test output and decide whether a hypothesis is supported or falsified. This is forbidden for two reasons.

First, **consultant contamination.** Once a consultant sees which hypotheses were supported, it cannot unsee that context. Subsequent consultant calls for Round 2 new hypotheses or Round 3 recovery would be anchored on the test results, defeating the independence guarantee the prior system depends on.

Second, **bucket gaming.** The posterior lookup table works because `likelihood` and `prior` are produced by orthogonal processes — prior comes from inter-model agreement at generation time, likelihood comes from raw empirical output interpreted by a single evaluator. If a consultant assigns likelihood, the "independent" prior and the likelihood become correlated: the same model that proposed a hypothesis is now scoring how well the test supports it. The table collapses from an adversarial check into a self-confirming loop.

The orchestrator's role is not to be smart about likelihood — it is to be **consistent and non-self-interested**: read the output, apply the bucket definition literally, record the rule that fired, move on.

## Worked example

### Scenario

Symptom: "User profile images are loading with a 400ms delay on first view, but only for users who signed up before 2024-01-01. Users who signed up after are instant."

Phase 0: user confirms no concrete hypothesis — proceed with `/z-debug`.

Phase 1 problem statement captured. Phase 2 evidence inventory:

- **EVID-001:** Slow requests always target the `/avatars/legacy/` URL prefix; fast requests use `/avatars/`.
- **EVID-002:** Network tab shows the 400ms is server-side TTFB, not download time.
- **EVID-003:** `user.created_at < 2024-01-01` correlates exactly with slow responses in production logs (1,200 rows sampled).
- **EVID-004:** No CDN cache miss logged — the delay originates from the app server, not the CDN.
- **EVID-005:** Legacy avatars are stored as `.png`; new avatars are `.webp`.

### Round 1 hypothesis generation

Three sources (orchestrator, Codex, Gemini) each independently propose exactly 3 hypotheses. After merge and semantic dedup, the pool has 8 rows (H001 was proposed by both orchestrator and Codex; all other rows were unique):

| id | claim | proposed_by | overlap |
|---|---|---|---|
| H001 | Legacy avatar route hits a synchronous disk-read path; new route uses async storage | [orchestrator, codex] | 2 |
| H002 | `.png` files are being re-encoded to `.webp` on-the-fly per request | [orchestrator] | 1 |
| H003 | Legacy avatar route queries a distant origin server, adding round-trip latency | [gemini] | 1 |
| H004 | Legacy user profiles lack a DB index on `avatar_path`; every request triggers a full scan | [codex] | 1 |
| H005 | Legacy avatars are served through a middleware chain that includes an auth re-check | [gemini] | 1 |
| H006 | `/avatars/legacy/` handler opens a new DB connection per request instead of pooling | [orchestrator] | 1 |
| H007 | Legacy route applies an image-resizing transform before serving | [gemini] | 1 |
| H008 | Legacy avatar storage bucket is in a different cloud region than the app server | [codex] | 1 |

### Round 2 adversarial

Round 2 dispatches both consultants with the merged pool. Results after orchestrator post-process:

- **NEW added:** H009 — "Legacy route logs each request to a synchronous audit table insert" (identified by Codex as an orthogonality gap not covered by existing rows; one source, `overlap=1`).
- **NEW added:** H010 — "Legacy avatars are stored with per-file encryption; decryption is synchronous CPU-bound" (identified independently by both Gemini and Codex; collapsed to one row with `proposed_by: [gemini, codex]`, `overlap=2`).
- **Duplicate dropped:** H003 and H008 were judged semantically equivalent ("distant origin server" ≡ "different cloud region"). H008 merged into H003; `overlap_count` recomputed as `len({gemini, codex}) = 2` (not arithmetic sum `1+1=2` — the rule counts unique sources: cap at 3).
- **False parallel-safe flagged:** H009 had `parallel_safe: true`; Codex critique cited "audit table INSERT acquires a row-level lock on `audit_log` — writes to shared state." Flag flipped to `false`.

Final pool: **9 rows** — H001, H002, H003, H004, H005, H006, H007, H009, H010. Accounting: 8 rows from R1 → drop H008 (merged into H003) → add H009 and H010 = 9 rows. H008 is retired; its ID is not reused.

### Test Matrix (initial)

| id | claim | overlap | prior | cost | parallel | status |
|---|---|---|---|---|---|---|
| H001 | Legacy route hits synchronous disk-read path | 2 | med | cheap | true | active |
| H002 | `.png` re-encoded to `.webp` per request | 1 | low | cheap | true | active |
| H003 | Legacy route queries distant origin server | 2 | med | cheap | true | active |
| H004 | Missing DB index on `avatar_path` | 1 | low | free | true | active |
| H005 | Legacy middleware includes auth re-check | 1 | low | cheap | true | active |
| H006 | Legacy handler opens new DB connection per request | 1 | low | cheap | true | active |
| H007 | Legacy route applies image-resizing transform | 1 | low | medium | false | active |
| H009 | Legacy route logs synchronous audit INSERT | 1 | low | cheap | false | active |
| H010 | Per-file encryption with synchronous CPU-bound decryption | 2 | med | cheap | true | active |

Outlier carve-out: H002 and H004 (`overlap=1`) inserted near the front of the test order despite low prior.

### Isolation cycle 1

Parallel-safe batch run (H001, H002, H003, H004, H005, H006, H010):

- H001 — profiler shows `/avatars/legacy/` handler calls `File.read_sync`, but tracing reveals the same call exists in the new route's cold-path. Likelihood: `weakly_supported`.
- H002 — no encoder in the call stack during the request. Likelihood: `strongly_falsified`.
- H003 — latency trace shows a 380ms outbound call from the app server on the legacy path; new route makes no equivalent call. Likelihood: `weakly_supported`.
- H004 — `EXPLAIN` shows index exists on `avatar_path`. Likelihood: `strongly_falsified`.
- H005 — middleware stack identical for both routes. Likelihood: `strongly_falsified`.
- H006 — connection pool log shows reuse on legacy route. Likelihood: `strongly_falsified`.
- H010 — no encryption call in profiler output. Likelihood: `strongly_falsified`.

Serial tests (H007, H009):

- H007 — no resizing transform found. Likelihood: `strongly_falsified`.
- H009 — audit table query absent from query log during request. Likelihood: `strongly_falsified`.

**Score Updates — Cycle 1:**

```
H001: prior=med + likelihood=weakly_supported  → posterior=high
H002: prior=low + likelihood=strongly_falsified → posterior=eliminated
H003: prior=med + likelihood=weakly_supported  → posterior=high
H004: prior=low + likelihood=strongly_falsified → posterior=eliminated
H005: prior=low + likelihood=strongly_falsified → posterior=eliminated
H006: prior=low + likelihood=strongly_falsified → posterior=eliminated
H007: prior=low + likelihood=strongly_falsified → posterior=eliminated
H009: prior=low + likelihood=strongly_falsified → posterior=eliminated
H010: prior=med + likelihood=strongly_falsified → posterior=eliminated
```

**Fix-gate check after Cycle 1:** No hypothesis has reached `very_high`. H001 and H003 are both at `high`. Fix-gate remains closed; proceed to Cycle 2 with the two surviving hypotheses.

### Isolation cycle 2

Two surviving hypotheses (H001 and H003), tested in order:

- H001 — deeper profiler run with the new route under identical load confirms `File.read_sync` is present in both routes' hot paths; the cold-path result from Cycle 1 was a false signal. Likelihood: `weakly_falsified`.
- H003 — network trace confirms the outbound call from the legacy handler targets `storage-us-west-2.internal` while the app server is in `us-east-1`; cross-region latency accounts for the full 400ms delta. Likelihood: `strongly_supported`.

**Score Updates — Cycle 2:**

```
H001: prior=med + likelihood=weakly_falsified  → posterior=very_low
H003: prior=med + likelihood=strongly_supported → posterior=very_high
```

**Fix-gate check after Cycle 2:** H003 posterior = `very_high`. Draft root cause written; Evidence coverage table completed:

### Evidence coverage table

| evid_id | text | status | how_root_cause_handles_it |
|---|---|---|---|
| EVID-001 | Slow requests always target `/avatars/legacy/` URL prefix | explained | The legacy handler routes avatar storage calls to the distant origin; the new handler uses the local region. |
| EVID-002 | 400ms is server-side TTFB, not download time | explained | The outbound cross-region storage call blocks the response thread; TTFB rises while download size is unchanged. |
| EVID-003 | `user.created_at < 2024-01-01` correlates with slow responses | explained | Users before 2024-01-01 have legacy avatars stored on the distant origin, routed through the legacy handler by the migration flag. |
| EVID-004 | No CDN cache miss logged | falsifies_alternative | The delay occurs inside the app server (outbound storage call), not at the CDN layer — consistent with H003. |
| EVID-005 | Legacy avatars are `.png`; new avatars are `.webp` | orthogonal_with_reason | File format is a correlation artifact of the migration boundary, not a cause — H002 (re-encoding) was eliminated; format has no bearing on H003's storage-origin routing. |

Zero `unexplained` rows — fix-gate opens. **Convergence in 2 isolation cycles** (Cycle 2 achieved `very_high` on H003 with full evidence coverage).

Fix consult dispatched; fix implemented; Codex review passed; post-mortem written.

## Fix-gate conditions (hard, both must hold)

1. Winning hypothesis `posterior == very_high`.
2. Zero rows in the Evidence coverage table with `status == unexplained`.

If either condition fails, either upgrade the root cause statement or return to Phase 6 for more experiments. Do not advance to fix on a partial story.

## When to pick `/z-fix` vs `/z-debug`

| Signal | Pick |
|---|---|
| You can state a hypothesis in one sentence. | `/z-fix` |
| You cannot name what's causing the symptom. | `/z-debug` |
| The fix touches 1-5 files in one module. | `/z-fix` |
| The fix may involve multiple modules or public APIs — root cause unclear. | `/z-debug` |
| The fix scope is confirmed too large (cross-module impact, architectural change). | `/z-plan` |
| You want a fast loop — 15 min target. | `/z-fix` |
| You want adversarial hypothesis generation and Bayesian elimination. | `/z-debug` |
| A previous `/z-debug` run identified the root cause. | `/z-fix` to implement the fix. |
| Post-mortem is optional. | `/z-fix` |
| Post-mortem is mandatory. | `/z-debug` |

## Hard rules

- **Never debug without repro.** If repro is impossible and user picks "proceed on inference," document that decision in the Problem section and flag in the Post-mortem Confidence section.
- **Never skip the post-mortem.** Even on a trivial bug — the preventative action-items habit is what makes `/z-debug` different from `/z-fix`.
- **Never skip Codex review on the fix.** The safety gate is non-negotiable.
- **Always emit BOTH Round 1 and Round 2 hypothesis-generation consults** — four subagent calls total during generation (2 in R1 + 2 in R2). Plus a fifth pair in Phase 7 for the fix consult.
- **Likelihood-bucket assignment is orchestrator-only.** Never delegate the `{strongly_falsified, ..., strongly_supported}` call to a consultant. Never pass raw test output to a consultant.
- **Orchestrator's Round 1 block MUST be checkpointed to disk** (`archive/<run>/round1-orchestrator.md`) BEFORE consultant dispatch. Re-read from disk at merge time, not from conversation state.
- **Wrong-tool gate (Phase 0) is non-skippable.** If the user already has a hypothesis, exit with a `/z-fix` recommendation — do not proceed.
- **Fix-gate is objective and binary.** Opens only when (a) winning hypothesis posterior == `very_high` AND (b) every `EVID-NNN` has status in `{explained, falsifies_alternative, orthogonal_with_reason}` (zero `unexplained`).
- **Never proceed past auto-bail thresholds without explicit user override.** When cross-module impact, architectural change, or new public surface is detected, write `escalation.md` and halt. Only continue if the user explicitly overrides in response to that escalation.
- **No emojis** anywhere in artifacts.

## See also

- `commands/z-debug.md` — full phase-by-phase procedure with prompts, schemas, and loop logic.
- `docs/human/z-fix.md` — the lightweight companion for known-root-cause bugs.
- `docs/human/commands.md` — index of all slash commands.
