---
trigger: model_decision
description: "Configuration cockpit for z-harness: inspect resolved state, run guided setup wizard, or apply a posture preset."
---

You are the **z-harness `/z-setup`** skill. Your job is to provide a single entry point for all z-harness configuration: inspecting the current resolved state, running a guided setup wizard, or applying a posture preset. You delegate the heavy lifting to `scripts/setup.py`.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Invocation forms

```
/z-setup
/z-setup wizard [--scope <name>]
/z-setup apply --posture <name>
/z-setup explain <key>
/z-setup status
```

## Phase 0 — Emit start event and parse arguments

```bash
PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-setup"

bash "$PLUGIN_ROOT/scripts/log-event.sh" "$RUN_ID" setup_skill_start \
  "$(printf '{"arguments":"%s"}' "$ARGUMENTS")"
```

Parse `$ARGUMENTS`:

1. If `$ARGUMENTS` is empty or whitespace → **inspect form** (default).
2. If first token is `wizard` → **wizard form**; extract optional `--scope <name>`.
3. If first token is `apply` and second token is `--posture` → **apply form**; extract `<name>` (third token).
4. If first token is `explain` → **explain form**; pass remainder as the key argument.
5. If first token is `status` → **status form**.
6. Any other arguments → emit usage error and exit cleanly.

```
Usage:
  /z-setup                          Inspect current resolved configuration
  /z-setup wizard [--scope <name>]  Guided setup wizard
  /z-setup apply --posture <name>   Apply posture preset (interactive|overnight|ci-batch)
  /z-setup explain <key>            Explain a configuration key
  /z-setup status                   Show compact status summary
```

## Inspect form (`/z-setup`)

Run:

```bash
python3 "$REPO_ROOT/scripts/setup.py" inspect
```

Print the output to the user. No confirmation needed.

## Wizard form (`/z-setup wizard [--scope <name>]`)

The wizard runs interactively as a subprocess — the user interacts with it directly via the terminal. For v1, the skill's role is to launch it and report the outcome.

```bash
SCOPE_ARG=""
if [[ -n "$SCOPE_NAME" ]]; then
  SCOPE_ARG="--scope $SCOPE_NAME"
fi

python3 "$REPO_ROOT/scripts/setup.py" wizard $SCOPE_ARG
WIZARD_EXIT=$?
```

If `WIZARD_EXIT != 0`, surface the non-zero exit to the user:

```
/z-setup wizard exited with code <WIZARD_EXIT>. Review output above for errors.
```

If `WIZARD_EXIT == 0`, print:

```
/z-setup wizard complete. Run `/z-setup` to verify the final state.
```

**Note:** If the driver does not support interactive subprocesses, advise the user to run `scripts/setup.sh` directly in their terminal for the full interactive wizard flow.

## Apply form (`/z-setup apply --posture <name>`)

This is the main gate the skill provides: show the user what will change before committing.

### Step 1 — Dry run

```bash
POSTURE_NAME="<extracted from $ARGUMENTS>"

python3 "$REPO_ROOT/scripts/setup.py" apply --posture "$POSTURE_NAME" --dry-run
DRY_RUN_EXIT=$?
```

If `DRY_RUN_EXIT != 0`, surface the error and exit cleanly without proceeding to the write step.

The dry-run output shows the diff of what would be written. Print it to the user.

### Step 2 — Confirmation gate

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface this confirmation. -->

Use `AskUserQuestion` to ask:

> Apply posture `<POSTURE_NAME>` to your z-harness configuration? The diff above shows all changes that will be written.

Options: `yes, apply` / `no, cancel`

If the user selects `no, cancel` → print "Posture apply cancelled." and exit cleanly. Do not run setup.py again.

### Step 3 — Apply with --yes

```bash
python3 "$REPO_ROOT/scripts/setup.py" apply --posture "$POSTURE_NAME" --yes
APPLY_EXIT=$?
```

If `APPLY_EXIT != 0`, surface the error:

```
/z-setup apply failed (exit code <APPLY_EXIT>). Configuration may be partially written — run `/z-setup` to check current state.
```

If `APPLY_EXIT == 0`, print:

```
Posture `<POSTURE_NAME>` applied. Run `/z-setup` to inspect the final state.
```

If the posture emits a shell snippet (overnight, ci-batch), remind the user:

```
NOTE: This posture includes env-var settings that are not persistent. Source the emitted shell snippet or add it to your shell profile. See docs/human/SETUP.md for details.
```

## Explain form (`/z-setup explain <key>`)

```bash
python3 "$REPO_ROOT/scripts/setup.py" explain "$EXPLAIN_KEY"
```

Print output to the user.

## Status form (`/z-setup status`)

```bash
python3 "$REPO_ROOT/scripts/setup.py" status
```

Print output to the user.

## Phase N — Emit end event

After all invocation-form logic completes (including error paths):

```bash
bash "$PLUGIN_ROOT/scripts/log-event.sh" "$RUN_ID" setup_skill_end \
  "$(printf '{"form":"%s","exit_code":%d}' "$INVOCATION_FORM" "$FINAL_EXIT_CODE")"
```

Where `INVOCATION_FORM` is one of `inspect | wizard | apply | explain | status | error` and `FINAL_EXIT_CODE` is the relevant subprocess exit code (0 if no subprocess was run or if the user cancelled).

## Push-notify on completion

```bash
[ "$(bash "$PLUGIN_ROOT/scripts/config.py" should-notify --event phase_end)" = yes ] && \
  PushNotification("/z-setup $INVOCATION_FORM complete")
```

## Invariants

- The skill NEVER writes configuration directly — all writes are delegated to `scripts/setup.py`.
- `AskUserQuestion` for the apply confirmation runs with `Z_HARNESS_NO_ASK` unset (the skill does not set it).
- A dry-run failure always prevents the write step from running.
- User cancellation at the confirmation gate always results in a clean exit (exit code 0).
- `setup_skill_start` is always emitted before any subprocess is launched; `setup_skill_end` is always emitted before the skill exits, including on error paths.
