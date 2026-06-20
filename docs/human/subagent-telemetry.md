# subagent-telemetry

> Last updated: 2026-06-19
> Covers source: scripts/detect-host.sh, scripts/log-event.sh, scripts/log-subagent.sh, scripts/estimate-tokens.py, scripts/test_subagent_logging.sh, commands/z-stats.md

## Overview

`subagent-telemetry` is the per-subagent cost telemetry system introduced in the `reviewer-cost-telemetry` plan (Change 2). Before this change, only a fraction of subagent dispatches were logged with token-bearing events; host detection ran only in the Python subprocess-runtime path, never in native Claude orchestration; and the largest Claude cost bucket (implementer dispatches in `/z-implement-all`) was completely invisible. This concept covers three interlocking pieces: `scripts/detect-host.sh` for host identification, `host` stamping on every event via `scripts/log-event.sh`, and `scripts/log-subagent.sh` for per-subagent `subagent_call` events.

The read-side of this system lives in `scripts/estimate-tokens.py subagent-costs`, which reads `subagent_call` events from `metrics.jsonl` and computes a per-host, per-subagent-type cost breakdown using separated input/output rate weighting. The `/z-stats` command surfaces this output to users. A drift-guard CI script (`scripts/test_subagent_logging.sh`) enforces that new `implementer` dispatch sites are always logged or explicitly opted out.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/detect-host.sh:21` — `detect_host()` — prints one of `claude|pi|codex|cursor|antigravity`; defaults to `claude`; positive-marker overrides only; never empty or `unknown`
- `scripts/log-event.sh:133` — host lazy resolution — reads `Z_HARNESS_HOST` env var if set; else calls `detect-host.sh` once and caches to `/tmp/zh-host-$PPID`; also supports `resolve-run-dir <run-id>` read-only subcommand
- `scripts/log-subagent.sh:1` — `log-subagent.sh` — emits `subagent_call` event; non-fatal (always exits 0); delegates host stamping to `log-event.sh`
- `scripts/estimate-tokens.py:408` — `subagent_costs()` — per-host, per-subagent_type cost breakdown from `subagent_call` events in `metrics.jsonl`; weights `prompt_chars` vs `response_chars` by per-model input/output rates
- `scripts/test_subagent_logging.sh:1` — drift-guard CI — scans commands/ and agents/ for `subagent_type="implementer"` dispatch sites; fails if any site lacks a paired `log-subagent.sh` call or an explicit `# no-subagent-log: <reason>` opt-out
- `commands/z-stats.md` — `subagent-costs` surface — renders `subagent_costs()` output as a per-host, per-type cost table with `char-est` vs `real-tokens` labeling
<!-- AUTO-END: entry-points -->

## detect-host.sh

`scripts/detect-host.sh` detects the current z-harness host environment. It prints exactly one of `claude`, `pi`, `codex`, `cursor`, or `antigravity`.

Detection rules (first match wins):

| Host | Trigger |
|------|---------|
| `antigravity` | `ANTIGRAVITY_PLUGIN_ROOT` is set and non-empty |
| `pi` | any `PI_*` environment variable is set and non-empty |
| `codex` | `CODEX_API_KEY` or `CODEX_EXEC` is set and non-empty |
| `cursor` | `CURSOR_API_KEY` is set and non-empty |
| `claude` | (default — always reachable) |

Key invariants:
- Never prints `unknown` or an empty string. `unknown` would pollute host-filtered metrics.
- Positive-marker-only: an override requires a present env var; absence of all markers yields `claude`.
- Idempotent; no side effects.

The script can be sourced (exposes `detect_host()` function) or executed directly.

## host field on every event

`scripts/log-event.sh` stamps `host` onto every event envelope. Host resolution is **lazy**:

1. If `Z_HARNESS_HOST` is set in the environment, use that value directly (allows CI/test override).
2. Else call `detect-host.sh` once and cache the result to `/tmp/zh-host-$PPID` (keyed on the parent shell PID so the cache persists across all `log-event.sh` invocations in one orchestrating process).

`log-event.sh` also supports a `resolve-run-dir <run-id>` read-only subcommand that prints the run's archive directory (using the same slug-aware, 5-tier logic the write path uses) without creating or writing anything. This lets other tools locate a run's `events.jsonl` without duplicating the resolution logic.

## log-subagent.sh and the subagent_call event

`scripts/log-subagent.sh` is the shared helper for emitting a `subagent_call` event. It is non-fatal — it always exits 0, and callers may also invoke with `|| true`.

### Event shape

```json
{
  "kind": "subagent_call",
  "host": "<detected>",
  "role": "reviewer",
  "subagent_type": "codex-reviewer",
  "subagent_model": "haiku",
  "prompt_chars": 4821,
  "response_chars": 3102,
  "provider_input_tokens": 1210,
  "provider_output_tokens": 755
}
```

Fields:
- `host` — stamped automatically by `log-event.sh`; not passed by the caller.
- `role` — logical role name, e.g. `reviewer`, `consultant-primary`, `implementer`.
- `subagent_type` — e.g. `codex-reviewer`, `consultant`, `implementer`.
- `subagent_model` — e.g. `haiku`, `sonnet`, `opus`.
- `prompt_chars` — raw character count of the prompt; NEVER collapsed with `response_chars`.
- `response_chars` — raw character count of the response; kept separate (Decision D9).
- `provider_input_tokens` (optional) — real token count from a CLI usage line; omit for native Claude subagents.
- `provider_output_tokens` (optional) — real token count from a CLI usage line; omit for native Claude subagents.

### Wiring

Five canonical logging sites are pinned by the drift-guard:
- `agents/reviewer.md` — self-logs on return
- `agents/consultant-primary.md` — self-logs on return
- `agents/consultant-secondary.md` — self-logs on return
- `commands/z-implement-all.md` — orchestrator logs implementer dispatch (wired by T006)
- `commands/z-implement-next.md` — orchestrator logs implementer dispatch (wired by T007)

Consultant dispatches from orchestrators (e.g. `z-review-all.md`, `z-audit-plan.md`) do NOT require an additional `log-subagent.sh` call — the agents self-log. Double-logging from orchestrators would inflate cost metrics.

### CLI usage

```bash
bash scripts/log-subagent.sh \
  --run          "tasks/<task-id>"   \
  --role         "reviewer"          \
  --subagent-type "codex-reviewer"   \
  --subagent-model "haiku"           \
  --prompt-chars  4821               \
  --response-chars 3102              \
  [--provider-input-tokens  1210]    \
  [--provider-output-tokens 755]
```

## Honest limitation: chars not tokens for native Claude subagents

For native Claude `Agent()` subagents, the orchestrator does not have access to real provider token usage. `prompt_chars` and `response_chars` are therefore **exact character counts, not token counts**. This limitation is labeled in the event and in `/z-stats` output.

Real `provider_input_tokens` / `provider_output_tokens` appear only for external CLI providers (e.g. codex) that print a usage line the agent can parse.

In `/z-stats` output, cost estimates using char-based data are labeled `[char-est]` to distinguish them from `[real tokens]` entries backed by CLI usage lines, or `[mixed: provider+chars]` when a bucket has both.

## Drift-guard CI: test_subagent_logging.sh

`scripts/test_subagent_logging.sh` enforces that `implementer` dispatch sites stay logged. It runs two checks:

**Part 1 — Pinned canonical sites:** verifies the 5 files wired by T006/T007 still contain `log-subagent.sh`. Failure here is a regression.

**Part 2 — Broad drift scan:** scans all `commands/*.md` and `agents/*.md` for `subagent_type="implementer"`. Any such file lacking either `log-subagent.sh` or `# no-subagent-log: <reason>` is a violation. Opt-out comment must be exactly `# no-subagent-log: <reason>`.

The test includes a self-test (fixtures A/B/C) that proves the detection logic itself works.

Note: this check only targets `implementer` dispatch sites, not all `Agent()` calls. Consultant dispatches from orchestrators are exempt because the agents self-log.

## Read-side: estimate-tokens.py subagent-costs

`estimate-tokens.py subagent-costs` reads `subagent_call` events from `metrics.jsonl` and computes a per-host, per-subagent-type cost breakdown. It weights `prompt_chars` and `response_chars` using per-model input/output rates, because output is priced approximately 5x input and a flat `chars/4` proxy actively under-costs output-heavy calls.

The output is grouped by `host` (so the `claude` vs `pi` vs `codex` cut is a one-liner) and labeled with `[char-est]` or `[real tokens]` depending on whether provider token counts were available. This is surfaced in `/z-stats` Phase 3b.

Model rate table lives in `_DEFAULT_MODEL_RATES` in `estimate-tokens.py` — covers Claude family (haiku/sonnet/opus), GPT family, Gemini family, and DeepSeek. Unknown models fall back to sonnet rates.

Environment knobs for the estimate subcommand:
- `Z_HARNESS_COST_TAIL_LINES` — max lines read from `metrics.jsonl` tail (default: `2000` for estimate, `5000` for subagent-costs)
- `Z_HARNESS_COST_MIN_SAMPLES` — minimum historical samples for empirical tier (default: `3`)

**Decision D9:** prompt and response chars are kept separate in the event. Collapsing them into a single `est_tokens = chars/4` was rejected as actively misleading for cost attribution — output-heavy calls are ~5x more expensive per token than input. Price weighting belongs downstream in the cost model, not in telemetry.

## How it interacts with others

- `cost-estimation` — `estimate-tokens.py` hosts both the pre-run estimate and the subagent-costs read-side in the same file; the subagent-costs model uses the same `_default_metrics_path()` resolution logic
- `scripts` — `log-event.sh` and `detect-host.sh` are the foundation; `log-subagent.sh` delegates to `log-event.sh`
- `reviewer-capture` — reviewer and consultant agents call `log-subagent.sh` as part of their capture flow; `response_chars` is sourced from the captured review file size
- `impl-pre-review` — the pre-reviewer subagent is also logged via `log-subagent.sh`

## Edge cases / gotchas

- `Z_HARNESS_HOST` env var overrides detection entirely; useful in CI where the env markers are absent but the true host is known.
- The host sentinel is keyed on `$PPID`, not `$$` — each `bash log-event.sh` call is a new process; `$PPID` is the stable parent orchestrator PID.
- `log-subagent.sh` `--provider-input-tokens` and `--provider-output-tokens` are optional flags; passing empty string is equivalent to omitting them (the payload builder skips falsy values).
- `/z-stats` `subagent-costs` output labels char-based estimates clearly — do not compare `[char-est]` rows with `[real tokens]` rows without accounting for the ~4-char-per-token heuristic.
- Drift-guard opt-out comment must be exactly `# no-subagent-log: <reason>` — any deviation will cause `test_subagent_logging.sh` to flag the site.
- The drift guard only catches `subagent_type="implementer"` sites, not all `Agent()` calls; consultant dispatches from orchestrators are exempt because the agents self-log from within `consultant-primary.md` / `consultant-secondary.md`.
- `subagent_call` events land in the repo-wide `metrics.jsonl` at the external base root, not in the per-plan directory; `/z-stats` Phase 3b explicitly resolves `base_dir` for this reason.

## Examples

Example `/z-stats` Phase 3b output:

```
Subagent cost breakdown (char-based estimate: chars/4 -> tokens; no native-Claude token counts available)
  Events: 47 subagent_call (of 4042 total read)

  Host: claude
    consultant             calls=12   in=   48000 out=   16000 tok  est=$0.4560 [char-est]
    implementer            calls=23   in=   92000 out=   30000 tok  est=$1.7250 [char-est]
    reviewer               calls=12   in=   48000 out=   12000 tok  est=$0.1980 [char-est]

  Host: pi
    reviewer               calls=4    in=   16000 out=    4000 tok  est=$0.0660 [mixed: provider+chars]

  TOTAL                     calls=51   in=  204000 out=   62000 tok  est=$2.4450
    (input: $0.8160  output: $1.6290)
```
