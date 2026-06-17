---
inclusion: manual
description: Read-only lazy-code debt ledger. Scans for z-colon debt markers and renders a grouped ledger to stdout. Flags no-trigger entries. Optional one-shot persist to Z-DEBT.md when the user asks.
---

You are running **z-harness `/z-debt`** — a lightweight, one-shot debt-ledger scanner. Read-only by default. No subagent dispatch, no LLM analysis, no tracker coupling.

## What it does

Scans the repository for **z-colon debt markers** — inline annotations a developer left in source code to signal intentional shortcuts, ceilings, and planned upgrade paths. Renders a grouped markdown ledger to stdout. Optionally saves to `Z-DEBT.md` when the user explicitly asks with `--save`.

## Marker grammar

A valid z-colon marker is a **comment** containing the literal token `z:` (lowercase, preceded by a single space, following a comment leader). Supported comment leaders: `#`, `//`, `--`. The marker can appear anywhere on the line — both as a standalone comment line or as a trailing inline comment.

Pattern (strict): a comment leader (`#`, `//`, or `--`) followed immediately by ` z: ` (space-z-colon-space).

Example of valid markers (shown with placeholders to avoid self-matching):

- Python/YAML/shell: `# z<:> <what>. ceiling: <X>. upgrade: <Y>.`
- JavaScript/TypeScript: `// z<:> <what>. ceiling: <X>. upgrade: <Y>.`
- SQL: `-- z<:> <what>. ceiling: <X>. upgrade: <Y>.`
- Trailing inline: `do_work(); // z<:> <what>. ceiling: <X>. upgrade: <Y>.`

The payload conventionally uses the form `<what>. ceiling: <X>. upgrade: <Y>.` but the scanner accepts any non-empty payload — partial forms are valid markers, just flagged `no-trigger` if `upgrade:` is absent.

**Deliberate false-positive avoidance:** require the comment leader + space before `z:` so strings like `fuzz:`, `topaz:`, or bare `z:` in non-comment contexts are not matched.

## Phase 0 — Parse arguments

Parse `$ARGUMENTS` before scanning:

1. If `$ARGUMENTS` contains `--save`, set `_zh_save=true` and remove the `--save` token.
2. If the remaining tokens form a single non-flag token (a path), use it as `_zh_args_path`.
3. If there are remaining tokens that look ambiguous (multiple tokens, or tokens starting with `-` that aren't `--save`), emit:
   `Usage: /z-debt [--save] [<path>]` and stop.
4. Otherwise proceed with `_zh_save=false` and no scoped path.

## Phase 1 — Scan

Run from the repo root (or the path given by `_zh_args_path`, if any):

```bash
# Determine repo root (fall back to cwd)
_zh_repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Optional scoped path from $ARGUMENTS (after stripping --save)
_zh_scan_path="${_zh_args_path:-$_zh_repo_root}"

# Grep: comment leader + space + z: — unanchored so inline trailing comments are caught
# -rn: recursive + line numbers; --include covers common source/config/doc types
# -E: extended regex for alternation
grep -rn -E \
  '(#|//|--) z: ' \
  --include="*.py" --include="*.sh" --include="*.bash" \
  --include="*.js" --include="*.ts" --include="*.jsx" --include="*.tsx" \
  --include="*.rb" --include="*.go" --include="*.rs" --include="*.java" \
  --include="*.c" --include="*.cpp" --include="*.h" --include="*.hpp" \
  --include="*.lua" --include="*.r" --include="*.R" \
  --include="*.sql" --include="*.toml" --include="*.yaml" --include="*.yml" \
  "$_zh_scan_path" 2>/dev/null
```

Note: `.md` and `.txt` files are intentionally excluded from the default scan — documentation and skill files commonly contain illustrative marker examples that are not real debt. If you need to scan docs, pass the path explicitly.

Parse each result line as `<file>:<lineno>:<content>`. Extract:
- `file` — path relative to `_zh_repo_root` (strip the leading `_zh_repo_root/` prefix)
- `lineno` — integer
- `payload` — everything after the comment leader + ` z: ` (trimmed)
- `has_upgrade` — true if `upgrade:` appears (case-insensitive) anywhere in the payload

## Phase 2 — Render ledger

Group results by `file` (sorted alphabetically). Within each file, sort by `lineno` ascending.

Print the ledger to stdout in this exact format (the heading uses `z:` literally in output, not in this SKILL.md source):

```
[debt-ledger-heading]

### <file>

- <file>:<lineno> — <payload>  [no-trigger]?

### <file2>

- <file2>:<lineno> — <payload>
```

The `[debt-ledger-heading]` above stands for the literal markdown heading `## z: debt ledger` (written that way in the output, not in this doc to avoid self-matching).

Row format rules:
- Row literal: `- <file>:<line> — <payload>` (NO backtick wrapping around `<file>:<line>`)
- Append `  **[no-trigger]**` (two spaces, bold) after the payload when `has_upgrade` is false.
- Omit the `[no-trigger]` suffix when `upgrade:` is present.
- Do NOT truncate payloads. Render verbatim.
- If zero markers found, print exactly: `No z: debt. Clean ledger.`

Footer line (always printed when markers > 0):

```
<N> markers, <M> no-trigger.
```

Where `N` = total markers found, `M` = count of no-trigger entries.

## Phase 3 — Optional persist

**Default: read-only.** Do not write any file unless `--save` was present in `$ARGUMENTS`.

Persist trigger: `_zh_save=true` (set only from `--save` flag in Phase 0).

If `_zh_save` is true:

1. Write the rendered ledger (same content as stdout) to `Z-DEBT.md` at the repo root.
2. Print below the ledger: `Saved to Z-DEBT.md.`

If `_zh_save` is false: do not write `Z-DEBT.md`. Do not prompt. Do not suggest it unless the user asks with `--save`.

## Hard rules

- **READ ONLY** unless `--save` flag was present. Never write `Z-DEBT.md` based on NL phrasing alone.
- **No LLM analysis.** Render what the grep finds; do not paraphrase or critique markers.
- **No tracker coupling.** Do not open GitHub issues, create tickets, or call any external API.
- **No auto-upgrade.** Never modify source files.
- **No `env -i`.** Use the inherited environment as-is.
- **No subagent dispatch.** Single phase, instant (≤2s wall time for typical repos).
- Robust to empty results — `No z: debt. Clean ledger.` is a valid, successful output.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | no | — |
| `skill_invoke` | no | — |

This skill has no gated blocks; it runs in any driver that supports Bash execution.
