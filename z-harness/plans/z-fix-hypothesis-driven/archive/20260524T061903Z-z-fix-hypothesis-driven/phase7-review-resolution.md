# Phase 7 — Plan review resolution

Both reviewers (Gemini + Codex) raised six overlapping concerns. Resolution per item, with "one reason it might be wrong" pushback applied:

## Q1 — Orchestrator-only likelihood / contamination boundary

**Gemini:** orchestrator-generated R1 hypotheses stay in LLM context history; "read from disk" doesn't erase them from reasoning. Recommends delegating R1 orchestrator generation to a subagent.

**Codex:** Round 3 (Eliminated Alternatives) leak — consultants would see test-derived conclusions indirectly.

**Pushback (Gemini):** the orchestrator's task during merge is semantic dedup against text strings on disk — NOT re-generation. Reasoning-persistence biases dedup judgment marginally, not catastrophically. Removing the orchestrator from R1 generation entirely would also delete the strongest hypothesis source (the one with full evidence context) for ceremony purposes.

**Resolution:** keep orchestrator R1 generation but tighten the merge rule. **Apply changes:**
- SPEC merge rule: "semantic dedup MUST use the exact written text of each row, not the orchestrator's recall of intent. Two rows from different models with the same `claim` text (or close paraphrase, judged by content not source) merge with `overlap_count += 1`."
- Phase 0 of SPEC adds an explicit **Phase-visibility matrix** (Codex's recommendation) — table of `(phase, consultant mode, sections passed, raw test output permission)`. This belongs in SPEC's invariants section.

**Resolution (Codex Round 3 leak):** Round 3 (if it happens) hands consultants ONLY the eliminated `claim` text and the `discriminating_test` that falsified each — NOT the likelihood bucket nor the posterior. Facts, not judgments. Document in SPEC Phase 6 loop logic.

## Q2 — Round 2 forbid-agreement enforcement

**Gemini:** prompt instruction is too weak; LLMs will smuggle agreement as "nuanced refinements." Add orchestrator post-process filter.

**Codex:** treat agreement-shaped output as schema violation; require critique rows to reference hypothesis IDs.

**Both correct.** Accept both:
- Add hypothesis IDs (`H001`, `H002`, ...) to the Hypothesis Pool table at Phase 3a merge step.
- Round 2 mode contract requires critiques to cite `target_id: H<NNN>` per row. Critiques without a target_id are invalid and discarded by orchestrator post-process.
- Orchestrator post-process: any Round-2 NEW row whose `claim` text matches (semantic dedup, same rule as merge) an existing pool row is dropped as a non-orthogonal duplicate. Any critique row whose `critique_type` doesn't name a concrete problem (e.g., critique text == "looks good", "agree") is discarded.

## Q3 — Fix-gate measurability ("explains all evidence")

**Both:** "explains all evidence" is too subjective; reopens BRAINSTORM's #1 risk.

**Codex's concrete fix (accepted):** assign evidence IDs (`EVID-001`, `EVID-002`, ...) during Phase 2 Evidence Inventory. Phase 7 Root Cause section MUST include an **Evidence coverage table** with one row per `EVID-NNN`, status ∈ `{explained, falsifies_alternative, orthogonal_with_reason, unexplained}`. Fix-gate opens only when zero `unexplained` rows AND winning hypothesis posterior is highest.

**Apply changes:**
- Phase 2 Evidence Inventory: each piece of evidence gets a stable `EVID-NNN` ID (orchestrator-assigned at capture time).
- Phase 7 Root Cause section: required `### Evidence coverage` subsection with markdown table `| evid_id | text | status | how_root_cause_handles_it |`.
- Phase 7 fix-gate logic: hard precondition: `count(rows where status == unexplained) == 0`. If any unexplained, halt and either upgrade the root cause or return to Phase 6.

This also unifies with Q4 — the evidence-coverage table is the compact evidence context for Round 2.

## Q4 — Surgical extraction is too aggressive

**Both:** Round 2 consultants can't judge test discriminability without the Problem + Evidence; fix consult can't validate symptom coverage.

**Pushback:** the original concern was context bloat at 5 cycles. But context bloat happens in the *orchestrator's* main thread (cumulative DEBUG.md across cycles), not in subagent prompts (which are one-shot, fresh-context). Subagent context budget is separate.

**Resolution — revised extraction map:**
- **Round 1:** Problem + Evidence Inventory.
- **Round 2:** Problem + Evidence Inventory + Hypothesis Pool. (Per Gemini Q4.)
- **Fix consult (Phase 7):** Problem + Evidence Inventory + Hypothesis Pool (winners only) + Experiment Log + draft Root Cause + draft Evidence coverage table.
- **Round 3 (if any):** Problem + Evidence Inventory + Eliminated Alternatives (claim text + falsifying test only, no buckets per Q1 resolution).

Document this map as the Phase-visibility matrix in SPEC invariants.

## Q5 — Return-shape contract tightness

**Codex:** formalize Round 2 critique row schema — `target_id | critique_type | problem | recommended_action | merge_with_id` with `critique_type ∈ {non_discriminating_test, false_parallel_safe, duplicate, weak_claim, unclear_prediction}`.

**Gemini:** mandate JSON for both rounds.

**Pushback on Gemini:** the rest of the plugin uses markdown tables (Test Matrix, Evidence coverage, etc.). Forcing JSON returns creates a parsing fork between consultant output and DEBUG.md insertion. Markdown tables with documented headers are parseable without regex hell (`csv.reader` with `delimiter='|'` works after trimming).

**Resolution:** accept Codex's formal critique schema, in markdown table form. Document as part of the `generate-hypotheses-round2-adversarial` mode contract in both agent files. Apply same level of rigor to Round 1 returns (already has clear field list).

**Round 2 critique schema (locked):**
```markdown
| target_id | critique_type | problem | recommended_action | merge_with_id |
```
where `critique_type ∈ {non_discriminating_test, false_parallel_safe, duplicate, weak_claim, unclear_prediction}` and `merge_with_id` is populated only when `critique_type == duplicate`.

**Round 2 NEW row schema (locked):** same as Round 1 schema (claim, prediction_if_true, prediction_if_false, discriminating_test, test_cost, parallel_safe, reasoning), with one additional column `orthogonality_to: [target_ids]` documenting which pool entries this fills a gap relative to.

**Codex's adjacent point** (parallel_safe critique must cite a specific mutation): accept. Round 2 mode contract requires `critique_type: false_parallel_safe` rows to include the mutation in the `problem` cell (e.g., `"writes to ~/.cache/foo"`).

## Q6 — Migration scope incomplete

**Both:** scan must cover more than `commands/z-debug.md`.

**Verified via grep:** real cross-references found in:
- `commands/z-improve.md:45` — references `POST-MORTEM.md` and `PROBLEM.md`.
- `commands/z-stats.md:97-99` — describes z-debug flow and `POSTMORTEM.md` action items.
- `commands/z-suggest-memory.md:2` — references "/z-debug post-mortem" (conceptual).
- `skills/z-improve/SKILL.md:45` — same as commands/z-improve.md.
- `skills/z-suggest-memory/SKILL.md:382-385` — references POSTMORTEM.md "Root cause" section and PROBLEM.md "Relevant concepts:" line.
- **`skills/z-debug/SKILL.md` — parallel skill-form copy of `commands/z-debug.md`**, full ~340 lines, with all the same artifact references. This is a duplicate that must be rewritten in lockstep with the command form.

**Resolution:** expand PLAN Phase E into Phase E1 (audit + update non-z-debug references) and add a new Phase C2 (rewrite `skills/z-debug/SKILL.md` in lockstep with `commands/z-debug.md`). All POSTMORTEM.md / PROBLEM.md / EVIDENCE.md / ISOLATION.md references must be rewritten to either:
- Section references within unified `DEBUG.md` (e.g., `"DEBUG.md ## Post-mortem"`), OR
- Documented as legacy (for historical archive runs prior to the rewrite).

**`skills/z-suggest-memory/SKILL.md:223` referencing `source: debug:<run-id>`** — that's a conceptual reference to the calling context, not an artifact path. Keep as-is.

**`commands/z-suggest-memory.md:2` description** referencing "/z-debug post-mortem" is also conceptual. Keep as-is.

## Items rejected

None. All six concerns are real and accepted (with one substitution: Codex's markdown table over Gemini's JSON for Q5).

## Net additions to plan

1. Phase-visibility matrix added to SPEC invariants (Q1).
2. Orchestrator merge rule pinned to text-only semantic dedup (Q1).
3. Round 3 input shape restricted to claim + falsifying-test (Q1).
4. Hypothesis IDs `H<NNN>` introduced; required in Round 2 critique target_id (Q2).
5. Round 2 orchestrator post-process filter rules documented (Q2).
6. Evidence IDs `EVID-<NNN>` introduced at Phase 2 (Q3).
7. Evidence coverage table required in Root Cause (Q3) — also serves as Q4 compact context.
8. Fix-gate hard precondition: zero unexplained EVID rows (Q3).
9. Surgical extraction map (Q4) — documented as the Phase-visibility matrix.
10. Round 2 critique table schema with controlled `critique_type` vocabulary (Q5).
11. Round 2 NEW row gets `orthogonality_to` column (Q5).
12. `false_parallel_safe` critiques must cite specific mutation in `problem` cell (Q5 / Codex side note).
13. Phase E expanded; new Phase C2 added for `skills/z-debug/SKILL.md` lockstep rewrite (Q6).

These flow into TASKS.md as additional task ordering + acceptance criteria.
