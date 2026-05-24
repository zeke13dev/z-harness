# Style Init

> Last updated: 2026-05-23
> Covers source: commands/z-style-init.md

## What it does

`/z-style-init` authors a project `STYLE.md` — the style guide that `/z-mr-review` uses to detect rule violations and idiom drift. The command has two modes: **bootstrap** (create a new STYLE.md from scratch) and **amend** (add rules derived from repeated dismissal patterns in past review runs).

`STYLE.md` lives at the repository root. Its schema is documented in `docs/human/STYLE-md-schema.md`.

## Bootstrap mode (no `--amend`)

Run `/z-style-init` on a repo that has no STYLE.md. The command refuses if STYLE.md already exists — use `--amend` instead.

### The Capture phase

The command builds your STYLE.md from the most idiomatic files in your repo, not from templates. This is the "Capture" insight: style rules grounded in code you already consider correct are more accurate and less controversial than rules invented from scratch.

Steps:

1. **Heuristic prefilter.** All tracked files are listed via `git ls-files`. Files that are generated, vendor, or too short/long (< 50 or > 800 lines) are excluded. The exclusion list includes `node_modules/`, `vendor/`, `dist/`, `target/`, `*.pb.go`, `*_pb2.py`, `migrations/`, lock files, and minified assets.
2. **Idiomatic-file ranking.** A Sonnet subagent ranks the candidates by idiomatic-ness and picks the top 5.
3. **User confirmation.** You are shown the 5 chosen files and may accept them, edit the list, ask for a different 5, or abandon. This gate prevents legacy god-objects from anchoring STYLE.md to bad patterns.
4. **File read.** The confirmed 5 files are read into context as Capture material.

### Interview phase

Up to 4 questions are asked interactively (via `AskUserQuestion`):

- Error handling philosophy — defensive or propagate-up?
- Testing posture — mock-heavy, integration-heavy, or mixed?
- Comment policy — when to comment and when not to?
- Anything else the project insists on (free text).

If you pass `--ingest <path>`, the interview is skipped and your existing guide at `<path>` is used as the input instead.

### Critique and approval

After the draft is generated from the Capture files and interview answers, the configured `consultant-primary` and `consultant-secondary` providers critique it in parallel (flagging missing categories, vague rules, contradictions). The critique is applied, and you are asked to approve, edit, re-critique, or abandon.

Approved STYLE.md is written to the repo root. The `style_init_complete` event is logged and a push notification is sent.

## Amend mode (`--amend`)

Run `/z-style-init --amend` to add new rules derived from findings you have repeatedly dismissed in past `/z-mr-review` runs. The command refuses if no STYLE.md exists yet.

Steps:

1. **Scan archives.** `scripts/extract-dismissals.py` walks `z-harness/*/archive/*/MR-REVIEW.md` snapshots (default: most recent 10 runs, `--global` scans all slugs) to identify dismissed finding signatures.
2. **Cluster.** Dismissed signatures are grouped by category and text similarity (Jaccard token-overlap ≥ 0.6 after stopword removal). Clusters with fewer than 2 members are discarded — single-occurrence dismissals are not considered patterns.
3. **Propose rules.** A Sonnet subagent examines each cluster alongside the current STYLE.md and proposes new rules with stable IDs in the next-free range for each section.
4. **User review.** You review proposed rules per cluster: add as-drafted, or reject. (If you want to customize a rule before adding it, reject it and manually edit STYLE.md afterward.) Approved rules are appended to the relevant STYLE.md sections.

The `style_amend_complete` event is logged with cluster counts. The `schema_version` frontmatter field is unchanged by amend.

## Rule ID convention

Rules use section-prefixed, zero-padded, three-digit IDs:

| Section | Prefix | Example |
|---|---|---|
| Error handling | `EH-` | `EH-001` |
| Tests | `T-` | `T-001` |
| Comments | `C-` | `C-001` |
| Naming | `N-` | `N-001` |
| Project-specific | `P-` | `P-001` |

Rule IDs are **append-only and never reused**. When a rule is retired, it is replaced by a tombstone comment (`<!-- EH-003 retired 2026-06-01 -->`) so that historical `mr-reviewer` citations remain traceable. The `mr-reviewer` agent cites rules by their ID (e.g. `Citation: EH-001`).

## See also

- `docs/human/STYLE-md-schema.md` — full schema reference with a worked Rust example.
- `docs/human/mr-reviewer.md` — the review command that consumes STYLE.md.
