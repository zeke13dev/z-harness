# Vendored: pi subagent extension

These files are copied verbatim from the pi coding-agent npm package:

    @earendil-works/pi-coding-agent/examples/extensions/subagent/

- **Pinned version:** 0.78.1
- **Files:** `index.ts`, `agents.ts`
- **Why vendored:** so the generated pi export tree is self-contained and the live symlinks in
  `~/.pi/agent/extensions/subagent/` point at stable z-harness paths (the npm path
  embeds the Node version and moves on every `pi update` / node bump).

## Refreshing after a pi upgrade

    PKG=$(npm root -g)/@earendil-works/pi-coding-agent
    cp "$PKG/examples/extensions/subagent/index.ts" index.ts
    cp "$PKG/examples/extensions/subagent/agents.ts" agents.ts
    # bump the pinned version above

Run `pi /reload` after refreshing to hot-reload the extension.
