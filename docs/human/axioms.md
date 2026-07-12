# Axioms

> Last updated: 2026-07-09
> Covers source: scripts/axiom-store.py, scripts/axiom-extract.py, scripts/build-kernel.py, scripts/resolve-kernel.sh, scripts/build-skill-index.py, agents/axiom-extractor.md, skills/z-axiom-scan/SKILL.md, skills/z-axiom-list/SKILL.md, skills/z-axiom-approve/SKILL.md, skills/z-axiom-reject/SKILL.md, skills/z-axiom-edit/SKILL.md, docs/schemas/axiom.schema.json, scripts/config.py, scripts/setup.py

## Overview

Axioms are **advisory** behavioral rules mined from z-harness interaction history. They capture recurring user decisions — how you typically answer workflow questions — and feed that knowledge back into future runs without you having to re-state preferences each time.

The key word is _advisory_. The authority hierarchy is:

```
explicit user instruction  >  hard safety gates  >  config/env (explicit)
   >  routing-preference memory  >  approved axioms (project > global)  >  persona / built-in defaults
```

When an axiom conflicts with a config setting or a routing-preference memory entry, **config/memory wins** and the conflict is surfaced to you via an `axiom_conflict` envelope in the resolver response — it is never silently swallowed. An agreeing axiom is simply recorded in `sources[]` for traceability without altering the resolution outcome.

**Important, current-as-of-2026-07-09 caveat:** the underlying store/resolver/kernel machinery (`axiom-store.py`, `axiom-extract.py`, `build-kernel.py`, `resolve-kernel.sh`, `config.py`, the `axiom-extractor` agent) is fully live and correctly wired. The five user-facing `/z-axiom-*` slash commands are **not** currently functional — see Gotchas below.

---

## Axiom lifecycle

Axioms pass through three statuses, and the transition from `candidate` to `approved` **always requires explicit user action**:

```
raw decision events  →  candidate  →  approved  (or rejected)
       (metrics.jsonl)   (store)     (KERNEL.md)
```

### 1. Raw events

Every workflow decision you make is logged to `<base>/metrics.jsonl` (the resolved artifact base — see [telemetry](telemetry.md)) as a structured event (via `scripts/log-decision.sh`). The axiom extractor reads these events to find recurring patterns.

Since the Phase-D external-base flip, `metrics.jsonl` no longer lives under `repo_root/z-harness/` by default. `axiom-extract.py` now resolves the metrics path via `plan-path.sh base_dir` (honouring the full 5-tier fallback), with a legacy in-repo fallback when `plan-path.sh` is unavailable.

### 2. Candidate

When a grouping of `(event_kind, decision_key, value)` reaches the minimum recurrence threshold (default 3, configurable via `axioms.extract_min_recurrence`), `scripts/axiom-extract.py` synthesizes a draft candidate record. The `agents/axiom-extractor.md` agent (Sonnet-tier) then sharpens the statement, merges near-duplicates, and drafts falsifiability fields (`boundary_conditions`, `counterexamples`). Candidates land in the two-layer axiom store under `candidates/` — they never participate in resolution or kernel compilation.

The extractor is read-only: it never writes the store and never approves anything (Invariant 8).

### 3. Approved

You approve a candidate using `/z-axiom-approve <id>`. The approve flow (as implemented in `axiom-store.py cmd_approve` — see the command-availability caveat in Gotchas):
1. Fetches and displays the candidate and its evidence.
2. Shows a falsifiability warning if neither `boundary_conditions` nor `counterexamples` are present (you must pass `--ack-observation` to override).
3. Presents a final confirmation gate (`AskUserQuestion`).
4. Atomically validates the full axiom graph, writes `approved/<id>.json`, and removes the candidate file (O_EXCL lock prevents concurrent approvals from producing a graph-invalid state).
5. Immediately regenerates `KERNEL.md` synchronously.

Rejection (`/z-axiom-reject <id>`) demotes the record to `rejected/` (tombstone), records an optional reason, and also triggers a synchronous kernel regen if the record was previously approved.

---

## Authority boundary — when axioms speak

Axioms participate in `scripts/config.py resolve-question` via `_load_axiom_matches`, which loads the graph-valid approved set and filters for records whose `applies_to` array contains an entry matching the `question_id` being resolved. Each `applies_to` entry is a `"<question_id>:<value>"` string. The `<value>` half is validated against the registered choices for that question — entries with unknown values are silently dropped and do not participate.

Three outcomes are possible:

| Situation | `source` field | Effect |
|-----------|---------------|--------|
| Axiom agrees with already-resolved config/memory value | listed in `sources[]` only | No change to result/strength |
| Config is default (`ask`) AND memory is silent — axiom fills the gap | `"axiom"` | `strength: "soft"`, result mapped via `RESULT_MAP` |
| Axiom value differs from config/memory resolution | `"axiom_conflict"` | Conflict surfaced; nested `axiom: {id, statement, conflict: true}` added to envelope |

Free-form behavioral axioms (no `applies_to` field) appear only in `KERNEL.md` and never enter the resolver.

The axiom layer is gated by `axioms.enabled` (default `true`). When disabled, `_load_axiom_matches` returns `[]` and the resolver behaves identically to a pre-axioms run (backward-compatible).

---

## The command family

| Command | What it is documented to do | Currently functional? |
|---------|-------------|-----------------------|
| `/z-axiom-scan` | Mine candidates from history by dispatching the `axiom-extractor` agent, write returned candidates to the store. `--historical` for a full scan (CPU-heavy). Proposes only — never auto-approves. | **No — broken stub (see Gotchas)** |
| `/z-axiom-list` | List axiom records from the store as a readable table; filter by `--status`, `--scope`, `--discipline`. | **No — broken stub** |
| `/z-axiom-approve <id>` | Show the candidate, its evidence, and falsifiability state; require explicit confirmation; regenerate KERNEL.md synchronously on approval. | **No — broken stub** |
| `/z-axiom-reject <id>` | Move a candidate or approved record to the tombstone store; optionally record a reason; regenerate kernel if previously approved. | **No — broken stub** |
| `/z-axiom-edit <id> --set <field>=<value>` | Patch any field on a candidate or approved record; re-validates graph and regenerates kernel for approved records. | **No — broken stub** |

All five commands are *designed* to delegate to `scripts/axiom-store.py` subcommands for store mutation — and that delegation logic is what the descriptions above still accurately describe. But invoking any of them today does not actually run that logic. See the first Gotcha below for the mechanism and a manual workaround.

---

## Store layout

Axioms live in two layers — global and project — each following the same directory structure:

```
$XDG_CONFIG_HOME/z-harness/axioms/      ← global layer
  candidates/<id>.json
  approved/<id>.json
  rejected/<id>.json

<git-root>/.z-harness/axioms/           ← project layer
  candidates/<id>.json
  approved/<id>.json
  rejected/<id>.json
```

Project records shadow global records with the same id. Both layers survive `/z-update` because they are outside the plugin install tree.

The `.z-harness/axioms/` directory and `.z-harness/KERNEL.md` should be added to your project `.gitignore` (the `/z-setup` axioms wizard offers to do this automatically).

---

## Kernel compilation and inheritance

`scripts/build-kernel.py` assembles `KERNEL.md` — the single artifact that every behavioral subagent reads at the start of each task. The kernel contains three sections:

1. **Authority precedence** — the authority boundary verbatim from SPEC, so agents always know axioms are advisory.
2. **Skill dispatch index** — a compact one-line-per-command table (built by `scripts/build-skill-index.py`, crawling `skills/*/SKILL.md` frontmatter — `skills/` is once again the sole crawled source tier, per the z-harness-portability re-flip).
3. **Approved axioms** — sorted by scope (project before global), discipline applicability, confidence (desc), and recency, truncated to the character budget (`axioms.kernel_budget_chars`, default 6000 chars).

The kernel header carries `source_hash` (SHA-256 over skill index + sorted approved axiom id+statement pairs), `n_axioms`, `drop_count`, `compiler_version`, and `generated_at`. Same inputs always produce a byte-identical body (`generated_at` is the only volatile field, R6).

Because `build-skill-index.py` reads only skill *frontmatter* (name/description), the broken `/z-axiom-*` command bodies described in Gotchas do **not** corrupt the kernel's skill dispatch index — the frontmatter for all five is intact, so they still list correctly in `KERNEL.md`. It is only the on-disk command *procedure* that is dead.

**Staleness check:** `scripts/resolve-kernel.sh` resolves the correct `KERNEL.md` path (checking `Z_HARNESS_KERNEL_PATH` override, then `.z-harness/KERNEL.md`, then the global path) and emits a loud stderr warning if the embedded `source_hash` does not match a non-mutating recompute via `build-kernel.py --print-hash`. This check is non-blocking and never changes exit code.

**Inheritance:** Behavioral subagents (implementer, reviewers, and consultant roles) read `KERNEL.md` at invocation time via the `CLAUDE.md` kernel pointer that `/z-setup` installs. The main thread does not read `KERNEL.md` directly — this is an agent-tier inheritance mechanism. `/z-plan`, `/z-audit`, and `/z-debug` all invoke `resolve-kernel.sh` to inject a `kernel_path` into behavioral agent dispatches.

---

## Configuration knobs

| Key | Default | Description | Configurable via `/z-setup` axioms wizard? |
|-----|---------|--------------|------|
| `axioms.enabled` | `true` | Enable or disable the axiom layer in the resolver. `false` makes axioms invisible to resolve-question. | Yes |
| `axioms.auto_extract_post_run` | `true` | Automatically mine candidates after each run via `axiom-extract.py`. | Yes |
| `axioms.extract_min_recurrence` | `3` | Minimum event count in a group before a candidate is proposed. | **No — TOML/env only, see Gotchas** |
| `axioms.kernel_budget_chars` | `6000` | Max characters of axiom text in the compiled kernel. | Yes |

Configure via the 4-layer TOML system (see `docs/human/config.md`) or run `/z-setup` and choose the `axioms` wizard scope for the three wizard-exposed keys.

---

## How it interacts with others

- `config` — The resolver (`scripts/config.py _build_resolve_envelope`) applies the axiom layer as the last (lowest-authority) input. `_load_axiom_matches` gates on `axioms.enabled`, validates `<value>` against registered QUESTION_IDS choices, and delegates store access to `axiom-store.py`. Config/memory always win direct conflicts; conflicts are surfaced, not silenced.
- `agents` — The `axiom-extractor` agent (Sonnet) wraps `axiom-extract.py` with LLM judgement; it is *designed* to be dispatched by `/z-axiom-scan` (currently broken — see Gotchas). Behavioral subagents (implementer, reviewer, auditor, consultants, spec-precheck, pre-reviewer, self-reviewer) each read `KERNEL.md` at task start, either via a `kernel_path` injected by the caller or via self-resolution with `resolve-kernel.sh`.
- `commands` — The five `/z-axiom-*` skills are the intended user-facing surface but are currently non-functional stubs (see Gotchas). `/z-setup` (axioms scope) configures a subset of axioms keys and installs the `CLAUDE.md` kernel pointer. `/z-plan`, `/z-audit`, and `/z-debug` each resolve the kernel path once at run start and inject it into every behavioral agent dispatch.
- `scripts` — `axiom-store.py` is the CRUD + validation layer; `axiom-extract.py` is the miner (resolves `metrics.jsonl` via `plan-path.sh base_dir`); `build-kernel.py` is the compiler; `resolve-kernel.sh` is the path resolver + staleness checker; `build-skill-index.py` generates the skill dispatch section of the kernel by crawling `skills/*/SKILL.md` frontmatter.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/axiom-store.py:1` — `axiom-store` — CRUD + validation for the two-layer (global+project) axiom store. Subcommands: path, add, list, get, validate, approve, reject, edit.
- `scripts/axiom-store.py:336` — `validate_graph` — R1 shared graph validator (referential integrity, mutual conflict, acyclicity). Used by both approve and build-kernel.py.
- `scripts/axiom-store.py:488` — `_load_active_set` — R1 shared load semantics for approve and build-kernel.py. Project shadows global by id.
- `scripts/axiom-store.py:927` — `cmd_approve` — Atomic approve: O_EXCL lock, prospective graph validation, demote supersedes target, regen kernel.
- `scripts/axiom-extract.py:1` — `axiom-extract` — Mine candidate axioms from metrics.jsonl. Resolves path via plan-path.sh. Invariant 8: never writes the store.
- `scripts/axiom-extract.py:105` — `_resolved_base_dir` — Resolve artifact base directory via plan-path.sh base_dir (Phase-D external-base).
- `scripts/build-kernel.py:1` — `build-kernel` — Compile KERNEL.md for a scope. R1/R2/R5/R6 invariants. --print-hash: non-mutating hash mode.
- `scripts/resolve-kernel.sh:1` — `resolve-kernel` — Resolve absolute KERNEL.md path; non-blocking staleness check via --print-hash.
- `scripts/build-skill-index.py:179` — `build_skill_index` — Crawl `skills/*/SKILL.md` frontmatter; emit compact dispatch table for KERNEL.md. `skills/` is once again the sole crawled source tier (line moved from 198→179 since the last doc refresh; behavior itself flipped back from `commands/` to `skills/` under the z-harness-portability plan).
- `agents/axiom-extractor.md:1` — `axiom-extractor` — Sonnet-tier agent: sharpen statements, merge near-duplicates, draft falsifiability fields, cap at <=5 candidates.
- `scripts/config.py:2562` — `_load_axiom_matches` — Load graph-valid approved axioms matching a question_id; validates <value> against QUESTION_IDS choices; gates on axioms.enabled. (line moved from 2109→2562 since the last doc refresh.)
- `scripts/config.py:2928` — `_build_resolve_envelope` — Core resolver applying axiom layer: agree / gap-fill / conflict outcomes. (line moved from 2475→2928 since the last doc refresh.)
- `scripts/setup.py:1303` — `_wizard_axioms` — /z-setup wizard for axioms scope: configures axioms.enabled, axioms.auto_extract_post_run, axioms.kernel_budget_chars only (NOT axioms.extract_min_recurrence — see Gotchas); offers to add .z-harness/axioms/ and .z-harness/KERNEL.md to project .gitignore; installs the CLAUDE.md kernel pointer.
- `skills/z-axiom-scan/SKILL.md:1`, `skills/z-axiom-list/SKILL.md:1`, `skills/z-axiom-approve/SKILL.md:1`, `skills/z-axiom-reject/SKILL.md:1`, `skills/z-axiom-edit/SKILL.md:1` — **broken self-referential stubs.** Frontmatter (name/description/argument-hint) is intact and correctly feeds `build-skill-index.py`. The body of each is exactly one line of instruction: "Read and execute `skills/<name>/SKILL.md` in full, passing `$ARGUMENTS` through verbatim" — which points at itself and resolves to nothing. See Gotchas for root cause and recovery path.
<!-- AUTO-END: entry-points -->

## Edge cases / gotchas

- **All five `/z-axiom-*` commands are currently broken self-referential stubs — this is a real regression, not documentation drift.** Root-caused via git history: the real 84–242-line procedure bodies for all five commands lived at `skills/z-axiom-*/SKILL.md` from the original `inherited-agents-axioms` implementation (commit `6d9d55b`) through commit `399ab4a` ("refactor: remove skills/ dir — commands/ is the single source"), which **deleted** `skills/z-axiom-*/SKILL.md` and left a thin redirect under `commands/` (named `z-axiom-*.md`) pointing at the now-deleted `skills/` target — orphaning the redirect instead of merging the real content back into `commands/`. The later `commands/`→`skills/` re-flip (T001, commit `2494756`, "migrate the per-command markdown files to `skills/<id>/SKILL.md`") renamed that already-broken stub verbatim back into `skills/z-axiom-*/SKILL.md`, so the dangling self-reference just moved location rather than being fixed. **Recovery path:** the original procedure content is recoverable via `git show 399ab4a^:skills/z-axiom-scan/SKILL.md` (and the equivalent for `z-axiom-list`, `z-axiom-approve`, `z-axiom-reject`, `z-axiom-edit`) — each needs its post-`399ab4a` frontmatter (name/runtime/driver_features_required fields) merged with its pre-`399ab4a` body. This is a real-fix task for `/z-plan`, not something doc-updater can perform.
- **The broken commands do not affect the kernel or the resolver.** `build-skill-index.py` only reads frontmatter (name + description), so `KERNEL.md`'s skill dispatch index still lists all five commands correctly. `scripts/config.py`'s `_load_axiom_matches` / `_build_resolve_envelope` and the axiom store CRUD in `axiom-store.py` are entirely independent of the command layer and work exactly as documented when driven directly (e.g. `python3 scripts/axiom-store.py approve ax-1a2b3c4d --scope global`).
- **Manual workaround until the commands are fixed:** drive `scripts/axiom-extract.py`, `scripts/axiom-store.py`, and `scripts/build-kernel.py` directly via Bash, or dispatch the `axiom-extractor` agent by hand with the same `repo_root`/`mode` inputs the (broken) `/z-axiom-scan` command would have passed. See `agents/axiom-extractor.md` for the exact dispatch shape and `scripts/axiom-store.py`'s module docstring for subcommand syntax.
- **`axioms.extract_min_recurrence` is no longer exposed by the `/z-setup` axioms wizard**, even though the config key, default (3), and validator are all still fully live in `scripts/config.py`. The wizard's `axioms_keys` list only prompts for `axioms.enabled`, `axioms.auto_extract_post_run`, and `axioms.kernel_budget_chars`. Set `extract_min_recurrence` via direct TOML edit or `config.py set axioms.extract_min_recurrence <n>` instead.
- **`build-skill-index.py` crawls `skills/*/SKILL.md` frontmatter, not `commands/`.** The `commands/` directory no longer exists in this repo. This reverses what the previous doc revision said (which reflected the interim `commands/`-only state between `399ab4a` and the portability re-flip) — see the entry-points list above for the confirmed current line numbers.
- **Axioms advisory — config/memory win direct conflicts but conflict is surfaced:** a config or memory entry that disagrees with an axiom produces `source='axiom_conflict'` in the resolve-question envelope. The result/strength/rule_id from config/memory still apply; the axiom object is informational. Callers must handle the `axiom_conflict` source value.
- **Kernel regen synchronous on approve/reject/edit:** any of these three mutations blocks until `build-kernel.py` completes. If the kernel cannot be written (e.g., disk full), the command exits with `*_kernel_stale` and the mutation HAS already been committed to the store. The store mutation is NOT rolled back on kernel failure.
- **Store in user-space survives /z-update:** `$XDG_CONFIG_HOME/z-harness/axioms/` (global) and `<git-root>/.z-harness/axioms/` (project) are outside the plugin install tree. `/z-update` does not touch these directories.
- **Gap-fill vs agree vs conflict:** axioms only change the resolution outcome in the gap-fill case (config=ask default + memory silent). When config or memory has a non-default value, the axiom layer records the axiom in `sources[]` (agree) or emits `axiom_conflict` (disagree) but does NOT change result/strength. Treat `strength='soft'` as the marker for an axiom-driven gap-fill.
- **Free-form behavioral axioms (no `applies_to` field) never enter the resolver.** They appear only in `KERNEL.md` and are read by behavioral subagents at task start. The resolver only consults axioms that have a matching `applies_to` entry.
- **`_load_axiom_matches` validates `<value>` against QUESTION_IDS choices:** each `applies_to` entry is `"<question_id>:<value>"`. The `<value>` half must be a registered choice for that question or the match is silently dropped. Hand-authored axioms with an outdated value (e.g., after a choice was renamed in config.py) will not participate in resolution.
- **axiom-extract.py strips extractor-only fields before emitting to stdout.** The fields `possible_duplicate_of` and `notes` are used internally during mining but are NOT in the schema (`additionalProperties:false`) and would cause `axiom-store.py add` to reject the record. These annotations appear on stderr as `{"advisories":[...]}`.
- **Fuzzy dedup in axiom-extract.py flags but does not drop duplicates.** Token-set Jaccard >= 0.9 triggers a `possible_duplicate_of` advisory on stderr. The `axiom-extractor` agent is responsible for actually merging near-duplicates before returning candidates to the caller.
- **resolve-kernel.sh staleness check is non-blocking and best-effort.** It shells out to `build-kernel.py --print-hash`; if that fails for any reason (missing script, non-zero exit, parse error), it silently skips the check. A stale kernel does not prevent agents from reading the file.
- **Mutual conflict exemption requires demotion:** `validate_graph` check 2 only exempts a supersedes relationship from mutual-conflict errors if the superseded record is NOT approved. If both records are approved and one supersedes the other, it is still an error — the superseded record must be rejected first.
- **Project scope _load_active_set always includes global records.** This means a project-scope approve sees global approved records for graph validation — a conflict between a project candidate and a global approved record will be caught.
- **metrics.jsonl is now resolved via external base:** Since the Phase-D flip, `axiom-extract.py` calls `plan-path.sh base_dir` to find the aggregate metrics file; the hardcoded `repo_root/z-harness/metrics.jsonl` path is only a last-resort fallback. Running the (currently broken) `/z-axiom-scan` — or `axiom-extract.py` directly — against a repo where the external base is not set up will mine zero candidates from the wrong location.

## Examples

- Mine candidates from a finished run (workaround — dispatch the agent directly, since `/z-axiom-scan` is currently broken): `Agent(subagent_type="axiom-extractor", description="Axiom mining", prompt="repo_root: <path>\nmode: post-run <run-id>")`, then pipe each returned candidate into `python3 scripts/axiom-store.py add --scope global --from-json -`
- Review candidates directly: `python3 scripts/axiom-store.py list --status candidate`
- Approve one directly: `python3 scripts/axiom-store.py approve ax-1a2b3c4d --scope global`
- Patch a field directly: `python3 scripts/axiom-store.py edit ax-1a2b3c4d --set confidence=0.9`
- Full historical scan directly: `python3 scripts/axiom-extract.py --historical --repo-root <path>`
