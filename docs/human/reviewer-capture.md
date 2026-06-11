# reviewer-capture

> Last updated: 2026-06-10
> Covers source: agents/reviewer.md, agents/consultant-primary.md, agents/consultant-secondary.md

## Overview

`reviewer-capture` is the file-based review capture mechanism introduced in the `reviewer-cost-telemetry` plan (Change 1). Before this change, `agents/reviewer.md` and both consultant agents captured the codex provider's full stdout transcript — including reasoning, chatter, and the final message — and truncated it to 8 000 characters for return. Observed `response_chars` of 76 k/122 k/211 k resulted in 95–100 % discard, and some reviews landed `return=0`, clobbering the verdict entirely. The file-based path exploits codex's native `-o/--output-last-message FILE` flag to capture only the final message, discarding the transcript.

The non-codex provider path (gemini/flash/manual) is byte-identical to the pre-feature behavior — the `-o` flag is never appended for non-codex providers.

## Key entry points

<!-- AUTO-START: entry-points -->
- `agents/reviewer.md:135` — `# Call the provider (with file-based capture for codex)` — codex capability probe + file-based dispatch block; fallback-on-empty-file logic
- `agents/reviewer.md:143` — `PROBE_SENTINEL` — per-session sentinel keyed on `$PPID`; caches `CODEX_SUPPORTS_OUTFILE` so the probe runs once per run, not once per task
- `agents/reviewer.md:160` — `ARCHIVE_DIR / OUTFILE` — canonical artifact path: `$Z_HARNESS_PLAN_DIR/archive/tasks/<id>/review-cycle<N>.md`
- `agents/reviewer.md:166` — `CAPTURE_MODE="file"` branch — codex path: appends `-o "$OUTFILE"`; ignores stdout transcript; reads final review from `$OUTFILE`
- `agents/consultant-primary.md:61` — same probe + dispatch block (CAPTURE_MODE); log-subagent.sh call at line 224
- `agents/consultant-secondary.md:61` — identical shape; same invariants as consultant-primary
<!-- AUTO-END: entry-points -->

## Codex capability probe

The probe runs once per orchestrating process, keyed on `$PPID` (parent shell PID) so it persists across multiple task reviews within one `/z-implement-all` run but is not shared across runs:

```bash
PROBE_SENTINEL="/tmp/z-harness-codex-outfile-probe.${PPID:-$$}"
if [ ! -f "$PROBE_SENTINEL" ]; then
  if codex exec --help 2>&1 | grep -q 'output-last-message'; then
    printf '1' > "$PROBE_SENTINEL"
  else
    printf '0' > "$PROBE_SENTINEL"
  fi
fi
CODEX_SUPPORTS_OUTFILE="$(cat "$PROBE_SENTINEL")"
```

The probe greps for the long-form `--output-last-message` flag. If found, `-o` (the short alias) is used in the actual dispatch. If not found (older codex version), the stdout-capture fallback is used.

## Canonical artifact path

The full review is written to:

```
$Z_HARNESS_PLAN_DIR/archive/tasks/<task-id>/review-cycle<N>.md
```

This file is the **source of truth** for the review content. The orchestrator receives only the verdict (`PASS`/`FAIL`/`BLOCKED`), blocker/major counts, and the artifact path. The 8 000-character `$RETURN` cap is no longer the source of truth — the file is.

The archive directory is created with `mkdir -p` before dispatch. `CYCLE` is the current review cycle number (1 on first review, N on subsequent retries).

## Dispatch logic

```bash
if [ "$PROVIDER" = "codex" ] && [ "$CODEX_SUPPORTS_OUTFILE" = "1" ]; then
  CAPTURE_MODE="file"
  # appends: -o "$OUTFILE" to the codex exec invocation
  # stdout transcript is intentionally discarded
  ...
fi
```

The provider value comes from `resolve-provider.sh` output (`d["provider"]`). Non-codex providers (`gemini`, `flash`, `manual`) enter the `stdout` capture path, which is byte-identical to the pre-feature behavior.

## Fallback path

If `$OUTFILE` is missing or empty after a codex dispatch, or if codex exits non-zero:

1. Revert to current stdout capture + truncation.
2. Emit `review_capture_fallback {id, cycle, role, reason}` — one uniform schema across the reviewer (`role=reviewer`) and both consultants (`role=consultant-primary`/`consultant-secondary`). The SPEC's `{id, cycle, reason}` is the required floor; `role` is the cross-agent disambiguator a fallback-rate cut needs.
3. Never silently lose a verdict.

The fallback ensures no behavior regression when codex's `-o` support is absent or the file write fails.

## response_chars semantics

After this change, `response_chars` logged in the `phase_end` and `subagent_call` events is the **size of the captured final review** (the file or stdout content used as the verdict), not the size of the discarded transcript. This makes `response_chars` an honest cost signal for the first time.

## Invariants

- Non-codex provider path is byte-identical to today — `-o` is only appended when provider == `codex`.
- The capability probe runs at most once per parent-PID process; the sentinel file is never deleted mid-run.
- `OUTFILE` is always in `$Z_HARNESS_PLAN_DIR/archive/tasks/<id>/` — callers never need to discover the path separately.
- Fallback emits `review_capture_fallback` before reverting; verdict is never silently dropped.
- `response_chars` = size of the review text actually used (honest); transcript discard is not reflected in any event field.
- Both consultant agents share the same probe/dispatch/fallback/log shape as the reviewer — the three files are co-maintained.

## Edge cases / gotchas

- The sentinel is keyed on `$PPID`, not `$$`. Each `bash reviewer.md` invocation is a new process (`$$` differs); `$PPID` is the orchestrating shell that spawns it, which persists across all task reviews in one run.
- If `$Z_HARNESS_PLAN_DIR` is unset, `ARCHIVE_DIR` construction fails — the agent will error before dispatch. The orchestrator is responsible for exporting this variable.
- codex exit non-zero (e.g. timeout) triggers the fallback even if `$OUTFILE` was partially written — the file is considered valid only when codex exits 0.
- The `-o` flag is the documented short alias of `--output-last-message`; the probe greps for the long form, so a future codex version that renames it will correctly probe-fail and fall through to stdout capture without regression.
- `review-cycle<N>.md` is overwritten if a task is retried and the cycle number resets (not expected in v1, but callers should not assume file uniqueness across retries).

## See also

- `agents/reviewer.md` — source file; file-based capture wiring at line ~135.
- `agents/consultant-primary.md` — same wiring; role = `consultant-primary`.
- `agents/consultant-secondary.md` — same wiring; role = `consultant-secondary`.
- `docs/human/subagent-telemetry.md` — `response_chars` is consumed by `log-subagent.sh` after capture.
- `docs/human/reviewer-cost-telemetry` SPEC Change 1 — full design rationale.
