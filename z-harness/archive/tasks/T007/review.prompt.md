You are reviewing code that Claude just wrote for task T007: Telemetry events: full component lifecycle wiring.

Spec (excerpt):
From SPEC.md lines 164-170:
```
### `commands/z-uplift.md` — telemetry contract
Standard `phase_end` events per phase. Component-specific events:
- `component_detected` — payload: `{slug, path, method, unclaimed: bool}`
- `component_audit_start` — `{component, dimensions}`
- `component_audit_done` — `{component, findings_total, findings_crit_high, bailed, bail_reason}`
- `component_implement_start` — `{component, task_count}`
- `component_implement_done` — `{component, completed, halted}`
- `cross_cutting_classified` — `{global_tasks, per_component_context, risks}`
```

Acceptance criteria:
1. grep `commands/z-uplift.md` for `log-event.sh` returns ≥10 distinct event names matching the SPEC list (component_detected, component_audit_start, component_audit_done, component_implement_start, component_implement_done, cross_cutting_classified, style_md_missing, resume_detected)
2. every AskUser block is wrapped by user_wait_start / user_wait_end
