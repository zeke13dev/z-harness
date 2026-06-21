# statusLine HUD — live subagent / run liveness

A native Claude Code status line that shows, at a glance, whether work is actually
happening in a session — most importantly **whether a subagent is in flight**, what
it is, and for how long. It is the *positive* liveness signal: where the watchdog
asks "should I worry?", the HUD answers "is it working?" continuously, in the
surface you are already looking at.

## What it shows

```
Opus · ctx 47% · $2.31                              (idle — base tier only)
Opus · ctx 12% · $0.05 · > reviewer 44s             (a subagent is working)
Opus · ctx 41% · > implementer 38s · implement T3 hb4s   (during a z-harness run)
```

Two tiers, both degrade gracefully:

- **Generic tier (any session).** Tails the session transcript and detects an
  in-flight subagent — an `Agent`/`Task` tool call with no result yet — showing
  `> <agent> <elapsed>`. Works in any session, with or without z-harness.
- **z-harness tier (during a run).** Correlates the working directory to the
  active-plan registry and overlays `<phase> <current_task> hb<heartbeat-age>`.

When nothing is active it falls back to `model · ctx% · $cost`.

## Install (opt-in)

Nothing is written to your settings automatically. To wire it up:

```bash
scripts/install-statusline.sh                 # writes ~/.claude/settings.json
scripts/install-statusline.sh --print         # just show the snippet, write nothing
scripts/install-statusline.sh --target ./.claude/settings.json   # project scope
```

Or add it by hand:

```json
"statusLine": {
  "type": "command",
  "command": "/abs/path/to/scripts/zh-statusline.py",
  "refreshInterval": 2
}
```

### `refreshInterval` is load-bearing

Without `refreshInterval`, Claude Code only re-runs the status line on a new
assistant message — so it would **freeze during a long subagent run**, which is
exactly the moment you want a live signal. `refreshInterval: 2` makes Claude Code
re-invoke the command every 2 seconds even while idle or waiting on a subagent, so
the elapsed counter actually ticks.

## Properties worth knowing

- **Per-local-TUI, local-file-only.** Each session renders its own line by reading
  local files. There is no cross-host machinery — which is the point: it sidesteps
  the cross-host blind spot the daemon watchdog has. If you run Claude Code on a
  remote box, the HUD works there natively too.
- **Fail-safe.** Any error still prints at least the base tier and exits 0 — a
  non-zero exit or empty output would blank the status line.
- **Fast.** Tail-bounded transcript read (never a full parse) plus at most one
  registry read; a warm tick is well under the refresh interval even on a
  multi-megabyte transcript.

## Relationship to the watchdog

The HUD is the passive, in-chat liveness glance. The *active* backstop — a
scheduled hang-detector that fires when a subagent runs past its expected time —
is the second half of this effort (`statusline-hud` plan, Workstream B) and
replaces the daemon/poller layer of the old watchdog. The hard-deadline kill layer
(`supervised-run.sh`) is unaffected.
