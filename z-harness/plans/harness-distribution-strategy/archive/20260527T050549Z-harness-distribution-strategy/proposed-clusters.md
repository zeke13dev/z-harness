# Proposed clusters — harness-distribution-strategy

Six clusters (at the upper bound of 2-6). Skipping `doc-fetcher` for this phase — BRAINSTORM.md + RESEARCH.md already grounded the topic; cluster-planners will re-dispatch doc-fetcher for their own scope as needed.

## C1 — runtime-core

**Scope.** The canonical wire-level contract that every driver and command speaks: command schema (kebab-id, frontmatter, body), agent schema (model/tools/triggers), provider/auth schema (roles, kind, env-var contract), event JSONL schema (versioned), and the in-process dispatcher core that consumes them. Owns `runtime/` source tree, `runtime/contract/`, `runtime/dispatch/`. NOT this cluster: any host-specific driver code, any user-facing command body, any install/distribution work.

## C2 — driver-codex

**Scope.** Concrete implementation of the runtime dispatcher's "host driver" interface for Codex CLI (`codex exec -`) at the CLI tier, plus an optional SDK tier shim. Owns `runtime/drivers/codex/`. Replaces today's `scripts/resolve-provider.py` Codex dispatch path. Handles Codex-specific quirks: `CODEX_API_KEY` vs `OPENAI_API_KEY` via `model_providers` workaround, ChatGPT OAuth token storage in `~/.codex/auth.json`, `codex mcp add` registration. NOT this cluster: runtime contract definition, Antigravity/Cursor/Claude drivers, conformance harness.

## C3 — driver-antigravity

**Scope.** Concrete driver implementation for Antigravity (`agy -p` CLI with `--output-format stream-json`), plus optional Antigravity Extension SDK tier. Owns `runtime/drivers/antigravity/`. Unblocks `/z-plan` past Antigravity's 12k-char workflow body limit. Includes a pre-flight check for agy public-distribution availability (`npm install -g @google/antigravity` 404 on 2026-05-21 per RESEARCH.md). NOT this cluster: runtime contract, Codex/Cursor/Claude drivers, conformance harness.

## C4 — driver-claude-cursor

**Scope.** Two drivers bundled because each is structurally "the host has a richer programmatic surface than just a CLI": (a) Claude-self driver (z-harness runs *as* a Claude Code plugin — the driver mostly proxies tool calls back to the host runtime, with `CLAUDECODE=""` env-hygiene when spawning child subprocesses), (b) Cursor driver (`cursor-agent -p` at CLI tier, optional `@cursor/sdk` at SDK tier, Background Agents REST API as a future tier). Owns `runtime/drivers/claude/` and `runtime/drivers/cursor/`. NOT this cluster: runtime contract, Codex/Antigravity drivers, conformance harness.

## C5 — conformance-harness

**Scope.** Cross-driver test matrix that asserts the same `/z-*` command invocation against each driver produces equivalent artifacts (TASKS.md, events.jsonl shape, push notifications, exit semantics). Owns `tests/conformance/` and the golden-output fixtures. Required gating for any new driver to land. NOT this cluster: implementation of any driver, runtime contract definition.

## C6 — shipping

**Scope.** The release / distribution / migration concerns: (a) port every existing `commands/z-*.md` body to the runtime contract (command-migration), (b) freeze `scripts/export-{codex,agy,cursor}.py` at current capability (no new features; explicit deprecation), (c) refactor `install.sh` and `/z-update` to package the runtime binary, `runtime/`, `drivers/`, plus the legacy frozen exporters during the transition. Owns `install.sh`, `commands/z-update.md`, `scripts/export-*.py` (freeze-only), and the migrated `commands/z-*.md`. NOT this cluster: any runtime/driver implementation, conformance harness.

---

## SHARED-CONCERNS hints for the splitter
- `runtime/contract/` schemas (owned by C1) are read by every driver (C2-C4) and consumed by the conformance harness (C5) and the migrated commands (C6). Mechanically, the contract `.json` schema files appear in C1's TASKS.md exclusively, but logically every cluster depends on them.
- `commands/z-*.md` are owned exclusively by C6, but their contract-compliance is tested by C5.
- `providers.json` schema lives in C1 (runtime-core), but the env-var contract for SDK tier is consumed by every driver in C2/C3/C4.
- The `CLAUDECODE=""` env-hygiene policy is implemented in C1's dispatcher-core but explicitly inverted by C4's Claude-self driver.
- Prompt-cache locality "stable preamble" policy (if adopted) lives in C1's contract; every driver enforces it.

## Run order rationale
C1 (runtime-core) MUST land first — it defines the interface every other cluster targets. C2/C3/C4 (drivers) can land in any order after C1; suggest C2 first because it replaces an actively-used path. C5 (conformance-harness) can land in parallel with the first driver. C6 (shipping) lands last because it depends on C1's contract being stable and at least one driver being operational.

Suggested MANIFEST run order: **C1 → C2 → C5 → C3 → C4 → C6**.
