# Golden Snapshot Fixtures

This directory holds reference output snapshots captured from the former legacy
export scripts (`scripts/export-{cursor,codex,agy,pi}.py`). Those scripts have
since been deleted (T009); the snapshots remain as the reference baseline for
the runtime driver ports.

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

The golden test `test_export_golden.py` skips each target's runtime assertion when
`runtime/drivers/<target>/export.py` does not yet exist. As T003–T006 land:

| Task | File created | Test assertion flips |
|------|-------------|---------------------|
| T003 | `runtime/drivers/cursor/export.py` | cursor golden assert goes green |
| T004 | `runtime/drivers/codex/export.py` | codex golden assert goes green |
| T005 | `runtime/drivers/antigravity/export.py` | antigravity golden assert goes green |
| T006 | `runtime/drivers/pi/export.py` | pi golden assert goes green |
