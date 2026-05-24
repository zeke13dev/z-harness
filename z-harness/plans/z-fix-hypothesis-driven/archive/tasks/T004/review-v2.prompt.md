You are reviewing a second-pass delta for task T004: docs/human/z-fix.md fixes.

Spec excerpt (decision matrix section):
```
## File: `docs/human/z-fix.md` (NEW)

Companion human doc for `/z-fix`. Structure following existing human-tier docs:
- One-paragraph overview ("what this command is for / not for").
- Phase-by-phase walkthrough (brief — link to `commands/z-fix.md` for full procedure).
- "When to pick `/z-fix` vs `/z-debug`" decision matrix.
- Example invocation + sample FIX.md.
- Hard rules summary.
```

Acceptance criteria (from v1 review findings):
1. Major: Missing hard rule "Never overwrite existing slug directory without asking"
2. Major: Decision matrix routed cross-module to /z-debug; should route diagnosis-unknown→/z-debug AND scope-too-large→/z-plan

Implementer's claim for v2: Split the decision-matrix row; added the missing hard rule.

Delta (changes from v1 → v2):
```
@@ -50,7 +50,8 @@
 +| You can state a hypothesis in one sentence. | `/z-fix` |
 +| You cannot name what's causing the symptom. | `/z-debug` |
 +| The fix touches 1–5 files in one module. | `/z-fix` |
-+| The fix may involve multiple modules or public APIs. | `/z-debug` (or `/z-plan`) |
++| The fix may involve multiple modules or public APIs — root cause unclear. | `/z-debug` |
++| The fix scope is confirmed too large (cross-module impact, >5 files). | `/z-plan` |
 +| You want a fast loop — 15 min target. | `/z-fix` |
 +| You want adversarial hypothesis generation and Bayesian elimination. | `/z-debug` |
 +| A previous `/z-debug` run identified the root cause. | `/z-fix` to implement the fix. |
@@ -126,6 +127,7 @@
 +- **Single bundled `light-fix` consult only.** This is not a multi-round hypothesis generation flow.
 +- **No emojis** in any artifact.
 +- **FIX.md is the single artifact.** No SPEC.md, PLAN.md, TASKS.md, PROBLEM.md, or EVIDENCE.md.
++- **Never overwrite an existing `<slug>/` directory** without asking the user.
 +
 +## See also
```

Current document excerpts:

=== /Users/zeke/dev/z-harness/docs/human/z-fix.md (lines 40-60) ===
```
## When to pick `/z-fix` vs `/z-debug`

| Signal | Pick |
|---|---|
| You can state a hypothesis in one sentence. | `/z-fix` |
| You cannot name what's causing the symptom. | `/z-debug` |
| The fix touches 1–5 files in one module. | `/z-fix` |
| The fix may involve multiple modules or public APIs — root cause unclear. | `/z-debug` |
| The fix scope is confirmed too large (cross-module impact, >5 files). | `/z-plan` |
| You want a fast loop — 15 min target. | `/z-fix` |
| You want adversarial hypothesis generation and Bayesian elimination. | `/z-debug` |
| A previous `/z-debug` run identified the root cause. | `/z-fix` to implement the fix. |
| Post-mortem is optional. | `/z-fix` |
| Post-mortem is mandatory. | `/z-debug` |
```

=== /Users/zeke/dev/z-harness/docs/human/z-fix.md (lines 115-130) ===
```
## Hard rules

- **Never skip Codex review.** Fix mode cuts planning overhead, not correctness.
- **Never proceed past auto-bail thresholds** without explicit user override.
- **Always emit cross-LLM consult** — both Gemini and Codex in parallel, framed around "does this cause explain all symptoms?".
- **Phase 0 is non-skippable.** A symptom description alone is not a hypothesis. If the user cannot name a hypothesis, the command exits with a `/z-debug` recommendation.
- **Single bundled `light-fix` consult only.** This is not a multi-round hypothesis generation flow.
- **No emojis** in any artifact.
- **FIX.md is the single artifact.** No SPEC.md, PLAN.md, TASKS.md, PROBLEM.md, or EVIDENCE.md.
- **Never overwrite an existing `<slug>/` directory** without asking the user.
```

Scrutinize rigorously. This is a delta review — focus on whether the prior findings were resolved; do NOT re-flag issues outside the delta.

Report:
1. Do both prior findings verify as addressed?
2. Are there any problems with the new rows or the hard rule?
3. Does the decision matrix now correctly route all three cases (diagnosis-unclear → /z-debug; scope-too-large → /z-plan; diagnosis-known + scope-ok → /z-fix)?

OUTPUT BUDGET — under 2000 characters for a delta review.

For each finding: severity (blocker / major / minor), location, and a suggested fix.
