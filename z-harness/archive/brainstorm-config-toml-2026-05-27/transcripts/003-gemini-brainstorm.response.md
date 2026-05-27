### 1. Framing
The goal is to transition `z-harness` from a hardcoded, environment-variable-heavy system to a flexible, configuration-driven tool using TOML. Concurrently, the `README.md` will be aggressively slimmed down into a pure quick-start guide, delegating all comprehensive reference material to `docs/human/` and token-optimized `docs/llm/`. The configuration architecture must support layered loading (global vs. repository-scoped), facilitate dynamic prompt fragment injection to minimize token overhead, and silently auto-generate missing keys to guarantee zero-friction onboarding and execution.

### 2. Core hypothesis
By centralizing runtime behavior (escalation ladders, doc-fetcher toggles, notification preferences, consultation rules) into a structured `config.toml`, we can drastically reduce the static token footprint of individual skill prompts. Instead of skills carrying exhaustive conditional logic ("If you are in a small flow, do this, unless Z_HARNESS..."), a thin wrapper script will parse the TOML and inject only the active, relevant directives into the prompt payload at execution time. A layered fallback approach (`~/.config/z-harness/config.toml` acting as base, overridden by `./.z-harness/config.toml`) paired with silent auto-generation of defaults guarantees a consistently valid state without requiring manual user setup.

### 3. Risks
- **Parsing Complexity in Shell:** Extracting, merging, and mutating TOML files natively in shell scripts is notoriously brittle. Relying on an external dependency (like Python `tomllib` or `yq`) introduces an execution requirement that might break in minimal environments.
- **Opaque Prompt Injection:** Dynamically assembling prompt wrappers can complicate debugging. If an agent misbehaves, it becomes harder to trace whether the issue lies in the base skill `.md`, the TOML config, or the injection logic.
- **Config vs. Schema Drift:** As new features are added, the TOML schema might evolve faster than the fallback auto-generation logic or the LLM's understanding of the config layout, leading to ignored settings or corrupted config files.
- **Loss of Context:** Removing hardcoded procedural rules from the raw skill prompts and replacing them with dynamic fragments might cause the LLM to lose the deeper context or "why" behind the rules, potentially degrading its adherence to complex escalation paths.

### 4. Plan implications
- **README Refactoring:** Gut the existing `README.md`. Retain only the pitch ("What is z-harness?"), installation instructions, and pointers to the documentation directories. Migrate all command, agent, and architectural specifics to `docs/human/`.
- **TOML Manager Implementation:** Develop a dedicated script (e.g., `scripts/manage-config.py`) responsible for reading, merging global/local configurations, and safely auto-appending missing default keys to the user's `config.toml` without overwriting custom values or crashing.
- **Thin Wrapper Architecture:** Introduce an interception layer (e.g., `scripts/inject-context.sh`) that reads the resolved configuration and prepends a clean, token-efficient `<runtime_config>` XML block to the skill's `.md` prompt prior to execution.
- **Skill Simplification:** Systematically strip existing environment variable checks and static conditional escalation logic from the 21 skill `.md` files. Refactor them to expect and obey the injected `<runtime_config>` block.
- **Documentation Overhaul:** Document the new TOML schema, fallback hierarchy, and available keys (e.g., `escalation.auto_escalate`, `docs.always_apply`, `consultation.mode`) in both `docs/human/` and the token-compacted `docs/llm/INDEX.json`.

### 5. What would change my mind
- If token profiling reveals that the savings achieved by dynamic prompt injection are negligible compared to the maintenance burden of the TOML parsing infrastructure.
- If feedback indicates users strongly prefer a zero-configuration "magic" approach and view auto-generated TOML files in their local `.z-harness/` directory as repository pollution, suggesting we should stick to environment variables for core knobs.
- If the underlying IDE/plugin host (e.g., Claude Code) introduces native, built-in configuration management that renders a custom TOML implementation redundant.
