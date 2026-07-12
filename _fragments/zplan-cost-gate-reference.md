<!-- ZPLAN-COST-GATE-REFERENCE: reference tables for /z-plan's pre-subagent
     hard cost gate, extracted from skills/z-plan/SKILL.md at T113
     (skill-overhaul-phase1, criterion #9 extraction-first remedy). These are
     decision-table/telemetry-field lookups the model consults while running
     the cost-gate branch documented in skills/z-plan/SKILL.md's "Pre-subagent
     cost gate (hard)" section — never restated inline there; reference this
     file by name instead. -->

## Cost gate telemetry field reference

`cost_gate_decision` is reserved for **exactly one terminal `/z-plan` cost-gate decision per run**. It is emitted before any expensive Agent dispatch and never emitted again on later success paths. Every terminal branch uses the same payload builder and includes these fields when known:

- `command: "z-plan"`
- `choice`: one of `auto_proceed`, `proceed`, `abandon`, `halt`, or `interrupted`
- `estimated_tokens`, `confidence`, `basis`
- `disposition`: normalized helper disposition that led to the branch (`auto_proceed`, `ask`, `halt`, `unhandled_gate`, or the sanitized fallback disposition)
- `rule_id`
- `range_high`
- `choice_source`: `helper`, `user`, `policy`, `sanitized_helper_error`, or `driver_interrupt`
- `attempt_count`: terminal count of cost reduction / re-estimate attempts
- optional `reason`: sanitized reason such as `gate_policy_halt`, `unhandled_gate`, `helper_invocation_failure`, `malformed_helper_json`, `missing_estimate_fields`, `user_abandoned`, or `user_wait_interrupted`

Nonterminal reduction / re-estimate attempts MUST NOT emit `cost_gate_decision`. They emit `cost_gate_reestimate_attempt` instead, with: `command`, `run_id`, `gate_id`, `attempt_index`, changed driver(s) (for example `changed_drivers`), `prior_range_high`, `new_range_high`, `disposition`, and terminal-correlation fields (`terminal_event_kind: "cost_gate_decision"` plus the same `gate_id`).

## Cleanup matrix

| Branch | Terminal event | Cleanup / next step |
|---|---|---|
| `auto_proceed` | `choice=auto_proceed`, `choice_source=helper`, `disposition=auto_proceed` | Continue; no AskUser; no cleanup. |
| `ask` → Proceed | `choice=proceed`, `choice_source=user`, `disposition=ask` | Continue after `user_wait_end`; no cleanup. |
| `ask` → Reduce / re-estimate | Nonterminal only: emit `cost_gate_reestimate_attempt`; do **not** emit `cost_gate_decision` | Mutate the authoritative intent/dispatch variables, re-run the helper, print the recomputed human block, and loop until proceed/abandon, cap, interruption, or policy halt. |
| `ask` → Re-estimate returns `auto_proceed` | `choice=auto_proceed`, `choice_source=helper`, `disposition=auto_proceed`, `attempt_count>0` | Continue immediately; no extra AskUser and no user-proceed terminal event. |
| `ask` → Re-estimate returns `halt` | `choice=halt`, `choice_source=policy`, `reason=gate_policy_halt`, `attempt_count>0` | Run `zplan_cost_gate_halt_finalize "cost gate policy halt"`; exit 1. |
| `ask` → Abandon | `choice=abandon`, `choice_source=user`, `reason=user_abandoned` | Run `zplan_cost_gate_halt_finalize "cost gate abandoned by user"`; exit 1. |
| `halt` | `choice=halt`, `choice_source=policy`, `reason=gate_policy_halt` | Run `zplan_cost_gate_halt_finalize "cost gate policy halt"`; exit 1. |
| `unhandled_gate` | `choice=halt`, `choice_source=policy`, `disposition=unhandled_gate`, `reason=unhandled_gate` | Run `zplan_cost_gate_halt_finalize "cost gate unhandled disposition"`; exit 1. |
| Helper invocation failure | Interactive: ask branch with `reason=helper_invocation_failure`; no-ask: terminal `choice=halt` | If terminal, run halt-finalize; if user proceeds, continue only after the terminal `proceed` event. |
| Malformed helper JSON | Interactive: ask branch with `reason=malformed_helper_json`; no-ask: terminal `choice=halt` | Never log raw helper output; if terminal, run halt-finalize. |
| Missing estimate fields | Interactive: ask branch with `reason=missing_estimate_fields`; no-ask: terminal `choice=halt` | Never invent confidence/basis beyond safe defaults; if terminal, run halt-finalize. |
| Interrupted user wait after claim/register | `choice=interrupted`, `choice_source=driver_interrupt`, `reason=user_wait_interrupted` | Emit `user_wait_end` with interrupted disposition, then halt-finalize; release guarded by `CLAIM_HELD`, deregister only when `REG_RC==0`. |

## Sanitized helper-error expansion

These are the only allowed outcomes once `GATE_SANITIZED_ERROR` is set:

| Condition | Interactive outcome | No-ask / noninteractive outcome |
|---|---|---|
| `helper_invocation_failure` | Ask with safe defaults. Proceed emits one terminal `cost_gate_decision` (`choice=proceed`, `reason=helper_invocation_failure`) and continues; Abandon/Interrupted emit one terminal decision and halt-finalize. | Emit one terminal `cost_gate_decision` (`choice=halt`, `choice_source=sanitized_helper_error`, `reason=helper_invocation_failure`), then halt-finalize. |
| `malformed_helper_json` | Ask with safe defaults. Proceed emits one terminal `cost_gate_decision` (`choice=proceed`, `reason=malformed_helper_json`) and continues; Abandon/Interrupted emit one terminal decision and halt-finalize. Raw helper text is never logged. | Emit one terminal `cost_gate_decision` (`choice=halt`, `choice_source=sanitized_helper_error`, `reason=malformed_helper_json`), then halt-finalize. Raw helper text is never logged. |
| `missing_estimate_fields` | Ask with safe defaults. Proceed emits one terminal `cost_gate_decision` (`choice=proceed`, `reason=missing_estimate_fields`) and continues; Abandon/Interrupted emit one terminal decision and halt-finalize. | Emit one terminal `cost_gate_decision` (`choice=halt`, `choice_source=sanitized_helper_error`, `reason=missing_estimate_fields`), then halt-finalize. |
