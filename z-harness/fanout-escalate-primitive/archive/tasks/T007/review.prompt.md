You are reviewing code that Claude just wrote for task T007: Unit-test the calibration harness against synthetic fixtures.

Spec (excerpt from SPEC.md):
- `scripts/scope-probe-calibrate.py` emits `scripts/calibration-epoch-<N>.json`.
- Exit codes: 0 — no tripwires fired; 1 — at least one tripwire fired.

Acceptance criteria:
- 3 fake archive runs (LIGHT/MEDIUM/HEAVY ground-truth).
- classify_ground_truth matches expected on all 3.
- Confusion matrix correctly counts matches.
- Tripwire detection fires on synthetic all-MEDIUM set.
- Test exits 0 on success, 1 on failure.

The diff introduces test-scope-probe-calibrate.py, a new unit test suite that imports and exercises the production module's core functions.
