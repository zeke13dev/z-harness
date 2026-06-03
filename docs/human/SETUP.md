# SETUP — z-harness configuration runbook

> Last updated: 2026-06-03
> Covers source: scripts/setup.py, scripts/setup.sh, commands/z-setup.md, docs/human/SETUP.md

---

## Overview

z-harness has eight configuration surfaces. Each surface has a distinct persistence class and precedence level.

| Surface | File / mechanism | Persistence class | Writable via |
|---------|-----------------|-------------------|--------------|
| TOML global | `~/.config/z-harness/config.toml` | `global` | `config.py set --scope global` |
| TOML repo | `.z-harness/config.toml` | `repo` | `config.py set --scope project` |
| Env-only knobs | Shell environment | `env` (not persistent) | Shell profile or `export` |
| providers.json | `~/.config/z-harness/providers.json` or `.z-harness/providers.json` | `provider_file` | `/z-providers-discover` |
| Personas | `~/.config/z-harness/personas/` or `.z-harness/personas/` | `persona_file` | Direct file edit |
| docs INDEX.json | `docs/llm/INDEX.json` | `generated_docs` | `/z-init-docs` |
| Routing-preference memories | `docs/llm/*.json` (field: `memories[]`) | `memory` | `/z-suggest-memory` |
| Posture presets | Built into `scripts/setup.py` | — | `/z-setup apply --posture <name>` |

Config precedence (highest wins): env > repo TOML > global TOML > defaults.

---

## First-time setup

Recommended sequence for a fresh install:

```
/z-setup inspect
```

Shows the current resolved state across all surfaces. Look for `(not set)` or `(absent)` entries to identify gaps.

```
/z-setup wizard
```

Guided concern-grouped flow: notifications → workflow → overnight → providers → personas → docs → memories → axioms → Final review. Asks about each gap and writes confirmed changes. Safe to re-run: diffs are shown and confirmed before any write.

Alternatively, for a one-shot bootstrap:

```
/z-setup apply --posture interactive
```

Sets all TOML keys to the interactive preset defaults. For overnight or CI environments:

```
/z-setup apply --posture overnight
/z-setup apply --posture ci-batch
```

If the inspect view shows providers or docs as missing, also run:

```
/z-providers-discover
/z-init-docs
```

The wizard detects these gaps and tells you when to run them. `/z-setup` itself does not invoke these commands.

---

## Posture presets

Posture presets are defined verbatim in `scripts/setup.py` as `POSTURE_PRESETS`.

### interactive

Default for fresh installs. All workflow gates are interactive (`ask`). No env vars required.

| Key | Value |
|-----|-------|
| `notify.level` | `approval_only` |
| `docs.always_apply` | `always` |
| `workflow.audit_to_amend` | `ask` |
| `workflow.slug_confirm` | `ask` |
| `workflow.implement_all_proceed` | `ask` |
| `workflow.review_all_proceed` | `ask` |
| `workflow.plan_decisions_approval` | `ask` |

Env vars: none.

### overnight

Suitable for `/z-overnight` runs where workflow gates should halt instead of blocking. Requires env vars to be exported in your shell for the session.

| Key | Value |
|-----|-------|
| `notify.level` | `approval_only` |
| `workflow.implement_all_proceed` | `halt` |
| `workflow.review_all_proceed` | `halt` |
| `workflow.plan_decisions_approval` | `halt` |

Env vars emitted by `apply`:

```bash
export Z_HARNESS_NO_ASK='halt'
export Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE='{"workflow.slug_confirm":"recommend_derived","workflow.audit_to_amend":"amend"}'
```

These are NOT written to any file. Add them to your shell profile manually if you want them persistent.

### ci-batch

For non-interactive CI pipelines. All gates auto-proceed or halt immediately.

| Key | Value |
|-----|-------|
| `notify.level` | `off` |
| `workflow.audit_to_amend` | `amend` |
| `workflow.slug_confirm` | `recommend_derived` |
| `workflow.implement_all_proceed` | `auto_resume` |

Env vars emitted by `apply`:

```bash
export Z_HARNESS_NO_ASK='halt'
export Z_HARNESS_PAUSE_AT_PCT='85'
```

---

## Axioms wizard section

The `axioms` wizard section (added after the memories section) handles two things:

1. **Axioms TOML keys** — prompts to set `axioms.enabled`, `axioms.auto_extract_post_run`, and `axioms.kernel_budget_chars`.
2. **Kernel-pointer install** — idempotently installs a `<!-- z-harness-kernel-pointer BEGIN/END -->` block into `~/.claude/CLAUDE.md`. If the block exists but differs from the canonical text, a diff is shown and the user is asked to confirm an overwrite. If multiple marker blocks are found (e.g. from a prior interrupted run), they are collapsed into one.
3. **Gitignore entries** — offers to add `.z-harness/axioms/` and `.z-harness/KERNEL.md` to the project's `.gitignore`.

Run only the axioms section:

```bash
/z-setup wizard --scope axioms
```

---

## Manual fallbacks

Use these when `/z-setup` is unavailable or you want direct control.

**Set a TOML config key:**
```bash
python3 scripts/config.py set notify.level approval_only
python3 scripts/config.py set notify.level approval_only --scope global   # global file (default)
python3 scripts/config.py set notify.level approval_only --scope project  # repo file
```

**Inspect all keys (machine-readable):**
```bash
python3 scripts/setup.py inspect
python3 scripts/setup.py inspect --flat
python3 scripts/setup.py inspect --json
```

**Compact status line:**
```bash
python3 scripts/setup.py status
# z-harness: posture=interactive, providers=bound, docs=initialized, prefs=2 standing
```

**Run provider discovery:**
```bash
/z-providers-discover            # global providers.json
/z-providers-discover --repo     # repo .z-harness/providers.json
```

**Bootstrap docs INDEX:**
```bash
/z-init-docs
```

**Add a routing-preference memory:**
```bash
/z-suggest-memory --kind routing-preference --question-id workflow.slug_confirm --value recommend_derived --strength strong
```

---

## Troubleshooting

### Explain a key's resolution and precedence

```bash
python3 scripts/setup.py explain notify.level
python3 scripts/config.py explain notify.level
```

Prints the resolved value, source layer, override strength, and any conflict candidates.

### Conflict resolution

If two config layers set the same key, the higher-precedence layer wins (env > repo > global > default). To resolve a conflict:

1. Run `python3 scripts/setup.py inspect` to see which layer is overriding.
2. Unset the unwanted layer with `python3 scripts/config.py set <key> <default-value> --scope <layer>`, or remove the key from the relevant TOML file directly.

### Env vars are not persistent

All `Z_HARNESS_*` env vars are session-only. Setting them with `export` in a terminal does not survive shell restart. To persist:

- Add `export Z_HARNESS_NO_ASK=halt` to `~/.zshrc` (or `~/.bashrc`).
- Or write the snippet emitted by `apply --posture overnight` to a file and source it in your profile.

`Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` is an internal variable set by the `/z-overnight` orchestrator before invoking sub-skills. Do not set it manually — set `Z_HARNESS_OVERNIGHT_AUTODECIDE` instead.

### tomlkit not installed

Comment-preserving TOML writes require `tomlkit`. Without it, `config.py set` falls back to a basic writer that strips comments. Install with:

```bash
pip install tomlkit
```

### Memory edits go through /z-suggest-memory

Routing-preference memories stored in `docs/llm/*.json` are read-only from the `/z-setup` wizard. To add or modify:

```bash
/z-suggest-memory --kind routing-preference --question-id <id> --value <v> --strength weak|strong|very_strong
```

Do not hand-edit the `memories[]` arrays in `docs/llm/*.json` — the schema is managed by the docs system and manual edits may be overwritten on the next `/z-init-docs` or `/z-maintain-docs` run.

---

## Reference

### POSTURE_PRESETS (verbatim from scripts/setup.py)

```python
POSTURE_PRESETS = {
    "interactive": {
        "toml": {
            "notify.level": "approval_only",
            "docs.always_apply": "always",
            "workflow.audit_to_amend": "ask",
            "workflow.slug_confirm": "ask",
            "workflow.implement_all_proceed": "ask",
            "workflow.review_all_proceed": "ask",
            "workflow.plan_decisions_approval": "ask",
        },
        "env": {},
    },
    "overnight": {
        "toml": {
            "notify.level": "approval_only",
            "workflow.implement_all_proceed": "halt",
            "workflow.review_all_proceed": "halt",
            "workflow.plan_decisions_approval": "halt",
        },
        "env": {
            "Z_HARNESS_NO_ASK": "halt",
            "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE": '{"workflow.slug_confirm":"recommend_derived","workflow.audit_to_amend":"amend"}',
        },
    },
    "ci-batch": {
        "toml": {
            "notify.level": "off",
            "workflow.audit_to_amend": "amend",
            "workflow.slug_confirm": "recommend_derived",
            "workflow.implement_all_proceed": "auto_resume",
        },
        "env": {
            "Z_HARNESS_NO_ASK": "halt",
            "Z_HARNESS_PAUSE_AT_PCT": "85",
        },
    },
}
```

### ENV_ONLY_KNOBS (verbatim from scripts/config.py)

```python
ENV_ONLY_KNOBS = [
    "Z_HARNESS_NO_ASK",
    "Z_HARNESS_OVERNIGHT_AUTODECIDE",
    "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE",
    "Z_HARNESS_PAUSE_AT_PCT",
    "Z_HARNESS_PARALLEL",
    "Z_HARNESS_ASK_ALL",
    "Z_HARNESS_NOTIFY",
    "Z_HARNESS_REPO_PROVIDERS",
    "Z_HARNESS_PLANS_DIR",
    "Z_HARNESS_EXPLAIN_RESOLUTION",
    "Z_HARNESS_MAX_EXPLORE",
]
```

These knobs are never written to TOML. They are read from the process environment only. See `docs/human/environment-knobs.md` for per-knob descriptions.

### Axioms env knobs (setup scope only)

These are surfaced read-only in the axioms wizard section but are not in the core `ENV_ONLY_KNOBS` list:

```
Z_HARNESS_AXIOMS_ENABLED
Z_HARNESS_AXIOMS_KERNEL_BUDGET_CHARS
Z_HARNESS_AXIOMS_EXTRACT_MIN_RECURRENCE
Z_HARNESS_AXIOMS_AUTO_EXTRACT_POST_RUN
```
