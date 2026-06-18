---
inclusion: manual
description: Install, remove, or report status of the z-harness PreToolUse guardrail hooks (git-safety + worktree-isolation) in global or project Claude Code settings.
---

You are running **z-harness `/z-git-guardrails`** — the installer for the z-harness PreToolUse guardrail hooks. It manages a **bundle of two** hooks that run at the Claude Code tool-call level before a tool executes:

1. **git-safety** (`scripts/block-dangerous-git.sh`, matcher `Bash`) — blocks dangerous git operations (force-pushes onto upstream-reachable commits, working-tree-destructive commands).
2. **worktree-isolation** (`scripts/block-shared-tree-edit.sh`, matcher `Edit|Write|MultiEdit|NotebookEdit`) — blocks a second concurrent Claude session from editing a working tree another session already owns, so two sessions can't collide on one tree (the failure that diverged `main` on 2026-06-12). Solo editing is never blocked.

Both are installed/removed/reported together as one bundle. `install` adds whichever are missing; `remove` strips both; `status` reports each.

Subcommand (from `$ARGUMENTS`): `install`, `remove`, or `status`.

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question "Which subcommand? (install / remove / status)" via their native channel. Silent omission is forbidden. -->
**If empty or unrecognized**, use `AskUserQuestion`: "Which subcommand do you want? (install / remove / status)" Block until answered.

## Setup

1. Locate the plugin root and both hook scripts:
   ```bash
   PLUGIN_ROOT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" plugin_root 2>/dev/null)"
   [[ -d "$PLUGIN_ROOT" ]] || PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"
   GIT_HOOK="$PLUGIN_ROOT/scripts/block-dangerous-git.sh"
   TREE_HOOK="$PLUGIN_ROOT/scripts/block-shared-tree-edit.sh"
   ```
   If either script does not exist at that path, halt with a clear error naming the missing file: "Cannot locate <name>. Is the z-harness plugin installed?"

2. Define both settings.json paths:
   ```bash
   GLOBAL_SETTINGS="$HOME/.claude/settings.json"
   PROJECT_SETTINGS=".claude/settings.json"   # relative to repo root; resolve to absolute before use
   ```

3. Build the bundle descriptor (consumed by every subcommand below). Each entry is `{matcher, command}` — the exact object shape that must appear in `hooks.PreToolUse`:
   ```bash
   export HOOKS_JSON="$(python3 -c '
   import json, os
   print(json.dumps([
     {"matcher": "Bash", "command": os.environ["GIT_HOOK"]},
     {"matcher": "Edit|Write|MultiEdit|NotebookEdit", "command": os.environ["TREE_HOOK"]},
   ]))' )"
   ```

---

## Subcommand: `install`

### Step 1 — Choose scope

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the scope question via their native channel. Silent omission is forbidden. -->
Use `AskUserQuestion`:

> Where should the guardrail hooks be installed?
>
> - **global** — `~/.claude/settings.json` (applies to every Claude Code project on this machine)
> - **project** — `.claude/settings.json` in the current repo (applies only to this project)

Wait for the answer. Accepted responses (case-insensitive): `global`, `g` → global; `project`, `p`, `local` → project. Anything else → re-ask once, then halt.

Resolve `TARGET_SETTINGS`:
- global → `$HOME/.claude/settings.json`
- project → `$(pwd)/.claude/settings.json`

### Step 2 — Idempotent merge

Read the existing `TARGET_SETTINGS` (empty object `{}` if the file does not exist). Then add whichever bundle entries are missing. **Never clobber other hooks or the `permissions` block.**

Use the following python3 merge logic (safe, atomic, idempotent — loops over the bundle):

```bash
python3 << 'PYEOF'
import json, os, sys, tempfile

target = os.environ["TARGET_SETTINGS"]
bundle = json.loads(os.environ["HOOKS_JSON"])

# --- read existing settings ---
if os.path.exists(target):
    with open(target) as f:
        try:
            settings = json.load(f)
        except (ValueError, TypeError):
            print(f"ERROR: {target} contains invalid JSON — aborting to avoid clobbering it.", file=sys.stderr)
            sys.exit(1)
else:
    settings = {}

hooks = settings.setdefault("hooks", {})
pre_tool_use = hooks.setdefault("PreToolUse", [])

def present(matcher, command):
    for entry in pre_tool_use:
        if entry.get("matcher") != matcher:
            continue
        for h in entry.get("hooks", []):
            if h.get("type") == "command" and h.get("command") == command:
                return True
    return False

added, already = [], []
for spec in bundle:
    if present(spec["matcher"], spec["command"]):
        already.append(spec["command"])
        continue
    pre_tool_use.append({
        "matcher": spec["matcher"],
        "hooks": [{"type": "command", "command": spec["command"]}],
    })
    added.append(spec["command"])

if not added:
    print("ALREADY_INSTALLED")
    sys.exit(0)

# --- atomic write: temp file beside target, then rename ---
dir_ = os.path.dirname(os.path.abspath(target))
os.makedirs(dir_, exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
try:
    with os.fdopen(fd, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, target)
except OSError:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise

print("INSTALLED " + str(len(added)) + " of " + str(len(bundle)))
for c in added:
    print("  + " + c)
for c in already:
    print("  = " + c + " (already present)")
PYEOF
```

Export `TARGET_SETTINGS` before running the block (`HOOKS_JSON` was exported in Setup):
```bash
export TARGET_SETTINGS="<resolved abs path>"
```

Interpret the output:
- `ALREADY_INSTALLED` → inform the user: "Both guardrail hooks are already installed in `<TARGET_SETTINGS>` — no changes made."
- `INSTALLED N of 2` → proceed to Step 3 (report which were added).
- Any stderr / non-zero exit → halt with the error text; do not attempt the verify step.

### Step 3 — Verify

Dry-run each installed hook to confirm it is wired and runnable:

```bash
# git-safety: a destructive command must be BLOCKED (exit 2).
GIT_OUT="$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"git clean -fdx"}}' | bash "$GIT_HOOK" 2>&1)"; GIT_EXIT=$?

# worktree-isolation: a solo edit must be ALLOWED (exit 0). Full block behavior
# (a 2nd concurrent session -> exit 2) is covered by tests/test_block_shared_tree_edit.py;
# it can't be reproduced with a single dry-run payload (needs a prior live claim).
TREE_OUT="$(printf '%s' '{"session_id":"verify","cwd":"'"$(pwd)"'","tool_name":"Write","tool_input":{"file_path":"'"$(pwd)"'/.z-harness-guardrails-verify"}}' | bash "$TREE_HOOK" 2>&1)"; TREE_EXIT=$?
```

- `GIT_EXIT == 2` → git-safety verified (blocks `git clean -fdx`). Any other value → "WARNING: git-safety hook installed but dry-run returned exit `$GIT_EXIT`; inspect `$GIT_HOOK`."
- `TREE_EXIT == 0` → worktree-isolation verified (runnable; allows solo edit). Any other value → "WARNING: worktree-isolation hook installed but solo dry-run returned exit `$TREE_EXIT` (expected 0 allow); inspect `$TREE_HOOK`."

Tell the user the combined result, e.g. "Both guardrail hooks installed and verified in `<TARGET_SETTINGS>`. Takes effect for new Claude Code sessions."

---

## Subcommand: `remove`

Determine which scope(s) contain any bundle entry. Check both `$HOME/.claude/settings.json` and `$(pwd)/.claude/settings.json`. For each file that exists, strip every bundle entry:

```bash
python3 << 'PYEOF'
import json, os, sys, tempfile

target = os.environ["TARGET_SETTINGS"]
bundle = json.loads(os.environ["HOOKS_JSON"])
commands = {spec["command"] for spec in bundle}

if not os.path.exists(target):
    print("NOT_FOUND")
    sys.exit(0)

with open(target) as f:
    try:
        settings = json.load(f)
    except (ValueError, TypeError):
        print(f"ERROR: {target} contains invalid JSON — aborting.", file=sys.stderr)
        sys.exit(1)

pre_tool_use = settings.get("hooks", {}).get("PreToolUse", [])

def is_ours(entry):
    for h in entry.get("hooks", []):
        if h.get("type") == "command" and h.get("command") in commands:
            return True
    return False

original_len = len(pre_tool_use)
filtered = [e for e in pre_tool_use if not is_ours(e)]

if len(filtered) == original_len:
    print("NOT_FOUND")
    sys.exit(0)

settings["hooks"]["PreToolUse"] = filtered

# Tidy up empty structures.
if not settings["hooks"]["PreToolUse"]:
    del settings["hooks"]["PreToolUse"]
if not settings["hooks"]:
    del settings["hooks"]

dir_ = os.path.dirname(os.path.abspath(target))
fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
try:
    with os.fdopen(fd, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, target)
except OSError:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise

print("REMOVED " + str(original_len - len(filtered)))
PYEOF
```

- Check both settings files (set `TARGET_SETTINGS` to each and re-run). If found and removed in one or both, tell the user which file(s) were updated and how many entries were stripped.
- If not found in either file, tell the user: "Guardrail hooks not found in global or project settings — nothing to remove."
- On JSON parse error or unexpected exit, halt with the error; do not modify the file.

**Note:** `remove` strips only the two guardrail `PreToolUse` entries this command manages. It does not touch any other hooks, the `permissions` block, or any other key in `settings.json`.

---

## Subcommand: `status`

Check both scopes and report each guardrail:

```bash
python3 << 'PYEOF'
import json, os

bundle = json.loads(os.environ["HOOKS_JSON"])

def installed(settings, command):
    for e in settings.get("hooks", {}).get("PreToolUse", []):
        for h in e.get("hooks", []):
            if h.get("type") == "command" and h.get("command") == command:
                return True
    return False

NAMES = {
    "block-dangerous-git.sh": "git-safety",
    "block-shared-tree-edit.sh": "worktree-isolation",
}

for label, path in [
    ("global",  os.path.expanduser("~/.claude/settings.json")),
    ("project", os.path.join(os.getcwd(), ".claude/settings.json")),
]:
    if not os.path.exists(path):
        print(f"{label}: absent ({path})")
        continue
    try:
        with open(path) as f:
            settings = json.load(f)
    except (ValueError, TypeError):
        print(f"{label}: invalid_json ({path})")
        continue
    states = []
    for spec in bundle:
        name = NAMES.get(os.path.basename(spec["command"]), os.path.basename(spec["command"]))
        states.append(f"{name}={'installed' if installed(settings, spec['command']) else 'not_installed'}")
    print(f"{label}: " + ", ".join(states) + f" ({path})")
PYEOF
```

Report the output clearly. Example:

```
guardrail hook status:
  global:  git-safety=installed, worktree-isolation=installed  (~/.claude/settings.json)
  project: git-safety=not_installed, worktree-isolation=not_installed  (/repo/.claude/settings.json)
```

---

## Anti-patterns (push back)

- **"Just edit settings.json manually"** — the merge logic exists precisely to prevent clobbering other hooks or the `permissions` block. Manual edits skip the idempotency check and the verify step.
- **"Skip the verify step after install"** — the verify step catches installation errors (wrong path, permission issue) before the first real tool call. It takes less than a second. Do not skip it.
- **"Install globally AND in the project to be safe"** — double-installation is harmless but unnecessary. The global setting already covers all projects. Only install in both if the user explicitly asks, and inform them that each hook will run twice per matching tool call.
- **"Remove all hooks from settings.json"** — the remove subcommand strips only the two guardrail entries. Any other PreToolUse hooks present in the file are intentional and must not be touched.
- **"Leave Z_HARNESS_ALLOW_SHARED_TREE=1 / Z_HARNESS_GIT_GUARDRAILS_OVERRIDE=1 exported permanently"** — those overrides are one-shot escape hatches for a single session/command. Setting them permanently defeats the guardrail. Push back; offer `/z-git-guardrails remove` if the user wants to fully disable a hook.

---

## Out of scope

- Editing the logic of `block-dangerous-git.sh` or `block-shared-tree-edit.sh` themselves → those files are managed as source code; use normal edit tools.
- Installing either hook under a different matcher → the matchers are fixed (`Bash` for git-safety; `Edit|Write|MultiEdit|NotebookEdit` for worktree-isolation); a different matcher would never fire correctly.
- Managing other Claude Code settings (model, `permissions`, other hooks) → this command is scoped to the two PreToolUse guardrail entries.
- Restarting or reloading Claude Code → after editing `settings.json`, Claude Code picks up the change on the next session; this command cannot trigger a reload.
- Auditing past override events → see `<z-harness-base>/git-guardrails-audit.log` directly.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | yes | Empty/unrecognized subcommand; `install` scope selection |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden. Each gated call site is annotated with a `<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
