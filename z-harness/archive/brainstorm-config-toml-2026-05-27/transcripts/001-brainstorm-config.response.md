## Framing

The core tension: z-harness has grown to 28 commands and 17 agents, but runtime behavior is split between hardcoded decision points, procedural environment variables (7 Z_HARNESS_* knobs), and documentation that lives in CLAUDE.md. Users cannot trade off doc-fetcher latency, consultation depth, or escalation without reading code or modifying their shell profile. When they do, they lose the original setting and have no way to ask "what is the current policy?" without grepping. The README conflates user quickstart with reference material, making it long and hard to navigate.

The fix is a first-class config surface: one file (or layered pair of files) that declares the full policy surface in a parseable format, is queryable at runtime, stays visible in git, and separates humans (README → docs/human/) from agents (resolved config → docs/llm/ + in-command uses).

**Why it matters:**

- Token efficiency: agents should not receive preambles that contradict config (if `consult.codex = "never"`, do not ask Codex what to do).
- Debuggability: users need to know what setting is actually in force without reading code.
- DRY: one canonical source of truth for "should we call doc-fetcher on a small task?" or "should we escalate from z-plan-light to z-plan?"
- Readability: README becomes orientation; reference docs move into discoverable human + LLM tiers.

## Core hypothesis

The first-class abstraction should be layered policy profiles, not one giant flat config.

I would bet on:

- `~/.config/z-harness/config.toml` for user defaults
- repo-local `.z-harness/config.toml` for project overrides
- optional plan/run-local generated defaults when missing
- deterministic per-key shadowing: repo overrides user, env overrides both only for legacy compatibility
- a tiny resolver script that emits focused JSON/TOML fragments for a specific consumer, not the whole config

The schema should be load-bearing around decision points:

```toml
[docs]
always_apply = false
depth = "standard"
staleness_threshold = 0.20

[escalation]
z_do = "auto"
z_plan_light = "auto"

[consult.codex]
mode = "phase"
cli_path = "codex"
phases = ["plan", "review"]

[consult.gemini]
mode = "never"

[agents.implementer]
model = "default"
docs_context = "compact"

[archive]
retention_days = 30

[notify]
level = "approval_only"
```

The key design move: commands and skills should ask for exactly the policy slice they need, for example:

```bash
scripts/config-resolve.py --for z-do --format prompt-fragment
scripts/config-resolve.py --for consult.codex --format json
scripts/config-resolve.py --for docs --task-size small --format prompt-fragment
```

That enables prompt injection-removal because disabled features simply produce empty fragments. If `consult.codex.mode = "never"`, the consult preamble is not shortened; it is absent.

## Risks

The biggest risk is creating a second programming language for z-harness behavior. If every command gains bespoke config interpretation, the repo gets more complex while appearing more configurable.

Silent behavior changes are another serious risk. Users may set `docs.always_apply = false` and later wonder why a plan missed repo context. Or `consult.gemini = "never"` may improve speed while reducing adversarial coverage. The config needs resolved-state visibility, probably a `z-config doctor` or `scripts/config-resolve.py --explain`.

Migration can also become messy. Existing env knobs cannot just disappear. For at least one release, env vars should map into config keys with warnings or clear precedence. Otherwise existing users with `Z_HARNESS_NOTIFY=off` or `Z_HARNESS_PLANS_DIR` get surprising behavior.

The auto-generation requirement is useful but dangerous. Writing a huge default file on first run creates noise and makes future defaults harder to evolve. Better: generate a minimal config with comments, while the resolver internally fills defaults for every missing key. "Missing keys never fail" should not mean "dump every possible knob into the user's repo."

The prompt-fragment mechanism can become brittle if fragments are hand-maintained in many places. It should live behind one resolver/template layer, with tests that assert disabled features produce empty or minimal output.

## Plan implications

The roadmap should shift toward a resolver-first implementation.

Smallest credible first slice:

1. Add a canonical schema and defaults in one machine-readable location, likely `config/defaults.toml` or `scripts/config_schema.py`.
2. Add `scripts/config-resolve.py` that loads global config, repo config, env compatibility, and emits scoped results.
3. Support only a few real knobs first: `docs.always_apply`, `notify.level`, `plans.dir`, and consultation mode for Codex/Gemini.
4. Wire those knobs into two or three high-value flows, not all 28 commands: likely `z-do`, `z-plan-light`, and `z-implement-next`.
5. Add first-run creation of `.z-harness/config.toml` only when a command needs it, with minimal comments and no failure on missing keys.
6. Slim README to quickstart and move reference material into `docs/human/config.md`.
7. Add `docs/llm/config-design.json` or similar, plus update `docs/llm/INDEX.json`.

This implies the implementation should not start by editing every command. It should create a stable config API, prove the prompt-fragment model in a narrow path, then expand command coverage mechanically.

## What would change my mind

I would back away from layered TOML if testing shows most commands only need one or two global switches and users do not actually need repo-specific overrides. In that case, a smaller `~/.config/z-harness/config.toml` plus env compatibility may be enough.

I would also change direction if prompt-fragment generation makes commands harder to audit. If reviewers cannot tell which instructions an agent receives without running several scripts, the token savings may not be worth the indirection.

Another disconfirming signal would be frequent conflicts between config and skill docs. If every behavior change requires updating schema, resolver code, human docs, LLM memory, command markdown, and tests, the maintenance cost is too high. The schema should reduce duplication, not multiply it.
