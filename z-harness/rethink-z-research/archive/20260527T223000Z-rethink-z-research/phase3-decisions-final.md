# Phase 3 — Decisions final (post-consult)

## Final calls + "one reason it might be wrong" pass

### D1: Inline dispatch + audit grafts
- **Final call:** Inline dispatch via Agent() (Gemini's pick), with Codex's audit grafts: emit `research_dispatch_decision` event per sub-command dispatched; create `archive/<RUN>/subruns/<map|brainstorm|panel-<perspective>|judge>/` sub-folders for each nested run so the audit trail exists even without two-step ceremony.
- **One reason wrong (Codex):** weakens planning-family no-auto-execute contract. **Mitigation:** explicit telemetry + sub-run archives preserve auditability without breaking single-command UX. The contract argument applies to ROUTE decisions; this is COMPOSITION, which /z-uplift already does (just at the implementation tier instead of planning tier).

### D2: User-driven AskUserQuestion with state-aware defaults
- **Final call:** (c). Both consultants endorse.
- **One reason wrong:** AskUser adds friction users may find annoying for "obvious" cases (e.g., neither artifact exists → both will obviously run). **Mitigation:** if both artifacts are absent, the AskUser shows "both will be dispatched — confirm or change?" with a clearly default-affirmative option (single click to proceed).

### D5: Lead-with-matrix schema + schema_version + artifact_kind
- **Final call:** (b) reordered (matrix first) + Codex grafts: add `schema_version: 1` and `artifact_kind: approach_synthesis` to frontmatter for future-proof migrations.
- **One reason wrong:** more frontmatter fields = more things that can drift between writer and reader. **Mitigation:** explicit schema_version field gives /z-plan a clean way to detect version mismatches and warn rather than silently mis-parse.

### D8: One-way gate with explicit legacy fallback
- **Final call:** (a) one-way gate via `artifact_kind: approach_synthesis` frontmatter check. If present + status complete → inject only RESEARCH.md, ignore MAP.md + BRAINSTORM.md. If missing OR `artifact_kind: map` (legacy old-RESEARCH.md → MAP.md migration) OR status incomplete → fall back to component-file behavior.
- **One reason wrong:** if the synthesis hallucinates or omits a key MAP/BRAINSTORM detail, /z-plan flies blind. **Mitigation:** D6 already enforces citations per matrix cell + UNVERIFIED markers; /z-plan reads UNVERIFIED cells and surfaces them as open questions.

### D10: Orthogonal axes + explicit `needs_research` migration
- **Final call:** (c). Add new reason code `needs_approach_synthesis` for new /z-research. The existing `needs_research` reason code in planning-router gets renamed to `needs_terrain_map` (since that's now what it pointed to). Migration: any in-flight references to old `needs_research` are mechanically renamed.
- **One reason wrong:** users see the rename and assume `needs_research` (old) is gone, missing that the new /z-research uses a different reason code. **Mitigation:** keep `needs_research` as an *alias* deprecated-warning reason code that recommends /z-map for one version cycle, then drop. Documented in router agent + commands/z-map.md changelog.

## No shortcuts taken

All five flagged decisions land on the robust path. No `--skip-` flags, no "v1.5 punt that becomes v2.5," no degraded fallbacks except the explicit legacy fallback for D8 (which is required for the rename to be non-breaking).

## Cross-cutting concerns from consultants

1. **Synthesis hallucination risk** (both consultants flagged) → D6 already addresses via mandatory citations + UNVERIFIED markers.
2. **Artifact name confusion during migration** (Codex) → D5 schema_version + artifact_kind fields handle this; documentation in commands/z-map.md changelog handles user-facing.
3. **Inline-dispatch token burst** (Gemini noted as acceptable; Codex flagged as auditability risk) → resolved by inline+audit grafts; sub-run archives provide audit trail.
4. **Router orthogonality discipline** (both) → reason codes are explicit and documented; new docs section in planning-router.md clarifies map vs research.
