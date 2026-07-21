# oh-my-pi (omp) setup for z-harness

> Last updated: 2026-07-21 (default advisory roles aligned to the repository provider registry)

`omp` / [oh-my-pi](https://github.com/can1357/oh-my-pi) (`@earendil-works/pi-coding-agent`) has
two distinct roles in z-harness. Understanding the difference is important:

| Role | What it does | When to use |
|------|-------------|-------------|
| **OMP native host** | `z-harness launch --host omp` runs z-harness commands directly in OMP; OMP is the execution environment | When you want to run `/z-execute`, `/z-consult`, `/z-gate`, or `/z-panel` natively in OMP (four families proven at Claude-parity, T009) |
| **OMP consult-provider** | `scripts/omp-consult.sh` adapts stdin prompts for the provider registry; `omp-antigravity-pro`/`omp-openai-sol`/`omp-openai-terra` route advisory consultant/reviewer roles through OMP's OAuth | When Claude Code is the primary host and you want advisory consultant/reviewer roles to use Gemini 3.1 Pro / GPT-5.6 Sol / GPT-5.6 Terra via OMP's OAuth subscriptions |

These two paths are explicitly separate. The consult-provider path (`omp-consult.sh`) uses
`--no-rules --no-session` and is only for advisory uses. The native host path keeps
rules and session semantics enabled through `OMP_PLUGIN_ROOT`. Do not conflate them.

## OMP as a native host (T009)

z-harness treats `omp` as a first-class host alongside Claude Code. The parity gate in
`z_harness_cli/adapters/omp_parity_gate.py` (T009) has resolved: four command families are
**native** (proven to Claude-Code parity by T008 behavioral tests):

- `/z-execute` — subagent fan-out, reviewer routing, AskUser/gate mapping, telemetry
- `/z-consult` — consultant dispatch isolation (separate from `omp-consult.sh`)
- `/z-gate` — AskUser/gate ordering, payload, blocking semantics
- `/z-panel` — multi-agent panel dispatch (shared fan-out evidence with z-execute)

All other command families (`/z-plan`, `/z-brainstorm`, `/z-audit`, `/z-export`, etc.) run in
**degraded** mode — they work but without proven Claude-Code behavioral parity.

### Launch and inject

```bash
z-harness launch --host omp
# or:
python3 -m z_harness_cli launch --host omp
```

On launch, z-harness:
1. Writes a gitignored session file at `<project>/.omp/z-harness/session.yml` (magic marker so
   cleanup can identify it).
2. Sets `OMP_PLUGIN_ROOT=<project>/.omp/z-harness` in the child environment.
3. PTY-hands over to `omp` in the requested project directory.
4. On exit or crash: removes `session.yml` and the `.omp/z-harness/` directory idempotently.
5. On orphan recovery (next launch after abrupt parent-process death): cleanup is re-attempted.

**`.omp/config.yml` is never modified.** The checked-in `.omp/config.yml` keeps
`skills.enableAgentsProject: false` to avoid auto-loading this repo's large root `AGENTS.md`.
Discovery comes entirely from `OMP_PLUGIN_ROOT`.

### Export

```bash
python3 -m z_harness_cli export --host omp --out temp/exports/omp --force
```

Emits the OMP-native package layout under `.omp/z-harness/`:

```
.omp/z-harness/
  manifest.yml
  skills/<id>/SKILL.md
  rules/<id>.md
  prompts/<id>.md
  agents/<id>.md
  profiles/<name>.yml
```

The export returns `ExportResult(fidelity="native")` after T009. `.omp/config.yml` is not
modified by the exporter; it continues to suppress project AGENTS autoloading.

### Doctor / detect

```bash
z-harness doctor
# or:
python3 -m z_harness_cli doctor
```

Reports OMP with fidelity tier (`native`), capabilities (`OMP_PLUGIN_ROOT`, ephemeral cleanup),
and per-command tiers (native for 4 families; degraded for others).

### Runtime driver verification

```bash
python3 -m pytest tests/adapters/test_omp_adapter.py tests/drivers/test_omp_export_driver.py runtime/tests/test_omp_driver.py runtime/tests/test_omp_parity.py runtime/tests/test_omp_export.py tests/conformance/test_strict.py -q
```

All tests should pass (86 passed, 1 skipped, 80 subtests as of T009).

---

## OMP as a consult-provider

z-harness can route its **advisory consult arms** through omp's OAuth-backed multi-model
dispatch so a single binary serves multiple model providers from your subscriptions instead of
separate vendor CLIs and API keys.

All three consult/reviewer roles are wired through omp by default (`.z-harness/providers.json`):

| Role | Provider entry | Model | Auth |
|------|----------------|-------|------|
| `consultant_primary` | `omp-antigravity-pro` (alias `omp-gemini`) | `google-antigravity/gemini-3.1-pro` | Antigravity OAuth |
| `consultant_secondary` | `omp-openai-sol` | `openai-codex/gpt-5.6-sol` | OpenAI Codex OAuth |
| `reviewer` | `omp-openai-terra` | `openai-codex/gpt-5.6-terra` | OpenAI Codex OAuth |

> **Compatibility history:** `consultant_secondary = omp-cursor-sol` and
> `reviewer = omp-cursor-terra` were former defaults; the later intermediate
> `consultant_secondary = omp-codex` and `reviewer = codex-cli` bindings are retired too.
> Cursor-backed entries and `omp-codex` remain available for manual/custom binding, but none is a
> current default. Cursor authentication is optional and not bound to a default role.

## `pi` vs `omp` — which binary

`pi` and `omp` are the **same agent** (`@earendil-works/pi-coding-agent`): `pi` is the Node
CLI wrapper, `omp` is the compiled binary. **z-harness drives `omp`**, because the OAuth
credentials live in omp's *auth-broker vault* — the `pi` Node CLI reads `~/.pi/agent/auth.json`
and cannot see them (`pi -p` reports "no API key" while `omp -p` works).

## One-time OAuth login (for consult-provider use)

Login is interactive (browser); run it in your terminal:

```
pi            # or: omp
/login        # select a provider:
              #   ChatGPT Plus/Pro (Codex)   -> openai-codex   (GPT-5.6 Sol/Terra roles)
              #   google-antigravity         -> Gemini 3.1 Pro, pooled Google/Anthropic/OpenAI
              #   (optional) Claude Pro/Max, GitHub Copilot, xAI Grok
```

If the flow prints a URL and waits, complete it in the browser and paste the redirect back with
`/login <url>`. Tokens are stored in the auth-broker and auto-refresh. `/logout <provider>`
clears one.

**Gemini via API key (alternative to Antigravity OAuth):** export `GEMINI_API_KEY` (or add a
`"google"` api_key entry to `~/.pi/agent/auth.json`) and point `omp-gemini` at `google/<id>`
instead.

> **Billing caveat:** routing Claude (or the Antigravity-pooled Anthropic bucket) through omp
> draws on per-token *extra usage*, not your Claude plan limits. Use Codex/Gemini arms, not
> Claude-via-omp.

## Verify consult-provider auth

```
scripts/check-pi-auth.sh
```

Read-only; probes `omp token <provider>` (never prints secrets) and reports which providers are
authenticated. Exit 0 always (add `--strict` to fail when a required arm is missing). Example
output (`google-antigravity` and `openai-codex` are required; Cursor is optional):

```
PROVIDER               STATUS     POWERS
google-antigravity     authed     omp-antigravity-pro consultant_primary arm (Gemini 3.1 Pro, Antigravity OAuth)
openai-codex           authed     omp-openai-sol/omp-openai-terra consultant_secondary+reviewer arms (GPT-5.6 Sol/Terra)
cursor                 authed     optional manual compatibility entries; not bound to a default role
```

`openai-codex` is the required backend for both `consultant_secondary` and `reviewer`.
`google-antigravity` is required for `consultant_primary`. Cursor is optional and not role-bound;
its provider entries remain for manual compatibility only.

## How the consult dispatch works

The provider registry pipes the prompt to a command's **stdin**, but `omp -p` ignores stdin and
takes the prompt as a positional **argument**. `scripts/omp-consult.sh` bridges the two:

```bash
printf '%s' "$PROMPT" | omp-consult.sh openai-codex/gpt-5.6-sol
# == omp -p --no-session --no-rules --model openai-codex/gpt-5.6-sol "$PROMPT"
```

The model id is stored in each entry's `args_template` (not `model_arg_template`) because the
consult agent dispatch reads `args_template` directly. `omp-consult.sh` must be on `PATH`
(symlinked into `~/.local/bin/`) so `resolve-provider`'s `shutil.which` check passes.

Note: `omp-consult.sh` uses `--no-session --no-rules` because consult roles are advisory only.
This is different from OMP **native dispatch** (`OmpHostDriver`), which keeps rules and session
semantics enabled.

## Turning the consult arms on

The consult arms only fire when `runtime.consult = "on"`. If your `.z-harness/config.toml` has
it set to `off` (a pacing default), flip it to `on` to use the omp arms:

```toml
[runtime]
consult = "on"
```

See also: [providers-registry.md](providers-registry.md), [PROVIDERS.md](PROVIDERS.md).
