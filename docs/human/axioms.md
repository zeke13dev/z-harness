# Axioms

> Last updated: 2026-05-29
> Covers source: scripts/axiom-store.py, scripts/axiom-extract.py, scripts/build-kernel.py, scripts/resolve-kernel.sh, scripts/build-skill-index.py, agents/axiom-extractor.md, commands/z-axiom-scan.md, commands/z-axiom-list.md, commands/z-axiom-approve.md, commands/z-axiom-reject.md, commands/z-axiom-edit.md, docs/schemas/axiom.schema.json, scripts/config.py, scripts/setup.py

## Overview

Axioms are **advisory** behavioral rules mined from z-harness interaction history. They capture recurring user decisions — how you typically answer workflow questions — and feed that knowledge back into future runs without you having to re-state preferences each time.

The key word is _advisory_. The authority hierarchy is:

```
explicit user instruction  >  hard safety gates  >  config/env (explicit)
   >  routing-preference memory  >  approved axioms (project > global)  >  persona / built-in defaults
```

When an axiom conflicts with a config setting or a routing-preference memory entry, **config/memory wins** and the conflict is surfaced to you via an `axiom_conflict` envelope in the resolver response — it is never silently swallowed. An agreeing axiom is simply recorded in `sources[]` for traceability without altering the resolution outcome.

---

## Axiom lifecycle

Axioms pass through three statuses, and the transition from `candidate` to `approved` **always requires explicit user action**:

```
raw decision events  →  candidate  →  approved  (or rejected)
       (metrics.jsonl)   (store)     (KERNEL.md)
```

### 1. Raw events

Every workflow decision you make is logged to `<base>/metrics.jsonl` (the resolved artifact base — see [telemetry](telemetry.md)) as a structured event (via `scripts/log-decision.sh`). The axiom extractor reads these events to find recurring patterns.

### 2. Candidate

When a grouping of `(event_kind, decision_key, value)` reaches the minimum recurrence threshold (default 3, configurable via `axioms.extract_min_recurrence`), `scripts/axiom-extract.py` synthesizes a draft candidate record. The `agents/axiom-extractor.md` agent (Sonnet-tier) then sharpens the statement, merges near-duplicates, and drafts falsifiability fields (`boundary_conditions`, `counterexamples`). Candidates land in the two-layer axiom store under `candidates/` — they never participate in resolution or kernel compilation.

The extractor is read-only: it never writes the store and never approves anything (Invariant 8).

### 3. Approved

You approve a candidate using `/z-axiom-approve <id>`. The approve flow:
1. Fetches and displays the candidate and its evidence.
2. Shows a falsifiability warning if neither `boundary_conditions` nor `counterexamples` are present (you must pass `--ack-observation` to override).
3. Presents a final confirmation gate (`AskUserQuestion`).
4. Atomically validates the full axiom graph, writes `approved/<id>.json`, and removes the candidate file (O_EXCL lock prevents concurrent approvals from producing a graph-invalid state).
5. Immediately regenerates `KERNEL.md` synchronously.

Rejection (`/z-axiom-reject <id>`) demotes the record to `rejected/` (tombstone), records an optional reason, and also triggers a synchronous kernel regen if the record was previously approved.

---

## Authority boundary — when axioms speak

Axioms participate in `scripts/config.py resolve-question` via `_load_axiom_matches`, which loads the graph-valid approved set and filters for records whose `applies_to` array contains an entry matching the `question_id` being resolved.

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

| Command | What it does |
|---------|-------------|
| `/z-axiom-scan` | Mine candidates from history by dispatching the `axiom-extractor` agent, write returned candidates to the store. `--historical` for a full scan (CPU-heavy). Proposes only — never auto-approves. |
| `/z-axiom-list` | List axiom records from the store as a readable table; filter by `--status`, `--scope`, `--discipline`. |
| `/z-axiom-approve <id>` | Show the candidate, its evidence, and falsifiability state; require explicit confirmation; regenerate KERNEL.md synchronously on approval. |
| `/z-axiom-reject <id>` | Move a candidate or approved record to the tombstone store; optionally record a reason; regenerate kernel if previously approved. |
| `/z-axiom-edit <id> --set <field>=<value>` | Patch any field on a candidate or approved record; re-validates graph and regenerates kernel for approved records. |

All five commands delegate to `scripts/axiom-store.py` subcommands for store mutation.

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
2. **Skill dispatch index** — a compact one-line-per-command table (built by `scripts/build-skill-index.py`).
3. **Approved axioms** — sorted by scope (project before global), discipline applicability, confidence (desc), and recency, truncated to the character budget (`axioms.kernel_budget_chars`, default 6000 chars).

The kernel header carries `source_hash` (SHA-256 over skill index + sorted approved axiom id+statement pairs), `n_axioms`, `drop_count`, `compiler_version`, and `generated_at`. Same inputs always produce a byte-identical body (`generated_at` is the only volatile field, R6).

**Staleness check:** `scripts/resolve-kernel.sh` resolves the correct `KERNEL.md` path (checking `Z_HARNESS_KERNEL_PATH` override, then `.z-harness/KERNEL.md`, then the global path) and emits a loud stderr warning if the embedded `source_hash` does not match a non-mutating recompute via `build-kernel.py --print-hash`. This check is non-blocking and never changes exit code.

**Inheritance:** Six behavioral subagents (implementer, reviewers, and consultant roles) read `KERNEL.md` at invocation time via the `CLAUDE.md` kernel pointer that `/z-setup` installs. The main thread does not read `KERNEL.md` directly — this is an agent-tier inheritance mechanism.

---

## Configuration knobs

| Key | Default | Description |
|-----|---------|-------------|
| `axioms.enabled` | `true` | Enable or disable the axiom layer in the resolver. `false` makes axioms invisible to resolve-question. |
| `axioms.auto_extract_post_run` | `true` | Automatically mine candidates after each run via `axiom-extract.py`. |
| `axioms.extract_min_recurrence` | `3` | Minimum event count in a group before a candidate is proposed. |
| `axioms.kernel_budget_chars` | `6000` | Max characters of axiom text in the compiled kernel. |

Configure via the 4-layer TOML system (see `docs/human/config.md`) or run `/z-setup` and choose the `axioms` wizard scope.

---

## How it interacts with others

- `config` — The resolver (`scripts/config.py _build_resolve_envelope`) applies the axiom layer as the last (lowest-authority) input. `_load_axiom_matches` gates on `axioms.enabled` and delegates store access to `axiom-store.py`. Config/memory always win direct conflicts; conflicts are surfaced, not silenced.
- `agents` — The `axiom-extractor` agent (Sonnet) wraps `axiom-extract.py` with LLM judgement; it is dispatched by `/z-axiom-scan`. The six behavioral subagents (implementer, reviewer, consultants) read `KERNEL.md` at task start.
- `commands` — The five `/z-axiom-*` commands are the user-facing surface. `/z-setup` (axioms scope) configures keys and installs the `CLAUDE.md` kernel pointer.
- `scripts` — `axiom-store.py` is the CRUD + validation layer; `axiom-extract.py` is the miner; `build-kernel.py` is the compiler; `resolve-kernel.sh` is the path resolver + staleness checker; `build-skill-index.py` generates the skill dispatch section of the kernel.
