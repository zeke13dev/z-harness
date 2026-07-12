# subagent-telemetry

> Last updated: 2026-07-11
> Covers source: scripts/detect-host.sh, scripts/log-event.sh, scripts/log-subagent.sh, scripts/estimate-tokens.py, scripts/test_subagent_logging.sh, skills/z-stats/SKILL.md

## Overview

`subagent-telemetry` records per-subagent dispatch cost signals without blocking the dispatch path. `scripts/detect-host.sh` identifies the host, `scripts/log-event.sh` stamps `host` on every event and writes events to the repo-wide metrics stream, `scripts/log-subagent.sh` emits non-fatal `subagent_call` events, and `scripts/estimate-tokens.py subagent-costs` reads those events to produce host/type cost breakdowns for `/z-stats`.

The telemetry intentionally stores raw `prompt_chars` and `response_chars` separately. Pricing knowledge lives only in the read-side estimator, which uses real provider token counts when present and a labeled chars/4 approximation for native Claude subagents. This avoids a misleading single `est_tokens` field, especially for output-heavy reviewers and consultants.

Do not conflate this retrospective surface with pre-run forecasts. `subagent-costs` prices observed `subagent_call` events after dispatch (exact when provider token fields exist, labeled `[char-est]` when it must use chars/4). `estimate-tokens.py` also exposes `estimate` and `forecast` subcommands (pre-run/E2E cost projection) that live in the same file but belong to the separate `cost-estimation` concept — `subagent-costs` is the only piece of `estimate-tokens.py` in scope here.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/detect-host.sh:21` — `detect_host()` — prints `antigravity`, `pi`, `codex`, `cursor`, or default `claude` from positive environment markers.
- `scripts/log-event.sh:42` — `resolve-run-dir` read-only resolver subcommand.
- `scripts/log-event.sh:133` — lazy host resolution: `Z_HARNESS_HOST` override or `/tmp/zh-host-$PPID` cache from `detect-host.sh`.
- `scripts/log-subagent.sh:1` — non-fatal helper for emitting `subagent_call` events with role/type/model and prompt/response sizes.
- `scripts/log-subagent.sh:107` — payload builder; optional provider token fields are included only when non-empty.
- `scripts/log-subagent.sh:154` — delegates the actual event write to `log-event.sh`.
- `scripts/estimate-tokens.py:373` — `_compute_event_cost()` — computes input/output tokens and cost for one `subagent_call` event.
- `scripts/estimate-tokens.py:441` — `subagent_costs()` — groups cost by host and subagent type from repo-wide metrics.
- `scripts/estimate-tokens.py:1493` — `_format_subagent_costs_table()` — human-readable `/z-stats` table formatter.
- `scripts/test_subagent_logging.sh:1` — drift-guard for role-bearing dispatch logging.
- `skills/z-stats/SKILL.md:77` — Phase 6 ("Per-host, per-subagent cost breakdown") — user surface for `subagent-costs`.
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `reviewer-capture` — reviewer and consultant agents self-log after capturing final responses.
- `z-execute` — orchestrator-side implementer dispatch logging is a pinned drift-guard site.
- `cost-estimation` — `estimate-tokens.py` owns both pre-run estimates/plan+execute forecasts and observed post-run subagent-cost read-side pricing; the surfaces share rates but not semantics.
- `plan-path` / external base — `subagent_call` events land in the repo-wide metrics file at the resolved base, not per-plan metrics.
- `z-stats` — displays per-host/per-type cost and labels `[char-est]`, `[real tokens]`, or `[mixed: provider+chars]`. `skills/z-stats/SKILL.md` was rewritten (266→156 lines) to absorb the former `/z-where` command as its unconditional Phase 1 header and to delegate every other computed section (progress, wall time, tokens, coordination tallies, halts, next-command) to the new `scripts/stats.py` subcommands instead of inline jq/awk. **Phase 6 (subagent-costs) is the only section this concept still owns** — the rewrite left it untouched, still shelling out directly to `scripts/estimate-tokens.py subagent-costs`. `scripts/stats.py` itself is out of scope for this concept (it is not one of the tracked source files); see its own concept doc for the absorbed `/z-where` and progress/walltime/tokens machinery.
- `scripts/report-context.py` — a second, undocumented-as-concept consumer that shells out to `estimate-tokens.py subagent-costs --json` to fold cost data into its own report; see NOTES.

## detect-host.sh

Detection order is first positive marker wins:

| Host | Trigger |
|---|---|
| `antigravity` | `ANTIGRAVITY_PLUGIN_ROOT` is set |
| `pi` | any non-empty `PI_*` env var |
| `codex` | `CODEX_API_KEY` or `CODEX_EXEC` is set |
| `cursor` | `CURSOR_API_KEY` is set |
| `claude` | default |

The script never prints `unknown` or an empty string and has no side effects.

## log-subagent event shape

```json
{
  "kind": "subagent_call",
  "host": "claude",
  "role": "reviewer",
  "subagent_type": "reviewer",
  "subagent_model": "haiku",
  "prompt_chars": 4821,
  "response_chars": 3102,
  "provider_input_tokens": 1210,
  "provider_output_tokens": 755
}
```

Provider token fields are optional and appear only for external CLIs that expose usage lines. Native Claude subagents use exact character counts and are labeled as estimates in read-side output.

## Edge cases / gotchas

- `log-subagent.sh` always exits 0, including missing argument and payload-build failures; telemetry must not block work.
- Callers do not stamp host themselves; `log-event.sh` overwrites/sets it authoritatively.
- The host sentinel is keyed on `$PPID`; each `bash log-event.sh` process has a different `$$`.
- The drift guard pins four canonical logging files: `skills/z-execute/SKILL.md`, `agents/reviewer.md`, `agents/consultant-primary.md`, and `agents/consultant-secondary.md`.
- Broad drift detection scans `skills/` and `agents/` for new `subagent_type="implementer"` sites lacking either `log-subagent.sh` or `# no-subagent-log: <reason>`.
- Consultant dispatches from orchestrators must not double-log; consultant agents self-log.
- `/z-stats` resolves the base dir explicitly for subagent costs because repo-wide metrics may live outside the plan dir.
- `/z-plan` pre-run cost forecasts are not reconciled inline with `subagent-costs`; compare them after the run via `/z-stats` if calibration is needed.
- `skills/z-stats/SKILL.md` phase numbering shifted in the 2026-07 rewrite: subagent-costs moved from the old "Phase 3b" label to "Phase 6" because Phase 1 now absorbs the former `/z-where` header and Phase 2 handles slug discovery before the preflight `Setup` step. Re-verify the phase number on every future refresh — it is not pinned to this concept and can renumber independently as `scripts/stats.py` gains or loses subcommands.
- Line-number anchors for `log-subagent.sh` and `estimate-tokens.py` drift with file growth; this refresh re-verified every anchor (`estimate-tokens.py` anchors shifted by -3 lines since the previous doc revision) and the `skills/z-stats/SKILL.md` anchor against the current 156-line rewrite.
- No persona-related event kinds (`persona_attempt_outcome`, `persona_bound`, `persona_random_selected`) belong to this concept — those are emitted by the (now-excised) persona-rotation subsystem and documented, where still relevant, under `scripts.json`/`watchdog.json`, not here.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/subagent-telemetry.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```bash
bash scripts/log-subagent.sh --run tasks/T001 --role reviewer --subagent-type reviewer --subagent-model haiku --prompt-chars 4821 --response-chars 3102
python3 scripts/estimate-tokens.py subagent-costs --metrics /path/to/metrics.jsonl
/z-stats --slug my-plan
```
