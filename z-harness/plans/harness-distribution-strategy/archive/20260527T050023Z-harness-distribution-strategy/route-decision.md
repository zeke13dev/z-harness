# Route decision

**From:** `/z-plan`
**To:** `/z-plan-split`
**Class:** deterministic
**Confidence:** high
**Classifier used:** no — deterministic thresholds decided

## Reason codes
- `expected_tasks_over_threshold` (estimated 40+ tasks; threshold 25)
- `cluster_seams` (6 clean independently-developable clusters)

## Signals
- `expected_tasks: ~40` — full multi-host runtime + 4 host drivers (CLI + SDK tiers) + conformance harness + command migration of every existing `/z-*` command + adapter freeze + install/distribution refactor.
- `cluster_seams: 6` — clean file-path separation between:
  1. **runtime-contract** — canonical command/agent/provider/event/skill schemas + serializer/deserializer.
  2. **dispatcher-core** — CLI subprocess driver (stream-json parser, env hygiene, timeout/reap, session resumption); SDK driver shim.
  3. **driver-codex** — Codex CLI + (optional) OpenAI SDK driver.
  4. **driver-antigravity** — `agy -p` CLI driver + (optional) Antigravity SDK driver; unblocks `/z-plan` past 12k workflow limit.
  5. **driver-claude** + **driver-cursor** — Claude Code self-driver (special: we run *as* a Claude Code plugin) + Cursor `cursor-agent` driver + (optional) `@cursor/sdk` driver.
  6. **conformance-harness** — same-command-against-each-backend test matrix.
  7. **command-migration** — port every `/z-*` command body to the runtime contract.
  8. **adapter-freeze + distribution** — freeze `export-{codex,agy,cursor}.py` at current capability, refactor `install.sh` for new runtime distribution model.
- `cross_module: true` — every driver touches the dispatcher core and the runtime contract; conformance harness touches every driver.
- `public_api_or_wire_format: true` — the runtime contract IS a public wire format (subagent prompts, command schema, event JSONL shape).
- `has_brainstorm: true`, `has_research: true` — both precontext artifacts are present and reconciled.
- `terrain_uncertain: false`, `approach_uncertain: false` — direction (Codex framing: host-neutral runtime + tiered drivers) is settled; only execution scope is large.

## Why /z-plan-split, not /z-plan
The deterministic threshold from /z-plan's Plan Route Check: "Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`." This run trips both conditions simultaneously. Continuing inside one /z-plan would produce a TASKS.md too large for the 10-20 sweet spot AND mix concerns across orthogonal clusters, making implementer subagents' fresh-context loads bloated and reviewer feedback noisy.

`/z-plan-split` fans the topic out into N narrow cluster-planner subagents in parallel, each producing its own SPEC.md/PLAN.md/TASKS.md for its scope. It then reconciles cross-cluster file-path overlaps into SHARED-CONCERNS.md + MANIFEST.md. The runtime-contract cluster's outputs (schemas) become the dependency the other clusters' planners share.

## Route chain
1. `/z-brainstorm` (complete — Codex framing)
2. `/z-plan` (routed away — premature, missing terrain)
3. `/z-research` (complete — terrain mapped)
4. `/z-plan` (this run — routed away again, this time for scope, not terrain)
5. `/z-plan-split` (next)

## Cluster seed list for /z-plan-split
The cluster-planner subagents should be seeded with these scopes (one each):

1. **runtime-contract** — Define `commands/<id>.json` schema, `agents/<id>.json` schema, `events.jsonl` event schema, `providers.json` schema, and the wire format for prompts sent to host drivers. Owner of `runtime/` source tree. Becomes a hard dependency of every other cluster.
2. **dispatcher-core** — `runtime/dispatch/` — CLI subprocess driver (env-hygiene including `CLAUDECODE=""` override, `stream-json` parser, exit-code-via-`is_error` discrimination, timeout + reap, optional session resumption). SDK-driver abstract base.
3. **driver-codex** — `runtime/drivers/codex/` — wraps `codex exec -`; replaces today's resolve-provider.py CLI dispatch for Codex.
4. **driver-antigravity** — `runtime/drivers/antigravity/` — wraps `agy -p`; unblocks `/z-plan` past 12k-char Antigravity workflow limit. Verify agy public-distribution availability BEFORE landing.
5. **driver-claude-self** + **driver-cursor** — `runtime/drivers/claude/` (special: orchestrator runs *as* a Claude Code plugin, so the "driver" mostly proxies tool calls) + `runtime/drivers/cursor/` (wraps `cursor-agent -p`, plus optional `@cursor/sdk` SDK tier).
6. **conformance-harness** — `tests/conformance/` — golden command-shape tests: same `/z-do` invocation run against each driver must produce equivalent artifacts/events.
7. **command-migration** — port `commands/z-*.md` bodies to use the runtime contract. Big mechanical sweep.
8. **adapter-freeze + distribution** — freeze `scripts/export-{codex,agy,cursor}.py` (no new features; bug-fix only); refactor `install.sh` and `/z-update` for the runtime-binary distribution model.

## SHARED-CONCERNS the splitter needs to call out
- Auth tier UX: research confirmed no vendor permits OAuth reuse from sibling SDK processes. The shared concern is "how does a user opt into the SDK tier" — env-var convention, providers.json schema, /z-update behavior. Lives in providers.json (runtime-contract) but consumed by every driver.
- Event JSONL schema versioning — every driver writes events; bumping the schema crosses all clusters.
- The `CLAUDECODE=1` env-var override is a dispatcher-core concern that the Claude-self driver inverts.
- Prompt-cache locality strategy — every CLI driver shares this risk; whether to enforce a "prefix-stable preamble" policy at runtime-contract level is a cross-cutting decision.

## User choice
Pending — present the AskUser handoff gate.
