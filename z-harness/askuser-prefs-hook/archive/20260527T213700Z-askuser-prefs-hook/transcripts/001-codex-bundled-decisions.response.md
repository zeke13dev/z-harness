Tentatives are mostly sound, but I would change D2 and trim D7 for v1.

The two key corrections:

1. Use `workflow.audit_to_amend`, not `workflow.audit-to-amend`.
   Current [scripts/config.py](/Users/zeke/dev/z-harness/scripts/config.py:48) explicitly rejects hyphenated TOML keys and only supports two-segment dotted keys with underscores. Fighting that creates env-var and validation friction.

2. V1 should ship config-backed `hard|none` first, with the memory schema designed but not used for skip decisions unless you are willing to implement JSON memory parsing, enum validation, conflict handling, and tests now.

**D1: Resolver Entry Point**

Use `scripts/config.py resolve-question`.

This is sound because `config.py` already owns the 4-layer precedence model, enum validation, config source tracking, and clean stdout/stderr discipline. A standalone script would either duplicate loader behavior or call back into `config.py`, creating two public surfaces.

Gemini’s stdout concern is real but manageable. Extending `config.py` does not automatically avoid pollution; discipline and tests do. Validation should include:

```bash
out="$(scripts/config.py resolve-question --payload payload.json)"
python3 -m json.tool <<<"$out" >/dev/null
```

Also test error paths: invalid config, unknown `question_id`, malformed payload. Diagnostics must go to stderr; stdout must be either exactly one JSON object or empty only on fatal process failure.

Return contract should be tested by subprocess, not just unit tests, because import-time prints, logging, or helper subprocess output are what corrupt consumers.

**D2: Question ID Naming**

Push back on the tentative syntax.

Use:

```toml
[workflow]
audit_to_amend = "amend"
slug_confirm = "skip"
```

And canonical IDs:

```text
workflow.audit_to_amend
workflow.slug_confirm
```

Do not use `workflow.audit-to-amend`. The existing config system rejects hyphenated TOML keys and env var derivation is already aligned around underscores: `Z_HARNESS_WORKFLOW_AUDIT_TO_AMEND`.

The `[workflow]` section is the right namespace. `[askuser]` is too implementation-shaped; workflow preference is the user concept. Fingerprint keys are weaker because prompt prose is unstable.

Concrete enum pattern:

```python
QUESTION_IDS = {
    "workflow.audit_to_amend": {
        "config_key": "workflow.audit_to_amend",
        "choices": {"ask", "amend", "stop"},
    },
    "workflow.slug_confirm": {
        "config_key": "workflow.slug_confirm",
        "choices": {"ask", "skip", "prefill"},
    },
}
```

Then validate all of these against `DEFAULTS`/`VALIDATORS` at startup or in tests:

```python
assert set(QUESTION_IDS) <= set(VALIDATORS)
```

Or better: derive valid question IDs from one registry and use it for config defaults, memory validation, CLI payload validation, and docs generation. One source of truth prevents `audit-to-amend` vs `audit_to_amend` drift.

**D3: Memory Schema**

The schema is sound:

```json
{
  "type": "routing-preference",
  "question_id": "workflow.audit_to_amend",
  "value": "amend",
  "scope": "global",
  "strength": "very_strong",
  "reason": "User explicitly asked to always amend after audits."
}
```

But Gemini is right: do not grep `MEMORIES-FLAT.md` for resolver behavior. That file is derived/search-oriented and too brittle for a wire contract. Parse `docs/llm/<slug>.json` directly and read `memories[]`.

If global memories live outside the repo, the resolver needs an explicit global memory location. If that location does not exist yet, do not pretend two-level memory resolution is implemented. V1 can still support two-level config and defer two-level memory.

Important interaction: D3 depends on D2’s registry. `/z-suggest-memory` should reject unknown `question_id`, unknown `value` for that question, invalid `scope`, and invalid `strength`. Unknown IDs should fail loudly, not just result in “no memory found.”

**D5: Return Contract**

JSON on stdout is the right call.

Use a stable envelope slightly wider than the tentative:

```json
{
  "result": "skip",
  "default": "amend",
  "source": "config",
  "rule_id": "workflow.audit_to_amend",
  "strength": "hard",
  "reason": "repo config",
  "sources": []
}
```

Keep `result`, `default`, `source`, `rule_id`, and `strength` as required. Additive fields are fine later. Avoid exit-code-only; callers need to distinguish ask/prefill/skip/conflict and surface source text.

Recommended semantics:

- `0`: valid resolution JSON emitted
- `2`: bad payload/schema/config
- `3`: unknown question ID
- `4`: I/O
- stdout: JSON only
- stderr: diagnostics only

For `conflict`, still return JSON with `result: "ask"` and `source: "conflict"` so call sites can show sources.

**D7: Strength Heuristic**

Explicit strength is the right long-term design. Regex inference is brittle; count-based inference rewards duplicated memories and stale behavior.

But I would not let user-chosen `very_strong` alone skip in v1 unless you also implement the full safety model:

- parse JSON memories directly
- validate question IDs against registry
- validate values against per-question choices
- detect project/global conflicts
- detect config/memory conflicts
- run collision checks even on `very_strong:skip`
- log the resolution source

Without those, memory skip is too easy to get wrong silently.

Pragmatic v1:

- `hard`: config/env explicit -> skip or prefill
- `none`: ask
- memory routing schema may be accepted by `/z-suggest-memory`, but resolver either ignores memory for routing or uses it only for prefill after validation

That preserves the public schema while avoiding a half-built policy engine.

**Interaction Risks**

D1 ↔ D5: `config.py resolve-question` must have a stricter stdout contract than human-facing subcommands. JSON consumers make accidental prints a breaking bug.

D2 ↔ D3: shared `question_id` registry is mandatory. Otherwise TOML and memories can silently miss each other.

D2 ↔ config.py: hyphenated IDs conflict with existing key validation. Use underscores.

D3 ↔ D7: explicit strength only works if `/z-suggest-memory` is the sole writer and validates the enum. Hand-authored or malformed memories must be ignored with a warning or rejected by a validator.

D5 ↔ call sites: call sites should branch only on `result`; they should not re-derive policy from `source` or `strength`.

D7 ↔ collision checks: collision checks must be outside the resolver result. Even if resolver says `skip`, the slug path must still check for existing plan dirs before proceeding.

**V1 Viability**

Yes, v1 is viable with config-only hard tier plus typed question IDs. That is enough for audit→amend and slug-confirmation if those are deterministic user preferences.

I would not include memory-based `very_strong -> skip` in v1 unless you treat memory parsing and enum sync as first-class implementation work. The safer v1 is:

```text
config hard -> skip/prefill
memory valid strong/very_strong -> maybe prefill only, or deferred
none/conflict -> ask
```

That still fits the chosen architecture and avoids overcommitting the first retrofit across ~9 prose sites.
tokens used
73,300
**Bottom Line**

Tentatives are mostly sound, but I would change D2 and trim D7 for v1.

The two key corrections:

1. Use `workflow.audit_to_amend`, not `workflow.audit-to-amend`.
   Current [scripts/config.py](/Users/zeke/dev/z-harness/scripts/config.py:48) explicitly rejects hyphenated TOML keys and only supports two-segment dotted keys with underscores. Fighting that creates env-var and validation friction.

2. V1 should ship config-backed `hard|none` first, with the memory schema designed but not used for skip decisions unless you are willing to implement JSON memory parsing, enum validation, conflict handling, and tests now.

**D1: Resolver Entry Point**

Use `scripts/config.py resolve-question`.

This is sound because `config.py` already owns the 4-layer precedence model, enum validation, config source tracking, and clean stdout/stderr discipline. A standalone script would either duplicate loader behavior or call back into `config.py`, creating two public surfaces.

Gemini’s stdout concern is real but manageable. Extending `config.py` does not automatically avoid pollution; discipline and tests do. Validation should include:

```bash
out="$(scripts/config.py resolve-question --payload payload.json)"
python3 -m json.tool <<<"$out" >/dev/null
```

Also test error paths: invalid config, unknown `question_id`, malformed payload. Diagnostics must go to stderr; stdout must be either exactly one JSON object or empty only on fatal process failure.

Return contract should be tested by subprocess, not just unit tests, because import-time prints, logging, or helper subprocess output are what corrupt consumers.

**D2: Question ID Naming**

Push back on the tentative syntax.

Use:

```toml
[workflow]
audit_to_amend = "amend"
slug_confirm = "skip"
```

And canonical IDs:

```text
workflow.audit_to_amend
workflow.slug_confirm
```

Do not use `workflow.audit-to-amend`. The existing config system rejects hyphenated TOML keys and env var derivation is already aligned around underscores: `Z_HARNESS_WORKFLOW_AUDIT_TO_AMEND`.

The `[workflow]` section is the right namespace. `[askuser]` is too implementation-shaped; workflow preference is the user concept. Fingerprint keys are weaker because prompt prose is unstable.

Concrete enum pattern:

```python
QUESTION_IDS = {
    "workflow.audit_to_amend": {
        "config_key": "workflow.audit_to_amend",
        "choices": {"ask", "amend", "stop"},
    },
    "workflow.slug_confirm": {
        "config_key": "workflow.slug_confirm",
        "choices": {"ask", "skip", "prefill"},
    },
}
```

Then validate all of these against `DEFAULTS`/`VALIDATORS` at startup or in tests:

```python
assert set(QUESTION_IDS) <= set(VALIDATORS)
```

Or better: derive valid question IDs from one registry and use it for config defaults, memory validation, CLI payload validation, and docs generation. One source of truth prevents `audit-to-amend` vs `audit_to_amend` drift.

**D3: Memory Schema**

The schema is sound:

```json
{
  "type": "routing-preference",
  "question_id": "workflow.audit_to_amend",
  "value": "amend",
  "scope": "global",
  "strength": "very_strong",
  "reason": "User explicitly asked to always amend after audits."
}
```

But Gemini is right: do not grep `MEMORIES-FLAT.md` for resolver behavior. That file is derived/search-oriented and too brittle for a wire contract. Parse `docs/llm/<slug>.json` directly and read `memories[]`.

If global memories live outside the repo, the resolver needs an explicit global memory location. If that location does not exist yet, do not pretend two-level memory resolution is implemented. V1 can still support two-level config and defer two-level memory.

Important interaction: D3 depends on D2’s registry. `/z-suggest-memory` should reject unknown `question_id`, unknown `value` for that question, invalid `scope`, and invalid `strength`. Unknown IDs should fail loudly, not just result in “no memory found.”

**D5: Return Contract**

JSON on stdout is the right call.

Use a stable envelope slightly wider than the tentative:

```json
{
  "result": "skip",
  "default": "amend",
  "source": "config",
  "rule_id": "workflow.audit_to_amend",
  "strength": "hard",
  "reason": "repo config",
  "sources": []
}
```

Keep `result`, `default`, `source`, `rule_id`, and `strength` as required. Additive fields are fine later. Avoid exit-code-only; callers need to distinguish ask/prefill/skip/conflict and surface source text.

Recommended semantics:

- `0`: valid resolution JSON emitted
- `2`: bad payload/schema/config
- `3`: unknown question ID
- `4`: I/O
- stdout: JSON only
- stderr: diagnostics only

For `conflict`, still return JSON with `result: "ask"` and `source: "conflict"` so call sites can show sources.

**D7: Strength Heuristic**

Explicit strength is the right long-term design. Regex inference is brittle; count-based inference rewards duplicated memories and stale behavior.

But I would not let user-chosen `very_strong` alone skip in v1 unless you also implement the full safety model:

- parse JSON memories directly
- validate question IDs against registry
- validate values against per-question choices
- detect project/global conflicts
- detect config/memory conflicts
- run collision checks even on `very_strong:skip`
- log the resolution source

Without those, memory skip is too easy to get wrong silently.

Pragmatic v1:

- `hard`: config/env explicit -> skip or prefill
- `none`: ask
- memory routing schema may be accepted by `/z-suggest-memory`, but resolver either ignores memory for routing or uses it only for prefill after validation

That preserves the public schema while avoiding a half-built policy engine.

**Interaction Risks**

D1 ↔ D5: `config.py resolve-question` must have a stricter stdout contract than human-facing subcommands. JSON consumers make accidental prints a breaking bug.

D2 ↔ D3: shared `question_id` registry is mandatory. Otherwise TOML and memories can silently miss each other.

D2 ↔ config.py: hyphenated IDs conflict with existing key validation. Use underscores.

D3 ↔ D7: explicit strength only works if `/z-suggest-memory` is the sole writer and validates the enum. Hand-authored or malformed memories must be ignored with a warning or rejected by a validator.

D5 ↔ call sites: call sites should branch only on `result`; they should not re-derive policy from `source` or `strength`.

D7 ↔ collision checks: collision checks must be outside the resolver result. Even if resolver says `skip`, the slug path must still check for existing plan dirs before proceeding.

**V1 Viability**

Yes, v1 is viable with config-only hard tier plus typed question IDs. That is enough for audit→amend and slug-confirmation if those are deterministic user preferences.

I would not include memory-based `very_strong -> skip` in v1 unless you treat memory parsing and enum sync as first-class implementation work. The safer v1 is:

```text
config hard -> skip/prefill
memory valid strong/very_strong -> maybe prefill only, or deferred
none/conflict -> ask
```

That still fits the chosen architecture and avoids overcommitting the first retrofit across ~9 prose sites.
