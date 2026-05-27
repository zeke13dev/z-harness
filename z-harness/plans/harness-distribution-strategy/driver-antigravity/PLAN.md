# PLAN — C3: driver-antigravity

cluster-id: C3
cluster-name: driver-antigravity
run-id: 20260527T050549Z-harness-distribution-strategy

---

## Goal

Implement the Antigravity (agy) driver for the z-harness host-neutral runtime. The driver lives at `runtime/drivers/antigravity/` and dispatches harness commands through `agy -p --output-format stream-json`, handling JSONL output parsing, auth (Google OAuth inherited from `~/.gemini/`), MCP config helpers for `~/.gemini/config/mcp_config.json`, and the 12k-char workflow-body-limit workaround (the CLI-tier `agy -p` path bypasses this limit entirely). A mandatory pre-flight check gates all driver tasks on confirmed public availability of `agy` — since `npm install -g @google/antigravity` returned 404 on 2026-05-21, the pre-flight must re-verify current availability before any driver code is committed as non-speculative. The Extension SDK tier is deferred to v2. The existing `export-agy.py` dispatch path is preserved untouched; cutover is C6's responsibility.

---

## Decisions

| ID | Question | Chosen option | Rationale |
|----|----------|--------------|-----------|
| C3-D1 | Extension SDK tier in v1? | defer-sdk-to-v2 | Community docs only; no first-party API ref; agy may not be publicly distributed; SDK requires GEMINI_API_KEY (new credential burden for users). |
| C3-D2 | Driver implementation language/approach? | python-subprocess-popen | Consistent with existing harness Python scripts; no new external dependency; subprocess.Popen with stdout JSONL iteration is the same pattern as the Codex driver (C2). Driver conforms to C1's interface, does not define its own public contract. |
| C3-D3 | Touch export-agy.py from C3? | coexist-no-cutover | Scope leak into C6 domain. C3 writes new driver and a READY marker; C6 owns the actual cutover wiring. |

---

## Non-goals (v1)

- Extension SDK tier (sdk.cascade, sdk.monitor, sdk.commands, sdk.ls, sdk.state)
- Antigravity Managed Agents REST API (`POST /v1beta/interactions`)
- Modifying `scripts/export-agy.py`
- CDP debug port / Antigravity-link-extension integration
- Persistent daemon mode or connection pooling for agy subprocess
- Session resumability across harness restarts (agy `-p` is single-shot per invocation)
- pty/TUI wrapping (`agy chat` interactive mode)

---

## Approved shortcuts

- The driver's C1-facing interface is written as a stub with `# TODO: import from runtime.contract once C1 ships`. C3 does not wait for C1 to complete before writing driver code; the interface boundary is thin (one `dispatch(prompt: str) -> Iterator[dict]` method).
- `mcp_config.py` supports only stdio transport in v1 (no SSE / Streamable HTTP). Rationale: the 100-tool-per-server IDE limit and env-var-expansion bug (May 2026) make MCP config an informational/diagnostic tool for now, not a first-class dispatch path.
- `auth.py` is documentation-only (prints validation warnings, does not perform OAuth flow). Rationale: Google OAuth is handled entirely by the agy binary; z-harness has no need to touch `~/.gemini/oauth_creds.json`.

---

## Phases

### Phase A — Pre-flight (T001)
Implement `preflight.py`. Run `agy --version` (or `which agy` + version check). If unavailable, emit `agy_preflight_fail` telemetry and raise `DriverUnavailableError` with a message prompting the user to decide whether to defer C3 entirely. If available, emit `agy_preflight_pass` with the version string.

This task is independently runnable and must pass before any Phase B or C tasks are merged.

### Phase B — stream-json parser (T002)
Implement `stream_parser.py`. Parse JSONL lines from `agy -p --output-format stream-json` stdout. Map event types to a normalized dict structure. Handle malformed lines gracefully (emit `agy_stream_parse_error`, continue). Write unit tests using captured fixture data.

Dependency: none (can be done in parallel with Phase A since it only requires knowledge of the stream-json format, which is documented in RESEARCH.md).

### Phase C — CLI-tier driver (T003, T004)
T003: Implement `driver.py` with `AntigravityDriver.dispatch(prompt)` using `subprocess.Popen(['agy', '-p', prompt, '--output-format', 'stream-json'])`. Wire telemetry events. Handle exit code != 0 by parsing the JSONL error event (not by trusting the exit code alone, per RESEARCH.md output-format pitfalls).

T004: Implement `__init__.py` package init; export `AntigravityDriver` and `DriverUnavailableError`; write stub C1-interface conformance comment.

Dependencies: T001 (pre-flight must pass), T002 (stream parser must exist).

### Phase D — MCP config + auth helpers (T005, T006)
T005: Implement `mcp_config.py`. Read `~/.gemini/config/mcp_config.json` (or `.agents/mcp_config.json` for project-scoped). Emit `agy_mcp_config_read`. Write helper that adds a stdio server entry and emits `agy_mcp_config_write`. Guard writes behind opt-in flag. Note the known env-var-expansion bug.

T006: Implement `auth.py`. Validate that `~/.gemini/oauth_creds.json` exists (CLI auth present). Note that SDK-tier requires `GEMINI_API_KEY`; SDK is deferred. Print a warning if neither credential path is detectable.

Dependencies: T001.

### Phase E — READY marker + README (T007, T008)
T007: Write logic (in `driver.py`) to produce `runtime/drivers/antigravity/READY` after a successful end-to-end round-trip (dispatch + parse a minimal probe prompt). Emit `agy_ready_written`.

T008: Write `runtime/drivers/antigravity/README.md` covering: install pre-requisites, how to run pre-flight, auth setup, known limitations (12k limit bypassed by CLI-tier, 100-tool MCP IDE limit, env-var-expansion bug, SDK deferred to v2), handoff notes for C6.

Dependencies: T003 (for READY); T001–T007 (for README — written last).

---

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `agy` still not publicly distributed (npm 404 persists) | High | T001 pre-flight catches this immediately; all other tasks are written speculatively but clearly gated on T001 passing. |
| `agy -p` has the same non-nesting limitation as `agy chat --mode` | Medium | RESEARCH.md open question; add a probe in T003 that detects "nested session" error output and surfaces it as a `DriverConstraint`. |
| stream-json output format changes between agy versions | Medium | `stream_parser.py` emits per-line parse errors rather than crashing; driver logs `agy_version` at pre-flight for correlation. |
| C1 interface not finalized when C3 ships | Medium | C3-D2 resolution: use a stub interface comment; C3 works as a standalone Python module until C1 is ready to wire it. |
| env-var expansion bug in mcp_config.json (May 2026) | High (known) | `mcp_config.py` documents the bug inline; does not attempt env-var substitution; recommends literal paths. |
| `--prompt-interactive` (`-i`) vs `-p` semantics unclear | Low | v1 uses `-p` only (single-shot). Interactive mode is not in scope. |

---

## DRY / KISS / SOLID applied

- **DRY**: `stream_parser.py` is extracted from `driver.py` so it can be unit-tested independently with fixture data. The same parser is used for both dispatch outputs and any future probe outputs.
- **KISS**: Auth is documentation and validation only — no OAuth flow implementation. Google OAuth is `agy`'s responsibility.
- **SOLID**: `AntigravityDriver` implements a thin interface (will match C1's `BaseDriver` contract). Pre-flight, parsing, MCP config, and auth are separate modules so they can be swapped or extended independently.
