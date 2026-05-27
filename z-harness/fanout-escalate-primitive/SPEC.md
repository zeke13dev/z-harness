# SPEC — fanout-escalate-primitive v1a

## Overview

Adds a Haiku `scope-probe` subagent that runs as Phase 0 of `/z-audit` and `/z-brainstorm`. The probe classifies the topic as LIGHT (narrow single run, narrowed scope) / MEDIUM (standard single run) / HEAVY (fan out N parallel sub-runs along a natural axis, main thread reconciles). v1a ships the probe + SCOPE.json artifact + calibration harness + integrations into `/z-audit` and `/z-brainstorm` ONLY. Deletions of existing escalation chains are explicitly v1b (see [BRAINSTORM.md](BRAINSTORM.md) User choice section).

## Relationship to `complexity-classifier`

These are NOT duplicate concepts. `complexity-classifier` operates on a **single task block AFTER TASKS.md is written** and returns `low|medium|high` to pick the **implementer model** at dispatch time. `scope-probe` operates on a **topic/argument BEFORE Phase 1** and returns `LIGHT|MEDIUM|HEAVY` to pick the **execution topology** (single run vs fan-out). Different inputs (task block vs free-text topic), different outputs (implementer model tier vs fan-out shape + chunks), different invocation point (Phase 8 vs Phase 0), different host commands (anything that produces TASKS.md vs `/z-audit` + `/z-brainstorm` in v1a). They coexist by design; future readers should consult `agents/scope-probe.md` for scope routing and `agents/complexity-classifier.md` for per-task model routing.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/fanout-escalate-primitive/BRAINSTORM.md | 2026-05-27T17:08:00Z |
| RESEARCH.md | — | n/a |

## Goals (v1a)

1. Build `scope-probe` Haiku agent with hybrid output contract.
2. Define and document `SCOPE-<host>.json` schema (live + archived + namespaced per host command).
3. Integrate scope-probe as Phase 0 of `/z-audit` (unconditional, MEDIUM-passthrough).
4. Integrate scope-probe as Phase 0 of `/z-brainstorm` (same pattern, validates 2 distinct axis taxonomies).
5. Build `scope-reconciler-audit` and `scope-reconciler-brainstorm` Sonnet agents for HEAVY fanout synthesis.
6. Build calibration harness `scripts/scope-probe-calibrate.py` with versioned rubric in `scripts/CALIBRATION.md`.
7. Run calibration against 5–6 historical archive runs (3× majority-vote per run). Tune thresholds. Verify the 4 falsifiability tripwires.

## Non-goals (deferred to v1b)

- Deleting `/z-plan-light` Phase 1 up-route.
- Deleting `/z-plan` pre-Phase-1 Plan Route Check.
- Deleting `/z-debug` mid-flight architectural bail.
- Retiring/demoting `planning-router`.
- Folding `/z-plan-split` into `/z-plan` HEAVY.
- Integration into `/z-debug`, `/z-plan`, `/z-review-all`, `/z-implement-all`, `/z-fix`, `/z-do`.
- Garbage collection for stale live `SCOPE-*.json` files.
- AskUser confirmation gate on low-confidence probe results (just degrades to MEDIUM in v1a).

## Per-file specs

### `agents/scope-probe.md` (NEW)

**Frontmatter:**
```yaml
---
name: scope-probe
description: Pre-dispatch Haiku scope classifier. Runs as Phase 0 of host z-* commands (initially /z-audit and /z-brainstorm). Classifies the topic as LIGHT / MEDIUM / HEAVY by walking codebase structure and counting natural seams, with a caller-supplied axis taxonomy. Returns a parseable hybrid contract (line-prefix routing fields + fenced JSON chunks array). Advisory only — orchestrator owns final dispatch.
tools: Read, Grep, Glob
model: haiku
---
```

**Inputs from caller (in prompt):**
- `host_command:` one of `z-audit`, `z-brainstorm` (extensible).
- `topic:` the user's argument verbatim.
- `axis_taxonomy:` JSON array of allowed axis names (caller-supplied). Examples:
  - `/z-audit`: `["per_dimension", "per_component", "per_risk_domain", "per_workflow"]`
  - `/z-brainstorm`: `["per_vendor", "per_framing"]`
- `repo_root:` absolute path.
- `run_id:` the host command's `$RUN`.

**Procedure (5 steps, per BRAINSTORM):**
1. Parse topic into candidate entities (file paths, module names, named components).
2. For each candidate, walk directory structure 2 levels deep (cap at 4 candidates).
3. Count seams:
   - Subdirectories with their own entry points or `mod.rs`/`__init__.py`/`SKILL.md`/`<name>.md` markers.
   - Files with distinct import profiles (heuristic only — count of distinct top-level imports).
   - Named cluster directories matching `strategies/`, `components/`, `commands/`, `agents/`, `skills/`, `hypotheses/`, `dimensions/`.
4. Optionally query `doc-fetcher` for cluster docs related to the topic (single call only; depth=summary).
5. Pick the axis from `axis_taxonomy` best supported by seam evidence. Emit the manifest.

**Output contract (hybrid):**

```
STATUS: classified | refused | bad_input
MODE: LIGHT | MEDIUM | HEAVY
AXIS: <axis-name-from-caller-taxonomy> | none
CONFIDENCE: high | medium | low
REASON_CODES: <comma-separated codes>
REASON: <one line, <=160 chars>

```json
{
  "chunks": [
    {"id": "C1", "intent": "<short>", "scope_hint": "<file-or-symbol>", "evidence": "<why this chunk>"},
    ...
  ],
  "seams_counted": <int>,
  "candidates_walked": <int>
}
```
```

**Mode classification thresholds (v1a placeholders, tuned by calibration):**
- LIGHT: ≤1 file/component referenced; 0 seams.
- MEDIUM: 2–5 files/components; ≤2 seams.
- HEAVY: ≥3 seams OR named sub-cluster directory exists OR module name with ≥4 direct children.

**Three-state graceful degradation (D4):**
- **High-confidence axis pick:** `STATUS: classified`, `CONFIDENCE: high`, populated chunks.
- **Low-confidence pick:** `STATUS: classified`, `CONFIDENCE: low`, populated chunks with `low_confidence_reason` in REASON_CODES. Orchestrator may proceed or AskUser (v1a: proceeds with logged warning).
- **No axis evidence:** `STATUS: refused`, `MODE: MEDIUM`, `AXIS: none`, empty chunks. Orchestrator falls back to standard single-run behavior.

**Stable REASON_CODES:** `single_file`, `flat_module`, `named_cluster_dir`, `import_profile_split`, `module_with_subchildren`, `topic_too_vague`, `topic_resolves_to_missing_path`, `low_confidence_pick`, `taxonomy_no_match`, `axis_evidence_thin`.

**Hard rules:**
- Read-only. Never edits files.
- Never invents an axis name outside the caller's `axis_taxonomy` (except `none` on refusal).
- Never recommends a different host command (that's planning-router's job).
- Always returns exactly one fenced JSON block; orchestrator parses it.

**Doc-fetcher dispatch is scope-probe-internal.** Step 4 of the 5-step procedure dispatches `doc-fetcher` from inside scope-probe when cluster docs may help disambiguate the axis. Host commands do NOT have to run doc-fetcher before invoking scope-probe — scope-probe handles its own doc-grounding. This means scope-probe is safe to run as the FIRST action of a host command (before Phase 1 scaffolding); its internal doc-fetcher call is independent of any doc-fetcher invocation later in the host's pipeline.

**Parser safety rule (addresses Gemini's "Haiku may put prefix inside fence" concern):**
The host command parser MUST:
1. Read the response line-by-line; collect `KEY: VALUE` lines that occur BEFORE the first ` ```json ` fence marker. Any line-prefix headers found INSIDE the fence are an error.
2. Extract the fenced JSON block via the same regex review-agent uses (`^```json\n(.*?)^```$`).
3. On parser failure (missing line-prefix headers, no fenced block, malformed JSON, or prefix-inside-fence): emit `scope_probe_malformed` event, treat as `STATUS: refused` + `MODE: MEDIUM`, log the raw response for debugging. Host command proceeds as MEDIUM. Never retry — Haiku non-determinism makes retry costly and rarely produces a different shape.

### `agents/scope-reconciler-audit.md` (NEW)

**Frontmatter:** `name: scope-reconciler-audit`, `model: sonnet`, `tools: Read, Grep, Glob`.

**Role:** Given the N per-chunk auditor returns (each chunk ran its own `/z-audit` sub-flow producing per-chunk findings), merge into a unified REPORT.md.

**Inputs:** `host_run_id`, `chunks: [{id, findings_path}]`, `target_slug`, `axis`.

**Procedure:**
1. Read each chunk's `findings-*.md`.
2. Dedupe findings by (severity, normalized-evidence-line) across chunks.
3. Preserve dissent: if 2 chunks find conflicting things on the same site, emit BOTH with a `## Cross-chunk dissent` note.
4. Elevate cross-chunk patterns: if ≥2 chunks flag the same systemic issue, bump severity by one tier.
5. Emit unified `REPORT.md` and per-chunk `chunks/` subdirectory preserved verbatim.

**Hard rule:** never smooths over disagreement. Dissent is a feature.

### `agents/scope-reconciler-brainstorm.md` (NEW)

**Frontmatter:** `name: scope-reconciler-brainstorm`, `model: sonnet`, `tools: Read`.

**Role:** Given N per-chunk brainstorm sub-runs (each producing its own BRAINSTORM.md), merge into a top-level BRAINSTORM.md that preserves framings per chunk and adds a meta-level anti-bias check across chunks.

**Inputs:** `host_run_id`, `chunks: [{id, brainstorm_path}]`, `axis`.

**Procedure:**
1. Read each chunk's BRAINSTORM.md.
2. Concatenate framing sections under `## Chunk: <chunk_id>` headers.
3. Run a cross-chunk anti-bias check: are there framings unique to one chunk that should propagate? Are there contradictions?
4. Emit unified BRAINSTORM.md with `chosen_framing: pending` (user picks).

### `commands/z-audit.md` (EDIT)

Insert a new **Phase 0** block between the current Setup and Phase 1 ("Pre-flight scoping"). The block:
1. Defines `AXIS_TAXONOMY='["per_dimension","per_component","per_risk_domain","per_workflow"]'`.
2. Dispatches `Agent(subagent_type="scope-probe", ...)` with `host_command: z-audit` and the `AXIS_TAXONOMY`.
3. Parses the hybrid return; extracts `MODE`, `AXIS`, `chunks`.
4. Writes `z-harness/<slug>/archive/<RUN>/SCOPE.json` (archive-first, atomic) AND `z-harness/<slug>/SCOPE-audit.json` (live, namespaced) with full manifest + `last_updated` + `last_run_id`.
5. Branches:
   - **LIGHT:** populate SCOPE.json with `dimensions_hint: [...]` (a narrowed dimension list derived from the topic). Phase 1's existing AskUserQuestion for dimension selection consults SCOPE.json FIRST — if `dimensions_hint` is present and `MODE: LIGHT`, Phase 1 auto-confirms that dimension list without asking the user (Phase 1's prompt phrasing changes from "Which dimensions?" to "Phase 0 suggests <dimensions>; proceed?").
   - **MEDIUM:** SCOPE.json populated but no `dimensions_hint`. Phase 1 runs unchanged (user picks dimensions interactively).
   - **HEAVY:** Phase 1 dispatches `/z-audit` as N parallel sub-flows (one per chunk; each sub-flow uses `--scope-from <chunk-path>` to narrow target — see new flag spec below). After all sub-flows complete, dispatch `scope-reconciler-audit` to produce unified REPORT.md. Skip the standard Phase 2 auditor dispatch (replaced by per-chunk sub-runs).
   - **refused / MEDIUM-fallback:** SCOPE.json populated with `MODE: MEDIUM`, empty chunks. Phase 1 unchanged.

**Critical: no double-scoping.** Phase 1's existing pre-flight scoping logic MUST consult SCOPE.json's `dimensions_hint` field before its own auto-derivation runs. The Phase 0 / Phase 1 contract is "Phase 0 narrows, Phase 1 confirms-and-proceeds." Phase 1 never re-derives scope from scratch when SCOPE.json exists for this run.

**`--scope-from <chunk-spec>` flag spec for `/z-audit`:** new CLI flag, parsed at the TOP of `/z-audit` **BEFORE Setup** (slug derivation, doc-fetcher, version stamp, run-start logging). This ordering ensures recursive sub-flows do NOT pollute the parent run's slug or events.

**Input formats accepted for `<chunk-spec>`:**
- **Bare chunk ID** (e.g. `C1`): resolved against the parent run's SCOPE.json found via the `$Z_HARNESS_PARENT_RUN_ID` env var that the parent's HEAVY dispatch sets when spawning sub-flows. Sub-flow's SCOPE.json path: `z-harness/<parent-slug>/archive/$Z_HARNESS_PARENT_RUN_ID/SCOPE.json`.
- **Absolute path** to a SCOPE.json file plus `#<chunk-id>` fragment (e.g. `/abs/path/SCOPE.json#C1`): used when invoking out-of-band (no parent run context). The path is split on `#` to yield (file, chunk_id).

When `--scope-from` is present:
1. `/z-audit` sets `SKIP_PHASE_0=true` immediately (before Setup runs).
2. Setup runs but `$ARGUMENTS` is sanitized — `--scope-from <chunk-spec>` tokens are stripped before slug derivation or doc-fetcher dispatch.
3. After Setup completes, the resolved chunk's `scope_hint` is loaded into `$SCOPE_HINT` and used as the operative target by Phase 1.
4. Phase 0 is skipped (SKIP_PHASE_0=true). **Anti-sprawl invariant is enforced by this skip alone — no separate event needed.** Sub-flows cannot recursively go HEAVY because they never reach Phase 0's HEAVY dispatch branch.

(The prior SPEC text "When Phase 0 runs, it MUST skip HEAVY dispatch" is removed — it referenced a code path that doesn't execute when SKIP_PHASE_0 is set.)
6. Log events: `scope_probe_start`, `scope_probe_classified`, `scope_fanout_dispatched` (HEAVY only), `scope_fanout_reconciled` (HEAVY only).

### `commands/z-brainstorm.md` (EDIT)

Insert a new **Phase 0** block immediately after Setup. The original `/z-brainstorm` pipeline order is Setup → Plan Route Check → Phase 1 scaffolding → Phase 2 ideators → Phase 3 synthesis → Phase 4 finalize. Insert Phase 0 so the new order is **Setup → Phase 0 → Plan Route Check → Phase 1 → …**. scope-probe and Plan Route Check are independent gates: scope-probe sizes the topic against codebase structure (and dispatches doc-fetcher internally per its step 4); Plan Route Check decides whether brainstorm is even the right command for this scope. Neither depends on Phase 1 signals.

Same pattern as `/z-audit` Phase 0 but with `axis_taxonomy: ["per_vendor","per_framing"]`. Writes `SCOPE-brainstorm.json` (live + archived). scope-probe internally dispatches doc-fetcher (per its step 4), so Phase 0 does not depend on Phase 1's doc-fetcher run.

**HEAVY mode** (rare for brainstorm — most topics are MEDIUM):
1. Phase 0 emits N chunks (one per axis-defined sub-topic, e.g. one per `per_vendor` value).
2. Dispatch N parallel `/z-brainstorm` **sub-flows**, one per chunk, each receiving `$Z_HARNESS_PARENT_RUN_ID` (current run's ID) so they can locate the parent's SCOPE.json. Each sub-flow:
   - Skips Phase 0 entirely (parent already ran it).
   - Skips Plan Route Check (parent already passed it; sub-flows are inherently in brainstorm).
   - Runs Phase 1 (scaffolding) **scoped to its chunk's `scope_hint`**.
   - Runs Phase 2 (ideators) and **Phase 3 (synthesis)** to completion. **Each sub-flow produces its own per-chunk BRAINSTORM.md** at `z-harness/<parent-slug>/archive/<RUN>/chunks/<chunk-id>/BRAINSTORM.md`.
   - Skips Phase 4 (no per-chunk user-pick gate — selection happens at the parent level in HEAVY mode).
3. After all sub-flows return, dispatch `scope-reconciler-brainstorm` to merge the N chunk BRAINSTORM.md files into a top-level unified BRAINSTORM.md (chunk-major output per T003's existing contract: `## Chunk: C1 / ## Framing: claude` etc).
4. **Phase 4 (HEAVY-mode branch)** — NEW selection logic added in v1a Task T016: present the user with a `chunks × framings` matrix; user picks ONE `(chunk_id, framing)` pair (e.g. "C1: codex"). The picked pair becomes the seed for any downstream `/z-plan`.

**LIGHT / MEDIUM mode:** Phase 0 result is informational — SCOPE-brainstorm.json gets written but no fanout. Plan Route Check and Phase 1+ proceed unchanged. Phase 4 stays unchanged (claude/codex/gemini selection only).

### `scripts/scope-probe-calibrate.py` (NEW)

CLI: `python3 scripts/scope-probe-calibrate.py --archive-root z-harness/archive [--epoch N] [--n-runs 6] [--samples-per-run 3]`.

**Behavior:**
1. Walk `z-harness/*/archive/*/` directories. Pick up to `n_runs` recent runs that have `manifest.json` (skip incomplete runs).
2. For each picked run, extract: `slug`, `topic` (from `events.jsonl` `run_start`), `manifest.json`, `events.jsonl` escalation events.
3. Compute ground-truth `LIGHT|MEDIUM|HEAVY` per the rubric (see [scripts/CALIBRATION.md](../scripts/CALIBRATION.md)).
4. For each run, dispatch `scope-probe` `samples_per_run` times (default 3) via a CLI shim (subprocess; replicate the Agent-dispatch prompt format). Take majority-vote classification as the run's Haiku-classification.
5. Compute confusion matrix: scope-probe-MODE × ground-truth-MODE.
6. Emit `scripts/calibration-epoch-<N>.json`: `{epoch, rubric_version, n_runs, samples_per_run, runs: [{slug, run_id, topic, classified_mode, ground_truth_mode, match}], confusion_matrix, pct_heavy, pct_medium, pct_light}`.
7. Print a tripwire report to stdout:
   - **Tripwire 1** (≥70% MEDIUM): warn if `pct_medium >= 70`.
   - **Tripwire 2** (<20% HEAVY): warn if `pct_heavy < 20`.
   - **Tripwires 3, 4** (synthesis quality, semantic axis): require manual review; flag for human follow-up.

**Exit codes:** 0 if no tripwires fire; 1 if any tripwire fires.

### `scripts/CALIBRATION.md` (NEW)

Documentation file containing the versioned ground-truth rubric. Frontmatter:
```yaml
---
rubric_version: 1
applies_to: scope-probe-calibrate.py
---
```

Body documents the rubric as a Python function spec:

```python
def classify_ground_truth(manifest: dict, events: list[dict]) -> str:
    """Returns 'LIGHT' | 'MEDIUM' | 'HEAVY' from a historical run's artifacts.

    Rule (rubric_version 1):
      - HEAVY if events contains any escalation_* event OR manifest.tasks_total >= 16.
      - LIGHT if manifest.tasks_total <= 5 AND tasks_complexity.high == 0
              AND no plan_route_decision event.
      - MEDIUM otherwise.
    Tie-break: if signals disagree, prefer escalation event > tasks_complexity > tasks_total.
    """
```

The actual function lives in `scope-probe-calibrate.py`; CALIBRATION.md is the human-readable canonical reference plus the rubric_version bump log.

### `z-harness/<slug>/SCOPE-<host>.json` (NEW SCHEMA)

```json
{
  "host_command": "z-audit",
  "slug": "<target-slug>",
  "last_run_id": "20260527T175422Z-fanout-escalate-primitive",
  "last_updated": "2026-05-27T18:00:00Z",
  "mode": "HEAVY",
  "axis": "per_dimension",
  "confidence": "high",
  "reason_codes": ["named_cluster_dir", "module_with_subchildren"],
  "chunks": [
    {"id": "C1", "intent": "...", "scope_hint": "...", "evidence": "..."}
  ],
  "seams_counted": 4,
  "candidates_walked": 2,
  "scope_probe_version": "1"
}
```

Same schema for the archived copy at `z-harness/<slug>/archive/<RUN>/SCOPE.json` (note: archived copy is NOT namespaced — one per run, host_command is the discriminator field inside).

## Invariants

1. `scope-probe` is advisory: host command may override probe's `MODE` based on user flags or its own signals.
2. Probe never invents axes outside `axis_taxonomy`.
3. SCOPE writes are archive-first, then live-overwrite (atomic via tmp+rename).
4. Live `SCOPE-<host>.json` includes `last_run_id` so readers can detect stale entries when the matching archive `events.jsonl` is missing.
5. HEAVY fanout dispatches sub-flows of the SAME host command (not different commands); reconciler runs ONCE in the orchestrator's main thread after all sub-flows return.
6. Probe failure → MEDIUM fallback + logged warning. Never block the host command.
7. Calibration epochs are append-only; rubric_version bumps invalidate prior epochs for the purposes of trend comparison.

## Edge cases / error handling

- **Topic resolves to a deleted path:** `REASON_CODES: topic_resolves_to_missing_path`, `STATUS: refused`, `MODE: MEDIUM`. Host proceeds.
- **`doc-fetcher` call from inside scope-probe fails:** scope-probe continues with zero doc-grounding (don't block on doc-fetcher).
- **`axis_taxonomy` is empty array:** scope-probe returns `STATUS: bad_input`. Caller must always provide a non-empty taxonomy.
- **Live SCOPE file write succeeds, archive write fails:** swap order — archive must succeed first. If archive write fails, abort scope-probe Phase 0 entirely; host proceeds as if probe was never dispatched.
- **HEAVY sub-flow fails mid-fanout (one chunk fails):** reconciler still runs on the surviving chunks; failed chunk recorded in REPORT.md as `chunk_failed`.
- **Reconciler fails:** main thread falls back to concatenated per-chunk artifacts with a `## Reconciliation failed — raw chunks below` header.

## DRY / KISS / SOLID

- **DRY:** SCOPE.json schema and the line-prefix output convention are shared between `/z-audit` and `/z-brainstorm`. Only the `axis_taxonomy` differs per host command. Future commands extend by passing a new taxonomy; the agent itself doesn't change. Reuses existing `doc-fetcher` for axis-discovery step 4 — no new doc-walking code.
- **KISS:** v1a deliberately ships **read-only** alongside existing escalation chains; no deletions, no AskUser gates, no garbage collection. Calibration harness is one Python script + one doc file. The hybrid output contract uses two established z-harness patterns (line-prefix + fenced JSON) rather than inventing a third.
- **SOLID:**
  - *Single responsibility:* scope-probe classifies; per-host reconcilers synthesize; calibration harness validates. No agent owns more than one of those.
  - *Open/closed:* taxonomy is runtime input — extending to new host commands does NOT require editing scope-probe.md. New host = new taxonomy + new reconciler + Phase 0 block.
  - *Liskov:* both `scope-reconciler-audit` and `scope-reconciler-brainstorm` honor the same contract (chunks-in, unified-artifact-out, preserve-dissent invariant).
  - *Interface segregation:* live SCOPE files namespaced per host so readers only depend on the host they care about.
  - *Dependency inversion:* host commands depend on the scope-probe contract (line-prefix + JSON), not on the agent's internal implementation. Future scope-probe v2 can change heuristics without breaking host commands.
