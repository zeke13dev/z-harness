## D1: Output Contract Shape

**Recommendation:** c

**Reasoning:** Hybrid fits the agent's two jobs: grep-friendly routing fields for orchestration and JSON for structured chunk metadata. This matches existing split patterns: `planning-router` for simple routing signals, `review-agent` for structured parseable payloads. Keep the line-prefix fields authoritative for mode/routing, and make JSON authoritative for chunk details.

**Interaction warnings:** D1 strongly interacts with D2 because the archived/live `SCOPE*.json` should be derived from the JSON payload plus the prefix routing fields, not from two divergent schemas. It also interacts with D7 because calibration should parse the same contract the orchestrator parses.

## D2: SCOPE.json Schema + Location

**Recommendation:** c

**Reasoning:** Both live and archived copies serve different operational needs: live for latest downstream routing context, archive for forensics and calibration. Namespacing by host command avoids collision between `/z-audit` and `/z-brainstorm` on the same slug. Versioning should live inside the JSON so archived files remain self-describing.

**Interaction warnings:** D2 depends on D1 having one canonical structured payload. It also supports D7 directly because calibration replay can consume archived `SCOPE-audit.json` / `SCOPE-brainstorm.json` as prior predictions once runs accumulate.

## D4: Axis Discovery Heuristics

**Recommendation:** c

**Reasoning:** Hybrid gives the orchestrator a way to preserve user intent through `preferred_axes` while still letting the agent discover real structural seams from files, tasks, dimensions, or prior artifacts. Caller-only taxonomy is too brittle for early Phase 0 use, and free-form-only risks producing axes that are technically plausible but operationally unhelpful. The agent should report evidence for the chosen axis so escalation is auditable.

**Interaction warnings:** D4 affects D1 because chunk metadata must include enough axis evidence to explain why a split is natural. It also affects D8 because axis quality should be considered separately from classification correctness during calibration.

## D7: Calibration Replay Protocol

**Recommendation:** a

**Reasoning:** Calibration should test the actual Haiku agent behavior, not a Python proxy for it. Five or six historical runs is small enough that full LLM replay is acceptable, especially because this agent gates later fanout behavior. Deterministic checks can still validate artifact shape, but should not replace replay.

**Interaction warnings:** D7 depends on D1 and D2 being stable enough to parse consistently across runs. It also interacts with D8 because replay needs a clear ground-truth rubric before results are meaningful.

## D8: Ground-Truth Label

**Recommendation:** c

**Reasoning:** Combined rubric is the best fit because scope is not reducible to task count. `tasks_total`, `tasks_complexity`, and escalation/fanout evidence each capture different failure modes: size, difficulty, and actual runtime pressure. Disagreement among the signals should produce a lower-confidence ground-truth label rather than forcing a simplistic answer.

**Interaction warnings:** D8 interacts with D7 because calibration output should distinguish "wrong classification" from "ambiguous historical ground truth." It also interacts with D4 because a run may be correctly classified as HEAVY but still choose a poor parallelization axis.

## Cross-Cutting Concerns

All five tentative calls lean toward richer structure. That is reasonable for a Phase 0 gate, but v1a should keep one simplifying rule: line-prefix fields are for orchestration, `SCOPE*.json` is for durable structured state, and calibration reads the same durable schema.

D7 can become a regression suite for `scope-probe`: every historical replay should record input summary, emitted contract, parsed `SCOPE*.json`, ground-truth rubric, and mismatch reason.
