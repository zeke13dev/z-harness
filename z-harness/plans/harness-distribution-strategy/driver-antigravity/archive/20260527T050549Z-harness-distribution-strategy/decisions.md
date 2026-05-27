# Decisions — C3 driver-antigravity

run-id: 20260527T050549Z-harness-distribution-strategy
cluster-id: C3

## Resolved unilaterally

- C3-D1, defer-sdk-to-v2, Extension SDK tier (sdk.cascade / sdk.monitor / sdk.commands / sdk.ls) is deferred entirely to v2; no SDK code is written in v1. Rationale: kanezal.github.io docs are community reverse-engineering with no first-party API reference confirmed; agy itself may not be publicly distributed yet; SDK requires GEMINI_API_KEY (no OAuth) adding a new credential requirement that is out of scope for v1 CLI-tier work.

- C3-D2, python-subprocess-popen, CLI-tier driver is implemented as a Python module using subprocess.Popen to drive `agy -p --output-format stream-json`, iterating stdout JSONL lines. Rationale: consistent with how export-codex.py and the existing harness scripts work; Python is already the harness scripting language; no new external dependency needed. Driver will conform to whatever interface C1 (runtime-core) publishes rather than defining its own public contract.

- C3-D3, coexist-no-cutover, C3 writes the new driver at runtime/drivers/antigravity/ and does NOT touch export-agy.py. Cutover coordination is C6's responsibility. C3 delivers a driver that is ready for C6 to wire up; C3 tasks include a readiness signal (READY file or capability flag) for C6 to consume. Rationale: touching export-agy.py from C3 would be a scope leak into C6's domain; keeping them separate keeps the blast radius of C3 failures contained.
