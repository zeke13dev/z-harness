<!-- SURFACE-MAPPING: shared command fragment. Include from command specs with the repo-root marker for _fragments/surface-mapping.md. -->

## Shared surface mapping contract

Surface mapping is a bounded discovery layer used by existing understanding and report commands. It produces neutral source-fact context only: no user-facing prose, implementation recommendations, audit findings, planning decisions, sibling command invocation, or new command surface.

### Modes and callers

- `repo` — broad repository/package/module orientation.
- `symbol` — one unqualified symbol, type, module, or similarly named surface.
- `diff` — files and hunks touched by a PR, range, base ref, or worktree diff.
- Valid callers: `z-explain`, `z-learn`, `z-report`, `z-explore`.

### Status vocabulary

Every persisted `surface-map.json` uses exactly one of these statuses:

- `ok` — complete within caps.
- `partial` — useful map, but one or more intended facets are missing.
- `not_found` — no plausible surface was found.
- `ambiguous` — multiple unrelated surfaces matched; caller should ask, narrow, or route.
- `too_broad` — target exceeds safe caps; caller should narrow or route.
- `truncated` — hard caps cut output; show only as bounded context, never as complete coverage.
- `error` — mapper failed; caller degrades to its existing behavior and surfaces a warning.

### Shared JSON schema

Persist the raw payload as `surface-map.json` in the command's archive when a map is kept.

```json
{
  "schema_version": 1,
  "generated_at": "<ISO-8601 UTC>",
  "mode": "repo|symbol|diff",
  "caller": "z-explain|z-learn|z-report|z-explore",
  "status": "ok|partial|not_found|ambiguous|too_broad|truncated|error",
  "target": {
    "raw": "<original target>",
    "repo_root": "<absolute path>",
    "inferred_kind": "repo|directory|module|symbol|type|free_text|diff"
  },
  "caps": {
    "max_primary_files": 10,
    "max_refs": 100,
    "max_bytes": 200000
  },
  "stats": {
    "files_scanned": 0,
    "candidate_files": 0,
    "refs": 0,
    "truncated": false
  },
  "primary": [
    {
      "path": "path/to/file.ext",
      "symbol": "optional symbol name",
      "kind": "entrypoint|module|type|function|config|test|doc|artifact|changed_file",
      "relation": "defines|exports|entrypoint|implements|calls|uses|tests|documents|changes",
      "line_start": 1,
      "line_end": 1,
      "citations": ["path/to/file.ext:1"],
      "reason": "why this surface is primary",
      "confidence": "high|medium|low"
    }
  ],
  "related": [],
  "clusters": [
    {
      "id": "C1",
      "label": "short label",
      "paths": ["path/to/file.ext"],
      "summary": "neutral, non-recommendation summary"
    }
  ],
  "suggested_reads": [
    {
      "path": "path/to/file.ext",
      "ranges": ["1-80"],
      "reason": "why to read this first"
    }
  ],
  "warnings": [],
  "tried_strategies": []
}
```

Required top-level fields are `schema_version`, `generated_at`, `mode`, `caller`, `status`, `target`, `caps`, `stats`, `primary`, `related`, `clusters`, `suggested_reads`, `warnings`, and `tried_strategies`. `target` must include `raw`, `repo_root`, and `inferred_kind`; `caps` must include `max_primary_files`, `max_refs`, and `max_bytes`; `stats` must include `files_scanned`, `candidate_files`, `refs`, and `truncated`.

### Cap policy

Default caps are `max_primary_files=10`, `max_refs=100`, and `max_bytes=200000`. Producers must stop at caps and set `too_broad` or `truncated` rather than scanning unboundedly or claiming completeness. Callers may pass tighter caps for small contexts; they must not silently raise caps to make a broad request fit. A map with `stats.truncated=true` is safe only as a bounded reading guide.

### Repo Explore facets

For repo orientation in commands that use Explore, dispatch the facets in one parallel batch and require file:line citations with no recommendations:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this repo-orientation Explore dispatch requirement and skip the live Explore batch if subagents are unavailable. Existing command behavior must continue with a warning. -->

1. **Top-level structure** — directories, package/build/config files, docs locations, and test locations.
2. **Entry points and runtime surfaces** — CLI commands, scripts, package entrypoints, service/process starts, and exported command specs.
3. **Key modules and seams** — major subsystems, shared helpers, generated artifacts, and stateful boundaries.

The command orchestrator merges cited findings from these facets into the shared schema. Uncited Explore claims are not source facts; ignore them until direct reads verify the claim.

### Failure semantics

Surface mapping is an enhancement, not a dependency for baseline command behavior. On `error`, log/surface a warning and continue with the command's existing grounding path. On `too_broad`, `truncated`, `ambiguous`, or multiple unrelated clusters, show a bounded result only if it can remain honest; otherwise ask the user to narrow. Explicit surface-only requests may halt for narrowing, but ordinary explain/learn/report flows degrade gracefully.

### Caller responsibilities

- `/z-explain` owns one-shot rendering. It may use `repo` Explore facets or deterministic `symbol` preflight, then still returns exactly one cited answer at one lens.
- `/z-learn` owns progressive teaching. It may use the same repo facets for initial grounding, archives raw `surface-map.json`, stages only compact metadata, and teaches one chunk per turn.
- `/z-report` owns context-grounded reporting. It uses the JSON contract through deterministic context assembly; report prose must render from assembled `context.json` fields, not ad hoc discovery.
- `/z-explore` owns depth-scaled terrain discovery. Quick mode may use repo facets for fast orientation; standard mode persists `surface-map.json` alongside `EXPLORE.md`; deep mode produces MAP.md-compatible terrain. Depth determines whether the map is inline, persisted, or produces full cross-LLM critique.
- All callers preserve the raw map separately from user prose, cite direct source lines for factual claims, expose warnings/cap status, and avoid treating a surface map as an audit, plan, or complete codebase atlas.
