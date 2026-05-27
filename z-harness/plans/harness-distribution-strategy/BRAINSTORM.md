---
artifact: brainstorm
slug: harness-distribution-strategy
generated_at: 2026-05-27T03:32:10Z
command: /z-brainstorm let's make sure we do this properly and explore all our options.
input_hash: 9c1f4a7d3b8e2056
depends_on: []
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: codex
---

# BRAINSTORM — harness-distribution-strategy

**Topic.** Today z-harness distributes to non-Claude-Code hosts via per-host Python adapter scripts (`export-codex.py`, `export-agy.py`, `export-cursor.py`) that translate `commands/`, `agents/`, `skills/` into target-specific surfaces, plus an `install.sh` that symlinks or tarball-extracts the result. The cost: a constant update loop, and host-unsupported constructs (subagent dispatch, AskUserQuestion, provider registry) degrade to limitation comments. The user's question: should z-harness instead ship as a standalone wrapper around the underlying CLI (claude/codex), owning UI + notifications? What are all the real alternatives?

---

## Framing: Claude

### Framing
The adapter approach is solving the wrong problem. It treats the host's plugin surface as the distribution target, but plugin surfaces are the least stable thing in the system — Cursor changed `.mdc` twice, Antigravity's 12k workflow limit already breaks `/z-plan`, Codex caches plugins per-thread. The real distribution target is the *conversation turn*: a structured prompt that reaches the model with the right context, tools, and subagent dispatch intact. Everything above that layer is envelope formatting that dies every time a host releases a breaking update. The wrapper hypothesis inverts the dependency, but obscures a secondary problem: the features that degrade aren't degrading because of wrong format — they degrade because they require runtime capabilities (parallel execution, interactive confirmation, tool plumbing) that only Claude Code provides. A wrapper does not conjure those capabilities; it relocates the absence.

### Core hypothesis
The correct architecture is a **thin routing daemon** that treats each host's native API as a dumb text transport and implements all orchestration above it in a host-agnostic runtime. Not a subprocess wrapper (fragile stdin/stdout, TUI interference, cache destruction). Not MCP (still a tool-call protocol gated by the host model). A local HTTP+SSE server — `z-daemon` — that any IDE plugin / CLI adapter / MCP bridge POSTs slash commands to. Daemon owns: provider selection, subagent dispatch, AskUserQuestion (via readline or web fallback), TaskCreate, metrics, push notifications. Each host shim shrinks to ~40 lines of "POST localhost:7373, stream events back". When Cursor changes `.mdc`, you update 40 lines, not `export-cursor.py` plus every command body.

### Risks
- **Provider credential plumbing is the hardest problem.** Today each host already has a valid model key. A daemon needs its own — or it has to borrow the host's via a local API, which vendors will eventually block as ToS.
- **Prompt cache locality loss.** Claude Code's perf advantage partly comes from cache affinity. Daemon-spawned subagents become cold-start sequences. Subagent dispatch latency for `/z-implement-all` is already a bottleneck.
- **The daemon becomes a new maintenance surface that is harder to update than a plugin file.** Plugin = symlink hot-swap. Daemon = restart, port allocation, multi-repo conflicts, persistent process the user must know is running. The "40-line shim" argument only holds if the daemon itself never changes — but it will, because AskUserQuestion / provider registry live there now, and those iterate constantly.

### Plan implications
- Freeze `export-codex.py` / `export-agy.py` / `export-cursor.py` at current capability; let them rot gracefully. Cut body-rewriting / limitation-comment substitution — those are false advertising.
- Install simplifies to `curl | sh` for daemon binary + one-time per-IDE shim. No per-host CAPABILITIES.md, no collision-suffix logic.
- `/z-update` becomes single-binary atomic swap.
- **Upstream blocking decision:** API key strategy. Either daemon brings its own key (works, but billing duplication and credential management on user), or it routes back through the host (works, but ToS risk).

### What would change my mind
- If Anthropic ships a stable, versioned MCP schema with multi-call concurrency (parallel child tool calls), adapters become viable again and the "limitation comment" problem dissolves. No sign of this happening.
- If prompt-cache locality measurements show cold-start subagent dispatch is acceptable on real tasks, daemon's main cost disappears. The "`/z-implement-all` is slow" claim is anecdotal — a 48-hour latency benchmark across warm-continuation vs fresh-process subagent dispatch would resolve it.

---

## Framing: Codex

### Framing
Stop treating host plugin formats as the product. Treat them as thin launchers. The durable unit is a **host-neutral z-harness runtime** with a stable internal command model; each host integration only answers "how do I invoke the runtime, pass context in, and stream results back?" Native plugins become convenience shims, not translated copies of the whole harness.

### Core hypothesis
A standalone wrapper works, but only if it stops pretending to be the underlying agent TUI. The right shape is a **sidecar/runtime that owns orchestration, state, notifications, subagent semantics, provider routing, and updates** — and delegates actual model turns and tool execution to **host-specific drivers**. The driver tier depends on what the host exposes: official SDK/API where it exists, CLI machine-readable mode where it exists, pty/TUI fallback only as last resort, "unsupported" gates above that.

### Risks
- Subprocess-wrapping a TUI is brittle: terminal escapes, stdin modes, resize events, auth flows, interrupts, tool prompts.
- Prompt cache locality degrades if the wrapper injects large dynamic scaffolding ahead of the host's stable prefix.
- Bypassing the host's native tool broker can make tool dispatch *worse*, not better.
- Some hosts don't expose enough API to drive cleanly; scraping terminal output is a last resort, not a platform.
- The runtime adds its own compatibility contract, release channel, config store, logs, security model.
- Users may lose the "native feel" that makes Claude Code / Codex / Cursor useful in the first place.

### Plan implications
- Define the canonical runtime contract **first**: command schema, agent schema, provider registry, user-question primitive, event log, artifact layout, notification API.
- Replace exporters with **tiny launch adapters**: "invoke runtime with command X and current repo context."
- Tier the execution backends explicitly: SDK > CLI machine-readable > pty/TUI > unsupported. Refuse to ship features into a tier that can't carry them — no limitation comments.
- Prototype on Codex CLI first (closest to current target, fastest to surface cache/tool/TUI costs).
- Keep native plugin exports as a compatibility bridge during migration, but stop expanding them strategically.
- Add a conformance test suite: same z-harness command run against each backend, asserting artifacts, prompts, logs, failure behavior match.

### What would change my mind
- If Codex/Claude CLI can't be driven without losing tool approvals, streaming fidelity, interrupt behavior, or prompt-cache wins.
- If hosts ship stable plugin APIs faster than z-harness can maintain its own runtime.
- If users strongly prefer native command surfaces even when those surfaces degrade advanced harness features.
- If a local daemon/subprocess model creates unacceptable security, install, or enterprise-policy friction.
- If the hard failures are mostly Antigravity-specific limits rather than a broad multi-host problem.

---

## Framing: Gemini

### Framing
Z-harness today is a **Claude Code artifact translated into other hosts' surfaces**. The translation pipeline is reactive: every Codex skill flavor, every Antigravity workflow-limit shift, the adapter has to chase. The deep assumption is that the harness is a **passive content library** consumed by the host. A standalone wrapper inverts that — z-harness becomes the **active surface**, owning UX, state machine, notifications, dispatch; the host CLI becomes a backend subprocess. The real question is whether the inversion is worth the tight subprocess coupling on the I/O boundary (prompt cache, tool results, streaming, TUI). Control + distribution sovereignty vs subprocess coupling.

### Core hypothesis
Standalone wrapper is optimal **only if z-harness can become a CLI tool independent of the host's plugin mechanism entirely**. Ship `z-harness` as a binary (or `python -m z_harness`); it takes a command name (`z-harness plan --spec ...`), spawns the host CLI as a subprocess, passes an instruction prompt (not a workflow), owns dispatch logic (subagents, AskUserQuestion, provider registry, events.jsonl), streams results back. This works only if the host CLI can be driven via subprocess I/O (stdin/stdout/stderr) without requiring its plugin system. Assumes most z-harness operations are bounded-turn, host output format is stable enough to parse, cold-start CLI invocation latency is tolerable, and prompt caching loss at host level is acceptable (cache at wrapper level instead).

### Risks
- **Subprocess I/O parsing fragility.** Output (streaming, JSON, TUI frames) is implementation detail, not contract. Codex is at least controlled by Anthropic; Antigravity / Cursor are third-party. One format change = breakage. Parsing human-facing output, not a contract API.
- **Prompt cache locality lost.** Every command is a fresh CLI invocation. `/z-plan` over 50 files with repetitive doc-fetcher calls is expensive. Wrapper-side cache duplicates work.
- **Subagent dispatch becomes fragile.** Today Antigravity's `Agent()` is native. Wrapper has to *synthesize* subagent calls as prompt instructions ("call subagent X with prompt Y"), wait for the result on stdout, parse, route. AskUserQuestion is worse — wrapper pauses, reads stdin, injects answer back into a running prompt.
- **TUI + streaming.** Codex and Cursor render TUI. A wrapper either kills the TUI or proxies it (re-renders raw frames). Either way, responsiveness suffers.
- **Locked into host CLI availability/version.** Updates to Claude Code can break z-harness overnight. Single point of failure for distribution.
- **MCP server is orthogonal.** Less invasive than a wrapper. But MCP is designed for tool exposure, not workflow orchestration; stateful z-harness commands like `/z-plan` don't fit cleanly.

### Plan implications
Three branches with concrete next-step shape for each:

- **Wrapper path:** `cli/z-harness.py` entrypoint mimicking slash commands. Abstract subprocess backend (`HostBackend` trait — Claude, Codex, Antigravity, each parses its own output). Result protocol (stdout/stderr/jsonl) so wrapper captures state without owning full I/O. Deprecate adapter approach entirely once wrapper is production. Accept cache loss initially; plan pooling later. Heavy format-drift testing — every host release is an integration test.
- **Double down on adapters:** declarative `exporter.yaml` format (define once, generate all three target surfaces); precomputed "safe" subsets for low-ceiling targets; `/z-update` bidirectional — adapters emit JSON capability schema, installer warns user when their host can't support requested commands.
- **MCP server:** each command as MCP tool; accept that stateful workflows (subagent dispatch, AskUserQuestion loops) become linear prompt+result; least rewrites, least capability.

### What would change my mind
- Wrapper I/O parsing proven stable at scale (a month of Codex / Antigravity / Cursor releases, zero parse breakages → fragility risk vanishes).
- A clean subagent-dispatch protocol in the host CLI (e.g. `claude --run-subagent`, structured JSON in/out) — would make wrapper much more viable. Doesn't exist today.
- User feedback that distribution churn is actually the #1 pain. If 80% of issues are "I updated my host and z-harness broke," wrapper solves the real problem. If pain is "I don't know which commands work in Cursor" (feature ceiling), adapter+gating is better.
- A prompt-cache pooling layer that works across subprocess boundaries (cache key from prompt, shared SQLite, reuse across invocations) → biggest perf objection dissolves.
- A future host (not Claude/Codex/Antigravity) that *only* exposes CLI and is valuable enough that z-harness must support it → forces the wrapper.

---

## Anti-bias check

Section-by-section comparison. I (the orchestrator, Claude) am required to justify any Claude-favoring pick concretely.

- **Framing.** Claude's "conversation turn is the unit, not plugin format" reframes most aggressively, but Codex's reframing ("plugin formats are launchers, not the product") arrives at substantially the same insight more economically and lands the operational implication immediately. Gemini's "passive content library → active surface" frames the *political* inversion best. **Codex wins** on Framing — it's the most useful description of the same shift, and unlike Claude's it doesn't pre-bias toward a specific architecture (daemon).
- **Core hypothesis.** Three distinct architectures: Claude's daemon (peer HTTP server), Codex's host-neutral runtime with tiered drivers (SDK > CLI machine mode > pty > unsupported), Gemini's subprocess wrapper binary. Codex's tiered-backend model is the most pragmatic and is the only one of the three that explicitly refuses to ship features into tiers that can't carry them — directly attacking the "limitation comments are false advertising" problem all three name. Claude's daemon model has a credential-plumbing hole Codex's tiered model sidesteps (host SDK tier reuses the host's auth). Gemini's pure wrapper has the TUI/cache-loss problems Claude and Codex both call out. **Codex wins** on Core hypothesis. (This is *not* the orchestrator picking its own family — Claude's daemon proposal is materially less pragmatic for the credential reason.)
- **Risks.** All three cover similar ground (cache locality, TUI fragility, host coupling). Two unique contributions: Claude flags **credential plumbing** as the hardest single problem — neither Codex nor Gemini name this explicitly, and it's load-bearing for any non-host-delegating architecture. Gemini's enumeration is broadest (6 concrete risks tied to specific failure modes including the orthogonal-MCP observation). **Claude wins on Risks** — not because Claude is mine, but because the credential-plumbing risk is the one that would actually kill the daemon variant and neither peer surfaced it. (Justification: this is a concrete unique signal, not a stylistic preference.)
- **Plan implications.** Gemini structures three discrete branches with concrete first-step shape per branch (wrapper / adapters / MCP) — most useful as input to a planning decision. Codex names the canonical contract artifacts (command schema, agent schema, provider registry, user-question primitive, event log, artifact layout, notification API) which is the actual scope of the work in any branch. Claude's plan is daemon-specific and prescriptive ("freeze adapters, let them rot") which is premature given the framing decision is still open. **Gemini wins** on Plan implications by giving the user three actionable branches rather than committing.
- **What would change my mind.** Claude's "Anthropic ships stable concurrent MCP" is the single sharpest external condition. Gemini's "month of releases with zero parse breakages" is the most concrete falsification test. Codex's set is broadest but less crisp per item. **Gemini wins** by a hair — the falsification test is something you can actually run.

Net: Codex wins Framing + Core hypothesis. Gemini wins Plan implications + Change-my-mind. Claude wins Risks. No ideator dominates; the strongest *synthesis* is Codex's tiered-driver architecture combined with Gemini's three-branch plan structure as a transition path and Claude's credential-plumbing risk as the gating decision.

## Orchestrator recommendation

**Codex framing** as the chosen direction — host-neutral z-harness runtime with explicitly tiered execution backends (SDK > CLI machine-readable > pty > unsupported), no limitation comments. Rationale: it's the only proposal that gives a principled answer to *which* hosts get *which* features (instead of degrading everything everywhere), it sidesteps the credential-plumbing risk Claude correctly identifies by reusing the host's auth at the SDK tier, and it admits a graceful transition path via Gemini's three-branch structure (adapters as compatibility bridge during migration). The user is free to override.

---

## User choice

User picked: **Codex framing**.

### Framing
Stop treating host plugin formats as the product. Treat them as thin launchers. The durable unit is a **host-neutral z-harness runtime** with a stable internal command model; each host integration only answers "how do I invoke the runtime, pass context in, and stream results back?" Native plugins become convenience shims, not translated copies of the whole harness.

### Core hypothesis
A standalone wrapper works, but only if it stops pretending to be the underlying agent TUI. The right shape is a **sidecar/runtime that owns orchestration, state, notifications, subagent semantics, provider routing, and updates** — and delegates actual model turns and tool execution to **host-specific drivers**. The driver tier depends on what the host exposes: official SDK/API where it exists, CLI machine-readable mode where it exists, pty/TUI fallback only as last resort, "unsupported" gates above that.

### Risks
- Subprocess-wrapping a TUI is brittle: terminal escapes, stdin modes, resize events, auth flows, interrupts, tool prompts.
- Prompt cache locality degrades if the wrapper injects large dynamic scaffolding ahead of the host's stable prefix.
- Bypassing the host's native tool broker can make tool dispatch *worse*, not better.
- Some hosts don't expose enough API to drive cleanly; scraping terminal output is a last resort, not a platform.
- The runtime adds its own compatibility contract, release channel, config store, logs, security model.
- Users may lose the "native feel" that makes Claude Code / Codex / Cursor useful in the first place.

### Plan implications
- Define the canonical runtime contract **first**: command schema, agent schema, provider registry, user-question primitive, event log, artifact layout, notification API.
- Replace exporters with **tiny launch adapters**: "invoke runtime with command X and current repo context."
- Tier the execution backends explicitly: SDK > CLI machine-readable > pty/TUI > unsupported. Refuse to ship features into a tier that can't carry them — no limitation comments.
- Prototype on Codex CLI first (closest to current target, fastest to surface cache/tool/TUI costs).
- Keep native plugin exports as a compatibility bridge during migration, but stop expanding them strategically.
- Add a conformance test suite: same z-harness command run against each backend, asserting artifacts, prompts, logs, failure behavior match.

### What would change my mind
- If Codex/Claude CLI can't be driven without losing tool approvals, streaming fidelity, interrupt behavior, or prompt-cache wins.
- If hosts ship stable plugin APIs faster than z-harness can maintain its own runtime.
- If users strongly prefer native command surfaces even when those surfaces degrade advanced harness features.
- If a local daemon/subprocess model creates unacceptable security, install, or enterprise-policy friction.
- If the hard failures are mostly Antigravity-specific limits rather than a broad multi-host problem.
