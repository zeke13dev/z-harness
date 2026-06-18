# /z-axiom-scan

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
