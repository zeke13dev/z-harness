Warning: Basic terminal detected (TERM=dumb). Visual rendering will be limited. For the best experience, use a terminal emulator with truecolor support.
Ripgrep is not available. Falling back to GrepTool.
Here is the final two-pronged review of the `plan-bail-router` implementation and spec correctness.

### Prong A - Implementation Faithfulness

**1. Omission of Stable Reason Codes Enums in Command Blocks**
- **severity:** major
- **prong:** A
- **file/path:** `commands/*.md` (e.g., `commands/z-do.md`)
- **evidence:** The spec defines a strict enum of `reason_codes` (e.g., `tiny_task`, `route_loop_risk`). The implemented `Plan Route Check` blocks instruct the orchestrator to emit `reason_codes` in the telemetry event, but they fail to provide the actual list of valid codes. When an orchestrator routes deterministically without the classifier, it has no reference for which codes are valid and will invent strings.
- **recommendation:** Embed the list of stable `reason_codes` directly into the `Plan Route Check` block so the orchestrator can select the correct string.
- **one reason the finding might be wrong:** The LLM might be able to infer a reasonable string that, while not strictly in the enum, is acceptable for logging, or the downstream metrics system is tolerant of arbitrary strings.

**2. Inconsistent Sentinel Tag Placement**
- **severity:** minor
- **prong:** A
- **file/path:** `commands/z-do.md`, `commands/z-plan-light.md`, `commands/z-brainstorm.md`
- **evidence:** In `z-do.md` and `z-plan-light.md`, the `## Plan Route Check` heading is placed *outside* the `<!-- PLAN_ROUTE_CHECK_START -->` sentinel. In `commands/z-brainstorm.md` and `commands/z-plan-split.md`, the heading is placed *inside* the sentinel block. 
- **recommendation:** Standardize the placement of the heading to be inside the HTML sentinel comments across all files to ensure reliable programmatic extraction.
- **one reason the finding might be wrong:** Future automated extraction scripts might only search for the sentinels and not care if the markdown heading is included in the extracted payload.

---

### Prong B - Spec Correctness & Sufficiency

**1. `planning-router` Tool Contradiction**
- **severity:** major
- **prong:** B
- **file/path:** `agents/planning-router.md`
- **evidence:** The spec mandates that `planning-router` is a "Cheap Haiku ambiguity resolver" and explicitly states "Do not run expensive repo sweeps." However, its frontmatter gives it `tools: Read, Grep, Glob`. If granted these tools, an LLM will naturally use them to investigate uncertain terrain, burning tokens/time and violating the "advisory only / no expensive exploration" constraint.
- **recommendation:** Remove `Read, Grep, Glob` from the `planning-router` tools list. It should rely exclusively on the `signals_json` payload.
- **one reason the finding might be wrong:** Haiku is cheap enough that a single targeted `Read` or `Grep` might be considered an acceptable cost if the signals payload is missing a critical piece of context.

**2. Missing `Agent()` Dispatch Template for Router**
- **severity:** major
- **prong:** B
- **file/path:** `SPEC.md` / `commands/*.md`
- **evidence:** The spec defines strict inputs for `planning-router` (`current_command`, `task_or_topic`, `signals_json`, `route_chain_json`, `repo_root`) but did not mandate an exact `Agent(...)` block in the Source Changes section. Consequently, the implementation just says "Call `planning-router`". Without the `Agent()` syntax block, the orchestrator will likely hallucinate the dispatch format or omit required JSON payload fields.
- **recommendation:** Update the spec to require the exact `Agent(subagent_type="planning-router", prompt="...")` code block in the `Plan Route Check` section.
- **one reason the finding might be wrong:** Claude 3.5 Sonnet might successfully infer the `Agent()` dispatch syntax from adjacent phases in the command file.

**3. Telemetry Payload JSON Construction Risk**
- **severity:** major
- **prong:** B
- **file/path:** `SPEC.md`
- **evidence:** The spec requires the `plan_route_decision` event to carry a highly structured, nested JSON payload (including arrays and objects like `signals` and `route_chain`). It directs the LLM to emit this via a bash script but provides no `jq` or `printf` template. Expecting an LLM to dynamically generate flawless bash to serialize complex nested JSON without a template is highly prone to syntax errors.
- **recommendation:** Provide a concrete `jq -n` template snippet in the `Plan Route Check` block so orchestrators can safely construct the JSON payload.
- **one reason the finding might be wrong:** Modern LLMs are very strong at generating basic JSON serialization scripts, so the risk of syntax errors might be low in practice.

**4. `REASON_CODES` Format Mismatch**
- **severity:** minor
- **prong:** B
- **file/path:** `SPEC.md`
- **evidence:** The spec states the `planning-router` agent returns `REASON_CODES: <comma-separated stable reason codes>`. However, the telemetry contract requires `reason_codes` to be a `JSON array of stable strings`. This forces the orchestrator to perform an unspecified string-splitting operation to construct the JSON array, which will likely result in malformed JSON.
- **recommendation:** Modify the `planning-router` return contract to output a valid JSON array directly (e.g., `REASON_CODES: ["small_fix", "needs_research"]`).
- **one reason the finding might be wrong:** Passing the comma-separated string as a single array element (e.g., `["small_fix, needs_research"]`) might be perfectly acceptable for the downstream telemetry consumer.
