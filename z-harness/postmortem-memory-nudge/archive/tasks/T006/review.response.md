# Codex Review Output

## Blockers

- **Blocker, Phase 7 step 5:** The ready-path agent failure cases emit no `memory_review_terminal`, violating the single-terminal-event-per-invocation invariant whenever the helper returns `STATUS: ready` and the agent output is malformed or missing. Fix by emitting exactly one terminal event on these soft-failure exits, or explicitly amend the spec if agent failure is meant to be the only non-terminal exception.

- **Blocker, Phase 7 steps 2/6/8:** The skip and empty-candidate snippets rely on comments saying "exit phase" but do not show an actual `return`/`exit`/branch terminator, so a literal implementation can continue into ready-path parsing or emit a second terminal event. Add explicit control flow after every terminal/skip path, and make step 8 apply only to the candidates ≥1 gate loop.

## Major Issues

- **Major, Phase 7 step 5:** No-fenced-block handling is contradictory: it is included under `review_agent_malformed` and also separately under `review_agent_failed`, so implementers may log the wrong event or both. Split the cases unambiguously: no fenced block → one event kind, invalid fenced JSON → the other, then soft-exit once.

- **Major, Phase 7 "Clear dedup file at phase start":** `rm -f "$BASE/.notify-dedup-session"` can target `/.notify-dedup-session` when `$BASE` is unset, which is exactly one of the broken-context paths this phase must handle silently. Guard with `[[ -n "${BASE:-}" ]] && rm -f "$BASE/.notify-dedup-session"` or move dedup clearing after the helper has resolved a valid plan dir.

- **Major, Phase 7 step 2:** The skipped-broken-context push-notify path only records the dedup key and contains a comment for the notification, so it does not actually satisfy the required push-notify behavior. Wire the same concrete notification mechanism used elsewhere in the harness inside the dedup guard, then append the key only after the notification attempt path is entered.

- **Major, Phase 7 step 5:** Malformed-output failure paths include push-notify instructions, but the acceptance text says malformed output exits silently without halting. Remove the push notification for malformed/no-fenced output unless the spec is amended to make this an approval-visible failure.

- **Major, Phase 7 steps 6/8:** The terminal payloads are built with `printf` and raw `"${Z_HARNESS_SLUG:-null}"`, producing `"null"` as a string when unset and invalid JSON if the slug contains quotes or backslashes. Build these payloads with `jq -n` or the helper's JSON builder so `slug` is either JSON null or a correctly escaped string.
