# Final review — brainstorm-and-research

Run: 20260522T172231Z-review
Base ref: HEAD (`aaa6f80`) — plan changes are uncommitted working-tree edits
Diff stats: 9 files, ~2371 lines (4 new + 5 modified)

## Prong A — Implementation drift

### Severity: blocker

- **[both] `agents/gemini-consultant.md` is missing the cross-mode hardening that T001 added to codex-consultant.** T002's cycle-1 review missed three issues that T001 cycle-2 fixed in the sibling file:
  1. **L51-70 "Returning to the caller"** mandates the standard wrapper unconditionally. No carve-out for `brainstorm` and `research-review` (which must return RAW). The mode entries at L29-30 claim "Return RAW — no standard wrapper," but the operational section below contradicts them. Mirror T001's fix: split into wrapper-modes vs raw-modes.
  2. **L83 `SLUG="gemini-<bundled-decisions|plan-review>"`** hardcodes only two modes. All other modes (light-fix, debug-hypotheses, doc-audit, test-cases, brainstorm, research-review) will get inconsistently labeled transcripts. Fix: `SLUG="gemini-$MODE"` (matches the T001 fix in codex-consultant.md L100).
  3. **L45 + L49 "Building the prompt to Gemini"** only enumerates Ask templates for `bundled decisions` and `plan review`. The new modes (brainstorm, research-review) and the other 4 existing modes have no Ask templates. Mirror T001's fix: add per-mode Ask templates for all 8 modes; brainstorm enumerates 5 sections; research-review includes explicit "do NOT recommend an approach".

### Severity: major

- **[gemini] `commands/z-plan.md` Setup step 10 vs Setup step 1 ordering.** The new precontext detection in step 10 fires *after* the slug-collision check in step 1, but step 1's "distinguish precontext-only vs finished-plan" rule requires the same artifact-detection logic that step 10 performs. The two steps duplicate scanning and could disagree if files appear between them. Push-back consideration: the operations are idempotent, so the duplication is harmless. Recommend merging the artifact scan into a single helper invoked from both, or accept the duplication and document it.

- **[gemini] BRAINSTORM.md `ideators` YAML list structure is ambiguous in the command file.** SPEC L161 says failed members are recorded as `"<id>:failed"`. The command file (z-brainstorm.md Phase 3) shows the example as `- claude` + a YAML comment `# failed members recorded as "<id>:failed"`. A reader could interpret this as either an annotated list (string item `"claude:failed"`) or a separate keyed structure. Tighten to: "If `<id>` fails, the list item itself becomes `<id>:failed` (a plain string, not a separate field)."

### Severity: minor

- **[gemini] Consultant mode prose phrasing inconsistent.** codex-consultant uses "Does NOT use the standard return wrapper" while gemini-consultant uses "Return RAW — no standard wrapper." Both correct; tighten to one phrase for grep-ability.

- **[gemini] z-brainstorm/z-research command files don't list env vars upfront.** README documents `Z_HARNESS_BRAINSTORM_EXPLORE`, but neither command file has an "Environment" section at the top. Inconsistent with how /z-plan documents its env knobs.

### Pushed back (LLM flagged but rejected)

- **[codex] "Missing `append-to-new-run` option in /z-brainstorm Setup step 5."** This option was *deliberately dropped* in T003 cycle-2 per a prior reviewer finding (MAJOR 2: "option underspecified — drop or define"). The Restart flow within a single run already covers the "do another pass" use case. Restoring the option would re-introduce the undefined behavior the cycle-1 reviewer flagged. Spec text at L165 ("Re-run on existing BRAINSTORM.md: prompt overwrite / append (= move to .previous-<N>) / abort") is stale relative to the implemented decision — see Prong B major below.

## Prong B — Spec gaps

### Severity: blocker

- (none — none of the findings rise to "ship-blocking spec defect")

### Severity: major (worth amending SPEC)

- **[both, transposed] Spec L165 still says "overwrite / append / abort" but the implementation dropped append.** The SPEC needs to be amended to match the implemented "overwrite / abort" decision (or the implementation needs the third option back). Recommend amending SPEC — the implementer's cycle-2 reviewer correctly rejected the under-specified append option.

- **[gemini] Anti-bias "Claude-favoring justification" rule is one-sided.** SPEC L58 + z-brainstorm Phase 3 say *if you pick Claude over a peer, justify*. They do not say what to do for Codex-over-Gemini, Gemini-over-Codex, or peer-over-Claude. Reading: the rule is one-sided by design (only the orchestrator's own-vendor pick needs justification). Defensible, but the SPEC should state explicitly which direction the rule cuts, since "anti-bias" by name implies symmetry.

- **[gemini] `/z-research` `depends_on:` frontmatter semantics undefined.** SPEC L85 shows `depends_on: []` always. Behavior is unclear if a future /z-research run wants to chain on a prior research note. Recommend amending: either lock it to `[]` for v1 (explicit) or document the upstream-artifact case (`depends_on: [BRAINSTORM.md]` if scaffolded from one).

- **[gemini] BRAINSTORM restart-flow archived-copy frontmatter mutation is implementation-only.** z-brainstorm Phase 4 sets the archived copy to `status: complete, chosen_framing: restart`. SPEC L165 doesn't mention this mutation. Implementation is correct (otherwise the historical copy would be spec-invalid), but the rule should appear in SPEC.

- **[gemini] `/z-research` Setup mutates workspace before Phase 0 cost gate.** TASKS.md notes this as "partial-fix minor accepted." SPEC should be amended to either (a) require mkdir + research_run_start to run only post-cost-gate, or (b) explicitly document that setup mutations precede the gate and orphan empty dirs are acceptable. Currently a known issue with no SPEC text.

### Severity: minor

- **[gemini] `/z-plan` Phase 1 task-adjacency rule is in implementation but not SPEC.** z-plan.md uses "≥1 distinct facet of the task" / "citing a file in the task's likely-touched set" — SPEC L215-221 doesn't mention adjacency. Code is correct; SPEC could be tightened.

- **[gemini] `precontext_source_deleted` event severity isn't operationalized.** SPEC L199 says it's "higher severity than stale-mtime" but the user-gate treats it identically. Decide: either auto-block on deleted source, or remove the severity-implying language.

- **[gemini] BRAINSTORM orchestrator-recommendation tie-breaking unspecified.** Edge case (all three framings equally compelling). Probably fine to leave the orchestrator's judgment, but worth one sentence.

- **[gemini] `## Cross-LLM review notes` section authorship is implementation-clarified but not spec-clarified.** Tighten SPEC to state "orchestrator writes this section in Phase 5."

## Consensus vs disagreement

**Both LLMs agreed (high confidence):**
- gemini-consultant.md needs the wrapper/SLUG/Ask-template carve-outs (3 Prong-A blockers).

**Codex-only:**
- "Missing append-to-new-run" — rejected (see push-back above).

**Gemini-only:**
- All Prong B findings (Codex's review was shorter and focused on Prong A).

## Summary by severity

| | Prong A (drift) | Prong B (spec gaps) |
|---|---|---|
| Blockers | 3 (all in gemini-consultant.md) | 0 |
| Majors | 2 | 5 |
| Minors | 2 | 4 |

Total actionable items: 3 blockers + 7 majors + 6 minors.
