**Findings**

**blocker** agents/mr-reviewer.md:245 conflicts with the required parse-failure telemetry.
Step 4 explicitly requires logging `mr_voice_failed` on malformed JSON, but the "What this agent does NOT do" section says the agent "Does not emit telemetry events." That directly undermines acceptance criterion 3 and gives the agent contradictory instructions.

Suggested fix: remove that bullet or narrow it:
- Does not emit telemetry events except `mr_voice_failed` for malformed external voice JSON.

**major** agents/mr-reviewer.md:157 uses input `voices_available` for consensus even when an external voice failed parsing.
Step 4 says malformed voices are skipped entirely and tracks `voices_succeeded`, while Step 6 exposes `voices_used` as parseable contributors. But Step 5 applies tier-bump against the original input `voices_available`. If `voices_available=[claude,codex,gemini]` and Gemini returns malformed JSON, a finding raised by Claude+Codex will not promote, and Claude-only findings will demote as if three voices participated. That makes parse failure affect severity despite "skip that voice's findings entirely," and breaks the practical "single-available no bump" fallback when all external voices fail.

Suggested fix: define the consensus set explicitly after parsing, for example:
Use `voices_succeeded` / `voices_used` as `voices_available` for consensus tier-bump. Failed voices do not count as available consensus participants.

Everything else in the scrutiny focus looks satisfied: parallel dispatch is stated at lines 107 and 136, dedup normalization matches the SPEC wording at line 155, P0 is protected in both tier-bump branches, the consultant mode additions are scoped and do not disrupt existing raw/wrapped mode handling, and the final JSON schema includes both per-finding `voices` and top-level `voices_used`.
