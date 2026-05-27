# TASKS — askuser-prefs-hook

Target: 10–20 tasks. Actual: 14.

---

## T001 [ ] — Extend `scripts/config.py` DEFAULTS and VALIDATORS with `[workflow]` section
- **Files:** scripts/config.py
- **Depends on:** —
- **Acceptance:**
  - `DEFAULTS["workflow"]` contains `audit_to_amend: "ask"` and `slug_confirm: "ask"`.
  - `VALIDATORS["workflow.audit_to_amend"] = {"ask","amend","stop"}`.
  - `VALIDATORS["workflow.slug_confirm"] = {"ask","auto_accept","recommend_derived"}`.
  - Env transliteration `Z_HARNESS_WORKFLOW_AUDIT_TO_AMEND` and `Z_HARNESS_WORKFLOW_SLUG_CONFIRM` work via existing `_dotted_to_env`.
- **DOCS:** config
- **Complexity:** low

## T002 [ ] — Add `QUESTION_IDS` registry + `RESULT_MAP` + startup guards to config.py
- **Files:** scripts/config.py
- **Depends on:** T001
- **Acceptance:**
  - `QUESTION_IDS` dict per SPEC §config.py registry (audit_to_amend + slug_confirm entries with full callsite list).
  - `RESULT_MAP` table maps `(question_id, choice) → "skip"|"prefill"|"ask"`.
  - Three startup guards run at module load: registry⊆validators, every `skill_default` non-null, every `RESULT_MAP` value ∈ `QUESTION_IDS[qid]["choices"]`. Each raises `SystemExit(2)` with descriptive message.
  - New subcommand `list-question-ids` (used by /z-suggest-memory validation) prints sorted JSON array of registered IDs to stdout.
- **DOCS:** config
- **Complexity:** medium

## T003 [ ] — Implement `resolve-question` subcommand: config layer
- **Files:** scripts/config.py
- **Depends on:** T002
- **Acceptance:**
  - `python3 scripts/config.py resolve-question <question_id>` returns JSON envelope `{result, default, source, rule_id, strength, reason, sources}` on stdout.
  - Validates `question_id` ∈ `QUESTION_IDS`; unknown → exit 3 with JSON error body.
  - Honors `Z_HARNESS_ASK_ALL=1` short-circuit returning result=ask, source=override.
  - Consults 4-layer config precedence. When config value ≠ default (`"ask"`), returns `RESULT_MAP[(qid, value)]` mapped result, tier=hard, source=config.
  - Stdout reserved for JSON only; all diag → stderr. Validated by piping output through `python3 -m json.tool`.
  - Exit codes: 0=ok, 2=bad invocation, 3=unknown question_id, 4=I/O error.
  - Emits `askuser_resolved` event per invocation (success path) with `{question_id, result, source, strength}`.
- **DOCS:** config, commands
- **Complexity:** medium

## T004 [ ] — Add memory consultation to `resolve-question` (JSON walk, not grep)
- **Files:** scripts/config.py
- **Depends on:** T003
- **Acceptance:**
  - Iterates `glob("docs/llm/*.json")`, filters `memories[]` for `type: "routing-preference"` matching `question_id`.
  - Honors `scope`: `"global"` always; `"project"` only when `Z_HARNESS_PROJECT_ROOT` (or `git rev-parse --show-toplevel`) matches entry's `project_root`.
  - One match → emit tier from memory's `strength`. Multiple agreeing matches → highest strength wins.
  - Multiple disagreeing matches → `conflict` tier; `sources[]` lists each with location.
  - Config-vs-memory disagreement → `conflict` tier; `sources[]` includes both.
  - Config-vs-memory agreement → config-source emitted, no conflict.
  - Malformed memory entry (missing required field) → log `routing_preference_malformed` event, treat as if absent.
- **DOCS:** config
- **Complexity:** medium

## T005 [ ] — Add `config.py set <key> <value> [--scope=global|project]` subcommand
- **Files:** scripts/config.py
- **Depends on:** T001
- **Acceptance:**
  - Validates `<key>` against `_KEY_RE` and `VALIDATORS[<key>]` before write.
  - Atomic write via tmp+rename to `~/.config/z-harness/config.toml` (`--scope=global`) or `.z-harness/config.toml` (`--scope=project`, default).
  - Preserves existing keys in the target TOML file (read-modify-write).
  - Invalid key or invalid value → exit 2 with stderr message.
- **DOCS:** config
- **Complexity:** low

## T006 [ ] — Extend `/z-suggest-memory` with `--kind routing-preference` flow
- **Files:** skills/z-suggest-memory/SKILL.md, commands/z-suggest-memory.md
- **Depends on:** T002 (QUESTION_IDS available)
- **Acceptance:**
  - New flag set: `--kind routing-preference`, `--question-id`, `--value`, `--strength`, `--scope`, optional `--reason`.
  - Validates `question_id` via subprocess to `python3 scripts/config.py list-question-ids`; rejects unknown.
  - Validates `strength` ∈ `{weak, strong, very_strong}`.
  - Writes memory to `docs/llm/workflow.json` (or per-slug for project scope: `docs/llm/workflow-<project-slug>.json`). Creates the file if missing with proper INDEX.json registration.
  - Memory entry shape: `{type: "routing-preference", question_id, value, scope, strength, reason, date, project_root: <abs path or null>}`.
  - Triggers MEMORIES-FLAT.md regeneration.
- **DOCS:** commands, review-agent
- **Complexity:** medium

## T007 [ ] — Add routing-flavored-text detection redirect in /z-suggest-memory Phase 3a
- **Files:** skills/z-suggest-memory/SKILL.md
- **Depends on:** T006
- **Acceptance:**
  - Phase 3a scans candidate text for patterns like `\b(always|usually|every time)\b.*\b(after|before|when)\b` (case-insensitive).
  - On match, surfaces one-shot AskUserQuestion: "This looks like a workflow preference. Write to `.z-harness/config.toml [workflow]` instead?" with options: yes-config / write-as-routing-preference / write-as-lesson-learned.
  - Detection-fail or detection-irrelevant → continue with original write path silently.
- **DOCS:** commands
- **Complexity:** low

## T008 [ ] — Retrofit `/z-audit-plan` and `/z-audit-plan-style` Phase 5 with resolver hook
- **Files:** commands/z-audit-plan.md, commands/z-audit-plan-style.md
- **Depends on:** T003, T004
- **Acceptance:**
  - At Phase 5 step 3 of each file, prepend the canonical retrofit bash block per SPEC §audit retrofit.
  - Branches on `$RESULT` for skip/prefill/ask. Skip path emits `askuser_skipped` event.
  - Conflict branch surfaces the conflict header text AND the post-answer write-back AskUserQuestion.
  - Error fallback (exit ≠ 0) always sends user to `ask`; never silently skips.
- **DOCS:** commands
- **Complexity:** medium

## T009 [ ] — Retrofit 7 slug-confirm sites with split safety+preference pattern
- **Files:** commands/z-plan.md, commands/z-fix.md, skills/z-debug/SKILL.md, skills/z-brainstorm/SKILL.md, skills/z-research/SKILL.md, skills/z-plan-light/SKILL.md, commands/z-uplift.md
- **Depends on:** T003, T004
- **Acceptance:**
  - Each site preserves the existing collision check as a hard prerequisite that runs UNCONDITIONALLY before the resolver call.
  - After collision check passes, the soft non-obvious-slug confirmation gate consults `workflow.slug_confirm` via the canonical retrofit pattern.
  - Skip path accepts the derived slug silently. Prefill pre-selects derived slug. Ask presents normally.
  - Each site explicitly spells out the split: collision check first (hard), then resolver (soft).
- **DOCS:** commands
- **Complexity:** medium

## T010 [ ] — Implement `scripts/propose-prefs.py` for command-pair pattern detection
- **Files:** scripts/propose-prefs.py (new)
- **Depends on:** T002
- **Acceptance:**
  - Reads `z-harness/metrics.jsonl` (last 30 runs by default).
  - Detects command-pair patterns: command A `run_end` followed by command B `run_start` within `Z_HARNESS_PROPOSE_WINDOW_S` seconds (default 3600), same slug, ≥ `Z_HARNESS_PROPOSE_THRESHOLD` times (default 3).
  - v1 watched patterns: `/z-audit-plan → /z-amend` and `/z-audit-plan-style → /z-amend` (both propose `workflow.audit_to_amend = "amend"`).
  - Pattern must show consistent user-pair behavior (same A→B every time within window).
  - `--check <command-name>` mode: invoked at end of A's run, returns JSON `{question_id, proposed_value, evidence: [{run, ts, ...}], scope_recommendation}` if threshold met; empty stdout otherwise.
  - Honors per-project suppression file `.z-harness/.propose-suppress` keyed by `(question_id)` with `expiry_ts`. 30-day default expiry on rejection.
  - Never auto-writes; only emits proposal JSON.
  - Any internal exception → exit 0, empty stdout, stderr log.
- **DOCS:** scripts
- **Complexity:** medium

## T011 [ ] — Wire elevation proposer into z-audit-plan, z-audit-plan-style, z-amend finalize
- **Files:** commands/z-audit-plan.md, commands/z-audit-plan-style.md, commands/z-amend.md
- **Depends on:** T010, T005, T006
- **Acceptance:**
  - At each command's Phase 9/finalize, invoke `python3 scripts/propose-prefs.py --check <command-name>`.
  - If stdout non-empty: parse JSON, surface one-shot AskUserQuestion: "You've done <pattern> N times — add as preference? (config / memory:very_strong / memory:strong / no)".
  - Accept-config branch calls `python3 scripts/config.py set workflow.audit_to_amend amend --scope=project` (or global per scope_recommendation).
  - Accept-memory branch dispatches `/z-suggest-memory --kind routing-preference --question-id <qid> --value <v> --strength <s>`.
  - No branch writes the suppression marker with 30-day expiry.
  - Emits `proposal_surfaced`, `proposal_accepted`, or `proposal_rejected` events.
- **DOCS:** commands
- **Complexity:** medium

## T012 [ ] — Add Phase 4c "Preference resolutions" to /z-stats
- **Files:** skills/z-stats/SKILL.md
- **Depends on:** T003
- **Acceptance:**
  - Phase 4c reads `askuser_resolved` events from `z-harness/metrics.jsonl`.
  - Aggregates by result (skip/prefill/ask), source (config/memory/conflict/none/override), question_id.
  - Reports conflict-rate as a proxy for user surprise.
  - Read-only; no writes.
  - Appears after Phase 4b in /z-stats output.
- **DOCS:** commands
- **Complexity:** low

## T013 [ ] — Update docs/llm/config.json + docs/human/config.md
- **Files:** docs/human/config.md, docs/llm/config.json
- **Depends on:** T001-T011 (all SPEC surfaces stable)
- **Acceptance:**
  - Document `[workflow]` section with both keys, valid values, env transliterations.
  - Document `resolve-question`, `set`, `list-question-ids` subcommands.
  - Document `routing-preference` memory type schema.
  - Document `Z_HARNESS_ASK_ALL`, `Z_HARNESS_EXPLAIN_RESOLUTION`, `Z_HARNESS_PROPOSE_WINDOW_S`, `Z_HARNESS_PROPOSE_THRESHOLD` env overrides.
  - Document v2 deferrals (multi-IDE export, halt-class bypass, stale-memory hygiene).
- **DOCS:** config
- **Complexity:** medium

## T014 [ ] — End-to-end smoke verification
- **Files:** (none — verification only)
- **Depends on:** T001-T013 shipped
- **Acceptance:**
  - Set `workflow.audit_to_amend = "amend"` in `.z-harness/config.toml`. Run `/z-audit-plan` on a real plan slug. Confirm Phase 5 emits `askuser_skipped` and proceeds as amend without prompting.
  - Conflict-tier test: set config="amend", write a routing-preference memory for same question_id with value="stop". Run `/z-audit-plan`. Confirm the conflict-header AskUser fires and the post-answer write-back AskUser appears.
  - Slug-confirm test: set `workflow.slug_confirm = "auto_accept"` and run `/z-plan "small test task"`. Confirm collision check still runs (try with a colliding slug — must prompt). Confirm non-colliding case skips the soft confirmation.
  - Proposer test: append 3 simulated `/z-audit-plan → /z-amend` pairs to a test metrics.jsonl. Run `scripts/propose-prefs.py --check z-audit-plan`. Confirm proposal returned.
  - Stdout discipline test: every resolve-question invocation pipes cleanly through `python3 -m json.tool`.
- **Complexity:** low
