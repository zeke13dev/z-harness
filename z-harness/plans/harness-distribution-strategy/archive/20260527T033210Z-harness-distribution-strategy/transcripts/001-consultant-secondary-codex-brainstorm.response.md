**(1) Framing**

Stop treating host plugin formats as the product. Treat them as thin launchers. The durable unit should be a host-neutral z-harness runtime with a stable internal command model, and each host integration should only answer: "How do I invoke the runtime, pass context in, and stream results back?" Native plugins become convenience shims, not translated copies of the whole harness.

**(2) Core hypothesis**

A standalone wrapper can work, but only if it avoids pretending to be the underlying agent TUI. The right shape is probably a sidecar/runtime that owns orchestration, state, notifications, subagent semantics, provider routing, and update mechanics, while delegating actual model turns/tool execution to host-specific drivers. For Codex/Claude CLI this may mean subprocess control; for Cursor/Antigravity it may mean a local daemon plus minimal prompt/plugin entrypoints.

**(3) Risks**

- Subprocess-wrapping a rich TUI is brittle: terminal escape handling, stdin modes, resize events, auth flows, interrupts, and tool prompts can all become failure surfaces.
- Prompt cache locality may degrade if the wrapper injects large dynamic scaffolding or prevents the underlying CLI from seeing stable prompt prefixes.
- Tool dispatch may become worse if the host's native tool broker is bypassed instead of reused.
- Hosts may not expose enough API surface to drive them cleanly; scraping terminal I/O is a last resort, not a platform.
- A standalone runtime adds its own compatibility contract, release channel, config store, logs, and security model.
- Users may lose the "native feel" that makes Claude Code/Codex/Cursor useful in the first place.

**(4) Plan implications**

- Define a canonical z-harness runtime contract first: command schema, agent schema, provider registry, user-question primitive, event log, artifact layout, and notification API.
- Replace exporters with tiny launch adapters where possible: "invoke runtime with command X and current repo context."
- Split execution backends into tiers: official SDK/API, CLI machine-readable mode, pty/TUI fallback, unsupported.
- Prototype on Codex CLI before harder hosts because it is closest to the current target and can reveal cache/tool/TUI costs quickly.
- Keep native plugin export as a compatibility bridge during migration, but stop expanding it as the strategic path.
- Add a conformance test suite that runs the same z-harness command against each backend and checks artifacts, user prompts, logs, and failure behavior.

**(5) What would change my mind**

- If Codex/Claude CLI cannot be driven without losing tool approvals, streaming fidelity, interrupt behavior, or prompt cache wins.
- If hosts expose stable plugin APIs faster than z-harness can maintain a runtime.
- If users strongly prefer native command surfaces even when those surfaces degrade advanced harness features.
- If a local daemon/subprocess model creates unacceptable security, install, or enterprise-policy friction.
- If the hard failures are mostly Antigravity-specific limits rather than a broad multi-host distribution problem.
