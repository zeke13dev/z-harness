---
description: List axiom records from the store, rendered as a readable table. Supports filtering by status, scope, and discipline.
argument-hint: "[--status <candidate|approved|rejected>] [--scope <global|project>] [--discipline <tag>] [--repo-root <path>]"
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-axiom-list`**.

Read and execute `skills/z-axiom-list/SKILL.md` in full, passing `$ARGUMENTS` through verbatim.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | no | — |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
