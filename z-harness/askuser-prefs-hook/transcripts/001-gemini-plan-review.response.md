## Gemini consultation: askuser-prefs-hook plan critique

### Finding 1: 5-tier signal-strength model mapping flaw
**Severity:** Critical  
**Citation:** SPEC.md lines 84–101 (tier derivation), line 11 (tier → result mapping)

For `workflow.slug_confirm`, valid config values (`"ask"`, `"skip"`, `"prefill"`) are also interaction results. If a user explicitly configures `workflow.slug_confirm = "prefill"`, step 3 assigns it `hard` tier (not "ask"), and step 11 maps this to `skip`. The resolver incorrectly overrides the user's explicit `"prefill"` preference with `"skip"` action.

### Finding 2: Bash error swallowing causes silent degradation
**Severity:** Major  
**Citation:** SPEC.md lines 166–180 (retrofit prose), lines 214–223 (invariants)

The retrofit prose pipes the resolver call to `2>/dev/null`. If there is a typo in the `question_id` argument (e.g., `audit_to_amen`), `config.py` exits with an error but bash silences it. `$RESULT` becomes empty, all conditional branches fail, and the skill falls through to unpredictable behavior (hang, skip without default, or hallucination).

### Finding 3: Proposer cannot detect "slug-derive-confirm answered 'yes'"
**Severity:** Critical  
**Citation:** SPEC.md lines 133–154 (proposer detection)

The proposer is instructed to detect the pattern "z-fix → slug-derive-confirm answered 'yes' × 3" by walking `metrics.jsonl`. However, no telemetry event currently records interactive `AskUserQuestion` answers (only `run_start` events track command execution). The proposer has zero data to determine whether the user answered "yes", "no", or "change it", making this detection impossible to implement.

### Finding 4: Incompatible callsites for identical retrofits
**Severity:** Critical  
**Citation:** PLAN.md lines 49–53 (Phase C), SPEC.md lines 189–191 (slug-confirm retrofit)

The plan mandates "identical pattern" retrofits across 9 sites, but `z-plan.md:21` is a pure collision-safety check. If a `skip` result is applied here, it bypasses the collision check entirely, violating the stated invariant "Safety checks survive skip." The callsites are semantically disjointed and cannot share one uniform retrofit.

### Finding 5: Conflict tier creates a permanent loop
**Severity:** Major  
**Citation:** SPEC.md lines 166–180 (retrofit prose), lines 87–96 (conflict logic)

When config and memory disagree, the retrofit prose displays both but provides no mechanism for writing the user's resolution back to config or memory. The skill prose lacks instructions to patch the underlying discrepancy. The user will be forced to resolve the same conflict on every subsequent run.

---

**Additional observations:**
- The startup assertion (line 77) validates Python data structures but doesn't catch question_id typos at invocation time in skill prose.
- Phase G verification tests do not include a test for the error-swallowing scenario (malformed `question_id` in a shell invocation).
- The proposer's v1 patterns (audit→amend, fix→yes) cannot both be detected from `metrics.jsonl` with current telemetry shape.
