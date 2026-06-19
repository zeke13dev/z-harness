---
description: Approve a candidate axiom. Shows the candidate, its evidence, and falsifiability state. Requires explicit user confirmation before approving. Reuses /z-suggest-memory --from-candidate-json for the MEMORY-overlap advisory. Regenerates the kernel synchronously on approval.
argument-hint: <id> [--scope <global|project>] [--repo-root <path>]
runtime: c1
driver_features_required:
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-axiom-approve`**.

Read and execute `skills/z-axiom-approve/SKILL.md` in full, passing `$ARGUMENTS` through verbatim.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | yes | Falsifiability acknowledgement (needs_ack); final approval gate |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
