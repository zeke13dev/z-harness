# SPEC — askuser-prefs-hook

Pre-AskUserQuestion preference resolver. Full 5-tier signal-strength model with memory consultation (Path X). Plus a human-in-the-loop elevation subsystem that observes repeated user behavior and proposes config/memory additions.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/askuser-prefs-hook/BRAINSTORM.md | 2026-05-27T20:40:00Z |
| RESEARCH.md | z-harness/askuser-prefs-hook/RESEARCH.md | 2026-05-27T21:10:00Z |

## Overview

Two coupled subsystems shipped together as v1:

1. **Resolver** — `python3 scripts/config.py resolve-question <question_id>` returns a typed JSON envelope `{result, default, source, rule_id, strength, reason, sources}`. Result is one of `skip|prefill|ask`. Consulted by every retrofitted AskUserQuestion site in skill prose, before the actual AskUserQuestion fires.

2. **Elevation proposer** — `python3 scripts/propose-prefs.py` walks `z-harness/metrics.jsonl`, detects repeated user-follow-up patterns (e.g. /z-amend invoked within 60min of /z-audit-plan finishing on the same slug, 3+ times), and at run-end of relevant commands surfaces a one-time AskUserQuestion: "You've done X→Y three times. Add as preference? (config / memory:very_strong / memory:strong / no)."

Both subsystems share the same `QUESTION_IDS` registry in `scripts/config.py`.

## File-by-file spec

### `scripts/config.py` — extended

#### New DEFAULTS section

```python
DEFAULTS: dict = {
    "schema_version": 1,
    "notify": { "level": "approval_only" },
    "docs":   { "always_apply": "always" },
    "workflow": {
        "audit_to_amend": "ask",      # ask | amend | stop
        "slug_confirm":   "ask",      # ask | skip | prefill
    },
}

VALIDATORS: dict = {
    "notify.level":            {"off", "approval_only", "all"},
    "docs.always_apply":       {"always", "never"},
    "workflow.audit_to_amend": {"ask", "amend", "stop"},
    "workflow.slug_confirm":   {"ask", "skip", "prefill"},
}
```

#### New `QUESTION_IDS` registry (single source of truth)

```python
QUESTION_IDS: dict[str, dict] = {
    "workflow.audit_to_amend": {
        "config_key": "workflow.audit_to_amend",
        # values are option-domain (what user picks at the AskUser site)
        "choices": {"ask", "amend", "stop"},
        # the "default option" the AskUser would have shown; used in `default` field of envelope
        "skill_default": "amend",
        "callsites": [
            "commands/z-audit-plan.md:183",
            "commands/z-audit-plan-style.md:384",
        ],
    },
    "workflow.slug_confirm": {
        "config_key": "workflow.slug_confirm",
        # AMENDED (Phase 7 Gemini CRIT #1): values are NOT the same words as resolver-result domain.
        # `auto_accept` means "always accept derived slug without asking" (resolves to result: skip).
        # `recommend_derived` means "show AskUser with derived slug pre-selected" (resolves to result: prefill).
        # `ask` means "always ask" (resolves to result: ask).
        "choices": {"ask", "auto_accept", "recommend_derived"},
        "skill_default": "yes_keep_derived",   # the option label the AskUser would present
        "callsites": [
            "commands/z-plan.md:21",
            "commands/z-fix.md:18",
            "skills/z-debug/SKILL.md:17",
            "skills/z-brainstorm/SKILL.md:19",
            "skills/z-research/SKILL.md:117",
            "skills/z-plan-light/SKILL.md:19",
            "commands/z-uplift.md:71",
        ],
        # Hard prerequisite: even when resolver returns skip, the slug-COLLISION check runs unconditionally.
        # Collision check is in skill prose; the resolver only governs the soft non-obvious-slug confirmation.
        "safety_check_runs_unconditionally": True,
    },
}

# Map each question_id's option-domain value → resolver result-domain
RESULT_MAP: dict[tuple[str, str], str] = {
    ("workflow.audit_to_amend", "ask"):    "ask",
    ("workflow.audit_to_amend", "amend"):  "skip",   # user wants auto-amend → skip the prompt
    ("workflow.audit_to_amend", "stop"):   "skip",   # user wants auto-stop → also skip the prompt
    ("workflow.slug_confirm", "ask"):                "ask",
    ("workflow.slug_confirm", "auto_accept"):        "skip",
    ("workflow.slug_confirm", "recommend_derived"):  "prefill",
}
```

Startup guards (all run at config.py module load):
- `assert set(QUESTION_IDS) <= set(VALIDATORS)` — registry/validator consistency
- `for qid, meta in QUESTION_IDS.items(): assert meta["skill_default"] is not None` — every question_id has a presentation default
- `for (qid, v) in RESULT_MAP: assert v in QUESTION_IDS[qid]["choices"]` — Codex CRIT #2 fix: every result-mappable value is a valid choice

Raises `SystemExit(2)` with clear message if any violated.

#### New subcommand `resolve-question <question_id> [--scope-slug <slug>] [--explain]`

Behavior:
1. Validate `question_id` ∈ `QUESTION_IDS`. Unknown → exit 3 with JSON `{"error": "unknown_question_id", "known": [...]}`.
2. Honor `Z_HARNESS_ASK_ALL=1` env: short-circuit return `{"result": "ask", "source": "override", "rule_id": "Z_HARNESS_ASK_ALL", ...}`.
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
11. Map tier + source-value → result (AMENDED Phase 7 Gemini CRIT #1):
    - **When `source == config` (tier always `hard`):** result is `RESULT_MAP[(question_id, config_value)]`. Direct table lookup. The config value carries semantic meaning specific to the question_id, not generic skip/prefill.
    - **When `source == memory`:** result is derived from strength + safety:
      - `very_strong` AND question_id is NOT safety-sensitive → `skip`
      - `very_strong` AND question_id IS safety-sensitive (e.g. workflow.slug_confirm, where collision check still runs) → `skip` (resolver answer; safety check is separate gate)
      - `strong` → `prefill`
      - `weak` → `prefill`
    - **When `source == conflict`:** `ask` (always). The `sources` field lists both disagreeing entries.
    - **When `source == none`:** `ask`.
    - **When `source == override` (Z_HARNESS_ASK_ALL=1):** `ask`.

JSON envelope shape (stdout, exit 0):
```json
{
  "result":   "skip|prefill|ask",
  "default":  "<option-label-from-skill_default>",
  "source":   "config|memory|conflict|none|override",
  "rule_id":  "workflow.audit_to_amend",
  "strength": "hard|very_strong|strong|weak|none",
  "reason":   "<one-line human-readable>",
  "sources":  [{"kind": "config|memory", "value": "<v>", "location": "<path>", "strength": "<t>"}]
}
```

`stdout` reserved for JSON. All log/diag lines route to `stderr`. Test gate: `python3 -m json.tool` on every output succeeds.

Exit codes:
- 0 — valid JSON returned
- 2 — bad invocation (missing question_id arg)
- 3 — unknown question_id (JSON still emitted with `error` key)
- 4 — I/O error reading config or memory (JSON still emitted)

Always emit `askuser_resolved` event after successful resolution:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" askuser_resolved \
  "$(printf '{"question_id":"%s","result":"%s","source":"%s","strength":"%s"}' \
     "$question_id" "$result" "$source" "$strength")"
```

Optional `--explain`: prefix stderr with a human-readable "Here's how I resolved this" block. Default off; opt-in via flag OR `Z_HARNESS_EXPLAIN_RESOLUTION=1`.

### `scripts/propose-prefs.py` — new

Walk `z-harness/metrics.jsonl` for the last N (default 30) `run_start` events. Detect patterns of the shape "command A finished within T seconds of command B starting, same slug". Configurable via env:
- `Z_HARNESS_PROPOSE_WINDOW_S=3600` — max gap between command A end and B start
- `Z_HARNESS_PROPOSE_THRESHOLD=3` — min repetitions to propose

For v1, watched patterns are hardcoded:
- `/z-audit-plan → /z-amend` → propose `workflow.audit_to_amend = "amend"`
- `/z-audit-plan-style → /z-amend` → propose `workflow.audit_to_amend = "amend"` (same key)

**AMENDED (Phase 7 Gemini CRIT #2):** The `/z-fix → slug-derive-confirm answered yes` pattern was REMOVED from v1 watched patterns because `metrics.jsonl` does not record AskUserQuestion responses today. The proposer in v1 only watches command-pair patterns (which ARE in metrics.jsonl as `run_start` / `phase_end` events for distinct commands). Users can still manually set `workflow.slug_confirm` via `config.py set` or via `/z-suggest-memory --kind routing-preference`; it just won't be auto-proposed. Adding AskUser-response telemetry is a v2 prerequisite for auto-proposing slug-confirm.

Invocation: `python3 scripts/propose-prefs.py --check <command-name>` at end of /z-audit-plan, /z-audit-plan-style, /z-amend Phase 9, and any command whose finalize is "high-frequency follow-up source." Returns:
- exit 0, stdout empty → no proposal threshold met
- exit 0, stdout JSON `{"question_id": "...", "proposed_value": "...", "evidence": [...], "scope_recommendation": "global|project"}` → caller surfaces a one-shot AskUserQuestion (skill prose)

The proposer never writes anything — proposal AskUserQuestion is in the calling skill's prose. User picks:
- Accept as config → caller calls `python3 scripts/config.py set workflow.audit_to_amend amend [--scope=global|project]`
- Accept as memory:very_strong → caller dispatches `/z-suggest-memory --kind routing-preference --question-id workflow.audit_to_amend --value amend --strength very_strong --scope project`
- Accept as memory:strong → same, strength=strong
- No → record `propose_rejected` event with question_id; suppress this proposal for the next 30 days (via marker file `~/.config/z-harness/.propose-suppress` keyed `<question_id>:<expiry-ts>`)

Dedup: a single proposal fires at most once per command-run. Per-question_id suppression is honored as long as the marker file says so.

**Suppression scope (AMENDED Phase 7 Codex MAJOR #4):** Suppression marker is keyed by `(project_root, question_id)`, not just `question_id`. Storage at `~/.config/z-harness/.propose-suppress` as JSON `{"<project_root>": {"<question_id>": "<expiry-ts>"}}` or as a per-project marker file in `.z-harness/.propose-suppress`. The latter is simpler and avoids the cross-repo bleed Codex flagged.

### `scripts/config.py set <key> <value> [--scope=global|project]` — new subcommand

Atomically writes a TOML key to `~/.config/z-harness/config.toml` (global) or `.z-harness/config.toml` (project, default). Tmp+rename. Validates against `VALIDATORS[<key>]` before writing; exit 2 with clear message if invalid.

### `skills/z-suggest-memory/SKILL.md` — extended

- **Phase 3a detection (D4):** scan candidate text for routing-flavored patterns (`always X after Y`, `usually X`, `every time X`). If matched and the candidate has no explicit `type`, surface one-shot AskUserQuestion:
  - "This looks like a workflow preference. Write to `.z-harness/config.toml` `[workflow]` instead?" (Yes / Write as routing-preference memory / Write as lesson-learned anyway)
- **New `--kind routing-preference` flow:** when invoked with this flag plus `--question-id`, `--value`, `--strength`, `--scope`, write a memory entry with `type: "routing-preference"` to the appropriate `docs/llm/<slug>.json` (slug = "workflow" by convention; create if not exists). Validate `question_id ∈ QUESTION_IDS` (via subprocess to `config.py list-question-ids`) and `strength ∈ {weak, strong, very_strong}`.

### `commands/z-audit-plan.md` and `commands/z-audit-plan-style.md` — retrofit (preference-only, no safety bypass concern)

At Phase 5 step 3 (the existing `AskUserQuestion`), prepend the canonical retrofit pattern (AMENDED Phase 7 Gemini MAJOR #4 + Codex MAJOR #3 to fix bash error swallowing):

```markdown
Before invoking AskUserQuestion, run:
```bash
# Capture exit code separately — do NOT silence stderr
RESOLVED="$(python3 scripts/config.py resolve-question workflow.audit_to_amend)"
RESOLVE_EXIT=$?

if [[ $RESOLVE_EXIT -ne 0 ]]; then
  # Exit codes: 2=bad invocation, 3=unknown question_id, 4=I/O error.
  # In all error cases, fall through to ask the user normally — never silently skip.
  echo "resolve-question failed (exit $RESOLVE_EXIT); falling back to ask" >&2
  RESULT="ask"; DEFAULT=""; SOURCE="error"
else
  RESULT="$(echo "$RESOLVED" | jq -r .result)"
  DEFAULT="$(echo "$RESOLVED" | jq -r .default)"
  SOURCE="$(echo "$RESOLVED" | jq -r .source)"
fi
```

Branch on `$RESULT`:
- `skip`: skip the AskUserQuestion and proceed as if the user picked `$DEFAULT`. Emit `askuser_skipped` event with `{question_id, source}`.
- `prefill`: present the AskUserQuestion normally, pre-select `$DEFAULT` as the recommended option (label suffix: ` (Recommended — your preference)`).
- `ask`: present the AskUserQuestion normally. **If `$SOURCE == "conflict"`** (AMENDED Phase 7 Gemini MAJOR #5): add to the question header text: `(Note: config says <X>, memory says <Y> — your answer below will be offered as a conflict-resolution write target.)` After the user picks an answer, IF that answer differs from BOTH config and memory values, surface a one-shot follow-up AskUserQuestion: "Record your answer as the new preference? (config / memory:very_strong / memory:strong / no — keep both stored, ask again next time)". Caller writes to config or dispatches /z-suggest-memory accordingly. This prevents the conflict from re-appearing on every subsequent run.
```

At Phase 9 (finalize), add an elevation-proposal step:
```bash
PROP="$(python3 scripts/propose-prefs.py --check z-audit-plan 2>/dev/null)"
[[ -n "$PROP" ]] && # surface one-shot AskUserQuestion per the spec above
```

### Slug-confirm retrofit (AMENDED Phase 7 Gemini CRIT #3 — different from audit-amend pattern)

Sites: `commands/z-plan.md:21`, `commands/z-fix.md:18`, `skills/z-debug/SKILL.md:17`, `skills/z-brainstorm/SKILL.md:19`, `skills/z-research/SKILL.md:117`, `skills/z-plan-light/SKILL.md:19`, `commands/z-uplift.md:71`.

Slug-confirm sites mix TWO concerns that the prior retrofit conflated. Split them explicitly:

1. **Collision check (UNCHANGED — always runs FIRST, never bypassed):** the existing `ls z-harness/` (or `ls z-harness/plans/` per scripts/plan-path.sh canonical layout) check that detects a finished-plan slug-dir collision. If collision found, AskUserQuestion fires UNCONDITIONALLY to confirm or pick a different slug. The resolver is NOT consulted at this gate.

2. **Soft non-obvious-slug confirmation (RETROFITTED):** the secondary "if the auto-derived slug is non-obvious, confirm via AskUserQuestion" gate. This is the routing-class preference site. Apply the canonical retrofit with `question_id = workflow.slug_confirm`:

```bash
# Only reaches this point if collision check has already passed.
RESOLVED="$(python3 scripts/config.py resolve-question workflow.slug_confirm)"
RESOLVE_EXIT=$?
# ... (same error-handling pattern as audit retrofit) ...
```

Branch on `$RESULT`:
- `skip`: accept the derived slug silently. Emit `askuser_skipped`.
- `prefill`: present the AskUser with derived slug pre-selected.
- `ask`: present normally; conflict-write-back logic same as audit retrofit.

**Invariant (spelled out in skill prose):** the safety/collision check is a separate hard prerequisite that runs unconditionally regardless of resolver outcome.

### `skills/z-stats/SKILL.md` — Phase 4c (new)

After existing Phase 4b (memory-review terminal states), add Phase 4c:

```markdown
### Memory-driven preference resolutions (last 10 runs)

Read `askuser_resolved` events from metrics.jsonl. Aggregate:
- Total resolutions
- By result: skip / prefill / ask
- By source: config / memory / conflict / none / override
- By question_id (most-fired prefs)
- Conflict rate (a proxy for user surprise; should trend down as users clean up TOML)

Output table; read-only.
```

### `docs/human/config.md` and `docs/llm/config.json` — update (D12)

Document the `[workflow]` section, the `Z_HARNESS_ASK_ALL` override, the `resolve-question` subcommand, the `set` subcommand. Also document the `routing-preference` memory type schema. Note that this concept covers config — separate concept (or section in commands/skills) covers the elevation-proposer.

## Invariants

- **Stdout discipline (D1↔D5).** `config.py resolve-question` writes JSON only on stdout. All diagnostics on stderr. Validated by a test that pipes output through `python3 -m json.tool`.
- **Single QUESTION_IDS registry (D2↔D3).** One source of truth in `config.py`. Validated at startup: `assert set(QUESTION_IDS) <= set(VALIDATORS)`. /z-suggest-memory checks `question_id` against this registry via subprocess.
- **Safety checks survive skip (D7↔collision).** Slug-collision check is a hard prerequisite enforced in skill prose, independent of resolver outcome. SPEC retrofit prose makes this explicit.
- **Resolver is read-only.** Never writes to config or memory. All writes go through `config.py set` or `/z-suggest-memory`.
- **Proposer never auto-writes.** Threshold-reached → AskUserQuestion → user picks → caller does the write. Suppression is honored.
- **Conflict tier always asks.** No silent override. `sources[]` always populated. User sees both.
- **/z-suggest-memory routing-preference detection is non-blocking.** Detection-fail = continue with original write path.
- **Resolver is Claude-Code-only.** Multi-IDE export (Cursor/Codex/agy) does NOT carry the precheck. SPEC notes this; v2 concern.

## Edge cases

- **No memory JSONs exist yet.** Resolver returns `none` if config is also `ask` default. Common at fresh repo.
- **Stale `Z_HARNESS_PROJECT_ROOT`.** If unset, resolver falls back to `git rev-parse --show-toplevel`. If both fail (running outside a git repo), resolver treats all memories as `scope: "global"` matches.
- **Memory entry missing required fields.** Resolver logs `routing_preference_malformed` event with the slug/index, treats as if memory does not exist. Doesn't crash.
- **`config.py set` race.** Atomic via tmp+rename. Concurrent invocations: last-write-wins (acceptable for human-interactive use).
- **Proposer false positives.** User runs `/z-audit-plan → /z-amend` 3 times but each was for different slugs. The proposer must group by command-pair AND require user choice was consistent (e.g. always "amend", never "stop"). Configurable in v1 logic.
- **Cycle: proposer fires AskUserQuestion, user accepts, the very next /z-audit-plan run's resolver fires `skip`.** This is the desired loop. Telemetry should see the `askuser_resolved {source: config}` events immediately after.
- **`Z_HARNESS_ASK_ALL=1` set globally.** Resolver always returns ask. Use case: debugging or user wants temporary control.

## Error handling

- Resolver: any internal exception → exit 4, JSON `{error: "internal", message: "<str>"}`, stderr stack trace.
- Proposer: any exception → exit 0, empty stdout, stderr log. Never blocks the calling command.
- /z-suggest-memory write of routing-preference: validate question_id and strength before write; invalid → bad_input.

## Known v2 hygiene items (deferred but documented)

These were surfaced in Phase 7 review and are real, but not blocking v1:

- **Stale-memory hygiene after config supersedes it (Codex CRIT #1).** When a routing-preference memory exists and the user later writes the same question_id to config, the memory entry continues to be consulted in `conflict` cases. v1 emits a `memory_potentially_superseded` warning event in this case; v2 will add a cleanup prompt or auto-archive.
- **config.py set lacks `--dry-run` / rollback (Codex MAJOR #5).** v2: add `--dry-run` flag, `--backup` to write the prior config to `.toml.bak` before overwrite.
- **Async memory-write gap (Codex MAJOR #6).** v1: when proposer accepts memory write, the `askuser_resolved` source field reads "memory" even if /z-suggest-memory dispatch fails. v2: introduce `propose_accepted` event logged only after /z-suggest-memory returns 0, and let `askuser_resolved` reflect actual outcome.
- **Tier-naming asymmetry (Codex MINOR #7).** Config always reports `hard` while memory reports `weak|strong|very_strong`. Cosmetic — `source` field disambiguates.
- **routing-preference memory schema_version (Codex MINOR #8).** v2: add `schema_version: 1` to memory entries so future migrations can detect old shapes.

## Non-goals (explicit deferrals)

- `/z-amend` slug-discovery auto-pinning when invoked after audit (separate plumbing concern; the resolver-hook is enough for the user's named complaint).
- Halt-class bypass (spec_problem, decision_needed): out of v1 — too risky.
- Multi-IDE-export precheck integration: Cursor/Codex/agy fall back to raw AskUserQuestion. v2.
- Retrofitting all 30 distinct AskUserQuestion patterns. v1 covers exactly the 2 patterns (audit→amend + slug-confirm).
- Memory-strength inference from text. Always explicit `strength` field.
- Mid-run config changes. Resolver reads config at invocation; doesn't re-read.
