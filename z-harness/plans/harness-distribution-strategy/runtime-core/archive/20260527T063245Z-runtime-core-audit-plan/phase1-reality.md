# Phase 1 — Reality Check (C1 runtime-core)

## MUST EXIST NOW — verified

- **`scripts/resolve-provider.py`** ✓ exists; outputs JSON descriptor on stdout (line 285 `print(json.dumps(descriptor))`).
- **`scripts/log-event.sh`** ✓ exists; appends event to events.jsonl.
- **`.z-harness/providers.json`** ✓ exists. Top-level shape matches SPEC's claim: `version: 1`, `roles: object`, `providers: object`. Two providers present: `gemini`, `codex`.

## WILL BE CREATED — no path clash

- **`runtime/`** ✓ does NOT exist anywhere in the repo. Safe to create. All sub-paths under it (contract/, dispatch/, tests/, etc.) are virgin.

## Drift & contract findings

### F1.1 (MAJOR) — `--output-format` drift in providers.json
- C1-T012 acceptance: "Parses `--output-format stream-json` JSONL from the driver's stdout."
- Actual `gemini` provider in `.z-harness/providers.json` uses `"--output-format", "text"` (not `stream-json`).
- Actual `codex` provider uses `["exec", "-"]` with no explicit `--output-format` flag.
- The dispatcher's stream-json parser will receive plain text from existing gemini provider invocations → either zero parsed events (silent breakage) or `is_error` mis-classification.
- Either (a) every provider must move to stream-json before C1's dispatcher is reachable (breaks C1 backward-compat invariant #4), OR (b) the dispatcher must be output-format-agnostic and drivers normalize to a common event shape. T012's spec picks neither and conflicts with itself.

### F1.2 (MAJOR) — `args_template` → `args` resolution unspecified
- Existing provider entries have `args_template: list[str]` (e.g. `["exec", "-"]`).
- `HostDriver.dispatch(command_id: str, args: list[str], env: dict)` (T007 acceptance) takes `args: list[str]` — but doesn't specify where they come from. The Dispatcher.run() (T012) accepts `args: list[str]` too. Neither says "dispatcher composes args from provider_config.args_template + command args".
- An implementer reading T007 + T012 cannot determine: is the caller expected to pre-compose? Does the dispatcher? Does the driver?
- This is a contract gap, not a hallucination.

### F1.3 (MINOR) — schema_version absent from log-event.sh today
- SPEC invariant #2 says "Every event emitted via the dispatcher carries `schema_version: 1`."
- `scripts/log-event.sh` does NOT currently emit `schema_version` — verified by grep. T013 acceptance correctly notes the compat shim "adds `schema_version: 1` to `payload` if missing." ✓ correctly accounted for, but worth flagging that any caller of `log-event.sh` directly (i.e. not via compat.py) will continue producing schema_version-less events. Mixed-shape events.jsonl will result.

### F1.4 (MINOR) — `runtime/compat.py` subprocess to scripts/resolve-provider.py
- T013 acceptance: "Calls `scripts/resolve-provider.py <role>` as a subprocess and returns parsed JSON."
- resolve-provider.py supports being called as a subprocess; output shape matches expectation. ✓ OK.
- Latency note (not a finding, just info): one Python interpreter cold-start per resolve call. For per-command dispatch this is negligible; for fan-out subagent dispatch (z-implement-all spawning 6+ subagents that each resolve) it adds ~100-300ms per resolve. Not a v1 blocker.

## Cross-cluster reality concerns

### F1.5 (MAJOR) — command.schema.json shape vs commands/z-*.md reality
- C1-T001 acceptance: command schema requires `{id, description, argument_hint, body, schema_version}` as a JSON object.
- Actual `commands/z-*.md` files (28 of them) are MARKDOWN with YAML frontmatter — not JSON objects. Frontmatter fields include `description`, `allowed-tools`, `model`, `argument-hint`, etc.
- C6 (shipping) is the cluster that migrates commands TO whatever C1's schema mandates. But C1's schema as written assumes JSON input, not YAML-frontmatter-with-body markdown.
- Either (a) C1's schema describes a parsed JSON projection of the markdown+frontmatter shape (then T001 acceptance should clarify "validated against the parsed projection", not the raw file), OR (b) C1's schema is genuinely the future serialization format and C6 must convert .md→.json files during migration. The SPEC doesn't pick one.
- C6's plan (`/Users/zeke/dev/z-harness/z-harness/plans/harness-distribution-strategy/shipping/PLAN.md` not re-read here, but FILES_TOUCHED shows it still writes .md command files) suggests C6 expects .md to stay. So C1's schema must describe the parsed projection. The C1 SPEC needs to say so.

### F1.6 (MINOR) — `version` field on providers.json vs `schema_version` everywhere else
- providers.json top-level uses `version: 1`. C1's other schemas use `schema_version: 1`. Inconsistent field name.
- C1-T003 spec accepts the existing `version` key (good for backward compat). But it implies provider entries are the only place using `version` while everything else uses `schema_version`. Minor consistency drift, but a real one.
