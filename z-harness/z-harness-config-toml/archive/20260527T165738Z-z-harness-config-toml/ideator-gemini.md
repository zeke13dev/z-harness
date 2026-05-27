Warning: 256-color support not detected. Using a terminal with at least 256-color support is recommended for a better visual experience.
Ripgrep is not available. Falling back to GrepTool.
### (1) Framing
This initiative transitions z-harness from a "bag of scripts" with hardcoded heuristics into a **Policy-Driven Execution Engine**. By decoupling the *capability* (the shell/python logic) from the *policy* (the TOML configuration), we move the "intent" out of the codebase and into a declarative layer. This treats the agents as a runtime that interprets user-defined constraints, allowing for a "Thin Wrapper" architecture where prompts are dynamically assembled based on the active config.

### (2) Core hypothesis
The most effective implementation is a **"Policy-Fragment Injection"** system: instead of SKILL.md and AGENT.md files containing static preamble rituals (like Codex-consulting logic), they should reference "Policy IDs." A centralized config-helper (likely `scripts/z-config.py`) will resolve the TOML knobs and inject the corresponding Markdown fragments into the prompt context at runtime. This "Prompt Templating" will reduce baseline token overhead by 20-40% and allow users to silence specific agent "behaviors" (e.g., the doc-fetcher preface) globally without modifying the core skill files.

### (3) Risks
The primary risk is **"Configuration Drift & Non-Deterministic Debugging."** Layered TOML shadowing (`~/.config/z-harness/` vs. `./z-harness.toml`) can lead to "ghost settings" where an agent's behavior is influenced by a local file that isn't committed to the repo, making bug reproduction difficult for collaborators. Additionally, "slimmed" READMEs risk breaking the entry-point heuristic for LLMs that rely on a single root-level file for system orientation; if the LLM doesn't follow the "Human Quickstart" links to `docs/llm/`, it may lose the map of the workspace entirely.

### (4) Plan implications
A new `scripts/z-config` utility must be the single source of truth, capable of emitting `eval`-friendly shell exports for commands and JSON-structured data for Python scripts. Every skill must be refactored to move its "preamble" text into a `fragments/` or `policies/` directory. The "First Slice" should migrate the `z-plan` skill—moving its auto-escalation logic and consultation preferences into TOML—to prove the token-savings and behavioral-toggling before scaling to all 21 skills and 17 agents.

### (5) What would change my mind
If the execution latency of the "config-check → fragment-resolution → prompt-assembly" loop offsets the speed gains of smaller prompts, the architecture is a net loss. Furthermore, if modern large-context models (like Gemini 1.5 Pro) demonstrate that 500-token "noise reduction" has zero statistical impact on reasoning performance, then the complexity of maintaining a fragmented prompt system would outweigh the benefits of a "Thin Wrapper."
