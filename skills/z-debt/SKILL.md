---
name: z-debt
disable-model-invocation: false
description: "Read-only lazy-code debt ledger. Scans for z-colon debt markers and renders a grouped ledger to stdout. Flags no-trigger entries. Persist to Z-DEBT.md only with --save."
argument-hint: "[--save] [<path>]"
runtime: c1
---

You are running **z-harness `/z-debt`**. Invoke the `z-debt` skill.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

Follow the `skills/z-debt/SKILL.md` phases exactly:

1. **Parse arguments (Phase 0).** Recognize `--save` flag only (note it for Phase 3). Remaining single non-flag token, if any, is a scoped path. If there are multiple unknown tokens or unrecognized flags, emit `Usage: /z-debt [--save] [<path>]` and stop.

2. **Phase 1 — Scan.** Determine repo root via `git rev-parse --show-toplevel` (fall back to `pwd`). Run the grep (unanchored `-E` pattern so inline trailing comments are caught; `.md` files excluded). Collect all `<file>:<lineno>:<content>` hits.

3. **Phase 2 — Render.** Group by file (alphabetical), sort by line number within each file. Print the debt ledger heading, then per-file sections with bullet rows. Row format: `- <file>:<line> — <payload>` (no backticks around file:line). Append `  **[no-trigger]**` to any row whose payload lacks `upgrade:`. If zero hits: print `No z: debt. Clean ledger.` and stop. Otherwise print footer `<N> markers, <M> no-trigger.`

4. **Phase 3 — Persist (only if --save).** If `--save` was present in `$ARGUMENTS`, write the rendered ledger to `Z-DEBT.md` at the repo root and print `Saved to Z-DEBT.md.` Do NOT trigger on NL phrasing alone.

## Hard rules (non-negotiable)

- **READ ONLY** unless `--save` flag was explicitly passed.
- **No LLM analysis** — render grep output verbatim.
- **No tracker coupling** — do not open issues or call external APIs.
- **No auto-upgrade** — never modify source files.
- **No subagent dispatch** — single inline phase.
