---
description: Authoring skill for the docs/llm/ memory layer. Called mandatorily from /z-debug post-mortem and /z-improve retro. Validates input against the memory schema, writes to docs/llm/<slug>.json, regenerates docs/llm/MEMORIES-FLAT.md, optionally extracts into docs/human/<slug>.md.
argument-hint: [--concept <slug>] [--concept-hints <slug>,<slug>] [--source <prefix:ref>] [--edit <slug> <index>] [--delete <slug> <index>] [--dry-run] [--no-refresh-human]
---

You are running **z-harness `/z-suggest-memory`**.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

Read and execute `skills/z-suggest-memory/SKILL.md` in full, passing `$ARGUMENTS` through verbatim.
