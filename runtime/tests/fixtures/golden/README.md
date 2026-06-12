# Golden Snapshot Fixtures

This directory holds reference output snapshots for the runtime export drivers
(`runtime/drivers/<target>/export.py`).

**Last re-baseline:** 2026-06-11 — post-merge re-baseline after merging
`f/claude/z/export-runtime-drivers` into `main`. The merged tree included:
(a) the `run-brief-finalize.md` shared fragment change affecting ~13 commands,
(b) new commands/agents/skills (z-context-budget, z-doc-rationale, z-evaluate,
z-handoff, z-reality, z-verify, pre-reviewer, tier1-doc-updater, z-test-invariant),
and (c) migration-era updates (runtime driver self-references in CAPABILITIES.md,
README.md, agy-plugin.yaml; updated z-export description; slug field in
z-implement-all/next session-status). Fixtures now reflect the merged source tree.

Validation performed before re-baselining: runtime output was compared against
the last legacy export (commit 815d001). All differences were traced to source
changes after 815d001 (bef4ae1 adding slug field; 33c727f updating z-export.md
description) or migration-era driver self-reference updates — no unexpected
runtime-vs-source divergences found. Runtime == legacy on all files where the
source was unchanged since 815d001.

The former legacy scripts (`scripts/export-{cursor,codex,agy,pi}.py`) have been
deleted (T009); the runtime drivers are the sole export path.

The golden comparator in `runtime/tests/test_export_golden.py` normalizes both
sides before equality checking. See "Normalization rules" below.

---

## Determinism

Each legacy exporter was invoked **twice** into separate temp directories at
capture time and the outputs were compared with `diff -r` before snapshotting.
All four targets were confirmed deterministic (see table below). The live
automated determinism tests (formerly `TestLegacyDeterminism`) were removed in
T009 when the legacy scripts were deleted.

| Target       | Deterministic? | Source of non-determinism | Normalization applied |
|--------------|----------------|---------------------------|-----------------------|
| cursor       | YES            | n/a                       | repo-root path → `<REPO>` |
| codex        | YES            | n/a                       | repo-root path → `<REPO>` |
| antigravity  | YES            | n/a (manifest has no timestamps or mtime fields; entry order controlled by `sorted(directory.glob("*.md"))` and `sorted(skills_dir.iterdir())`) | repo-root path → `<REPO>` |
| pi           | YES            | n/a                       | repo-root path → `<REPO>` |

---

## Normalization rules

`normalize_for_comparison(root_dir, repo_root)` applies these transformations to
file content **on both the snapshot side and the live side** before comparison:

1. **Repo-root path stripping** — every occurrence of the absolute repo root path
   (e.g. `/Users/zeke/dev/z-harness-export-rt`) is replaced with `<REPO>`. This
   prevents the test from failing when executed on a different machine or in a
   different checkout location.

No additional normalizations are required because all four targets are fully
deterministic.

---

## Snapshot contents

```
fixtures/golden/
├── cursor/           # captured from the former scripts/export-cursor.py
│   └── .cursor/rules/*.mdc           (118 files)
├── codex/            # captured from the former scripts/export-codex.py
│   ├── AGENTS.md
│   └── prompts/*.md                  (90 files + AGENTS.md)
├── antigravity/      # captured from the former scripts/export-agy.py
│   ├── .agent/workflows/*.md         (54 files)
│   ├── .agent/rules/*.md             (28 files)
│   ├── .agent/skills/**/SKILL.md     (36 files)
│   ├── prompts/*.md                  (118 files)
│   ├── agy-plugin.yaml
│   ├── CAPABILITIES.md
│   └── README.md
└── pi/               # captured from the former scripts/export-pi.py
    ├── agents/*.md                   (29 files)
    ├── prompts/*.md                  (90 files)
    ├── extensions/subagent/          (vendored TS extension)
    ├── AGENTS.md
    ├── CAPABILITIES.md
    └── README.md
```

---

## Wiring to runtime ports

All four runtime driver ports are now complete (T003–T006 landed). The golden
test `test_export_golden.py` runs all four target assertions without skipping.

| Target | Driver | Status |
|--------|--------|--------|
| cursor | `runtime/drivers/cursor/export.py` | live — green |
| codex | `runtime/drivers/codex/export.py` | live — green |
| antigravity | `runtime/drivers/antigravity/export.py` | live — green |
| pi | `runtime/drivers/pi/export.py` | live — green |
