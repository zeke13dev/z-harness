# Codex Bundled Decisions Consultation

## D2: Recommend B

Use `cluster-planner` with a light decision gate: premise check, SPEC/PLAN/TASKS, and `STATUS: decision_needed` for non-obvious decisions. Per-leaf consult should be reserved for decisions the main thread explicitly flags after seeing the leaf's blocker, otherwise `/z-plan-split` drifts too close to "N full `/z-plan`s" and loses its purpose.

**Tradeoff:** B relies on the leaf correctly recognizing uncertainty. Mitigate that by making `cluster-planner` fail closed: any dependency boundary, shared schema/config, irreversible migration, public API, or ambiguous acceptance criterion must become `decision_needed`. Wrong scope boundaries are only partly caught by reconciliation, so the main thread should also validate each leaf's declared scope against the confirmed split before accepting outputs.

**Interactions:** decisions resolved by the main thread should be written both into the affected cluster's decision log and the root `MANIFEST.md` or `SHARED-CONCERNS.md`, not only local cluster notes. This keeps later implementation from silently inheriting an invisible root-level choice.

## D3: Recommend B

Do file-overlap detection plus an active `shared/` scaffold, but mark it explicitly as `STATUS: needs_planning` or `SKIP: shared reconciliation required`, not as an implementable empty plan. "File overlap" should mean exact file path overlap from declared `Files:` blocks, plus simple structured signals such as migrations, config, schemas, generated types, env files, and package/version files.

**Tradeoff:** B adds a small amount of orchestration state, but it makes shared risk visible and actionable. A passive `SHARED-CONCERNS.md` is too easy to miss before `/z-implement-all`; C is likely not worth the recurring cost unless overlap count or risk labels exceed a threshold.

**Missed consideration:** require each leaf to emit a machine-readable touched-files/shared-surfaces section, otherwise reconciliation becomes brittle prose parsing. The scaffold should block parent implementation until either planned or explicitly waived in the manifest.

## D7: Recommend A, One Level Only

Extend `/z-implement-all` to recognize `MANIFEST.md`, recurse one level into listed clusters, validate each leaf has SPEC/PLAN/TASKS, and execute clusters in manifest run-order. Arbitrary depth should be rejected with a clear "flatten or run per subtree" message; recursive trees create too much state for an already complex command.

**Tradeoff:** A avoids another command while preserving the user's expected "implement the plan" flow. It does add manifest parsing and cluster state, but discovery is cheap if the manifest is authoritative and contains cluster paths, statuses, run-order, and skip/blocked markers.

**Interactions:** manifest run-order should be enforced, not advisory. Parent-level skips/blocks should override leaf TASKS, while leaf skip markers govern individual tasks inside an eligible cluster. If a cluster fails under existing halt semantics, halt the parent run unless the manifest explicitly marks clusters as independent and continue-on-failure.
