# reviewer-capture

> Last updated: 2026-06-24
> Covers source: agents/reviewer.md, agents/consultant-primary.md, agents/consultant-secondary.md

## Overview

`reviewer-capture` is the shared final-message capture pattern used by `agents/reviewer.md`, `agents/consultant-primary.md`, and `agents/consultant-secondary.md`. When the resolved provider is Codex and the local CLI supports `--output-last-message`, the agents pass `-o <outfile>` so Codex writes only the final provider response to the canonical artifact. Stdout transcript chatter is discarded. Non-Codex providers and Codex probe failures follow the existing stdout-capture path.

The same source files also define review/consult telemetry and contracts: consultants emit `consult_start` before their CLI call for liveness, all three agents emit `log-subagent.sh` after capture, reviewers support legacy SPEC and INTENT mode contracts, and reviewer minor/nit findings must be routed through the `FOLLOWUPS` block rather than silently dropped.

## Key entry points

- `agents/reviewer.md:20` — reviewer persona contract is `review-verdict`.
- `agents/reviewer.md:67` — INTENT-mode inputs: frozen `intent_snapshot`, `ledger_path`, and optional durable-tier files.
- `agents/reviewer.md:92` — misconfiguration guard: exactly one of `intent_snapshot`/`ledger_path` returns BLOCKED instead of guessing mode.
- `agents/reviewer.md:221` — Codex output-file capability probe sentinel keyed on `$PPID`.
- `agents/reviewer.md:240` — reviewer archive dir: `$Z_HARNESS_PLAN_DIR/archive/tasks/<task-id>/`.
- `agents/reviewer.md:248` — Codex file-capture branch; `-o "$OUTFILE"` writes the final message.
- `agents/reviewer.md:263` — `review_capture_fallback` event with uniform `{id, cycle, role, reason}` schema.
- `agents/reviewer.md:301` — reviewer subagent telemetry call.
- `agents/reviewer.md:354` — `FOLLOWUPS` output section specification for minors/nits routed to the follow-up sink.
- `agents/consultant-primary.md:49` / `agents/consultant-secondary.md:49` — `consult_start` emitted before CLI call.
- `agents/consultant-primary.md:53` / `agents/consultant-secondary.md:53` — consultant Codex probe; transcript archive under `z-harness/archive/$RUN/transcripts/`.
- `agents/consultant-primary.md:224` / `agents/consultant-secondary.md:224` — consultant subagent telemetry calls.

## How it interacts with others

- `providers-registry` — resolved provider name gates whether Codex file capture applies.
- `subagent-telemetry` — captured final response size is the honest `response_chars` source.
- `followup-sink` — reviewer `FOLLOWUPS` JSON is parsed and persisted as lower-priority follow-up work.
- `liveness` — consultant `consult_start` and final `consult` event form the in-flight/end marker pair.
- `/z-execute`, `/z-review-all`, `/z-plan`, `/z-debug` — orchestrators dispatch these agents and consume the artifact/verdict outputs.

## Edge cases / gotchas

- The capability sentinel is keyed on `$PPID`, not `$$`, so it persists across subprocess invocations in one orchestration.
- `-o` is appended only for `provider == "codex"` and only after a positive capability probe.
- Codex non-zero exit or empty/missing outfile triggers fallback even if a partial file exists.
- Consultant archive paths differ from reviewer task archive paths; do not assume one locator works for all three agents.
- `$Z_HARNESS_PLAN_DIR` must be exported before reviewer dispatch because reviewer artifact paths depend on it.
- Reviewer INTENT mode requires both frozen INTENT and LEDGER; it does not infer a missing one and does not fall back to legacy mode.
- Minors and nits are not returned in blocker/major sections; they must appear in `FOLLOWUPS` with P2/P3 priority.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/reviewer-capture.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

- Reviewer artifact: `$Z_HARNESS_PLAN_DIR/archive/tasks/T001/review-cycle1.md`
- Consultant artifact: `z-harness/archive/<run-id>/transcripts/001-consultant-primary-codex-plan-review.response.md`
- Fallback event: `{"id":"T001","cycle":1,"role":"reviewer","reason":"exit_1_or_empty_outfile"}`
