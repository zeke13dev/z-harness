# T006 Review: ConcurrencyConfig renaming and extension

**Verdict: FAIL**

**Blockers: 1 | Majors: 1**

## Findings

### Blocker: Exception handling regression in load_config

**Location:** `scripts/hermes/config.py:135`

The exception handler was narrowed from `except Exception:` to `except (ValueError, TypeError, OSError):`. However, `yaml.safe_load()` raises `yaml.YAMLError` and its subclasses (e.g., `ParserError`, `ScannerError`) which are **not** subclasses of `ValueError`, `TypeError`, or `OSError`. 

If a user has a malformed `hermes-config.yaml`, the parser will now raise an uncaught `yaml.YAMLError` and crash `load_config()` instead of gracefully falling through to defaults (the original fail-safe behavior). This violates INV-4 (fail-safe serialization).

**Fix:** Either revert to `except Exception:`, or extend the tuple to include `yaml.YAMLError`: `except (ValueError, TypeError, OSError, yaml.YAMLError) if yaml else (ValueError, TypeError, OSError)`. The intent to narrow exceptions is valid (avoid masking logic bugs), but YAML parsing errors must be caught.

---

### Major: Empty string in _bool_coerce returns True instead of False

**Location:** `scripts/hermes/config.py:24`

The `_bool_coerce` function returns `True` for empty strings: `"".strip().lower() not in ("0", "false", "no", "off")` evaluates to `True`. While unlikely in practice (env vars are typically absent or have a value), this contradicts the docstring's intent ("maps falsey strings ... to False") and the test for "0" → False.

**Fix:** Add explicit empty-string check: `return val.strip().lower() not in ("0", "false", "no", "off", "")` or check `if not val.strip(): return False` before the lookup.

Alternatively, if empty is considered "not set" and should default to the original value (not override), skip the coerce on empty strings in `_env_override()` — but the current code doesn't do that.

---

## Verification Summary

✓ **Rename completeness (critical):** PASSED
  - No live code references to `max_parallel_sessions` anywhere in scripts/, runtime/, z_harness_cli/, exports/ — all confirm the field is gone.
  - Test `test_no_max_parallel_sessions_attribute` explicitly validates the old name no longer exists.
  - Comment at line 145 clearly documents the HERMES_MAX_PARALLEL → max_parallel_workstreams binding.
  - No stale references in docs/human/ or docs/schemas/.

✓ **Default flip: 3→1 (INV-5):** PASSED
  - `max_parallel_workstreams: int = 1` at line 38.
  - Test `test_max_parallel_workstreams_default_is_1` asserts this.
  - HERMES_MAX_PARALLEL env override still binds correctly at line 147.

✓ **Bool env parsing "0"→False:** MOSTLY PASSED
  - _bool_coerce correctly maps "0"/"false"/"no"/"off" → False and "1"/"true"/"yes"/"on" → True.
  - Test `test_hermes_serialize_all_env_false_string` exercises "0" → False path.
  - **Exception:** empty string returns True instead of False (see Major above).

✓ **No duplicate dataclass:** PASSED
  - Only one `ConcurrencyConfig` in config.py (line 34).
  - HermesConfig properly wires it at line 68.

✓ **New fields with correct defaults:** PASSED
  - `max_parallel_plans: int = 1` (line 39)
  - `serialize_all: bool = False` (line 40)
  - `serialize_high_severity: bool = True` (line 41)
  - File and env override paths present and tested.

✓ **Test coverage:** 27 tests present, comprehensive coverage of defaults, file override, env override, and bool parsing — but see Blocker above regarding exception handling.

---

## Implementer claims vs. actual code

**RATIONALE (stated):** extend existing dormant ConcurrencyConfig, rename field, flip default 1 for sequential-by-default (INV-5), add new concurrency controls.

**Code matches rationale:** Yes, all claimed changes are present and correctly implemented — except for the exception-handling narrowing, which was a side change not justified in the task description.

**TRIED:** None claimed. No contradictions detected in the code.

**DEVIATIONS:** Implementer narrowed exception handler from `except Exception:` to `except (ValueError, TypeError, OSError)`. This is an undocumented change with negative consequences (see Blocker). The code does not show a conscious trade-off; it looks like an unvetted refactor to "only catch known errors." That's a reasonable goal in principle, but YAML errors must be included in the list.

---

## Impact assessment

- **Blocker:** Will cause production failures on malformed config files. Must fix before merging.
- **Major:** Low probability in practice (env var is either absent or has a non-empty value), but violates the test's own intent.
- Tests are extensive but do not cover malformed YAML files (no test exercises `yaml.safe_load()` failure path).
