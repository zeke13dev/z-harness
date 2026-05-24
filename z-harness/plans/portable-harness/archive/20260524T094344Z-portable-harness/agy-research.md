# Agy Plugin Format Research Note

**Date:** 2026-05-24  
**Author:** T004 implementer (z-harness)  
**Purpose:** Ground-truth for T012 (agy export adapter).

---

## 1. CLI Discovery

`agy` is on PATH at `/Users/zeke/.antigravity/antigravity/bin/agy`.

```
$ agy --version
1.107.0
62335c71d47037adf0a8de54e250bb8ea6016b15
arm64
```

`agy` is a shell wrapper that symlinks to:
```
/Applications/Antigravity.app/Contents/Resources/app/bin/antigravity
```

**Product identity (product.json):**

| Field | Value |
|-------|-------|
| nameShort | Antigravity |
| applicationName | antigravity |
| aliasName | agy |
| dataFolderName | .antigravity |
| darwinBundleIdentifier | com.google.antigravity |
| ideVersion | 1.22.2 (VS Code fork) |

Antigravity is **Google's VS Code fork** with built-in AI (Cascade agent). Documentation lives at `https://antigravity.google/docs`.

---

## 2. CLI Help Output (`agy --help` / `agy chat --help`)

`agy` exposes all standard VS Code CLI flags. AI-specific subcommand:

```
agy chat [options] [prompt]

Options:
  -m --mode <mode>        Mode: 'ask', 'edit', 'agent', or identifier of a custom mode.
                          Defaults to 'agent'.
  -a --add-file <path>    Add files as context.
  --maximize              Maximize chat view.
  -r --reuse-window
  -n --new-window
  --profile <profileName>
```

No `agy plugin`, `agy commands`, or `agy skill` subcommands exist. Plugin extension follows VS Code extension conventions (VSIX, OpenVSX gallery at `open-vsx.org`).

---

## 3. Native "Plugin" Concepts in Antigravity

Antigravity does not have a `agy-plugin.yaml` format natively. It instead uses **three filesystem-based primitives** that constitute the "plugin surface":

### 3.1 Workflows (custom chat modes)

**File pattern:** `.agent/workflows/**/*.md` (also `_agent/`, `.agents/`, `_agents/`)  
**Global scope:** `.gemini/antigravity*/global_workflows/*.md`

**Format** (YAML frontmatter + Markdown body):

```markdown
---
description: <one-line description shown in mode picker>
---

<Markdown body — the system prompt / instruction content for this mode>
```

- The **filename** (without `.md`) becomes the **mode identifier** used with `agy chat --mode <identifier>`.
- The `description` field is displayed in the Antigravity UI mode picker.
- Body supports full Markdown; interpreted as system-level instructions by the Cascade agent.
- Character limits enforced by the GUI editor: `description` ≤ 250 chars; `content` ≤ 12,000 chars.
- The string `---` is banned inside `description` (YAML delimiter conflict).

**Example:**

```markdown
---
description: Run the z-harness /z-plan command in this repo
---

You are acting as the z-harness planner. Follow instructions in commands/z-plan.md...
```

### 3.2 Rules (persistent context / always-on instructions)

**File pattern:** `.agent/rules/**/*.md` (also `_agent/`, `.agents/`, `_agents/`)

**Format:**

```markdown
---
trigger: always_on | model_decision | glob
description: <optional, shown when trigger=model_decision — the condition description>
globs: <optional glob pattern, used when trigger=glob>
---

<Markdown body — the rule content injected into every session or on trigger>
```

**Trigger values:**

| Value | Meaning |
|-------|---------|
| `always_on` | Injected into every agent session (equivalent to CLAUDE.md global rules) |
| `model_decision` | Model decides whether to apply based on the `description` hint |
| `glob` | Applied only when matching files are in context (`globs` field) |

**Character limits:** `description` / `globs` ≤ 250 chars each; `content` ≤ 12,000 chars.

### 3.3 MCP Servers (tool extension)

**Config file:** `mcp_config.json` at workspace root (JSON Schema at `schemas/mcp_config.schema.json`).

Antigravity follows the VS Code MCP server spec — same shape as `--add-mcp <json>` CLI flag:

```json
{
  "mcpServers": {
    "<name>": {
      "command": "<binary>",
      "args": ["..."],
      "env": {}
    }
  }
}
```

MCP servers add tools callable by the Cascade agent.

---

## 4. Native Subagent Dispatch Support

**Short answer: No.** Antigravity does not expose a first-class subagent dispatch API analogous to Claude Code's `Agent(subagent_type=...)`.

Evidence from binary analysis:
- `SkipBrowserSubagentResponseSchema` / `SkipBrowserSubagentRequestSchema` appear in the extension's protobuf schemas — these are **browser-automation subagents** used internally by Cascade when the agent browses the web, not general-purpose programmable agent dispatch.
- No `Agent()` builtin, no `.agent/subagents/` path, no YAML key for spawning child agents was found in `dist/extension.js`, the language server binary, or the package manifest.
- The Cascade agent can **use MCP tools**, which can themselves call external processes — this is the closest analog to subagent dispatch but requires authoring an MCP server.

**Implication for this repo:** Our `Agent(subagent_type="implementer", ...)` pattern has no direct mapping. It must be lowered to a shell-wrapper invocation (e.g., `claude --print < prompt.md`) documented in `CAPABILITIES.md`.

---

## 5. Install / Load Procedure

### Workflows and Rules
No install step needed. Antigravity auto-discovers `.agent/workflows/**/*.md` and `.agent/rules/**/*.md` by watching the workspace directory tree. Files placed there are immediately available in the IDE.

For global scope (available across all projects), place workflows at:
```
~/.antigravity/antigravity/data/User/globalStorage/antigravity.antigravity/global_workflows/<name>.md
```
or use the `.gemini/antigravity*/global_workflows/` path inside any workspace.

### VS Code Extensions (VSIX)
```bash
agy --install-extension <path>.vsix
# or from Open VSX:
agy --install-extension <publisher>.<extension-id>
```

### MCP Servers
```bash
agy --add-mcp '{"name":"my-server","command":"npx","args":["my-mcp-server"]}'
# or edit mcp_config.json at workspace root
```

---

## 6. Prompt-Format Expectations

Cascade ingests the workflow body as **system-level instructions** using Markdown. No special syntax required. Practical constraints:

- Markdown headings, lists, code blocks all work.
- No `<!-- comment -->` stripping confirmed (treat body as literal Markdown passed to model).
- `---` delimiters in the body are safe (only banned in the `description` frontmatter field).
- The Cascade agent is Gemini-based; prompt engineering conventions follow Gemini norms (clear imperatives, structured sections, no Anthropic-specific XML tags).
- Tool calls (`Bash`, `Read`, etc.) are Antigravity-native tool names — their exact API is not documented in the local binary. Assume standard coding-agent tool set (read file, write file, run command, search).

---

## 7. Summary: What Exists vs What We're Inventing

There is **no native `agy-plugin.yaml` format.** The SPEC and TASKS require us to design and generate one for the `exports/agy/` tree. This file is a **convention document** (not read by `agy` itself) that T012's export adapter will use as a manifest linking our commands → workflow files and our agents → rule files. The generated `.agent/workflows/*.md` and `.agent/rules/*.md` are what `agy` actually consumes.

---

## 8. Conclusion: Target `agy-plugin.yaml` Skeleton

This is the proposed schema for `exports/agy/agy-plugin.yaml`. It is **not** a native Antigravity schema; it is a z-harness export manifest consumed by `scripts/export-agy.py`.

```yaml
# agy-plugin.yaml
# z-harness agy export manifest — read by scripts/export-agy.py
# NOT a native Antigravity file format (agy does not read this)
schema_version: 1

metadata:
  name: z-harness
  description: z-harness planning and implementation workflow for Antigravity IDE
  source_repo: https://github.com/zeke-tools/z-harness

# Commands → .agent/workflows/*.md
# Each command becomes a custom chat mode (agy chat --mode <id>)
workflows:
  - id: z-plan
    source: commands/z-plan.md
    output: .agent/workflows/z-plan.md
    description: "Plan a new feature with z-harness spec/task decomposition"

  - id: z-implement-next
    source: commands/z-implement-next.md
    output: .agent/workflows/z-implement-next.md
    description: "Implement the next pending task in the current plan"

  - id: z-implement-all
    source: commands/z-implement-all.md
    output: .agent/workflows/z-implement-all.md
    description: "Implement all pending tasks in sequence"

  # ... one entry per commands/*.md file

# Agents → .agent/rules/*.md (always_on trigger — injected as standing context)
# No subagent dispatch in agy; agents become role-specific system-prompt rules
rules:
  - id: implementer-context
    source: agents/implementer.md
    output: .agent/rules/z-harness-implementer.md
    trigger: always_on
    description: "z-harness implementer conventions always loaded"

  - id: spec-precheck-context
    source: agents/spec-precheck.md
    output: .agent/rules/z-harness-spec-precheck.md
    trigger: model_decision
    description: "Activate when reviewing a spec for feasibility"

  # ... one entry per agents/*.md

# Skills → inlined into the workflow that references them
# No separate skill concept in agy; skills fold into their parent workflow body
skills: []  # not expressible natively; see CAPABILITIES.md

# MCP tools — optional; registered separately by user
# Listed here for documentation only; export-agy.py does not write mcp_config.json
mcp_hint:
  - tool: z-harness-log
    description: "Would be implemented as MCP server for metrics/event logging"
    status: not_implemented
```

---

## 9. Mapping Table: Our Concepts → Agy Concepts

| z-harness construct | Agy equivalent | Mapping strategy |
|---------------------|---------------|-----------------|
| `commands/*.md` (slash commands) | `.agent/workflows/<name>.md` | One workflow per command; frontmatter `description` = command's first paragraph |
| `agents/*.md` (subagents) | `.agent/rules/<name>.md` with `trigger: always_on` or `model_decision` | Context-injection only; no dispatch |
| `skills/*/SKILL.md` | No direct analog | Inline into parent workflow body; list in CAPABILITIES.md |
| `Agent(subagent_type=...)` dispatch | Not supported | Lower to `agy chat --mode <mode>` shell call; document in CAPABILITIES.md |
| `AskUserQuestion` tool | Built-in Cascade behavior | Native (Cascade always has a turn for questions) |
| `Bash`, `Read`, `Edit`, `Write` tools | Cascade native tools | Direct mapping; exact tool names may differ |
| `WebFetch`, `WebSearch` tools | Cascade native (if enabled) | Likely available; confirm via Antigravity docs |
| `metrics.jsonl` / `log-event.sh` | No native equivalent | Shell-wrapper in workflow body |
| `Z_HARNESS_PLANS_DIR` env | No native env injection | Must be hardcoded or set via shell wrapper |
| `providers.json` | Not applicable (Cascade uses Gemini) | Drop; document in CAPABILITIES.md |

---

## 10. Unsupported Constructs (CAPABILITIES.md Feeder)

The following z-harness features have no native agy equivalent and must be listed in `exports/agy/CAPABILITIES.md`:

1. **Subagent dispatch (`Agent(subagent_type=...)`)** — Cascade has no `Agent()` builtin. Workaround: `agy chat --mode <workflow-id>` via shell; not available within a running agent session.

2. **Skills / Skill inclusion** — No native skill-loading mechanism. Skills must be inlined into the invoking workflow's body (increasing per-file size toward the 12,000 char limit).

3. **Provider registry (`providers.json`, `resolve-provider.sh`)** — Cascade is bound to Gemini; no multi-provider routing. All provider-routing logic is inapplicable.

4. **Multi-model review loop** — `/z-review-all` dispatches Codex + Gemini reviewers in parallel. Single-provider Cascade cannot replicate this.

5. **`Z_HARNESS_PLANS_DIR` + `plan-path.sh`** — No mechanism to inject env vars into a workflow's execution context. Path must be hardcoded or assumed to be the workspace root.

6. **`metrics.jsonl` event stream** — `log-event.sh` and `log-phase.sh` write JSONL files. This works inside workflow bodies (shell commands are available) but requires the workspace to be writable at the expected path.

7. **`AskUserQuestion` vs turn-based clarification** — Claude Code's `AskUserQuestion` tool pauses execution and returns a typed answer. Cascade's equivalent is a conversational turn (no structured return value), which may break agent logic that branches on the answer.

8. **Workflow body > 12,000 chars** — Several z-harness commands (e.g., `z-plan`) exceed this limit. Mitigation: split into sub-workflows or link to an external file via `@file` syntax (if supported — unconfirmed).

---

## Appendix: File Locations Inspected

| Path | Notes |
|------|-------|
| `/Users/zeke/.antigravity/antigravity/bin/agy` | Shell wrapper → Antigravity.app |
| `/Applications/Antigravity.app/Contents/Resources/app/extensions/antigravity/package.json` | Extension manifest; reveals customEditors, configuration |
| `/Applications/Antigravity.app/Contents/Resources/app/extensions/antigravity/dist/extension.js` | Minified extension; source of workflow/rule schema |
| `/Applications/Antigravity.app/Contents/Resources/app/extensions/antigravity/customEditor/media/workflowEditor/workflowEditor.js` | Webview script; confirms workflow document state shape |
| `/Applications/Antigravity.app/Contents/Resources/app/extensions/antigravity/customEditor/media/ruleEditor/ruleEditor.js` | Webview script; confirms rule document state shape with trigger types |
| `/Applications/Antigravity.app/Contents/Resources/app/product.json` | Product metadata; confirms Google Antigravity identity + docs URLs |
| `https://antigravity.google/docs` | Official docs URL (not fetched — offline research only) |
