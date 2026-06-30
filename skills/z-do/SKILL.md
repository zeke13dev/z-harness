---
name: z-do
disable-model-invocation: false
description: Deprecated compatibility alias. Immediately routes to /z-plan --quick with the original arguments; retained only for user muscle memory and legacy artifact references.
argument-hint: <small task description>
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

## Deprecated alias

**Print to the user:** "Note: /z-do is deprecated and now routes to /z-plan --quick (L1)."

Immediately invoke `/z-plan --quick $ARGUMENTS`, passing `$ARGUMENTS` verbatim, then stop this command. Do not perform premise checks, doc grounding, inline implementation, review, logging, or any other legacy `/z-do` phase here.

```text
/z-plan --quick $ARGUMENTS
```

## Backward compatibility

Historical `/z-do` runs may still have `approach.md` and `premise.md` artifacts under the legacy `adhoc/archive/<run-id>/` layout. Readers such as `/z-improve`, run-brief rendering, or archival reports may reference those files when summarizing old runs; new invocations must create artifacts through `/z-plan --quick` instead.
