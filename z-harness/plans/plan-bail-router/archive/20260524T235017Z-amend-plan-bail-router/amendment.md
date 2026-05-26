# Amendment: Clarify planning-router fallback statuses

**Run:** 20260524T235017Z-amend-plan-bail-router
**Mode:** full
**Requested change:** fix planning-router contract precheck blocker

## What this affects

### SPEC.md
- Update the `planning-router` return shape to allow `STATUS: routed | ask_user | bad_input`.
- Define how malformed input is represented without inventing a route.
- Define route-loop output using an explicit `RECOMMENDED: ask_user` advisory value and `ROUTE_CLASS: none`.
- Add `bad_input` to the stable `reason_codes` list.
- Keep concrete command recommendations unchanged for normal routed decisions.

### PLAN.md
- Add a short amendment note that the router can return `bad_input` for malformed payloads and `ask_user` for loop-risk fallback cases.

### TASKS.md
- **New tasks:** none
- **Modified tasks:** none
- **Removed tasks:** none
- **Touched-but-completed tasks:** none

### FIX.md
- no change

## Risk
- No cross-module implementation risk beyond clarifying the planned agent contract.
- No new dependency, persistence, schema, or public runtime API change.
- No consult triggered.
