---
artifact: brainstorm
slug: askuser-prefs-hook
generated_at: 2026-05-27T20:42:00Z
command: /z-brainstorm askuser-prefs-hook
input_hash: 381e0cbdd6e2a1ce
depends_on: []
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: codex
---

## Framing: claude

### Framing

The core friction is that `AskUserQuestion` is a synchronous decision gate, but most of the questions it asks have already been answered implicitly through behavioral patterns. The problem isn't "how do we store preferences" — it's that the harness treats every decision as novel when most are habitual. A pre-hook should function as a *preference resolver* that transforms the question "should we proceed?" into the answer "yes, proceeding (per your standing preference)" or falls back to asking only when no signal exists or the signal is ambiguous. The distinction between config and memory is fundamental: config expresses *invariant policy* (you always want X), memory expresses *statistical tendency* (you usually want X). These require different resolution logic and different UX.

### Core hypothesis

The correct architecture is **two distinct storage locations with a single resolution point**: (a) a new `[workflow]` TOML stanza for invariant policy (e.g., `workflow.after_audit = "amend"`) that lives in `.z-harness/config.toml` (per-project) or `~/.config/z-harness/config.toml` (global), and (b) the existing memories infrastructure left unchanged for soft signals. The pre-hook at each `AskUserQuestion` site checks config first (deterministic skip if policy matches), then checks memories for soft-confidence scoring, then falls back to the prompt with a pre-filled default if a memory signal exceeds a threshold (say, 2+ matching memories of type `workflow-preference` tagged for the context). Config and memory play different roles and should never be conflated. The audit→amend case specifically belongs in TOML config, not memory, because it's a deterministic preference, not a probabilistic one.

### Risks

- **Silent action drift**: if the hook silently acts on stale config (e.g., `after_audit = "amend"` but the plan has changed structure), the user loses a chance to reconsider. Mitigation: config-driven skips should still print a one-line "Skipping confirmation: proceeding to /z-amend per workflow.after_audit config" message — never truly silent.
- **Config sprawl**: adding workflow keys for every `AskUserQuestion` site produces a sprawling TOML schema. Mitigation: only expose config keys for the highest-frequency decisions (audit→amend, implement-all auto-confirm, review-all auto-apply). The long tail stays as memories.
- **Memory as cargo cult**: if users can't distinguish "this is config" from "this is memory," they'll try to use `/z-suggest-memory` to set hard preferences, and the system won't honor them deterministically. Mitigation: `docs/human/config.md` must explicitly contrast the two.
- **Hook coupling**: injecting preference-resolution before every `AskUserQuestion` call risks introducing bugs or latency in the critical decision path. Mitigation: the hook must be a single no-I/O function (reads from already-exported env vars, no file reads at decision time).

### Plan implications

- Add a `[workflow]` section to the config schema with typed keys per command (e.g., `workflow.after_audit`, `workflow.confirm_implement`). Values: `"ask"` (default), `"skip"`, `"amend"`, `"apply"`, etc.
- Extend `scripts/config.py` to export these keys at Setup time.
- Add a `resolve-question` helper (bash function or Python one-liner) that checks the exported env var for a given decision point and returns `skip|prefill|ask`.
- At each `AskUserQuestion` site, prepend the helper check. If it returns `skip`, log an event (`askuser_skipped`) and proceed. If `prefill`, pass the default option. If `ask`, invoke normally.
- The memories-based soft-confidence path is a v2 concern — v1 is purely config-driven because it's simpler, auditable, and doesn't require probabilistic scoring logic.

### What would change my mind

- If the user wants preferences that vary *by plan* (e.g., "amend after audit on feature branches but not on hotfix branches"), TOML config can't express this — memories or a richer rule DSL would be needed.
- If empirical usage shows that users set `workflow.after_audit = "amend"` in global config but frequently override it per-project, the per-project/global distinction alone is insufficient and we'd need an override-with-confirmation mode.
- If the number of distinct `AskUserQuestion` sites requiring preference resolution is >15, the per-key TOML approach becomes unmanageable and a more declarative schema (e.g., a `[question-defaults]` table keyed by question-id string) would be better.

---

## Framing: codex

### Framing

This is not primarily a memory problem. It is an intent-resolution problem before expensive or annoying human interruption.

Treat `AskUserQuestion` as the last step in a decision pipeline:

`explicit command/context -> deterministic config -> strong preference memory -> weak/default suggestion -> ask user`

The key distinction is between **policy** and **preference**. TOML config is policy: stable, auditable, exact. Memories are preference signals: narrative, probabilistic, user-authored, and context-sensitive.

"I almost always amend after audit" is a preference signal unless the user encodes it as policy.

### Core hypothesis

Use both, but with different authority.

TOML should hold deterministic behavior:

```toml
[audit]
after_audit = "ask" # ask | amend | stop
```

Memories should hold learned or declared tendencies:

```json
{
  "text": "User almost always runs /z-amend after /z-audit-plan.",
  "tags": ["workflow", "audit", "amend", "preference"]
}
```

Scope should be two-level: Global memory/config answers "how this user usually works." Project memory/config answers "how this repo wants to work." Resolution order mirrors existing config layering, but with separate authority: `built-in defaults -> global config -> project config -> env`, then preference augmentation: `project memory -> global memory -> ask`.

A hook should live immediately before every `AskUserQuestion` call, but it should receive a typed question payload, not raw prose. Example:

```json
{
  "kind": "post_audit_next_step",
  "choices": ["amend", "stop", "ask"],
  "default": "ask",
  "context": {"slug": "...", "artifact": "PLAN_AUDIT_REPORT.md"}
}
```

### Risks

- Memory can become spooky if it silently skips prompts from vague statements. "Almost always" should not equal "always."
- TOML can become too rigid if every workflow preference becomes a first-class key.
- Per-project memory can rot if copied between repos or generated from stale behavior.
- Global memory can over-apply to repos with different conventions.
- A generic pre-hook can become an invisible policy engine unless every skip is logged.
- Retrofitting direct `AskUserQuestion` calls may be brittle unless the hook is centralized behind a wrapper.
- Weak signals are dangerous for irreversible or high-blast-radius choices, even if the user usually picks the same answer.
- "Skip prompt" and "prefill default" need different thresholds; collapsing them will make the system feel either timid or presumptuous.

### Plan implications

Add a typed question resolver rather than editing every skill ad hoc:

```
ResolveQuestionPreference(question_payload) -> resolved | defaulted | ask
```

Signal strength tiers:
- `hard`: config/env says what to do; skip prompt unless destructive.
- `strong`: repeated or user-authored memory with matching tags and no conflict; default the choice, usually still surface.
- `very_strong`: explicit memory phrase like "always do X after Y" plus low-risk action; skip prompt.
- `weak`: one-off memory, vague wording, or broad context match; ask with prefilled default.
- `conflict`: project and global disagree, or memory and config disagree; ask and show source.

For the audit-amend bridge specifically: after `/z-audit-plan` writes `PLAN_AUDIT_REPORT.md`, emit a typed `post_audit_next_step` question. If project config says `audit.after_audit = "amend"`, run or hand off to `/z-amend` without asking. If memory says "almost always amend after audit," present `/z-amend` as the default. Always log the resolution source into the run archive.

### What would change my mind

- If users frequently want memories to be editable by hand, then TOML or a separate human-readable preferences file becomes more important.
- If most prompt skips are workflow automation rather than personal preference, config should dominate and memories should only suggest defaults.
- If memory retrieval cannot reliably distinguish "audit then amend" from unrelated amendment behavior, it should never skip, only prefill.
- If `/z-amend` itself still asks slug-discovery questions, the better first fix may be passing audit context directly into `/z-amend` rather than building a broad preference hook.
- If users find silent automation unsettling, the threshold should shift: memories may default answers, but only config may skip prompts.
- If many skills use `AskUserQuestion` for semantically different decisions, the hook must be opt-in by question kind, not globally automatic.

---

## Framing: gemini

### Framing

The system currently lacks a mechanism to bridge recurring human workflow patterns with the rigid, explicit prompt architecture of `AskUserQuestion`. When a user establishes a strong procedural habit — such as immediately invoking `/z-amend` following `/z-audit-plan` — they are penalized with repetitive manual invocation and context-gathering prompts. The challenge is introducing a system that can bypass these gates using stored preferences without creating "magic" state that obscures control flow or executes risky actions based on poorly understood signals.

### Core hypothesis

Routing decisions and control-flow overrides must be deterministic and should therefore live exclusively in the 4-layer TOML configuration (e.g., `flow.auto_amend_after_audit = true`), NOT in unstructured LLM memories. The TOML config provides rigid scoping (global vs. per-project), explicit human readability, and clear overriding rules. We introduce a `preference_precheck` hook executed immediately prior to `AskUserQuestion`. If the configuration yields an explicit override for the target decision, the prompt is skipped and the configured route is taken. Unstructured memories (`MEMORIES-FLAT.md`) remain strictly for qualitative domain context and code-generation guidance, isolating routing logic from probabilistic interpretation.

### Risks

- **Automation Oaths:** Bypassing prompts based on global config might cause the system to take sweeping, unwanted actions in a new project if the user forgets they set a global override (e.g., auto-amending destructive audit changes).
- **Configuration Sprawl:** Creating a distinct TOML key for every possible branch or prompt will bloat the schema and overwhelm the user.
- **Memory/Config Confusion:** Users will naturally try to teach the system their routing preferences via `/z-suggest-memory`. If the system ignores these memories for routing because it relies solely on TOML, the user will perceive the system as "forgetting" or ignoring their instructions.
- **Binary Rigidity:** TOML configuration is largely binary or categorical. It cannot handle nuanced preferences (e.g., "always amend after audit, *unless* the audit touches the database schema").

### Plan implications

- Extend the TOML configuration schema (`scripts/config.py`) to include a `[flow]` or `[prompts]` section.
- Implement a `resolve_prompt_preference(context_key)` function that evaluates the 4-layer config state.
- Refactor the caller sites of `AskUserQuestion` across relevant skills (like `z-audit-plan` and `z-audit-plan-style`) to inject this pre-hook. If the pre-hook returns a definitive route, the skill autonomously triggers the follow-up execution (e.g., chaining directly into `z-amend`).
- Add terminal output when a prompt is bypassed (e.g., `[Config: flow.auto_amend=true] Skipping prompt and proceeding to /z-amend...`) to maintain transparency.
- Update `/z-suggest-memory` logic or documentation to detect when a user is trying to store a routing preference and redirect them to update their `config.toml`.

### What would change my mind

If user research shows that routing preferences are overwhelmingly conditional rather than absolute (e.g., "Skip the binding prompt *if* I'm working in the `scripts/` directory, but ask me otherwise"), the rigid TOML approach will fail. In that scenario, I would pivot to a hybrid model: using a fast, low-parameter LLM call as the pre-hook to evaluate the current context against the `MEMORIES-FLAT.md` file. If the LLM determines a stored memory provides a >95% confidence signal for a specific route based on the current context, it skips the prompt; otherwise, it degrades to `AskUserQuestion`.

---

## Anti-bias check

Section-by-section comparison:

### (1) Framing

All three ideators identify the same root problem: `AskUserQuestion` is a synchronous gate that fires for habitual decisions. The framings differ in emphasis:

- **Claude** frames it as a policy/tendency distinction requiring different storage and resolution logic.
- **Codex** frames it as a decision pipeline with explicit tier ordering (command → config → memory → ask). This is the most actionable framing for implementation.
- **Gemini** frames it as a "magic state" safety problem — the risk of opaque automation — which is valid but reactive.

**Pick: Codex wins on Framing.** The pipeline model (`explicit context -> config -> memory -> ask`) is a concrete, implementable mental model that neither Claude nor Gemini produced with the same precision. Claude's framing is close but less structured. Gemini's framing focuses on the risk rather than the mechanism.

### (2) Core hypothesis

- **Claude** argues for a `[workflow]` TOML stanza + memories left unchanged, with config checked first. V1 config-only, memories deferred to v2.
- **Codex** argues for both with a typed question payload (`kind`, `choices`, `default`, `context`) as the interface. This is the only ideator to introduce a *typed* question protocol — avoiding raw prose matching.
- **Gemini** argues for TOML-only (no memory routing at all), keeping memories for qualitative context only.

**Pick: Codex wins on Core hypothesis.** The typed question payload is the key insight that neither Claude nor Gemini produced. Without it, the pre-hook must do string-matching on question text, which is fragile. Gemini's TOML-only position is defensible but creates the Memory/Config Confusion risk it correctly identifies — users will inevitably try to store routing preferences in memory, and the system will silently ignore them.

*Justification for not picking Claude here:* Claude's hypothesis is structurally similar to Codex's but lacks the typed question payload. The v1/v2 split (config-only first) is practical but may be a false economy if the typed question architecture requires the same refactoring whether or not memory tier is activated.

### (3) Risks

- **Claude** surfaces 4 risks. Notable: "Memory as cargo cult" (users will try `/z-suggest-memory` for hard preferences) and "Hook coupling" (latency/bugs in the decision path).
- **Codex** surfaces 8 risks. Most comprehensive. Notable additions: "Skip vs prefill need different thresholds" and "per-project memory can rot if copied between repos."
- **Gemini** surfaces 4 risks. Notable: "Memory/Config Confusion" (same as Claude's cargo cult risk but more precisely named) and "Binary Rigidity" (TOML can't express conditional preferences).

**Pick: Codex wins on Risks.** Codex has the most complete risk enumeration. The "different thresholds for skip vs prefill" risk is uniquely important and not captured by either Claude or Gemini. Gemini's "Binary Rigidity" risk is a genuine counter-argument to its own hypothesis and worth preserving.

### (4) Plan implications

- **Claude** proposes a `[workflow]` section with per-command typed values, a `resolve-question` bash helper, and `askuser_skipped` log events. Clean and implementable.
- **Codex** proposes a typed `ResolveQuestionPreference()` function with explicit signal-strength tiers (`hard|strong|very_strong|weak|conflict`). More complete but heavier.
- **Gemini** proposes a `[flow]` or `[prompts]` TOML section + a `resolve_prompt_preference(context_key)` function + terminal transparency output + updating `/z-suggest-memory` to redirect routing-preference attempts. The suggestion to update `/z-suggest-memory` to redirect users to config is a unique and valuable operational detail.

**Pick: Codex wins on Plan implications overall, but Gemini contributes one unique detail.** Codex's signal-strength tiers (`hard|strong|very_strong|weak|conflict`) give the resolver a precise contract. Gemini's suggestion to update `/z-suggest-memory` to detect routing-preference entries and redirect to config is the only plan implication that addresses the feedback loop — without it, the Memory/Config Confusion risk has no mitigation.

*Justification for not picking Claude here:* Claude's plan is sound but is a strict subset of Codex's. The signal-strength taxonomy is the differentiator.

### (5) What would change my mind

- **Claude**: branch-specific preferences (feature vs hotfix); >15 distinct sites → needs table-keyed schema.
- **Codex**: if `/z-amend` still asks slug-discovery questions, fix that first before building the hook; if memories can't distinguish context reliably, never skip, only prefill.
- **Gemini**: if preferences are overwhelmingly conditional rather than absolute, pivot to a fast LLM evaluator against MEMORIES-FLAT.md with a >95% confidence threshold.

**Pick: Codex wins on "What would change my mind."** The observation that if `/z-amend` still has slug-discovery friction, the real fix is context-passing rather than a preference hook — this is the sharpest practical challenge to the entire premise. Claude's ">15 sites needs a table" point is also valuable and not redundant with Codex.

---

**Summary of anti-bias analysis:** Codex wins 5/5 sections. This was not driven by LLM-vendor affinity — the Codex output is structurally superior on two concrete dimensions: (1) the typed question payload concept (`kind`, `choices`, `default`, `context`) which solves the fragile string-matching problem, and (2) the signal-strength taxonomy (`hard|strong|very_strong|weak|conflict`) which gives the resolver a precise contract. Gemini contributes one unique operationally-valuable point (updating `/z-suggest-memory` to redirect routing preferences). Claude's framing is solid but largely overlaps with Codex.

## Orchestrator recommendation

**Pick Codex framing** — it provides the cleanest architectural model (typed question payload + signal-strength tiers) and its "What would change my mind" section contains the most important practical challenge to validate before building: confirm whether `/z-amend` slug-discovery friction is the real bottleneck, which may make the whole hook secondary to fixing context-passing.


## User choice

**Chosen framing:** codex

## Framing: codex

### Framing

This is not primarily a memory problem. It is an intent-resolution problem before expensive or annoying human interruption.

Treat `AskUserQuestion` as the last step in a decision pipeline:

`explicit command/context -> deterministic config -> strong preference memory -> weak/default suggestion -> ask user`

The key distinction is between **policy** and **preference**. TOML config is policy: stable, auditable, exact. Memories are preference signals: narrative, probabilistic, user-authored, and context-sensitive.

"I almost always amend after audit" is a preference signal unless the user encodes it as policy.

### Core hypothesis

Use both, but with different authority.

TOML should hold deterministic behavior:

```toml
[audit]
after_audit = "ask" # ask | amend | stop
```

Memories should hold learned or declared tendencies:

```json
{
  "text": "User almost always runs /z-amend after /z-audit-plan.",
  "tags": ["workflow", "audit", "amend", "preference"]
}
```

Scope should be two-level: Global memory/config answers "how this user usually works." Project memory/config answers "how this repo wants to work." Resolution order mirrors existing config layering, but with separate authority: `built-in defaults -> global config -> project config -> env`, then preference augmentation: `project memory -> global memory -> ask`.

A hook should live immediately before every `AskUserQuestion` call, but it should receive a typed question payload, not raw prose. Example:

```json
{
  "kind": "post_audit_next_step",
  "choices": ["amend", "stop", "ask"],
  "default": "ask",
  "context": {"slug": "...", "artifact": "PLAN_AUDIT_REPORT.md"}
}
```

### Risks

- Memory can become spooky if it silently skips prompts from vague statements. "Almost always" should not equal "always."
- TOML can become too rigid if every workflow preference becomes a first-class key.
- Per-project memory can rot if copied between repos or generated from stale behavior.
- Global memory can over-apply to repos with different conventions.
- A generic pre-hook can become an invisible policy engine unless every skip is logged.
- Retrofitting direct `AskUserQuestion` calls may be brittle unless the hook is centralized behind a wrapper.
- Weak signals are dangerous for irreversible or high-blast-radius choices, even if the user usually picks the same answer.
- "Skip prompt" and "prefill default" need different thresholds; collapsing them will make the system feel either timid or presumptuous.

### Plan implications

Add a typed question resolver rather than editing every skill ad hoc:

```
ResolveQuestionPreference(question_payload) -> resolved | defaulted | ask
```

Signal strength tiers:
- `hard`: config/env says what to do; skip prompt unless destructive.
- `strong`: repeated or user-authored memory with matching tags and no conflict; default the choice, usually still surface.
- `very_strong`: explicit memory phrase like "always do X after Y" plus low-risk action; skip prompt.
- `weak`: one-off memory, vague wording, or broad context match; ask with prefilled default.
- `conflict`: project and global disagree, or memory and config disagree; ask and show source.

For the audit-amend bridge specifically: after `/z-audit-plan` writes `PLAN_AUDIT_REPORT.md`, emit a typed `post_audit_next_step` question. If project config says `audit.after_audit = "amend"`, run or hand off to `/z-amend` without asking. If memory says "almost always amend after audit," present `/z-amend` as the default. Always log the resolution source into the run archive.

### What would change my mind

- If users frequently want memories to be editable by hand, then TOML or a separate human-readable preferences file becomes more important.
- If most prompt skips are workflow automation rather than personal preference, config should dominate and memories should only suggest defaults.
- If memory retrieval cannot reliably distinguish "audit then amend" from unrelated amendment behavior, it should never skip, only prefill.
- If `/z-amend` itself still asks slug-discovery questions, the better first fix may be passing audit context directly into `/z-amend` rather than building a broad preference hook.
- If users find silent automation unsettling, the threshold should shift: memories may default answers, but only config may skip prompts.
- If many skills use `AskUserQuestion` for semantically different decisions, the hook must be opt-in by question kind, not globally automatic.

---

_Carry-forwards from other framings (per orchestrator recommendation):_
- From Gemini: update `/z-suggest-memory` to detect routing-preference text and redirect users to `config.toml` (closes the onboarding loop — must-have for v1).
- From Claude: use `[workflow]` as the simplest TOML section name for v1 (mirrors existing `[notify]`, `[docs]`).
- Pre-build validation: before building the hook, confirm whether `/z-amend` slug-discovery friction is the real bottleneck. If yes, upstream context-passing into `/z-amend` is the higher-impact fix; the hook still has value but should not be the only fix.
