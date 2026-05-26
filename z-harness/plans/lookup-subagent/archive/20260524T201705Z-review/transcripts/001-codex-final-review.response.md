2026-05-24T20:18:35.215195Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-24T20:18:35.215837Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-24T20:18:35.215843Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e5ba3-b216-7512-b563-a65b017fbbcd
--------
user
MODE: final-review-2pronged

## Lookup-Subagent Implementation: Cross-Task Faithfulness & Spec Sufficiency

### Background

The lookup-subagent plan introduces two subagents sharing one published output contract:
- `external-lookup` (haiku, z-harness) — generic WebFetch/WebSearch/Bash lookup with verb-blocklist
- `qt-market-lookup` (sonnet, staged for qt-bot) — Kalshi/weather-market enrichment

**Approved decision D2:** user override on Bash inclusion despite exfiltration risk (verb-blocklist mitigation). **Tasks T011/T012 are REMOTE-SKIPPED** (require qt-bot-remote skill on zeke-pc); **they do NOT appear in the cumulative.diff** — only T001-T010 are implemented.

### Inputs

**SPEC.md** commits to:
- Verb-blocklist covering six categories: DB writes, git mutations, gh API mutations, HTTP mutations (curl-d/wget-postdata), eval/pipe, filesystem destructive
- Contract lives at `docs/llm/lookup-contract.json` (canonical)
- Two-tier docs: LLM JSON (`docs/llm/lookup-contract.json`, `docs/llm/external-lookup-agent.json`) + human (`docs/human/lookup-contract.md`)
- INDEX.json entries use schema with keys `source_files` (plural), `last_updated`, `confidence`, `depends_on`, `consumed_by`, `summary`
- Concept JSON schema (`docs/llm/*.json`) uses `key_invariants` / `key_files` instead of SPEC's literal `source_files`/`invariants` (T001 retry fixed this)

**cumulative.diff** (8 files, 580 insertions):
1. README.md — external-lookup row added ✓
2. agents/external-lookup.md — 151 lines (full agent) ✓
3. docs/human/lookup-contract.md — 183 lines (human tier) ✓
4. docs/llm/INDEX.json — two new entries (lookup-contract, external-lookup-agent) ✓
5. docs/llm/external-lookup-agent.json — 19 lines (LLM tier concept) ✓
6. docs/llm/lookup-contract.json — 18 lines (contract JSON) ✓
7. z-harness/lookup-cache/.gitignore — 2 lines ✓
8. z-harness/plans/lookup-subagent/staging/qt-market-lookup.md — 175 lines (staged, not deployed) ✓

### Questions for Codex

**Prong A — Faithfulness to SPEC.md:**

1. **Verb-blocklist completeness:** SPEC §File 2 step 4 enumerates six categories (DB, git, gh, HTTP, eval-pipe, filesystem destructive). In cumulative.diff `agents/external-lookup.md` L89-L114, are all six patterns present and correctly formed as Python regexes?

2. **INDEX.json schema:** SPEC §File 4 says to use the **existing** schema from INDEX.json. The diff shows:
   - lookup-contract entry has keys: `slug`, `source_files` (plural), `last_updated`, `confidence`, `depends_on`, `consumed_by`, `summary`
   - external-lookup-agent entry has same keys
   
   Does this match the **existing** INDEX schema shown in the INDEX.json snapshot, and are there any inconsistencies across the two new entries?

3. **Concept JSON schema drift:** The diff shows `docs/llm/lookup-contract.json` and `docs/llm/external-lookup-agent.json` use `key_invariants` / `key_files` (not `invariants` / `source_files`). Is this the corrected T001 retry schema that matches other existing concept JSONs like `providers-registry.json`? SPEC §File 4b says "matches existing concept JSONs" — confirm alignment.

4. **Contract reference consistency:** 
   - agents/external-lookup.md L65 cites `docs/llm/lookup-contract.json` ✓
   - docs/human/lookup-contract.md L366-369 cites it via doc-fetcher ✓
   - qt-market-lookup.md L508 cites `<z-harness-plugin>/docs/llm/lookup-contract.json` with fallback
   
   Any dangling references or paths that don't exist?

5. **README row faithfulness:** cumulative.diff shows README.md line 9 matches `agents/external-lookup.md` frontmatter description verbatim?

6. **qt-market-lookup verb-blocklist:** cumulative.diff staging/qt-market-lookup.md L536-L583 — does it inherit ALL of external-lookup's patterns (DB, git, gh, HTTP, eval) PLUS the trading-specific patterns (place_order, cancel_order, buy, sell, etc.)? Are the trading patterns correctly formed?

**Prong B — Spec Sufficiency & Gaps:**

1. **T001 Retry Schema Correction:** SPEC File 4 initially says `source_files`/`invariants` as literal JSON keys, but T001 implemented it using `key_invariants`/`key_files` (per existing JSONs). Should SPEC §File 4b be amended to call out this correction?

2. **Edge case — cache-key collision:** SPEC §File 2 step 5 says normalized query = lowercase + collapse whitespace + strip. Two distinct queries could hash to the same SHA256 after normalization (unlikely but possible). Should SPEC address cache-key format or versioning?

3. **Confidence degradation ambiguity:** SPEC §File 2 step 6 says "if cache is >24h old, mark confidence: low". But SPEC does not define what happens if:
   - A fresh fetch and a stale cache both exist (which one wins?)
   - Cache freshness conflicts with source freshness (e.g. a 1h-old cache of a 5-day-old web page)?
   
   Should SPEC clarify cache-vs-source precedence?

4. **qt-market-lookup paper-env-var enforcement:** SPEC §File 3 says the agent must reject commands that omit `<PAPER_ENV_VAR>=paper`. But cumulative.diff staging/qt-market-lookup.md L585-L589 references `<PAPER_ENV_VAR>` as a placeholder to be substituted at T011 deposit time. What prevents the Kalshi client from being invoked without the prefix if deposit never happens (T011/T012 are remote-skipped)?

5. **Provenance `commands:` truncation rule:** SPEC §File 2 step 8 says "verbatim" in provenance, "display-side truncation … only in Answer". But if a command is 2 KB long (e.g. a massive `jq` filter), recording it verbatim pushes the response over 3 KB. Should SPEC clarify the 3 KB cap rule: is it hard (reject, drop to raw-artifact), or soft (truncate commands)?

6. **No cache expiry policy:** SPEC does not address: how long should entries in `z-harness/lookup-cache/` be kept? Should implementers / users garbage-collect them? Should the agent refuse if cache is too old vs. just degrade confidence?

7. **Agent lifecycle gap:** SPEC defines contract + agent file + docs, but does not address:
   - How is the agent dispatched (Agent(...) call syntax, model tier, tool whitelist)?
   - What happens if main thread needs to force a fresh (non-cached) lookup?
   - What is the retry budget if WebFetch + WebSearch both fail?

---

**Output: For each finding, cite source (e.g. agents/external-lookup.md:L63 or SPEC.md §File 2) and severity (blocker | major | minor). Keep output <4 KB.**

codex
I’ll verify the implemented files against the stated contract and the repo’s existing docs schema, then separate hard faithfulness issues from spec gaps.
exec
/bin/zsh -lc 'git status --short' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
 M README.md
 A agents/external-lookup.md
 A docs/human/lookup-contract.md
 M docs/llm/INDEX.json
 A docs/llm/external-lookup-agent.json
 A docs/llm/lookup-contract.json
 M z-harness/archive/orchestration/events.jsonl
 M z-harness/archive/tasks/T001/events.jsonl
 M z-harness/archive/tasks/T001/review.prompt.md
 M z-harness/archive/tasks/T001/review.response.md
 M z-harness/archive/tasks/T002/events.jsonl
 M z-harness/archive/tasks/T003/review.prompt.md
 M z-harness/archive/tasks/T003/review.response.md
 A z-harness/lookup-cache/.gitignore
 M z-harness/metrics.jsonl
 A z-harness/plans/lookup-subagent/staging/qt-market-lookup.md
?? z-harness/archive/20260524T184104Z-lookup-subagent/
?? z-harness/archive/20260524T184351Z-lookup-subagent/
?? z-harness/archive/20260524T190609Z-lookup-subagent/
?? z-harness/archive/consult-lookup-architecture/
?? z-harness/archive/consults/
?? z-harness/archive/lookup-subagent-brainstorm/
?? z-harness/archive/lookup-subagent-review/
?? z-harness/archive/tasks/T002/review.prompt.md
?? z-harness/archive/tasks/T002/review.response.md
?? z-harness/plans/lookup-subagent/BRAINSTORM.md
?? z-harness/plans/lookup-subagent/PLAN.md
?? z-harness/plans/lookup-subagent/SPEC.md
?? z-harness/plans/lookup-subagent/TASKS.md
?? z-harness/plans/lookup-subagent/archive/

exec
/bin/zsh -lc "rg --files | rg '("'^SPEC.md$|cumulative.diff$|agents/external-lookup.md$|docs/llm/(INDEX|lookup-contract|external-lookup-agent|providers-registry)'"\\.json"'$|docs/human/lookup-contract.md$|qt-market-lookup.md$|README.md$)'"'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
exports/agy/README.md
README.md
exports/codex/README.md
exports/cursor/README.md
agents/external-lookup.md
docs/llm/INDEX.json
docs/llm/providers-registry.json
docs/llm/external-lookup-agent.json
docs/llm/lookup-contract.json
docs/human/lookup-contract.md
z-harness/plans/portable-harness/archive/20260524T174504Z-review/cumulative.diff
z-harness/plans/mr-style-reviewer/archive/20260524T004459Z-review/cumulative.diff
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/cumulative.diff
z-harness/plans/lookup-subagent/staging/qt-market-lookup.md
z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff
z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff
z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff
z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff

codex
I found the lookup-subagent plan artifacts under `z-harness/plans/lookup-subagent/` and the staged qt agent. I’m reading the concrete line ranges now, including existing schema examples for comparison.
exec
/bin/zsh -lc "nl -ba agents/external-lookup.md | sed -n '1,170p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	---
     2	name: external-lookup
     3	description: Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blocklist.
     4	model: haiku
     5	tools: WebFetch, WebSearch, Bash, Read, Grep, Glob
     6	---
     7	
     8	## Mission
     9	
    10	You are a fresh-context lookup worker. Main thread delegates noisy retrieval to you so it doesn't pollute its context. Return ≤3 KB STATUS-headed Markdown per `docs/llm/lookup-contract.json`. All external retrieval — web docs, public API endpoints, paginated JSON responses, library docs outside training cutoff — is your responsibility. Synthesize; never dump raw HTML or JSON into `## Answer`.
    11	
    12	## Output contract
    13	
    14	Every response begins with exactly one STATUS line, followed by the four Markdown sections in fixed order:
    15	
    16	```
    17	STATUS: <ok|partial|refused>
    18	
    19	## Answer
    20	<synthesis of retrieved information; ≤2 KB; no raw HTML/JSON/YAML>
    21	
    22	## Provenance
    23	- query: <normalized query string>
    24	- tools_used: <comma-separated subset of {WebFetch, WebSearch, Bash, Read}>
    25	- sources: <bulleted sub-list of url:section or path:line>
    26	- freshness_ts: <ISO 8601 UTC, e.g. 2026-05-24T18:41:00Z>
    27	- confidence: <high | medium | low>
    28	- commands: <bulleted sub-list of verbatim Bash commands, OR "n/a" if Bash unused>
    29	
    30	## Unresolved
    31	<gaps, partial results, pagination truncation, stale cache warnings; or "none" if fully resolved>
    32	
    33	## Raw artifact pointer
    34	<path to z-harness/lookup-cache/<sha256>.raw if raw artifact was written; omit section if not used>
    35	```
    36	
    37	The canonical version of this contract is `docs/llm/lookup-contract.json`. If anything here conflicts with that file, `lookup-contract.json` wins.
    38	
    39	**STATUS values:**
    40	- `ok` — answer believed reliable.
    41	- `partial` — retrieval completed but incomplete OR ambiguous. Includes: 4xx (incl. 429 rate-limit), 5xx, no-results-found, pagination-truncation, source-cache-stale. Body explains gaps in `## Unresolved`.
    42	- `refused` — verb-blocklist matched OR explicit mission-scope violation. `## Answer` first line MUST be `Refused: <category> — <detail>` where category ∈ {`mutation_blocked`, `out_of_scope`, `auth_missing`}.
    43	
    44	## Tool guidance
    45	
    46	- Prefer `WebFetch` for known URLs of public docs or pages.
    47	- Prefer `WebSearch` to discover URLs when only a topic is given.
    48	- Use `Bash` for endpoints WebFetch cannot handle: `gh api`, `curl` with custom headers / query params / auth, `jq` filtering of returned JSON.
    49	- Use `Read` / `Grep` / `Glob` to inspect local files when the query references repo-local content.
    50	
    51	## Verb-blocklist
    52	
    53	Before running any Bash command, grep the literal command string (case-insensitive) against every pattern below. Any match → emit `STATUS: refused` with `## Answer` body:
    54	
    55	```
    56	Refused: mutation_blocked — matched pattern '<pattern>' in command '<verbatim cmd>'
    57	```
    58	
    59	Do not execute the command.
    60	
    61	```
    62	# DB writes (verb anywhere AND via -f / redirect)
    63	INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|VACUUM
    64	psql\s+[^|]*\s-f\s|sqlite3\s+[^|]*\s*<|>\s*[^|>\s]+\.(db|sqlite|sqlite3)\b
    65	
    66	# Git mutations
    67	git\s+push|git\s+commit|git\s+reset\s+--hard|git\s+rebase\s+--|git\s+stash\s+drop|git\s+branch\s+-D|git\s+checkout\s+--
    68	
    69	# GitHub mutations (including gh api with mutating methods)
    70	gh\s+pr\s+(create|merge|close|edit)|gh\s+issue\s+(create|close|edit)|gh\s+release\s+create|gh\s+api\s+[^|]*--method\s+(POST|PUT|PATCH|DELETE)
    71	
    72	# HTTP mutations
    73	curl[^|]*(-X|--request)\s*(POST|PUT|DELETE|PATCH)
    74	curl[^|]*(-d|--data|--data-raw|--data-binary|-F|--form)\b
    75	wget\s+[^|]*--(post-data|method)\b
    76	\bhttpie\s+(POST|PUT|DELETE|PATCH)\b
    77	\bhttp\s+(POST|PUT|DELETE|PATCH)\b
    78	
    79	# Eval / piped interpreters (NOTE: bare $(...) and backticks NOT blocked — too disruptive; rely on pipe-to-interpreter detection)
    80	\beval\b|\bsh\s+-c\b|\bbash\s+-c\b
    81	\|\s*(sh|bash|zsh|python|python3|perl|ruby|node)\b
    82	<\s*\(.*\)\s*\|\s*(sh|bash|python|perl|ruby|node)\b
    83	\b(perl|ruby|node|python|python3)\s+-e\b
    84	
    85	# Filesystem destructive
    86	rm\s+-(rf|fr|Rf|fR)\b|>\s*/dev/(sd|nvme|disk)
    87	```
    88	
    89	Implementation note: each pattern is a Python regex tested with `re.IGNORECASE` against the joined argv string. Compile once; test before every `Bash` invocation.
    90	
    91	## Budget
    92	
    93	Total response (STATUS line + all sections + whitespace) ≤3 KB. Aim for ≤2 KB synthesis inside `## Answer` so Provenance + Unresolved have headroom.
    94	
    95	If a raw artifact exceeds the budget, write it to `z-harness/lookup-cache/<sha256-of-normalized-query>.raw` and point at it in `## Raw artifact pointer`. The cache dir is gitignored; create it with `mkdir -p` if missing.
    96	
    97	**Normalized query** = lowercase + collapse all internal whitespace runs to one space + strip leading/trailing whitespace.
    98	
    99	## Freshness discipline
   100	
   101	`freshness_ts` is the **retrieval timestamp** in UTC ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`) — not the source document's own last-modified date.
   102	
   103	If a source was loaded from cache and the cache file is >24h old (compare mtime), mark `confidence: low` and call it out in `## Unresolved`.
   104	
   105	## Refusal modes
   106	
   107	STATUS values are mutually exclusive:
   108	
   109	- `ok` — answer believed reliable.
   110	- `partial` — retrieval completed but incomplete OR ambiguous. Body explains gaps in `## Unresolved`.
   111	- `refused` — verb-blocklist matched OR explicit mission-scope violation (e.g. user asked to place a trade). Body's first `## Answer` line MUST be `Refused: <category> — <detail>` where category ∈ {`mutation_blocked`, `out_of_scope`, `auth_missing`}.
   112	
   113	## Provenance section format
   114	
   115	```markdown
   116	## Provenance
   117	- query: <normalized query string>
   118	- tools_used: <comma-separated subset of {WebFetch, WebSearch, Bash, Read}>
   119	- sources: <bulleted sub-list of url:section or path:line>
   120	- freshness_ts: <ISO 8601 UTC>
   121	- confidence: <high | medium | low>
   122	- commands: <bulleted sub-list of verbatim Bash commands, OR "n/a" if Bash unused>
   123	```
   124	
   125	`commands:` entries are **verbatim** — never truncated in provenance. Display-side truncation may happen in `## Answer` (with `…`) but only there. If verbatim commands push the response over 3 KB, drop the response into the raw artifact pointer file and synthesize down.
   126	
   127	## Confidence scale
   128	
   129	Three-value enum `{high, medium, low}`:
   130	
   131	- `high` — ≥1 authoritative source was directly retrieved AND the answer requires no interpolation.
   132	- `medium` — multiple sources retrieved but one or more required inference, or sources partially contradict each other.
   133	- `low` — cached/stale-source answers, or single-source answers where corroboration was attempted but failed.
   134	
   135	Never paste raw HTML, JSON, or YAML dumps into `## Answer`. Cite and summarize. Use the raw-artifact pointer for overflow.
   136	
   137	## Edge cases
   138	
   139	- **WebFetch returns 4xx/5xx** → log in provenance, mark `STATUS: partial`, try **one** fallback (WebSearch or Bash `gh api`) before giving up.
   140	- **WebSearch returns nothing** → `STATUS: partial`, `## Unresolved` notes "no results for query terms; suggest broader search".
   141	- **Pagination** → WebSearch results ≤10 entries returned. WebFetch link-follow depth ≤2 (the original URL + at most one followed link per source). If more pages exist, note in `## Unresolved` that results are truncated and suggest a narrower query.
   142	- **Authenticated endpoints** requiring secrets the agent doesn't have → `STATUS: refused`, category `auth_missing`. Do not attempt env-var sniffing.
   143	
   144	## Invariants
   145	
   146	- First output line is exactly `STATUS: <token>` where token ∈ {`ok`, `partial`, `refused`}.
   147	- Sections appear in fixed order: `## Answer`, `## Provenance`, `## Unresolved`, optional `## Raw artifact pointer`.
   148	- No tool dispatch other than the whitelist (`WebFetch`, `WebSearch`, `Bash`, `Read`, `Grep`, `Glob`).
   149	- Total response ≤3 KB.
   150	- No raw HTML/JSON/YAML in `## Answer` — cite and summarize; dump to raw-artifact pointer if needed.
   151	- Bash commands recorded verbatim in `provenance.commands`; never truncated in provenance.

exec
/bin/zsh -lc "nl -ba docs/llm/INDEX.json | sed -n '1,220p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	{
     2	  "version": "1",
     3	  "generated_at": "2026-05-24T00:00:00Z",
     4	  "z_harness_version": "64a3dbe",
     5	  "concepts": [
     6	    {
     7	      "slug": "agents",
     8	      "source_file": [
     9	        "agents/auditor.md",
    10	        "agents/cluster-planner.md",
    11	        "agents/codex-consultant.md",
    12	        "agents/codex-reviewer.md",
    13	        "agents/complexity-classifier.md",
    14	        "agents/doc-fetcher.md",
    15	        "agents/doc-updater.md",
    16	        "agents/gemini-consultant.md",
    17	        "agents/implementer.md",
    18	        "agents/remote-runner.md",
    19	        "agents/spec-precheck.md"
    20	      ],
    21	      "last_updated": "2026-05-24",
    22	      "confidence": "high",
    23	      "depends_on": [
    24	        "scripts"
    25	      ],
    26	      "consumed_by": [
    27	        "commands",
    28	        "skills"
    29	      ],
    30	      "summary": "Scrutinizes codebase targets across correctness/perf/cleanliness/design."
    31	    },
    32	    {
    33	      "slug": "commands",
    34	      "source_file": [
    35	        "commands/z-amend.md",
    36	        "commands/z-audit.md",
    37	        "commands/z-brainstorm.md",
    38	        "commands/z-debug.md",
    39	        "commands/z-do.md",
    40	        "commands/z-fix.md",
    41	        "commands/z-implement-all.md",
    42	        "commands/z-implement-next.md",
    43	        "commands/z-improve.md",
    44	        "commands/z-init-docs.md",
    45	        "commands/z-maintain-docs.md",
    46	        "commands/z-plan-light.md",
    47	        "commands/z-plan-split.md",
    48	        "commands/z-plan.md",
    49	        "commands/z-research.md",
    50	        "commands/z-review-all.md",
    51	        "commands/z-skill-fix.md",
    52	        "commands/z-stats.md",
    53	        "commands/z-suggest-memory.md",
    54	        "commands/z-test.md"
    55	      ],
    56	      "last_updated": "2026-05-24",
    57	      "confidence": "high",
    58	      "depends_on": [
    59	        "agents",
    60	        "scripts"
    61	      ],
    62	      "consumed_by": [
    63	        "skills"
    64	      ],
    65	      "summary": "Propagates targeted plan amendments consistently across plan artifacts."
    66	    },
    67	    {
    68	      "slug": "scripts",
    69	      "source_file": [
    70	        "scripts/log-event.sh",
    71	        "scripts/log-phase.sh",
    72	        "scripts/regenerate-memories-flat.py",
    73	        "scripts/remote-sandbox-sync.sh",
    74	        "scripts/version.sh"
    75	      ],
    76	      "last_updated": "2026-05-23",
    77	      "confidence": "high",
    78	      "depends_on": [],
    79	      "consumed_by": [
    80	        "agents",
    81	        "commands",
    82	        "skills"
    83	      ],
    84	      "summary": "Appends standard JSON events to run and global logs."
    85	    },
    86	    {
    87	      "slug": "z-fix",
    88	      "source_file": [
    89	        "commands/z-fix.md"
    90	      ],
    91	      "last_updated": "2026-05-24",
    92	      "confidence": "high",
    93	      "depends_on": [
    94	        "agents",
    95	        "commands"
    96	      ],
    97	      "consumed_by": [
    98	        "commands"
    99	      ],
   100	      "summary": "Lightweight bug-fix command for the case where the user already has a diagnosis; single light-fix consult, inline implementation, non-negotiable Codex review, optional post-mortem."
   101	    },
   102	    {
   103	      "slug": "skills",
   104	      "source_file": [
   105	        "skills/z-amend/SKILL.md",
   106	        "skills/z-brainstorm/SKILL.md",
   107	        "skills/z-debug/SKILL.md",
   108	        "skills/z-do/SKILL.md",
   109	        "skills/z-implement-all/SKILL.md",
   110	        "skills/z-implement-next/SKILL.md",
   111	        "skills/z-improve/SKILL.md",
   112	        "skills/z-init-docs/SKILL.md",
   113	        "skills/z-maintain-docs/SKILL.md",
   114	        "skills/z-plan-light/SKILL.md",
   115	        "skills/z-plan-split/SKILL.md",
   116	        "skills/z-plan/SKILL.md",
   117	        "skills/z-research/SKILL.md",
   118	        "skills/z-review-all/SKILL.md",
   119	        "skills/z-stats/SKILL.md",
   120	        "skills/z-suggest-memory/SKILL.md",
   121	        "skills/z-test/SKILL.md"
   122	      ],
   123	      "last_updated": "2026-05-23",
   124	      "confidence": "high",
   125	      "depends_on": [
   126	        "agents",
   127	        "commands",
   128	        "scripts"
   129	      ],
   130	      "consumed_by": [],
   131	      "summary": "Checklists for amending spec, plan, and task checklists consistently."
   132	    },
   133	    {
   134	      "slug": "providers-registry",
   135	      "source_files": [
   136	        "scripts/resolve-provider.py",
   137	        "scripts/resolve-provider.sh",
   138	        "scripts/discover-providers.py",
   139	        "commands/z-providers-discover.md",
   140	        "docs/human/PROVIDERS.md"
   141	      ],
   142	      "last_updated": "2026-05-24",
   143	      "confidence": "high",
   144	      "depends_on": [
   145	        "scripts"
   146	      ],
   147	      "consumed_by": [
   148	        "agents",
   149	        "commands"
   150	      ],
   151	      "summary": "Config-file registry routing consultant/reviewer dispatches to any CLI-addressable LLM; three fixed roles mapped to named provider entries; resolution via scripts/resolve-provider.sh."
   152	    },
   153	    {
   154	      "slug": "multi-ide-exports",
   155	      "source_files": [
   156	        "scripts/export-common.py",
   157	        "scripts/export-cursor.py",
   158	        "scripts/export-codex.py",
   159	        "scripts/export-agy.py",
   160	        "scripts/audit-tarball.sh",
   161	        "commands/z-export.md",
   162	        "docs/human/MULTI-IDE.md",
   163	        "exports/cursor/CAPABILITIES.md",
   164	        "exports/codex/CAPABILITIES.md",
   165	        "exports/agy/CAPABILITIES.md"
   166	      ],
   167	      "last_updated": "2026-05-24",
   168	      "confidence": "high",
   169	      "depends_on": [
   170	        "commands",
   171	        "agents"
   172	      ],
   173	      "consumed_by": [],
   174	      "summary": "Pipeline translating Claude Code source files into Cursor (.mdc rules), Codex CLI (AGENTS.md + prompts), and Antigravity (agy-plugin.yaml + prompts); /z-export slash command; per-target CAPABILITIES.md documents dropped constructs."
   175	    },
   176	    {
   177	      "slug": "plan-layout-migration",
   178	      "source_files": [
   179	        "scripts/plan-path.sh",
   180	        "scripts/migrate-plan-layout.sh",
   181	        "scripts/log-event.sh",
   182	        "docs/human/PLAN-LAYOUT.md"
   183	      ],
   184	      "last_updated": "2026-05-24",
   185	      "confidence": "high",
   186	      "depends_on": [
   187	        "scripts",
   188	        "commands"
   189	      ],
   190	      "consumed_by": [
   191	        "commands"
   192	      ],
   193	      "summary": "Canonical plan layout under z-harness/plans/<slug>/; Z_HARNESS_PLANS_DIR override; dual-read fallback from legacy z-harness/<slug>/; migrate-plan-layout.sh for bulk or per-slug migration."
   194	    },
   195	    {
   196	      "slug": "z-update",
   197	      "source_files": [
   198	        "install.sh",
   199	        "scripts/bundle-plugin.sh",
   200	        "scripts/version.sh",
   201	        "commands/z-update.md",
   202	        "docs/human/INSTALL.md"
   203	      ],
   204	      "last_updated": "2026-05-24",
   205	      "confidence": "high",
   206	      "depends_on": [
   207	        "scripts",
   208	        "commands"
   209	      ],
   210	      "consumed_by": [],
   211	      "summary": "Explicit in-place plugin update via /z-update; detects symlink vs tarball mode; git pull --ff-only for symlink, atomic swap for tarball; no autoupdate; version tracked by scripts/version.sh."
   212	    },
   213	    {
   214	      "slug": "lookup-contract",
   215	      "source_files": [
   216	        "agents/external-lookup.md"
   217	      ],
   218	      "last_updated": "2026-05-24",
   219	      "confidence": "high",
   220	      "depends_on": [

exec
/bin/zsh -lc "nl -ba docs/llm/providers-registry.json | sed -n '1,120p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	{
     2	  "slug": "providers-registry",
     3	  "summary": "Config-file-based registry for routing consultant and reviewer dispatches to any CLI-addressable LLM. Providers are defined in providers.json at user-global or repo-local scope; roles map the three logical slots (consultant_primary, consultant_secondary, reviewer) to named providers. Resolution is handled by scripts/resolve-provider.sh.",
     4	  "key_invariants": [
     5	    "consultant_primary and consultant_secondary MUST resolve to distinct providers — the resolver exits nonzero if they collide.",
     6	    "Repo-local config overrides user-global config per-key (per provider name and per role), not whole-file. Shadowing emits a provider_shadowed event and a stderr warning.",
     7	    "A role with no bound provider causes the dispatching command to halt immediately with an actionable error pointing to /z-providers-discover.",
     8	    "Schema version field must equal 1; the resolver exits with a schema error on any other value."
     9	  ],
    10	  "key_files": [
    11	    { "path": "scripts/resolve-provider.sh", "why": "Single resolution entrypoint used by every consultant/reviewer dispatch site." },
    12	    { "path": "scripts/resolve-provider.py", "why": "Python implementation of the same resolution logic (used by export scripts and tests)." },
    13	    { "path": "scripts/discover-providers.py", "why": "Probes PATH for known LLM CLIs and emits a proposed providers.json — never writes files directly." },
    14	    { "path": "commands/z-providers-discover.md", "why": "Slash command that wraps discover-providers.py with a user-confirmation gate before writing." },
    15	    { "path": "docs/human/PROVIDERS.md", "why": "User-facing guide: schema reference, config locations, precedence, roles, error messages, and custom CLI patterns." }
    16	  ],
    17	  "related_concepts": ["agents", "commands", "z-update"],
    18	  "last_updated": "2026-05-24"
    19	}

exec
/bin/zsh -lc "nl -ba z-harness/plans/lookup-subagent/SPEC.md | sed -n '1,240p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	# SPEC — lookup-subagent
     2	
     3	Two-tier "lookup" subagent infrastructure: generic `external-lookup` lives in z-harness; domain-specific `qt-market-lookup` lives in qt-bot. Both target a shared output contract published as `docs/llm/lookup-contract.json` (z-harness). Main thread delegates noisy external retrieval (web docs outside training cutoff, paginated APIs, market discovery) to either agent and gets back a ≤3 KB STATUS-headed Markdown synthesis.
     4	
     5	## Planning Inputs
     6	
     7	| Artifact | Path | generated_at |
     8	|----------|------|--------------|
     9	| BRAINSTORM.md | z-harness/plans/lookup-subagent/BRAINSTORM.md | 2026-05-24T18:41:04Z |
    10	| RESEARCH.md | n/a | n/a |
    11	
    12	---
    13	
    14	## File 1: `docs/llm/lookup-contract.json` (z-harness — NEW)
    15	
    16	**Purpose:** Canonical machine-readable description of the lookup output contract that both agents emit and that any future consumer can target.
    17	
    18	**Frontmatter / schema** (matches existing two-tier docs concept format):
    19	
    20	```json
    21	{
    22	  "slug": "lookup-contract",
    23	  "title": "External lookup output contract",
    24	  "last_updated": "<run-date>",
    25	  "source_files": [
    26	    "agents/external-lookup.md",
    27	    "docs/llm/lookup-contract.json"
    28	  ],
    29	  "summary": "Output envelope all lookup subagents emit. STATUS-line + Markdown sections (## Answer / ## Provenance / ## Unresolved). ≤3 KB.",
    30	  "key_concepts": [
    31	    "STATUS values: ok | refused | partial",
    32	    "Provenance fields are mandatory: query, tools_used, sources, freshness_ts, confidence",
    33	    "Bash commands (if any) recorded verbatim in provenance.commands",
    34	    "Body ≤3 KB total",
    35	    "Raw artifacts pointed-to, not pasted"
    36	  ],
    37	  "invariants": [
    38	    "First line is exactly `STATUS: <token>` where token in {ok,refused,partial}",
    39	    "All headed sections appear in fixed order: Answer, Provenance, Unresolved, [Raw artifact pointer]",
    40	    "No raw HTML/JSON dumped into Answer; cite + summarize",
    41	    "Refused responses MUST give reason in Answer"
    42	  ],
    43	  "gotchas": [
    44	    "Body cap is total — header + sections combined ≤3 KB",
    45	    "Markdown section names are load-bearing for orchestrator parsing"
    46	  ]
    47	}
    48	```
    49	
    50	**Behavior:** read-only doc concept consumed by `doc-fetcher` like any other; surfaces when a query mentions "lookup" / "contract" / "external".
    51	
    52	**Invariant:** updating this file MUST bump `last_updated` and trigger /z-maintain-docs awareness for both downstream agents.
    53	
    54	---
    55	
    56	## File 2: `agents/external-lookup.md` (z-harness — NEW)
    57	
    58	**Purpose:** Generic, repo-agnostic Haiku subagent that handles external retrieval — web docs, public APIs, structured fetches — and returns the lookup-contract envelope.
    59	
    60	**Frontmatter:**
    61	
    62	```yaml
    63	---
    64	name: external-lookup
    65	description: Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blocklist.
    66	model: haiku
    67	tools: WebFetch, WebSearch, Bash, Read, Grep, Glob
    68	---
    69	```
    70	
    71	**Body sections (prose):**
    72	
    73	1. **Mission.** One paragraph: "You are a fresh-context lookup worker. Main thread delegates noisy retrieval to you so it doesn't pollute its context. Return ≤3 KB STATUS-headed Markdown per `docs/llm/lookup-contract.json`."
    74	2. **Output contract.** Reproduce the contract structure inline (STATUS line + the four Markdown sections) AND cite `docs/llm/lookup-contract.json` as the canonical version. If conflict, contract.json wins.
    75	3. **Tool guidance.**
    76	   - Prefer `WebFetch` for known URLs of public docs/pages.
    77	   - Prefer `WebSearch` to discover URLs when only a topic is given.
    78	   - Use `Bash` for endpoints WebFetch can't handle: `gh api`, `curl` with custom headers / query params / auth, `jq` filtering of returned JSON.
    79	4. **Verb-blocklist (mandatory before any Bash exec).** Before running any Bash command, grep the literal command string (case-insensitive) against the patterns below. Any match → emit `STATUS: refused` with `## Answer` body `Refused: mutation_blocked — matched pattern '<pattern>' in command '<verbatim cmd>'`. Do not execute.
    80	
    81	   ```
    82	   # DB writes (verb anywhere AND via -f / redirect)
    83	   INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|VACUUM
    84	   psql\s+[^|]*\s-f\s|sqlite3\s+[^|]*\s*<|>\s*[^|>\s]+\.(db|sqlite|sqlite3)\b
    85	
    86	   # Git mutations
    87	   git\s+push|git\s+commit|git\s+reset\s+--hard|git\s+rebase\s+--|git\s+stash\s+drop|git\s+branch\s+-D|git\s+checkout\s+--
    88	
    89	   # GitHub mutations (including gh api with mutating methods)
    90	   gh\s+pr\s+(create|merge|close|edit)|gh\s+issue\s+(create|close|edit)|gh\s+release\s+create|gh\s+api\s+[^|]*--method\s+(POST|PUT|PATCH|DELETE)
    91	
    92	   # HTTP mutations
    93	   curl[^|]*(-X|--request)\s*(POST|PUT|DELETE|PATCH)
    94	   curl[^|]*(-d|--data|--data-raw|--data-binary|-F|--form)\b
    95	   wget\s+[^|]*--(post-data|method)\b
    96	   \bhttpie\s+(POST|PUT|DELETE|PATCH)\b
    97	   \bhttp\s+(POST|PUT|DELETE|PATCH)\b
    98	
    99	   # Eval / piped interpreters (NOTE: bare $(...) and backticks NOT blocked — too disruptive; rely on pipe-to-interpreter detection)
   100	   \beval\b|\bsh\s+-c\b|\bbash\s+-c\b
   101	   \|\s*(sh|bash|zsh|python|python3|perl|ruby|node)\b
   102	   <\s*\(.*\)\s*\|\s*(sh|bash|python|perl|ruby|node)\b
   103	   \b(perl|ruby|node|python|python3)\s+-e\b
   104	
   105	   # Filesystem destructive
   106	   rm\s+-(rf|fr|Rf|fR)\b|>\s*/dev/(sd|nvme|disk)
   107	   ```
   108	
   109	   Implementation note: each pattern is a Python regex tested with `re.IGNORECASE` against the joined argv string. Compile once; test before every `Bash` invocation.
   110	5. **Budget.** Total response (STATUS line + all sections + whitespace) ≤3 KB. Aim for ≤2 KB synthesis inside `## Answer` so Provenance + Unresolved have headroom. If raw artifact exceeds budget, write it to `z-harness/lookup-cache/<sha256-of-normalized-query>.raw` and point at it in `## Raw artifact pointer`. The cache dir is gitignored; mkdir if missing. **Normalized query** = lowercase + collapse all internal whitespace runs to one space + strip leading/trailing whitespace.
   111	6. **Freshness discipline.** `freshness_ts` is the **retrieval timestamp** in UTC ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`) — not the source document's own last-modified date. If a source was loaded from cache and the cache is >24h old, mark `confidence: low` and call it out in `## Unresolved`.
   112	7. **Refusal modes.** STATUS values, mutually exclusive:
   113	   - `ok` — answer believed reliable.
   114	   - `partial` — retrieval completed but incomplete OR ambiguous. Includes: 4xx (incl. 429 rate-limit), 5xx, no-results-found, pagination-truncation, source-cache-stale. Body explains gaps in `## Unresolved`.
   115	   - `refused` — verb-blocklist matched OR explicit mission-scope violation (e.g. user asked to place a trade). Body's first `## Answer` line MUST be `Refused: <category> — <detail>` where category ∈ {`mutation_blocked`, `out_of_scope`, `auth_missing`}.
   116	8. **Provenance section format.** Markdown bullet list, fields in fixed order, each on its own line:
   117	
   118	   ```markdown
   119	   ## Provenance
   120	   - query: <normalized query string>
   121	   - tools_used: <comma-separated subset of {WebFetch, WebSearch, Bash, Read}>
   122	   - sources: <bulleted sub-list of url:section or path:line>
   123	   - freshness_ts: <ISO 8601 UTC>
   124	   - confidence: <high | medium | low>
   125	   - commands: <bulleted sub-list of verbatim Bash commands, OR "n/a" if Bash unused>
   126	   ```
   127	
   128	   `commands:` entries are **verbatim** — never truncated in provenance. Display-side truncation may happen in `## Answer` (with `…`) but only there. If verbatim commands push the response over 3 KB, drop the response into the raw artifact pointer file and synthesize down.
   129	
   130	9. **Confidence scale.** Three-value enum `{high, medium, low}`. Use `high` only when ≥1 authoritative source was directly retrieved AND the answer requires no interpolation. Use `low` for cached/stale-source answers or single-source answers where corroboration was attempted but failed.
   131	9. **Never paste raw HTML, JSON, or YAML dumps into `## Answer`.** Cite + summarize. Use the raw-artifact pointer.
   132	
   133	**Invariants:**
   134	- First output line is exactly `STATUS: <token>`.
   135	- Sections appear in fixed order: `## Answer`, `## Provenance`, `## Unresolved`, optional `## Raw artifact pointer`.
   136	- No tool dispatch other than the whitelist.
   137	
   138	**Edge cases:**
   139	- WebFetch returns 4xx/5xx → log in provenance, mark `STATUS: partial`, try **one** fallback (WebSearch or Bash `gh api`) before giving up.
   140	- WebSearch returns nothing → `STATUS: partial`, `## Unresolved` notes "no results for query terms; suggest broader search".
   141	- Pagination: WebSearch results ≤10 entries returned. WebFetch link-follow depth ≤2 (the original URL + at most one followed link per source). If more pages exist, note in `## Unresolved` that results are truncated and suggest a narrower query.
   142	- Authenticated endpoints requiring secrets the agent doesn't have → `STATUS: refused`, category `auth_missing`. Do not attempt env-var sniffing.
   143	
   144	---
   145	
   146	## File 3: `agents/qt-market-lookup.md` (qt-bot — NEW, authored locally, then deposited via `qt-bot-remote` skill)
   147	
   148	**Deposit procedure (load-bearing — implementer follows this exactly):**
   149	
   150	1. Author the file locally first under `z-harness/plans/lookup-subagent/staging/qt-market-lookup.md`. Do NOT commit it to z-harness's `agents/` (it does not belong there).
   151	2. Use the `qt-bot-remote` skill to inspect qt-bot's tree on remote host `zeke-pc`:
   152	   - Confirm the agents directory path: most likely `~/dev/qt-bot/.claude/agents/` or `~/dev/qt-bot/agents/`. If neither exists, ask the user.
   153	   - Confirm the Kalshi client invocation path. Search for known patterns: `~/dev/qt-bot/scripts/kalshi*`, `cargo run -p kalshi*`, `python -m qt_bot.kalshi*`. Record the exact invocation discovered.
   154	   - Confirm the env var(s) that gate paper vs. real-money mode. Likely `KALSHI_ENV`, `KALSHI_MODE`, or similar. Required for the trading verb-blocklist.
   155	3. Substitute the discovered Kalshi client invocation and env-var name into the agent file's prose (the body has explicit `<KALSHI_CLIENT>` and `<PAPER_ENV_VAR>` placeholders).
   156	4. Use the `qt-bot-remote` skill to scp the finalized file to the discovered agents dir on remote. No restart needed (agent files are read on dispatch).
   157	5. Static-verify on remote: file exists at the deposited path; frontmatter parses; `name:` field equals `qt-market-lookup`.
   158	
   159	**If qt-bot's tree lacks any of the above (no agents dir, no Kalshi client, no env var)** → halt deposit, surface findings to user, do NOT improvise.
   160	
   161	
   162	
   163	**Purpose:** Domain-specific Sonnet subagent in qt-bot that handles Kalshi / weather-market lookup using repo-local clients. Emits the same `lookup-contract` envelope.
   164	
   165	**Frontmatter:**
   166	
   167	```yaml
   168	---
   169	name: qt-market-lookup
   170	description: Discover and inspect Kalshi tickers, weather markets, and related domain entities. Returns the STATUS-headed Markdown envelope from z-harness's docs/llm/lookup-contract.json. Read-only against the Kalshi API; refuses any order/trade verbs.
   171	model: sonnet
   172	tools: Bash, Read, Grep, Glob
   173	---
   174	```
   175	
   176	**Body sections (prose):**
   177	
   178	1. **Mission.** Resolve domain-specific lookups: "what is the ticker for Chicago daily high temperature?", "what weather markets are open for NYC next week?", "what's the payout schema for KXHIGHCHI-26MAY24-T70?". Return the lookup-contract envelope.
   179	2. **Contract reference.** Cite the canonical contract at `<z-harness-plugin>/docs/llm/lookup-contract.json` (path resolved at deposit time; documented as an env var or known relative path). If the plugin path can't be resolved, fall back to the embedded contract description here.
   180	3. **Tool guidance.** Use the qt-bot repo's existing Kalshi client (path resolved at deposit time — examples: `./scripts/kalshi-cli/...`, `cargo run -p kalshi-client --`, or `python -m qt_bot.kalshi`). The implementer determines the exact invocation when the agent is deposited.
   181	4. **Verb-blocklist (mandatory before any Bash exec).** Same DB / git / gh / HTTP / eval / filesystem rules as `external-lookup`, PLUS qt-bot-specific:
   182	   - **Trading mutations:** `place_order|cancel_order|trade|sell|buy(?!_?info)|withdraw|deposit|--execute|--submit`
   183	   - **Real-money operations:** any command containing `--real|--live|--mainnet` while `KALSHI_ENV` ≠ `paper`/`demo`.
   184	5. **Domain enrichment.** When returning ticker info, always include if available: contract symbol, market title, expiration timestamp, payout/strike schema, last price, current open interest. Mark `confidence: low` if any field came from a stale cache (>5 min for prices, >24h for static schema).
   185	6. **Budget.** Same ≤3 KB total cap. Raw paginated API responses → cache pointer.
   186	7. **Refusal modes.** Same `ok | refused | partial` semantics. Bias toward `partial` over confident `ok` when payout schema or expiry is ambiguous.
   187	
   188	**Invariants:**
   189	- Same output structure as `external-lookup` — orchestrator parses both identically.
   190	- No order placement, ever. The verb-blocklist is hard.
   191	- Sonnet tier; do not invoke unless main thread genuinely needs domain reasoning.
   192	
   193	**Edge cases:**
   194	- Kalshi API rate-limit hit → `STATUS: partial`, retry policy documented in `## Unresolved`.
   195	- Market not yet listed → `STATUS: partial`, suggest re-querying after expected listing time (if known).
   196	- Stale cache → degrade to `confidence: low` rather than refusing.
   197	
   198	---
   199	
   200	## File 4: `docs/llm/INDEX.json` (z-harness — MODIFIED)
   201	
   202	Add two entries. Match the existing schema **exactly** by inspecting the current INDEX.json first (key names: confirm singular `source_file` vs plural `source_files`; confirm whether INDEX entries are nested inside a `concepts:` key or are top-level). The implementer reads the existing INDEX before editing.
   203	
   204	Entries to add (schema may vary based on existing file):
   205	
   206	```json
   207	{
   208	  "slug": "lookup-contract",
   209	  "title": "External lookup output contract",
   210	  "summary": "Envelope all lookup subagents emit. STATUS-line + Markdown sections. ≤3 KB.",
   211	  "last_updated": "<run-date>",
   212	  "source_files": ["agents/external-lookup.md", "docs/llm/lookup-contract.json"]
   213	}
   214	```
   215	
   216	```json
   217	{
   218	  "slug": "external-lookup-agent",
   219	  "title": "external-lookup subagent",
   220	  "summary": "Generic Haiku subagent for external retrieval (web docs, public APIs, paginated JSON). Returns lookup-contract envelope.",
   221	  "last_updated": "<run-date>",
   222	  "source_files": ["agents/external-lookup.md"]
   223	}
   224	```
   225	
   226	**Invariant:** INDEX.json remains the only main-thread-readable doc index. Per existing convention, each INDEX entry MUST have a paired `docs/llm/<slug>.json` body file. The `lookup-contract` entry's body is File 1. The `external-lookup-agent` entry's body is File 4b below.
   227	
   228	## File 4b: `docs/llm/external-lookup-agent.json` (z-harness — NEW)
   229	
   230	Token-compacted concept JSON for the `external-lookup` agent. Format mirrors existing concept JSONs (read one existing file like `docs/llm/providers-registry.json` to copy the schema). Required fields: slug, title, summary, key_concepts, invariants, gotchas, source_files. Content:
   231	
   232	- `summary`: one-sentence purpose.
   233	- `key_concepts`: model tier (Haiku); tool whitelist; output envelope shape (STATUS + 4 sections); verb-blocklist categories.
   234	- `invariants`: total response ≤3 KB; first line STATUS; no raw HTML/JSON in Answer; commands recorded verbatim.
   235	- `gotchas`: prompt-injection risk (mitigated by verb-blocklist + audit trail, not eliminated); WebFetch link-depth ≤2; cache dir gitignored.
   236	- `source_files`: `["agents/external-lookup.md"]`.
   237	
   238	## File 4c: `docs/llm/agents.json` (z-harness — MODIFIED, if it exists and lists agents)
   239	
   240	If `docs/llm/agents.json` exists as a registry of agents (read first to confirm schema), append an entry for `external-lookup` with model tier and tool whitelist matching File 2's frontmatter. If `agents.json` is not an agent registry, skip this file.

exec
/bin/zsh -lc "nl -ba docs/llm/lookup-contract.json | sed -n '1,120p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba docs/llm/INDEX.json | sed -n '210,270p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	{
     2	  "slug": "lookup-contract",
     3	  "summary": "Output envelope all lookup subagents emit. Every response begins with a STATUS line (ok | refused | partial) followed by fixed Markdown sections: ## Answer, ## Provenance, ## Unresolved, and an optional ## Raw artifact pointer. Provenance records the original query, tools used, sources cited, a freshness timestamp, and a confidence level. The total body including all sections must not exceed 3 KB.",
     4	  "key_invariants": [
     5	    "First line is exactly `STATUS: <token>` where token is one of {ok, refused, partial}.",
     6	    "Headed sections appear in fixed order: ## Answer, ## Provenance, ## Unresolved, then optionally ## Raw artifact pointer — no other ordering is valid.",
     7	    "No raw HTML or JSON may be dumped into ## Answer; content must be cited and summarized.",
     8	    "STATUS: refused responses MUST include a `reason:` line in the response body.",
     9	    "Total body (all sections combined) must be ≤3 KB."
    10	  ],
    11	  "key_files": [
    12	    { "path": "agents/external-lookup.md", "why": "Agent prompt that implements the lookup contract — defines the required output structure and section semantics." },
    13	    { "path": "docs/llm/lookup-contract.json", "why": "This canonical contract file — fast-lookup oracle for planners and implementers that need to know the envelope schema." },
    14	    { "path": "docs/human/lookup-contract.md", "why": "Human-readable explanation of the contract including examples and section-by-section field reference." }
    15	  ],
    16	  "related_concepts": ["agents"],
    17	  "last_updated": "2026-05-24"
    18	}

 succeeded in 0ms:
   210	      "consumed_by": [],
   211	      "summary": "Explicit in-place plugin update via /z-update; detects symlink vs tarball mode; git pull --ff-only for symlink, atomic swap for tarball; no autoupdate; version tracked by scripts/version.sh."
   212	    },
   213	    {
   214	      "slug": "lookup-contract",
   215	      "source_files": [
   216	        "agents/external-lookup.md"
   217	      ],
   218	      "last_updated": "2026-05-24",
   219	      "confidence": "high",
   220	      "depends_on": [
   221	        "agents"
   222	      ],
   223	      "consumed_by": [
   224	        "external-lookup-agent"
   225	      ],
   226	      "summary": "Output envelope contract (STATUS line + fixed Markdown sections) that all external/domain lookup subagents must emit."
   227	    },
   228	    {
   229	      "slug": "external-lookup-agent",
   230	      "source_files": [
   231	        "agents/external-lookup.md"
   232	      ],
   233	      "last_updated": "2026-05-24",
   234	      "confidence": "high",
   235	      "depends_on": [
   236	        "agents",
   237	        "lookup-contract"
   238	      ],
   239	      "consumed_by": [],
   240	      "summary": "Haiku-tier subagent for external retrieval (web docs, public APIs, library docs) that offloads lookups from main context while enforcing a read-only verb-blocklist."
   241	    }
   242	  ]
   243	}

exec
/bin/zsh -lc "nl -ba docs/llm/external-lookup-agent.json | sed -n '1,120p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	{
     2	  "slug": "external-lookup-agent",
     3	  "summary": "Haiku-tier subagent dispatched by the main thread to handle external retrieval (web docs, public APIs, paginated JSON, library docs outside training cutoff) without polluting the main context. Defined in agents/external-lookup.md. All responses must conform to the output envelope in docs/llm/lookup-contract.json: a STATUS-headed Markdown body with fixed sections (## Answer, ## Provenance, ## Unresolved, optional ## Raw artifact pointer), total response capped at 3 KB. The agent is read-only; mutating shell commands are blocked via a verb-blocklist enforced before every Bash invocation.",
     4	  "key_invariants": [
     5	    "Total response body (STATUS line + all sections + whitespace) must not exceed 3 KB.",
     6	    "First output line is exactly `STATUS: <token>` where token is one of {ok, partial, refused}.",
     7	    "Output sections appear in fixed order: ## Answer, ## Provenance, ## Unresolved, then optionally ## Raw artifact pointer — no other ordering is valid.",
     8	    "No raw HTML or JSON may be dumped into ## Answer; content must be cited and summarized.",
     9	    "All Bash commands must be recorded verbatim (never truncated) in the provenance.commands sub-list.",
    10	    "Verb-blocklist patterns are compiled once and tested with re.IGNORECASE against the full command string before every Bash dispatch; any match triggers STATUS: refused with category mutation_blocked.",
    11	    "Model tier is haiku — the agent must not be dispatched at a higher-cost tier unless explicitly overridden."
    12	  ],
    13	  "key_files": [
    14	    { "path": "agents/external-lookup.md", "why": "The agent file itself — defines mission, output contract, tool whitelist, verb-blocklist patterns, budget rules, and all invariants." },
    15	    { "path": "docs/llm/lookup-contract.json", "why": "Canonical output contract the agent must follow; wins over any conflicting statement in the agent file." }
    16	  ],
    17	  "related_concepts": ["lookup-contract", "agents"],
    18	  "last_updated": "2026-05-24"
    19	}

exec
/bin/zsh -lc "nl -ba README.md | sed -n '1,35p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	# z-harness
     2	
     3	A Claude Code plugin that wraps planning and implementation in a rigorous, cross-LLM-reviewed pipeline.
     4	
     5	## What it does
     6	
     7	Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen archives in `z-harness/<slug>/archive/<run-id>/` and aggregated telemetry in `z-harness/metrics.jsonl`.
     8	
     9	### Pre-planning (optional; feed into `/z-plan`)
    10	
    11	- **`/z-brainstorm <topic>`** — Cheap parallel idea generation across three vendor-diverse ideators (Claude Sonnet + Codex + Gemini). Produces `BRAINSTORM.md` in `z-harness/<slug>/`. Cost target: ≤200K tokens. Use this when the framing or approach for a problem is still open and you want divergent perspectives before locking in a plan.
    12	- **`/z-research <question>`** — Heavier terrain mapping via parallel Explores + cross-LLM critique. Produces `RESEARCH.md` in `z-harness/<slug>/`. Cost target: ≤2M tokens. Use this when you need concrete file:line evidence about an existing codebase or design space before deciding what to build.
    13	
    14	**Typical chains:**
    15	
    16	- Murky problem: `/z-research → /z-brainstorm → /z-plan` — research terrain first, generate framed approaches, then plan.
    17	- Lighter case: `/z-brainstorm → /z-plan` — skip research when the codebase is already well understood.
    18	- Standard: `/z-plan` alone — when the problem and approach are already clear.
    19	
    20	`/z-plan` Setup step 10 automatically detects `BRAINSTORM.md` and `RESEARCH.md` in the slug directory and incorporates them into Phase 0 (premise check) and Phase 1 (exploration). For `RESEARCH.md`, a freshness check runs against every cited `file:line` reference; stale citations prompt a warning before proceeding. If `RESEARCH.md` is non-stale and covers the task's likely-touched files, doc-fetcher and Explore become optional in Phase 1.
    21	
    22	### Planning
    23	
    24	- **`/z-plan <task>`** — Rigorous pipeline: premise check → exploration (with `docs/llm/INDEX.json` if present, plus a freshness gate that defers to `/z-maintain-docs` when docs are stale) → enumerate decisions → user-gated bundled Gemini+Codex consult → SPEC.md / PLAN.md / TASKS.md.
    25	- **`/z-plan-light <fix>`** — Fast path for 1-5 file fixes; auto-bails to `/z-plan` if scope grows. Single `FIX.md` artifact, inline implementation, reviewer safety gate kept.
    26	- **`/z-plan-split <topic>`** — Pre-emptive scope splitter for sprawling topics that would otherwise yield a ≥40-task `/z-plan` run across natural seams. Proposes 2-6 narrow clusters, dispatches one `cluster-planner` subagent per cluster in parallel, then reconciles file-path overlaps into `SHARED-CONCERNS.md` + `MANIFEST.md` under `z-harness/<root-slug>/`. One-level recursion only; no production code. Cost target: cheaper than a single mega-`/z-plan` only when the user genuinely needed N narrow plans — otherwise more expensive (opt-in, do not use as a default).
    27	
    28	  Typical chain for a murky multi-component problem: `/z-research → /z-brainstorm → /z-plan-split → /z-implement-all`.
    29	- **`/z-test`** — Semantic test-case planner. Reads SPEC/PLAN/TASKS, drafts non-trivial tests (sign errors, schema mismatches, off-by-one, unit confusion), cross-consults Gemini+Codex, writes `TESTS.md`. The implementer reads TESTS.md alongside TASKS.md so tests land in the same diff as production code.
    30	
    31	### Implementation
    32	
    33	- **`/z-implement-all`** — Orchestrates the full TASKS.md queue: one fresh `implementer` subagent per task → per-task reviewer safety gate → retry once on review failure → push-notify at every task boundary. Walks a tree-rooted plan produced by `/z-plan-split` (one cluster at a time, in MANIFEST run order) as well as legacy single-slug plans. Flags: `--ack` (override the SHARED-CONCERNS.md ack-gate) and `--force-partial` (proceed against a tree where some clusters failed planning, excluding the failed ones from the run set). Both flags are inert for legacy single-slug plans.
    34	- **`/z-implement-next`** — Same loop, one task at a time.
    35	

exec
/bin/zsh -lc "nl -ba z-harness/plans/lookup-subagent/staging/qt-market-lookup.md | sed -n '1,220p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	---
     2	name: qt-market-lookup
     3	description: Discover and inspect Kalshi tickers, weather markets, and related domain entities. Returns the STATUS-headed Markdown envelope from z-harness's docs/llm/lookup-contract.json. Read-only against the Kalshi API; refuses any order/trade verbs.
     4	model: sonnet
     5	tools: Bash, Read, Grep, Glob
     6	---
     7	
     8	## Mission
     9	
    10	You are a domain-specific lookup worker for Kalshi and weather prediction markets. Main thread delegates market discovery and inspection to you so it doesn't pollute its context. Resolve queries like "what is the ticker for Chicago daily high temperature?", "what weather markets are open for NYC next week?", and "what's the payout schema for KXHIGHCHI-26MAY24-T70?". Return ≤3 KB STATUS-headed Markdown per the contract described below. Read-only against the Kalshi API; never place orders or submit trades.
    11	
    12	## Contract reference
    13	
    14	Every response begins with exactly one STATUS line, followed by four Markdown sections in fixed order:
    15	
    16	```
    17	STATUS: <ok|partial|refused>
    18	
    19	## Answer
    20	<synthesis of retrieved market information; ≤2 KB; no raw HTML/JSON/YAML>
    21	
    22	## Provenance
    23	- query: <normalized query string>
    24	- tools_used: <comma-separated subset of {Bash, Read, Grep, Glob}>
    25	- sources: <bulleted sub-list of endpoint:field or path:line>
    26	- freshness_ts: <ISO 8601 UTC, e.g. 2026-05-24T18:41:00Z>
    27	- confidence: <high | medium | low>
    28	- commands: <bulleted sub-list of verbatim Bash commands, OR "n/a" if Bash unused>
    29	
    30	## Unresolved
    31	<gaps, partial results, rate-limit hits, stale cache warnings; or "none" if fully resolved>
    32	
    33	## Raw artifact pointer
    34	<path to cache file if raw API response was written; omit section if not used>
    35	```
    36	
    37	The canonical version of this contract is at `<z-harness-plugin>/docs/llm/lookup-contract.json` (slug: `lookup-contract`). Resolve the plugin path via the `ANTIGRAVITY_PLUGIN_ROOT` or `CLAUDE_PLUGIN_ROOT` env var, or use the path `z-harness/docs/llm/lookup-contract.json` relative to the workspace root. If the plugin path cannot be resolved, the embedded contract description above is authoritative.
    38	
    39	**STATUS values:**
    40	- `ok` — answer believed reliable.
    41	- `partial` — retrieval completed but incomplete OR ambiguous. Includes: rate-limit (429), 5xx, no-results-found, pagination-truncation, stale cache (>5 min for prices, >24h for static schema). Body explains gaps in `## Unresolved`.
    42	- `refused` — verb-blocklist matched OR explicit mission-scope violation. `## Answer` first line MUST be `Refused: <category> — <detail>` where category ∈ {`mutation_blocked`, `out_of_scope`, `auth_missing`}.
    43	
    44	## Tool guidance
    45	
    46	Use the qt-bot repo's Kalshi client for all market queries. The exact invocation is resolved at deposit time and substituted below:
    47	
    48	```
    49	<KALSHI_CLIENT> <subcommand> [args]
    50	```
    51	
    52	Always prefix the client invocation with the paper-mode env var to ensure read-only sandbox operation:
    53	
    54	```
    55	<PAPER_ENV_VAR>=paper <KALSHI_CLIENT> <subcommand> [args]
    56	```
    57	
    58	Examples of valid read-only subcommands (actual subcommand names depend on the client discovered at deposit):
    59	- Market listing / search: `<KALSHI_CLIENT> list`, `<KALSHI_CLIENT> search <query>`
    60	- Market detail: `<KALSHI_CLIENT> get <ticker>`, `<KALSHI_CLIENT> inspect <ticker>`
    61	- Series listing: `<KALSHI_CLIENT> series list`
    62	
    63	Use `Read` / `Grep` / `Glob` to inspect local repo files when a query references qt-bot source code, config, or cached data. Use `Bash` only for Kalshi client invocations and local file processing (`jq`, `grep`, `awk`).
    64	
    65	## Verb-blocklist
    66	
    67	Before running any Bash command, grep the literal command string (case-insensitive) against every pattern below. Any match → emit `STATUS: refused` with `## Answer` body:
    68	
    69	```
    70	Refused: mutation_blocked — matched pattern '<pattern>' in command '<verbatim cmd>'
    71	```
    72	
    73	Do not execute the command.
    74	
    75	```
    76	# DB writes (verb anywhere AND via -f / redirect)
    77	INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|VACUUM
    78	psql\s+[^|]*\s-f\s|sqlite3\s+[^|]*\s*<|>\s*[^|>\s]+\.(db|sqlite|sqlite3)\b
    79	
    80	# Git mutations
    81	git\s+push|git\s+commit|git\s+reset\s+--hard|git\s+rebase\s+--|git\s+stash\s+drop|git\s+branch\s+-D|git\s+checkout\s+--
    82	
    83	# GitHub mutations (including gh api with mutating methods)
    84	gh\s+pr\s+(create|merge|close|edit)|gh\s+issue\s+(create|close|edit)|gh\s+release\s+create|gh\s+api\s+[^|]*--method\s+(POST|PUT|PATCH|DELETE)
    85	
    86	# HTTP mutations
    87	curl[^|]*(-X|--request)\s*(POST|PUT|DELETE|PATCH)
    88	curl[^|]*(-d|--data|--data-raw|--data-binary|-F|--form)\b
    89	wget\s+[^|]*--(post-data|method)\b
    90	\bhttpie\s+(POST|PUT|DELETE|PATCH)\b
    91	\bhttp\s+(POST|PUT|DELETE|PATCH)\b
    92	
    93	# Eval / piped interpreters (NOTE: bare $(...) and backticks NOT blocked — too disruptive; rely on pipe-to-interpreter detection)
    94	\beval\b|\bsh\s+-c\b|\bbash\s+-c\b
    95	\|\s*(sh|bash|zsh|python|python3|perl|ruby|node)\b
    96	<\s*\(.*\)\s*\|\s*(sh|bash|python|perl|ruby|node)\b
    97	\b(perl|ruby|node|python|python3)\s+-e\b
    98	
    99	# Filesystem destructive
   100	rm\s+-(rf|fr|Rf|fR)\b|>\s*/dev/(sd|nvme|disk)
   101	
   102	# Trading mutations (qt-bot-specific) — target Kalshi client invocations that mutate state
   103	# Matches order/trade submission verbs in client argv; does NOT block read-only verbs like list/search/get/inspect
   104	place_order|cancel_order|\border\s+(create|new|place)\b|\btrade\b(?!\s*history|\s*list)
   105	\bsell\b|\bbuy\b(?!\s*_?info|\s*list|\s*search|\s*history)
   106	\bwithdraw\b|\bdeposit\b
   107	--execute\b|--submit\b
   108	
   109	# Real-money mode guard — reject any invocation that passes --real / --live / --mainnet
   110	# (paper-mode env var enforced separately; this catches flag-based overrides)
   111	--real\b|--live\b|--mainnet\b
   112	```
   113	
   114	Additionally, reject any Kalshi client invocation that does NOT include `<PAPER_ENV_VAR>=paper` (or equivalent paper/demo signal) as a prefix or argument. If the command invokes the Kalshi client but omits the paper-mode env var, refuse with:
   115	
   116	```
   117	Refused: mutation_blocked — Kalshi client invoked without <PAPER_ENV_VAR>=paper guard in command '<verbatim cmd>'
   118	```
   119	
   120	Implementation note: each pattern above is a Python regex tested with `re.IGNORECASE` against the joined argv string. Compile once; test before every `Bash` invocation.
   121	
   122	## Domain enrichment
   123	
   124	When returning ticker or market information, always include the following fields if available:
   125	
   126	- **Contract symbol / ticker** — the canonical market identifier (e.g. `KXHIGHCHI-26MAY24-T70`)
   127	- **Market title** — human-readable name
   128	- **Expiration timestamp** — UTC ISO 8601 when the market closes for trading
   129	- **Strike / threshold** — the numeric threshold or event condition defining the binary outcome
   130	- **Payout schema** — yes/no payout amounts (or range bounds for range contracts)
   131	- **Settlement source** — the data source used to determine the outcome (e.g. NOAA, NWS, ASOS)
   132	- **Last price** — most recent trade price (in cents or probability, per the API)
   133	- **Open interest** — number of currently open contracts
   134	
   135	Mark `confidence: low` for any field sourced from a stale cache (>5 min for prices, >24h for static schema like payout schema or settlement source). If a field is not available from the client response, omit it and note the gap in `## Unresolved`.
   136	
   137	## Budget
   138	
   139	Total response (STATUS line + all sections + whitespace) ≤3 KB. Aim for ≤2 KB synthesis inside `## Answer` so Provenance + Unresolved have headroom.
   140	
   141	If a raw API response exceeds the budget, write it to a local cache file (ask the orchestrator for the appropriate cache path, or use `~/.qt-bot-lookup-cache/<sha256-of-normalized-query>.raw`) and point at it in `## Raw artifact pointer`.
   142	
   143	**Normalized query** = lowercase + collapse all internal whitespace runs to one space + strip leading/trailing whitespace.
   144	
   145	## Refusal modes
   146	
   147	STATUS values are mutually exclusive. Bias toward `partial` over `ok` when payout schema or expiry is ambiguous.
   148	
   149	- `ok` — answer believed reliable; all requested fields retrieved without ambiguity.
   150	- `partial` — retrieval completed but fields are missing, ambiguous, or from stale cache. Explain in `## Unresolved`. Includes: rate-limit (429), API 5xx, market-not-yet-listed, pagination truncated, price cache >5 min old.
   151	- `refused` — verb-blocklist matched OR scope violation. `## Answer` first line: `Refused: <category> — <detail>`.
   152	
   153	Refusal categories:
   154	- `mutation_blocked` — a trading verb or real-money flag was detected.
   155	- `out_of_scope` — request asks this agent to do something beyond market lookup (e.g. "place a trade", "run a backtest", "modify config").
   156	- `auth_missing` — required credentials not available in the environment; do not attempt env-var sniffing.
   157	
   158	## Invariants
   159	
   160	- First output line is exactly `STATUS: <token>` where token ∈ {`ok`, `partial`, `refused`}.
   161	- Sections appear in fixed order: `## Answer`, `## Provenance`, `## Unresolved`, optional `## Raw artifact pointer`.
   162	- No order placement, ever. The verb-blocklist is hard.
   163	- No tool dispatch other than the whitelist (`Bash`, `Read`, `Grep`, `Glob`).
   164	- Total response ≤3 KB.
   165	- No raw HTML/JSON/YAML in `## Answer` — cite and summarize; dump to raw-artifact pointer if needed.
   166	- Every Kalshi client invocation must carry `<PAPER_ENV_VAR>=paper` (or equivalent).
   167	- Bash commands recorded verbatim in `provenance.commands`; never truncated in provenance.
   168	
   169	## Edge cases
   170	
   171	- **Kalshi API rate-limit (429)** → `STATUS: partial`. Record the limit hit in `## Unresolved` with: "Rate-limited at <timestamp>; retry after <retry-after header value or 60s default>." Do not retry automatically.
   172	- **Market not yet listed** → `STATUS: partial`. In `## Unresolved`: "Ticker <X> not found; may not yet be listed. Re-query after expected listing time if known."
   173	- **Stale cache** → Degrade to `confidence: low` rather than refusing. Note staleness in `## Unresolved`.
   174	- **Client subcommand not recognized** → `STATUS: partial`. Note in `## Unresolved` that the exact client interface was not yet resolved (deposit pending). Suggest the user run T011 deposit.
   175	- **Paper-env var not set in shell environment** → Still require the explicit prefix `<PAPER_ENV_VAR>=paper` in the command; do not infer from ambient env.

exec
/bin/zsh -lc "nl -ba docs/human/lookup-contract.md | sed -n '1,220p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	# LOOKUP-CONTRACT — External Lookup Output Contract
     2	
     3	> Last updated: 2026-05-24
     4	
     5	## Motivation
     6	
     7	External lookups — fetching library docs outside the training cutoff, paging
     8	through a market API, resolving a Kalshi ticker — are noisy and context-heavy.
     9	z-harness delegates them to dedicated subagents (`external-lookup`,
    10	`qt-market-lookup`) rather than letting the main orchestrator thread accumulate
    11	raw HTML or paginated JSON in its context window.
    12	
    13	The **lookup contract** is the shared output envelope that every lookup subagent
    14	emits. Because both agents produce the same structure, the orchestrator can parse
    15	them without per-agent branching, and new lookup agents can be added without
    16	changing any consumer code.
    17	
    18	---
    19	
    20	## Envelope structure
    21	
    22	Every lookup response is a single ≤3 KB UTF-8 Markdown string with this shape:
    23	
    24	```
    25	STATUS: <token>
    26	
    27	## Answer
    28	<synthesized prose — no raw HTML, JSON, or YAML dumps>
    29	
    30	## Provenance
    31	- query: <normalized query string>
    32	- tools_used: <comma-separated: WebFetch, WebSearch, Bash, Read>
    33	- sources:
    34	  - <url or path:line>
    35	- freshness_ts: <YYYY-MM-DDTHH:MM:SSZ>
    36	- confidence: <high | medium | low>
    37	- commands:
    38	  - <verbatim Bash command, if any>
    39	
    40	## Unresolved
    41	<gaps, caveats, suggested follow-up — or "none" if fully resolved>
    42	
    43	## Raw artifact pointer
    44	<path to z-harness/lookup-cache/<sha256>.raw>
    45	```
    46	
    47	_(The `## Raw artifact pointer` section is optional; it is only present when the body would exceed 3 KB.)_
    48	
    49	### Key constraints
    50	
    51	- The **first line** of the response is always `STATUS: <token>` — no leading
    52	  whitespace, no blank line before it.
    53	- **Section order is fixed and load-bearing.** The orchestrator parses sections
    54	  by heading name; out-of-order headings break parsing.
    55	- **Total size ≤3 KB** — header + all sections + whitespace combined. This keeps
    56	  the orchestrator's context footprint predictable.
    57	- **No raw dumps in `## Answer`.** Cite and summarize; if the full artifact is
    58	  needed, write it to `lookup-cache/` and add a `## Raw artifact pointer`.
    59	
    60	---
    61	
    62	## STATUS values
    63	
    64	| Value | When to use |
    65	|-------|-------------|
    66	| `ok` | Retrieval succeeded. Answer is believed reliable. At least one authoritative source was directly fetched and no interpolation was required. |
    67	| `partial` | Retrieval ran but the result is incomplete or ambiguous. Covers: HTTP 4xx/5xx, rate-limit (429), no search results, pagination truncation, stale cache (>24h). `## Unresolved` explains the gap and may suggest a follow-up. |
    68	| `refused` | A verb-blocklist pattern matched, or the query was out of scope (e.g. "place a trade"), or a required auth credential was absent. The first line of `## Answer` must be `Refused: <category> — <detail>` where `category` ∈ `{mutation_blocked, out_of_scope, auth_missing}`. |
    69	
    70	Exactly one of these three tokens appears; they are mutually exclusive.
    71	
    72	---
    73	
    74	## Provenance fields
    75	
    76	| Field | Required | Description |
    77	|-------|----------|-------------|
    78	| `query` | yes | The originating query string, preserved verbatim (no lowercasing); whitespace normalized for cache-key derivation only. |
    79	| `tools_used` | yes | Comma-separated subset of `{WebFetch, WebSearch, Bash, Read}`. |
    80	| `sources` | yes | Bulleted sub-list of URL or `path:line` references actually consulted. |
    81	| `freshness_ts` | yes | UTC ISO 8601 timestamp of retrieval — **not** the source document's own last-modified date. |
    82	| `confidence` | yes | See Confidence scale below. |
    83	| `commands` | yes | Verbatim Bash commands issued, or `n/a` if Bash was not used. Commands are **never truncated** here; truncation may appear only inside `## Answer`. |
    84	
    85	---
    86	
    87	## Confidence scale
    88	
    89	| Value | Meaning |
    90	|-------|---------|
    91	| `high` | ≥1 authoritative source directly retrieved; no interpolation needed. |
    92	| `medium` | Source retrieved but corroboration incomplete, or minor interpolation was required. |
    93	| `low` | Answer came from a stale cache (>24h), or a single source where corroboration was attempted and failed, or significant interpolation was required. |
    94	
    95	Use `high` conservatively. When in doubt, prefer `medium`. A stale cache always
    96	forces `low`, regardless of other signals.
    97	
    98	---
    99	
   100	## Examples
   101	
   102	### Example 1 — web documentation lookup
   103	
   104	**Query:** "pydantic v2 model_validator order of execution"
   105	
   106	```
   107	STATUS: ok
   108	
   109	## Answer
   110	In Pydantic v2, `@model_validator(mode='before')` runs before field validation
   111	(receives raw input dict). `@model_validator(mode='after')` runs after all fields
   112	are validated (receives the model instance). Both may be stacked; they execute
   113	in definition order. Class-level validators run before `@field_validator`.
   114	
   115	Source: https://docs.pydantic.dev/latest/concepts/validators/#model-validators
   116	
   117	## Provenance
   118	- query: pydantic v2 model_validator order of execution
   119	- tools_used: WebFetch
   120	- sources:
   121	  - https://docs.pydantic.dev/latest/concepts/validators/#model-validators
   122	- freshness_ts: 2026-05-24T14:32:10Z
   123	- confidence: high
   124	- commands: n/a
   125	
   126	## Unresolved
   127	none
   128	```
   129	
   130	---
   131	
   132	### Example 2 — Kalshi ticker lookup
   133	
   134	**Query:** "payout schema for KXHIGHCHI-27MAY15-T70"
   135	
   136	```
   137	STATUS: ok
   138	
   139	## Answer
   140	KXHIGHCHI-27MAY15-T70 is a Kalshi binary contract on Chicago daily high
   141	temperature for 15 May 2027, strike at 70 °F.
   142	
   143	- Contract symbol: KXHIGHCHI-27MAY15-T70
   144	- Market title: Will the Chicago high temperature exceed 70°F on May 15, 2027?
   145	- Expiration: 2027-05-15T23:59:00Z
   146	- Payout schema: binary — YES settles at $1.00 if official high ≥ 70 °F,
   147	  NO settles at $1.00 otherwise
   148	- Last price: YES $0.42 / NO $0.58  (as of freshness_ts)
   149	- Open interest: 1,840 contracts
   150	
   151	## Provenance
   152	- query: payout schema for KXHIGHCHI-27MAY15-T70
   153	- tools_used: Bash
   154	- sources:
   155	  - kalshi-cli get-market KXHIGHCHI-27MAY15-T70 (local client)
   156	- freshness_ts: 2026-05-24T14:35:02Z
   157	- confidence: high
   158	- commands:
   159	  - kalshi-cli get-market KXHIGHCHI-27MAY15-T70
   160	
   161	## Unresolved
   162	none
   163	```
   164	
   165	---
   166	
   167	## Authoring a new lookup agent
   168	
   169	Any agent that wants to be a compatible lookup provider must:
   170	
   171	1. Emit `STATUS: <token>` as its **first line**, no exceptions.
   172	2. Produce the four sections in the fixed order: `## Answer`, `## Provenance`,
   173	   `## Unresolved`, and optionally `## Raw artifact pointer`.
   174	3. Stay within the **3 KB total** budget; overflow goes to `lookup-cache/`.
   175	4. Record `commands:` verbatim in `## Provenance`.
   176	5. Never paste raw HTML, JSON, or YAML into `## Answer`.
   177	6. Implement a verb-blocklist guard before every `Bash` invocation. The baseline
   178	   patterns are defined in `agents/external-lookup.md`; domain-specific agents
   179	   extend them.
   180	
   181	The canonical machine-readable version of this contract lives at
   182	`docs/llm/lookup-contract.json`.  The `doc-fetcher` subagent surfaces it
   183	automatically whenever a query mentions "lookup", "contract", or "external".

exec
/bin/zsh -lc 'rg -n "external-lookup|lookup-contract|doc-fetcher|qt-market" README.md docs/human/lookup-contract.md z-harness/plans/lookup-subagent/staging/qt-market-lookup.md z-harness/plans/lookup-subagent/SPEC.md' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
docs/human/lookup-contract.md:9:z-harness delegates them to dedicated subagents (`external-lookup`,
docs/human/lookup-contract.md:10:`qt-market-lookup`) rather than letting the main orchestrator thread accumulate
docs/human/lookup-contract.md:178:   patterns are defined in `agents/external-lookup.md`; domain-specific agents
docs/human/lookup-contract.md:182:`docs/llm/lookup-contract.json`.  The `doc-fetcher` subagent surfaces it
README.md:20:`/z-plan` Setup step 10 automatically detects `BRAINSTORM.md` and `RESEARCH.md` in the slug directory and incorporates them into Phase 0 (premise check) and Phase 1 (exploration). For `RESEARCH.md`, a freshness check runs against every cited `file:line` reference; stale citations prompt a warning before proceeding. If `RESEARCH.md` is non-stale and covers the task's likely-touched files, doc-fetcher and Explore become optional in Phase 1.
README.md:85:| `external-lookup` | haiku | Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blocklist. |
README.md:199:- `Z_HARNESS_BRAINSTORM_EXPLORE=1` — opts into a Phase 1 Explore dispatch inside `/z-brainstorm`. Off by default (doc-fetcher only). Set this when you want the brainstorm scaffolding to include live codebase exploration in addition to the doc-fetcher lookup.
README.md:251:- **No doc-fetcher caching across precontext and plan runs.** If you run `/z-research` and then `/z-plan` in the same slug, doc-fetcher is dispatched twice (once per command). Marked as a v2 candidate; the cost is low enough today.
README.md:295:│   └── external-lookup.md
z-harness/plans/lookup-subagent/staging/qt-market-lookup.md:2:name: qt-market-lookup
z-harness/plans/lookup-subagent/staging/qt-market-lookup.md:3:description: Discover and inspect Kalshi tickers, weather markets, and related domain entities. Returns the STATUS-headed Markdown envelope from z-harness's docs/llm/lookup-contract.json. Read-only against the Kalshi API; refuses any order/trade verbs.
z-harness/plans/lookup-subagent/staging/qt-market-lookup.md:37:The canonical version of this contract is at `<z-harness-plugin>/docs/llm/lookup-contract.json` (slug: `lookup-contract`). Resolve the plugin path via the `ANTIGRAVITY_PLUGIN_ROOT` or `CLAUDE_PLUGIN_ROOT` env var, or use the path `z-harness/docs/llm/lookup-contract.json` relative to the workspace root. If the plugin path cannot be resolved, the embedded contract description above is authoritative.
z-harness/plans/lookup-subagent/SPEC.md:3:Two-tier "lookup" subagent infrastructure: generic `external-lookup` lives in z-harness; domain-specific `qt-market-lookup` lives in qt-bot. Both target a shared output contract published as `docs/llm/lookup-contract.json` (z-harness). Main thread delegates noisy external retrieval (web docs outside training cutoff, paginated APIs, market discovery) to either agent and gets back a ≤3 KB STATUS-headed Markdown synthesis.
z-harness/plans/lookup-subagent/SPEC.md:14:## File 1: `docs/llm/lookup-contract.json` (z-harness — NEW)
z-harness/plans/lookup-subagent/SPEC.md:22:  "slug": "lookup-contract",
z-harness/plans/lookup-subagent/SPEC.md:26:    "agents/external-lookup.md",
z-harness/plans/lookup-subagent/SPEC.md:27:    "docs/llm/lookup-contract.json"
z-harness/plans/lookup-subagent/SPEC.md:50:**Behavior:** read-only doc concept consumed by `doc-fetcher` like any other; surfaces when a query mentions "lookup" / "contract" / "external".
z-harness/plans/lookup-subagent/SPEC.md:56:## File 2: `agents/external-lookup.md` (z-harness — NEW)
z-harness/plans/lookup-subagent/SPEC.md:58:**Purpose:** Generic, repo-agnostic Haiku subagent that handles external retrieval — web docs, public APIs, structured fetches — and returns the lookup-contract envelope.
z-harness/plans/lookup-subagent/SPEC.md:64:name: external-lookup
z-harness/plans/lookup-subagent/SPEC.md:65:description: Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blocklist.
z-harness/plans/lookup-subagent/SPEC.md:73:1. **Mission.** One paragraph: "You are a fresh-context lookup worker. Main thread delegates noisy retrieval to you so it doesn't pollute its context. Return ≤3 KB STATUS-headed Markdown per `docs/llm/lookup-contract.json`."
z-harness/plans/lookup-subagent/SPEC.md:74:2. **Output contract.** Reproduce the contract structure inline (STATUS line + the four Markdown sections) AND cite `docs/llm/lookup-contract.json` as the canonical version. If conflict, contract.json wins.
z-harness/plans/lookup-subagent/SPEC.md:146:## File 3: `agents/qt-market-lookup.md` (qt-bot — NEW, authored locally, then deposited via `qt-bot-remote` skill)
z-harness/plans/lookup-subagent/SPEC.md:150:1. Author the file locally first under `z-harness/plans/lookup-subagent/staging/qt-market-lookup.md`. Do NOT commit it to z-harness's `agents/` (it does not belong there).
z-harness/plans/lookup-subagent/SPEC.md:157:5. Static-verify on remote: file exists at the deposited path; frontmatter parses; `name:` field equals `qt-market-lookup`.
z-harness/plans/lookup-subagent/SPEC.md:163:**Purpose:** Domain-specific Sonnet subagent in qt-bot that handles Kalshi / weather-market lookup using repo-local clients. Emits the same `lookup-contract` envelope.
z-harness/plans/lookup-subagent/SPEC.md:169:name: qt-market-lookup
z-harness/plans/lookup-subagent/SPEC.md:170:description: Discover and inspect Kalshi tickers, weather markets, and related domain entities. Returns the STATUS-headed Markdown envelope from z-harness's docs/llm/lookup-contract.json. Read-only against the Kalshi API; refuses any order/trade verbs.
z-harness/plans/lookup-subagent/SPEC.md:178:1. **Mission.** Resolve domain-specific lookups: "what is the ticker for Chicago daily high temperature?", "what weather markets are open for NYC next week?", "what's the payout schema for KXHIGHCHI-26MAY24-T70?". Return the lookup-contract envelope.
z-harness/plans/lookup-subagent/SPEC.md:179:2. **Contract reference.** Cite the canonical contract at `<z-harness-plugin>/docs/llm/lookup-contract.json` (path resolved at deposit time; documented as an env var or known relative path). If the plugin path can't be resolved, fall back to the embedded contract description here.
z-harness/plans/lookup-subagent/SPEC.md:181:4. **Verb-blocklist (mandatory before any Bash exec).** Same DB / git / gh / HTTP / eval / filesystem rules as `external-lookup`, PLUS qt-bot-specific:
z-harness/plans/lookup-subagent/SPEC.md:189:- Same output structure as `external-lookup` — orchestrator parses both identically.
z-harness/plans/lookup-subagent/SPEC.md:208:  "slug": "lookup-contract",
z-harness/plans/lookup-subagent/SPEC.md:212:  "source_files": ["agents/external-lookup.md", "docs/llm/lookup-contract.json"]
z-harness/plans/lookup-subagent/SPEC.md:218:  "slug": "external-lookup-agent",
z-harness/plans/lookup-subagent/SPEC.md:219:  "title": "external-lookup subagent",
z-harness/plans/lookup-subagent/SPEC.md:220:  "summary": "Generic Haiku subagent for external retrieval (web docs, public APIs, paginated JSON). Returns lookup-contract envelope.",
z-harness/plans/lookup-subagent/SPEC.md:222:  "source_files": ["agents/external-lookup.md"]
z-harness/plans/lookup-subagent/SPEC.md:226:**Invariant:** INDEX.json remains the only main-thread-readable doc index. Per existing convention, each INDEX entry MUST have a paired `docs/llm/<slug>.json` body file. The `lookup-contract` entry's body is File 1. The `external-lookup-agent` entry's body is File 4b below.
z-harness/plans/lookup-subagent/SPEC.md:228:## File 4b: `docs/llm/external-lookup-agent.json` (z-harness — NEW)
z-harness/plans/lookup-subagent/SPEC.md:230:Token-compacted concept JSON for the `external-lookup` agent. Format mirrors existing concept JSONs (read one existing file like `docs/llm/providers-registry.json` to copy the schema). Required fields: slug, title, summary, key_concepts, invariants, gotchas, source_files. Content:
z-harness/plans/lookup-subagent/SPEC.md:236:- `source_files`: `["agents/external-lookup.md"]`.
z-harness/plans/lookup-subagent/SPEC.md:240:If `docs/llm/agents.json` exists as a registry of agents (read first to confirm schema), append an entry for `external-lookup` with model tier and tool whitelist matching File 2's frontmatter. If `agents.json` is not an agent registry, skip this file.
z-harness/plans/lookup-subagent/SPEC.md:244:## File 5: `docs/human/lookup-contract.md` (z-harness — NEW)
z-harness/plans/lookup-subagent/SPEC.md:246:Human-tier description of the contract. Mirrors `docs/llm/lookup-contract.json` semantics. ~1 page Markdown: motivation, the envelope structure, when to use `STATUS: partial` vs `refused`, examples of well-formed responses (one for a doc lookup, one for a Kalshi ticker lookup).
z-harness/plans/lookup-subagent/SPEC.md:265:Add `external-lookup` to the agents table near the existing agent list. One row, one-line description matching the agent frontmatter.
z-harness/plans/lookup-subagent/SPEC.md:274:- **Main thread never reads `docs/llm/lookup-contract.json` directly.** Always via `doc-fetcher`.
z-harness/plans/lookup-subagent/SPEC.md:278:- **DRY:** the contract lives once in `docs/llm/lookup-contract.json`; both agents reference it instead of duplicating prose. Verb-blocklist patterns are mostly shared (`external-lookup` defines the core; `qt-market-lookup` extends with trading verbs).
z-harness/plans/lookup-subagent/SPEC.md:280:- **SOLID — Single Responsibility:** `external-lookup` does generic web/API; `qt-market-lookup` does Kalshi/weather. No overlap.

codex
A few details are already visible: the core blocklist text matches the SPEC, while the INDEX snapshot has a mixed historical schema (`source_file` in older entries, `source_files` in newer ones). I’m checking regex validity and whether the staged qt patterns introduce any malformed expressions.
exec
/bin/zsh -lc "python3 - <<'PY'
import re
patterns = [
 r'INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|VACUUM',
 r'psql\\s+["'^|]*'"\\s-f\\s|sqlite3\\s+["'^|]*'"\\s*<|>\\s*["'^|>'"\\s]+\\.(db|sqlite|sqlite3)\\b',
 r'git\\s+push|git\\s+commit|git\\s+reset\\s+--hard|git\\s+rebase\\s+--|git\\s+stash\\s+drop|git\\s+branch\\s+-D|git\\s+checkout\\s+--',
 r'gh\\s+pr\\s+(create|merge|close|edit)|gh\\s+issue\\s+(create|close|edit)|gh\\s+release\\s+create|gh\\s+api\\s+["'^|]*--method'"\\s+(POST|PUT|PATCH|DELETE)',
 r'curl["'^|]*(-X|--request)'"\\s*(POST|PUT|DELETE|PATCH)',
 r'curl["'^|]*(-d|--data|--data-raw|--data-binary|-F|--form)'"\\b',
 r'wget\\s+["'^|]*--(post-data|method)'"\\b',
 r'\\bhttpie\\s+(POST|PUT|DELETE|PATCH)\\b',
 r'\\bhttp\\s+(POST|PUT|DELETE|PATCH)\\b',
 r'\\beval\\b|\\bsh\\s+-c\\b|\\bbash\\s+-c\\b',
 r'\\|\\s*(sh|bash|zsh|python|python3|perl|ruby|node)\\b',
 r'<\\s*\\(.*\\)\\s*\\|\\s*(sh|bash|python|perl|ruby|node)\\b',
 r'\\b(perl|ruby|node|python|python3)\\s+-e\\b',
 r'rm\\s+-(rf|fr|Rf|fR)\\b|>\\s*/dev/(sd|nvme|disk)',
 r'place_order|cancel_order|\\border\\s+(create|new|place)\\b|\\btrade\\b(?"'!'"\\s*history|\\s*list)',
 r'\\bsell\\b|\\bbuy\\b(?"'!'"\\s*_?info|\\s*list|\\s*search|\\s*history)',
 r'\\bwithdraw\\b|\\bdeposit\\b',
 r'--execute\\b|--submit\\b',
 r'--real\\b|--live\\b|--mainnet\\b',
]
for i,p in enumerate(patterns,1):
    re.compile(p, re.I)
print('all compile')
PY" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
all compile

codex
**Prong A**

1. **OK.** All six core verb-blocklist categories are present in [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:61): DB writes, git mutations, gh mutations, HTTP mutations, eval/piped interpreters, and filesystem destructive commands. I also compiled the patterns with Python `re.IGNORECASE`; they are valid regexes. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:79), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:61).

2. **Minor.** The two new INDEX entries are internally consistent and match the newer existing `source_files` schema used by entries like `providers-registry`, not the older `source_file` entries still present earlier in the file. However, the `lookup-contract` INDEX entry omits `docs/llm/lookup-contract.json` from `source_files`, despite SPEC’s sample including it. Source: [docs/llm/INDEX.json](/Users/zeke/dev/z-harness/docs/llm/INDEX.json:214), [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:208).

3. **OK.** The concept JSONs use `key_invariants` / `key_files`, matching existing concept JSONs such as `providers-registry.json`. This is the corrected T001 retry shape, not the stale literal `invariants` / `source_files` wording in SPEC File 4b. Source: [docs/llm/providers-registry.json](/Users/zeke/dev/z-harness/docs/llm/providers-registry.json:4), [docs/llm/external-lookup-agent.json](/Users/zeke/dev/z-harness/docs/llm/external-lookup-agent.json:4).

4. **Major.** Path references mostly exist, but the canonical contract JSON contains a contract-content inconsistency: it says refused responses must include a `reason:` line, while the agent and human doc require `Refused: <category> — <detail>` as the first `## Answer` line. Since `lookup-contract.json` is canonical, this should be fixed. Source: [docs/llm/lookup-contract.json](/Users/zeke/dev/z-harness/docs/llm/lookup-contract.json:8), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:42), [docs/human/lookup-contract.md](/Users/zeke/dev/z-harness/docs/human/lookup-contract.md:68).

5. **OK.** The README row description matches the `external-lookup` frontmatter description verbatim. Source: [README.md](/Users/zeke/dev/z-harness/README.md:85), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:3).

6. **OK with minor caveat.** `qt-market-lookup` inherits all external-lookup core blocklist patterns and adds trading plus real-money flag guards; those added regexes compile. The caveat is operational: `<PAPER_ENV_VAR>` remains a placeholder until T011 deposit, so the staged file is not deployable as-is. Source: [qt-market-lookup.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/staging/qt-market-lookup.md:75), [qt-market-lookup.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/staging/qt-market-lookup.md:102).

**Prong B**

1. **Minor.** Yes, SPEC File 4b should be amended. It still names stale required fields (`key_concepts`, `invariants`, `gotchas`, `source_files`) rather than the actual concept schema (`key_invariants`, `key_files`, `related_concepts`, etc.). Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:230).

2. **Minor.** SPEC should define cache-key versioning/namespace. SHA256 collision is not the practical risk; normalized-equivalent queries intentionally collide. That may be fine, but it should be explicit, ideally with `lookup-cache/v1/<sha256>.raw` or domain/tool namespacing. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:110).

3. **Major.** Cache-vs-source freshness needs clarification. Current text only says stale cache forces `confidence: low`; it does not say fresh fetch wins over stale cache, nor how to score a fresh retrieval of stale source content. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:111), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:101).

4. **Major.** Nothing runtime-enforceable exists until T011 substitutes the real Kalshi client and paper env var. Because T011/T012 are remote-skipped, staged `qt-market-lookup` should be treated as non-deployable; SPEC should explicitly make deposit/substitution a precondition for dispatch. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:150), [qt-market-lookup.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/staging/qt-market-lookup.md:114).

5. **Major.** The 3 KB cap and “commands verbatim, never truncated” invariant still conflict for very long commands. The agent says to “drop the response into the raw artifact pointer file and synthesize down,” but that implies provenance commands may no longer be fully verbatim in the returned body. SPEC should define the precedence explicitly. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:128), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:125).

6. **Minor.** No cache expiry or GC policy is defined. Current behavior is “stale cache degrades confidence,” not refusal. SPEC should say that explicitly and optionally define user/implementer cleanup expectations. Source: [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:103).

7. **Major.** Lifecycle is underspecified. The agent frontmatter gives model/tools, and edge cases give one fallback for WebFetch failures, but SPEC does not define dispatch syntax, force-fresh lookup behavior, or a general retry budget after both WebFetch and WebSearch fail. Source: [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:4), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:139).
tokens used
69,064
**Prong A**

1. **OK.** All six core verb-blocklist categories are present in [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:61): DB writes, git mutations, gh mutations, HTTP mutations, eval/piped interpreters, and filesystem destructive commands. I also compiled the patterns with Python `re.IGNORECASE`; they are valid regexes. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:79), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:61).

2. **Minor.** The two new INDEX entries are internally consistent and match the newer existing `source_files` schema used by entries like `providers-registry`, not the older `source_file` entries still present earlier in the file. However, the `lookup-contract` INDEX entry omits `docs/llm/lookup-contract.json` from `source_files`, despite SPEC’s sample including it. Source: [docs/llm/INDEX.json](/Users/zeke/dev/z-harness/docs/llm/INDEX.json:214), [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:208).

3. **OK.** The concept JSONs use `key_invariants` / `key_files`, matching existing concept JSONs such as `providers-registry.json`. This is the corrected T001 retry shape, not the stale literal `invariants` / `source_files` wording in SPEC File 4b. Source: [docs/llm/providers-registry.json](/Users/zeke/dev/z-harness/docs/llm/providers-registry.json:4), [docs/llm/external-lookup-agent.json](/Users/zeke/dev/z-harness/docs/llm/external-lookup-agent.json:4).

4. **Major.** Path references mostly exist, but the canonical contract JSON contains a contract-content inconsistency: it says refused responses must include a `reason:` line, while the agent and human doc require `Refused: <category> — <detail>` as the first `## Answer` line. Since `lookup-contract.json` is canonical, this should be fixed. Source: [docs/llm/lookup-contract.json](/Users/zeke/dev/z-harness/docs/llm/lookup-contract.json:8), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:42), [docs/human/lookup-contract.md](/Users/zeke/dev/z-harness/docs/human/lookup-contract.md:68).

5. **OK.** The README row description matches the `external-lookup` frontmatter description verbatim. Source: [README.md](/Users/zeke/dev/z-harness/README.md:85), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:3).

6. **OK with minor caveat.** `qt-market-lookup` inherits all external-lookup core blocklist patterns and adds trading plus real-money flag guards; those added regexes compile. The caveat is operational: `<PAPER_ENV_VAR>` remains a placeholder until T011 deposit, so the staged file is not deployable as-is. Source: [qt-market-lookup.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/staging/qt-market-lookup.md:75), [qt-market-lookup.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/staging/qt-market-lookup.md:102).

**Prong B**

1. **Minor.** Yes, SPEC File 4b should be amended. It still names stale required fields (`key_concepts`, `invariants`, `gotchas`, `source_files`) rather than the actual concept schema (`key_invariants`, `key_files`, `related_concepts`, etc.). Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:230).

2. **Minor.** SPEC should define cache-key versioning/namespace. SHA256 collision is not the practical risk; normalized-equivalent queries intentionally collide. That may be fine, but it should be explicit, ideally with `lookup-cache/v1/<sha256>.raw` or domain/tool namespacing. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:110).

3. **Major.** Cache-vs-source freshness needs clarification. Current text only says stale cache forces `confidence: low`; it does not say fresh fetch wins over stale cache, nor how to score a fresh retrieval of stale source content. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:111), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:101).

4. **Major.** Nothing runtime-enforceable exists until T011 substitutes the real Kalshi client and paper env var. Because T011/T012 are remote-skipped, staged `qt-market-lookup` should be treated as non-deployable; SPEC should explicitly make deposit/substitution a precondition for dispatch. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:150), [qt-market-lookup.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/staging/qt-market-lookup.md:114).

5. **Major.** The 3 KB cap and “commands verbatim, never truncated” invariant still conflict for very long commands. The agent says to “drop the response into the raw artifact pointer file and synthesize down,” but that implies provenance commands may no longer be fully verbatim in the returned body. SPEC should define the precedence explicitly. Source: [SPEC.md](/Users/zeke/dev/z-harness/z-harness/plans/lookup-subagent/SPEC.md:128), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:125).

6. **Minor.** No cache expiry or GC policy is defined. Current behavior is “stale cache degrades confidence,” not refusal. SPEC should say that explicitly and optionally define user/implementer cleanup expectations. Source: [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:103).

7. **Major.** Lifecycle is underspecified. The agent frontmatter gives model/tools, and edge cases give one fallback for WebFetch failures, but SPEC does not define dispatch syntax, force-fresh lookup behavior, or a general retry budget after both WebFetch and WebSearch fail. Source: [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:4), [agents/external-lookup.md](/Users/zeke/dev/z-harness/agents/external-lookup.md:139).
