README.md:283:├── agents/
README.md:293:│   └── remote-runner.md

codex
**Findings**

1. **INDEX/doc-fetcher mismatch.** Existing `docs/llm/INDEX.json` uses `source_file`, not `source_files`, and `doc-fetcher` reads `docs/llm/<slug>.json`. If you add `external-lookup-agent` to INDEX, you also need `docs/llm/external-lookup-agent.json`, or doc-fetcher can select a slug whose body file does not exist.

2. **Docs phase is incomplete.** Adding an agent should update either `docs/llm/agents.json` / `docs/human/agents.md`, or the plan should explicitly say not to. README alone is not the current two-tier docs surface for agents.

3. **`qt-bot-remote` is a blocker unless specified.** The plan says use that skill, but it is not in the available skill list here. A fresh implementer needs either the actual skill name/path, or concrete deposit commands/host/path/expected remote agent directory.

4. **qt-bot client invocation is under-specified.** “Resolve at deposit time” is acceptable only if the PLAN includes the discovery checklist: inspect repo, find read-only market/ticker command, verify paper/demo env, record exact command examples in the agent.

5. **Blocklist has holes.** `curl -d/--data/--form` mutates without `-X POST`. `gh api --method POST|PATCH|PUT|DELETE` also mutates without `gh pr create`. Add those.

6. **Blocklist prose has a Markdown/regex bug.** The eval/shell regex includes a raw backtick near ``|`\s*\|\s*sh``; that will likely render/break incorrectly. Put blocklist regexes in fenced code blocks.

7. **“Bash commands verbatim” conflicts with truncation.** SPEC says record verbatim; agent says truncate args >120 chars. Pick one. For auditability, prefer verbatim in `commands`, with only display truncation in `Answer`.

8. **Smoke tests need definition.** “Validate external-lookup with one real lookup” is not mechanically testable from this repo unless the implementer can actually spawn the subagent with WebFetch/WebSearch. Add fallback static checks: frontmatter parse, required section strings, INDEX body file exists, cache gitignore exists.

**Answers**

1. **Not fully implementable yet.** Main ambiguity is qt-bot deposit/client discovery and the INDEX/body-file mismatch.

2. **Phases are close but incomplete.** Add: create `docs/llm/external-lookup-agent.json` or remove that INDEX entry; update `agents.json`/`docs/human/agents.md`; define qt-bot remote discovery/deposit steps; add static smoke checks.

3. **Load-bearing assumptions:** Claude-style `WebFetch/WebSearch` tool names are valid in the target agent runtime; `doc-fetcher` tolerates new concept shape; remote qt-bot access and path are known; qt-bot already has a read-only Kalshi inspection command; auth-bearing fetches will not require secret handling beyond Bash.

4. **Most fragile part:** security is model-honored only while granting Bash plus network. Tighten mutation detection and make provenance truly auditable. Also, stale cache handling needs exact timestamp source: cache mtime vs embedded API timestamp.
tokens used
65,930
**Findings**

1. **INDEX/doc-fetcher mismatch.** Existing `docs/llm/INDEX.json` uses `source_file`, not `source_files`, and `doc-fetcher` reads `docs/llm/<slug>.json`. If you add `external-lookup-agent` to INDEX, you also need `docs/llm/external-lookup-agent.json`, or doc-fetcher can select a slug whose body file does not exist.

2. **Docs phase is incomplete.** Adding an agent should update either `docs/llm/agents.json` / `docs/human/agents.md`, or the plan should explicitly say not to. README alone is not the current two-tier docs surface for agents.

3. **`qt-bot-remote` is a blocker unless specified.** The plan says use that skill, but it is not in the available skill list here. A fresh implementer needs either the actual skill name/path, or concrete deposit commands/host/path/expected remote agent directory.

4. **qt-bot client invocation is under-specified.** “Resolve at deposit time” is acceptable only if the PLAN includes the discovery checklist: inspect repo, find read-only market/ticker command, verify paper/demo env, record exact command examples in the agent.

5. **Blocklist has holes.** `curl -d/--data/--form` mutates without `-X POST`. `gh api --method POST|PATCH|PUT|DELETE` also mutates without `gh pr create`. Add those.

6. **Blocklist prose has a Markdown/regex bug.** The eval/shell regex includes a raw backtick near ``|`\s*\|\s*sh``; that will likely render/break incorrectly. Put blocklist regexes in fenced code blocks.

7. **“Bash commands verbatim” conflicts with truncation.** SPEC says record verbatim; agent says truncate args >120 chars. Pick one. For auditability, prefer verbatim in `commands`, with only display truncation in `Answer`.

8. **Smoke tests need definition.** “Validate external-lookup with one real lookup” is not mechanically testable from this repo unless the implementer can actually spawn the subagent with WebFetch/WebSearch. Add fallback static checks: frontmatter parse, required section strings, INDEX body file exists, cache gitignore exists.

**Answers**

1. **Not fully implementable yet.** Main ambiguity is qt-bot deposit/client discovery and the INDEX/body-file mismatch.

2. **Phases are close but incomplete.** Add: create `docs/llm/external-lookup-agent.json` or remove that INDEX entry; update `agents.json`/`docs/human/agents.md`; define qt-bot remote discovery/deposit steps; add static smoke checks.

3. **Load-bearing assumptions:** Claude-style `WebFetch/WebSearch` tool names are valid in the target agent runtime; `doc-fetcher` tolerates new concept shape; remote qt-bot access and path are known; qt-bot already has a read-only Kalshi inspection command; auth-bearing fetches will not require secret handling beyond Bash.

4. **Most fragile part:** security is model-honored only while granting Bash plus network. Tighten mutation detection and make provenance truly auditable. Also, stale cache handling needs exact timestamp source: cache mtime vs embedded API timestamp.
