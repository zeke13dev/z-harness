# Review Prompt for T006: ConcurrencyConfig Renaming & Extension

## Task
T006: Extend the existing dormant ConcurrencyConfig (audit M3): rename max_parallel_sessions→max_parallel_workstreams (single authoritative field), flip default 3→1 (INV-5), add max_parallel_plans/serialize_all/serialize_high_severity, wire through file+env precedence. No duplicate dataclass.

## Acceptance Criteria
1. Single ConcurrencyConfig
2. max_parallel_workstreams default 1
3. HERMES_MAX_PARALLEL still overrides
4. New fields present with defaults
5. env/file override works
6. Existing config tests green

## SPEC Excerpt (INV-5 and config section)
INV-5 (cap=1 ≡ legacy sequential): with `max_parallel_workstreams=1` the new scheduler must be behaviorally equivalent to today's sequential loop (same completion/merge order outcomes).

### File: scripts/hermes/config.py
- Extend the existing ConcurrencyConfig (audit M3) — config.py already defines ConcurrencyConfig(max_parallel_sessions=3), wired into load_config and env-overridable via HERMES_MAX_PARALLEL, but dormant (never read by the executor). Do NOT add a second Concurrency dataclass.
- Reconcile naming: max_parallel_workstreams is the canonical "live sessions" knob — rename max_parallel_sessions→max_parallel_workstreams (updating the HERMES_MAX_PARALLEL binding and the load_config block at config.py:90/120), or keep one authoritative field aliased. Add max_parallel_plans: int = 1, serialize_all: bool = False, serialize_high_severity: bool = True to the same dataclass.
- Flip the default from 3 to 1 so defaults reproduce today's sequential behavior (INV-5); document the default change. Wire through the existing timeouts/retry/paths env/file precedence pattern.

### Tests
- Defaults present; env/file override path; cap=1 is the default.

## Changed Files
- /Users/zeke/dev/z-harness/scripts/hermes/config.py
- /Users/zeke/dev/z-harness/tests/test_hermes_config.py (NEW, 27 tests)

## Critical Review Focus

1. **RENAME COMPLETENESS (critical):** independently grep -rn "max_parallel_sessions" across the WHOLE repo (scripts, tests, docs/, exports/, runtime/, z_harness_cli/, mcp). The implementer claims only comment/assertion-string occurrences remain. Verify NO live code path anywhere still reads/writes `max_parallel_sessions` (a stale reader would get the default silently). Pay attention to: docs/human/config.md (does it document the old key?), any config schema/example JSON, exports/ mirrors. Flag any stale live reference as a blocker; a stale doc mention is a minor.

2. **DEFAULT FLIP:** max_parallel_workstreams default is 1 (not 3). HERMES_MAX_PARALLEL binds to the renamed field.

3. **BOOL ENV PARSING:** the new bool env vars (HERMES_SERIALIZE_ALL, HERMES_SERIALIZE_HIGH_SEVERITY) must NOT fall into the bool("0")==True trap. Verify _bool_coerce maps "0"/"false"/"no"/"" → False and "1"/"true" → True, and that a test exercises "0"→False.

4. **DEVIATION CHECK:** implementer narrowed `except Exception` → `except (ValueError, TypeError, OSError)` in the config file-load block. Confirm this doesn't now let a previously-swallowed exception (e.g. json.JSONDecodeError — is it a subclass of ValueError? yes) escape and crash load_config on a malformed config file. If JSONDecodeError/yaml errors are NOT covered by the narrowed tuple, that's a MAJOR regression (load_config would raise where it used to degrade to defaults). Check which parser is used (json vs yaml) and whether its error type is in the tuple.

5. No duplicate Concurrency dataclass introduced; HermesConfig still wires it.

## Scrutiny Strategy

- Start with rename completeness via full-repo grep
- Verify exception handling safety by checking yaml.YAMLError hierarchy
- Validate _bool_coerce edge cases
- Confirm dataclass structure and wiring
- Review test assertions against acceptance criteria
