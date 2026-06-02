# PERSONAS — Persona System Guide

> Last updated: 2026-06-02
> Covers source: scripts/resolve-persona.py, scripts/resolve-persona.sh, runtime/contract/persona.schema.json, personas/README.md, personas/builtin/codex-default-consultant.md, personas/builtin/codex-default-reviewer.md, personas/builtin/gemini-default-consultant.md, commands/z-personas.md, skills/z-personas/SKILL.md, runtime/drivers/_persona_utils.py, runtime/drivers/claude/persona_export.py, runtime/contract/event.schema.json

## Overview

A **persona** is a saved prompt-prefix preset that gets prepended to a role's task prompt at dispatch time. Persona, model, and runtime are **orthogonal axes** — each is configured independently, not bundled together.

- **Persona** — what behavioral tone and context the agent has (prompt prefix).
- **Model** — which model to use (e.g. `gpt-5-codex`, `gemini-2.5-pro`).
- **Runtime** — which CLI provider executes the call (e.g. `codex-cli`, `gemini-cli`).

You can mix any combination: a Gemini-tuned persona body with the `codex-cli` runtime and any model string your CLI accepts. The persona system is now applied across many dispatch sites — critique panels (`z-plan`, `z-debug`), audit dimensions (`z-audit`), advisory consult arms (`z-plan-light`, `z-audit`), code-review gates, and brainstorm ideators — with all convergent sites governed by the NEUTRAL-AUTHORITY invariant.

See [PROVIDERS.md](PROVIDERS.md) for the runtime registry that describes how each CLI is invoked.

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

You are an adversarial code reviewer. Your job is to find blockers and major
issues only — do not report style nits or minor suggestions.

Return your verdict in this exact structure:
VERDICT: PASS | FAIL | BLOCKED
...
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique identifier. Must match `^[a-z][a-z0-9-]*$` (kebab-case; no dots, slashes, or trailing hyphen). |
| `description` | yes | Human-readable summary shown by `/z-personas list`. |
| `compatible_roles` | no | Soft hint: list of roles this persona is designed for. A mismatch emits a `persona_compat_warning` event but does not block. |
| `contract` | no | Expected output structure: `freeform`, `review-verdict`, or `strict-json`. When the bound role declares an `expected_contract`, a mismatch is a hard failure at startup. |

### Body

Everything below the closing `---` is the prompt prefix. It is prepended verbatim before the role's task prompt at dispatch time. No interpolation in v1 — the body is treated as a static string.

---

## Layered storage and precedence

Personas are discovered from three layers in ascending priority (last wins per name):

| Layer | Path | Priority |
|-------|------|----------|
| Builtin (shipped with harness) | `personas/builtin/` | Lowest |
| User-global | `~/.config/z-harness/personas/` | Middle |
| Repo-local | `<repo>/.z-harness/personas/` | Highest |

When the same `name` appears in more than one layer, the highest-priority layer wins and z-harness emits a `persona_shadowed` event (once per process per name):

```
[personas] persona_shadowed: codex-default-reviewer — repo overrides user-global
```

Run `/z-personas where <name>` to see all layers that define a persona and which one won.

---

## Role registry

The role registry (`_ROLE_REGISTRY` in `scripts/resolve-persona.py`) is the single source of truth for known roles and their expected output contracts. There are currently **seven roles**:

| Role | Contract | Purpose |
|------|----------|---------|
| `consultant_primary` | `freeform` | Primary consultant dispatch; skeptical/analytical tone. |
| `consultant_secondary` | `freeform` | Secondary consultant dispatch; synthesis or adversarial framing. |
| `reviewer` | `review-verdict` | Code/plan reviewer; must produce `VERDICT: PASS\|FAIL\|BLOCKED`. |
| `implementer` | `None` (any) | Task implementer in the persona-rotation experiment. |
| `ideator` | `None` (any) | Brainstorm ideator — distinct personas per ideator arm in `/z-brainstorm`. |
| `consultant` | `None` (any) | Convergent eval lens — used by the 5-panel critique arms in `/z-plan` / `/z-debug` AND the measured advisory consult arms in `/z-plan-light` / `/z-audit`. |
| `audit_persona` | `None` (any) | Dimension auditor in `/z-audit` — one persona drawn per audit dimension (correctness / perf / cleanliness / design). Finding-oriented personas are appropriate here. |

A persona joins a role's pool by listing that role in its `compatible_roles` frontmatter field. Omitting `compatible_roles` makes the persona eligible for any role (unless a contract mismatch exists).

---

## Builtin persona pools

The harness ships 30 builtin personas under `personas/builtin/`. The table below shows the pool size per role:

| Role | Builtin count | Example members |
|------|--------------|-----------------|
| `consultant` | 7 | `cold-bench-scientist`, `quiet-systems-cartographer`, `paranoid-ledger-keeper`, `anti-consensus-surgeon`, `cut-it-half`, `physics-reductionist`, `fossil-whisperer` |
| `audit_persona` | 6 | `correctness-nihilist`, `bug-bounty-feralist`, `paranoid-guard`, `nanosecond-miser`, `contract-lawyer-bot`, `spec-literalist` |
| `ideator` | 8 | `anti-consensus-surgeon`, `biomimetic-architect`, `brutalist-architect`, `cobol-greybeard`, `cut-it-half`, `fossil-whisperer`, `pattern-oracle`, `physics-reductionist` |
| `consultant_primary/secondary` | varies | `codex-default-consultant`, `gemini-default-consultant`, `biomimetic-architect`, `cold-bench-scientist`, `fossil-whisperer`, `paranoid-ledger-keeper`, `quiet-systems-cartographer`, `cut-it-half` |
| `reviewer` | varies | `codex-default-reviewer`, `reddit-archaeologist`, `spec-literalist`, `adversarial-user`, `anti-consensus-surgeon`, `boring-anchor`, `bug-bounty-feralist`, `chaos-injection`, `correctness-nihilist`, `contract-lawyer-bot`, `cobol-greybeard`, `exhausted-maintainer`, `nanosecond-miser`, `overnight-intern`, `paranoid-guard`, `postmortem-coroner`, `cold-bench-scientist`, `quiet-systems-cartographer` |
| `implementer` | varies | `boring-anchor`, `brutalist-architect`, `bug-bounty-feralist`, `contract-lawyer-bot`, `correctness-nihilist`, `exhausted-maintainer`, `lazy-golfer`, `physics-reductionist`, `postmortem-coroner`, `paranoid-ledger-keeper`, `probationary-implementer` |

Pool must be >= the max arm count drawn: consultant pool >= 5 (5-panel), audit_persona pool >= 4 (4 dimensions). Both invariants are verified by tests.

---

## TOML binding

Bind a persona (plus model and runtime) to a specific (command, role) pair in your `config.toml`:

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

- Command names use underscores in TOML (`z_plan` not `/z-plan`). `/z-personas` translates back to slash-form on output.
- All three fields (`persona`, `model`, `runtime`) are optional within a `[roles.*.*]` table — set only what you want to override.
- Per-field merge: when a repo TOML sets `model` and a global TOML sets `persona`, the merged binding has both.

### Resolution order

At dispatch time, each axis (persona, model, runtime) is resolved independently in this priority:

1. **`[roles.<command>.<role>]` in repo config.toml** — command-scoped, repo wins.
2. **`[roles.<command>.<role>]` in global config.toml** — command-scoped, global.
3. **`[roles.default.<role>]` in repo config.toml** — cross-command default, repo wins.
4. **`[roles.default.<role>]` in global config.toml** — cross-command default, global.
5. **Legacy `providers.json` `roles` mapping** — backward-compat fallback (runtime only; emits `legacy_provider_roles_used`).
6. **None** — axis unset.

---

## Per-site persona behavior

Dispatch sites are classified as **divergent** (generation) or **convergent** (evaluation). The two categories differ in how personas participate:

| Site | Kind | Gating knob | Persona behavior |
|------|------|-------------|-----------------|
| `/z-debug` Phase 3a + 3b (hypothesis generators) | DIVERGENT | `personas.critique_panel` | Draw 5 distinct `consultant` personas; positionally prepend onto the 5 fixed panel arms. |
| `/z-plan` Phase 3 + Phase 7 (critique panel) | DIVERGENT | `personas.critique_panel` | Draw 5 distinct `consultant` personas; positionally prepend onto the 5 fixed panel arms. |
| `/z-audit` dimension auditors (correctness/perf/cleanliness/design) | DIVERGENT | `personas.audit` | Draw 1 distinct `audit_persona` per dimension; prepend directly. |
| `/z-brainstorm` ideators (3 parallel ideators) | DIVERGENT | `brainstorm.personas` | Draw 3 distinct `ideator` personas; positional assignment. |
| `/z-plan-light` bundled consult | CONVERGENT | `personas.consult_eval` (default OFF) | Advisory persona arm alongside neutral arm. Neutral stays authoritative. |
| `/z-audit` bundled consult | CONVERGENT | `personas.consult_eval` (default OFF) | Advisory persona arm alongside neutral arm. Neutral stays authoritative. |
| Code-review gates (`/z-implement-all`, `/z-implement-next`, `/z-plan-light`, `/z-fix`, `/z-do`) | CONVERGENT | `personas.review_eval` (default ON) | One advisory `reviewer`-role persona drawn with `random-for-role`. Neutral codex gate is authoritative. |

**`/z-research` is intentionally excluded.** Its three perspectives (architecture-conservative / product-expansive / failure-mode-adversarial) are already fixed semantic lenses; adding random personas on top would conflict with those assigned roles.

---

## NEUTRAL-AUTHORITY invariant

At every **convergent** site, the following is a mechanical contract (not prose-only):

- The **neutral arm's output is the decision of record**. The persona arm is ADDITIVE and advisory only.
- The persona arm's recommendation is logged under a **separate telemetry field**: `persona_advisory_recommendation` for consults; `reviewer_participant=random_arm` for eval-reviewers.
- **No code path reads both** the neutral and persona outputs into the authoritative decision or synthesis.
- The persona arm NEVER changes halt/retry behavior at code-review gates.
- Enforced by acceptance tests (T006/T007): construct a mock case where the persona arm disagrees with the neutral arm and assert the neutral output stands unchanged.

### Advisory eval-reviewer at code-review gates

At `/z-implement-all` / `/z-implement-next` / `/z-plan-light` / `/z-fix` / `/z-do` review gates:

- The **neutral codex reviewer** runs as the authoritative gate. Its PASS/FAIL/BLOCKED verdict is the decision.
- When `personas.review_eval = true` (default ON), **one advisory reviewer** is dispatched in parallel with a `random-for-role reviewer` draw (`selection_source=random_role_pool`). Its verdict is logged advisory-only (`reviewer_participant=random_arm`).
- Both reviewers share `attempt_id`; each has its own `draw_id`.
- The shared advisory eval-reviewer pattern is defined **once** (a referenced snippet) and reused across all 5 gate sites — not copy-pasted.
- `personas.review_eval = false` restores neutral-gate-only behavior (identical to pre-feature).

---

## The `ideator` role (`/z-brainstorm` persona diversity)

`ideator` is used by `/z-brainstorm` to give its three parallel ideators **distinct** personas — persona diversity layered on top of vendor diversity. Unlike the `implementer` rotation, this is **not** an experiment: there are no control / no-persona baseline arms and no per-ideator outcome tracking (an ideator has no measurable terminal). It is gated on the `brainstorm.personas` config knob (default ON).

Drawing is done by `random-distinct-for-role`, which omits control arms (boring-anchor, no-persona) and draws without replacement:

```bash
# Draw up to 3 distinct ideator personas (never boring-anchor / no-persona):
python scripts/resolve-persona.py random-distinct-for-role ideator --count=3
# Returns: JSON array of resolve-shaped objects (one per ideator slot)
```

**Graceful degradation:** if the pool holds fewer than the requested count, the subcommand returns a shorter array (or `[]` when empty), notes the underflow on stderr, and exits 0. `/z-brainstorm` binds the returned personas positionally and runs any unfilled slot vanilla.

---

## Orchestrator usage pattern

The **orchestrator** (slash command, skill, or Agent() call site) is responsible for persona resolution and prompt composition. The dispatcher stays thin — it accepts an already-composed prompt and never calls `resolve-persona.py` internally.

### Step 1 — Resolve persona + model + runtime

```bash
python scripts/resolve-persona.py resolve z_plan consultant_primary
# → {"persona": "codex-default-consultant", "model": "", "runtime": "codex-cli",
#    "source": "roles_default", "persona_body_path": "/abs/path/..."}
```

### Step 2 — Compose the final prompt

```python
from runtime.dispatch.persona_prompt import prepend_persona

final_prompt = prepend_persona(body_path, task_prompt)
# If body_path is None/empty, task_prompt is returned unchanged.
# YAML frontmatter (--- blocks) is stripped automatically.
```

### Step 3 — Pass `final_prompt` to `Dispatcher.run`

```python
from runtime.dispatch.dispatcher import Dispatcher

dispatcher = Dispatcher(repo_root=repo_root, run_id=run_id)
result = dispatcher.run(
    driver,
    command_id="z-plan",
    caller_args=[final_prompt],
    provider_config=provider_config,
    role="consultant_primary",
    model=envelope.get("model") or None,
    runtime=envelope.get("runtime") or None,
)
```

The `role` kwarg is informational — it is included in the `persona_bound` event payload but not used for resolution. The dispatcher itself does **not** call `resolve-persona.py` or read persona files.

---

## `resolve-persona.py` subcommand reference

| Subcommand | Purpose |
|-----------|---------|
| `list-personas` | Print JSON array of `{name, source_layer, path}` — winner per name only. |
| `where <name>` | Print all layer paths defining `<name>` in load order. Exits 1 if not found. |
| `resolve <command> <role>` | Resolve persona/model/runtime triple for (command, role). |
| `list-bindings [--command <c>]` | Walk all configured bindings; output JSON tree. |
| `validate` | Check all bound personas exist, compatible_roles are known, contracts match. |
| `read <name>` | Print frontmatter + body of the winning persona file. |
| `random-for-role <role> [--exclude=<ids>] [--seed=<s>]` | Draw a random persona; includes boring-anchor and no-persona sentinel; returns resolve-shaped JSON + `{selection_source, draw_id, candidates}`. |
| `random-distinct-for-role <role> --count=<N> [--exclude=<ids>] [--seed=<s>]` | Draw up to N distinct personas without replacement; excludes boring-anchor and no-persona. Graceful underflow. Used by `/z-brainstorm` and multi-arm panels. |
| `forced-control <role> [--arm=<boring-anchor\|no-persona>]` | Return forced-control arm tagged `selection_source=forced_control`. |
| `control-counter --increment` | Atomically read + increment + persist the repo-level control cadence counter. Returns new integer. |

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
| `/z-personas read <name>` | Print frontmatter + body of the named persona. |

---

## Persona rotation (experimental)

The persona-rotation experiment rotates which persona is used for the `implementer` and `reviewer` roles across z-harness runs, collecting passive outcome data to compare persona effectiveness. Gated by `experiment.persona_rotation` in config (default ON).

### How it works

**Implementer rotation (`/z-implement-all` and `/z-implement-next`):**

Every task attempt gets a persona drawn by `random-for-role implementer`. Every `experiment.control_every_n`-th attempt (default every 5th, counted repo-wide via `.z-harness/.persona-control-counter`) calls `forced-control implementer` instead, which returns `boring-anchor` tagged `selection_source: forced_control`. The draw result is persisted to `$BASE/archive/tasks/<task-id>/persona-draw.json`. On **resume** (same attempt_id), the draw is reused verbatim. On **retry** (new attempt_id = new cycle), a fresh draw is made.

**Reviewer dispatch:** both a base codex reviewer (`reviewer_participant: base_codex`) and one advisory random-arm reviewer (`reviewer_participant: random_arm`) are dispatched as separate `Agent()` calls. The random-arm verdict is advisory only — it never changes halt/retry behavior. Both share `attempt_id`; each has its own `draw_id`.

### Selection sources

| `selection_source` | Meaning |
|-------------------|---------|
| `random_role_pool` | Normal random draw from eligible personas (single-draw advisory arms). |
| `random_role_pool_distinct` | Distinct draw from a multi-arm pool — no replacement (panels, dimensions). |
| `forced_control` | Forced `boring-anchor` draw on the Nth-attempt cadence. |
| `fallback_empty_pool` | No eligible personas found; fell back to `boring-anchor`. **Quarantined in analysis.** |
| `fixed_panel` | Panel member in a fixed 5-panel consult (plan/debug phases). |

### `boring-anchor` and `no-persona`

`boring-anchor` is the baseline persona that ships with the harness. As of T102 (amended), it is a normal member of the `random_role_pool` and may be drawn stochastically, in addition to being the forced-control cadence arm.

`no-persona` is a reserved sentinel (no file on disk, `persona_body_path=null`) representing the vanilla implementer with zero prompt prefix. It is always prepended to the random candidate pool by `random-for-role` before disk enumeration (unless explicitly `--excluded`). A `no-persona` draw is a **tracked baseline arm**, not the same as knob-off.

### Analysis baseline resolution

`persona-stats.py` resolves the delta baseline per `(role, complexity_tier)` stratum:
1. `no-persona` — primary null baseline. Used when the stratum has at least one `no-persona` sample.
2. `boring-anchor` — secondary bland-control fallback.
3. `None` — raw metrics reported without a delta if neither baseline exists.

### `personas.implementer_retry` knob

| Value | Behavior |
|-------|----------|
| `same` (default) | `persona-draw.json` written once on cycle 1 and never overwritten. Same persona across all retry cycles for traceability. |
| `new` | Fresh draw on each retry, excluding the prior attempt's persona. |

### Turning off

```toml
[experiment]
persona_rotation = false
```

Or via env: `export Z_HARNESS_EXPERIMENT_PERSONA_ROTATION=false`

---

## Telemetry events

| Event | Fired when |
|-------|-----------|
| `persona_bound` | Each dispatch: records `{run_id, command, role, persona, persona_id, model, runtime, selection_source, draw_id, source}`. `source` is a per-axis nested dict `{persona: <layer>, model: <layer>, runtime: <layer>}`. |
| `persona_override_used` | A per-Agent() / Dispatcher.run() kwarg overrides a config default. |
| `model_resolved` | Records `{command, model, runtime, source}` at dispatch. |
| `persona_compat_warning` | A persona is bound to a role not in its `compatible_roles`. |
| `persona_shadowed` | A persona name is defined in more than one layer (once per process per name). |
| `persona_binding_chimera` | A binding's three axes resolve from >=2 different config layers. |
| `legacy_provider_roles_used` | Resolution falls back to `providers.json` `roles` map. |
| `persona_random_selected` | A random draw was made via `random-for-role`, `random-distinct-for-role`, or `forced-control`. Payload: `{role, selected, candidates, draw_id, selection_source, task_id, attempt_id, persona_id}`. Emitted BEFORE the agent runs. |
| `persona_attempt_outcome` | Per-attempt terminal outcome (only when `experiment.persona_rotation=true`). Payload: `{run_id, command, role, task_id, attempt_id, persona_id, draw_id, complexity_tier, diff_size, review_cycles, retries, blocker_count, wall_ms, status}`. |
| `persona_advisory_recommendation` | Advisory persona arm result at convergent consult sites. Logged separately; never folded into the authoritative decision. |

> Note: `persona_bound`, `persona_override_used`, and `model_resolved` payloads use `command` (not `command_id`) as of T103.

---

## Edge cases / gotchas

- `_shadowed_emitted` is keyed on name only (not on layer pair) — fires exactly once per process per shadowed name regardless of how many layers define it.
- `persona_binding_chimera` is keyed on `(command, role)`, not on the specific axis combination — fires only once per process per `(command, role)` pair.
- `boring-anchor` bypasses `compatible_roles` and contract checks in `_enumerate_role_compatible_personas` — it is treated as multi-role/any and enters the pool for any role.
- `random-distinct-for-role` **excludes** `boring-anchor` and `no-persona` (diversity focus); `random-for-role` **includes** them (experiment control arms).
- A `no-persona.md` file in any layer is silently filtered out by `_enumerate_role_compatible_personas` — only the hardcoded `_NO_PERSONA_SENTINEL` can produce a `no-persona` draw.
- `fallback_empty_pool` always returns `boring-anchor`; this is NOT a `forced_control` sample and must NOT be counted as boring-anchor baseline in analysis.
- `prepend_persona` strips YAML frontmatter using a simple string search for `"\n---\n"`; if the closing delimiter is missing, the entire file (including frontmatter) is treated as the body.
- Layer 3 (repo-local) path uses `git rev-parse` to find repo root; falls back to cwd if git is unavailable. `Z_HARNESS_REPO_ROOT`, `Z_HARNESS_REPO_PERSONAS_DIR`, `Z_HARNESS_BUILTIN_PERSONAS_DIR`, and `Z_HARNESS_USER_PERSONAS_DIR` all override the respective layer paths for hermetic testing.
- Unknown frontmatter keys cause exit 2 — `model` and `runtime` belong in TOML config, not in the persona file.
- `cmd_validate` checks `compatible_roles` only against known role names in `_ROLE_REGISTRY` — a `compatible_roles` entry for an unknown role is flagged as an error.
- `resolve-persona.sh` is a thin bash wrapper — all logic lives in `resolve-persona.py`; the shell script exists solely so dispatch sites do not need to know the Python path.

---

## Authoring a custom persona

1. Create `<repo>/.z-harness/personas/<your-name>.md`.
2. Add frontmatter with at least `name: <your-name>` and `description: <one-liner>`.
3. Write the prompt prefix in the body.
4. Bind it in `config.toml`:
   ```toml
   [roles.default.consultant_primary]
   persona = "<your-name>"
   ```
5. Run `/z-personas validate` to check for contract/compat issues.
