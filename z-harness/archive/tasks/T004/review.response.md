$RUN" missing_complexity_stamp \
z-harness/archive/tasks/per-task-model-selection/review.response.md:83:commands/z-implement-next.md:52:  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
z-harness/archive/tasks/per-task-model-selection/review.response.md:89:commands/z-implement-all.md:165:  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
z-harness/archive/tasks/per-task-model-selection/review.response.md:132:+  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
z-harness/archive/tasks/per-task-model-selection/review.response.md:186:+  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
z-harness/archive/tasks/per-task-model-selection/review.response.md:211:    Output lands under `z-harness/<slug>/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
z-harness/archive/tasks/per-task-model-selection/review.response.md:245: bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
z-harness/archive/tasks/per-task-model-selection/review.response.md:278:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
z-harness/archive/tasks/per-task-model-selection/review.response.md:325:    52	  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
z-harness/archive/tasks/per-task-model-selection/review.response.md:354:   165	  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
z-harness/archive/tasks/per-task-model-selection/review.response.md:398:   165	  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
z-harness/archive/tasks/per-task-model-selection/review.response.md:465:    52	  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:74:+-- `scripts` — Subagents use utility scripts to report telemetry log-events, time phase durations, and sync remote file structures.
z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:75:++- `scripts` — Subagents use `scripts/log-phase.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`, and `scripts/resolve-provider.sh` to emit telemetry, detect timeout availability, and resolve provider CLIs at runtime.
z-harness/archive/brainstorm-memory-loop-001/transcripts/001-codex-brainstorm.prompt.md:7:**Memory authoring**: `/z-suggest-memory` is the sole authoring path for `docs/llm/<slug>.json` memories. Schema-validated, atomic writes. Auto-regenerates `docs/llm/MEMORIES-FLAT.md` (format: `[<slug>] [<TYPE> <DATE>] [<source>] <text> (tags: t1, t2)`). Controlled tag seed at `docs/llm/TAGS.txt` (15 tags: correctness, perf, data-quality, schema, time-window, units, api-boundary, retry-loop, race-condition, dependency, deprecation, lossy-default, ux, observability, compliance). Default outcome in suggest-memory is **Cancel** — low bar; only persist novel anti-patterns or decision rationale.
z-harness/archive/brainstorm-memory-loop-001/transcripts/001-codex-brainstorm.prompt.md:9:**Post-run hooks (current)**: `/z-implement-all` and `/z-review-all` emit telemetry via `scripts/log-event.sh` to `$RUN_DIR/events.jsonl` (`run_start`, `phase_end`, `task_start`, `task_review_retry`, `doc_drift`, etc.). **No auto-invocation of `/z-improve` after completion** — entirely opt-in. `/z-improve` Phase 7 mandatorily calls `/z-suggest-memory --concept-hints <slugs>` after the user accepts harness edits.
z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:53:-- `scripts` — Subagents use utility scripts to report telemetry log-events, time phase durations, and sync remote file structures.
z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:54:+- `scripts` — Subagents use `scripts/log-phase.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`, and `scripts/resolve-provider.sh` to emit telemetry, detect timeout availability, and resolve provider CLIs at runtime.
z-harness/archive/tasks/T002/review.prompt.md:1:You are reviewing code that Claude just wrote for task T002: Add compaction_pause event type to log-event docs.
z-harness/archive/tasks/T006/review.response.md:958:8110|++   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
z-harness/archive/tasks/T006/review.response.md:1090:8630|++   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
z-harness/archive/tasks/T006/review.response.md:1140:8836|++   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
z-harness/archive/tasks/T006/review.response.md:1569:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
z-harness/archive/tasks/T006/review.response.md:1699:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_end \
z-harness/archive/tasks/T006/review.response.md:1772:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
z-harness/archive/tasks/T006/review.response.md:1902:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_end \
z-harness/archive/tasks/T006/review.response.md:2283:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
z-harness/archive/tasks/T006/review.response.md:2413:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_end \
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:99:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_route_decision \
z-harness/archive/tasks/T002/review.response.md:16:You are reviewing code that Claude just wrote for task T002: Add compaction_pause event type to log-event docs.
z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff-v1.patch:36:+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" fix_run_start "$START_PAYLOAD"
z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff-v1.patch:292:+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" fix_run_end \
z-harness/archive/tasks/T001/review.prompt.md:97:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_route_decision \
z-harness/archive/tasks/T001/review.prompt.md:916:- `scripts` — Subagents use utility scripts to report telemetry log-events, time phase durations, and sync remote file structures.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:114:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_route_decision \
z-harness/archive/tasks/T001/events.jsonl:35:{"ts":"2026-05-24T10:51:25Z","run":"tasks/T001","kind":"task_done","id":"T001","retries":0,"review_blockers":0,"review_cycles":0,"note":"net-new files mostly pre-existing; edits to log-event.sh only"}
z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff.patch:36:+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" fix_run_start "$START_PAYLOAD"
z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff.patch:294:+   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" fix_run_end \
z-harness/archive/tasks/T005/review.prompt.md:97:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_route_decision \
z-harness/archive/tasks/T005/review.prompt.md:487:        "scripts/log-event.sh",
z-harness/archive/tasks/T005/review.prompt.md:599:        "scripts/log-event.sh",
z-harness/archive/tasks/T005/review.prompt.md:916:    {"file": "skills/z-init-docs/SKILL.md", "line": 1, "symbol": "z-init-docs", "kind": "module", "summary": "Bootstraps two-tier docs: doc-updater per concept, INDEX.json aggregation, TAGS.txt 15-tag seed, MEMORIES-FLAT.md init via regenerate-memories-flat.py."},
z-harness/archive/tasks/T005/review.prompt.md:944:    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists.",
z-harness/archive/tasks/T005/review.prompt.md:1065:-- `scripts` — Subagents use utility scripts to report telemetry log-events, time phase durations, and sync remote file structures.
z-harness/archive/tasks/T005/review.prompt.md:1067:+- `scripts` — Subagents use `scripts/log-phase.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`, and `scripts/resolve-provider.sh` to emit telemetry, detect timeout availability, and resolve provider CLIs at runtime.
z-harness/archive/tasks/T005/review.prompt.md:1188:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
z-harness/archive/tasks/T005/review.prompt.md:1206:+- `scripts` — Skills call `plan-path.sh` to resolve `$Z_HARNESS_PLAN_DIR`, `log-event.sh` for telemetry, `version.sh` for run stamps, `log-phase.sh` for timing, and `regenerate-memories-flat.py` for memory flat-file sync.
z-harness/archive/tasks/T005/review.prompt.md:1219:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
z-harness/archive/tasks/T005/review.prompt.md:1768:+    {"file": "skills/z-init-docs/SKILL.md", "line": 1, "symbol": "z-init-docs", "kind": "module", "summary": "Bootstraps two-tier docs: doc-updater per concept, INDEX.json aggregation, TAGS.txt 15-tag seed, MEMORIES-FLAT.md init via regenerate-memories-flat.py."},
z-harness/archive/tasks/T005/review.prompt.md:1799:+    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists.",
z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:54: │   ├── log-event.sh
z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:146:    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_start "$START_PAYLOAD"
z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:742:    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_end \
z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:1061:    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_start "$START_PAYLOAD"
z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:1629:-bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" suggest_memory_called \
z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:1684:    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_end \
z-harness/archive/tasks/T005/review.response.md:112:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_route_decision \
z-harness/archive/tasks/T005/review.response.md:502:        "scripts/log-event.sh",
z-harness/archive/tasks/T005/review.response.md:614:        "scripts/log-event.sh",
z-harness/archive/tasks/T005/review.response.md:931:    {"file": "skills/z-init-docs/SKILL.md", "line": 1, "symbol": "z-init-docs", "kind": "module", "summary": "Bootstraps two-tier docs: doc-updater per concept, INDEX.json aggregation, TAGS.txt 15-tag seed, MEMORIES-FLAT.md init via regenerate-memories-flat.py."},
z-harness/archive/tasks/T005/review.response.md:959:    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists.",
z-harness/archive/tasks/T005/review.response.md:1080:-- `scripts` — Subagents use utility scripts to report telemetry log-events, time phase durations, and sync remote file structures.
z-harness/archive/tasks/T005/review.response.md:1082:+- `scripts` — Subagents use `scripts/log-phase.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`, and `scripts/resolve-provider.sh` to emit telemetry, detect timeout availability, and resolve provider CLIs at runtime.
z-harness/archive/tasks/T005/review.response.md:1203:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
z-harness/archive/tasks/T005/review.response.md:1221:+- `scripts` — Skills call `plan-path.sh` to resolve `$Z_HARNESS_PLAN_DIR`, `log-event.sh` for telemetry, `version.sh` for run stamps, `log-phase.sh` for timing, and `regenerate-memories-flat.py` for memory flat-file sync.
z-harness/archive/tasks/T005/review.response.md:1234:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
z-harness/archive/tasks/T005/review.response.md:1783:+    {"file": "skills/z-init-docs/SKILL.md", "line": 1, "symbol": "z-init-docs", "kind": "module", "summary": "Bootstraps two-tier docs: doc-updater per concept, INDEX.json aggregation, TAGS.txt 15-tag seed, MEMORIES-FLAT.md init via regenerate-memories-flat.py."},
z-harness/archive/tasks/T005/review.response.md:1814:+    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists.",
z-harness/archive/tasks/T005/review.response.md:2043:-- `scripts` — Subagents use utility scripts to report telemetry log-events, time phase durations, and sync remote file structures.
z-harness/archive/tasks/T005/review.response.md:2045:+- `scripts` — Subagents use `scripts/log-phase.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`, and `scripts/resolve-provider.sh` to emit telemetry, detect timeout availability, and resolve provider CLIs at runtime.
z-harness/archive/tasks/T005/review.response.md:2166:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
z-harness/archive/tasks/T005/review.response.md:2184:+- `scripts` — Skills call `plan-path.sh` to resolve `$Z_HARNESS_PLAN_DIR`, `log-event.sh` for telemetry, `version.sh` for run stamps, `log-phase.sh` for timing, and `regenerate-memories-flat.py` for memory flat-file sync.
z-harness/archive/tasks/T005/review.response.md:2197:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
z-harness/archive/tasks/T005/review.response.md:2746:+    {"file": "skills/z-init-docs/SKILL.md", "line": 1, "symbol": "z-init-docs", "kind": "module", "summary": "Bootstraps two-tier docs: doc-updater per concept, INDEX.json aggregation, TAGS.txt 15-tag seed, MEMORIES-FLAT.md init via regenerate-memories-flat.py."},
z-harness/archive/tasks/T005/review.response.md:2777:+    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists.",
z-harness/archive/tasks/T005/review.response.md:2922:commands/z-review-all.md:286:Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"review_tasks":<t>,"escalations":<k>,"user_action":"artifact_promoted"}'`.
z-harness/archive/tasks/T005/review.response.md:2988:commands/z-mr-review.md:732:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_finding_emitted \
z-harness/archive/tasks/T005/review.response.md:3062:         "scripts/log-event.sh",
z-harness/archive/tasks/T001/review.response.md:112:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_route_decision \
z-harness/archive/tasks/T001/review.response.md:931:- `scripts` — Subagents use utility scripts to report telemetry log-events, time phase durations, and sync remote file structures.
z-harness/archive/tasks/T001/review.response.md:1443:    72	        "scripts/log-event.sh",
z-harness/archive/tasks/subagent-liveness/review.prompt.md:45:+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
z-harness/archive/tasks/subagent-liveness/review.response.md:4:- **Major** `agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`: the `consult_start` JSON is built with `printf` string interpolation, so a provider or mode containing JSON-special characters produces invalid JSON and gets wrapped as `{"raw": ...}` by `log-event.sh`; then `role` is no longer a top-level field and the liveness close logic regresses. Build this payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.
z-harness/archive/tasks/subagent-liveness/review.response.md:8:- **Major** `scripts/check-timeout.sh:42`: the “exactly one per run” guarantee is path-scoped, not run-scoped, because the marker is placed in whichever archive layout the current environment resolves; the same run id can emit multiple `timeout_availability` events when sourced once with `Z_HARNESS_SLUG` and once without it, which already appears in `z-harness/metrics.jsonl`. Resolve through the same `plan-path.sh` logic as `log-event.sh` or gate on a repo-wide marker keyed by canonical `(slug, run)` before logging.
z-harness/archive/tasks/subagent-liveness/review.response.md:13:- **Major** `agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`: the `consult_start` JSON is built with `printf` string interpolation, so a provider or mode containing JSON-special characters produces invalid JSON and gets wrapped as `{"raw": ...}` by `log-event.sh`; then `role` is no longer a top-level field and the liveness close logic regresses. Build this payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.
z-harness/archive/tasks/subagent-liveness/review.response.md:17:- **Major** `scripts/check-timeout.sh:42`: the “exactly one per run” guarantee is path-scoped, not run-scoped, because the marker is placed in whichever archive layout the current environment resolves; the same run id can emit multiple `timeout_availability` events when sourced once with `Z_HARNESS_SLUG` and once without it, which already appears in `z-harness/metrics.jsonl`. Resolve through the same `plan-path.sh` logic as `log-event.sh` or gate on a repo-wide marker keyed by canonical `(slug, run)` before logging.
z-harness/archive/tasks/subagent-liveness/review.findings.md:7:2. **consult_start JSON not escaped** (`agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`): The `printf` string interpolation for `role`/`mode`/`provider` will produce invalid JSON if provider or mode contain JSON-special characters (quotes, backslashes, newlines), causing `log-event.sh` to wrap it as `{"raw": ...}` and lose the top-level `role` field that liveness matching depends on. Build the JSON payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.
z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.llm.json:35:    {"file": "skills/z-init-docs/SKILL.md", "line": 1, "symbol": "z-init-docs", "kind": "module", "summary": "Bootstraps two-tier docs: doc-updater per concept, INDEX.json aggregation, TAGS.txt 15-tag seed, MEMORIES-FLAT.md init via regenerate-memories-flat.py."},
z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.llm.json:70:    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists.",
z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:21:- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:36:- `scripts` — Skills call `plan-path.sh` to resolve `$Z_HARNESS_PLAN_DIR`, `log-event.sh` for telemetry, `version.sh` for run stamps, `log-phase.sh` for timing, and `regenerate-memories-flat.py` for memory flat-file sync.
z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:46:- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.llm.json:33:    {"file": "skills/z-init-docs/SKILL.md", "line": 1, "symbol": "z-init-docs", "kind": "module", "summary": "Bootstraps two-tier docs: doc-updater per concept, INDEX.json aggregation, TAGS.txt 15-tag seed, MEMORIES-FLAT.md init via regenerate-memories-flat.py."},
z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.llm.json:60:    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists."
z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md:32:- `scripts` — Subagents use `scripts/log-phase.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`, and `scripts/resolve-provider.sh` to emit telemetry, detect timeout availability, and resolve provider CLIs at runtime.
z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.human.md:33:- `scripts` — Subagents use `scripts/log-phase.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`, and `scripts/resolve-provider.sh` to emit telemetry, detect timeout availability, and resolve provider CLIs at runtime.
z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:22:- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:37:- `scripts` — Skills call `plan-path.sh` to resolve `$Z_HARNESS_PLAN_DIR`, `log-event.sh` for telemetry, `version.sh` for run stamps, `log-phase.sh` for timing, and `regenerate-memories-flat.py` for memory flat-file sync.
z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:52:- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
z-harness/archive/docs/20260525T081955Z-docs/proposed/skills.human.md:22:- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps docs/human and docs/llm, initializes INDEX files, writes the controlled TAGS.txt seed, and regenerates MEMORIES-FLAT.md.
z-harness/archive/docs/20260525T081955Z-docs/proposed/skills.human.md:37:- `scripts` — Skills rely on `plan-path.sh`, `log-event.sh`, `log-phase.sh`, `version.sh`, and `regenerate-memories-flat.py` for path resolution, telemetry, version stamping, and memory flat-file sync.
z-harness/archive/docs/20260525T081955Z-docs/proposed/skills.llm.json:56:    "Telemetry uses log-event.sh/log-phase.sh so z-stats can compute wall time."
z-harness/archive/docs/20260525T081955Z-docs/proposed/skills.llm.json:65:    "Adding a tag alias records TAGS.txt only; memory tags collapse on a later run.",
z-harness/plans/lookup-subagent/archive/20260524T184351Z-lookup-subagent/phase1-scaffolding.md:40:**Depends on:** scripts (log-event.sh, version.sh)
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.llm.diff:25:-    {"file": "skills/z-init-docs/SKILL.md", "line": 1, "symbol": "z-init-docs", "kind": "module", "summary": "Bootstraps two-tier docs: doc-updater per concept, INDEX.json aggregation, TAGS.txt 15-tag seed, MEMORIES-FLAT.md init via regenerate-memories-flat.py."},
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.llm.diff:73:+    "Telemetry uses log-event.sh/log-phase.sh so z-stats can compute wall time."
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.llm.diff:81:-    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists.",
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.llm.diff:90:+    "Adding a tag alias records TAGS.txt only; memory tags collapse on a later run.",
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:53:-- `scripts` — Subagents use `scripts/log-phase.sh`, `scripts/log-event.sh`, `scripts/check-timeout.sh`, and `scripts/resolve-provider.sh` to emit telemetry, detect timeout availability, and resolve provider CLIs at runtime.
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:28:-- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:46:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps docs/human and docs/llm, initializes INDEX files, writes the controlled TAGS.txt seed, and regenerates MEMORIES-FLAT.md.
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:61:-- `scripts` — Skills call `plan-path.sh` to resolve `$Z_HARNESS_PLAN_DIR`, `log-event.sh` for telemetry, `version.sh` for run stamps, `log-phase.sh` for timing, and `regenerate-memories-flat.py` for memory flat-file sync.
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:66:+- `scripts` — Skills rely on `plan-path.sh`, `log-event.sh`, `log-phase.sh`, `version.sh`, and `regenerate-memories-flat.py` for path resolution, telemetry, version stamping, and memory flat-file sync.
z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:77:-- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/cumulative.diff:22: │   ├── log-event.sh
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/transcripts/001-codex-final-review.response.md:386:    70	        "scripts/log-event.sh",
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/transcripts/001-codex-final-review.response.md:497:   181	        "scripts/log-event.sh",

codex
The surrounding spec confirms the task excerpt and shows `log-event.sh` has its own plan/run path resolution, which matters for whether this helper writes artifacts and events into the same run directory. I’m checking exact line numbers now so the findings are actionable.
exec
/bin/zsh -lc "nl -ba z-harness/plans/memory-self-improve-loop/SPEC.md | sed -n '88,110p;136,150p;196,204p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba scripts/run-memory-review.sh | sed -n '1,120p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    88	### `scripts/run-memory-review.sh`
    89	
    90	Bash helper called by both `/z-implement-all` and `/z-review-all`. Encapsulates the review-agent lifecycle so the two command files stay DRY.
    91	
    92	Signature: `bash scripts/run-memory-review.sh <RUN> <parent_command>`
    93	
    94	Where `<parent_command>` is `implement-all` or `review-all`.
    95	
    96	Behavior (in order):
    97	1. Resolve `$BASE = $Z_HARNESS_PLAN_DIR` and `$RUN_DIR = $BASE/archive/$RUN`.
    98	2. **Skip-conditions check** (D7 refined):
    99	   - Compute `git merge-base HEAD origin/main` (fallback `HEAD~5`); store base ref.
   100	   - Diff `<base>..HEAD`; if empty → emit `phase_end` with `name: memory_review`, `skipped: true`, `skip_reason: empty_diff`, exit 0.
   101	   - Parse `$BASE/TASKS.md`; count `[x]`. If zero AND parent_command is `implement-all` → skip with `skip_reason: all_tasks_skipped`, exit 0.
   102	   - NOTE: do NOT skip on halt — halted runs are high-signal.
   103	3. Write cumulative diff to `$RUN_DIR/cumulative.diff` (truncate to 5000 lines for context budget).
   104	4. Verify `docs/llm/TAGS.txt` exists (if missing, emit `review_agent_failed` event with reason `tags_missing` and exit 0 — soft-skip).
   105	5. (Caller — the orchestrator — handles the actual `Agent()` dispatch and JSON parse; this script's job is the deterministic plumbing.) Print to stdout, on separate lines: `STATUS: ready`, then `<RUN_DIR>/cumulative.diff`, then `<BASE>/SPEC.md`, then `docs/llm/TAGS.txt` (absolute paths).
   106	6. Exit 0. The skip paths print `STATUS: skipped <reason>` on the first line and exit 0 (skipping is success, not failure).
   107	
   108	Output contract: exit 0 always (skip is success); print `STATUS: <ready|skipped>` as first stdout line; if `ready`, also print absolute paths to the three artifacts the agent needs.
   109	
   110	---
   136	
   137	Insert a new `## Phase 9 — Memory review (auto)` section **AFTER** the existing Finalize block (which currently ends ~line 605) and **AFTER** the existing finalize push-notify, **BEFORE** the "Hard rules" / closing section.
   138	
   139	Phase 9 body:
   140	1. Call `bash scripts/run-memory-review.sh "$RUN" "implement-all"`. Capture stdout.
   141	2. If first line is `STATUS: skipped <reason>` — emit `phase_end` with `phase: 9, name: "memory_review", skipped: true, skip_reason: "<reason>"` and exit phase.
   142	3. If first line is `STATUS: ready`, parse the three paths.
   143	4. Dispatch:
   144	   ```
   145	   Agent(
   146	     subagent_type="review-agent",
   147	     description="Memory review for <slug>",
   148	     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <PATH>\nspec_path: <BASE>/SPEC.md\ntags_path: docs/llm/TAGS.txt\nrun_id: <RUN>\nparent_command: implement-all"
   149	   )
   150	   ```
   196	---
   197	
   198	## Edge cases and invariants
   199	
   200	- **Empty events.jsonl.** Should not happen (run_start always emitted) but if events.jsonl is empty, review-agent should treat as "no signal" and return `[]`. Orchestrator skip path handles emission.
   201	- **Tags-file collision.** If `docs/llm/TAGS.txt` is missing entirely (e.g. fresh repo), `run-memory-review.sh` soft-skips with `skip_reason: tags_missing`. Orchestrator does NOT auto-create TAGS.txt — that's `/z-suggest-memory`'s Phase 0 responsibility.
   202	- **Concurrent runs (same slug, different RUNs).** Per-run RUN_DIR isolation eliminates collisions on `memory-candidates.jsonl`. `/z-suggest-memory`'s atomic writes (existing) handle concurrent `docs/llm/<slug>.json` mutation if two reviews accept simultaneously.
   203	- **Subagent timeout.** No per-call wall-clock timeout in current Agent infrastructure (known v1 limitation per `/z-research` spec). If the Haiku call hangs, user ctrl-c is the escape. Document this in human-tier docs.
   204	- **Parse failure recovery.** The orchestrator does NOT retry on `review_agent_malformed` — soft-skip per D8. A v2 plan could add one retry with a "your previous output was malformed; produce a clean fenced json block" reprompt.

 succeeded in 0ms:
     1	#!/usr/bin/env bash
     2	# Helper called by /z-implement-all and /z-review-all.
     3	# Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
     4	#
     5	# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
     6	#   parent_command: implement-all | review-all
     7	#
     8	# Exit 0 always (skip is success).
     9	# Stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
    10	# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md, TAGS.txt
    11	
    12	set -euo pipefail
    13	
    14	if [[ $# -lt 2 ]]; then
    15	  echo "usage: run-memory-review.sh <RUN> <parent_command>" >&2
    16	  exit 2
    17	fi
    18	
    19	RUN="$1"
    20	PARENT_COMMAND="$2"
    21	
    22	REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    23	PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$REPO_ROOT}}"
    24	LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"
    25	
    26	# Resolve plan base dir
    27	BASE="${Z_HARNESS_PLAN_DIR:-}"
    28	if [[ -z "$BASE" ]]; then
    29	  echo "run-memory-review.sh: Z_HARNESS_PLAN_DIR is not set" >&2
    30	  exit 2
    31	fi
    32	
    33	RUN_DIR="$BASE/archive/$RUN"
    34	mkdir -p "$RUN_DIR"
    35	
    36	# --- Skip-condition 1: empty diff ---
    37	BASE_REF="$(git merge-base HEAD origin/main 2>/dev/null || echo "HEAD~5")"
    38	DIFF_OUTPUT="$(git diff "${BASE_REF}..HEAD" 2>/dev/null || true)"
    39	
    40	if [[ -z "$DIFF_OUTPUT" ]]; then
    41	  echo "STATUS: skipped empty_diff"
    42	  if [[ -x "$LOG_EVENT" ]]; then
    43	    bash "$LOG_EVENT" "$RUN" "phase_end" \
    44	      '{"name":"memory_review","skipped":true,"skip_reason":"empty_diff"}' || true
    45	  fi
    46	  exit 0
    47	fi
    48	
    49	# --- Skip-condition 2: zero completed tasks and parent is implement-all ---
    50	TASKS_FILE="$BASE/TASKS.md"
    51	if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
    52	  COMPLETED_COUNT="$(grep -c '\[x\]' "$TASKS_FILE" 2>/dev/null || true)"
    53	  COMPLETED_COUNT="${COMPLETED_COUNT:-0}"
    54	  COMPLETED_COUNT="$(printf '%s' "$COMPLETED_COUNT" | tr -d '[:space:]')"
    55	  if [[ "${COMPLETED_COUNT:-0}" -eq 0 ]]; then
    56	    echo "STATUS: skipped all_tasks_skipped"
    57	    if [[ -x "$LOG_EVENT" ]]; then
    58	      bash "$LOG_EVENT" "$RUN" "phase_end" \
    59	        '{"name":"memory_review","skipped":true,"skip_reason":"all_tasks_skipped"}' || true
    60	    fi
    61	    exit 0
    62	  fi
    63	fi
    64	
    65	# --- Verify TAGS.txt exists ---
    66	TAGS_FILE="$REPO_ROOT/docs/llm/TAGS.txt"
    67	if [[ ! -f "$TAGS_FILE" ]]; then
    68	  echo "STATUS: skipped tags_missing"
    69	  if [[ -x "$LOG_EVENT" ]]; then
    70	    bash "$LOG_EVENT" "$RUN" "review_agent_failed" \
    71	      '{"reason":"tags_missing"}' || true
    72	  fi
    73	  exit 0
    74	fi
    75	
    76	# --- Write cumulative diff (truncated to 5000 lines) ---
    77	DIFF_FILE="$RUN_DIR/cumulative.diff"
    78	# Use set +e around head to avoid SIGPIPE exit 141 when diff is shorter than 5000 lines.
    79	set +o pipefail
    80	printf '%s\n' "$DIFF_OUTPUT" | head -n 5000 > "$DIFF_FILE"
    81	set -o pipefail
    82	
    83	# --- Print ready + artifact paths ---
    84	echo "STATUS: ready"
    85	echo "$DIFF_FILE"
    86	echo "$BASE/SPEC.md"
    87	echo "$TAGS_FILE"
    88	
    89	exit 0

exec
/bin/zsh -lc "nl -ba scripts/log-event.sh | sed -n '1,115p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	#!/usr/bin/env bash
     2	# Append a structured event to the run's events.jsonl.
     3	#
     4	# Usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>
     5	#
     6	# Slug namespacing: if env var Z_HARNESS_SLUG is set (non-empty), all output
     7	# paths are namespaced under ${Z_HARNESS_PLANS_DIR:-z-harness/plans}/<slug>/
     8	# so multiple plans can coexist in the same repo. If unset, the legacy flat
     9	# layout (z-harness/archive/...) is used for backward compat with old plans.
    10	#
    11	# Example:
    12	#   Z_HARNESS_SLUG=add-rate-limit \
    13	#   log-event.sh 20260517T144200Z-add-rate-limit consult \
    14	#     '{"llm":"gemini","phase":3,"prompt_chars":4821,"wall_ms":18204,"transcript":"001-gemini.md"}'
    15	#
    16	# Writes to (with Z_HARNESS_SLUG set):
    17	#   ${Z_HARNESS_PLANS_DIR:-z-harness/plans}/<slug>/archive/<run>/events.jsonl  (new canonical)
    18	#   z-harness/<slug>/archive/<run>/events.jsonl  (legacy mid-flight fallback — if run dir
    19	#     already exists at legacy path, writes there to avoid splitting a run's events;
    20	#     run 'scripts/migrate-plan-layout.sh <slug>' to move to the new layout)
    21	#   z-harness/metrics.jsonl  (repo-wide aggregate, slug added to event)
    22	#
    23	# Writes to (legacy, no slug):
    24	#   z-harness/archive/<run>/events.jsonl
    25	#   z-harness/metrics.jsonl
    26	#
    27	# Both files are JSON Lines. Append-safe under concurrent calls via flock when available.
    28	
    29	set -euo pipefail
    30	
    31	if [[ $# -lt 3 ]]; then
    32	  echo "usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>" >&2
    33	  exit 2
    34	fi
    35	
    36	RUN="$1"
    37	KIND="$2"
    38	PAYLOAD="$3"
    39	
    40	# Resolve repo root (caller's cwd is assumed to be inside the target repo).
    41	REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    42	
    43	# Load plan-path helper
    44	# shellcheck source=scripts/plan-path.sh
    45	source "$(dirname "$0")/plan-path.sh"
    46	
    47	# Join a base dir (may be relative or absolute) with a suffix under REPO_ROOT.
    48	# If the base is absolute it is used verbatim; if relative it is resolved
    49	# relative to REPO_ROOT. This handles Z_HARNESS_PLANS_DIR=/tmp/p correctly.
    50	abs_plan_dir() {
    51	  local base="$1"
    52	  case "$base" in
    53	    /*) printf '%s' "$base" ;;
    54	    *)  printf '%s/%s' "$REPO_ROOT" "$base" ;;
    55	  esac
    56	}
    57	
    58	# Slug namespacing — see header comment.
    59	SLUG="${Z_HARNESS_SLUG:-}"
    60	if [[ -n "$SLUG" ]]; then
    61	  # Mid-flight legacy run detection: if the legacy archive dir for this run
    62	  # already exists (meaning the run was started before the plan-layout migration),
    63	  # write there to avoid splitting a run's events across two locations.
    64	  # Otherwise, use the new canonical path from plan_dir.
    65	  LEGACY_RUN_DIR="$(abs_plan_dir "$(legacy_plan_dir "$SLUG")")/archive/$RUN"
    66	  if [[ -d "$LEGACY_RUN_DIR" ]]; then
    67	    RUN_DIR="$LEGACY_RUN_DIR"
    68	  else
    69	    RUN_DIR="$(abs_plan_dir "$(plan_dir "$SLUG")")/archive/$RUN"
    70	  fi
    71	else
    72	  # Global archive fallback (no slug)
    73	  RUN_DIR="$REPO_ROOT/z-harness/archive/$RUN"
    74	fi
    75	mkdir -p "$RUN_DIR"
    76	
    77	TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    78	
    79	# Validate payload is JSON; if not, wrap it as a string.
    80	if ! printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' 2>/dev/null; then
    81	  PAYLOAD="$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.dumps({"raw": sys.stdin.read()}))')"
    82	fi
    83	
    84	EVENT="$(python3 -c '
    85	import json, sys
    86	ts, run, kind, slug, payload = sys.argv[1:6]
    87	obj = {"ts": ts, "run": run, "kind": kind}
    88	if slug:
    89	    obj["slug"] = slug
    90	obj.update(json.loads(payload))
    91	print(json.dumps(obj, separators=(",", ":")))
    92	' "$TS" "$RUN" "$KIND" "$SLUG" "$PAYLOAD")"
    93	
    94	append() {
    95	  local target="$1"
    96	  if command -v flock >/dev/null 2>&1; then
    97	    ( flock 9; printf '%s\n' "$EVENT" >> "$target" ) 9>>"$target.lock"
    98	  else
    99	    printf '%s\n' "$EVENT" >> "$target"
   100	  fi
   101	}
   102	
   103	append "$RUN_DIR/events.jsonl"
   104	append "$REPO_ROOT/z-harness/metrics.jsonl"

codex
Findings, ordered by impact:

1. **Major** [scripts/run-memory-review.sh:37](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:37>)  
   Invalid fallback base can falsely produce `empty_diff`. If `origin/main` is missing and `HEAD~5` does not exist, `git diff "${BASE_REF}..HEAD" 2>/dev/null || true` returns empty, so the script reports `STATUS: skipped empty_diff` even when the repo has changes.  
   **Suggested fix:** validate the fallback before diffing. If `HEAD~5` is invalid, use the root commit or an empty-tree diff, or emit a soft skipped/error status explicitly rather than treating diff failure as empty.

2. **Major** [scripts/run-memory-review.sh:38](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:38>) and [scripts/run-memory-review.sh:80](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:80>)  
   The full diff is captured into a shell variable before truncation. That defeats the 5000-line context-budget intent for large diffs and can consume a lot of memory before `head` ever runs.  
   **Suggested fix:** stream the diff directly: first check emptiness with `git diff --quiet "$BASE_REF..HEAD"` or a small temp/status check, then write with `git diff "$BASE_REF..HEAD" | head -n 5000 > "$DIFF_FILE"`.

3. **Major** [scripts/run-memory-review.sh:27](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:27>), [scripts/run-memory-review.sh:33](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:33>), [scripts/run-memory-review.sh:85](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:85>)  
   Output paths are only absolute if `Z_HARNESS_PLAN_DIR` is already absolute. The spec requires absolute paths for `cumulative.diff`, `SPEC.md`, and `docs/llm/TAGS.txt`.  
   **Suggested fix:** normalize `BASE` after reading it, e.g. if relative, prefix `$REPO_ROOT/`, then build `RUN_DIR` and `SPEC.md` from that absolute base.

4. **Major** [scripts/run-memory-review.sh:14](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:14>) and [scripts/run-memory-review.sh:28](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:28>)  
   The script exits `2` for missing args or missing `Z_HARNESS_PLAN_DIR`, violating the output contract: “exit 0 always” and first stdout line must be `STATUS: ...`. Signature misuse is less important, but missing env can happen if an orchestrator integration regresses, and this would break parsing.  
   **Suggested fix:** for runtime precondition failures, print `STATUS: skipped <reason>` and exit `0`; reserve usage errors only if the project explicitly narrows “exit 0 always” to valid invocations.

5. **Minor** [scripts/run-memory-review.sh:57](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:57>)  
   The script emits `phase_end` for `all_tasks_skipped`, but the spec only explicitly requires script-side `phase_end` for `empty_diff`; the orchestrator section also says it emits `phase_end` for skipped helper output. This can duplicate telemetry once callers are wired.  
   **Suggested fix:** decide one owner. Given the helper output contract, prefer making the helper print status only for skip paths except the explicitly required `review_agent_failed` on `tags_missing`, or update caller spec to avoid duplicate `phase_end`.

6. **Minor** [scripts/run-memory-review.sh:65](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:65>)  
   The implementation verifies `TAGS.txt` before writing `cumulative.diff`, while the behavior order says write the cumulative diff first, then verify tags. Usually harmless, but it is a spec-order mismatch and can remove a useful artifact from failed runs.  
   **Suggested fix:** move the `TAGS.txt` check after `DIFF_FILE` is written.

7. **Minor** [scripts/run-memory-review.sh:20](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:20>)  
   `parent_command` is not validated. A typo silently disables the `implement-all` skip behavior and can dispatch review when all tasks were skipped.  
   **Suggested fix:** accept only `implement-all` or `review-all`; otherwise print a skipped/precondition status and exit `0`.

8. **Nit / hardening** [scripts/run-memory-review.sh:19](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:19>)  
   `RUN` is used directly in `$BASE/archive/$RUN`; a malformed value with `../` can write outside the archive. The orchestrator probably controls this, so not a blocker.  
   **Suggested fix:** reject absolute paths and path traversal in `RUN`, or allow only the run-id character set used elsewhere.

Acceptance status: chmod is satisfied (`100755`). The ready and named skip statuses mostly exist, but the absolute-path, invalid-base, and nonzero-exit issues should be fixed before accepting T004.
tokens used
63,885
Findings, ordered by impact:

1. **Major** [scripts/run-memory-review.sh:37](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:37>)  
   Invalid fallback base can falsely produce `empty_diff`. If `origin/main` is missing and `HEAD~5` does not exist, `git diff "${BASE_REF}..HEAD" 2>/dev/null || true` returns empty, so the script reports `STATUS: skipped empty_diff` even when the repo has changes.  
   **Suggested fix:** validate the fallback before diffing. If `HEAD~5` is invalid, use the root commit or an empty-tree diff, or emit a soft skipped/error status explicitly rather than treating diff failure as empty.

2. **Major** [scripts/run-memory-review.sh:38](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:38>) and [scripts/run-memory-review.sh:80](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:80>)  
   The full diff is captured into a shell variable before truncation. That defeats the 5000-line context-budget intent for large diffs and can consume a lot of memory before `head` ever runs.  
   **Suggested fix:** stream the diff directly: first check emptiness with `git diff --quiet "$BASE_REF..HEAD"` or a small temp/status check, then write with `git diff "$BASE_REF..HEAD" | head -n 5000 > "$DIFF_FILE"`.

3. **Major** [scripts/run-memory-review.sh:27](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:27>), [scripts/run-memory-review.sh:33](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:33>), [scripts/run-memory-review.sh:85](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:85>)  
   Output paths are only absolute if `Z_HARNESS_PLAN_DIR` is already absolute. The spec requires absolute paths for `cumulative.diff`, `SPEC.md`, and `docs/llm/TAGS.txt`.  
   **Suggested fix:** normalize `BASE` after reading it, e.g. if relative, prefix `$REPO_ROOT/`, then build `RUN_DIR` and `SPEC.md` from that absolute base.

4. **Major** [scripts/run-memory-review.sh:14](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:14>) and [scripts/run-memory-review.sh:28](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:28>)  
   The script exits `2` for missing args or missing `Z_HARNESS_PLAN_DIR`, violating the output contract: “exit 0 always” and first stdout line must be `STATUS: ...`. Signature misuse is less important, but missing env can happen if an orchestrator integration regresses, and this would break parsing.  
   **Suggested fix:** for runtime precondition failures, print `STATUS: skipped <reason>` and exit `0`; reserve usage errors only if the project explicitly narrows “exit 0 always” to valid invocations.

5. **Minor** [scripts/run-memory-review.sh:57](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:57>)  
   The script emits `phase_end` for `all_tasks_skipped`, but the spec only explicitly requires script-side `phase_end` for `empty_diff`; the orchestrator section also says it emits `phase_end` for skipped helper output. This can duplicate telemetry once callers are wired.  
   **Suggested fix:** decide one owner. Given the helper output contract, prefer making the helper print status only for skip paths except the explicitly required `review_agent_failed` on `tags_missing`, or update caller spec to avoid duplicate `phase_end`.

6. **Minor** [scripts/run-memory-review.sh:65](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:65>)  
   The implementation verifies `TAGS.txt` before writing `cumulative.diff`, while the behavior order says write the cumulative diff first, then verify tags. Usually harmless, but it is a spec-order mismatch and can remove a useful artifact from failed runs.  
   **Suggested fix:** move the `TAGS.txt` check after `DIFF_FILE` is written.

7. **Minor** [scripts/run-memory-review.sh:20](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:20>)  
   `parent_command` is not validated. A typo silently disables the `implement-all` skip behavior and can dispatch review when all tasks were skipped.  
   **Suggested fix:** accept only `implement-all` or `review-all`; otherwise print a skipped/precondition status and exit `0`.

8. **Nit / hardening** [scripts/run-memory-review.sh:19](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:19>)  
   `RUN` is used directly in `$BASE/archive/$RUN`; a malformed value with `../` can write outside the archive. The orchestrator probably controls this, so not a blocker.  
   **Suggested fix:** reject absolute paths and path traversal in `RUN`, or allow only the run-id character set used elsewhere.

Acceptance status: chmod is satisfied (`100755`). The ready and named skip statuses mostly exist, but the absolute-path, invalid-base, and nonzero-exit issues should be fixed before accepting T004.
