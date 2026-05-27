---
artifact: manifest
slug: harness-distribution-strategy
generated_at: 2026-05-27T05:05:49Z
command: /z-plan-split (continuation of harness-distribution-strategy slug; full multi-host runtime scope per /z-plan route decision)
input_hash: 5fa2c19e7d8b3406
status: ready
total_clusters: 6
clusters_ready: 6
---

# MANIFEST — harness-distribution-strategy

## Clusters

| ID | Name (slug) | Scope (one line) | Path | Status | Attempts | Final status at |
|----|-------------|------------------|------|--------|----------|-----------------|
| C1 | runtime-core | Canonical command/agent/provider/event schemas + in-process dispatcher core | plans/harness-distribution-strategy/runtime-core/ | ready | 1 | 2026-05-27T05:01:14Z |
| C2 | driver-codex | CLI-tier driver for `codex exec -` + Codex-specific auth/MCP handling | plans/harness-distribution-strategy/driver-codex/ | ready | 2 | 2026-05-27T05:05:21Z |
| C3 | driver-antigravity | CLI-tier driver for `agy -p`; unblocks /z-plan past 12k workflow limit | plans/harness-distribution-strategy/driver-antigravity/ | ready | 1 | 2026-05-27T05:01:18Z |
| C4 | driver-claude-cursor | Claude-self (in-process) + Cursor (cursor-agent CLI + @cursor/sdk) drivers | plans/harness-distribution-strategy/driver-claude-cursor/ | ready | 1 | 2026-05-27T05:01:21Z |
| C5 | conformance-harness | Cross-driver test matrix over `/z-do` pilot; gates new drivers | plans/harness-distribution-strategy/conformance-harness/ | ready | 1 | 2026-05-27T05:01:16Z |
| C6 | shipping | Command migration (template + bulk) + adapter freeze + install.sh / /z-update refactor | plans/harness-distribution-strategy/shipping/ | ready | 2 | 2026-05-27T05:05:11Z |

`ID` is the stable `cluster_id` used in telemetry. `Name (slug)` is the kebab-case `cluster_slug` used as the on-disk directory.

## Run order

Clusters execute sequentially in this order under `/z-implement-all`. Cross-cluster task parallelism is v2.

1. **C1 runtime-core** — must land first; defines the interface every other cluster targets.
2. **C2 driver-codex** — first driver; replaces an actively-used path; validates the dispatcher against the host z-harness already speaks to.
3. **C5 conformance-harness** — implementable scaffolding (T001-T004, T008-T010) in parallel with C2; recorded fixtures (T005-T007) flip to passing only after C2 lands.
4. **C3 driver-antigravity** — unblocks /z-plan past Antigravity 12k workflow limit; T001 is a hard pre-flight on agy public availability.
5. **C4 driver-claude-cursor** — Claude-self (in-process) is structurally different from spawn-based drivers; validate against C1's HostDriver interface early.
6. **C6 shipping** — lands last; depends on C1 + ≥1 driver + C5; command migration is the largest single task surface.

## Total task counts

| Cluster | Tasks | Notes |
|---------|-------|-------|
| C1 runtime-core | 16 | 3 high-complexity (T010, T012, T015) |
| C2 driver-codex | 7 | 4 high (T001, T002, T003, T004, T007 by inference); T006 blocked on C1 |
| C3 driver-antigravity | 8 | T001 is hard pre-flight gate (agy availability) |
| C4 driver-claude-cursor | 12 | Two drivers; could split if it grows in implementation |
| C5 conformance-harness | 10 | T005-T007 are `xfail` placeholders until C2 lands |
| C6 shipping | 8 | T002 is the largest single task (28-command bulk migration) |
| **Total** | **61** | Across 6 cluster plans |

## Shared concerns

See `SHARED-CONCERNS.md`. **`overlap_count: 0`** — no strict file-path overlaps; `acknowledged: true` auto-set. SHARED-CONCERNS.md additionally lists 6 informational cross-cluster awareness items (interface dependencies, sequencing, the `scripts/install.sh` vs `install.sh` path discrepancy in C6) that do NOT gate /z-implement-all but the implementer should read before starting C2/C4/C6.

## Resolved decisions

Decisions surfaced by cluster-planners during Phase 3 and resolved by the user before re-spawn:

- **C2 C2-D1**: chose `c1-owns-schema` — C1 (runtime-core) defines the canonical provider entry schema including any Codex-specific fields; C2 reads/validates only the fields it needs at runtime. Rationale: single source of truth, simpler C5 conformance import (run 20260527T050549Z).
- **C6 C6-D1**: chose `one-minor-version` — export-*.py and pre-migration commands print a deprecation warning for one minor version, then are removed in the following release. audit-tarball.sh keeps legacy paths in allowlist for that one minor version; install.sh keeps --legacy flag scoped to one minor version (run 20260527T050549Z).

Decisions resolved unilaterally by cluster-planners (no escalation):

- C1-D1: JSON Schema Draft 7 as the schema language.
- C1-D2: `auth_env` declared in provider.json schema; dispatcher reads and injects into subprocess env.
- C1-D3: `HostDriver` as Python ABC in `runtime/dispatch/driver.py`.
- C2-D2: OPENAI_API_KEY workaround uses model_providers stanza injection into ~/.codex/config.toml, idempotently.
- C2-D3: ~/.codex/auth.json is a read-only presence check — no OAuth token injection into env.
- C2-D4: session resumption is probed first (T004); no assumption made about flag existence.
- C3-D1: Antigravity Extension SDK deferred to v2.
- C3-D2: Python subprocess.Popen for CLI dispatch (matches existing harness scripting pattern).
- C3-D3: `export-agy.py` untouched in C3; C6 owns cutover.
- C4-D1: Dual-mode Claude driver — `SelfHostDriver` (in-process plugin case) + `SubprocessClaudeDriver` (cross-host case). Both needed.
- C4-D2: Auto-detect via `CLAUDECODE` env var; `--driver` flag overrides.
- C4-D3: Cursor CLI tier only in v1; `@cursor/sdk` stubbed as `NotImplementedError` for v2.
- C4-D4: MCP config key must be literal `"z-harness"` with runtime assertion in `mcp_config.py` (CVE-2025-54136 mitigation).
- C5-D1: Pilot command for conformance matrix is `/z-do`.
- C5-D2: Four-criteria equivalence (events modulo timestamps/run-ids, artifact paths, exit status, normalized fixture match) rather than byte-identical.

## Open questions carried forward to /z-implement-all

These were flagged in RESEARCH.md as terrain unknowns and remain unresolved by planning. Implementers must answer them empirically as they arise:

1. **Codex `exec` session-id flag existence** — C2-T004 probes this.
2. **Cross-vendor env-var collision** — C2-T007 smoke tests.
3. **OAuth token rotation in long-running subprocess sessions** — defer to v2.
4. **Antigravity public-distribution status** — C3-T001 hard pre-flight (cluster may auto-skip).
5. **Cursor SDK local-runtime `agent_busy` semantics** — C4-T009 will surface if blocking.
6. **MCP tool payload size limits across hosts** — defer to first user-reported truncation.
