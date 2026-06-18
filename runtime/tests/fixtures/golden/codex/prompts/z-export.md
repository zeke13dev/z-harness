# /z-export

You are running **z-harness `/z-export`**.

This command invokes the runtime export CLI (or, for `pi` and the export-only drivers, the standalone runtime driver) to translate z-harness source files (`commands/`, `agents/`, `skills/`) into IDE-specific formats under `exports/`. Persona files from `personas/` are also exported in the same pass for all adapter hosts (cursor, codex, agy).

> **Export-only hosts:** `pi`, `windsurf`, `kiro`, `cline`, and `copilot` are **export-only** targets. They have runtime export drivers but no HostAdapter, no launch/inject capability, and no adapter-registry entry. They cannot be used with `/z-launch` or `/z-inject`. Only `/z-export` and the runtime CLI support them.

## Fragment includes

Command, agent, and skill bodies may reference shared markdown under `commands/_fragments/` with an HTML comment marker on its own line (whole line — references inside backticks or fenced code blocks are not expanded):

```markdown
<!-- include: commands/_fragments/run-brief-finalize.md -->
```

During export, the runtime renderers inline the fragment file at each marker (repo-relative path). Nested includes in fragment files are expanded too. Cursor/Codex/Agy copies therefore stay in sync without duplicating finalize prose.

## Phase 1 — Parse arguments

Read `$ARGUMENTS`. Look for `--target=<value>` and `--include=<value>`.

Valid `--target` values: `cursor`, `codex`, `agy`, `pi`, `windsurf`, `kiro`, `cline`, `copilot`, `all`.

Default (no `--target` flag): `all`.

Valid `--include` values: `personas`. May be specified multiple times or comma-separated.

Default (no `--include` flag): include personas automatically (personas are always exported in v1).

If an unrecognized `--target` value is given, immediately print:

```
[z-export] error: --target must be one of: cursor, codex, agy, pi, windsurf, kiro, cline, copilot, all
```

and exit nonzero. Do not proceed.

Build the target list:
- `cursor` → `["cursor"]`
- `codex` → `["codex"]`
- `agy` → `["agy"]`
- `pi` → `["pi"]`
- `windsurf` → `["windsurf"]`
- `kiro` → `["kiro"]`
- `cline` → `["cline"]`
- `copilot` → `["copilot"]`
- `all` → read the configured host list from `config.py` by running:
  ```bash
  python3 scripts/config.py get export.hosts
  ```
  This prints a JSON array string (e.g. `["cursor","codex","agy","pi"]`). JSON-parse the output to obtain the list of hosts. Use that list as the target set for `all`. New hosts appear automatically once their entry is registered in config and their driver exists — no hardcoded list is maintained here.

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->

> **Export-only target notes:**
> - `windsurf` → curated rule files under `.windsurf/rules/*.md` with `trigger` frontmatter.
> - `kiro` → curated steering files under `.kiro/steering/*.md` with `inclusion` frontmatter.
> - `cline` → single pointer file `.clinerules/z-harness.md` (plain markdown, no frontmatter).
> - `copilot` → single file `.github/copilot-instructions.md` (plain markdown, no frontmatter).
>
> All four are export-only: no persona export, no adapter, no launch support.

## Phase 2 — Run per-target export

For each target in the list, run the export in sequence (not in parallel). For **cursor**, **codex**, and **agy**, invoke the runtime CLI. For **pi** and the export-only drivers (**windsurf**, **kiro**, **cline**, **copilot**), inline-import the standalone driver.

### cursor / codex / agy targets

Run via the runtime CLI, writing to the committed `exports/<target>/` mirror with `--out`:

```bash
python3 -m z_harness_cli export --host <host> --out exports/<target> --force
```

Replace `<host>` with `cursor`, `codex`, or `antigravity`, and `<target>` with the matching `exports/` dir name: `cursor` → `exports/cursor`, `codex` → `exports/codex`, and **`agy` in the target list maps to `--host antigravity --out exports/agy`**.

Use `--out exports/<target>` (NOT `--in-place`): `--in-place` writes the host layout into the current project root (cwd) for live use in a workspace — it does **not** populate the committed `exports/` mirror. `--force` is required because `exports/<target>/` is a non-empty existing directory.

The CLI exports commands, agents, skills, **and personas** in a single pass — no separate persona step is needed or wanted for these three hosts. (Persona sources are read from `personas/builtin/`.)

**Important:** run targets sequentially, not in parallel. Capture stdout and stderr for each separately.

For each target:

1. Note the exit code.
2. On **exit 0**: parse stdout for a line matching the pattern `files=<N>` or similar output from the CLI. Extract the file count and output path. Then print:
   ```
   [<target>] OK — <count> files written to exports/<target>/
   ```
   If the CLI does not emit a parseable count/path line, print:
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

### pi target

Inline-import the standalone pi driver directly:

```bash
python3 - <<'EOF'
import sys, pathlib

repo_root = pathlib.Path("${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}").parent
export_root = repo_root / "exports" / "pi"

sys.path.insert(0, str(repo_root))
from runtime.drivers.pi import export as pi_export

result = pi_export.export(repo_root, export_root)

if result.warnings:
    for w in result.warnings:
        print(f"[pi] WARNING: {w}", file=sys.stderr)
    print(f"[pi] {len(result.warnings)} validation warning(s) — see stderr", file=sys.stderr)
    sys.exit(1)

print(f"[pi] files={len(result.files)}  dest={result.dest}")
EOF
```

Capture stdout and stderr. On exit 0, print:
```
[pi] OK — <count> files written to exports/pi/
```

On nonzero exit (including when `result.warnings` is non-empty), capture the last 20 lines of stderr. Mark `pi` as FAILED. Print:
```
[pi] FAILED (exit <code>)
--- stderr (last 20 lines) ---
<last 20 lines of stderr>
---
```
Then continue to the final summary.

### windsurf / kiro / cline / copilot targets (export-only)

These four targets use standalone runtime drivers with no adapter. Inline-import each driver directly:

```bash
python3 - <<'EOF'
import sys, pathlib, importlib

repo_root = pathlib.Path("${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}").parent
target = "<target>"  # windsurf | kiro | cline | copilot
export_root = repo_root / "exports" / target

sys.path.insert(0, str(repo_root))
driver = importlib.import_module(f"runtime.drivers.{target}.export")

result = driver.export(repo_root, export_root)

if result.warnings:
    for w in result.warnings:
        print(f"[{target}] WARNING: {w}", file=sys.stderr)
    print(f"[{target}] {len(result.warnings)} validation warning(s) — see stderr", file=sys.stderr)
    sys.exit(1)

print(f"[{target}] files={len(result.files)}  dest={result.dest}")
EOF
```

Replace `<target>` with the actual target name. Capture stdout and stderr. Apply the same OK / FAILED reporting rules as the `pi` target. On nonzero exit, continue to the next target — do not abort.

**Note:** these drivers are export-only. They do not support `--include=personas` and do not write to the adapter-host persona directories. No separate persona step is needed.

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
- **No LLM interpretation of export output.** Just capture the CLI's stdout/stderr verbatim; do not summarize or editorialize on what the export produced.
- **Relative paths in OK output.** Output paths should be relative to the repo root (strip the leading absolute path prefix).
- **No writes by this command.** All file I/O is delegated to the runtime CLI and pi driver.
- **No double persona export.** The runtime CLI (cursor/codex/agy) already writes personas in the same pass as commands/agents/skills. There is no separate persona step for these hosts.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | no | — |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
