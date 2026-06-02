# PERSONAS — Persona System Guide

> Last updated: 2026-06-01
> Covers source: scripts/resolve-persona.py, scripts/resolve-persona.sh, runtime/contract/persona.schema.json, personas/README.md, personas/builtin/codex-default-consultant.md, personas/builtin/gemini-default-consultant.md, personas/builtin/codex-default-reviewer.md, commands/z-personas.md, skills/z-personas/SKILL.md, runtime/drivers/_persona_utils.py, runtime/drivers/antigravity/persona_export.py, runtime/drivers/cursor/persona_export.py, runtime/drivers/codex/persona_export.py, runtime/drivers/claude/persona_export.py, runtime/dispatch/persona_prompt.py, runtime/dispatch/dispatcher.py

## Overview

A **persona** is a saved prompt-prefix preset that gets prepended to a role's
task prompt at dispatch time.  Persona, model, and runtime are **orthogonal
axes** — each is configured independently, not bundled together.

- **Persona** — what behavioral tone and context the agent has (prompt prefix).
- **Model** — which model to use (e.g. `gpt-5-codex`, `gemini-2.5-pro`).
- **Runtime** — which CLI provider executes the call (e.g. `codex-cli`, `gemini-cli`).

You can mix any combination: a Gemini-tuned persona body with the `codex-cli`
runtime and any model string your CLI accepts.

See [PROVIDERS.md](PROVIDERS.md) for the runtime registry that describes how
each CLI is invoked.

---

## Persona file format

Persona files are plain Markdown with an optional YAML frontmatter block.

```markdown
---
name: codex-default-reviewer
description: Default Codex reviewer persona — adversarial, blockers/majors only.
compatible_roles: [reviewer]
contract: review-verdict
---

You are an adversarial code reviewer.  Your job is to find blockers and major
issues only — do not report style nits or minor suggestions.

Return your verdict in this exact structure:
VERDICT: PASS | FAIL | BLOCKED
...
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique identifier.  Must match `^[a-z0-9-]+$` (kebab-case; no dots or slashes). |
| `description` | no | Human-readable summary shown by `/z-personas list`. |
| `compatible_roles` | no | Soft hint: list of roles this persona is designed for.  A mismatch emits a `persona_compat_warning` event but does not block. |
| `contract` | no | Expected output structure: `freeform`, `review-verdict`, or `strict-json`.  When the bound role declares an `expected_contract`, a mismatch here is a hard failure at startup. |

### Body

Everything below the closing `---` is the prompt prefix.  It is prepended
verbatim before the role's task prompt at dispatch time.  No interpolation in
v1 — the body is treated as a static string.

---

## Layered storage and precedence

Personas are discovered from three layers in ascending priority (last wins per
name):

| Layer | Path | Priority |
|-------|------|----------|
| Builtin (shipped with harness) | `personas/builtin/` | Lowest |
| User-global | `~/.config/z-harness/personas/` | Middle |
| Repo-local | `<repo>/.z-harness/personas/` | Highest |

When the same `name` appears in more than one layer, the highest-priority layer
wins and z-harness emits a `persona_shadowed` event (once per process per
name):

```
[personas] persona_shadowed: codex-default-reviewer — repo overrides user-global
```

Run `/z-personas where <name>` to see all layers that define a persona and
which one won.

---

## TOML binding

Bind a persona (plus model and runtime) to a specific (command, role) pair in
your `config.toml`:

```toml
# Per-command binding — takes effect only for /z-plan
[roles.z_plan.consultant_primary]
persona  = "my-custom-consultant"
model    = "gpt-5-codex"
runtime  = "codex-cli"

# Default binding — applies to any command not listed above
[roles.default.consultant_primary]
persona  = "codex-default-consultant"
model    = ""              # empty string = use provider's default_model
runtime  = "codex-cli"

[roles.default.consultant_secondary]
persona  = "gemini-default-consultant"
runtime  = "gemini-cli"

[roles.default.reviewer]
persona  = "codex-default-reviewer"
runtime  = "codex-cli"
```

### Key rules

- Command names use underscores in TOML (`z_plan` not `/z-plan`).  `/z-personas`
  translates back to slash-form on output.
- All three fields (`persona`, `model`, `runtime`) are optional within a
  `[roles.*.*]` table — set only what you want to override.
- Per-field merge: when a repo TOML sets `model` and a global TOML sets
  `persona`, the merged binding has both.

### Resolution order

At dispatch time, each axis (persona, model, runtime) is resolved independently
in this priority:

1. **Per-Agent() / Dispatcher.run() kwargs** — explicit call-site override.
2. **`[roles.<command>.<role>]` in config.toml** — command-scoped binding.
3. **`[roles.default.<role>]` in config.toml** — cross-command default.
4. **Legacy `providers.json` `roles` mapping** — backward-compat fallback (emits `legacy_provider_roles_used`).
5. **Error** — halt with actionable message.

---

## The `ideator` role (brainstorm persona diversity)

`ideator` is a role used by `/z-brainstorm` to give its three parallel ideators
(Claude, Codex, Gemini) **distinct** personas — persona diversity layered on top
of vendor diversity. Unlike the `implementer` rotation, this is **not** an
experiment: there are no control / no-persona baseline arms and no per-ideator
outcome tracking (an ideator has no measurable terminal). It is gated on the
`brainstorm.personas` config knob (default ON); when OFF the brainstorm dispatch
is byte-identical to the vendor-only behaviour.

A persona joins the ideator pool by listing `ideator` in its `compatible_roles`.
The shipped pool is the set of bold, perspective-driven builtins (e.g.
`pattern-oracle`, `anti-consensus-surgeon`, `cut-it-half`, `brutalist-architect`,
`biomimetic-architect`, `physics-reductionist`, `fossil-whisperer`,
`cobol-greybeard`). Review-shaped personas (e.g. those with `contract:
review-verdict`) are intentionally excluded — they produce findings, not framings.

Drawing is done by a dedicated subcommand that omits the control arms and draws
without replacement:

```bash
# Draw up to 3 distinct ideator personas (never boring-anchor / no-persona):
python scripts/resolve-persona.py random-distinct-for-role ideator --count=3
# → JSON array of resolve-shaped objects (one per ideator slot)
```

**Graceful degradation:** if the ideator pool holds fewer than the requested
count, the subcommand returns a shorter array (or `[]` when empty), notes the
underflow on stderr, and exits 0. `/z-brainstorm` binds the returned personas
positionally (claude → codex → gemini) and runs any unfilled slot vanilla,
recording the binding (or `<none>`) in the BRAINSTORM.md `ideator_personas`
frontmatter map. Each bound ideator emits a `persona_bound` event for attribution.

---

## Orchestrator usage pattern

The **orchestrator** (slash command, skill, or Agent() call site) is responsible
for persona resolution and prompt composition.  The dispatcher stays thin —
it accepts an already-composed prompt and never calls `resolve-persona.py`
internally.

### Step 1 — resolve persona + model + runtime

Call `resolve-persona.py resolve` for the (command, role) pair:

```bash
python scripts/resolve-persona.py resolve z_plan consultant_primary
# → {"persona": "codex-default-consultant", "model": "", "runtime": "codex-cli",
#    "source": "roles_default", "persona_body_path": "/abs/path/personas/builtin/codex-default-consultant.md"}
```

### Step 2 — read the `persona_body_path`

```python
import json, subprocess

result = subprocess.run(
    ["python", "scripts/resolve-persona.py", "resolve", "z_plan", "consultant_primary"],
    capture_output=True, text=True, check=True,
)
envelope = json.loads(result.stdout)
body_path = envelope["persona_body_path"]  # str | None
```

### Step 3 — call `prepend_persona` to compose the final prompt

```python
from runtime.dispatch.persona_prompt import prepend_persona

final_prompt = prepend_persona(body_path, task_prompt)
# If body_path is None/empty, task_prompt is returned unchanged.
# If body_path points to a missing file, FileNotFoundError is raised.
# YAML frontmatter (--- blocks) is stripped automatically.
```

### Step 4 — pass `final_prompt` to `Dispatcher.run`

```python
from runtime.dispatch.dispatcher import Dispatcher

dispatcher = Dispatcher(repo_root=repo_root, run_id=run_id)
result = dispatcher.run(
    driver,
    command_id="z-plan",
    caller_args=[final_prompt],
    provider_config=provider_config,
    role="consultant_primary",
    # Optionally pass resolved fields as override kwargs:
    model=envelope.get("model") or None,
    runtime=envelope.get("runtime") or None,
)
```

The `role` kwarg is informational — it is included in the `persona_bound`
event payload but not used for resolution.  The dispatcher itself does **not**
call `resolve-persona.py` or read persona files.

---

## Per-Agent() override kwargs

Command authors can override any axis dynamically at the call site without
touching config files.  Pass keyword arguments to `Agent()` or
`Dispatcher.run()`:

```python
# Override persona and model for a single dispatch
agent = Agent(
    subagent_type="consultant",
    description="Deep-dive review of auth module",
    prompt=task_prompt,
    # Persona / model / runtime overrides:
    persona="my-security-consultant",
    model="o3",
    runtime="codex-cli",
)
```

The three optional kwargs are:

| Kwarg | Description |
|-------|-------------|
| `persona` | Name of a persona from any layer (builtin, user-global, or repo). |
| `model` | Model string passed to the CLI.  Overrides config and provider defaults. |
| `runtime` | Provider name from the registry (e.g. `codex-cli`, `gemini-cli`). |

When any override is active, z-harness emits a `persona_override_used` event
recording both the override value and what the config default would have been.

---

## `/z-personas` discovery command

`/z-personas` is the interactive tool for exploring the persona system.

| Invocation | What it does |
|------------|-------------|
| `/z-personas` | Equivalent to `/z-personas roles` (default). |
| `/z-personas list` | All personas across all layers with their source. |
| `/z-personas roles` | All roles with bound persona/model/runtime per command. |
| `/z-personas validate` | Run schema checks; verify contract compatibility for all default bindings. |
| `/z-personas where <name>` | Show the load-order chain for a persona name (all layers, winner marked). |

Example output of `/z-personas roles`:

```
/z-plan
  consultant_primary  → persona: codex-default-consultant  model: gpt-5-codex  runtime: codex-cli  (source: roles.default)
  consultant_secondary→ persona: gemini-default-consultant  model: gemini-2.5-pro  runtime: gemini-cli  (source: roles.default)
  reviewer            → persona: codex-default-reviewer    model: gpt-5-codex  runtime: codex-cli  (source: roles.default)
```

---

## Builtin personas

Three personas ship with the harness under `personas/builtin/`:

| Name | Compatible roles | Contract |
|------|-----------------|----------|
| `codex-default-consultant` | `consultant_primary`, `consultant_secondary` | `freeform` |
| `gemini-default-consultant` | `consultant_primary`, `consultant_secondary` | `freeform` |
| `codex-default-reviewer` | `reviewer` | `review-verdict` |

These form the default bindings used when no TOML overrides are present.

---

## Troubleshooting

### `persona_binding_chimera` event

This event fires when a single binding's three axes (persona, model, runtime)
resolve from two or more different layers:

```
[personas] persona_binding_chimera: command=z_plan role=consultant_primary
  persona → roles.z_plan (repo TOML)
  model   → roles.default (global TOML)
  runtime → roles.default (global TOML)
```

A chimera is **not an error** — resolution still proceeds.  It is a soft
observability signal so you can spot unintended pairings (e.g. a
Gemini-tuned persona body paired with the `codex-cli` runtime).

**To resolve:** either consolidate all three axes into the same
`[roles.<command>.<role>]` table, or verify the pairing is intentional.

### `persona_shadowed` debug

When a persona name exists in more than one layer, only the highest-priority
layer is used.  To see all layers:

```
/z-personas where my-custom-consultant
```

Output:

```
my-custom-consultant
  [1] personas/builtin/my-custom-consultant.md      (builtin)
  [2] ~/.config/z-harness/personas/my-custom-consultant.md  (user-global) ← winner
```

If your edits to a repo-local persona seem to have no effect, check whether
a user-global or builtin definition is shadowing it.

### Persona not found

If dispatch halts with:

```
[personas] persona X not found in any layer; check /z-personas list
```

The persona name in your TOML binding does not match any `.md` file across all
three layers.  Run `/z-personas list` to see what is available and check for
typos in `name` frontmatter vs. the binding string.

### Contract mismatch at startup

```
[personas] contract mismatch: role=reviewer expects contract=review-verdict but persona=my-persona declares contract=freeform
```

The `reviewer` role requires a structured `PASS/FAIL/BLOCKED` output format.
Either switch to a persona with `contract: review-verdict`, or author a new
persona with the correct contract declaration.

---

## Authoring a custom persona

1. Create `<repo>/.z-harness/personas/<your-name>.md`.
2. Add frontmatter with at least `name: <your-name>`.
3. Write the prompt prefix in the body.
4. Bind it in `config.toml`:
   ```toml
   [roles.default.consultant_primary]
   persona = "<your-name>"
   ```
5. Run `/z-personas validate` to check for contract/compat issues.

---

## Telemetry events

| Event | Fired when |
|-------|-----------|
| `persona_bound` | Each dispatch: records `{command, role, persona, model, runtime, source}`.  `source` is a per-axis nested dict `{persona: <layer>, model: <layer>, runtime: <layer>}` where each layer is one of `override`, `provider_config`, or `none`. |
| `persona_override_used` | A per-Agent() / Dispatcher.run() kwarg overrides a config default.  Payload includes `command`, `override_field`, `value`, `original`. |
| `model_resolved` | Records `{command, model, runtime, source}` at dispatch. |
| `persona_compat_warning` | A persona is bound to a role not in its `compatible_roles`. |
| `persona_shadowed` | A persona name is defined in more than one layer (once per process per name). |
| `persona_binding_chimera` | A binding's three axes resolve from ≥2 different config layers. |
| `legacy_provider_roles_used` | Resolution falls back to `providers.json` `roles` map. |
| `persona_random_selected` | A random draw was made via `random-for-role` or `forced-control`. Payload: `{role, selected, candidates, draw_id, selection_source}`. Optional join fields (stamped when env vars are exported): `task_id`, `attempt_id`, `persona_id`. Emitted BEFORE the agent runs. |
| `persona_attempt_outcome` | Per-attempt terminal outcome (only when `experiment.persona_rotation=true`). Payload: `{run_id, command, role, task_id, attempt_id, persona_id, draw_id, complexity_tier, diff_size, review_cycles, retries, blocker_count, wall_ms, status}`. Join key: `attempt_id` + `draw_id`. |

> Note: as of T103, `persona_bound`, `persona_override_used`, and
> `model_resolved` payloads use `command` (not `command_id`) as the field name.

---

## Persona rotation (experimental)

The persona-rotation experiment rotates which persona is used for the `implementer` and `reviewer` roles across z-harness runs, collecting passive outcome data to compare persona effectiveness. It is **on by default** and gated by `experiment.persona_rotation` in config (see `docs/human/config.md`).

### How it works

**Implementer rotation (`/z-implement-all` and `/z-implement-next`):**

Every task attempt gets a persona drawn by `resolve-persona.py random-for-role implementer`. The draw:
1. Enumerates all personas across all layers whose `compatible_roles` includes `implementer` (including `boring-anchor` — amended as of T102).
2. Prepends the `no-persona` sentinel (null/vanilla baseline arm) to the candidate pool.
3. Excludes only explicitly listed IDs (`--exclude`).
4. Draws uniformly at random using `secrets`/`random` (seeded for reproducibility if `--seed` given).
5. Emits `persona_random_selected` before the agent runs.

Every `experiment.control_every_n`-th attempt (default every 5th, counted repo-wide via `.z-harness/.persona-control-counter`) calls `forced-control implementer` instead, which returns `boring-anchor` tagged `selection_source: forced_control`. This ensures a baseline sample accrues automatically.

The draw result is persisted to `$BASE/archive/tasks/<task-id>/persona-draw.json`. On **resume** (same attempt_id), the draw is reused verbatim. On **retry** (new attempt_id = new cycle), a fresh draw is made, optionally excluding the prior attempt's persona via `--exclude`.

**Reviewer dispatch:** both a base codex reviewer (`reviewer_participant: base_codex`) and one advisory random-arm reviewer (`reviewer_participant: random_arm`) are dispatched as separate `Agent()` calls. The random-arm verdict is advisory only — it never changes halt/retry behavior. Both reviewers share `attempt_id`; each has its own `draw_id`.

**Fixed 5-panel consult (`/z-plan` and `/z-debug`):**
When `experiment.persona_rotation=true`, the Phase 3 / Phase 7 consultant dispatch uses a fixed 5-panel instead of the standard 2-consultant path. Panel members: agy (gemini), cursor@claude-4.6-sonnet, cursor@grok-4.3, cursor@composer-2.5, codex-cli. Each arm logs `persona_bound` with `selection_source: fixed_panel`. No random draw — the panel composition is deterministic.

### Selection sources

| `selection_source` | Meaning |
|-------------------|---------|
| `random_role_pool` | Normal random draw from eligible personas. |
| `forced_control` | Forced `boring-anchor` draw on the Nth-attempt cadence. |
| `fallback_empty_pool` | No eligible personas found; fell back to `boring-anchor`. **Quarantined in analysis** — never counted as a persona sample. |
| `fixed_panel` | Panel member in a fixed 5-panel consult (plan/debug phases). |

### `boring-anchor` — the control persona

`boring-anchor` is the baseline persona that ships with the harness. As of T102 (amended):
- **Eligible for random draws.** `boring-anchor` is now a normal member of the `random_role_pool` and may be drawn stochastically alongside other personas.
- **Also drawn via `forced-control`** (cadence — every `experiment.control_every_n`-th attempt). The cadence is a **floor** that guarantees a minimum `boring-anchor` sample rate regardless of random-pool outcomes.
- **Secondary delta baseline** in `persona-stats.py` analysis. Within each `(role, complexity_tier)` stratum, `boring-anchor` is used as the baseline only when the stratum has zero `no-persona` samples.

> Note: the prior invariant "boring-anchor is NEVER in the random pool" is REVERSED by T102. `selection_source` distinguishes a `random_role_pool` draw from a `forced_control` cadence draw.

### `no-persona` — the null baseline arm

`no-persona` is a reserved sentinel that represents the vanilla implementer: no persona prefix at all.
- **No file on disk.** `persona_body_path=null`; the implementer runs with zero prompt prefix.
- **Always in the random pool** (prepended to the candidate list by `random-for-role` before any disk enumeration, unless explicitly `--exclude`d).
- **Fully tracked.** A `no-persona` draw emits `persona_random_selected` and `persona_attempt_outcome` with `persona_id="no-persona"` — it is a **tracked baseline arm**, not the same as knob-off (which emits no events at all).
- **Primary delta baseline** in `persona-stats.py`. All per-stratum `delta_vs_baseline` values are computed against `no-persona` when the stratum has at least one no-persona sample.
- **Disk filtering.** `_enumerate_role_compatible_personas` filters out any `no-persona.md` found on disk so the hardcoded sentinel is the only source of `no-persona` draws.

### Analysis baseline resolution

`persona-stats.py` resolves the delta baseline per `(role, complexity_tier)` stratum in this order:
1. `no-persona` — primary null baseline (true vanilla, zero prefix). Used when the stratum has at least one `no-persona` sample.
2. `boring-anchor` — secondary bland-control fallback. Used only when the stratum has no `no-persona` samples.
3. `None` — raw metrics reported without a delta if neither baseline exists in the stratum.

Both `no-persona` and `boring-anchor` appear as normal tracked arms in every report section. `fallback_empty_pool` draws are quarantined and never enter any baseline.

### New subcommands in `resolve-persona.py`

| Subcommand | Purpose |
|-----------|---------|
| `random-for-role <role> [--exclude=<ids>] [--seed=<s>]` | Draw a random persona for the role; returns resolve-shaped JSON + `{selection_source, draw_id, candidates}`. |
| `forced-control <role>` | Return `boring-anchor` tagged `selection_source: forced_control`. |
| `control-counter --increment` | Atomically read + increment + persist the repo-level forced-control cadence counter in `.z-harness/.persona-control-counter`. Returns the new counter value. |

### Join keys for analysis

| Field | Present on | Purpose |
|-------|-----------|---------|
| `attempt_id` | `persona_bound`, `persona_attempt_outcome` | Links all events for one task attempt |
| `draw_id` | `persona_random_selected`, `persona_bound`, `persona_attempt_outcome` | Links draw event to outcome |
| `reviewer_participant` | `persona_bound` (reviewer) | `base_codex` or `random_arm` — disambiguates the two reviewer arms |

> Use `scripts/persona-stats.py` to join these events and compute per-persona outcome deltas. See `docs/human/scripts.md` for usage.

### Turning off

```toml
# .z-harness/config.toml
[experiment]
persona_rotation = false
```

Or temporarily via env:

```bash
export Z_HARNESS_EXPERIMENT_PERSONA_ROTATION=false
```

When `false`, the entire rotation block is a no-op: no draw events, no state files, no persona prefix, no outcome events, no dual reviewer. Behavior is identical to before the experiment was added.
