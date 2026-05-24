# SPEC — plan-decompose (`/z-plan-split`)

## Overview

`/z-plan-split <topic>` is a pre-emptive scope splitter that catches "this topic is too big for one `/z-plan`" *before* the full planning ceremony begins. Instead of producing one sprawling 60-task plan, it fans out N narrower scopes to parallel `cluster-planner` subagents, each of which produces a focused 5-15-task plan. After all clusters complete, the main thread does light reconciliation (file-path overlap detection) and writes a SHARED-CONCERNS.md observation note plus a MANIFEST.md describing run order.

Reconciliation is a passive observation — there is no auto-generated `shared/` plan. If shared concerns exist, the user reads SHARED-CONCERNS.md and either runs a separate `/z-plan --slug=<root>/shared/` for them, edits leaf plans manually, or acknowledges and proceeds.

## When to use

- A topic that's about to be ≥40 tasks across multiple natural seams (per-strategy, per-component, per-phase with independent shipping).
- The output of `/z-audit` when findings span multiple strategies/components (user invokes `/z-plan-split` with the audit findings as topic).
- A `/z-brainstorm` framing that explicitly identifies multiple sub-features.

Not for: features with tight cross-cutting coupling, single-component refactors, anything `/z-plan-light` could handle.

## File layout

```
z-harness/<root-slug>/
├── MANIFEST.md                       # cluster listing + run order + status
├── SHARED-CONCERNS.md                # detected file overlaps; ack-gate frontmatter
├── archive/<RUN>/
│   ├── events.jsonl
│   ├── proposed-clusters.md          # main thread's initial cluster proposal
│   ├── confirmed-clusters.md         # post-user-approval cluster list
│   └── transcripts/                  # cluster-planner subagent transcripts
├── <cluster-1>/
│   ├── SPEC.md
│   ├── PLAN.md
│   ├── TASKS.md
│   └── archive/<RUN>/
├── <cluster-2>/
│   └── ...
└── shared/                           # only present if user manually runs /z-plan on it
    └── ...
```

One-level recursion is invariant. `/z-plan-split` cannot produce sub-clusters that themselves contain a MANIFEST.md — that would be a tree of arbitrary depth and is explicitly out of scope for v1. `/z-implement-all` errors out if it discovers nested MANIFESTs (`tree_depth_exceeded` event).

## MANIFEST.md schema

YAML frontmatter:

```yaml
---
artifact: manifest
slug: <root-slug>
generated_at: <UTC ISO 8601>
command: /z-plan-split <args>
input_hash: <16 hex>  # sha256(canonicalize(topic + cluster names + scopes))[:16]
status: ready | partial | failed
total_clusters: <N>
clusters_ready: <K>
---
```

`status` semantics (only values ever written to MANIFEST.md): `ready` = all clusters succeeded; `partial` = ≥1 cluster failed but ≥1 succeeded (`partial_tree: true` in SHARED-CONCERNS); `failed` = all clusters failed (total-failure halt — minimal MANIFEST, no SHARED-CONCERNS.md). The `planning` value is transient inside cluster-planner execution and is **never written to MANIFEST.md** — by the time MANIFEST is written, all cluster-planners have returned.

Body:

```markdown
# MANIFEST — <root-slug>

## Clusters

| ID | Name | Scope (one line) | Path | Status |
|----|------|------------------|------|--------|
| C1 | <name> | <scope> | <root>/<cluster_slug>/ | ready / failed |
| C2 | ... |

(Each cluster row also carries `attempts: <N>` and `final_status_at: <UTC ISO>` as inline metadata or in a parallel `## Attempts` section. `attempts: 1` is the common case; `attempts: 2+` means the cluster escalated a decision and was re-spawned after resolution. Per-cluster `Status` is only ever `ready` or `failed` — `planning` is transient and not persisted.)

## Run order

Clusters execute sequentially in this order. Cross-cluster task parallelism is v2.

1. C1 → C2 → C3 → shared (if user runs it)

## Shared concerns

See SHARED-CONCERNS.md for detected file-overlap observations.
```

A cluster's `Status` field is `ready` (cluster-planner returned ok) or `failed` (cluster-planner returned a hard error). Cluster-planner internally passes through a `planning` state during execution; it is never serialized to MANIFEST.md. MANIFEST is the source of truth — leaf TASKS.md statuses are per-cluster, MANIFEST status is per-cluster aggregate.

## SHARED-CONCERNS.md schema

YAML frontmatter:

```yaml
---
artifact: shared-concerns
slug: <root-slug>
generated_at: <UTC ISO 8601>
acknowledged: false              # user manually flips to true after reading; CLI override is --ack
acknowledged_at: <UTC ISO 8601>  # set by user (free-form) OR auto-stamped by `/z-implement-all` Setup 2b.7 the first time it sees `acknowledged: true`
acknowledged_by: <free text>     # set by user (optional note: "ran shared/ plan", "decided to ignore", etc.) — `/z-implement-all` does not auto-populate
overlap_count: <N>
partial_tree: <true|false>       # true iff any cluster has Status == failed in MANIFEST (the only non-ready persisted state)
---
```

**Partial-tree gate (Phase 7 review fix #6).** If `partial_tree: true`, `/z-implement-all` refuses to walk the tree unless invoked with `--force-partial`. Reasoning: overlap detection on a partial tree is a lower bound, not authoritative — failed clusters never contributed their FILES_TOUCHED to the analysis, so undetected overlaps are possible.

Body lists each detected file-path overlap:

```markdown
# Shared concerns — <root-slug>

## Overlap: `<file path>`

Touched by:
- <cluster-id-1> (<task-ids>): <task title>
- <cluster-id-2> (<task-ids>): <task title>

Likely severity: <low | medium | high>

## ...
```

**Severity heuristics (cascading precedence — Phase 7 review fix #7):**

Apply in order, first match wins. Files touched by exactly 1 cluster are severity `none` and excluded from SHARED-CONCERNS.md entirely.

1. **high**: file matches `.*\.(sql|migration|schema|toml|yaml|yml|proto)$`, OR basename is in the extension-less / dependency-manifest allowlist: `Dockerfile`, `Makefile`, `package.json`, `package-lock.json`, `Cargo.lock`, `pnpm-lock.yaml`, `yarn.lock` (shared schema/config/migration/lockfile/manifest). Severity wins regardless of cluster count (so a `package.json` touched in 2 clusters is `high`, not `low`; same for any lockfile). Monorepo caveat: in repos with per-workspace `package.json` files, two clusters touching *different* manifests will both flag as `high` (path-only detection, no semantic dedup) — the ack-gate is where the user judges these as real or spurious.
2. **medium**: file matches `.*\.(rs|py|ts|tsx|js|jsx)$` AND appears in ≥3 clusters (cross-cutting code module).
3. **low**: file matches `.*\.(rs|py|ts|tsx|js|jsx)$` AND appears in exactly 2 clusters.
4. anything else with ≥2 cluster touches: `low`.

**Path normalization (Phase 7 review fix #4).** Before applying heuristics, all paths (from FILES_TOUCHED and from TASKS.md `**Files:**` lines) are normalized: strip leading `/` or `./`; collapse `.` and `..` segments; normalize separator to `/`; reject paths that escape repo root (`..` walks past origin) — log `precontext_freshness_check_failed`-style event and exclude the path from overlap detection.

No semantic analysis (Codex/Gemini consult) in v1; deterministic heuristics only.

**Ack-gate:** `/z-implement-all` discovery refuses to start the tree if `SHARED-CONCERNS.md` exists with `acknowledged: false` (or field unset). User edits the file to flip `acknowledged: true` (with an optional `acknowledged_by:` note) after reading, then `/z-implement-all` proceeds.

If `overlap_count: 0`, SHARED-CONCERNS.md is still written (for audit/log consistency) but ack-gate auto-passes (no concerns to acknowledge).

## Phase contract for `/z-plan-split`

### Setup (steps 1-9)

Same shape as `/z-plan` Setup: slug derivation, RUN id, mkdir, version stamp, `plan_split_run_start` event, notification policy, usage-limit guard. Skip the docs-freshness gate (this command doesn't itself touch INDEX.json; cluster-planners may if applicable).

**Setup step 10 — cluster proposal seed:**
- If `--clusters="a,b,c"` flag is passed, parse it and skip Phase 1.
- Otherwise, dispatch `doc-fetcher` (Haiku, iff `docs/llm/INDEX.json` exists) for one-shot topic grounding.

### Phase 1 — Cluster proposal

Main thread (in-context, no subagent):
1. Read the topic + doc-fetcher synthesis (if any).
2. Propose 2-6 narrow scopes. Each scope is named in kebab-case (becomes the cluster slug) and has a 1-line description.
3. Write `archive/$RUN/proposed-clusters.md`.
4. `AskUserQuestion` with previews:
   - One option per proposed cluster (preview = name + scope)
   - Options to edit names/scopes (free-text follow-up)
   - "Add a cluster" / "Drop a cluster" / "Approve as proposed" / "Abandon"
5. After user confirms, write `archive/$RUN/confirmed-clusters.md`.

Constraint: minimum 2 clusters, maximum 6. If fewer than 2 distinct seams found, recommend `/z-plan` directly and exit. If more than 6, refuse and ask user to narrow the topic (or accept losing some seams).

### Phase 2 — Parallel cluster-planner dispatch

ONE message with N parallel `Agent()` calls:

```
Agent(
  subagent_type="cluster-planner",
  description="Plan cluster <cluster_id>",
  prompt="<topic context>\n\ncluster-id: <cluster_id>\ncluster-slug: <cluster_slug>\ncluster-name: <name>\ncluster-scope: <scope>\nroot-slug: <root>\noutput-path: z-harness/<root>/<cluster_slug>/\n\n... full prompt per cluster-planner agent spec ..."
)
```

All N receive the same root-level topic context + confirmed cluster list (so each leaf knows its siblings exist and can stay in scope).

### Phase 3 — Collect leaf returns + handle decision gates

For each cluster-planner return:
- `STATUS: ok` → mark cluster `ready` in MANIFEST.
- `STATUS: decision_needed` → halt only that cluster, parse the structured `decision_needed` payload, present to user via `AskUserQuestion` (using OPTIONS verbatim, RECOMMENDED_OPTION as the first option label), then re-spawn the cluster-planner with a resolution block injected into the prompt: `RESOLVED_DECISION: {decision_id, chosen_option, rationale}`. The re-spawn resumes from Phase 4 (skip Phase 0-3 — premise + exploration + decisions are settled). Sibling clusters continue (no global halt). Decision and resolution archived to `<root>/<cluster_slug>/archive/$RUN/decisions-late.md` AND echoed into MANIFEST under a `## Resolved decisions` section. MANIFEST tracks `attempts: <N>` and `final_status_at: <UTC ISO>` per cluster.
- `STATUS: spec_problem` → halt that cluster, surface to user; user may edit the scope and re-spawn, or drop the cluster.
- `STATUS: unable_to_complete` → mark cluster `failed` in MANIFEST. Other clusters continue.

If ALL clusters fail, halt with `total_cluster_failure` event. If ≥1 cluster succeeds, proceed to Phase 4 — partial trees are valid (user can run /z-implement-all on what completed, address failures separately).

### Phase 4 — Reconciliation (file-overlap detection)

**TASKS.md is canonical (Phase 7 review fix #1).** Main thread parses each cluster's TASKS.md `**Files:**` lines and builds the canonical files-per-cluster set. The `FILES_TOUCHED` field in cluster-planner's return is a JSON-array fast-path summary — main thread validates it equals the TASKS.md-parsed set; if they disagree, cluster is marked `failed` and a `cluster_files_inconsistent` event is logged.

For each path appearing in ≥2 clusters:
- Record cluster IDs, task IDs, task titles.
- Apply severity heuristic from SHARED-CONCERNS.md schema.

Write `SHARED-CONCERNS.md` with all overlaps + frontmatter `acknowledged: false`.

If `overlap_count: 0`, still write the file (audit-consistency) with `acknowledged: true` (auto-passes ack-gate).

### Phase 5 — Write MANIFEST.md + finalize

Write `MANIFEST.md` with cluster listing, run order (default = order of cluster confirmation), and pointer to SHARED-CONCERNS.md. Status: `ready` if all clusters succeeded, `partial` if some failed.

Log `plan_split_run_end` event with payload `{slug, total_clusters, clusters_ready, clusters_failed, overlap_count}`.

Push-notify with recommended next:
```
Split complete: <K>/<N> clusters ready. Overlap count: <M>.
Recommended next:
  1. Read SHARED-CONCERNS.md and flip `acknowledged: true` (or `--ack`)
  2. /z-implement-all   — walks the tree in MANIFEST run-order
```

## `cluster-planner` agent (new) — phase contract

The cluster-planner is a `model: sonnet` subagent that runs a stripped-down `/z-plan`-equivalent for one narrow scope. Phases (in order):

### Phase 0 — Premise check (lightweight) + anti-self-nesting guard

**Anti-self-nesting (Phase 7 review fix #11).** First action: check whether the output path is itself nested inside a parent MANIFEST. Walk the slug-dir ancestors looking for `MANIFEST.md`; if found, refuse to write and return `STATUS: anti_nesting_violation` with the ancestor path. Prevents accidental tree-of-trees if a user manually invokes `/z-plan-split` with a slug like `<existing-root>/<cluster>`.

After the guard passes: quick sanity check: does the cluster's stated scope actually solve a coherent piece of the parent topic? Does the proposed surface make sense?

If premise concerns surface, return `STATUS: decision_needed` with a `decision_needed` block whose QUESTION is "is this scope coherent?" and AFFECTED_FILES is empty. Otherwise write a 1-paragraph "premise accepted, here's what I take the goal to be" note.

### Phase 1 — Exploration

If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku). Otherwise read 3-5 source files directly via Read/Grep/Glob (no Explore subagent — too expensive for narrow scopes). Cap: ≤10 file reads.

### Phase 2 — Identify decisions (≤3 expected)

For each non-obvious decision: list options + tentative call. Apply the same "one reason this might be wrong" rule.

**Hard rule:** if 4+ non-obvious decisions surface, return `STATUS: decision_needed` with the message "scope too broad — recommend re-scoping this cluster." This is the leaf's self-detection that the split was too coarse.

### Phase 3 — Decision resolution (no per-leaf consult)

cluster-planner resolves decisions itself with tentative calls. Each resolved decision logs `<decision-id>, <option>, <one-line rationale>` into the cluster's `archive/$RUN/decisions.md`.

**Conservative-flagging rubric (Phase 7 review fix #2).** Escalate to main thread via `STATUS: decision_needed` iff the decision involves any of:

- (a) Public API / interface / trait change.
- (b) Adding a new external dependency.
- (c) Modifying a shared schema / config / migration / wire format file (matches the high-severity overlap glob: `*.sql`, `*.toml`, `*.yaml`, `*.yml`, `*.proto`, `Dockerfile`, `Makefile`).
- (d) Structural changes outside the cluster's declared file set (cluster scope leak).
- (e) Irreversible data migration or destructive operation.
- (f) Algorithm change with materially different performance or correctness characteristics.

Anything not on this list is resolved unilaterally with a one-line rationale. The rubric is exhaustive in spirit, not literal — if a decision shares the *kind* of risk with one of these triggers (e.g., affecting cross-cluster interop), escalate.

When escalating, the return payload is a structured `decision_needed` block:
```
STATUS: decision_needed
DECISION_ID: <stable id, e.g. "C1-D2">
QUESTION: <one-sentence question>
OPTIONS: [
  {label, description, recommended: true|false}
]
RECOMMENDED_OPTION: <option label or "none">
IMPACT: <one-line description of what changes based on resolution>
AFFECTED_FILES: [<path>, ...]
```

### Phase 4 — Write SPEC.md + PLAN.md

Standard /z-plan format but compressed: no consult section (defer to MANIFEST root if needed); no plan-review (deferred to /z-review-all later); no decisions-resolved-by-consult (decisions are flat).

### Phase 5 — Write TASKS.md

Standard /z-plan TASKS format. Each task has Files / Depends / Acceptance / Complexity (stamped by `complexity-classifier` subagent, same as /z-plan Phase 8).

### Phase 6 — Return

```
STATUS: ok
CLUSTER_ID: <id>
TASKS_COUNT: <N>
DECISIONS_RESOLVED: <K>
DECISIONS_ESCALATED: <M>   # always 0 on STATUS: ok (M>0 → STATUS: decision_needed)
FILES_TOUCHED: [list of paths from TASKS.md]   # used by reconciliation Phase 4
```

The `FILES_TOUCHED` field is the reconciliation hook — main thread extracts paths from this rather than re-parsing TASKS.md.

## `/z-implement-all` extension (T-stuff later)

`/z-implement-all` Setup step 2 (slug discovery) is extended:

1. For each `z-harness/<slug>/`:
   - If `<slug>/MANIFEST.md` exists: this is a tree-rooted plan.
     - Validate: every cluster Path in MANIFEST points to an existing directory containing a finalized `TASKS.md` (parsed without errors, has ≥1 task block). If the directory or TASKS.md is missing, halt with `cluster_not_ready` event payload `{cluster_id, path, reason: "missing_dir | missing_tasks_md"}`. If TASKS.md is malformed (YAML/parse error, no task blocks), halt with `cluster_not_ready` event payload `{cluster_id, reason: "malformed_tasks_md", error: <detail>}`. If any cluster has `status: failed`, halt with `cluster_not_ready` (covered by the partial-tree gate below unless `--force-partial`). `planning` is never persisted (see MANIFEST.md schema) so it is not a valid status here.
     - Validate: no nested MANIFEST.md exists anywhere reachable from cluster directories. Check: `find <root>/*/  -name MANIFEST.md -not -path <root>/MANIFEST.md` returns empty. If any are found → halt with `tree_depth_exceeded` event, payload `{nested_paths: [...]}`. (Phase 7 review fix #5: "nested" is defined as recursive glob `**/MANIFEST.md` reachable from any cluster directory in the root MANIFEST, not just direct children.)
     - Check ack-gate: `<slug>/SHARED-CONCERNS.md` must have `acknowledged: true` (or `overlap_count: 0`). If not, halt with `shared_concerns_unacknowledged` event and instruct user to read + flip the frontmatter (or pass `--ack` flag).
     - Check partial-tree gate (Phase 7 review fix #6): if SHARED-CONCERNS.md has `partial_tree: true`, halt with `partial_tree_blocked` event unless invoked with `--force-partial`. Error message names the failed clusters from MANIFEST.
     - If all validations pass, expand the slug into a sequence of cluster paths in MANIFEST run-order. Iterate clusters sequentially; within each cluster, use the existing N=3 parallel-batching as today.
   - Else: legacy single-slug plan, current behavior.

The `--ack` flag is a CLI override for the ack-gate: `/z-implement-all --ack` proceeds without requiring frontmatter edit. Equivalent to flipping the file then running.

Cross-cluster task parallelism is v2 (not in v1). Document as a known limitation.

## Naming + invocation

```
/z-plan-split <topic>                              # main form
/z-plan-split --clusters="a,b,c" <topic>           # user-specified clusters
/z-plan-split --slug=<root-slug> <topic>           # override auto-derived slug
```

Sub-flags for v2 (not v1): `--from-audit=<slug>`, `--from-brainstorm=<slug>`.

## Telemetry events

Standard fields on every event: `ts`, `run`, `kind`, `slug`. Subagent-bracket events also carry `prompt_chars`, `response_chars`, `wall_ms`.

Per-event required fields (Phase 7 review fix #8):

| Kind | Required payload fields |
|---|---|
| `plan_split_run_start` | `topic_chars`, `clusters_proposed` (after Phase 1) |
| `plan_split_run_end` | `total_clusters`, `clusters_ready`, `clusters_failed`, `overlap_count`, `partial_tree` |
| `cluster_proposed` | `cluster_id`, `cluster_name`, `scope` |
| `cluster_confirmed` | `cluster_id`, `confirmed_clusters_total` |
| `cluster_planner_start` | `cluster_id` |
| `cluster_planner_end` | `cluster_id`, `status`, `attempts`, `tasks_count`, `decisions_resolved`, `decisions_escalated`, `wall_ms` |
| `cluster_decision_escalated` | `cluster_id`, `decision_id`, `decision_summary` (= the `QUESTION` field of the `decision_needed` payload), `flagged_reason` (which rubric trigger fired: `a`–`f` or `scope_too_broad`) |
| `cluster_failed` | `cluster_id`, `failure_reason` |
| `total_cluster_failure` | `cluster_ids` (all that failed) |
| `cluster_files_inconsistent` | `cluster_id`, `files_touched_set`, `tasks_md_files_set`, `mismatch` |
| `overlap_detected` | `file_path`, `cluster_ids`, `severity` |
| `shared_concerns_acknowledged` | `total_overlaps`, `highest_severity`, `acknowledged_by`, `acknowledged_via` (`frontmatter` \| `cli_flag`) — emitted by `/z-implement-all` Setup 2b.7 the first time the ack-gate passes (either `acknowledged: true` in frontmatter or `--ack` flag). Observational event; gating is the halt event `shared_concerns_unacknowledged`. (v1 status: declared in this table — implementation pending; `/z-implement-all` already emits `shared_concerns_ack_override` on the CLI-override path, see `partial_tree_force_override` for the analogous shape.) |
| `cluster_not_ready` (halt from /z-implement-all) | `cluster_id`, `cluster_status` |
| `tree_depth_exceeded` (halt) | `nested_paths` |
| `shared_concerns_unacknowledged` (halt) | `acknowledged` (false) |
| `partial_tree_blocked` (halt) | `failed_cluster_ids` |
| `anti_nesting_violation` | `cluster_id`, `ancestor_manifest_path` |

## Hard rules

- Minimum 2 clusters, maximum 6 per `/z-plan-split` run.
- One-level recursion only; nested MANIFESTs are errors.
- No per-leaf cross-LLM consult in v1 (cost discipline).
- `cluster-planner` is conservative on decision-escalation — better to over-escalate.
- SHARED-CONCERNS.md ack-gate is mandatory unless `overlap_count: 0`.
- Cluster execution within `/z-implement-all` is sequential (intra-cluster parallelism honored).

## Known v1 limitations

- Cross-cluster task parallelism not supported. If cluster 1 has 1 task and cluster 2 has 20, cluster 2 is starved waiting for cluster 1. v2: MANIFEST gains `independent: true` flag on clusters that have no inter-cluster file overlap.
- File-overlap detection is path-only, not semantic. Two clusters adding independent helpers to `utils.ts` flags as overlap. User decides via ack-gate whether the overlap is real or noise.
- No `--from-audit` / `--from-brainstorm` input chains. User pastes topic as free text.
- No auto-detection of "should /z-plan-split run instead of /z-plan." User invokes explicitly per `feedback-explicit-commands` memory.
- `Agent()` has no per-call wall-clock timeout — a hung cluster-planner blocks the whole batch (user escape: ctrl-c).
- `shared_concerns_acknowledged` event is declared in the telemetry table but emission is deferred to a follow-up — `/z-implement-all` Setup 2b.7 currently emits only the negative (`shared_concerns_unacknowledged`) and CLI-override (`shared_concerns_ack_override`) events. The positive frontmatter-flip event will be added when needed for analytics; gating semantics are already correct.
- Monorepos with multiple `package.json` files will see each one flagged independently as `high` severity by the path-only overlap detector — the ack-gate is the intended resolution point.
- `doc-fetcher` failure handling in cluster-planner Phase 1: timeouts, malformed `INDEX.json`, or any non-`STATUS: ok` return are treated as `STATUS: no_match` and cluster-planner falls back to direct Read/Grep (no retry).
