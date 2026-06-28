---
name: z-map
disable-model-invocation: false
description: Legacy compatibility wrapper for obsolete `/z-map`; use `/z-explore --depth=deep` for terrain mapping.
argument-hint: <question or technical area to explore>
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

## STOP — LEGACY COMPATIBILITY WRAPPER

`/z-map` is obsolete. It is retained only as a legacy compatibility name for older docs, artifacts, and command references.

**Print to the user:** "Note: /z-map is obsolete and now routes to /z-explore --depth=deep."

STOP. Do not run a standalone `/z-map` pipeline. Do not present `/z-map` as the active terrain-mapping command. Immediately delegate to the current command, passing `$ARGUMENTS` verbatim, then terminate this command's execution:

```text
/z-explore --depth=deep $ARGUMENTS
```

Preserve the historical `MAP.md` artifact name when referring to legacy `/z-map` outputs or compatibility paths. New terrain-mapping instructions, examples, and handoffs MUST name `/z-explore --depth=deep` as canonical.

If the user asks what happened to `/z-map`, answer briefly: `/z-map` is a legacy alias/compatibility surface; `/z-explore --depth=deep` is the active deep terrain exploration flow.
