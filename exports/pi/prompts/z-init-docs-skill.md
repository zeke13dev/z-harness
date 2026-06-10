# /z-init-docs

You are running **z-harness `/z-init-docs`**. Goal: stand up the two-tier documentation system in this repo so future plans can ground themselves cheaply and so humans get readable navigable docs.

This is a **one-time setup per repo** (safe to re-run for additional scope). After this, `/z-maintain-docs` handles ongoing updates.

## Phase 0 — Preflight

1. `cd` to repo root. Confirm a `z-harness/` dir exists (we want this command run in a repo where z-harness is or will be active; if not, ask user whether to proceed anyway).
2. Check whether `docs/human/` and/or `docs/llm/` already exist:
   - **Both present** → ask the user via `AskUserQuestion`: "Docs exist — extend with new scope / overwrite specific concepts / abort".
   - **Neither present** → fresh init; create both dirs.
   - **One missing** → fill in the missing tier; report.

3. **Version stamp + log run start:**
   ```bash
   Z_HARNESS_PLUGIN_ROOT="${Z_HARNESS_PLUGIN_ROOT:-${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-}}}"
   if [ -z "$Z_HARNESS_PLUGIN_ROOT" ]; then
     for candidate in "${HOME}/plugins/z-harness" "${HOME}/.claude/plugins/z-harness@zeke-tools" "$(pwd)"; do
       if [ -f "${candidate}/scripts/version.sh" ]; then
         Z_HARNESS_PLUGIN_ROOT="$candidate"
         break
       fi
     done
   fi
   if [ -z "$Z_HARNESS_PLUGIN_ROOT" ]; then
     echo "z-init-docs: ERROR: z-harness plugin root not found. Run install.sh --target=codex or set Z_HARNESS_PLUGIN_ROOT." >&2
     exit 1
   fi
   VERSION_BLOB="$(Z_HARNESS_PLUGIN_ROOT="$Z_HARNESS_PLUGIN_ROOT" bash "${Z_HARNESS_PLUGIN_ROOT}/scripts/version.sh")"
   bash "${Z_HARNESS_PLUGIN_ROOT}/scripts/log-event.sh" "docs" init_docs_start "$VERSION_BLOB"
   ```

## Phase 1 — Concept enumeration

Goal: produce a concrete list of `{ slug, source_files[], summary_seed }` to feed Phase 2.

### 1a. Enumerate candidate concepts

Apply these heuristics (run them all; dedupe by directory):

| Signal | Concept slug | Source files |
|---|---|---|
| Each `Cargo.toml` (Rust workspace member) | crate name → kebab-case | all `*.rs` under that crate's `src/` |
| Each `pyproject.toml` / `setup.py` | project name → kebab-case | all `*.py` under that project's package dir |
| Each `package.json` (Node) | package name → kebab-case (strip `@scope/`) | all `*.{ts,tsx,js,jsx}` under `src/` |
| Each `go.mod` | module last segment → kebab-case | all `*.go` under that module |
| Top-level dirs containing source files but no manifest above | dir name → kebab-case | source files in that dir |
| Top-level binary entry points (`src/bin/*.rs`, `cmd/*/main.go`, top-level `*.py` scripts with `if __name__`) | bin filename → kebab-case | single file + its tightest module |

Run language-specific detection commands:
```bash
# Rust crates
find . -name Cargo.toml -not -path './target/*' -not -path '*/node_modules/*' | head -100
# Python packages
find . -name pyproject.toml -o -name setup.py 2>/dev/null | grep -v node_modules | head -50
# Node packages
find . -name package.json -not -path '*/node_modules/*' | head -50
# Go modules
find . -name go.mod | head -50
```

For Rust binaries specifically (common pattern in qt-bot):
```bash
find . -path '*/src/bin/*.rs' -not -path './target/*' | head -100
```

Each binary entry point gets its own concept (because they're often the orchestration surface that benefits most from docs).

### 1b. Scope filter

- **If `--scope <module-or-dir>` argument** → filter Phase 1a candidates to ones whose top dir is under `<module-or-dir>`.
- **If extending existing docs** (INDEX.json exists) → drop candidates whose slug is already a `[x]` "high-confidence" entry in INDEX.json; keep candidates that are missing OR were last_updated more than 90 days ago. Show both lists to user.
- **Otherwise** → all of 1a.

### 1c. User confirmation

Present the candidate list via `AskUserQuestion` (multi-select). Show: slug, source-file count, ~20-char summary. Cap at the user's pick.

If the user picks zero concepts → abort cleanly with "no scope; nothing to do."

If the user picks >25 concepts in one run → warn (large docs runs take real wall time and may hit usage limits before completion). Recommend breaking into 2-3 scoped runs.

Output of Phase 1: a list `CONCEPTS = [{slug, source_files[]}, ...]` for Phase 2 to consume.

### 1d. Per-concept overwrite confirmation

For any concept where `docs/llm/<slug>.json` OR `docs/human/<slug>.md` already exists, ask the user via a SINGLE batched `AskUserQuestion`: "These N concepts already have docs. Overwrite / preserve / overwrite only LLM tier?" Default: preserve (do not overwrite without explicit consent).

## Phase 2 — Per-concept doc generation (parallel)

For each chosen concept, spawn a `doc-updater` subagent in `mode: write` (since this is init and there's nothing to dry-run against). Run up to 3 in parallel:

```
> [pi] Dispatch a subagent here via the subagent tool (see CAPABILITIES.md).
  subagent_type="doc-updater",
  description="Init docs for <concept>",
  prompt="concept: <concept-slug>\nhuman_path: docs/human/<concept-slug>.md\nllm_path: docs/llm/<concept-slug>.json\nsource_files: <list of paths>\nreason: init\nmode: write\nrepo_root: <abs path>"
)
```

Each doc-updater Reads its source files, drafts human + LLM tiers, writes both, and returns.

**Codex fallback:** if native `doc-updater` subagent dispatch is unavailable,
perform the same work inline for each selected concept. Read the listed source
files yourself, write `docs/human/<concept-slug>.md` and
`docs/llm/<concept-slug>.json` directly, then continue to Phase 3. Do not halt
solely because the host lacks a `doc-updater` primitive.

## Phase 3 — Build `docs/llm/INDEX.json`

Each `doc-updater` wrote `docs/llm/<slug>.json` to disk. Aggregate them into the index:

```bash
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
VERSION_BLOB="$(Z_HARNESS_PLUGIN_ROOT="$Z_HARNESS_PLUGIN_ROOT" bash "${Z_HARNESS_PLUGIN_ROOT}/scripts/version.sh")"
SHA="$(printf '%s' "$VERSION_BLOB" | python3 -c 'import json,sys; print(json.load(sys.stdin)["z_harness_version"])')"

# Merge all per-concept JSONs into one index. If INDEX.json exists already
# (extending an existing setup), preserve entries for concepts not in this
# run; replace entries for concepts that were just (re)generated.
python3 - <<PY
import json, glob, os, sys

llm_dir = "docs/llm"
index_path = f"{llm_dir}/INDEX.json"

existing = []
if os.path.exists(index_path):
    try:
        existing = json.load(open(index_path)).get("concepts", [])
    except Exception:
        existing = []
existing_by_slug = {c["slug"]: c for c in existing}

just_written = []
for f in sorted(glob.glob(f"{llm_dir}/*.json")):
    if f.endswith("/INDEX.json"):
        continue
    try:
        d = json.load(open(f))
    except Exception as e:
        sys.stderr.write(f"skip {f}: {e}\n")
        continue
    just_written.append({
        "slug": d.get("concept"),
        "source_file": d.get("source_file", []),
        "last_updated": d.get("last_updated"),
        "confidence": d.get("confidence", "medium"),
        "depends_on": d.get("depends_on", []),
        "consumed_by": d.get("consumed_by", []),
        "summary": (d.get("entry_points", [{}])[0].get("summary", "") if d.get("entry_points") else "")[:120],
    })

# Merge: just_written wins; keep existing entries for slugs not in this run.
written_slugs = {c["slug"] for c in just_written}
merged = just_written + [c for c in existing if c["slug"] not in written_slugs]

# Sort for stable diffs.
merged.sort(key=lambda c: c["slug"])

index = {
    "version": "1",
    "generated_at": "$TS",
    "z_harness_version": "$SHA",
    "concepts": merged,
}
open(index_path, "w").write(json.dumps(index, indent=2) + "\n")
print(f"wrote {len(merged)} concepts to {index_path}")
PY
```

Future `/z-plan` reads this INDEX first to decide where to look — it's the cheap entry point.

## Phase 4 — `docs/human/INDEX.md` (table of contents)

Generate `docs/human/INDEX.md` from `docs/llm/INDEX.json`:

```bash
python3 - <<'PY'
import json, os
from collections import defaultdict

index = json.load(open("docs/llm/INDEX.json"))
concepts = index["concepts"]

# Group by top-level directory of the first source_file (rough "module" cut).
groups = defaultdict(list)
for c in concepts:
    src = c.get("source_file", [])
    top = src[0].split("/", 2)[0] if src and "/" in src[0] else (src[0] if src else "other")
    groups[top].append(c)

out = ["# Docs index", "", f"_Generated: {index['generated_at']}_  ",
       f"_Plugin: z-harness {index['z_harness_version']}_", "",
       "Concepts grouped by top-level module. Each entry links to its human-tier page.",
       "Companion LLM-tier JSON lives at `../llm/<slug>.json`.", ""]

for top in sorted(groups):
    out.append(f"## {top}")
    out.append("")
    out.append("| Concept | Confidence | Source files | Summary |")
    out.append("|---|---|---|---|")
    for c in sorted(groups[top], key=lambda x: x["slug"]):
        srcs = ", ".join(f"`{p}`" for p in c.get("source_file", [])[:3])
        out.append(f"| [{c['slug']}](./{c['slug']}.md) | {c.get('confidence','?')} | {srcs} | {c.get('summary','').strip()} |")
    out.append("")

open("docs/human/INDEX.md", "w").write("\n".join(out))
print("wrote docs/human/INDEX.md")
PY
```

Then write `docs/llm/TAGS.txt` with the 15-tag controlled seed and an empty aliases section:

```bash
python3 - <<'PY'
import os

tags_path = "docs/llm/TAGS.txt"

# Do not overwrite if it already exists (idempotent on re-run).
if not os.path.exists(tags_path):
    content = """\
# Controlled tag seed — do not remove entries; add canonical aliases in section 2.
# Format:
#   Section 1: one tag per line (the controlled set).
#   Section 2 (after blank line): <canonical> = <alias1>, <alias2>
#              <canonical> must appear in section 1.
# /z-maintain-docs TAG_COLLISIONS UX writes to section 2 automatically.
correctness
perf
data-quality
schema
time-window
units
api-boundary
retry-loop
race-condition
dependency
deprecation
lossy-default
ux
observability
compliance

# Aliases: <canonical> = <alias1>, <alias2>
"""
    tmp = tags_path + ".tmp." + str(os.getpid())
    with open(tmp, "w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, tags_path)
    print(f"wrote {tags_path}")
else:
    print(f"{tags_path} already exists — skipped")
PY
```

Then initialize `docs/llm/MEMORIES-FLAT.md` with just the two-line header (no memories exist yet at init time):

```bash
python3 scripts/regenerate-memories-flat.py --repo-root "$(pwd)"
```

## Phase — Invariant discovery (`--invariants`)

**Gate:** This phase only runs when `--invariants` flag is passed. If not passed, skip to Phase 5.

Goal: Bootstrap `docs/INVARIANTS.json` by scanning existing SPEC.md files across the repo for durable, cross-cutting behavioral invariants. This phase is idempotent — re-running on an existing INVARIANTS.json only scans for NEW durable invariants.

### 0. Preflight

Check prerequisites:
- `docs/schemas/invariant.schema.json` must exist (created by T001). If absent, abort with "invariant schema not found — run /z-plan rewrite-z-test-invariants first".
- `scripts/validate-invariants.py` must exist (created by T002). If absent, abort.

### 1. Idempotency check

If `docs/INVARIANTS.json` exists, load it and build the set of existing invariant IDs and descriptions:

```bash
EXISTING_IDS="$(python3 -c "
import json, os
try:
    data = json.load(open('docs/INVARIANTS.json'))
    ids = {inv['id'] for inv in data.get('invariants', [])}
    descs = [inv.get('description', '').lower() for inv in data.get('invariants', [])]
    print(json.dumps({'ids': list(ids), 'descs': descs}))
except Exception:
    print(json.dumps({'ids': [], 'descs': []}))
")"
```

If INVARIANTS.json does NOT exist, proceed with an empty existing set (fresh init).

### 2. Discovery — scan SPEC.md files

Scan all discovery paths for SPEC.md files and extract invariant-like lines:

```bash
# Collect all SPEC.md paths from:
#   - z-harness/<slug>/SPEC.md (active plans)
#   - z-harness/<slug>/archive/<run>/SPEC.md (archived runs)
#   - plans/<slug>/SPEC.md (repo plans)
#   - $BASE/plans/<slug>/SPEC.md (state-dir plans)

SPEC_FILES="$(find z-harness plans -name SPEC.md -type f 2>/dev/null | sort -u)"
```

For each SPEC.md file, extract lines matching these patterns:
- `**INVARIANT:**` — explicit invariant declaration
- `**MUST:**` — mandatory behavioral constraint
- `**MUST NOT:**` — prohibited behavior
- `**DANGER:**` — danger-zone constraint

Each extracted line is a **candidate invariant**. Record for each candidate:
- The verbatim line text
- The source SPEC.md path
- The plan slug (derived from the SPEC.md's parent directory name)

The extract uses the same pattern as `/z-test` Phase 1 invariant extraction. Lines that are exact duplicates across different SPEC.md files count once (the earliest occurrence is kept).

**Graceful fallback:** If no SPEC.md files exist anywhere in the repo, output "no candidates found — no SPEC.md files exist in this repo" and skip to Phase 5. Do NOT error.

### 3. Durability heuristic filter

For each candidate invariant, apply the durability heuristic (same as T004):

A candidate is **durable** if:
- **(a) Multi-plan signal:** The same invariant text (fuzzy match) appears in SPEC.md files from ≥2 different plan slugs, OR
- **(b) Cross-module signal:** The invariant references files from ≥2 distinct top-level directories, OR uses cross-cutting language: "system", "cross-cutting", "cross-module", "across all", "every module", "pipeline-wide"

Fuzzy matching for (a): two candidate texts match if their lowercase, punctuation-stripped versions have Jaccard similarity ≥0.6 on word sets.

Non-durable candidates are logged to `docs/llm/.invariant-candidates-rejected.json` for human review but NOT proposed.

### 4. Candidate proposal — auto-classify

For each durable candidate:

1. **Assign ID:** `inv_NNN` with zero-padded sequential numbering, starting after the highest existing ID (or `inv_001` for fresh init).
2. **Auto-classify tags:** Keyword match against `docs/llm/TAGS.txt`:
   - "fee", "notional", "money" → `correctness`
   - "time", "window", "boundary", "rolling" → `time-window`
   - "schema", "field", "column", "type" → `schema`
   - "unit", "cents", "dollars", "bps" → `units`
   - "api", "endpoint", "rpc", "http" → `api-boundary`
   - "retry", "idempotent" → `retry-loop`
   - "race", "concurrent", "atomic" → `race-condition`
   - "perf", "slow", "latency" → `perf`
   - "data", "quality", "valid" → `data-quality`
   - "deprecated", "remove" → `deprecation`
   - "log", "metric", "observe" → `observability`
   - "default", "fallback", "silent" → `lossy-default`
   - "ux", "user", "display", "show" → `ux`
   - "compliance", "regulatory", "audit" → `compliance`
   - "dependency", "depends", "requires" → `dependency`
   At least one tag must be assigned. If no keywords match, default to `correctness`.
3. **Set severity:** Parse the invariant text for severity signals:
   - "must", "must not", "danger", "critical", "never" → `blocker`
   - "should", "strongly", "important" → `major`
   - otherwise → `minor`
4. **Set source:** `"spec"` (invariants discovered from SPEC.md files).
5. **Set source_files:** The set of file paths referenced in the invariant text OR the SPEC.md's own file list, deduped.
6. **Set last_updated:** Current ISO-8601 timestamp.
7. **Derive failure_class:** Extract the failure scenario from the invariant text — what real-world bug would occur if this invariant is violated. Default to the invariant text itself if no clear failure scenario.

### 5. Present to user

Present the proposed durable invariants via `AskUserQuestion`:

```
<N> durable invariants discovered from <M> SPEC.md files across <K> plans.

<summary table: id, description (truncated to 60 chars), tags, severity, source plan>

Options:
  [Accept all] — write all proposed entries to INVARIANTS.json
  [Pick] — let me choose which to include
  [Skip] — don't write any; candidates logged to docs/llm/.invariant-candidates-rejected.json
```

### 6. Write INVARIANTS.json

For user-accepted invariants, write to `docs/INVARIANTS.json` using atomic write (tmpfile → flush → fsync → os.replace()):

```bash
python3 -c "
import json, os
from datetime import datetime, timezone

data = json.load(open('docs/INVARIANTS.json')) if os.path.exists('docs/INVARIANTS.json') else {'version': 1, 'invariants': []}
data['invariants'].extend(<new_entries_json>)
data['invariants'].sort(key=lambda x: x['id'])
data['generated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

tmp = 'docs/INVARIANTS.json.tmp'
with open(tmp, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\\n')
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, 'docs/INVARIANTS.json')
"
```

Then validate:
```bash
python3 scripts/validate-invariants.py --file docs/INVARIANTS.json
```

If validation fails (exit code ≠ 0), surface the errors and halt — do NOT leave a partial INVARIANTS.json. The atomic write above ensures the previous valid version is preserved until the tmp file passes validation.

### 6a. Regenerate INVARIANTS.md

Generate `docs/INVARIANTS.md` — a human-readable Markdown rendering of INVARIANTS.json. One section per invariant. Same pattern as MEMORIES-FLAT.md regeneration.

```bash
python3 -c "
import json, os
from datetime import datetime, timezone

data = json.load(open('docs/INVARIANTS.json'))
invariants = data.get('invariants', [])

lines = [
    '# System-Level Behavioral Invariants',
    '',
    f\"_Generated: {data.get('generated_at', 'unknown')}_\",
    f\"_Version: {data.get('version', 1)} | {len(invariants)} invariants_\",
    '',
    'Each invariant declares a durable, cross-cutting behavioral constraint. ',
    'Consumed by `/z-test` for behavioral test generation. ',
    'Machine-readable source: `docs/INVARIANTS.json`.',
    '',
    '---',
    '',
]

for inv in invariants:
    inv_id = inv.get('id', '?')
    desc = inv.get('description', '')
    tags = ', '.join(inv.get('tags', []))
    severity = inv.get('severity', 'minor')
    failure_class = inv.get('failure_class', '')
    source_files = ', '.join(inv.get('source_files', [])[:5])
    source = inv.get('source', 'spec')
    last_updated = inv.get('last_updated', '')
    fixture_schema_present = 'yes' if inv.get('fixture_schema') else 'no'

    lines.append(f'## {inv_id} — {desc}')
    lines.append('')
    lines.append(f'**Tags:** {tags}')
    lines.append(f'**Severity:** {severity}')
    lines.append(f'**Failure class:** {failure_class}')
    lines.append(f'**Source files:** {source_files}')
    lines.append(f'**Source:** {source} (from SPEC.md)' if source == 'spec' else f'**Source:** {source}')
    lines.append(f'**Last updated:** {last_updated}')
    lines.append(f'**Fixture schema:** {fixture_schema_present}')
    lines.append('')

# Atomic write
tmp = 'docs/INVARIANTS.md.tmp'
with open(tmp, 'w') as f:
    f.write('\\n'.join(lines) + '\\n')
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, 'docs/INVARIANTS.md')
print(f'wrote INVARIANTS.md with {len(invariants)} invariants')
"
```

Regeneration is idempotent — same INVARIANTS.json always produces the same INVARIANTS.md.

### 6b. Update INDEX.json

Add (or update) the invariants entry in `docs/llm/INDEX.json`:

```bash
python3 -c "
import json, os
from datetime import datetime, timezone

index_path = 'docs/llm/INDEX.json'
if os.path.exists(index_path):
    index = json.load(open(index_path))
else:
    index = {'version': '1', 'generated_at': '', 'z_harness_version': '', 'concepts': []}

now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
inv_entry = {
    'slug': 'invariants',
    'source_files': ['docs/INVARIANTS.json'],
    'last_updated': now,
    'confidence': 'high',
    'summary': 'System-level behavioral invariants — permanent per-repo truths consumed by /z-test for behavioral test generation.'
}

# Replace existing invariants entry or append
concepts = index.get('concepts', [])
found = False
for i, c in enumerate(concepts):
    if c.get('slug') == 'invariants':
        concepts[i] = inv_entry
        found = True
        break
if not found:
    concepts.append(inv_entry)

index['concepts'] = concepts
index['generated_at'] = now

tmp = index_path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(index, f, indent=2)
    f.write('\\n')
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, index_path)
print('updated INDEX.json with invariants entry')
"
```

### 7. Report

Output counts: total candidates found, durable filtered, user-accepted, written to INVARIANTS.json.
Non-durable candidates are logged to `docs/llm/.invariant-candidates-rejected.json` (JSON array) with the reason "not durable".

---

## Phase 5 — Copy default `.z-harness-rsync-exclude`

If `<repo-root>/.z-harness-rsync-exclude` doesn't exist, copy the default from `${Z_HARNESS_PLUGIN_ROOT}/.z-harness-rsync-exclude` when that file exists. This file is used by the `remote-runner` subagent during `/z-implement-all` remote verification. If the default file is missing from the install, skip the copy and report it; do not fail docs initialization.

## Phase 6 — Finalize

1. Summary to user:
   ```
   Initialized docs:
     docs/human/   — <N> concept pages + INDEX.md
     docs/llm/     — <N> concept JSONs + INDEX.json
                     docs/llm/MEMORIES-FLAT.md (regenerated by /z-maintain-docs)
                     docs/llm/TAGS.txt (canonical tag taxonomy; aliases section managed by /z-maintain-docs)
   
   Recommended next:
     git add docs/ && git commit -m "Initialize z-harness docs"
     /z-plan <next feature>   — /z-plan Phase 1 will now read docs/llm/INDEX.json first
   ```
2. Log:
   ```bash
   bash "${Z_HARNESS_PLUGIN_ROOT}/scripts/log-event.sh" "docs" init_docs_end \
     "$(printf '{"concepts_count":%d,"human_dir":"docs/human","llm_dir":"docs/llm"}' "$N")"
   ```

## Hard rules

- **Idempotent.** Re-running with the same scope replaces those concepts' docs; doesn't blow away unrelated ones.
- **Never write outside `docs/human/`, `docs/llm/`, `docs/human/INDEX.md`, `docs/llm/INDEX.json`, and `.z-harness-rsync-exclude`.**
- **No emojis** in docs.
- If a `doc-updater` returns `STATUS: not_enough_info`, surface to user (`AskUserQuestion`) and let them decide whether to drop that concept or provide more context.
