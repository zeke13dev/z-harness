# oh-my-pi (omp) setup for z-harness

z-harness can route its **advisory consult arms** through [oh-my-pi](https://github.com/can1357/oh-my-pi)
(`omp` / `@earendil-works/pi-coding-agent`) so a single OAuth-backed binary serves multiple model
providers from your *subscriptions* instead of separate vendor CLIs and API keys.

Two arms are wired by default (`.z-harness/providers.json`):

| Role | Provider entry | Model | Auth |
|------|----------------|-------|------|
| `consultant_primary` | `omp-gemini` | `google-antigravity/gemini-3.1-pro` | Antigravity OAuth |
| `consultant_secondary` | `omp-codex` | `openai-codex/gpt-5.5` | ChatGPT Plus/Pro OAuth |
| `reviewer` | `codex-cli` (**unchanged**) | gpt-5-codex | native codex CLI |

> The blocking **reviewer** gate deliberately stays on the native codex CLI — it is not routed through
> omp, so an OAuth token-refresh hiccup can never stall a review (plan decision D2).

## `pi` vs `omp` — which binary

`pi` and `omp` are the **same agent** (`@earendil-works/pi-coding-agent`): `pi` is the Node CLI wrapper,
`omp` is the compiled binary. **z-harness drives `omp`**, because the OAuth credentials live in omp's
*auth-broker vault* — the `pi` Node CLI reads `~/.pi/agent/auth.json` and cannot see them (`pi -p`
reports "no API key" while `omp -p` works).

## One-time OAuth login

Login is interactive (browser); run it in your terminal:

```
pi            # or: omp
/login        # select a provider:
              #   ChatGPT Plus/Pro (Codex)   -> openai-codex   (GPT-5.5)
              #   google-antigravity         -> Gemini 3.1 Pro, pooled Google/Anthropic/OpenAI
              #   (optional) Claude Pro/Max, GitHub Copilot, xAI Grok
```

If the flow prints a URL and waits, complete it in the browser and paste the redirect back with
`/login <url>`. Tokens are stored in the auth-broker and auto-refresh. `/logout <provider>` clears one.

**Gemini via API key (alternative to Antigravity OAuth):** export `GEMINI_API_KEY` (or add a
`"google"` api_key entry to `~/.pi/agent/auth.json`) and point `omp-gemini` at `google/<id>` instead.

> **Billing caveat:** routing Claude (or the Antigravity-pooled Anthropic bucket) through omp draws on
> per-token *extra usage*, not your Claude plan limits. Use Codex/Gemini arms, not Claude-via-omp.

## Verify

```
scripts/check-pi-auth.sh
```

Read-only; probes `omp token <provider>` (never prints secrets) and reports which providers are
authenticated. Exit 0 always (add `--strict` to fail when a required arm is missing). Expected:

```
PROVIDER               STATUS     POWERS
openai-codex           authed     omp-codex consult arm (GPT-5.5, ChatGPT sub)
google-antigravity     authed     omp-gemini consult arm (Gemini 3.1 Pro, Antigravity OAuth)
cursor                 authed     optional future Cursor arm
```

## How the dispatch works (the adapter)

The provider registry pipes the prompt to a command's **stdin**, but `omp -p` ignores stdin and takes
the prompt as a positional **argument**. `scripts/omp-consult.sh` bridges the two:

```bash
printf '%s' "$PROMPT" | omp-consult.sh openai-codex/gpt-5.5
# == omp -p --no-session --model openai-codex/gpt-5.5 "$PROMPT"
```

The model id is stored in each entry's `args_template` (not `model_arg_template`) because the consult
agent dispatch reads `args_template` directly. `omp-consult.sh` must be on `PATH` (symlinked into
`~/.local/bin/`) so `resolve-provider`'s `shutil.which` check passes.

## Turning the arms on

The consult arms only fire when `runtime.consult = "on"`. If your `.z-harness/config.toml` has it set
to `off` (a pacing default), flip it to `on` to use the omp arms:

```toml
[runtime]
consult = "on"
```

See also: [providers-registry.md](providers-registry.md), [PROVIDERS.md](PROVIDERS.md).
