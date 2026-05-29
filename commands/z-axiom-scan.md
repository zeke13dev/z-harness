---
description: Mine candidate axioms from z-harness interaction history by dispatching the axiom-extractor agent, then writing returned candidates to the axiom store. Use --historical for a full metrics.jsonl scan (expensive). Proposes only — never auto-approves.
argument-hint: [--historical] [--scope <global|project>] [--run <run-id>] [--repo-root <path>]
runtime: c1
driver_features_required:
  - subagent
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-axiom-scan`**.

Read and execute `skills/z-axiom-scan/SKILL.md` in full, passing `$ARGUMENTS` through verbatim.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | axiom-extractor dispatch |
| `ask_user` | no | — |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
