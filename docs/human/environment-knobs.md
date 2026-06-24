# Environment Knobs

> Last updated: 2026-05-27

z-harness behaviour can be tuned via environment variables. The notify and
docs knobs are now managed through `scripts/config.py` (see
[docs/human/config.md](config.md)); the variables below remain in effect
for the other tunables.

## Variables

| Variable | Default | Purpose |
|---|---|---|
| ~~`Z_HARNESS_NOTIFY`~~ | — | Removed. Use `notify.level` in `~/.config/z-harness/config.toml` instead; see [docs/human/config.md](config.md). The loader exports `Z_HARNESS_NOTIFY_LEVEL` to migrated flows. |
| `Z_HARNESS_MAX_EXPLORE` | `3` | Cap on `Explore` subagent dispatches per `/z-plan` run. |
| `Z_HARNESS_DOC_STALENESS_THRESHOLD` | `20` | Percent staleness above which `/z-plan` halts and recommends `/z-maintain-docs`. |
| `Z_HARNESS_LOCAL_CARGO_CLEAN` | — | Set to `1` to trigger a one-time local `cargo clean` at the start of `/z-execute`. |
| `Z_HARNESS_SLUG` | — | Set by commands; namespaces all output paths under `z-harness/<slug>/`. |
| `Z_HARNESS_BRAINSTORM_EXPLORE` | — | Set to `1` to opt into a Phase 1 Explore dispatch inside `/z-brainstorm`. Off by default. |
| `Z_IMPLEMENT_PAUSE_TASKS` | `5` | Completed tasks since last checkpoint that triggers a clear checkpoint in `/z-execute`. Set to `0` to disable. |
| `Z_IMPLEMENT_PAUSE_MINUTES` | `30` | Wall-clock minutes since last checkpoint that triggers a clear checkpoint in `/z-execute`. Set to `0` to disable. |
| `Z_HARNESS_CHECKPOINT_STATUS` | `context_pressure` | Internal clear-checkpoint status passed to `write-clear-checkpoint.sh`; valid values match `handoff.json` status enum. |
| `Z_HARNESS_CHECKPOINT_NEXT_STEP` | — | Internal clear-checkpoint continuation prompt override for `handoff.json` `next_step`. |
| `Z_HARNESS_CHECKPOINT_RESUME_COMMAND` | `/z-execute <slug>` | Internal clear-checkpoint status-line/event resume command override for non-`/z-execute` checkpoints. |
| ~~`Z_HARNESS_RETRY_UPGRADE`~~ | — | Removed. Model selection now uses `**Complexity:** low\|medium\|high` stamp in TASKS.md; retries always use Opus. |

Setting both `Z_IMPLEMENT_PAUSE_TASKS=0` and `Z_IMPLEMENT_PAUSE_MINUTES=0` disables automatic
clear checkpoints in `/z-execute`.

See [docs/human/config.md](config.md) for the TOML config system, which covers
`notify.level` and `docs.always_apply` as structured, layered knobs.
