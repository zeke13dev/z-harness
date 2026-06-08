# z-harness fanout rules (pi)

These rules govern how you delegate work to subagents via the `subagent` tool. They mirror the z-harness "doc-fetcher first, explore for the gaps" discipline.

## doc-fetcher first, explore for gaps

Before any broad codebase exploration in a repo that has a `docs/llm/INDEX.json`:

1. **Dispatch `doc-fetcher` first.** Use the `subagent` tool:
   ```
   subagent { "agent": "doc-fetcher",
              "task": "query: <one-sentence question>\nrepo_root: <abs path>\ndepth: standard" }
   ```
   `depth`: `summary` (1 para) | `standard` (2-3 paras + file:line) | `deep` (≤200-line source excerpts).

2. **Read its return before exploring.** If `doc-fetcher` already answers the question, skip explore entirely.

3. **Only explore the gap.** If `doc-fetcher` returns `STATUS: no_docs`, `no_match`, or `partial`, dispatch `explore` for just the part the docs did not cover.

Never read `docs/llm/INDEX.json` or `docs/llm/<slug>.json` yourself from the main thread — that is exactly what `doc-fetcher` is for. Reading them directly wastes the point.

If `doc-fetcher` returns a `DRIFT WARNING`, surface it to the user.

## explore fan-out

When a question spans several subsystems, run multiple `explore` agents **in parallel** rather than one sweeping search:

```
subagent { "tasks": [
  { "agent": "explore", "task": "Find where X is defined and wired in <repo>" },
  { "agent": "explore", "task": "Find all callers of Y in <repo>" }
] }
```

Parallel mode caps at 8 tasks, 4 concurrent. Each `explore` agent is read-only and returns `path:line` conclusions, not file dumps — keep your own context lean by delegating the search and keeping only the result.

## Notes

- Agents run as isolated `pi` processes. They inherit your default model (`deepseek-v4-pro`) unless their definition pins one. There is no cheap Haiku tier here, so the win from fan-out is **context isolation**, not cost — delegate broad reads you don't want polluting the main thread.
- `explore` locates; it does not audit or judge. For review/correctness work, reason in the main thread or use a dedicated reviewer agent.
