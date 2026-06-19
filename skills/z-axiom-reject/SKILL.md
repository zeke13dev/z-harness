---
name: z-axiom-reject
disable-model-invocation: true
description: Reject a candidate or approved axiom, moving it to the rejected/ tombstone store. Optionally records a rejection reason.
argument-hint: <id> [--reason <text>] [--scope <global|project>] [--repo-root <path>]
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-axiom-reject`**.

Read and execute `skills/z-axiom-reject/SKILL.md` in full, passing `$ARGUMENTS` through verbatim.

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
