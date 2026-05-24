### D3 — Backwards compat for existing in-flight plans
1. **Why it's wrong:** A warning allows commands to proceed, creating a split-brain state. If `z-implement-next` warns but runs, it will likely write new output to `plans/<slug>/` while the old history remains in `z-harness/<slug>/`. 
2. **Better alternative:** Commands should **hard fail** with an actionable error if `z-harness/<slug>` exists, forcing the user to run the migration script before proceeding. 
3. **Failure mode:** Fractured run history. Commands lose context of previous phases because `events.jsonl` and `archive/` are split across two directories.

### D4 — Provider registry: location and schema
1. **Why it's wrong:** The schema mixes CLI commands (`"kind": "cli"`) with raw HTTP APIs (`"kind": "anthropic_api"`). Agents currently run within an IDE using shell commands. A bash/markdown agent cannot natively execute a raw Anthropic API call without an underlying CLI wrapper to handle HTTP requests, streaming, and authentication.
2. **Better alternative:** The registry must strictly map to executable CLI commands. If an API is required, bundle a thin Python/Bash adapter (e.g., `scripts/anthropic-adapter.py`) and register it as a CLI.
3. **Failure mode:** Execution failure when an agent tries to use the `anthropic_api` provider but lacks a tool to natively make HTTP requests.

### D5 — Consultant agent generalization
1. **Why it's wrong:** "Thin shims" that delegate to a generic `consultant.md` require an extra tool-call hop. Furthermore, relying on parameterized agent invocation (`role=...`) assumes all target IDEs support dynamic parameter passing to sub-agents.
2. **Better alternative:** Option (c) Generate per-provider files from a template, OR keep static files (`consultant_a.md`) that internally read the registry. Eliminate the generic middleman to reduce token overhead and latency.
3. **Failure mode:** IDE incompatibility. If exported to an IDE that doesn't support parameterized sub-agents, the routing fails entirely. In Claude Code, it wastes a turn/tokens routing through the shim.

### D7 — Haiku discovery of provider CLIs
1. **Why it's wrong:** Using an LLM to find binaries in `$PATH` is extreme over-engineering. It introduces latency, cost, and hallucination risks for a deterministic OS-level task.
2. **Better alternative:** Option (b/c hybrid) A simple local script (`scripts/discover-providers.sh`) that uses `command -v` to check a hardcoded list of common tools and writes the JSON.
3. **Failure mode:** The Haiku agent hallucinates paths, gets stuck trying to execute things, or writes malformed JSON, breaking the setup process.

### D8 — Multi-IDE export: pull vs push, source-of-truth
1. **Why it's wrong:** Claude Code's `.md` files are heavily coupled to its specific toolset (e.g., `run_shell_command`, `replace` with specific signatures). Attempting lossy regex exports to vastly different architectures (like Cursor Rules) will leak Claude-specific instructions into incompatible environments.
2. **Better alternative:** Option (b) Neutral schema. Keep the source of truth in a neutral `src/` directory (YAML/JSON + Markdown templates) and compile *all* targets (including Claude Code) from it.
3. **Failure mode:** Exported targets are fundamentally broken in other IDEs because they contain explicit instructions to use tools that don't exist in those environments.

### Cross-Decision Interactions
* **D8 vs D5:** Exporting a parameterized generic consultant (D5) will likely fail in D8 target IDEs (like Cursor) that don't support dynamic sub-agent parameter routing.
* **D8 vs D4:** The registry (D4) assumes sub-agents are executed via CLI commands. Other IDEs (like Cursor) use native model bindings rather than CLI tools. The export strategy (D8) must account for IDEs that completely ignore the CLI registry in favor of their native model dropdowns.
