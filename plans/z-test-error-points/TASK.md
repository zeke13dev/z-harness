# z-test dual-source redesign — plan

## Converged premise

Replace `z-test`'s current invariant-only approach with a **dual-source** architecture: ERROR_POINTS.json (empirical regression hardening from review findings) + INVARIANTS.json (preventive coverage from declared design truths), with a configurable interleave ratio.

### Key design decisions (from /z-brainstorm)

1. **Dual-source, not replacement** — ERROR_POINTS.json does NOT replace INVARIANTS.json. Both sources feed `z-test`. Default interleave: 70% error-points / 30% invariants.
2. **ERROR_POINTS registry** — New artifact at `docs/ERROR_POINTS.json`. Each entry: `ep_id`, `pattern`, `anchor_module`, `frequency`, `last_seen`, `severity`, `fixture_scope`, `tests_targeting`. Accumulates from every `z-review-all` run.
3. **INVARIANTS.json augmentation** — Add `sighting_count`, `last_sighting`, `anchor_module` to the existing invariant schema. Reuse existing Phase 5.5 Haiku subagent to increment counters on matched findings.
4. **z-review-all integration** — Every review run ALWAYS generates error point candidates via a cheap LLM subagent (reuse/extend Phase 5.5). Findings matched to existing error points increment frequency. Unmatched findings create new entries.
5. **z-test modes** — `--mode error-points | invariant | dual` (default: dual).
6. **Pruning** — Error points with `tests_targeting > 0` and no sightings in N review runs → archived. Archived points can resurrect if pattern reappears.
7. **Signal discipline** — Deterministic matching (module path similarity) before LLM classification. Classifier and test drafter use independent models to avoid compounding errors.
8. **Write rate-limiting** — Cap new error points per review run to prevent registry poisoning.
9. **Archive current z-test** — Current z-test skill archived as `z-test-invariant` (available via `--alt invariant`).
10. **Init bootstrap** — First-run codebase scan for bug patterns, error handlers, TODO/FIXME sites to seed initial registry.

### Scope

This touches:
- `skills/z-test/SKILL.md` — major rewrite for dual-source pipeline
- `docs/schemas/invariant.schema.json` — add sighting_count, last_sighting, anchor_module
- `docs/INVARIANTS.json` — migrate to new schema
- `docs/schemas/error_points.schema.json` — new schema
- `skills/z-review-all/SKILL.md` — extend Phase 5.5 (or add Phase 5.6) for error point extraction
- `scripts/validate-invariants.py` — update for new schema fields
- `scripts/validate-error-points.py` — new validation script
- `AGENTS.md` — update z-test description in routing table
- `exports/pi/prompts/z-test.md` — re-export
- Archive current `skills/z-test/SKILL.md` → `skills/z-test-invariant/SKILL.md`

### Constraints

- Do NOT run any z-harness shell scripts or setup commands
- Just read files and write files
- Do NOT stop to ask for permission at any gate — you have everything you need

/go z-plan
