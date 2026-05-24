---
description: Bootstrap a two-tier docs system in the current repo — docs/human/ (Markdown for humans) and docs/llm/ (token-compacted JSON for fast-lookup by future /z-plan runs). Idempotent; re-runnable to extend coverage.
---

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
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" init_docs_start "$VERSION_BLOB"
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
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="doc-updater",
  description="Init docs for <concept>",
  prompt="concept: <concept-slug>\nhuman_path: docs/human/<concept-slug>.md\nllm_path: docs/llm/<concept-slug>.json\nsource_files: <list of paths>\nreason: init\nmode: write\nrepo_root: <abs path>"
)
```

Each doc-updater Reads its source files, drafts human + LLM tiers, writes both, and returns.

## Phase 3 — Build `docs/llm/INDEX.json`

Each `doc-updater` wrote `docs/llm/<slug>.json` to disk. Aggregate them into the index:

```bash
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
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

## Phase 5 — Copy default `.z-harness-rsync-exclude`

If `<repo-root>/.z-harness-rsync-exclude` doesn't exist, copy the default from `${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/.z-harness-rsync-exclude`. This file is used by the `remote-runner` subagent during `/z-implement-all` remote verification.

## Phase 6 — Finalize

1. Summary to user:
   ```
   Initialized docs:
     docs/human/   — <N> concept pages + INDEX.md
     docs/llm/     — <N> concept JSONs + INDEX.json
   
   Recommended next:
     git add docs/ && git commit -m "Initialize z-harness docs"
     /z-plan <next feature>   — /z-plan Phase 1 will now read docs/llm/INDEX.json first
   ```
2. Log:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" init_docs_end \
     "$(printf '{"concepts_count":%d,"human_dir":"docs/human","llm_dir":"docs/llm"}' "$N")"
   ```

## Hard rules

- **Idempotent.** Re-running with the same scope replaces those concepts' docs; doesn't blow away unrelated ones.
- **Never write outside `docs/human/`, `docs/llm/`, `docs/human/INDEX.md`, `docs/llm/INDEX.json`, and `.z-harness-rsync-exclude`.**
- **No emojis** in docs.
- If a `doc-updater` returns `STATUS: not_enough_info`, surface to user (`AskUserQuestion`) and let them decide whether to drop that concept or provide more context.
