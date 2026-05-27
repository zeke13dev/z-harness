**D1. Locus**
- Recommendation: Compute the 4-state terminal taxonomy in `run-memory-review.sh`. Keep SKILL.md callers as thin dispatchers that pass context and parent metadata.
- Risk: The script can become a policy sink if it starts absorbing caller-specific semantics beyond terminal classification.
- Interaction: This supports D5 cleanly: `/z-debug` can dispatch the same script without reimplementing skip logic.

**D2. Event Shape**
- Recommendation: Add a dedicated `memory_review_terminal` event. Do not overload `phase_end`.
- Risk: Consumers like `/z-stats` need explicit updates or they will miss the new event until wired.
- Interaction: D11 depends on this being easy to detect; a dedicated event makes notify-on-skip and stats aggregation less ambiguous.

**D5. z-debug Dispatch**
- Recommendation: Yes, add Phase 9b to `/z-debug` and call `run-memory-review.sh` with `parent_command=debug` plus `DEBUG.md` context.
- Risk: Debug runs may produce noisy or premature memory candidates if the post-mortem is thin, speculative, or written before the fix is fully verified.
- Interaction: Requires D7. Also increases the importance of D1 because debug should not fork the review terminal model.

**D7. DEBUG.md Input**
- Recommendation: Add optional `debug_md_path` to the review-agent input contract. Keep `spec_path` unchanged and optional/nullable by command context if needed.
- Risk: Agent prompts may start treating both `spec_path` and `debug_md_path` as equally authoritative unless the contract says which artifact is primary per `parent_command`.
- Interaction: D5 needs this. It also avoids breaking existing `/z-implement-all` behavior because the current `spec_path` field remains stable.

**D11. skipped_broken_context Notify**
- Recommendation: Push-notify once per run for `skipped_broken_context`, including the concrete reason. Use the terminal event as the source of truth.
- Risk: Notification fatigue if `tags_missing` is common and not actionable by the user.
- Interaction: Depends on D2/D4-style terminal visibility. If D1 centralizes classification, the "once per run" guard should also live near the script or shared event emission path.
