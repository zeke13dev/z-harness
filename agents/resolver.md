---
name: resolver
description: Documents the workflow question resolver — the read-only subsystem that maps registered question_ids to a result-domain value (skip|prefill|ask|halt|defer-to-sink) by consulting config layers, memory, and overnight-gate overrides.
model: haiku
---

# Resolver — result vocabulary reference

The resolver is a read-only subsystem implemented in `scripts/config.py` (`cmd_resolve_question`). It consults the 4-layer config stack, routing-preference memory, and overnight-gate overrides, then returns a JSON envelope:

```jsonc
{
  "result": "<result-domain>",
  "default": "<option-label from QUESTION_IDS[id].skill_default>",
  "source": "<config|memory|conflict|none|override|overnight_allowlist|no_ask_halt>",
  "rule_id": "<question_id or special rule name>",
  "strength": "<hard|very_strong|strong|weak|none|policy>",
  "reason": "<one-line human-readable>",
  "sources": [
    {
      "kind": "<config|memory|allowlist|env>",
      "value": "<resolved value>",
      "location": "<config file path or docs/llm/*.json or env var name>",
      "strength": "<tier>"
    }
  ]
}
```

## Result domain

| result | meaning | orchestrator action |
|--------|---------|---------------------|
| `ask` | Present the question to the user interactively | Invoke `AskUserQuestion` |
| `skip` | Accept the pre-selected option without asking | Proceed silently |
| `prefill` | Pre-select the suggested option but still prompt | Invoke `AskUserQuestion` with option pre-highlighted |
| `halt` | Stop the current workflow entirely | Exit with structured error |
| `defer-to-sink` | Capture the question as a follow-up work item | Invoke `scripts/sink-add.sh` with question context as entry body |

## `defer-to-sink` result class

When the resolver returns `result: "defer-to-sink"`, the orchestrator **must not** present the question interactively. Instead it calls `scripts/sink-add.sh` and routes the question context as a new follow-up entry.

### When this result is produced

A registered question maps to `defer-to-sink` when its config/env value is set to `"defer-to-sink"` in RESULT_MAP. Any future question_id whose orchestrator contract says "if out-of-scope, park it for later" should map one of its choices to this result.

The canonical use case is **spec-retro discoveries**: if the implementer surfaces an out-of-current-SPEC finding during Phase 4 of `/z-implement-next`, the resolver can return `defer-to-sink` to route the finding to the project follow-up sink instead of triggering an in-run SPEC.md edit.

### Envelope shape for `defer-to-sink`

```jsonc
{
  "result": "defer-to-sink",
  "default": "<suggested option label>",
  "source": "config",
  "rule_id": "<question_id>",
  "strength": "hard",
  "reason": "question configured to defer to follow-up sink",
  "sources": [
    {
      "kind": "config",
      "value": "defer-to-sink",
      "location": "<config file path or env var>",
      "strength": "hard"
    }
  ]
}
```

### Orchestrator contract for `defer-to-sink`

When the orchestrator receives `result: "defer-to-sink"`, it must:

1. Build the entry body from the question context (question text, discovery summary, affected file paths).
2. Invoke `scripts/sink-add.sh` with at minimum:
   - `--sink=project` (or `global` for harness-wide findings)
   - `--priority=P2`
   - `--name='<short title derived from question>'`
   - `--recommended-command='<suggested z-command>'`
   - `--source-artifact='<path to task archive or spec file>'`
   - `--cited-paths='<affected paths>'`
   - `--prompt-body='<question context as entry body>'`
3. Log a `followup_deferred_from_resolver` event.
4. Proceed without asking the user — the question has been safely parked.

### Relationship to VALIDATORS and QUESTION_IDS

`defer-to-sink` is a **result-domain** value, not an option-domain value. It does not appear in `VALIDATORS` or `QUESTION_IDS[id]["choices"]`. It appears only in `RESULT_MAP` as the target of a mapping from a registered option-domain value.

Example: `workflow.spec_retro_discovery` with choices `{ask, defer_to_sink_p2}` maps to:
```python
("workflow.spec_retro_discovery", "defer_to_sink_p2"): "defer-to-sink",
```

### Error handling

- If `sink-add.sh` exits non-zero after a `defer-to-sink` result, the orchestrator must surface the error to the user and fall back to `ask` — the question cannot be silently dropped.
- `defer-to-sink` is never applied by the overnight gate (`_apply_overnight_overrides`); it is a config-layer result only.
