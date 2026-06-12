# Review: Hermes Integration Protocol v1

> **Note (2026-06-12):** The Hermes parallelism layer is now **ACTIVATED** (T001-T015 complete,
> all reviewed). The "dormant/planned" language from the original v1.1 review no longer applies.
> Within-plan DAG concurrency, cross-plan orchestration, and the merge mutex are all live.
> See [docs/human/hermes-integration-v1.md](hermes-integration-v1.md) for the finalized
> protocol v1.3 specification and operator runbook.

> **Document reviewed:** `docs/human/hermes-integration-v1.md` (v1.1.0, status: DRAFT)
> **Date:** 2026-06-08
> **Reviewer:** z-harness `/z-review-all` audit
> **Amended:** 2026-06-08 via `/z-amend` — all BLOCKER/MAJOR findings resolved, all MINOR/SUGGESTION findings applied

---

## Summary

The Hermes Integration Protocol v1 defines a clean separation of concerns — harness owns WHAT, orchestrator owns HOW — and the `workstreams.json` artifact is the right abstraction. The session lifecycle (resolve → worktree → spawn → monitor → merge → cleanup) is well-structured and the question-relay/dedup design is good. However, the spec has one **blocker** and four **majors** that must be resolved before finalization: the flat z-plan DAG derivation algorithm is ambiguous to the point of being unimplementable; `depends_on`/`parallel_group` assume v2 capabilities that don't exist in current z-plan-split; and `partial_tree` as a bare boolean is insufficient for the orchestrator to know which workstreams to skip. The severity heuristics also drift from z-plan-split's canonical definitions.

---

## Findings by category

### 1. Consistency with existing artifacts

**MAJOR — `depends_on` DAG doesn't match z-plan-split's linear run order.** The spec models inter-workstream dependencies as a DAG where leaf clusters can depend on setup clusters and share `parallel_group` labels. But z-plan-split's MANIFEST.md `## Run order` is currently a total sequential order: "Cross-cluster task parallelism is v2." There is no dependency DAG; there is no `parallel_group`. The spec is effectively designing against a future version of z-plan-split rather than the v1 that exists. **Recommendation:** Either (a) restrict `depends_on` to empty (no deps) or at most one predecessor for the z-plan-split source type, acknowledging that DAG support is v2; or (b) update z-plan-split to emit dependency information before this spec ships. The example in the spec showing ws-2 and ws-3 both depending on ws-1 with `parallel_group: "leaf-a"` is not producible by current z-plan-split. *(Line reference: spec §"Workstream derivation per plan type" → "z-plan-split" paragraph; z-plan-split SKILL.md §"Phase 5b" → "Run order" section.)*

**MINOR — Severity heuristics drift from z-plan-split Phase 4.** The spec defines `"high"` as "schema, migration, lockfile, config, Dockerfile" — an informal description. z-plan-split SKILL.md Phase 4 uses a precise regex `.*\.(sql|migration|schema|toml|yaml|yml|proto)$` plus an explicit allowlist (`Dockerfile`, `Makefile`, `package.json`, `package-lock.json`, `Cargo.lock`, `pnpm-lock.yaml`, `yarn.lock`). The spec omits `Makefile`, `pnpm-lock.yaml`, `yarn.lock`. **Recommendation:** Either reference z-plan-split's severity rules directly (DRY), or replicate the exact regex + allowlist so orchestrator implementers get the same behavior regardless of whether they read the JSON or SHARED-CONCERNS.md. *(Line reference: spec §"File conflict object" severity field; z-plan-split SKILL.md Phase 4 "Severity heuristics" block.)*

**CONSISTENT — `merge_order` maps correctly to MANIFEST.md `## Run order`.** The spec's `merge_order` array is a permutation of workstream IDs, matching the sequential order in MANIFEST.md. This is correct. ✓

**CONSISTENT — `file_conflicts` maps correctly to SHARED-CONCERNS.md overlap blocks.** The `file`, `workstreams`, and `severity` fields align with SHARED-CONCERNS.md's overlap sections. ✓

**CONSISTENT — `partial_tree` maps to MANIFEST.md `status: partial` and SHARED-CONCERNS.md `partial_tree: true`.** The boolean is compatible, though insufficient alone (see Design finding below). ⚠

### 2. Design quality

**MAJOR — `partial_tree: true/false` is insufficient for orchestrator decision-making.** The spec says `partial_tree` means "True if one or more workstreams failed planning (excluded from manifest)." But if failed workstreams are *excluded from the manifest*, then the `workstreams` array only contains ready workstreams — making `partial_tree` redundant. If failed workstreams remain in the array with a status marker, the orchestrator needs that marker to know which to skip. The spec doesn't define a per-workstream `status` field. **Recommendation:** Either (a) add `"status": "ready" | "failed"` to each Workstream object, or (b) remove `partial_tree` and have the orchestrator simply run all workstreams in the array (failed ones were excluded at generation time). The current design is ambiguous: "excluded from manifest" vs "True if one or more workstreams failed planning." *(Line reference: spec §"Schema" → `partial_tree` field description.)*

**MINOR — Schema validation rule 7 is circular at worst, redundant at best.** Rule 7: "`parallel_group` members are at the same dependency depth." If all members of a `parallel_group` have the same dependency depth AND share a `parallel_group` label, they must not depend on each other (since they're at the same depth). The rule is trying to enforce that parallel-grouped workstreams are independent, which is already guaranteed by the `depends_on` graph (mutual non-dependence). If the intent is to prevent incorrect group assignment, say "Workstreams in the same `parallel_group` must not have dependency relationships with each other." As written, "same dependency depth" allows A→B if both happen to be depth 2 (e.g., A depends on depth-1 X, B depends on depth-1 Y). **Recommendation:** Clarify to: "No workstream in a `parallel_group` may appear in the transitive `depends_on` of any other workstream in the same group, and vice versa." *(Line reference: spec §"Schema validation" rule 7.)*

**MINOR — Missing orchestrator crash-resumption story.** The execution contract steps 1–7 describe a linear lifecycle. If the orchestrator process itself crashes after spawning sessions and merging some workstreams, how does it resume? The manifest doesn't track execution progress. **Recommendation:** Add a section on resumption: the orchestrator re-reads `workstreams.json`, scans existing worktree branches (`hermes/<slug>/*`), reads per-session `session-status.json`, and reconstructs what's done, running, or not started. This doesn't require changes to the JSON schema — just documentation. *(Line reference: spec §"Execution contract" — no resumption section.)*

**MINOR — No guidance on manifest modification during execution.** The spec says `workstreams.json` is "Not updated during execution." But it doesn't say whether the orchestrator should read-once-and-cache or re-read. **Recommendation:** Explicitly state: "The orchestrator SHOULD read `workstreams.json` once at start. Re-reading mid-execution is undefined behavior; changes after execution begins are not supported." *(Line reference: spec §"Artifact: workstreams.json" → "Lifecycle" paragraph.)*

### 3. DRY / KISS / SOLID

**SUGGESTION — `workstreams.json` inherently duplicates MANIFEST.md + SHARED-CONCERNS.md.** This is acknowledged in the spec's "Relationship to other artifacts" table and is a necessary tradeoff (humans read Markdown, machines read JSON). Not a flaw — just noting that any future schema changes to MANIFEST.md or SHARED-CONCERNS.md must propagate to `workstreams.json` generation. Consider adding a note: "The content of `workstreams.json` is derived from the same source data as MANIFEST.md and SHARED-CONCERNS.md. Implementers MUST update all three when changing reconciliation logic." ✓ (already implied by the architecture)

**SUGGESTION — `workstreams.json` generation for z-plan-light may be unnecessary ceremony.** A `/z-plan-light` run produces a single FIX.md with 1-5 file changes. Generating a `workstreams.json` with one workstream containing all tasks is trivial overhead. The orchestrator could simply detect the absence of `workstreams.json` and run a single session. **Recommendation:** Make `workstreams.json` optional for `source: "/z-plan-light"` — if absent, the orchestrator runs the entire slug directory as a single workstream. This keeps z-plan-light's "no ceremony" spirit. *(Line reference: spec §"Workstream derivation per plan type" → "z-plan-light" paragraph.)*

**SOLID — Separation of concerns is well-executed.** The harness owns WHAT (defined in `workstreams.json`), the orchestrator owns HOW (concurrency cap, retry policy, model selection, timeouts). The "Orchestrator discretion" table is clear and makes the boundary explicit. ✓

**KISS — Protocol surface area is reasonable.** 7 top-level fields, 6 workstream fields, 3 conflict fields, 5 status fields. The session lifecycle is 7 steps. This is a reasonable level of complexity for a cross-process coordination protocol.

### 4. Interaction with existing z-harness commands

**MINOR — `/z-implement-all --tasks=<path>` fast path skips tree-validation gates.** The spec says the orchestrator invokes `pi z-implement-all --tasks=<workstream.path>/TASKS.md`. But z-implement-all's `--tasks` fast path skips slug discovery, tree validation, `--ack` gate, and `--force-partial` gate. This means the orchestrator cannot rely on z-implement-all to enforce SHARED-CONCERNS.md acknowledgements or partial-tree gates — the orchestrator must handle these itself. **Recommendation:** Document this explicitly in the spec: "The orchestrator is responsible for pre-validating tree-level gates (shared-concerns acknowledgement, partial-tree opt-in) before spawning individual workstream sessions. The `--tasks` flag bypasses these gates in z-implement-all." *(Line reference: spec §"Execution contract" step 3; z-implement-all SKILL.md §"Setup" step 1 — `--tasks` fast path.)*

**MINOR — Branch namespace belongs to Hermes, but z-implement-all doesn't know about branches.** z-implement-all runs in the current worktree and commits to the current branch. The orchestrator handles worktree creation and branch naming (`hermes/<slug>/<id>`). This is correct — the harness doesn't need to know about Hermes branches. ✓ But the spec uses `hermes/<slug>/<id>` as the branch name. If `id` is `ws-1`, the branch is `hermes/add-payment-system/ws-1`. This is safe because `slug` and `id` are validated (kebab-case). ✓

**SUGGESTION — No Hermes-specific slug validation referenced.** The spec's `slug` field is "Plan identifier. Used for git branch naming (`hermes/<slug>/<id>`)." z-harness planning commands validate slugs with `^[a-z0-9]+(-[a-z0-9]+)*$`. The spec should reference this validation or replicate it, since the orchestrator interpolates the slug into branch names. **Recommendation:** Add a note: "Slugs MUST match `^[a-z0-9]+(-[a-z0-9]+)*$`. z-harness planning commands enforce this at generation time; orchestrators SHOULD validate on read." *(Line reference: spec §"Schema" → `slug` field; z-plan-split SKILL.md §"Setup" step 2.)*

### 5. V1 scope

**BLOCKER — Flat z-plan DAG derivation algorithm is underspecified to the point of being unimplementable.** The spec says: "Generated by parsing `**Depends on:**` lines across all tasks into a DAG. Cut the DAG at each depth level. Dependent task chains become workstreams." But "cut at each depth level" and "chain dependent tasks into workstreams" are contradictory when a chain spans multiple depths.

Concrete example: T001 (no deps, depth 0), T002 (depends on T001, depth 1), T006 (depends on T002, depth 2). If we "cut at each depth level," we get three workstreams: ws-1 (T001), ws-2 (T002), ws-3 (T006). If we "chain dependent tasks," T001→T002→T006 becomes one workstream. Which rule wins?

The two examples in the spec don't resolve this. The linear example (T001→…→T010) is one workstream with 10 tasks — trivially correct. The branching example (T001→T002-T005 in parallel) produces two workstreams — also correct under either interpretation. But it never shows a depth-2 chain. **Recommendation:** Define the algorithm precisely:

> 1. Parse all `**Depends on:** Txxx` lines into a DAG.
> 2. Assign each task a *depth* = 0 for tasks with no dependencies; max(parent depths) + 1 otherwise.
> 3. Group tasks by depth. Each depth group becomes a workstream.
> 4. Chain: if a depth-N workstream has exactly one task AND that task is the sole dependency of ≥2 depth-(N+1) tasks, include it in the depth-(N+1) workstream to avoid a single-task setup workstream.
> 5. Tasks at the same depth that depend on DIFFERENT depth-(N-1) parents that are in different workstreams become separate workstreams.
> 6. Tasks that form a linear chain across depths (depth N → depth N+1 → depth N+2, with 1:1 dependency) are collapsed into a single workstream.

Alternatively, acknowledge that flat z-plan DAG support is v1.1 and ship v1.0 with z-plan producing a single workstream (like z-plan-light does). Many real z-plan task lists are effectively linear. *(Line reference: spec §"Workstream derivation per plan type" → "z-plan" paragraph.)*

**MAJOR — `parallel_group` assumes parallel execution, which z-plan-split explicitly defers to v2.** The spec's example shows ws-2 and ws-3 sharing `parallel_group: "leaf-a"`, meaning they can run concurrently. But z-plan-split's MANIFEST.md `## Run order` section says "Cross-cluster task parallelism is v2." The spec is designing a v1 contract that depends on v2 behavior. **Recommendation:** Either (a) include `parallel_group: null` for all z-plan-split-derived workstreams in v1, documenting that parallel-group support is reserved for v2; or (b) make `parallel_group` a v2-only field and exclude it from the v1 schema. *(Line reference: spec §"Workstream object" → `parallel_group` field; spec §"Example"; z-plan-split SKILL.md §"Phase 5b" → "Run order" section.)*

**SCOPE OK — z-plan-light → single workstream.** Trivially correct. ✓

**SCOPE OK — `partial_tree` is generated in all three plan types.** z-plan-split already tracks this in MANIFEST.md and SHARED-CONCERNS.md. z-plan and z-plan-light don't currently have a `partial_tree` concept but the value would always be `false` (no sub-plans to fail). ✓

### 6. Security

**MINOR — No sanitization guidance for `halt_description`.** The `session-status.json` `halt_description` field is "Free-text summary of the halt" produced by implementer subagents. If the orchestrator uses this text in shell commands, HTML rendering, or notification UIs, it could be an injection vector (newlines, control characters, terminal escape sequences). **Recommendation:** Add a note: "Orchestrators MUST treat all free-text fields (`halt_description`, `name`) as untrusted input. Sanitize before shell interpolation or UI rendering. Fields may contain newlines, Unicode, and shell metacharacters." *(Line reference: spec §"Execution contract" step 4 → `session-status.json` schema.)*

**MINOR — Path trailing-slash edge case.** Validation rule 6: "`workstreams[].path + "/TASKS.md"` resolves to an existing file." If `path` has a trailing slash (e.g., `z-harness/foo/`), this produces `z-harness/foo//TASKS.md` — which most filesystems normalize but is technically a double-slash. **Recommendation:** Add to path validation: "Paths MUST NOT end with `/`." Or normalize paths during generation. *(Line reference: spec §"Schema validation" rule 6.)*

**SECURE — Protocol version pinning.** The `protocol` field with strict version rejection and forward-compatibility rules (new fields → minor, renamed/removed → major) is well-designed. ✓

**SECURE — Path validation rules 5 and 6 are comprehensive.** No `../`, no absolute paths, no `//`, plus existence check for `TASKS.md`. ✓

**SECURE — Slug interpolation into branch names (`hermes/<slug>/<id>`) is safe** because z-harness planning commands enforce kebab-case slug validation. The orchestrator should validate on read for defense-in-depth. ✓

---

## Severity summary

| Severity | Count | IDs |
|----------|-------|-----|
| **BLOCKER** | 1 | Flat z-plan DAG derivation algorithm underspecified |
| **MAJOR** | 4 | `depends_on` DAG vs linear MANIFEST; `parallel_group` assumes v2; `partial_tree` boolean insufficient; validation rule 7 circular |
| **MINOR** | 8 | Severity heuristics drift; crash-resumption missing; manifest modification undefined; `--tasks` gate bypass undocumented; slug validation not referenced; `halt_description` sanitization; trailing-slash edge case; z-plan-light scope |
| **SUGGESTION** | 3 | DRY duplication inherent; optional for z-plan-light; DAG derivation possibly over-engineered |

---

## Recommendations for fixes before finalizing

1. **Define the flat z-plan DAG derivation algorithm precisely** (BLOCKER). Provide pseudocode or a deterministic 5-rule algorithm. Include edge cases: tasks with multiple `**Depends on:**` lines, tasks at different depths sharing a parent, and the "chain collapse" rule.

2. **Reconcile `depends_on` and `parallel_group` with z-plan-split's v1 capabilities** (MAJOR). Either restrict these fields for `source: "/z-plan-split"` (all workstreams have `depends_on: []` and `parallel_group: null`), or update z-plan-split to emit dependency information.

3. **Add per-workstream `status` field** (MAJOR). Replace or augment `partial_tree` with `"status": "ready" | "failed"` on each Workstream object so the orchestrator knows exactly which workstreams to skip.

4. **Fix validation rule 7** (MAJOR). Replace "same dependency depth" with "no transitive dependency relationship between workstreams in the same `parallel_group`."

5. **Add orchestrator resumption documentation** (MINOR). A short section on crash recovery: re-read manifest, scan existing branches, read session-status files, reconstruct execution state.

6. **Document `--tasks` gate bypass** (MINOR). The spec should note that when using `--tasks=<path>`, the orchestrator is responsible for pre-validating tree-level gates.

7. **Reference z-plan-split's severity heuristics explicitly** (MINOR). Either link to "z-plan-split SKILL.md Phase 4 Severity heuristics" or replicate the regex + allowlist verbatim.

8. **Add sanitization note for free-text fields** (MINOR). A one-liner about treating `halt_description` as untrusted input.

9. **Reject trailing slashes in path validation** (MINOR). Add to validation rule 5: "Paths must not end with `/`."

10. **Consider optional `workstreams.json` for z-plan-light** (SUGGESTION). The orchestrator can treat absence of the file as a single-workstream plan.

---

## Verdict

The protocol architecture is solid — the harness/orchestrator separation is clean, the session lifecycle is well-structured, and the schema is mostly consistent with existing artifacts. The blocker and majors are concentrated in the flat z-plan DAG derivation and the v1/v2 mismatch on parallelism. Fix these before finalizing, and the protocol is ready for implementation.
