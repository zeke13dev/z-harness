# Decisions — C5 conformance-harness

Run: 20260527T050549Z-harness-distribution-strategy

## Resolved (unilateral)

- C5-D1, pilot-command-z-do, `/z-do` chosen as the pilot conformance command; it is the smallest command that exercises subagent dispatch, AskUserQuestion, push notification, event log, and final-artifact write without hitting Antigravity's 12k body limit that breaks `/z-plan`.
- C5-D2, equivalence-four-criteria, "equivalent artifacts" means: (a) same set of event type+field names in events.jsonl modulo timestamps/run-ids/model-latency; (b) same set of artifact file paths created (path names, not byte content where nondeterminism applies); (c) same exit status (0 or nonzero); (d) normalized artifact content matches golden fixture after stripping known nondeterministic fields per source. Byte-identical comparison is explicitly rejected.
- C5-D3, runner-python, the conformance runner is a Python script (`tests/conformance/run_conformance.py`); z-harness scripting baseline is Python and the existing `tests/` directory already has Python tests with subprocess invocation patterns.
- C5-D4, ci-path-filter, CI runs the conformance matrix only when a PR touches `tests/conformance/**`, `runtime/**`, or `drivers/**`; all other PRs skip it; v1 is a GitHub Actions path filter + manual `make conformance` local target.
- C5-D5, llm-mock-replay, conformance runner supports two modes: `--mode=replay` (load recorded LLM response fixtures, fully deterministic, required for CI) and `--mode=live` (real model calls, manual only); fixture recording is a separate `--record` flag that captures a live run and writes the replay fixture.
