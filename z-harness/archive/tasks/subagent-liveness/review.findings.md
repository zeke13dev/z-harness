## Codex review: subagent-liveness (RETRY v5)

### Blockers

1. **RUN placeholder not derived before sourcing check-timeout.sh** (`agents/consultant-primary.md:28`, `agents/consultant-secondary.md:28`, `agents/reviewer.md:28`): The pre-call path sets `RUN` to a literal `"<run-id from caller>"` placeholder string with no fallback to derive the actual run id before sourcing `check-timeout.sh` or emitting `consult_start`. This logs liveness events to the wrong archive path. Derive the run id at the top of the agent file (reuse existing Archiving section logic) and thread it through all event calls.

2. **consult_start JSON not escaped** (`agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`): The `printf` string interpolation for `role`/`mode`/`provider` will produce invalid JSON if provider or mode contain JSON-special characters (quotes, backslashes, newlines), causing `log-event.sh` to wrap it as `{"raw": ...}` and lose the top-level `role` field that liveness matching depends on. Build the JSON payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.

### Major

1. **match_key() ignores mode/provider discriminators** (`scripts/liveness.sh`): Although `consult_start` events include `mode` and `provider`, `match_key()` only keys on `(base, tid, retry, role)`, so two parallel `consult_start` events from the same consultant agent role in different modes collapse to the same key. Include `mode` and provider identity (or a generated invocation id on both start and end) to distinguish overlapping calls.

2. **Timeout availability marker is path-scoped, not run-scoped** (`scripts/check-timeout.sh:42`): The `.timeout-logged` marker is placed under the resolved run dir, but the same run id can be sourced with different `Z_HARNESS_SLUG` values, each resolving to a different archive path and emitting duplicate `timeout_availability` events (this pattern already appears in `z-harness/metrics.jsonl`). Resolve through `plan-path.sh` or gate on a repo-wide canonical `(slug, run)` marker before logging.
