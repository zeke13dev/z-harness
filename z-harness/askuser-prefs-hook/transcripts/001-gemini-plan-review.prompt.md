MODE: plan-review

SPEC and PLAN for: askuser-prefs-hook — Pre-AskUserQuestion preference resolver + human-in-the-loop elevation proposer.

## SPEC excerpt — tier mapping and resolver logic

From SPEC.md lines 84–101 (config/memory consultation and tier-to-result mapping):

```
3. Consult 4-layer config precedence for `question_id`'s `config_key`. If the resolved value is **NOT** the default (`"ask"`) → `hard` tier:
   - Value `"skip"` → return `{result: "skip", default: <skill_default>, source: "config", rule_id: <key>, strength: "hard", ...}`.
   - Value `"prefill"` → return `{result: "prefill", ...}`.
   - Value `"amend"` / domain-specific → translate to `{result: "skip", default: "amend"}` (the option's display label is taken from the callsite's AskUserQuestion options).
4. Consult memory: glob `docs/llm/*.json`, filter `memories[]` for `type: "routing-preference"` matching this `question_id`. For each match, respect `scope`:
   - `scope: "global"` → always considered.
   - `scope: "project"` → only if `Z_HARNESS_PROJECT_ROOT` matches the entry's `project_root` field (or, if `Z_HARNESS_PROJECT_ROOT` unset, fall back to `git rev-parse --show-toplevel`).
5. If exactly one memory match: emit `strong | very_strong | weak` per its `strength` field.
6. If multiple memory matches with **agreeing values**: take the highest strength.
7. If multiple memory matches with **disagreeing values**: emit `conflict` tier with `sources` list naming each `{kind: "memory", value, location: "docs/llm/<slug>.json", strength}`.
8. If config is `"ask"` (default) AND any memory exists: that's not a conflict — the user-set-zero-config + had-a-memory means memory wins (no config opinion).
9. If config is `not "ask"` AND memory exists with **different** value: **conflict tier** — `sources` = `[{kind: "config", value, location, strength: "hard"}, {kind: "memory", value, location, strength}]`. Result is `ask`.
10. If config is `not "ask"` AND memory exists with **same** value: no conflict — emit the higher-confidence source's tier (config wins, source = "config").
11. Map tier → result:
    - `hard|very_strong` → `skip` (skill respects collision/safety checks regardless — SEE INVARIANTS)
    - `strong|weak` → `prefill`
    - `conflict` → `ask`
    - `none` → `ask`
```

QUESTION_IDS registry (lines 50–74):
```python
QUESTION_IDS: dict[str, dict] = {
    "workflow.audit_to_amend": {
        "config_key": "workflow.audit_to_amend",
        "choices": {"ask", "amend", "stop"},
        "skill_default": "amend",
        "callsites": [
            "commands/z-audit-plan.md:183",
            "commands/z-audit-plan-style.md:384",
        ],
    },
    "workflow.slug_confirm": {
        "config_key": "workflow.slug_confirm",
        "choices": {"ask", "skip", "prefill"},
        "skill_default": "skip",
        "callsites": [
            "commands/z-plan.md:21",
            "commands/z-fix.md:18",
            "skills/z-debug/SKILL.md:17",
            "skills/z-brainstorm/SKILL.md:19",
            "skills/z-research/SKILL.md:117",
            "skills/z-plan-light/SKILL.md:19",
            "commands/z-uplift.md:71",
        ],
    },
}
```

## SPEC excerpt — proposer and retrofit prose

From SPEC.md lines 133–154 (proposer detection):
```
Walk `z-harness/metrics.jsonl` for the last N (default 30) `run_start` events. Detect patterns of the shape "command A finished within T seconds of command B starting, same slug". Configurable via env:
- `Z_HARNESS_PROPOSE_WINDOW_S=3600` — max gap between command A end and B start
- `Z_HARNESS_PROPOSE_THRESHOLD=3` — min repetitions to propose

For v1, watched patterns are hardcoded:
- `/z-audit-plan → /z-amend` → propose `workflow.audit_to_amend = "amend"`
- `/z-audit-plan-style → /z-amend` → propose `workflow.audit_to_amend = "amend"` (same key)
- `/z-fix → (slug-derive-confirm answered "yes")` × 3 → propose `workflow.slug_confirm = "skip"` (telemetry-driven version)

The proposer never writes anything — proposal AskUserQuestion is in the calling skill's prose. User picks:
- Accept as config → caller calls `python3 scripts/config.py set workflow.audit_to_amend amend [--scope=global|project]`
- Accept as memory:very_strong → caller dispatches `/z-suggest-memory --kind routing-preference --question-id workflow.audit_to_amend --value amend --strength very_strong --scope project`
- Accept as memory:strong → same, strength=strong
- No → record `propose_rejected` event with question_id; suppress this proposal for the next 30 days (via marker file `~/.config/z-harness/.propose-suppress` keyed `<question_id>:<expiry-ts>`)

Dedup: a single proposal fires at most once per command-run. Per-question_id suppression is honored as long as the marker file says so.
```

From SPEC.md lines 166–180 (retrofit prose):
```markdown
At Phase 5 step 3 (the existing `AskUserQuestion`), prepend:

Before invoking AskUserQuestion, run:
```bash
RESOLVED="$(python3 scripts/config.py resolve-question workflow.audit_to_amend 2>/dev/null)"
RESULT="$(echo "$RESOLVED" | jq -r .result)"
DEFAULT="$(echo "$RESOLVED" | jq -r .default)"
```
- If `$RESULT == "skip"`: skip the AskUserQuestion and proceed as if the user picked `$DEFAULT` (which will be `"amend"` if config is set, or whatever memory said). Emit `askuser_skipped` event.
- If `$RESULT == "prefill"`: present the AskUserQuestion normally but pre-select `$DEFAULT` as the recommended option (label suffix: ` (Recommended — your preference)`).
- If `$RESULT == "ask"`: present the AskUserQuestion normally.
- If `$RESULT == "ask"` AND `source == "conflict"`: present normally, and add to the question header text: `(Note: config says <X>, memory says <Y> — resolve this conflict in your answer.)`
```

## SPEC excerpt — invariants (lines 214–223)

```
- **Stdout discipline (D1↔D5).** `config.py resolve-question` writes JSON only on stdout. All diagnostics on stderr. Validated by a test that pipes output through `python3 -m json.tool`.
- **Single QUESTION_IDS registry (D2↔D3).** One source of truth in `config.py`. Validated at startup: `assert set(QUESTION_IDS) <= set(VALIDATORS)`. /z-suggest-memory checks `question_id` against this registry via subprocess.
- **Safety checks survive skip (D7↔collision).** Slug-collision check is a hard prerequisite enforced in skill prose, independent of resolver outcome. SPEC retrofit prose makes this explicit.
- **Resolver is read-only.** Never writes to config or memory. All writes go through `config.py set` or `/z-suggest-memory`.
- **Proposer never auto-writes.** Threshold-reached → AskUserQuestion → user picks → caller does the write. Suppression is honored.
- **Conflict tier always asks.** No silent override. `sources[]` always populated. User sees both.
- **/z-suggest-memory routing-preference detection is non-blocking.** Detection-fail = continue with original write path.
- **Resolver is Claude-Code-only.** Multi-IDE export (Cursor/Codex/agy) does NOT carry the precheck. SPEC notes this; v2 concern.
```

## PLAN excerpt — retrofits and verification (PLAN.md lines 49–73)

```
### Phase C — Skill prose retrofits (D6, D10)
Update each of the 9 callsites per SPEC §retrofit. Pattern is identical (resolver call → branch on result). Two flavors:
- Audit→amend (2 sites: z-audit-plan.md, z-audit-plan-style.md).
- Slug-confirm (7 sites: z-plan.md, z-fix.md, z-debug/SKILL.md, z-brainstorm/SKILL.md, z-research/SKILL.md, z-plan-light/SKILL.md, z-uplift.md).
- Spell out the collision-check survives-skip invariant in the slug-confirm sites.

...

### Phase G — Verification
- End-to-end smoke test: set `workflow.audit_to_amend = "amend"` in `.z-harness/config.toml`. Run `/z-audit-plan`. Confirm Phase 5 skips its AskUserQuestion and proceeds as "amend". Confirm `askuser_resolved` event emitted with `source: config`.
- Conflict-tier test: set config = "amend", write memory routing-preference for same question_id with value = "stop". Run `/z-audit-plan`. Confirm Phase 5 surfaces the AskUser with sources clearly listed.
- Elevation-proposer test: simulate 3 runs of `/z-audit-plan → /z-amend` in metrics.jsonl; run `propose-prefs.py --check z-audit-plan`. Confirm proposal returned with the right question_id and `proposed_value: "amend"`.
- /z-suggest-memory routing-preference write test: invoke with `--kind routing-preference --question-id workflow.audit_to_amend --value amend --strength very_strong`. Confirm memory lands in `docs/llm/workflow.json` with the right shape, MEMORIES-FLAT.md is regenerated.
```

## The five focus questions

1. **5-tier signal-strength model → skip/prefill/ask outcomes.** Is the mapping (hard|very_strong → skip, strong|weak → prefill, conflict → ask, none → ask) correct? Are there edge cases in the tier derivation logic (especially lines 84–101) that map to wrong outcomes?

2. **QUESTION_IDS registry prevents typo-degradation.** If a question_id typo occurs (e.g., `/z-suggest-memory` receives `workflow.audit_to_amen` instead of `workflow.audit_to_amend`), does the registry check catch it? Is the startup assertion sufficient?

3. **Proposer pattern-detection robustness.** The proposer watches for "/z-audit-plan → /z-amend" (same slug, within 3600s, 3+ times). Could it false-positive (e.g., propose "amend" when the user was actually always picking "stop")? Does it validate that the user's choice was consistent?

4. **Retrofit prose consistency across 9 sites.** The plan calls for "identical pattern" retrofits across z-plan, z-fix, z-debug, z-brainstorm, z-research, z-plan-light, z-uplift, z-audit-plan, z-audit-plan-style. Are there syntactic or semantic differences in these files that could cause the resolver invocation or branching logic to drift or fail in some sites?

5. **Conflict-tier UX — is it complete?** When config and memory disagree (lines 9, 87–96), the resolver returns `conflict` tier and the retrofit prose adds "(Note: config says <X>, memory says <Y> — resolve this conflict in your answer.)" The AskUserQuestion then needs to present both options. Is the UX for surfacing and resolving the conflict workable, or are there missing details (e.g., what if the user picks an option that matches neither config nor memory)?

---

## Ask

Critique this plan for what's wrong, missing, or fragile. Focus especially on the five questions above. For each finding, rate as Critical / Major / Minor with specific file:line citations. Apply "one reason this might be wrong" to your own findings before listing them.

Return findings as a structured list (not prose narrative).
