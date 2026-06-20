# reviewer-capture

> Last updated: 2026-06-19
> Covers source: agents/reviewer.md, agents/consultant-primary.md, agents/consultant-secondary.md

## Overview

`reviewer-capture` is the file-based review capture mechanism shared by the `reviewer`, `consultant-primary`, and `consultant-secondary` agents. Rather than capturing codex's full stdout transcript (which includes reasoning chatter and can exceed 200 KB), all three agents exploit codex's native `-o/--output-last-message FILE` flag to write only the final message to an archive file. The file becomes the source of truth; the orchestrator receives only a tight structured summary (verdict + blocker/major counts + artifact path). Non-codex providers (gemini, flash, manual) use a byte-identical stdout-capture path — the `-o` flag is never appended for non-codex providers.

The mechanism also covers how both consultant agents emit a `consult_start` event before their CLI call (enabling liveness detection), and how all three agents validate provider capability once per session via a `$PPID`-keyed sentinel file. Since the 2026-06-10 initial release the reviewer has gained full INTENT mode support (durable tier: KERNEL/INVARIANTS/STYLE + frozen INTENT snapshot + LEDGER), a `FOLLOWUPS` output section that routes minors/nits to the follow-up sink, `relevant_docs` input for concept JSON cross-reference, and a `contract` validation field (`expected_contract: review-verdict`). Both consultant agents added `consult_start` telemetry and many new modes.

## Key entry points

- `agents/reviewer.md:229` — `PROBE_SENTINEL` — per-PPID sentinel caches `CODEX_SUPPORTS_OUTFILE`; greps `codex exec --help` for `output-last-message`; runs once per orchestrating process
- `agents/reviewer.md:248` — `ARCHIVE_DIR / OUTFILE` — canonical artifact path: `$Z_HARNESS_PLAN_DIR/archive/tasks/<id>/review-cycle<N>.md`
- `agents/reviewer.md:253` — `CAPTURE_MODE=file` branch — codex path: appends `-o "$OUTFILE"`; stdout transcript discarded; fallback on empty/missing file emits `review_capture_fallback`
- `agents/reviewer.md:281` — `review_capture_fallback` event — uniform schema `{id, cycle, role, reason}` across all three agents
- `agents/consultant-primary.md:49` — `consult_start` event — emitted before CLI call; liveness.sh uses it as an in-flight marker
- `agents/consultant-primary.md:53` — same probe block — identical `CODEX_SUPPORTS_OUTFILE` probe; archive path under `z-harness/archive/$RUN/transcripts/`
- `agents/consultant-secondary.md:49` — same `consult_start` + probe block as consultant-primary

## How it interacts with others

- `subagent-telemetry` — `log-subagent.sh` is called by all three agents after capture; `response_chars` equals the size of the captured final review (honest), not the discarded transcript
- `providers-registry` — `resolve-provider.sh` returns `{"provider": "codex"|"gemini"|...}` which gates the file-based path; only `provider == "codex"` triggers `-o`
- `commands` (z-implement-all, z-review-all, z-plan, z-debug) — orchestrators dispatch these agents and consume the `verdict / blockers / majors / artifact` structured return
- `followup-sink` — reviewer output includes a `**FOLLOWUPS:**` fenced JSON block; orchestrator routes entries via `scripts/parse-followups-block.py` and `scripts/sink-add.sh`

## Edge cases / gotchas

- Sentinel is keyed on `$PPID` (parent PID) not `$$`. Each `bash reviewer.md` invocation is a new process; `$PPID` is the orchestrating shell and persists across all tasks in one run.
- `$Z_HARNESS_PLAN_DIR` must be exported by the orchestrator; if unset, `ARCHIVE_DIR` construction fails before dispatch.
- Codex non-zero exit triggers fallback even if `$OUTFILE` was partially written — the file is considered valid only on exit 0.
- Probe greps for long-form `--output-last-message`; dispatches with short alias `-o`. A future codex rename will probe-fail and fall through to stdout capture without regression.
- Reviewer INTENT mode requires **both** `intent_snapshot:` AND `ledger_path:` to be present; if exactly one is present the agent returns a BLOCKED verdict with a `MISCONFIGURED` message rather than inferring the other.
- Consultant archive paths differ from reviewer: `z-harness/archive/$RUN/transcripts/<N>-<slug>.response.md` (consultant) vs `$Z_HARNESS_PLAN_DIR/archive/tasks/<id>/review-cycle<N>.md` (reviewer).
- `review_capture_fallback` uses a uniform schema `{id, cycle, role, reason}` across all three agents; `role` is the cross-agent disambiguator needed for fallback-rate analysis.
- Minors and nits from the reviewer are dropped from the `### Blockers` / `### Major` return sections and MUST appear in `**FOLLOWUPS:**` (P3 or P2) instead — they are never silently dropped.

## Examples

- Full review artifact: `$Z_HARNESS_PLAN_DIR/archive/tasks/T001/review-cycle1.md`
- Consultant transcript: `z-harness/archive/<run-id>/transcripts/001-consultant-primary-codex-plan-review.response.md`
- Fallback event payload: `{"id":"T001","cycle":1,"role":"reviewer","reason":"exit_1_or_empty_outfile"}`
