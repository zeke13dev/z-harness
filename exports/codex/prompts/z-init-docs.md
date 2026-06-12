# /z-init-docs

You are running **z-harness `/z-init-docs`**. Goal: stand up the two-tier documentation system in this repo so future plans can ground themselves cheaply and so humans get readable navigable docs.

This is a **one-time setup per repo** (safe to re-run for additional scope). After this, `/z-maintain-docs` handles ongoing updates.

## Phase 0 — Preflight

1. `cd` to repo root. Confirm a `z-harness/` dir exists (we want this command run in a repo where z-harness is or will be active; if not, ask user whether to proceed anyway).
2. Check whether `docs/human/` and/or `docs/llm/` already exist:
   <!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the docs-exist question (extend / overwrite / abort) via their native channel. Silent omission is forbidden. -->
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

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the concept-selection multi-select question via their native channel. Silent omission is forbidden. -->
Present the candidate list via `AskUserQuestion` (multi-select). Show: slug, source-file count, ~20-char summary. Cap at the user's pick.

If the user picks zero concepts → abort cleanly with "no scope; nothing to do."

If the user picks >25 concepts in one run → warn (large docs runs take real wall time and may hit usage limits before completion). Recommend breaking into 2-3 scoped runs.

Output of Phase 1: a list `CONCEPTS = [{slug, source_files[]}, ...]` for Phase 2 to consume.

### 1d. Per-concept overwrite confirmation

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the per-concept overwrite confirmation question via their native channel. Silent omission is forbidden. -->
For any concept where `docs/llm/<slug>.json` OR `docs/human/<slug>.md` already exists, ask the user via a SINGLE batched `AskUserQuestion`: "These N concepts already have docs. Overwrite / preserve / overwrite only LLM tier?" Default: preserve (do not overwrite without explicit consent).

## Phase 2 — Per-concept doc generation (parallel)

For each chosen concept, spawn a `doc-updater` subagent in `mode: write` (since this is init and there's nothing to dry-run against). Run up to 3 in parallel:

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
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

## Phase 5 — CONTEXT.md domain-glossary bootstrap

**Skip this phase if `--no-glossary` was passed.**

Goal: create `CONTEXT.md` at repo root as a domain ubiquitous-language glossary. This is the single authoritative vocabulary for the project — `/z-plan` and `/z-grill` can read it to stay on-terminology.

### 5a. Idempotency check

If `CONTEXT.md` already exists at repo root:
- Parse its existing term blocks (lines matching `### <Term>`).
- Collect the set of existing terms.
- Continue to 5b to discover candidate additions; skip any term already present.

If it does not exist, continue to 5b.

### 5b. Extract candidate domain terms

<!-- RUNTIME-GATE: subagent; non-supporting drivers must skip this Explore dispatch and notify the user that glossary bootstrap is unavailable without subagent support. -->
Dispatch `Explore` (haiku; upgrade to sonnet only if haiku misses structural patterns) to scan module names, type names, function names, and identifier tokens across the repo. Extract candidate domain nouns: recurring terms that are **not** common English words, not framework names, and not language keywords. Return a ranked list (top ~20) with occurrence counts and one representative usage each.

```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="Explore",
  model="haiku",
  description="Extract domain terms for glossary",
  prompt="Scan all source files in this repo. List the top ~20 recurring domain-specific nouns that appear in module names, type names, function names, or identifier tokens. Exclude: common English words, framework names (e.g. tokio, serde, react), language keywords. For each, provide: term (as it appears in code), occurrence count, one representative file:line usage, and a proposed one-line definition. Repo root: <abs path>."
)
```

### 5c. User confirmation

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the glossary term confirmation question via their native channel. Silent omission is forbidden. -->
Present the candidate list (minus any terms already in CONTEXT.md) to the user via `AskUserQuestion`. For each term show: the raw token, occurrence count, representative usage, and the proposed definition. Ask the user to:
- Confirm or edit each proposed definition.
- Supply an `_Avoid:_` synonym list (zero or more) for any term that has known aliases or common misnomers.
- Flag any terms to drop.
- Optionally add terms the Explore pass missed.

If the user confirms zero terms → skip writing CONTEXT.md this run; report "no terms confirmed; glossary bootstrap skipped."

### 5d. Write CONTEXT.md

Write (or extend) `CONTEXT.md` at repo root using the confirmed terms. Schema:

```markdown
# <Project> — Domain Language

> This file is the authoritative domain vocabulary for <Project>.
> Keep definitions short (one line). Use these exact spellings in code, docs, and plans.
> Re-run `/z-init-docs` to extend coverage; use `/z-maintain-docs --glossary` to refresh.

## Terms

### <Term>

<One-line definition.>

_Avoid:_ <synonym-1>, <synonym-2>

### <Term>

...

## Relationships

<!-- Describe how key terms relate to each other (e.g. "A Plan contains many Tasks"). -->

## Flagged ambiguities

<!-- Terms whose meaning was disputed or unclear during extraction. -->
```

**Idempotent merge rules:**
- Existing term blocks (matched by `### <Term>` heading) are preserved verbatim — never overwrite user-edited content.
- New confirmed terms are appended after the last existing term block, before `## Relationships`.
- `## Relationships` and `## Flagged ambiguities` section bodies are also preserved; do not overwrite user-authored content in those sections.
- When creating CONTEXT.md for the first time, substitute `<Project>` with the repo name (basename of `git rev-parse --show-toplevel`).

After writing, report the path and term count to the user.

## Phase 6 — Copy default `.z-harness-rsync-exclude`

If `<repo-root>/.z-harness-rsync-exclude` doesn't exist, copy the default from `${Z_HARNESS_PLUGIN_ROOT}/.z-harness-rsync-exclude` when that file exists. This file is used by the `remote-runner` subagent during `/z-implement-all` remote verification. If the default file is missing from the install, skip the copy and report it; do not fail docs initialization.

## Phase 7 — Finalize

1. Summary to user:
   ```
   Initialized docs:
     docs/human/   — <N> concept pages + INDEX.md
     docs/llm/     — <N> concept JSONs + INDEX.json
     CONTEXT.md    — <M> domain terms  (omit line if --no-glossary or zero terms confirmed)
   
   Recommended next:
     git add docs/ CONTEXT.md && git commit -m "Initialize z-harness docs"
     /z-plan <next feature>   — /z-plan Phase 1 will now read docs/llm/INDEX.json first
   ```
2. Log:
   ```bash
   bash "${Z_HARNESS_PLUGIN_ROOT}/scripts/log-event.sh" "docs" init_docs_end \
     "$(printf '{"concepts_count":%d,"human_dir":"docs/human","llm_dir":"docs/llm"}' "$N")"
   ```

## Hard rules

- **Idempotent.** Re-running with the same scope replaces those concepts' docs; doesn't blow away unrelated ones.
- **Never write outside `docs/human/`, `docs/llm/`, `docs/human/INDEX.md`, `docs/llm/INDEX.json`, `CONTEXT.md` (repo root), and `.z-harness-rsync-exclude`.**
- **No emojis** in docs.
<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the not_enough_info decision (drop concept / provide more context) via their native channel. Silent omission is forbidden. -->
- If a `doc-updater` returns `STATUS: not_enough_info`, surface to user (`AskUserQuestion`) and let them decide whether to drop that concept or provide more context.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 2 doc-updater (one per chosen concept, up to 3 in parallel); Phase 5b Explore dispatch for domain term extraction |
| `ask_user` | yes | Phase 0 docs-exist decision; Phase 1c concept-selection multi-select; Phase 1d per-concept overwrite confirmation; Phase 5c glossary term confirmation; Hard rules not_enough_info fallback |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
