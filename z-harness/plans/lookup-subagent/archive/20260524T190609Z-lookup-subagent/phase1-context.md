# Phase 1 — Context summary

## Confirmed (z-harness side)

- **Tool-whitelist pattern** is simple YAML frontmatter `tools: Bash, Read, Grep, Glob` (comma-separated). Pattern from `agents/remote-runner.md:4`, `agents/doc-fetcher.md:4`, `agents/cluster-planner.md:4`.
- **Verb-blocklist mechanism** is documented prose in `agents/remote-runner.md:35` — model-enforced via "before executing any X, grep the string for write verbs; refuse with `STATUS: refused`." Not a hard runtime guard; relies on the agent honoring the instruction.
- **No existing WebFetch/WebSearch usage** in z-harness commands/agents/skills. `external-lookup` would be the first agent to whitelist these tools.
- **No CLAUDE.md global-rule export mechanism** in z-harness today. The "no doc-fetcher main-thread read" rule lives in the user's `~/.claude/CLAUDE.md`, not auto-injected by z-harness into consumer repos. Any "main-thread WebFetch ban" rule would have to live (a) in the agent file as documentation, (b) in the user's own CLAUDE.md, or (c) be added as a new z-harness export feature — which would balloon scope.
- **z-export.md** + `scripts/export-*.py` already export z-harness commands/agents/skills into target repos (Cursor / Codex / Agy paths). A new `external-lookup` agent would auto-flow through this export mechanism.

## Constraint: qt-bot is remote-only

`~/dev/qt-bot/` does **not exist locally**. qt-bot lives on remote host `zeke-pc` (per `agents/remote-runner.md` precedent: sandbox at `~/dev/qt-bot-sandbox/`, live tree at `zeke-pc:~/dev/qt-bot/`).

**Implication for the plan:** we cannot directly inspect qt-bot's current `.claude/` directory, its existing skills, or its Kalshi client surface from this orchestrator session. Two options:

1. **SSH-peek via `qt-bot-remote` skill** during planning to enumerate qt-bot's agents dir + Kalshi client signatures. Adds a remote round-trip, but produces a concretely-targeted spec.
2. **Template abstractly** — assume qt-bot follows z-harness agent conventions (it's the same user, same plugin), spec the qt-bot agent file generically (filename, frontmatter, output contract, tool whitelist placeholder), and defer the actual deposit + Kalshi-client integration to implementation tasks that use `qt-bot-remote`.

**Recommendation:** option 2. The qt-bot agent file is a static spec that doesn't depend on knowing the exact Kalshi client path until deposit time. The implementer subagent can resolve the client path on remote during T-NNN execution. This keeps planning cheap.

## Open decisions surfaced by exploration

These get formalized in Phase 2's decisions.md:

1. **Tool whitelist for `external-lookup`** — WebFetch is the obvious primary, but does it need WebSearch? Bash for `curl`? If Bash, what verb-blocklist?
2. **Model tier** — Haiku for `external-lookup` per Codex; `qt-market-lookup` Sonnet or Haiku?
3. **Output contract location** — embed in `agents/external-lookup.md` only, or extract into a separate `docs/llm/lookup-contract.json` so qt-bot can target it without reading the agent file?
4. **Main-thread WebFetch ban** — agent-file documentation only? user CLAUDE.md rule? skip entirely as best-effort?
5. **`qt-market-lookup` deposit mechanism** — manual one-time SSH deposit, or extend z-harness `z-export` to also push to qt-bot remote?
6. **Verb-blocklist for `external-lookup`** — only if Bash is whitelisted. What verbs (no DB writes makes sense; what about no `git push`, no `gh pr create`)?
7. **Token budget on output** — `doc-fetcher` is ≤2 KB synthesis. Same cap for external-lookup? Or different (web responses are more variable)?
8. **Caching policy** — default off (per Codex risk #3), or include a stub for opt-in per-domain?
