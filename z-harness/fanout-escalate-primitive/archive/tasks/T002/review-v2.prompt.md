You are reviewing code that Claude just wrote for task T002 RETRY v2: Write agents/scope-reconciler-audit.md agent definition.

This is a ROUND 2 review — focus **only** on whether the 4 prior findings were addressed. Do not re-scan unrelated content.

**Prior findings (v1) that must be verified fixed:**

1. **Major 1:** tools missing Write but procedure writes REPORT.md / copies artifacts. Either add Write or change agent to return content.
2. **Major 2:** dissent detection key includes severity → same evidence at diff severities never collides as dissent.
3. **Major 3:** severity elevation only fires on exact severity+evidence match; should elevate systemic issues seen in 2+ chunks.
4. **Major 4:** chunks with PASS verdict + 0 findings incorrectly flagged as malformed.

**Implementer's v2 claim:**
- Agent is now explicitly read-only (RETURN content via REPORT_CONTENT/CHUNK_ARTIFACTS fields, not write); 
- Map A (evidence-only key) for dissent detection; 
- Map B (severity+evidence) for exact dedup within severity; 
- Severity elevation operates on systemic findings (same normalized_evidence_key in ≥2 chunks); 
- Zero-finding PASS verdict accepted.

**Spec excerpt (from SPEC.md agents/scope-reconciler-audit.md section):**

Role: Given N per-chunk auditor findings, merge into a unified REPORT.md.
Procedure:
1. Read each chunk's findings-*.md.
2. Dedupe findings by (severity, normalized-evidence-line) across chunks.
3. Preserve dissent: if 2 chunks find conflicting things on the same site, emit BOTH with a `## Cross-chunk dissent` note.
4. Elevate cross-chunk patterns: if ≥2 chunks flag the same systemic issue, bump severity by one tier.
5. Emit unified REPORT.md and per-chunk chunks/ subdirectory preserved verbatim.

Hard rule: never smooths over disagreement. Dissent is a feature.

**Acceptance criteria (from task):**

1. Agent is read-only; REPORT.md and chunk artifacts returned in return message, never written by the agent.
2. Dissent detection uses evidence-only key (Map A); severity+evidence key (Map B) used only for exact dedup within severity.
3. Severity elevation applies to systemic issues (same normalized_evidence_key in ≥2 distinct chunks), NOT just exact severity+evidence matches.
4. PASS verdict with zero findings is valid; only malformed if Verdict section is absent.
5. Hard rules explicitly forbid writing to disk; all content returned via REPORT_CONTENT and CHUNK_ARTIFACTS fields.

**Delta (v2 changes):**

Key edits in the current file:
- Line 3: description now says "read-only — never writes to disk" and "Returns REPORT.md content and chunk artifact list for the orchestrator to write"
- Line 18: `output_dir` now clarified as "used for constructing paths in the return shape only. The agent does NOT write to this directory — the orchestrator owns all file writes"
- Line 25: "NO writes to disk. This agent is read-only. You return the REPORT.md content and an artifact-copy list in your return message. The orchestrator writes all files."
- Lines 34-36: Now explicitly accept PASS verdict with zero findings; clarify malformed only if Verdict field absent
- Lines 55-62: Map A (evidence-keyed for dissent) and Map B (severity+evidence for consensus dedup)
- Lines 69-79: Systemic = same normalized_evidence_key in ≥2 chunks; elevation only for systemic non-dissent
- Lines 83, 167-177: Compose REPORT.md content (return) not write; Step 6 returns CHUNK_ARTIFACTS list
- Lines 179-220: Return shape includes REPORT_CONTENT and CHUNK_ARTIFACTS; hard rules enforce read-only

**Scrutinize:**

1. **Major 1 (Write tool):** Is the agent confirmed read-only with all content returned (never written)? Check:
   - Description says read-only ✓
   - tools line does NOT include Write (currently: Read, Grep, Glob) ✓
   - Procedure Step 5 says "Do NOT write it to disk" and "include the full content verbatim in your return message" ✓
   - Return shape includes REPORT_CONTENT field ✓
   - Hard rule 6: "This agent is strictly read-only. Never write any file to disk" ✓
   - Hard rule 4: "Chunk artifacts are returned for the orchestrator to write. No editing, summarizing, or reformatting of source file content. Provide content verbatim in the return message." ✓

2. **Major 2 (dissent detection key):** Is Map A keyed by evidence alone (not severity)? Check:
   - Step 3, Map A description: "keyed by `normalized_evidence_key` alone" ✓
   - "any entry whose `findings` list contains 2 or more items **with different severities** is a **dissent group**" ✓
   - So same evidence at different severities WILL be detected as dissent (correct) ✓

3. **Major 3 (severity elevation scope):** Does elevation apply to systemic findings (≥2 chunks with same evidence), not just exact severity+evidence matches? Check:
   - Step 4 definition: "A finding is **systemic** if its `normalized_evidence_key` appears in ≥2 distinct chunks (regardless of whether those chunks assigned different severities)" ✓
   - "For systemic findings that are **not** in a dissent group: take the highest severity assigned by any chunk, then bump it by one tier" ✓
   - This correctly elevates ANY systemic non-dissent finding, regardless of whether all chunks agree on severity ✓

4. **Major 4 (PASS + zero findings):** Is zero-finding PASS verdict accepted as valid? Check:
   - Step 1, line 35-36: "A chunk file is **valid** if it contains a `## Verdict` section with a `PASS | NEEDS-WORK | BLOCKED` verdict, even if it has zero `### [SEVERITY]` finding blocks. A `PASS` verdict with zero findings is expected and correct — count it in the verdict tally without penalizing it as a failure." ✓
   - Hard rule 7: "PASS verdict with zero findings is valid. A chunk that audited its scope and found no issues should return `verdict: PASS` with no finding blocks. This is not malformed. Malformed means the verdict field is entirely absent." ✓

**Report:** Check for any remaining issues with the 4 fixes. Output ONLY blockers and majors.
