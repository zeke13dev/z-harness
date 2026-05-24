---
description: "Export z-harness commands/agents/skills to Cursor / Codex / Antigravity (agy)."
role: workflow
---

You are running **z-harness `/z-export`**.

This command runs one or more export adapter scripts that translate z-harness source files (`commands/`, `agents/`, `skills/`) into IDE-specific formats under `exports/`.

## Phase 1 — Parse arguments

Read `$ARGUMENTS`. Look for `--target=<value>`.

Valid values: `cursor`, `codex`, `agy`, `all`.

Default (no `--target` flag): `all`.

If an unrecognized value is given, immediately print:

```
[z-export] error: --target must be one of: cursor, codex, agy, all
```

and exit nonzero. Do not proceed.

Build the target list:
- `cursor` → `["cursor"]`
- `codex` → `["codex"]`
- `agy` → `["agy"]`
- `all` → `["cursor", "codex", "agy"]`

## Phase 2 — Run per-target export scripts

For each target in the list, run the corresponding script via Bash:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/export-<target>.py"
```

(Replace `<target>` with the actual target name, e.g. `export-cursor.py`.)

**Important:** run targets sequentially, not in parallel. Capture stdout and stderr for each separately.

For each target:

1. Note the exit code.
2. On **exit 0**: parse stdout for a line matching the pattern `files written to <path>` or similar output from the export script. Extract the file count and output path. Then print:
   ```
   [<target>] OK — <count> files written to <relative path>
   ```
   If the script does not emit a parseable count/path line, print:
   ```
   [<target>] OK — exports/<target>/
   ```
3. On **nonzero exit**: capture the last 20 lines of stderr. Mark this target as FAILED. Print:
   ```
   [<target>] FAILED (exit <code>)
   --- stderr (last 20 lines) ---
   <last 20 lines of stderr>
   ---
   ```
   Then **continue to the next target** — do not abort.

## Phase 3 — Final summary

After all targets have been attempted:

**If no targets FAILED:**

Print:

```
All export targets succeeded.
```

Exit 0.

**If any targets FAILED:**

Print:

```
<N>/<total> targets failed: <comma-separated list of failed target names>
```

where `<N>` is the count of failed targets and `<total>` is the total number of targets attempted.

Exit nonzero (return a non-zero status to the user). You may signal this by ending your response with a clear `[z-export] exiting with errors.` line so the user knows the run did not fully succeed.

## Hard rules

- **Continue past failures.** A single target failure must not abort remaining targets.
- **No silent failures.** Every target must produce an explicit OK or FAILED line.
- **No LLM interpretation of export output.** Just capture the script's stdout/stderr verbatim; do not summarize or editorialize on what the export produced.
- **Relative paths in OK output.** Output paths should be relative to the repo root (strip the leading absolute path prefix).
- **No writes by this command.** All file I/O is delegated to the export scripts.
