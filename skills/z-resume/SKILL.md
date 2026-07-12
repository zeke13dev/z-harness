---
name: z-resume
disable-model-invocation: false
description: "Read-only work-thread recovery from a fuzzy or exact prior-work target. Finds and selects the likely plan/run/worktree/branch/artifact/repo context from bounded cited evidence, reports ambiguity explicitly, and recommends safe next commands without executing them. Optional --report reuses /z-report only after target selection."
argument-hint: "[topic|current|active|latest|--slug <slug>|--plan <slug>|--run <run-id>|--branch <name>|--worktree <path>|--artifact <path|kind>|--repo <repo-id|path> --topic <text>|--select <token>] [--lookback <duration|N>] [--all-repos] [--json|--noninteractive] [--report [summary|standard|deep] [z-report profile flags...]]"
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-resume`** — a first-class, read-only recovery surface for answering: "what was I doing, what state is it actually in, and how can I continue safely?"

`/z-resume` finds and selects a recovery target. It does **not** execute, restart, mutate, or auto-dispatch implementation, planning, attend, overnight, or report commands. It may recommend copyable next commands/prompts, and with `--report` it may invoke the existing `/z-report` machinery only after an unambiguous or explicit target selection exists.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Setup

Resolve only the plugin root needed to call deterministic helper scripts. Do not create archives, scratch dirs, telemetry files, or target artifacts during recovery.

```bash
PLUGIN_ROOT="${Z_HARNESS_PLUGIN_ROOT:-${OMP_PLUGIN_ROOT:-${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$PWD}}}}"
TARGET_REPO_ROOT="$(pwd -P)"
if [[ ! -f "$PLUGIN_ROOT/scripts/resume-context.py" ]]; then
  for candidate in "$PWD" "$PWD/.omp/z-harness" "$PWD/.." "$PWD/../.."; do
    if [[ -f "$candidate/scripts/resume-context.py" ]]; then
      PLUGIN_ROOT="$(cd "$candidate" && pwd)"
      break
    fi
  done
fi
```

If a hosting runtime already provides ordinary command logging, it may log invocation metadata outside this skill. `/z-resume` itself keeps deterministic context in memory/stdout unless a later selected `--report` phase delegates to `/z-report`.

## Hard boundaries

- **READ ONLY.** Do not edit target repos, plan artifacts, registries, state files, logs, branches, or worktrees. Do not write telemetry beyond ordinary command logging if the hosting runtime already performs it.
- **No execution handoff.** Never run `/z-execute`, `/z-implement-*`, `/z-plan*`, `/z-fix`, `/z-debug`, `/z-attend`, `/z-overnight`, `qtctl`, restart commands, test suites, backfills, migrations, or shell commands that mutate a worktree/service/database.
- **Selection before story.** Resolve ambiguity before narrative/report rendering. Interactive ambiguity asks one bounded selection question. Noninteractive ambiguity returns `needs_selection` with `selected_target: null` and stops.
- **Deterministic core.** `scripts/resume-context.py` is a pure gather/score/packet producer: no prompting, no LLM/subagent calls, no report rendering, no hidden filesystem expansion, no command dispatch, and no mutation.
- **Report reuse only.** `--report` reuses existing `/z-report` target/context/rendering seams after selection. Do not duplicate `report-synth`, do not invent a second report renderer, and do not call report machinery for ambiguous targets.
- **Evidence hierarchy.** Memories, follow-ups, cheap inference, and user-provided fuzzy text are side evidence only. They never prove current state, landed state, completion, or branch/worktree ownership.

## Accepted arguments and exact target shortcuts

Parse explicit controls before fuzzy text. If more than one exact target shortcut is supplied, stop with invalid usage unless one is an exact repo qualifier and the other is the target within that repo.

Exact target shortcuts:

| Form | Meaning | Notes |
|---|---|---|
| `--run <run-id>` or `run:<run-id>` | Exact z-harness run/archive target | ISO timestamp prefix is acceptable only when it uniquely resolves within bounded sources. |
| `--slug <slug>`, `--plan <slug>`, `slug:<slug>`, `plan:<slug>` | Exact plan slug target | Prefer current repo's plan base unless `--repo` selects another repo. |
| `--branch <name>` or `branch:<name>` | Exact branch-name candidate | Must be associated to a plan/run through cited registry, worktree, git-log, or artifact evidence; substring match alone is not proof. |
| `--worktree <path>` or `worktree:<path>` | Exact worktree path target | Path must be under a known or explicit repo/worktree root; do not expand arbitrary parent directories. |
| `--artifact <path|kind>` or `artifact:<path|kind>` | Exact artifact source | Selects or anchors candidates using a cited plan/run artifact such as `TASKS.md`, `REPORT.md`, `context.json`, or `run-brief.json`; artifact evidence still resolves to a work-thread target before rendering. |
| `--repo <repo-id|path>` or `repo:<repo-id|path>` | Exact repo qualifier | Restricts discovery to that repo's configured state base/worktree roots. Does not by itself select a work item unless only one candidate remains. |
| `--select <token>` or `select:<token>` | Explicit selection from a prior ambiguity packet | Token must match a candidate token emitted by `resume-context`; then rerun gather for that selected target. |
| `--topic <text>` | Fuzzy topic text | Equivalent to remaining positional text after control flags are removed. |
| `current` or `active` | Current active work in the selected/current repo | Exact only when registry/session evidence yields one candidate; otherwise ambiguity gate fires. |
| `latest` or `last` | Most recent bounded work thread in the selected/current repo | Uses deterministic recency only as a tiebreaker; ambiguity gate fires for close or conflicting candidates. |

Other controls:

- `--lookback <duration|N>`: cap recency window or candidate count. Defaults are bounded by `resume-context` policy; older canonical linked decisions may still be included as linked evidence without widening candidate discovery.
- `--all-repos`: opt in to broader configured-repo discovery. Still capped, cited, and limited to configured z-harness bases, active registry repo IDs, known Hermes/worktree roots, or explicit repo roots.
- Default interactive output is the concise human renderer. `--json`, `--format json`, or `--noninteractive` emits the machine-readable packet and never asks. Ambiguous noninteractive output is `needs_selection` with `selected_target: null`.
- `--report`: after selection, render a z-report-style narrative using `/z-report` machinery. Report-tier/profile flags following `--report` or recognized by `/z-report` (`summary|standard|deep`, `--profile`, `--audience`, `--style`, `--purpose`, `--share`, `--surface`) are forwarded only after target selection.

Empty arguments are allowed. They mean: recover the most plausible current/recent work thread for the current repo, subject to the same bounded evidence and ambiguity gates.

## Phase 0 — Parse args and classify request

1. Tokenize `$ARGUMENTS` preserving quoted topic text.
2. Extract exact target shortcuts (including artifact, current/active, latest/last), repo qualifier, lookback controls, selection token, noninteractive/json mode, and `--report` controls.
3. Treat all remaining text as fuzzy topic text. Normalize only for matching (case-fold, punctuation/stopword compaction); retain raw text in the packet.
4. Reject invalid combinations:
   - multiple exact target shortcuts without a repo qualifier;
   - `--select` plus a contradictory exact target;
   - `--report` with no route to either an explicit target or a possible unambiguous selection;
   - unknown `--lookback` or repo-scan controls.
5. Record `raw_arguments`, `parsed_arguments`, `query`, `requested_report`, and `interaction_mode` for `resume-context`.

## Phase 1 — Bounded repo and lookback resolution

Call the deterministic gatherer with only explicit, bounded inputs:

```bash
RESUME_CONTEXT_JSON="$(python3 "$PLUGIN_ROOT/scripts/resume-context.py" \
  --repo-root "$TARGET_REPO_ROOT" \
  --arguments "$ARGUMENTS" \
  --format json)"
RESUME_CONTEXT_EXIT=$?
```

`resume-context.py` owns repo/lookback resolution and must make it observable in the packet:

- **Default source order:** current repo identity from `plan-path.sh`; current repo's z-harness state base; active-plan registry records for the current repo; current repo worktrees/branches; current repo git log within the bounded lookback.
- **Explicit non-current sources:** `--repo` may select a configured repo id, configured state base, or explicit repo/worktree path. `--all-repos` may include configured z-harness bases, active registry repo IDs, and known Hermes/worktree roots only. Every non-current-repo candidate must carry source/repo citations.
- **Caps:** impose hard maximums for repos, plan dirs, runs, worktrees, git commits, artifact bytes, and candidate count. Truncation is a warning/source-status, never silent.
- **No hidden expansion:** do not walk `$HOME`, `/tmp`, arbitrary parent directories, or network mounts because a fuzzy topic looked promising. Broader discovery requires an explicit flag and still uses configured roots/caps.
- **Lookback:** recency filters discovery, not truth. Linked canonical decisions, selected-run artifacts, and directly referenced handoff/session evidence may be attached as older evidence with stale/linked flags.

If `resume-context.py` fails usage validation, print the usage error and stop. Provider failures inside the packet are non-fatal and rendered as degraded source status.

### `resume-context` packet contract

Every consumer must treat `resume-context.json` as the durable selection contract. Required top-level fields:

- `schema_version`, `query`, `raw_arguments`, `parsed_arguments`, `interaction_mode`, and `requested_report`;
- `repo_identity` with current repo id/path plus any explicit or discovered non-current repo sources;
- `lookback` with default caps, explicit overrides, source order, and truncation status;
- `source_status` keyed by provider, including `ok`, `missing`, `unavailable`, `partial`, `malformed`, `stale`, `superseded`, `degraded`, or `truncated`;
- `evidence_records` with typed citations and validation/freshness status;
- `candidates`, `score_components`, `negative_evidence`, `current_state`, `state_flags`, and `state_reasons`;
- `ambiguity` with state, trigger reasons, close candidates, and noninteractive `needs_selection` data when applicable;
- `selected_target`, which is either an exact selected object with `target_type`, `selection_token`, repo/worktree/branch/run/slug fields as available, and citations, or `null`;
- `subagent_judgments` as optional side-channel summaries that cannot alter deterministic evidence/state;
- `warnings`, `citation_metadata`, `suggested_continuations`, and noninteractive `suggested_selection_args` generated by the deterministic recommendation matrix.

CLI, MCP, and exported/noninteractive surfaces consume this packet directly. They must not infer a hidden target from prose, report text, or filesystem scans when `selected_target` is `null`.

## Phase 2 — Deterministic evidence gathering

The gatherer must reuse existing primitives rather than duplicating path semantics:

- `scripts/plan-path.sh` for base dir, repo id, and plan path resolution.
- `scripts/active-plan-registry.py list --json` for live run/session/phase/worktree/branch evidence.
- Deterministic in-process parsing for exact run/slug/branch/worktree/artifact targets; `scripts/report-context.py` remains reserved for the post-selection `--report` phase.
- `scripts/artifact-scout-inventory.py` inventory/scoring patterns for bounded plan/run artifact summaries.
- Existing session/handoff helpers and schemas for `SESSION.md`, `SESSION_CONTEXT.md`, `handoff.json`, and `HANDOFF.md` validation.

Evidence providers must emit typed records with: `type`, `source_path` or source descriptor, `repo_id`, `collected_at`, `citation`, `status`, `validation_status`, `freshness`, `candidate_refs`, and a short excerpt/summary when allowed by caps.

Provider families:

- plan/run artifacts: `INTENT.md`, `SPEC.md`, `PLAN.md`, `TASKS.md`, `FIX.md`, `LEDGER.md`, archive artifacts, `REPORT.md`, `context.json`, `run-brief.json`, events metadata, decisions, and follow-ups;
- active registry records: command, phase, current task, status, heartbeat age, held paths, waiting edges, branch, worktree, repo id;
- git/worktree/branch evidence: worktree paths, branch names, HEAD refs, commit subjects, relevant recent git log associations;
- session/handoff evidence: validated `SESSION.md`, stale/degraded `SESSION_CONTEXT.md`, validated `handoff.json` protocol fields, `HANDOFF.md`;
- memory/follow-up evidence: attached only as side evidence, never as proof of state or landing.

Session/handoff validation requirements:

- `SESSION.md` can describe current state only when its schema/frontmatter, done-set hash, and next-pending task agree with current `TASKS.md`; otherwise degrade to stale side evidence.
- `SESSION_CONTEXT.md` is live side evidence only when freshly linked by a valid session/handoff artifact; otherwise stale side evidence.
- `handoff.json` must validate protocol version, timestamp, status, `next_step`, and context-file references before influencing state; malformed or conflicting handoffs degrade.
- Conflicts among `TASKS.md`, session, handoff, registry, branch/worktree, and git evidence become warnings or ambiguity, not silent choices.

## Phase 3 — Deterministic candidate clustering, state, and scoring

`resume-context.py` clusters evidence into candidate work threads before any cheap inference. It must output deterministic components, not opaque rankings.

Candidate fields include: `candidate_id`, `selection_token`, `target_type`, `repo_id`, `slug`, `run_id`, `branch`, `worktree_path`, `title`, `matched_query_terms`, `evidence_refs`, `score_components`, `negative_evidence`, `confidence`, `current_state`, `state_flags`, `warnings`, `source_status`, and `citations`.

Scoring policy:

- Positive components may include exact target match, current repo match, active registry match, validated session/handoff match, plan/run artifact match, branch/worktree/git association, recency, query term density, linked canonical decision, and report/context availability.
- Negative components must include stale session, superseded run, dirty/divergent worktree conflict, completed/landed mismatch, cross-repo mismatch, provider truncation, malformed evidence, thin evidence, and close-score competitor pressure.
- Recency decay may lower discovery rank but must not hide older canonical linked decisions attached to an otherwise selected candidate.
- Branch/worktree matching is associative evidence only. A branch substring or worktree basename matching a slug is insufficient without repo id, registry, HEAD/commit, artifact, or user explicitness support.

Current-state taxonomy:

- `primary_state`: one of `active`, `paused`, `blocked`, `completed`, `landed`, `archived_only`, `stale`, `superseded`, `dirty`, `divergent`, or `unknown`.
- `state_flags`: zero or more of `active_registry`, `completed_tasks`, `landed_git`, `stale_session`, `stale_handoff`, `dirty_worktree`, `divergent_branch`, `superseded_by_newer_run`, `cross_repo`, `archived_only`, `thin_evidence`, `conflicting_evidence`, `degraded_sources`.
- State precedence must be explainable in `state_reasons`; conflicts produce warnings and may trigger ambiguity.

## Phase 4 — Optional bounded cheap inference

Cheap inference is optional and bounded. It happens only after deterministic evidence is gathered and only if the driver supports subagents/model invocation. The deterministic `resume-context.py` packet owns prompt construction in `subagent_requests`; the command may dispatch only those prepared requests to the `resume-cluster` agent.

Allowed use:

- Dispatch **zero** calls when subagents are unavailable, disabled, or the packet has no `subagent_requests`.
- Dispatch at most one cheap call for a single top/selected candidate summary, or at most two bounded cheap calls when the packet explicitly provides a compact ambiguous top-cluster comparison. Default dispatch must never exceed `subagent_request_policy.max_default_calls`.
- Prompt input is only the compact `resume-context` supplied candidate/evidence packet with citations. Do not add repo paths, file excerpts, command output, prior chat, or other facts that are not already present in that request payload.
- `resume-context.py` must hard-cap the complete prepared prompt, including instruction prefix, at `MAX_SUBAGENT_PROMPT_CHARS`. If budget reduction drops candidates or evidence, the request payload, `request_kind`, candidate ids, and citation ids must be degraded together so metadata still describes exactly what the subagent receives.
- The subagent is `resume-cluster` and is tool-less/read-only. It may summarize/rank supplied evidence but must not inspect the repo, run commands, read files, browse, message peers, or discover new facts.
- Required return fields: likely work thread, current/landed state exactly as `<unknown>` or supplied deterministic `primary_state` label(s), latest consensus or `<unknown>`, unresolved questions, confidence and reasons, suggested next command/prompt, and citations from supplied evidence only. Non-empty unresolved questions and confidence reasons count as factual claims requiring citations unless they are explicitly procedural next-step text.

Inference output is stored only under `subagent_judgments`. It may improve wording and expose uncertainty, but it never changes deterministic `source_status`, `primary_state`, `selected_target`, evidence records, or citations. Missing, malformed, uncited, unavailable, or contradictory inference degrades to deterministic summaries.

Dispatch procedure:

1. Read `subagent_request_policy`; if absent, malformed, or `max_default_calls` is greater than 2, skip cheap inference and use deterministic output.
2. Take only `subagent_requests[:max_default_calls]`. Each request already contains the full prompt; do not enrich it.
3. Invoke `resume-cluster` once per selected request with that prompt. If any call fails, times out, returns non-JSON, omits required fields, cites ids outside `request.citation_ids`, or contradicts deterministic state labels, record a degraded fallback judgment instead.
4. Validation must degrade any factual non-`<unknown>` inference that has no supplied citation, cites ids outside the request, reports arbitrary `current_or_landed_state` prose, or reports state labels that are not a subset of the deterministic states in the request.
5. Append accepted or degraded objects to `subagent_judgments` only. Do not write them into `evidence_records`, `source_status`, `selected_target`, `current_state`, `ranking`, or `safe_next_command`.

## Phase 5 — Ambiguity gate

Run the ambiguity gate before concise rendering and before any `--report` handoff.

Ambiguity triggers include:

- no candidate above minimum confidence;
- top candidates within the configured close-score band;
- low confidence, thin evidence, or provider truncation on the top candidate;
- conflicting state evidence for the top candidate;
- cross-repo candidates that plausibly answer the same query;
- exact target prefix resolving to multiple runs/slugs/branches/worktrees;
- `--repo` qualifier leaving multiple plausible targets;
- requested `--report` without an unambiguous or explicit selected target.

Interactive ambiguity behavior:

1. Stop before narrative/report rendering.
2. Ask exactly one bounded disambiguation question.
3. Show top candidates only, each with selection token, title/slug/run, date, repo/worktree/branch hints, confidence reasons, negative evidence, current-state warning, and citations.
4. Offer copyable replies: `--select <token>`, exact target flag, or narrowed topic/repo.
5. After the user chooses, rerun `resume-context.py` with the explicit selection and render from the new selected packet.

Noninteractive ambiguity behavior:

Return structured output and stop:

```json
{
  "status": "needs_selection",
  "selected_target": null,
  "ambiguity": {"state": "ambiguous", "reasons": ["..."]},
  "candidates": [{"selection_token": "...", "title": "...", "citations": ["..."]}],
  "suggested_selection_args": ["--select ...", "--slug ...", "--run ..."],
  "warnings": ["..."]
}
```

Do not invoke `report-context.py`, `report-synth`, `/z-report`, or any report renderer for `needs_selection`.

## Phase 6 — Concise recovery render

For a selected or unambiguous packet, render a compact recovery/status packet. Every factual status and next-step claim must cite packet evidence.

Default human output shape:

```markdown
Resume target: <title>  [<selection token>]
Repo: <repo_id>  Worktree: <path or unknown>  Branch: <branch or unknown>
State: <primary_state> (<flags>) — <cited reason>
Confidence: <high|medium|low> — <top score reasons>; caveats: <negative evidence>

Latest consensus
- <decision/session/handoff/report summary with citations, or unknown>

What changed / where it stands
- <current or landed state, task status, branch/worktree status, stale/degraded evidence>

Open ambiguity or degraded evidence
- <warnings, stale/superseded side evidence, missing providers, truncation>

Safe next options (advisory only)
1. <copyable command/prompt> — why this is safe [citation]
2. <copyable command/prompt> — why this is safe [citation]
```

Recommendation matrix is deterministic and advisory. It is keyed by selected target type, confidence, ambiguity, task completion, registry state, branch/worktree state, report availability, and known command forms. It may recommend commands such as `/z-stats`, `/z-execute`, `/z-review-all`, `/z-report`, `/z-explain`, or a `cd <worktree>` prompt, but it must not execute them.

If no useful candidate exists, render `status: not_found` with searched sources, caps, degraded providers, and exact examples the user can supply next.

## Phase 7 — Optional `--report` after selection

Only enter this phase when all are true:

- `--report` was requested;
- `resume-context` returned `status: selected` or equivalent unambiguous selected packet;
- `selected_target` is non-null and has an exact reportable target (`run`, `slug`, `worktree`, `range/base`, or an extension explicitly accepted by `report-context.py`);
- ambiguity state is not `ambiguous` / `needs_selection`.

Then reuse `/z-report` machinery:

1. Read `report_target` from the `resume-context` packet. It must be `status: ready` with `target_args` that name the selected target exactly; otherwise stop. `status: needs_selection` asks the bounded selection question in interactive mode or returns the JSON packet unchanged in noninteractive mode. `status: not_reportable` prints the packet's reason and stops.
2. Persist the already-selected packet only as the selected-context input for report assembly and export its path as `SELECTED_RESUME_CONTEXT_PATH`, then translate `report_target.target_args` into existing `/z-report` target args (`--run`, `--slug`, `current`/`changes`, `--base`, `--range`, or the `--worktree <path>` extension accepted by `report-context.py`). Worktree-backed selections must use `--worktree <path>` instead of a same-slug current-repo route; non-current-repo selections must not fall back to current-base `--run` or `--slug` unless the selected repo is the current repo.
3. Pass through report tier/profile/surface controls exactly as `/z-report` defines them.
4. Assemble report context via `scripts/report-context.py`, adding `--resume-context "$SELECTED_RESUME_CONTEXT_PATH"` so `context.json` contains the bounded `selected_resume_context` projection. This is the only selected-context extension point; it carries the validated selected target and explicitly selected evidence records, not prose or unrelated records sharing provider citation ids.
5. Render through the normal `/z-report` fast path, `report-synth`, or inline fallback. Do not duplicate report rendering inside `/z-resume`.

Ambiguous `--report` in interactive mode asks the selection question first. Ambiguous `--report` in noninteractive mode returns `needs_selection` with `selected_target: null` and stops before any `report-context.py`, `report-synth`, or inline report-rendering branch runs.

## Phase 8 — Advisory final follow-ups

End with advisory follow-ups only. They may include:

- exact selection command to rerun if confidence was low;
- safe continuation command/prompt copied from the deterministic matrix;
- warning to change directory when the selected target belongs to another repo/worktree;
- suggestion to run `/z-report` or `/z-resume --report` after selection for a narrative;
- stale/degraded evidence notes and which exact artifact/provider to inspect manually.

Never claim that a recommendation has been executed. Never mark a plan complete, restart a service, mutate registry state, or auto-open another command.

## Examples

- Fuzzy topic recovery in the current repo: `/z-resume "resume-context ranking"`.
- Current or latest bounded work thread: `/z-resume current` or `/z-resume latest --lookback 14d`.
- Exact target recovery: `/z-resume --slug z-resume`, `/z-resume --run 20260601T120000Z-implement`, or `/z-resume --artifact path/to/context.json`.
- Branch/worktree recovery: `/z-resume --branch feature/resume-context` or `/z-resume --worktree ../z-harness-resume`. Branch/worktree hints must still resolve to a cited work thread.
- Cross-repo recovery: `/z-resume --repo qt-bot --topic "missing fills report"`; selected output must cite the non-current repo/worktree and warn before recommending a directory change.
- Noninteractive ambiguity: `/z-resume "resume docs" --json` returns `needs_selection` and copyable `--select`/exact-target args instead of asking.
- Report after target selection: `/z-resume --slug z-resume --report standard --profile=technical-handoff`.

## Side-evidence rule

Memories and follow-ups can explain why a candidate is relevant, preserve reviewer/context reminders, or suggest unresolved work. They are never proof of current state, landed state, completion, active ownership, or branch/worktree association. When they conflict with registry, artifact, git, session, or handoff evidence, keep them as cited caveats and let the stronger bounded evidence drive selection or ambiguity.

## Entry points

- `scripts/resume-context.py` — deterministic gather/score/packet producer and selection contract.
- `scripts/active-plan-registry.py` — live active-plan evidence used as one provider, not the whole search space.
- `scripts/report-context.py` — report context assembler reused only after selected `--report` targets.
- `skills/z-report/SKILL.md` — narrative rendering contract for known/selected targets.
- `skills/z-explain/SKILL.md` and `skills/z-learn/SKILL.md` — code/system teaching surfaces to recommend only after work-thread selection.

## Adjacent command boundaries

| Command | Use it for | `/z-resume` boundary |
|---|---|---|
| `/z-stats` | Current active-plan registry status, wait edges, and path overlaps | `/z-resume` uses registry evidence but also searches bounded historical artifacts, sessions, handoffs, branches, reports, and repo context to select a recovery target. Use `/z-stats` when active plans are the entire question. |
| `/z-report` | Narrative for a known run/slug/PR/range/base/worktree | `/z-resume` finds/selects the target first; `--report` delegates to `/z-report` only after selection and never for `needs_selection`. |
| `/z-explore` | Code terrain mapping, entry points, seams, or investigative source context | `/z-resume` reconstructs a work thread, not code architecture; recommend `/z-explore` only after selected evidence says code terrain is the gap. |
| `/z-explain` | One-shot cited explanation of code/repo/topic | `/z-resume` may recommend it for understanding a selected surface, but work-thread continuation/reorientation routes to `/z-resume`, not `/z-explain`. |
| `/z-learn` | Interactive progressive tutoring | `/z-resume` may recommend it after selection for learning; `.learn-pending.md` is a teaching-session state, not proof of plan/run/worktree state. |
| `/z-attend resume` | Continue a known attended run context with validated handoff predicate | `/z-resume` can identify that a known attend run is likely relevant, but it does not run attended chains. |
| `/z-overnight resume` | Continue a known overnight run id/state | `/z-resume` can find the likely run id and cite state, but it does not resume unattended orchestration. |

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | optional | Cheap inference only; skip and render deterministic packet when unavailable. |
| `ask_user` | optional | Interactive ambiguity selection; non-supporting/noninteractive drivers return `needs_selection`. |
| `skill_invoke` | optional | `--report` may invoke/reuse `/z-report` only after target selection; otherwise translate to existing report-context/report-synth machinery. |

This command is read-only in every supported driver. Unsupported optional features must degrade visibly; they must not be replaced by hidden mutation, unbounded scans, uncited inference, or report rendering before selection.
