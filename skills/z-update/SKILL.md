---
name: z-update
disable-model-invocation: false
description: Update z-harness by delegating all release and install-mode decisions to the deterministic CLI.
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

# /z-update

Update z-harness explicitly. This skill is only a thin host wrapper; it does not fetch release manifests, parse manifest JSON, download tarballs, or decide how to replace an install in prose.

## What it does

Run the deterministic CLI update command and surface its exact result:

```bash
if command -v z-harness >/dev/null 2>&1; then
  z-harness update
else
  python3 -m z_harness_cli update
fi
```

The CLI owns the security-critical behavior:

- release manifest fetch and schema validation;
- verified wheel upgrades through `uv tool install`;
- source/symlink updates via clean-checkout `git pull --ff-only`;
- tarball/runtime guidance that routes users back through manifest-backed `z-harness install` / `install.sh` instead of host-side self-swapping.

## Interpreting outcomes

- **Up to date:** no action is needed.
- **Dev build:** no automatic update is applied; keep using the source checkout workflow.
- **Symlink/source install:** the CLI updates only a clean checkout and refuses dirty or diverged trees. Commit/stash or resolve manually, then rerun `/z-update`.
- **Tarball/runtime install:** host `/z-update` does not perform an in-place tarball self-update. Follow the CLI's reinstall command, normally `z-harness install --target=<host> --force` (or `python3 -m z_harness_cli install --target=<host> --force` when the executable is not on `PATH`); the deterministic installer handles release integrity before replacement.
- **Wheel install:** the CLI downloads, verifies, and upgrades through `uv`.

Do not add fallback manifest parsing, integrity-check commands, or tarball extraction snippets to this skill. If CLI behavior needs to change, update `z_harness_cli/commands/update.py`, `z_harness_cli/release.py`, and `install.sh` with tests.

---

## Environment variables

The CLI honors the release and plugin-root environment variables documented by the installer. This skill does not interpret them directly.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | no | — |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden. Each gated call site is annotated with a `<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
