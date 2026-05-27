---
description: Author the project STYLE.md interactively, grounded in the repo's most idiomatic existing files (Capture). Required before /z-mr-review will run.
---

You are running the **z-harness `/z-style-init`** pipeline.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Argument parsing

Parse `$ARGUMENTS` before doing anything else:

- `--amend` flag present → **Mode B** (amend). See Mode B section below.
- `--ingest <path>` → capture the path as `INGEST_PATH`; interview phase will be skipped and this file read instead.
- No flags → **Mode A** (bootstrap).

---

## Mode A — Bootstrap (no `--amend`)

### Setup

1. **Check for existing STYLE.md.** Run:
   ```bash
   ls ./STYLE.md 2>/dev/null
   ```
   If `STYLE.md` already exists at the repo root, refuse:
   > `STYLE.md` already exists. Pass `--amend` to add rules from recent dismissals (pending T011), or delete `STYLE.md` manually to start over.
   Exit without writing anything.

2. **Derive repo name** from the current directory basename:
   ```bash
   basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   ```

3. **Pick a run id:**
   ```bash
   RUN=$(date -u +%Y%m%dT%H%M%SZ)-style-init
   ```
   (No slug-dir is needed for `/z-style-init` — STYLE.md writes to repo root, not to a z-harness subdirectory.)

4. **Version stamp + log run start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1])
   v["ingest_path"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "${INGEST_PATH:-}")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_init_start "$START_PAYLOAD"
   ```

5. **Notification policy:** see [docs/human/config.md](docs/human/config.md) (notify.level key).

---

## Phase telemetry (mandatory)

At the **start** of each phase (1 through 5), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, bracket the wait:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 1 — Capture

**Goal:** identify the 5 most idiomatic source files in the repo to ground the style guide.

### Step 1a — Heuristic prefilter

Build the candidate list from tracked files:

```bash
git ls-files
```

Exclude files matching any of the following patterns (exact path prefix or glob):

- `node_modules/`
- `vendor/`
- `dist/`
- `target/`
- `__pycache__/`
- `*.pb.go`
- `*_pb2.py`
- `migrations/`
- `__generated__/`
- `*.min.*`
- `package-lock.json`
- `yarn.lock`
- `Cargo.lock`
- `poetry.lock`

Also exclude any file whose line count (via `wc -l`) is **< 50** or **> 800**.

Run line-count filtering in a shell loop or via `awk`. Record the surviving paths as `CANDIDATES`.

If `CANDIDATES` is empty, tell the user:

> No candidate files found after filtering (gitignored + exclusion list + size band 50-800 lines). The repo may be too small or entirely generated. STYLE.md cannot be bootstrapped without idiomatic examples. You may pass `--ingest <path>` to supply an existing guide instead.

Then exit.

### Step 1b — Sonnet rank

Dispatch a Sonnet subagent to pick the top 5 most idiomatic files from `CANDIDATES`:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="general-purpose",
  model="sonnet",
  description="Rank idiomatic source files for STYLE.md capture",
  prompt="You are helping author a project style guide. Below is a list of tracked source files (already filtered for size and excludes).

Your task: rank them by 'idiomatic-ness' — that is, which files are most likely to reflect the project's deliberate coding conventions (not just the biggest files, not generated code, not scaffolding). Prefer files that appear to be hand-authored business logic, helpers, or core modules. Avoid test fixtures, example files, and entry-point boilerplate unless the repo is almost entirely composed of them.

Return exactly 5 file paths from the list, one per line, ranked best-first. No explanation needed — just the 5 paths.

Repo language hint (from file extensions): <detect dominant extension from CANDIDATES list>

Candidate files:
<CANDIDATES, one per line>"
)
```

Capture the agent's return as `RANKED_5` (a list of 5 paths).

If the agent returns fewer than 5 paths (e.g. `CANDIDATES` had fewer than 5 entries), use all available.

### Step 1c — User confirmation of Capture set

Present the ranked 5 to the user via `AskUserQuestion`:

```
The following 5 files will anchor your STYLE.md (ranked by idiomatic-ness):

1. <path1>
2. <path2>
3. <path3>
4. <path4>
5. <path5>

Options:
  use these       — proceed with this list
  edit list       — provide a replacement list (free-text, one path per line)
  re-pick         — ask the ranker for a different set of 5
  abandon         — exit without writing STYLE.md
```

Log `user_wait_start` before presenting; log `user_wait_end` after reply. Track `USER_WAIT_MS_THIS_PHASE`.

Branch on reply:

- **use these** → `FINAL_5 = RANKED_5`; proceed.
- **edit list** → treat the user's reply as a newline-separated list of paths; verify each exists with `git ls-files <path>`; warn about any untracked/missing paths (but do not block); set `FINAL_5` to the provided list; proceed.
- **re-pick** → repeat Step 1b with a note in the prompt: "Do not return the same set as before: <RANKED_5>." Loop back to Step 1c.
- **abandon** → exit cleanly. Log `style_init_abandoned` event.

### Step 1d — Read Capture files

Read the contents of the `FINAL_5` files into context (using the Read tool for each). These will be passed verbatim to the Draft phase.

---

## Phase 2 — Interview (or Ingest)

**If `--ingest <path>` was specified:**

Read the file at `INGEST_PATH` into context as `EXISTING_GUIDE`. Skip the interview questions below. Set `SOURCE = ingest`. Proceed to Phase 3.

**Otherwise (no `--ingest`), ask up to 4 questions via `AskUserQuestion`:**

Ask all 4 in a single `AskUserQuestion` call (multi-part prompt), then wait for a single reply. If the user skips a question or gives a blank answer for it, treat that section as "no preference stated."

```
To write a style guide grounded in your project's actual conventions, please answer the following (skip any you don't care about):

1. Error handling philosophy: Do you prefer defensive error handling (wrap-and-log everywhere, guard clauses, early returns) or propagating errors upward (let callers decide)? Or something specific to your stack?

2. Testing posture: Mostly unit tests with mocks? Integration / end-to-end heavy? Mixed? Any testing anti-patterns you want to ban?

3. Comment policy: When should code be commented? Are there formats you require (e.g. JSDoc, rustdoc, /// only for public items)? What types of comments do you want to avoid?

4. Project-specific rules: Anything else this codebase insists on that wouldn't appear in a generic style guide? (e.g. "no direct DB calls outside the repository layer", "all datetimes in UTC", "never import from sibling packages")
```

Record answers as `INTERVIEW_ANSWERS`. Set `SOURCE = capture` (primary source is the Capture files).

---

## Phase 3 — Draft STYLE.md

Dispatch a Sonnet subagent to draft the full STYLE.md:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="general-purpose",
  model="sonnet",
  description="Draft STYLE.md from captured files and interview answers",
  prompt="You are writing a project STYLE.md. You will produce a style guide in a specific schema. The guide must have:

FRONTMATTER (YAML, required fields):
  schema_version: 1
  source: <SOURCE value>
  source_files: [<FINAL_5 paths, or empty list if ingest>]
  repo: <REPO_NAME>
  revision: <output of: git rev-parse HEAD>
  generated_at: <current ISO 8601 UTC timestamp>

BODY (five required sections, in this order, each with at least one rule):
  ## Error handling   (rule IDs: EH-001, EH-002, ...)
  ## Tests            (rule IDs: T-001, T-002, ...)
  ## Comments         (rule IDs: C-001, C-002, ...)
  ## Naming           (rule IDs: N-001, N-002, ...)
  ## Project-specific (rule IDs: P-001, P-002, ...)

Each rule must follow this format exactly:
  ### EH-001: <short rule title>
  <one-paragraph rule prose — concrete and actionable, not vague>
  Rationale: <one sentence explaining why this matters for the project>

Rule IDs are append-only within each section. Use sequential numbering starting at 001.

Aim for 3-5 rules per section. Draw directly from the source files and interview answers. Do not invent rules that contradict what you observe in the source files. If the source files show no evidence for a rule, omit it rather than guess.

Captured source files (read these carefully for observed conventions):
<contents of FINAL_5 files, one after another with path headers>

Interview answers (user preferences to encode as rules):
<INTERVIEW_ANSWERS or 'No interview answers — derived from ingest guide below' + EXISTING_GUIDE>

Return the complete STYLE.md content (frontmatter + body) as a single fenced markdown block."
)
```

Capture the agent return as `DRAFT_STYLE_MD`. Extract the content from the fenced block.

---

## Phase 4 — Cross-LLM Critique

Dispatch `consultant-secondary` and `consultant-primary` **in parallel in a single message** with `MODE: style-critique`:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Style-critique STYLE.md draft",
  prompt="MODE: style-critique

Review the STYLE.md draft below. Flag:
- Missing rule categories (e.g. a section with zero rules, or a clearly missing topic given the observed source files)
- Vague rules (prose that is not actionable — e.g. 'write clean code')
- Contradictions between rules (e.g. EH-001 says propagate; EH-003 says swallow)
- Rule IDs that are out of sequence or duplicated

Return your findings as a numbered list. Each finding: one sentence describing the problem + one sentence proposing a fix. If you find no problems, return 'No findings.'

STYLE.md draft:
<DRAFT_STYLE_MD>"
)

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Style-critique STYLE.md draft",
  prompt="MODE: style-critique

Review the STYLE.md draft below. Flag:
- Missing rule categories (e.g. a section with zero rules, or a clearly missing topic given the observed source files)
- Vague rules (prose that is not actionable — e.g. 'write clean code')
- Contradictions between rules
- Rule IDs that are out of sequence or duplicated

Return your findings as a numbered list. Each finding: one sentence describing the problem + one sentence proposing a fix. If you find no problems, return 'No findings.'

STYLE.md draft:
<DRAFT_STYLE_MD>"
)
```

Wait for both returns. Collect findings. If a consultant errors or times out, log `style_critic_failed {voice, reason}` and proceed with the other consultant's findings only.

**Apply findings:** for each non-trivial finding (skip duplicates and taste-only nits), apply the suggested fix to `DRAFT_STYLE_MD`. Use your own judgment to resolve contradictions between the two consultants' suggestions. The goal is a tighter, more actionable style guide — do not add rules that conflict with what the source files show.

Record the revised content as `REVISED_STYLE_MD`.

---

## Phase 5 — User approval and write

Present the draft to the user via `AskUserQuestion`:

```
STYLE.md draft is ready (after cross-LLM critique). Here's a summary:

Sections:
  - Error handling: <N> rules
  - Tests: <N> rules
  - Comments: <N> rules
  - Naming: <N> rules
  - Project-specific: <N> rules
Total rules: <total>

Source files used: <FINAL_5 paths, or 'ingest: <path>'>
Critique applied from: <codex|gemini|both|neither (if both failed)>

Options:
  accept            — write STYLE.md to repo root and finish
  edit-and-resave   — I'll paste an edited version; use that instead
  re-critique       — run another critique pass on the current draft
  abandon           — exit without writing STYLE.md
```

Log `user_wait_start` before presenting; log `user_wait_end` after reply.

Branch on reply:

- **accept** → proceed to write step.
- **edit-and-resave** → `AskUserQuestion` asking the user to paste the edited STYLE.md content. Accept the paste, set `REVISED_STYLE_MD` to the pasted content. Proceed to write step.
- **re-critique** → loop back to Phase 4 with the current `REVISED_STYLE_MD` as input.
- **abandon** → exit cleanly. Log `style_init_abandoned` event.

### Write step

Write `REVISED_STYLE_MD` to `./STYLE.md` at the repo root (use the Write tool).

Count the total number of rules across all sections (search for `### [A-Z]+-[0-9]+:` pattern). Count the number of non-empty sections.

Log `style_init_complete`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_init_complete \
  "$(printf '{"source":"%s","sections_populated":%d,"rule_count":%d}' \
     "<SOURCE>" "<SECTIONS_WITH_RULES>" "<TOTAL_RULE_COUNT>")"
```

Push-notify (if notify.level ≠ `off`; see [docs/human/config.md](docs/human/config.md)):

> STYLE.md written to repo root (<TOTAL_RULE_COUNT> rules across <SECTIONS_WITH_RULES> sections). Run `/z-mr-review` to review a branch diff against it.

---

---

## Mode B — Amend (`--amend`)

### Setup

1. **Check for STYLE.md.** Run:
   ```bash
   ls ./STYLE.md 2>/dev/null
   ```
   If `STYLE.md` does NOT exist, refuse:
   > No STYLE.md found. Run `/z-style-init` (without `--amend`) first to bootstrap one.
   Exit without writing anything.

2. **Pick a run id:**
   ```bash
   RUN=$(date -u +%Y%m%dT%H%M%SZ)-style-amend
   ```

3. **Version stamp + log run start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_amend_start \
     "$(python3 -c 'import json,sys; v=json.loads(sys.argv[1]); print(json.dumps(v))' "$VERSION_BLOB")"
   ```

4. **Derive slug-dir.** Attempt to read the current branch:
   ```bash
   BRANCH="$(git branch --show-current 2>/dev/null)"
   SLUG="$(printf '%s' "$BRANCH" | tr '[:upper:]' '[:lower:]' | tr '/' '-' | sed 's/[^a-z0-9-]//g')"
   SLUG_DIR="z-harness/${SLUG}/"
   ```
   If the branch is empty/detached or `SLUG_DIR` does not exist as a directory, use the first available `z-harness/*/` directory (via `ls -d z-harness/*/`). If no `z-harness/*/` directory exists at all, `SLUG_DIR` can be any valid path string — the `--global` flag causes `extract-dismissals.py` to scan all slugs, so a missing slug-dir simply yields an empty result set.

5. **Notification policy:** see [docs/human/config.md](docs/human/config.md) (notify.level key).

---

### Phase MB-1 — Scan dismissal archives

**Goal:** extract normalized finding snippets that users have repeatedly dismissed in past MR-REVIEW runs.

Record `T0=$(date +%s%3N)`.

Run:
```bash
python3 scripts/extract-dismissals.py "${SLUG_DIR}" --max-runs 10 --global
```

Capture stdout as `DISMISSED_JSON`. If the script exits nonzero or produces invalid JSON, log `style_amend_extract_failed {reason}` and exit with:
> Could not extract dismissal signatures (extract-dismissals.py failed). Check that `scripts/extract-dismissals.py` exists and the z-harness archive structure is intact.

Parse `DISMISSED_JSON` into `DISMISSED_SIGNATURES` (the array at `.signatures`). Record `N_SIGNATURES = len(DISMISSED_SIGNATURES)`.

**Empty-dismissals early exit:** If `N_SIGNATURES == 0` (the signatures array is empty or absent), output:
> No recent dismissals found. STYLE.md unchanged.

Log `style_amend_complete {clusters: 0, rules_added: 0}` and exit cleanly. Do not proceed to Phase MB-2.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-1","name":"scan-dismissals","wall_ms":%d,"n_signatures":%d}' \
     "$WALL_MS" "$N_SIGNATURES")"
```

---

### Phase MB-2 — Cluster dismissals

**Goal:** group similar dismissed findings into clusters so that one STYLE.md rule can address each cluster.

Record `T0=$(date +%s%3N)`.

**Stopword list** (hardcoded): `the a an this that is are in on of to for and or with by`

**Algorithm:**

1. **Tokenize each signature's `normalized_snippet`:**
   - Lowercase, collapse internal whitespace to a single space, strip leading/trailing punctuation.
   - Split on whitespace into a token list.
   - Remove all stopword tokens. Record as `tokens[i]`.

2. **Group by category first.** Signatures with different `category` values are placed in different clusters regardless of text similarity.

3. **Within each category, build clusters with Jaccard ≥ 0.6:**
   - For each signature not yet assigned to a cluster, start a new candidate cluster with that signature as seed.
   - For each remaining unassigned signature in the same category, compute Jaccard similarity:
     ```
     jaccard(A, B) = |tokens(A) ∩ tokens(B)| / |tokens(A) ∪ tokens(B)|
     ```
   - If Jaccard ≥ 0.6, add to the candidate cluster.
   - Mark all added signatures as assigned.
   - Repeat until all signatures in the category are assigned.

4. **Discard clusters with fewer than 2 members.**

Record `CLUSTERS` = the surviving clusters, each as:
```json
{
  "cluster_id": "<category>-<sequential-int>",
  "category": "<category>",
  "member_count": <int>,
  "representative_snippet": "<normalized_snippet of the seed signature>",
  "all_snippets": ["<snippet1>", "<snippet2>", ...]
}
```

Record `N_CLUSTERS = len(CLUSTERS)`.

If `N_CLUSTERS == 0`:
```
No dismissal clusters found (need ≥2 similar dismissed findings per cluster). Nothing to amend.
```
Log `style_amend_complete {clusters: 0, rules_added: 0}` and exit.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-2","name":"cluster-dismissals","wall_ms":%d,"n_clusters":%d}' \
     "$WALL_MS" "$N_CLUSTERS")"
```

---

### Phase MB-3 — Propose amendments (Sonnet)

**Goal:** for each cluster, propose a new STYLE.md rule that would prevent those findings from being raised again.

Record `T0=$(date +%s%3N)`.

Read `./STYLE.md` (full content) into `CURRENT_STYLE_MD`.

Dispatch a Sonnet subagent:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="general-purpose",
  model="sonnet",
  description="Propose STYLE.md rule amendments from dismissal clusters",
  prompt="You are helping maintain a project STYLE.md. The user has repeatedly dismissed certain code-review findings in past review runs. Your job is to propose new STYLE.md rules — one per cluster — that would prevent those findings from being raised again.

STYLE.md uses these sections with these rule-ID prefixes:
  ## Error handling   → EH-NNN
  ## Tests            → T-NNN
  ## Comments         → C-NNN
  ## Naming           → N-NNN
  ## Project-specific → P-NNN

Rule format (strictly required):
  ### EH-005: <short rule title>
  <one-paragraph rule prose — concrete and actionable, not vague>
  Rationale: <one sentence explaining why this matters for the project>

Instructions:
1. Read the current STYLE.md below carefully. For each section, identify the highest existing rule number (e.g. if EH-001 through EH-004 exist, the next free ID is EH-005).
2. For each dismissal cluster below, propose ONE new rule. Map the cluster to the most appropriate STYLE.md section based on the cluster's category:
   - category 'style-drift' or 'hygiene' → ## Project-specific or ## Naming
   - category 'defensive-bloat' → ## Error handling
   - category 'test-noise' → ## Tests
   - category 'abstraction' → ## Project-specific
   If uncertain, use ## Project-specific.
3. The rule must encode the intent behind the dismissals — why were these findings repeatedly rejected? What convention should the reviewer learn to stop flagging?
4. Return each proposed rule as a standalone markdown block preceded by a comment indicating which cluster it addresses and which STYLE.md section it belongs to.

Format your response as:

<!-- Cluster: <cluster_id> → Section: <section heading> -->
### <RULE-ID>: <short rule title>
<rule prose>
Rationale: <one sentence>

(one block per cluster, separated by blank lines)

Current STYLE.md:
<CURRENT_STYLE_MD>

Dismissal clusters (JSON):
<CLUSTERS as JSON>"
)
```

Capture the agent return as `PROPOSED_RULES_RAW`. If the agent errors or returns output that cannot be parsed into at least one valid `<!-- Cluster: ... → Section: ... -->` / rule-block pair, log:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_amend_propose_failed \
  "$(printf '{"reason":"%s"}' "<error description>")"
```
Then exit with the message:
> Could not generate rule proposals. Check the agent output and retry.

Parse `PROPOSED_RULES_RAW` into a list `PROPOSED_RULES`:
- Each entry: `{cluster_id, section, rule_id, rule_markdown}` extracted from the comment + rule block pairs.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-3","name":"propose-amendments","wall_ms":%d,"n_proposed":%d}' \
     "$WALL_MS" "${#PROPOSED_RULES[@]}")"
```

---

### Phase MB-4 — User review

**Goal:** let the user accept or reject each proposed rule.

Record `T0=$(date +%s%3N)`.

Log `user_wait_start`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":"MB-4","reason":"rule-review"}'
```

For each cluster / proposed rule, send a **separate `AskUserQuestion` call** — one cluster per call, sequentially. Do not batch multiple clusters into a single `AskUserQuestion`.

```
Proposed new rule for cluster <cluster_id> (category: <category>, <member_count> dismissed findings):

Representative dismissed finding:
  "<representative_snippet>"

Proposed rule (for <section>):
  <rule_markdown, indented 2 spaces>

Options:
  add-as-drafted     — append this rule to STYLE.md as written above
  reject             — skip this rule; do not add it
```

> **Implementation note (v1):** "add-with-edits" interactive free-text flow is deferred to v2. In v1, user can reject and manually edit STYLE.md afterward if they want a customized version of the rule. This is a known limitation flagged for v2 follow-up.

Collect responses. Track `APPROVED_RULES` (all entries where user chose `add-as-drafted`).

Log `user_wait_end`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":"MB-4","wall_ms":%d,"approved":%d,"rejected":%d}' \
     "$USER_WAIT_MS_THIS_PHASE" "${#APPROVED_RULES[@]}" \
     "$(( N_CLUSTERS - ${#APPROVED_RULES[@]} ))")"
```

If no rules approved, exit:
```
No rules approved. STYLE.md unchanged.
```
Log `style_amend_complete {clusters: N_CLUSTERS, rules_added: 0}` and exit.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-4","name":"user-review","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

### Phase MB-5 — Append approved rules to STYLE.md

**Goal:** write approved rules to the correct sections in `./STYLE.md`.

Record `T0=$(date +%s%3N)`.

For each approved rule in `APPROVED_RULES`:
1. Identify the target section heading (e.g. `## Error handling`).
2. Find the last rule block in that section (last `### <PREFIX>-NNN:` heading). Verify the proposed rule ID (`EH-005` etc.) is indeed the next free ID. If a collision is detected (the ID already exists in the file), increment the ID number until a free one is found.
3. Append the rule markdown immediately after the last rule block in that section (before the next `##`-level heading or end of file).

Use the Edit tool to append each rule to the correct section. Do not restructure or reformat the existing STYLE.md content.

After writing all approved rules, update the STYLE.md frontmatter field `source` to include `amend` if not already present. Specifically:
- If `source:` currently reads `capture`, change to `capture,amend`.
- If it already contains `amend`, leave unchanged.
- For any other value, append `,amend`.

(Do not change `schema_version` or any other frontmatter field.)

Count `N_RULES_ADDED = len(APPROVED_RULES)`.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-5","name":"append-rules","wall_ms":%d,"rules_added":%d}' \
     "$WALL_MS" "$N_RULES_ADDED")"
```

---

### Mode B completion

Log `style_amend_complete`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_amend_complete \
  "$(printf '{"clusters":%d,"rules_added":%d}' "$N_CLUSTERS" "$N_RULES_ADDED")"
```

Push-notify (if notify.level ≠ `off`; see [docs/human/config.md](docs/human/config.md)):
> STYLE.md amended: <N_RULES_ADDED> rule(s) added across <K> section(s) (from <N_CLUSTERS> dismissal clusters). Run `/z-mr-review` to see new findings against the updated guide.

---

## Operating principles

- **Capture before drafting.** The style guide is grounded in observed code, not invented conventions.
- **User confirms the file list.** The Capture set is shown and confirmed before reading file content (prevents god-objects from anchoring the guide).
- **Cross-LLM critique is mandatory.** Both consultants run in parallel; findings applied before user sees the draft.
- **Refuse without STYLE.md gate.** If STYLE.md already exists in Mode A, refuse immediately — do not overwrite silently. In Mode B, refuse if STYLE.md does NOT exist.
- **Log everything** via `scripts/log-event.sh`.
- **Never read `docs/llm/*.json` from main thread.** Dispatch `doc-fetcher` if INDEX.json exists and context is needed.
