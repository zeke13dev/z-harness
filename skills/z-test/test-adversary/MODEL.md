# test-adversary — Adversarial counterexample generator

**Type:** Subagent model for `/z-test` Phase 2.5
**Purpose:** Generate plausible adversarial inputs that violate invariants, feeding into the cross-LLM (Phase 3) for validation.

## Interface

### Input
- Target invariant (from INVARIANTS.json): `id`, `description`, `fixture_schema`, `fixture_defaults`, `failure_class`, `tags`
- Draft test entries from Phase 2 (behavioral test cases for the invariant)
- The invariant's `fixture_schema` (required fields, types, allowed values)

### Output
Structured JSON array. Each entry:

```json
{
  "invariant_id": "inv_001",
  "test_id": "TEST-001",
  "adversarial_scenario": "<one-line description of the adversarial input>",
  "fixture": { /* fixture object conforming to fixture_schema */ },
  "expected_violation": "<description of what should fail>",
  "subtlety_rating": "obvious | subtle | sneaky",
  "realism": "plausible | edge_case | synthetic"
}
```

## Behavioral specifications

### What qualifies as a good adversarial fixture

1. **Plausible but wrong.** The fixture should look like a realistic data point that happens to violate the invariant. Not a clearly invalid input (NaN, null in required field) but a structurally valid input that triggers the failure class.

2. **Structural validity.** Every fixture MUST conform to the invariant's `fixture_schema`. If the schema requires `price: number`, the fixture's price must be a number. Think: "a real system would produce this" not "this is obviously corrupt data."

3. **Subtlety matters.** The rating is:
   - `obvious` — any test would catch this (e.g., price = -1 for a positive-price invariant). Low value for falsification.
   - `subtle` — a good test would catch it but a weak one might not (e.g., 15-minute clock drift causing a stale update after a valid timestamp boundary). High falsification value.
   - `sneaky` — a realistic edge case that current tests almost certainly miss (e.g., fee rounding at 0.5 decimal tie in a specific direction). Maximum falsification value.

4. **Avoid trivial failure.** An adversarial fixture where the violation is trivially detectable (null price, negative quantity, wrong type) is NOT a good adversarial fixture. The point is to find failures that pass schema validation but violate behavioral constraints.

### Examples

**Invariant:** "Feed timestamps must be strictly monotonic — no duplicate or decreasing timestamps"
**Fixture schema:** `{"ts": "number (unix ms)", "price": "number", "volume": "number"}`
**Good adversarial fixture:** `{"ts": 1700000000000, "price": 100.0, "volume": 1000}` followed by `{"ts": 1700000000000, "price": 99.5, "volume": 500}` — duplicate timestamp with different data. Structurally valid, subtly wrong.
**Bad adversarial fixture:** `{"ts": null, "price": NaN, "volume": -1}` — trivially corrupt. Adds no falsification value.

## Usage

This subagent is called in Phase 2.5 of `/z-test`. Its output feeds into Phase 3 (cross-LLM consult) as context, so the consultants can evaluate: "Will the current test fixture catch this adversarial scenario?"

The cross-LLM consultants (Phase 3) can:
- Accept the adversarial fixture as-is (test is sufficient)
- Reject it (adversarial scenario is unrealistic or doesn't actually violate the invariant)
- Suggest a modified fixture (the adversarial scenario is real but the fixture needs adjustment)
