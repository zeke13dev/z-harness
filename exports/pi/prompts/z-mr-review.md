# /z-mr-review

You are running the **z-harness `/z-mr-review`** pipeline.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Finding promotion contract

`/z-mr-review` is a producer of the shared review-family promotion contract:

- The parsed reviewer JSON is the structured finding source.
- `MR-REVIEW.md` is both the evidence summary and the promotion artifact: ranked findings are emitted as task-shaped blocks that the user can delete before applying survivors.
- The command preserves its P0-P4 severity model because it is code-quality oriented, but every emitted task block must include source severity, category, file citation, finding detail, and acceptance criteria.

`MR-REVIEW.md` is intentionally separate from canonical plan `TASKS.md`. Users apply survivors with `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`; the implementation orchestrator must treat that path as the task queue while still resolving `$BASE` from the slug for SPEC/PLAN context when present.

## Argument parsing

Parse `$ARGUMENTS` before doing anything else:

- `--slug <value>` → capture as `SLUG_OVERRIDE`. Overrides the auto-derived slug.
- `--base <ref>` → capture as `BASE_OVERRIDE`. Overrides the default base ref computation.
- `--include-untracked` flag → set `INCLUDE_UNTRACKED=true` (default `false`).
- `--deep` flag → set `DEEP=true` (default `false`). Upgrades the abstraction pass to Opus (plumbed in T006+ agent dispatch).
- `--force-on-trunk` flag → set `FORCE_ON_TRUNK=true` (default `false`). Allows running on `main`/`master`/`trunk`.

---

## Phase 1 — Setup

### Step 1a — Slug resolution

Resolve the slug by which this run is namespaced (`$Z_HARNESS_PLAN_DIR/`):

**If `--slug` was provided:**

Validate the override before accepting it — reject empty values or any character outside `[a-z0-9-]`:

```bash
if [ -z "$SLUG_OVERRIDE" ] || ! echo "$SLUG_OVERRIDE" | grep -qE '^[a-z0-9-]+$'; then
  echo "Error: --slug value '$SLUG_OVERRIDE' is invalid. Must match ^[a-z0-9-]+$ (lowercase alphanumeric and hyphens only)." >&2
  exit 1
fi
SLUG="$SLUG_OVERRIDE"
```

**Trunk guard applies regardless of `--slug`.** Always inspect the actual current branch:

```bash
CURRENT_BRANCH="$(git branch --show-current 2>/dev/null)"
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ] || [ "$CURRENT_BRANCH" = "trunk" ]; then
  if [ "${FORCE_ON_TRUNK:-false}" != "true" ]; then
    echo "Error: current branch is '$CURRENT_BRANCH'. /z-mr-review is almost certainly meant for a feature branch, not trunk. Run with --force-on-trunk if you intend to review a trunk diff." >&2
    exit 1
  fi
fi
```

Export the slug for child processes:

```bash
export Z_HARNESS_SLUG="$SLUG"
```

**Otherwise, derive from the current branch:**

```bash
CURRENT_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null)"
```

If `git symbolic-ref --short HEAD` exits nonzero (detached HEAD), refuse with:

> Error: repository is in detached HEAD state. Use `--slug=<name>` to specify a slug explicitly.

Exit nonzero.

If `CURRENT_BRANCH` is empty after the check, apply the same detached-HEAD refusal.

Normalize the branch name to a slug:
1. Lowercase the branch name.
2. Replace `/` with `-`.
3. Strip any character that is not alphanumeric or `-`.

```bash
SLUG="$(echo "$CURRENT_BRANCH" | tr '[:upper:]' '[:lower:]' | tr '/' '-' | tr -cd 'a-z0-9-')"
```

Export the slug for child processes:

```bash
export Z_HARNESS_SLUG="$SLUG"
```

**Trunk guard:** If `CURRENT_BRANCH` is one of `main`, `master`, or `trunk` AND `FORCE_ON_TRUNK` is `false`, refuse with:

> Error: current branch is `<CURRENT_BRANCH>`. `/z-mr-review` is almost certainly meant for a feature branch, not trunk. Run with `--force-on-trunk` if you intend to review a trunk diff.

Exit nonzero.

### Step 1b — STYLE.md gate

Check that `STYLE.md` exists at the repo root:

```bash
ls ./STYLE.md 2>/dev/null
```

If `STYLE.md` does not exist, log `mr_style_missing`, then refuse:

> Error: no `STYLE.md` found at the repo root. Run `/z-style-init` first. There is no `--no-style` escape.

Exit nonzero.

### Step 1c — Run ID and archive setup

Pick a run ID and create the archive directory **before** any telemetry calls:

```bash
RUN="$(date -u +%Y%m%dT%H%M%SZ)-mr-review"
SLUG_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" plan_dir "$SLUG")"
ARCHIVE_DIR="$SLUG_DIR/archive/$RUN"
mkdir -p "$ARCHIVE_DIR/chunks"
export SLUG RUN ARCHIVE_DIR SLUG_DIR
```

### Step 1d — Voice availability pre-check

Check which multi-LLM voices are available:

```bash
command -v codex >/dev/null 2>&1 && CODEX_AVAILABLE=true || CODEX_AVAILABLE=false
command -v gemini >/dev/null 2>&1 && GEMINI_AVAILABLE=true || GEMINI_AVAILABLE=false
```

Build the `VOICES_AVAILABLE` list:

- Always include `claude`.
- If `CODEX_AVAILABLE=true`, include `codex`.
- If `GEMINI_AVAILABLE=true`, include `gemini`.

```bash
VOICES_AVAILABLE="claude"
[ "$CODEX_AVAILABLE" = "true" ] && VOICES_AVAILABLE="$VOICES_AVAILABLE,codex"
[ "$GEMINI_AVAILABLE" = "true" ] && VOICES_AVAILABLE="$VOICES_AVAILABLE,gemini"
```

If `VOICES_AVAILABLE` is only `claude` (neither codex nor gemini is available), warn the user and log a degraded event:

> Warning: neither `codex` nor `gemini` CLI is available. Running in single-voice (Claude-only) mode. Consensus tier-bump/demote logic is disabled. Install the missing CLIs for full multi-voice review.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_voices_degraded \
  "$(printf '{"slug":"%s","voices_available":"%s"}' "$SLUG" "$VOICES_AVAILABLE")"
```

### Step 1e — Archive any existing MR-REVIEW.md

If `$Z_HARNESS_PLAN_DIR/MR-REVIEW.md` already exists, archive it before overwriting:

```bash
EXISTING="$SLUG_DIR/MR-REVIEW.md"
if [ -f "$EXISTING" ]; then
  N=1
  while [ -f "$ARCHIVE_DIR/MR-REVIEW.md.previous-$N" ]; do
    N=$(( N + 1 ))
  done
  cp "$EXISTING" "$ARCHIVE_DIR/MR-REVIEW.md.previous-$N"
fi
```

### Step 1f — Version stamp and run-start log

```bash
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
```

### Step 1g — Base ref and diff capture

Determine the base git ref:

- If `--base` was provided, use `BASE_OVERRIDE`.
- Otherwise: check if `main` exists (`git rev-parse --verify main 2>/dev/null`); if so, use `main`.
- Otherwise: check if `master` exists (`git rev-parse --verify master 2>/dev/null`); if so, use `master`.
- Otherwise: refuse with "Cannot determine base ref: neither `main` nor `master` exists. Use `--base=<ref>` to specify one."

```bash
if [ -n "$BASE_OVERRIDE" ]; then
  BASE_REF="$BASE_OVERRIDE"
elif git rev-parse --verify main >/dev/null 2>&1; then
  BASE_REF="main"
elif git rev-parse --verify master >/dev/null 2>&1; then
  BASE_REF="master"
else
  echo "Error: Cannot determine base ref: neither 'main' nor 'master' exists. Use --base=<ref> to specify one." >&2
  exit 1
fi
```

Validate the resolved `BASE_REF` before using it — a bad `--base` value must error, not silently produce an empty diff:

```bash
if ! git rev-parse --verify "$BASE_REF" >/dev/null 2>&1; then
  echo "Error: base ref '$BASE_REF' does not exist in this repository." >&2
  exit 1
fi
BASE_SHA="$(git rev-parse "$BASE_REF")"
```

Capture the diff. `git diff` exits nonzero on error; an empty result is OK only when the diff command itself succeeds:

```bash
if ! git diff "$BASE_REF"...HEAD > "$ARCHIVE_DIR/diff.patch"; then
  echo "Error: 'git diff $BASE_REF...HEAD' failed — check that the base ref is reachable." >&2
  exit 1
fi
```

If `--include-untracked` is set, append untracked files using `git diff --no-index` directly (no custom header prepending to avoid malformed/duplicated hunks):

```bash
if [ "$INCLUDE_UNTRACKED" = "true" ]; then
  git ls-files --others --exclude-standard | while IFS= read -r f; do
    git diff --no-index -- /dev/null "$f" 2>/dev/null >> "$ARCHIVE_DIR/diff.patch" || true
  done
fi
```

If `diff.patch` is empty (zero bytes), exit cleanly:

> No changes vs `<BASE_REF>`; nothing to review.

```bash
if [ ! -s "$ARCHIVE_DIR/diff.patch" ]; then
  echo "No changes vs '$BASE_REF'; nothing to review."
  exit 0
fi
```

Compute diff stat for logging:

```bash
DIFF_STAT="$(git diff --stat "$BASE_REF"...HEAD | tail -1)"
```

### Step 1h — Size and chunking decision

Read the env-configurable threshold (default 320000 bytes ≈ 80k tokens):

```bash
CHUNK_THRESHOLD="${Z_MR_DIFF_CHUNK_BYTES:-320000}"
DIFF_BYTES="$(wc -c < "$ARCHIVE_DIR/diff.patch")"
```

If `DIFF_BYTES <= CHUNK_THRESHOLD`, set `MODE=full`. Otherwise set `MODE=per-chunk`.

```bash
if [ "$DIFF_BYTES" -le "$CHUNK_THRESHOLD" ]; then
  MODE="full"
else
  MODE="per-chunk"
fi
```

**If `MODE=per-chunk`**, split `diff.patch` into per-file chunks now:

Parse the diff to identify per-file sections (lines starting with `diff --git`). For each file section in diff order:
- Extract the file path (the `b/<path>` part).
- Sanitize the path for use as a filename: replace `/` with `__`, strip leading dots (e.g. `.hidden` → `hidden`).
- Write the section to `archive/$RUN/chunks/<NNN>-<sanitized-path>.patch` where `NNN` is zero-padded to 3 digits.
- Write a `chunks/manifest.json` listing all chunks.

```bash
# Chunking is performed via a Python inline script for reliable diff boundary detection:
python3 - <<'PYEOF'
import os, sys, json, re

archive_dir = os.environ['ARCHIVE_DIR']
diff_path = os.path.join(archive_dir, 'diff.patch')
chunks_dir = os.path.join(archive_dir, 'chunks')
os.makedirs(chunks_dir, exist_ok=True)

with open(diff_path, 'r', errors='replace') as f:
    content = f.read()

# Split on 'diff --git' boundaries
sections = re.split(r'(?=^diff --git )', content, flags=re.MULTILINE)
sections = [s for s in sections if s.strip()]

chunks = []
for idx, section in enumerate(sections):
    nnn = str(idx).zfill(3)
    # Extract file path from 'diff --git a/<path> b/<path>'
    m = re.match(r'^diff --git a/(.+?) b/(.+?)$', section, re.MULTILINE)
    if m:
        file_path = m.group(2)
    else:
        file_path = f'unknown-{nnn}'
    # Sanitize: replace / with __, strip leading dots
    sanitized = file_path.replace('/', '__').lstrip('.')
    chunk_name = f'{nnn}-{sanitized}.patch'
    chunk_path = os.path.join(chunks_dir, chunk_name)
    with open(chunk_path, 'w') as cf:
        cf.write(section)
    line_count = section.count('\n')
    chunks.append({
        'index': idx,
        'path': chunk_path,
        'files_touched': [file_path],
        'line_count': line_count
    })

manifest = {
    'chunks': chunks,
    'total_bytes': os.path.getsize(diff_path),
    'generated_at': os.popen('date -u +%Y-%m-%dT%H:%M:%SZ').read().strip()
}
manifest_path = os.path.join(chunks_dir, 'manifest.json')
with open(manifest_path, 'w') as mf:
    json.dump(manifest, mf, indent=2)

print(f"Chunked diff into {len(chunks)} file patches. Manifest: {manifest_path}")
PYEOF
```

After chunking, verify the manifest contains at least one chunk. If `MODE=per-chunk` and the manifest has zero chunks, the diff was either empty (shouldn't reach here) or the chunker failed to parse any file boundaries — fail fast with a clear error:

```bash
CHUNK_COUNT_CHECK="$(python3 -c 'import json; m=json.load(open("'"$ARCHIVE_DIR/chunks/manifest.json"'")); print(len(m["chunks"]))')"
if [ "$CHUNK_COUNT_CHECK" -eq 0 ]; then
  echo "Error: MODE=per-chunk but manifest contains zero chunks. The diff may be empty or malformed — check $ARCHIVE_DIR/diff.patch." >&2
  exit 1
fi
```

### Step 1i — Dismissal signature extraction

Invoke `scripts/extract-dismissals.py` to compute prior dismissal signatures:

```bash
if ! python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/extract-dismissals.py" \
  "$SLUG_DIR/" \
  --max-runs 10 \
  > "$ARCHIVE_DIR/dismissed_signatures.json" 2>/dev/null; then
  echo '{"signatures":[],"n_runs_scanned":0}' > "$ARCHIVE_DIR/dismissed_signatures.json"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_dismissal_extract_failed \
    "$(printf '{"slug":"%s"}' "$SLUG")"
fi
```

**Emit one `mr_finding_dismissed` event per dismissed signature:**

```bash
python3 - <<'PYEOF'
import json, os, subprocess

archive_dir = os.environ['ARCHIVE_DIR']
slug = os.environ['SLUG']
run_id = os.environ['RUN']
plugin_root = os.environ.get('ANTIGRAVITY_PLUGIN_ROOT') or os.environ.get('CLAUDE_PLUGIN_ROOT', '')

with open(os.path.join(archive_dir, 'dismissed_signatures.json')) as f:
    data = json.load(f)

for sig in data.get('signatures', []):
    payload = json.dumps({
        'slug': slug,
        'category': sig.get('category', ''),
        'prior_run_id': sig.get('prior_run_id') or sig.get('run_id', '')
    })
    subprocess.run([
        'bash',
        os.path.join(plugin_root, 'scripts/log-event.sh'),
        run_id,
        'mr_finding_dismissed',
        payload
    ])
PYEOF
```

### Step 1j — Log provider resolution and mr_run_start

Log provider resolution (once per run, guarded against re-emission):
```bash
if [ ! -f "$ARCHIVE_DIR/.providers-logged" ]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
  mkdir -p "$ARCHIVE_DIR"
  touch "$ARCHIVE_DIR/.providers-logged"
fi
```

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_run_start \
  "$(python3 -c '
import json, sys
v = json.loads(sys.argv[1])
v["slug"] = sys.argv[2]
v["run_id"] = sys.argv[3]
v["base"] = sys.argv[4]
v["diff_stat"] = sys.argv[5]
v["mode"] = sys.argv[6]
v["voices_available"] = sys.argv[7].split(",")
v["deep"] = sys.argv[8] == "true"
print(json.dumps(v))
' "$VERSION_BLOB" "$SLUG" "$RUN" "$BASE_REF" "$DIFF_STAT" "$MODE" "$VOICES_AVAILABLE" "${DEEP:-false}")"
```

---

## Phase 2 — Agent dispatch

### Step 2a — Resolve absolute paths for agent inputs

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
STYLE_PATH="$REPO_ROOT/STYLE.md"
DIFF_PATH="$REPO_ROOT/$ARCHIVE_DIR/diff.patch"
DISMISSED_PATH="$REPO_ROOT/$ARCHIVE_DIR/dismissed_signatures.json"
SLUG_DIR_ABS="$REPO_ROOT/$SLUG_DIR"
MANIFEST_PATH="$REPO_ROOT/$ARCHIVE_DIR/chunks/manifest.json"
```

### Step 2b — Dispatch mr-reviewer agent

The agent always receives one `diff_path` pointing to a single `.patch` file — polymorphism lives in the orchestrator only.

**If `MODE=full`:** dispatch the agent once with the full diff.

> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
```
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="mr-reviewer",
  model="sonnet",
  description="MR review for <SLUG>",
  prompt="slug: <SLUG>
run_id: <RUN>
slug_dir: <SLUG_DIR_ABS>
base: <BASE_REF>
base_sha: <BASE_SHA>
diff_path: <DIFF_PATH>
style_path: <STYLE_PATH>
dismissed_signatures_path: <DISMISSED_PATH>
voices_available: [<VOICES_AVAILABLE>]
mode: full
chunk_meta: null
deep: <DEEP>"
)
```

Capture the agent's full return text as `AGENT_RETURN`. Proceed to Phase 3 (single-return merge path).

> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).

Read `manifest.json` to enumerate chunks. Normalize each chunk path to an absolute path (manifests store paths as written by the chunker, which may be relative):

```python
python3 - <<'PYEOF'
import json, os

manifest_path = os.environ['MANIFEST_PATH']
repo_root = os.environ['REPO_ROOT']
with open(manifest_path) as f:
    manifest = json.load(f)

# Emit one line per chunk: INDEX|CHUNK_PATH (absolute)
for chunk in manifest['chunks']:
    chunk_path = chunk['path']
    # Normalize to absolute path so agent always receives an absolute path
    if not os.path.isabs(chunk_path):
        chunk_path = os.path.join(repo_root, chunk_path)
    print(f"{chunk['index']}|{chunk_path}")
PYEOF
```

> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).

> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
```
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="mr-reviewer",
  model="sonnet",
  description="MR review for <SLUG> — chunk <INDEX> of <TOTAL>",
  prompt="slug: <SLUG>
run_id: <RUN>
slug_dir: <SLUG_DIR_ABS>
base: <BASE_REF>
base_sha: <BASE_SHA>
diff_path: <CHUNK_PATH>
style_path: <STYLE_PATH>
dismissed_signatures_path: <DISMISSED_PATH>
voices_available: [<VOICES_AVAILABLE>]
mode: per-chunk
chunk_meta: {\"index\": <INDEX>, \"total\": <TOTAL>, \"manifest_path\": \"<MANIFEST_PATH>\"}
deep: <DEEP>"
)
```

Collect all per-chunk agent returns as a list `CHUNK_AGENT_RETURNS` (one entry per chunk).

After all per-chunk agents complete, dispatch one additional abstraction-only pass with the full diff. This pass runs AFTER the per-chunk batch (sequential, not parallel with the chunks):

> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
```
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="mr-reviewer",
  model="sonnet",
  description="MR abstraction-only pass for <SLUG>",
  prompt="slug: <SLUG>
run_id: <RUN>
slug_dir: <SLUG_DIR_ABS>
base: <BASE_REF>
base_sha: <BASE_SHA>
diff_path: <DIFF_PATH>
style_path: <STYLE_PATH>
dismissed_signatures_path: <DISMISSED_PATH>
voices_available: [<VOICES_AVAILABLE>]
mode: abstraction-only
chunk_meta: null
deep: <DEEP>"
)
```

Capture this return as `ABSTRACTION_AGENT_RETURN`. Proceed to Phase 3 (N+1-return merge path).

---

## Phase 3 — Parse agent return(s) and write MR-REVIEW.md

### Step 3a — Extract findings JSON

**Single-pass mode (`MODE=full`):**

Parse the agent return (`AGENT_RETURN`) by locating the first fenced `json` block (` ```json ... ``` `). Extract and parse its contents as JSON with schema `{"findings": [...]}`. Each finding has: `severity`, `category`, `file`, `line_start`, `line_end`, `title`, `detail`, `citation`.

If no valid JSON block is found, log `mr_all_voices_failed` and exit nonzero with:

```
Error: mr-reviewer agent returned no parseable findings JSON. The agent return was:
<AGENT_RETURN>
```

Set `ALL_FINDINGS` = the parsed findings list.

**Chunked-pass mode (`MODE=per-chunk`):**

Parse each return in `CHUNK_AGENT_RETURNS` by locating its first fenced `json` block. For chunk returns that fail to parse (no valid JSON block), log `mr_voice_failed {voice: "mr-reviewer-chunk-<INDEX>", reason: "malformed_json"}` and skip. Collect all parseable per-chunk findings into `CHUNK_FINDINGS` (union; duplicates not yet removed).

Parse `ABSTRACTION_AGENT_RETURN` by locating its first fenced `json` block. If the abstraction-only return fails to parse, log `mr_voice_failed {voice: "mr-reviewer-abstraction", reason: "malformed_json"}` and treat abstraction findings as empty.

**Dedup per-chunk findings:** identify findings from `CHUNK_FINDINGS` with the same `(file, category, normalized_text)` signature. Normalize: concatenate `title` + `" "` + `detail`, lowercase, collapse internal whitespace to single space, strip leading/trailing punctuation. Keep one finding per signature; merge the `voices` arrays of duplicates.

**Append abstraction findings:** add all abstraction-only findings to the deduped set. Per-chunk findings exclude the `abstraction` category entirely, so there is no overlap between the two sets.

**Final dedup pass:** after appending abstraction findings, run one final dedup pass over the full combined set using the same `(file, category, normalized_text)` key. This ensures any edge-case overlap (e.g., an abstraction finding that duplicates a per-chunk finding with same signature) is eliminated before setting `ALL_FINDINGS`.

Set `ALL_FINDINGS` = deduplicated combined set (per-chunk findings union abstraction findings, with any cross-set duplicates removed).

If `ALL_FINDINGS` is empty AND `MODE=per-chunk` AND all chunk parses failed, log `mr_all_voices_failed` and exit nonzero with:

```
Error: all mr-reviewer chunk agents returned no parseable findings JSON.
```

### Step 3b — Extract summary block

**Single-pass mode:** parse the `## Summary` block from `AGENT_RETURN` (the section after the JSON block).

**Chunked-pass mode:** parse the `## Summary` block from `ABSTRACTION_AGENT_RETURN`. Additionally, for each chunk return in `CHUNK_AGENT_RETURNS`, parse its `## Summary` block and union the `voices_succeeded` and `voices_failed` lists. Aggregate `dismissal_pattern_matches` by summing across all returns.

From the summary block(s), extract these fields:
- `voices_succeeded` — list, e.g. `[claude]`
- `voices_failed` — list
- `dismissal_pattern_matches` — integer

If parsing fails for any field, default to: `voices_succeeded=[claude]`, `voices_failed=[]`, `dismissal_pattern_matches=0`.

### Step 3c — Compute aggregates

From `ALL_FINDINGS` (the merged list from Step 3a — one item per deduplicated finding):

```python
import json as _json, os as _os
_archive_dir = _os.environ['ARCHIVE_DIR']
# `findings` here refers to ALL_FINDINGS from Step 3a
total_findings = len(findings)
by_severity = {"P0": 0, "P1": 0, "P2": 0, "P3": 0, "P4": 0}
by_category = {}
for f in findings:
    by_severity[f["severity"]] += 1
    cat = f.get("category", "uncategorized")
    by_category[cat] = by_category.get(cat, 0) + 1

# Serialize to files so the shell can read them back
with open(f"{_archive_dir}/by_severity.json", "w") as _fh:
    _fh.write(_json.dumps(by_severity))
with open(f"{_archive_dir}/by_category.json", "w") as _fh:
    _fh.write(_json.dumps(by_category))

# Group findings by severity for ordered output (P0 first)
severity_order = ["P0", "P1", "P2", "P3", "P4"]
by_severity_label = {
    "P0": "would cause future bugs",
    "P1": "clear regression",
    "P2": "style drift",
    "P3": "minor hygiene",
    "P4": "taste-only nits",
}
```

Then read back into shell variables:

```bash
BY_SEVERITY_JSON="$(cat "$ARCHIVE_DIR/by_severity.json")"
BY_CATEGORY_JSON="$(cat "$ARCHIVE_DIR/by_category.json")"
TOTAL_FINDINGS="$(python3 -c 'import json,sys; print(sum(json.load(open(sys.argv[1])).values()))' "$ARCHIVE_DIR/by_severity.json")"
```

Assign T-MR-NNN IDs by iterating findings in severity order (P0 first, then P1, P2, P3, P4), then in original finding order within each severity group. IDs start at T-MR-001.

Compute `STYLE_MD_REVISION`:

```bash
STYLE_MD_REVISION="$(git rev-parse HEAD:STYLE.md 2>/dev/null || echo 'unknown')"
```

### Step 3d — Build findings_index

For each finding (in T-MR-NNN order), build a YAML findings_index entry:

```yaml
  - {id: T-MR-001, severity: P1, category: defensive-bloat, file: src/foo.rs, title: "Short title here"}
```

### Step 3e — Write MR-REVIEW.md

Build the full MR-REVIEW.md content using this exact structure:

```markdown
---
artifact: mr-review
slug: <SLUG>
run_id: <RUN>
generated_at: <ISO timestamp — date -u +%Y-%m-%dT%H:%M:%SZ>
base: <BASE_REF>
base_sha: <BASE_SHA>
diff_stat: <DIFF_STAT>
mode: <MODE>
style_md_revision: <STYLE_MD_REVISION>
voices_available: [<VOICES_AVAILABLE comma-separated>]
voices_succeeded: [<voices_succeeded from summary>]
total_findings: <N>
by_severity: {P0: N, P1: N, P2: N, P3: N, P4: N}
findings_index:
  - {id: T-MR-001, severity: P1, category: defensive-bloat, file: src/foo.rs, title: "..."}
  # ... one entry per finding
---

# MR Review — <SLUG>

Findings ranked P0-P4. **Delete any finding you don't want fixed.** Then `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`.

## P0 — would cause future bugs

(findings with severity=P0, each as a task block; omit section if empty)

- [ ] T-MR-NNN. <title>
  **File:** <file>:<line_start>-<line_end>
  **Category:** <category>
  **Voices:** <voices list, comma-separated>
  **Citation:** <citation or "none">
  **Finding:** <detail>
  **Acceptance criteria:**
  - Address the finding in <file> per the detail above.

## P1 — clear regression

(findings with severity=P1; omit section if empty)

## P2 — style drift

(findings with severity=P2; omit section if empty)

## P3 — minor hygiene

(findings with severity=P3; omit section if empty)

## P4 — taste-only nits

(findings with severity=P4; omit section if empty)
```

Rules:
- Omit any severity section that has zero findings — do not emit an empty `## P2 — style drift` section.
- For `line_start`/`line_end`: if both are non-null, format as `<file>:<line_start>-<line_end>`. If only `line_start` is non-null, format as `<file>:<line_start>`. If both are null, just `<file>`.
- `voices` in each finding block: use the per-finding `voices` array from the merged `ALL_FINDINGS` list. In single-voice mode this is always `[claude]`; in multi-voice mode it reflects all voices that raised that finding.
- `Citation`: use the `citation` field from the finding JSON. If null, write `none`.

Write the completed content to **both** paths:
1. `z-harness/<SLUG>/MR-REVIEW.md` — canonical (overwrites any prior file)
2. `<ARCHIVE_DIR>/MR-REVIEW.md` — snapshot (identical content)

```bash
mkdir -p "$SLUG_DIR"
# Write both files with the same content
python3 - <<'PYEOF'
import os

slug_dir = os.environ['SLUG_DIR']
archive_dir = os.environ['ARCHIVE_DIR']
content = os.environ['MR_REVIEW_CONTENT']

canonical = os.path.join(slug_dir, 'MR-REVIEW.md')
snapshot  = os.path.join(archive_dir, 'MR-REVIEW.md')

with open(canonical, 'w') as f:
    f.write(content)
with open(snapshot, 'w') as f:
    f.write(content)

print(f"Wrote {canonical}")
print(f"Wrote {snapshot}")
PYEOF
```

### Step 3f — Emit per-finding telemetry

For each finding emit one `mr_finding_emitted` event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_finding_emitted \
  "$(printf '{"slug":"%s","run_id":"%s","id":"%s","severity":"%s","category":"%s","voices_count":1,"dismissal_match":false}' \
     "$SLUG" "$RUN" "$FINDING_ID" "$FINDING_SEVERITY" "$FINDING_CATEGORY")"
```

### Step 3g — Log mr_run_end

Compute `N_DISPATCHES` before emitting `mr_run_end`. In per-chunk mode, `N_DISPATCHES` = (number of chunks) + 1 (the abstraction-only pass). In full mode, `N_DISPATCHES` = 1.

```bash
if [ "$MODE" = "per-chunk" ]; then
  CHUNK_COUNT="$(python3 -c 'import json; m=json.load(open("'"$ARCHIVE_DIR/chunks/manifest.json"'")); print(len(m["chunks"]))')"
  N_DISPATCHES=$(( CHUNK_COUNT + 1 ))
else
  N_DISPATCHES=1
fi
```

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_run_end \
  "$(python3 -c '
import json, sys
slug, run_id, total, by_sev_json, by_cat_json, voices_s, voices_f, dismissal_matches, mode, n_dispatches = \
  sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7], int(sys.argv[8]), sys.argv[9], int(sys.argv[10])
by_sev = json.loads(by_sev_json)
by_cat = json.loads(by_cat_json)
print(json.dumps({
  "slug": slug,
  "run_id": run_id,
  "total_findings": total,
  "by_severity": by_sev,
  "by_category": by_cat,
  "voices_succeeded": voices_s.split(",") if voices_s else [],
  "voices_failed": voices_f.split(",") if voices_f else [],
  "dismissal_matches": dismissal_matches,
  "mode": mode,
  "n_dispatches": n_dispatches,
}))
' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES" "$MODE" "$N_DISPATCHES")"
```

---

## Phase 4 — Final user message

`N_DISPATCHES` was computed in Step 3g above. Use it directly here.

After writing both files, output a final message to the user:

```
MR review complete.

Results: z-harness/<SLUG>/MR-REVIEW.md
  Mode: <MODE>  Dispatches: <N_DISPATCHES>
  Total findings: <N>
  P0: <N>  P1: <N>  P2: <N>  P3: <N>  P4: <N>
  Voices: <VOICES_AVAILABLE>
  Run ID: <RUN>

Delete what you don't want, then /z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md to apply the survivors.
```

If `DISMISSAL_MATCHES >= 3`, append after the main message:

```
Note: <N> finding(s) match prior dismissal patterns. Consider `/z-style-init --amend` to codify these preferences into STYLE.md so they are not raised again.
```

---

## End-to-end smoke test (manual)

To manually verify this command end-to-end on a small synthetic diff:

1. Create a scratch repo with `git init scratch-repo && cd scratch-repo && git commit --allow-empty -m "init"`.
2. Create a minimal `STYLE.md` with one rule:
   ```markdown
   ---
   schema_version: 1
   source: natural-language
   source_files: []
   repo: scratch-repo
   revision: HEAD
   generated_at: 2026-05-23T00:00:00Z
   ---
   ## Error handling
   ### EH-001: Never swallow exceptions silently
   Do not use bare `except: pass` or `except Exception: pass` without re-raising.
   Rationale: Silent failures make debugging impossible.
   ## Tests
   ## Comments
   ## Naming
   ## Project-specific
   ```
   Commit STYLE.md to main: `git add STYLE.md && git commit -m "add STYLE.md"`.
3. Create a feature branch: `git checkout -b feature/smoke-test`.
4. Add a Python file with a bad pattern:
   ```python
   # payment.py
   def format_price(x):
       return f"${x:.2f}"

   def process():
       try:
           do_something()
       except Exception:
           pass  # swallow silently
   ```
   Commit: `git add payment.py && git commit -m "add payment module"`.
5. Run `/z-mr-review`. Expected outcome:
   - Command completes without error.
   - `z-harness/feature-smoke-test/MR-REVIEW.md` is created with valid YAML frontmatter, at least one finding, `T-MR-001` block present, and the "Delete what you don't want" footer line.

**Chunked-pass smoke test (per-chunk mode — T009):**

To manually verify chunked dispatch, set the threshold below the diff size to force `MODE=per-chunk`:

1. Follow steps 1–4 above, adding several Python files to create a multi-file diff. Commit them.
2. Set `Z_MR_DIFF_CHUNK_BYTES=1` to force per-chunk mode regardless of actual diff size.
3. Run `/z-mr-review`.
4. Expected outcome:
   - `archive/$RUN/chunks/` contains one `.patch` file per modified file plus `manifest.json`.
   - `archive/$RUN/MR-REVIEW.md` exists and has valid frontmatter.
   - MR-REVIEW.md frontmatter shows `mode: per-chunk` in the run_end log.
   - Final user message shows `Mode: per-chunk  Dispatches: <N+1>` where N = number of chunks.
   - MR-REVIEW.md contains both per-chunk category findings (defensive-bloat, test-noise, hygiene, style-drift) and possibly abstraction findings from the abstraction-only pass.

---

## Operating principles

- **Never skip the STYLE.md gate.** There is no `--no-style` flag. No STYLE.md → refuse immediately.
- **Never run on trunk without `--force-on-trunk`.** The check is a safety net against accidentally reviewing main.
- **Voice degradation is a warning, not an error.** Single-voice mode is allowed; the user is informed.
- **Chunking is transparent to the agent.** The agent always receives a single `.patch` file. Polymorphism lives in the orchestrator only.
- **Log everything** via `scripts/log-event.sh`. Dismissal events are emitted per-signature, every run.
- **Archive before overwrite.** Existing `MR-REVIEW.md` is always archived before being replaced.
- **Empty diff exits cleanly.** No review needed if there are no changes.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 2 mr-reviewer (full-diff mode); Phase 2 mr-reviewer per-chunk × N chunks (per-chunk mode); Phase 2 mr-reviewer abstraction-only pass (per-chunk mode) |
| `ask_user` | no | — |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
