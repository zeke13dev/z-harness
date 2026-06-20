---
name: z-axiom-edit
disable-model-invocation: false
description: Edit a field on a candidate or approved axiom record. On approved records, re-validates the graph and regenerates the kernel.
argument-hint: <id> --set <field>=<value> [--set <field>=<value> ...] [--scope <global|project>] [--repo-root <path>]
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-axiom-edit`**.

Read and execute `skills/z-axiom-edit/SKILL.md` in full, passing `$ARGUMENTS` through verbatim.

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
