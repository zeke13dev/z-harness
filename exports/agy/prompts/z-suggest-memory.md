---
description: "Authoring skill for the docs/llm/ memory layer. Called mandatorily from /z-debug post-mortem and /z-improve retro. Validates input against the memory schema, writes to docs/llm/<slug>.json, regenerates docs/llm/MEMORIES-FLAT.md, optionally extract..."
role: workflow
---

You are running **z-harness `/z-suggest-memory`**.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

### `--source` prefix conventions

The `--source <prefix:ref>` flag accepts these canonical prefixes:

| Prefix | Example | Set by |
|--------|---------|--------|
| `incident:<RUN_ID>` | `--source "incident:20260525T233740Z-implement"` | `/z-implement-all` Phase 9 and `/z-review-all` Phase 7 review-agent flow (automatic) |
| `debug:<run-id>` | `--source "debug:20260523T143012Z-my-plan"` | `/z-debug` (automatic) |
| `human_review:<username>` | `--source "human_review:zbarnett"` | `/z-improve` (automatic) |
| `spec:<plan>/<ref>` | `--source "spec:rebalance-v2/run-3"` | Manual |

The `incident:` prefix is used automatically by the review-agent flow — you do not need to supply it when invoked from `/z-implement-all` or `/z-review-all`.

### `--kind routing-preference` mode

When `--kind routing-preference` is present, the skill writes a structured routing-preference memory entry without any interactive collection. Required flags:

| Flag | Description | Example |
|------|-------------|---------|
| `--question-id <id>` | Registered question ID from `QUESTION_IDS` | `workflow.audit_to_amend` |
| `--value <v>` | The preferred answer for that question | `amend` |
| `--strength <s>` | Signal strength: `weak`, `strong`, or `very_strong` | `very_strong` |
| `--scope <s>` | Memory scope: `global` or `project` | `project` |
| `--reason <text>` | Optional one-line rationale (≤ 200 chars, no emojis) | `"always amend after style audit"` |

**Target file:** `docs/llm/workflow.json` for global scope; `docs/llm/workflow-<project-slug>.json` for project scope. The file is created (with INDEX.json registration) if it does not exist.

**Memory entry shape:**
```json
{
  "type": "routing-preference",
  "question_id": "<id>",
  "value": "<v>",
  "scope": "global|project",
  "strength": "weak|strong|very_strong",
  "reason": "<text>",
  "date": "<YYYY-MM-DD>",
  "project_root": "<abs-path or omitted>"
}
```

The `reason` and `project_root` fields are omitted when not applicable. MEMORIES-FLAT.md is regenerated after the write. This mode is used by the elevation proposer flow when the user accepts a proposal as a memory:strength entry.

Read and execute `skills/z-suggest-memory/SKILL.md` in full, passing `$ARGUMENTS` through verbatim.

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
