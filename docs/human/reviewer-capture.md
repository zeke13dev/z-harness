# reviewer-capture

> Last updated: 2026-07-09
> Covers source: agents/reviewer.md, agents/consultant-primary.md, agents/consultant-secondary.md

## Overview

`reviewer-capture` is the shared final-message capture pattern used by `agents/reviewer.md`, `agents/consultant-primary.md`, and `agents/consultant-secondary.md`. When the resolved provider is Codex and the local CLI supports `--output-last-message`, the agents pass `-o <outfile>` so Codex writes only the final provider response to the canonical artifact. Stdout transcript chatter is discarded. Non-Codex providers and Codex probe failures follow the existing stdout-capture path.

The same source files also define review/consult telemetry and contracts: consultants emit `consult_start` before their CLI call for liveness, all three agents emit `log-subagent.sh` after capture, reviewers support legacy SPEC and INTENT mode contracts, and reviewer minor/nit findings must be routed through the `FOLLOWUPS` block rather than silently dropped. All three agent files carry the auto-generated-shape marker (`<!-- auto-generated shape: consultant-primary | consultant-secondary | reviewer differ only in ROLE below -->`) — they are templated off one shape and differ only in `ROLE=` / `expected_contract:`.

## Key entry points

- `agents/reviewer.md:20` — reviewer persona contract is `review-verdict` (`expected_contract: review-verdict`).
- `agents/reviewer.md:67` — INTENT-mode inputs: frozen `intent_snapshot`, `ledger_path`, and optional durable-tier files.
- `agents/reviewer.md:95` — misconfiguration guard: exactly one of `intent_snapshot`/`ledger_path` returns BLOCKED instead of guessing mode.
- `agents/reviewer.md:231` — Codex output-file capability probe sentinel keyed on `$PPID`.
- `agents/reviewer.md:250` — reviewer archive dir: `$Z_HARNESS_PLAN_DIR/archive/tasks/<task-id>/`.
- `agents/reviewer.md:255` — Codex file-capture branch (`if [ "$PROVIDER" = "codex" ] ...`).
- `agents/reviewer.md:258` — `CAPTURE_MODE="file"` set; `-o "$OUTFILE"` writes the final message.
- `agents/reviewer.md:273` — `review_capture_fallback` event with uniform `{id, cycle, role, reason}` schema.
- `agents/reviewer.md:311` — reviewer subagent telemetry call (`log-subagent.sh`).
- `agents/reviewer.md:364` — `**FOLLOWUPS:**` output section for minors/nits routed to the follow-up sink.
- `agents/consultant-primary.md:20` / `agents/consultant-secondary.md:20` — consultant persona contract is `freeform` for both.
- `agents/consultant-primary.md:49` / `agents/consultant-secondary.md:49` — `consult_start` emitted before CLI call, for liveness detection even when `$TIMEOUT_CMD` is empty.
- `agents/consultant-primary.md:53` / `agents/consultant-secondary.md:53` — consultant Codex probe (same PPID-keyed sentinel pattern as the reviewer); transcript archive under `z-harness/archive/$RUN/transcripts/`.
- `agents/consultant-primary.md:224` / `agents/consultant-secondary.md:224` — consultant subagent telemetry calls (`log-subagent.sh`).

## How it interacts with others

- `providers-registry` (`scripts/resolve-provider.sh`) — resolved provider name gates whether Codex file capture applies; also supplies `command`, `args_template`, `stdin`, `model_label`, `timeout_s`.
- `subagent-telemetry` (`scripts/log-subagent.sh`) — captured final response size (`response_chars`) is the honest source, not the discarded Codex transcript.
- `followup-sink` (`scripts/parse-followups-block.py`, `scripts/sink-add.sh`) — reviewer `**FOLLOWUPS:**` JSON is parsed and persisted as lower-priority (P2/P3) follow-up work; parse failures log `followup_block_parse_failed` and never crash the reviewer return path.
- `liveness` (`scripts/liveness.sh`) — consultant `consult_start` and the later `consult` event form the in-flight/end marker pair (`END_KIND_TO_BASE`).
- `skills/z-execute`, `skills/z-review-all`, `skills/z-plan`, `skills/z-debug`, `skills/z-fix`, `skills/z-audit`, `skills/z-mr-review`, `skills/z-improve`, `skills/z-amend`, `skills/z-maintain-docs`, `skills/z-test`, `skills/z-explore`, `skills/z-brainstorm`, `skills/z-research`, `skills/z-style-init`, `skills/z-test-prune`, `skills/z-audit-plan` — the repo migrated `commands/` → `skills/` (see project memory `skills-removed-single-source` / `z-harness-portability plan`); these skills dispatch the reviewer and/or the two consultant agents and consume the artifact/verdict outputs. `skills/z-audit-plan-style` also references the reviewer.

## Edge cases / gotchas

- The capability sentinel is keyed on `$PPID`, not `$$`, so it persists across subprocess invocations in one orchestration.
- `-o` is appended only for `provider == "codex"` and only after a positive capability probe.
- Codex non-zero exit or empty/missing outfile triggers fallback even if a partial file exists.
- Consultant archive paths (`z-harness/archive/$RUN/transcripts/`) differ from reviewer task archive paths (`$Z_HARNESS_PLAN_DIR/archive/tasks/<task-id>/`); do not assume one locator works for all three agents.
- `$Z_HARNESS_PLAN_DIR` must be exported before reviewer dispatch because reviewer artifact paths depend on it.
- Reviewer INTENT mode requires both frozen INTENT and LEDGER; it does not infer a missing one and does not fall back to legacy mode.
- Minors and nits are not returned in blocker/major sections; they must appear in `**FOLLOWUPS:**` with P2/P3 priority.
- Consultants support many `MODE:` values (`bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `research-review`, `brainstorm`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`); most use a standard response wrapper, but `brainstorm`, `research-review`, `mr-review`, and both `generate-hypotheses-*` modes return the provider's raw output unchanged.
- Line numbers in this doc are exact for the current source; if any of the three agent files gets edited (e.g. a new mode added, a bash block reflowed), the numbered entry points below the "auto-generated shape" comment can drift out from under this doc quickly — this doc going stale via line-number drift (not content drift) is exactly what triggered this refresh.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/reviewer-capture.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

- Reviewer artifact: `$Z_HARNESS_PLAN_DIR/archive/tasks/T001/review-cycle1.md`
- Consultant artifact: `z-harness/archive/<run-id>/transcripts/001-consultant-primary-codex-plan-review.response.md`
- Fallback event: `{"id":"T001","cycle":1,"role":"reviewer","reason":"exit_1_or_empty_outfile"}`
