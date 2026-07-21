# z-harness

Plan deliberately. Implement in small, reviewable steps. Verify before you ship.

z-harness is an open-source workflow layer for AI coding agents. It adds structured planning, implementation, testing, review, documentation, and release workflows to the coding harness you already use.

[![Tests](https://github.com/zeke13dev/z-harness/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/zeke13dev/z-harness/actions/workflows/tests.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> [!IMPORTANT]
> z-harness is pre-1.0 beta software. Its workflows can direct tools that modify production code. Review generated plans and diffs, keep the test/review gates enabled, and use a linked worktree for agent-authored changes.

## What it adds

- A repeatable path from a rough idea to a reviewed implementation.
- Small task batches with explicit acceptance criteria and dependency tracking.
- Test planning, release-readiness audits, and cross-model review gates.
- Durable run artifacts so interrupted work can be resumed instead of reconstructed.
- Host-native skills and agents where supported, with explicit degradation where a host cannot provide the same orchestration primitives.

A typical workflow looks like this:

```text
idea -> sharpen -> plan -> audit -> execute -> test -> review -> release
```

The day-to-day interface stays inside your existing coding harness. The `z-harness` Python CLI is the bootstrap, setup, install, update, and diagnostic surface—not a replacement coding agent.

## Host support

| Host | Public beta status | Notes |
|---|---|---|
| Claude Code | Primary / native | Full plugin workflow and agent orchestration. |
| z-harness CLI | Supported | Setup, lifecycle, diagnostics, and release tooling. |
| Oh My Pi (OMP) | Conditional native | Released only when clean installed-wheel evidence passes. |
| Codex | Partial / preview | Plugin and export support; orchestration remains explicitly degraded where native primitives are unavailable. |

Cursor and Antigravity are development/advanced targets. Other generated host formats are export-only and are not part of the default public release.

See [CAPABILITIES.md](CAPABILITIES.md) for the exact support matrix and fidelity limits.

## Install

### Released beta

```bash
curl -fsSL https://github.com/zeke13dev/z-harness/releases/latest/download/install.sh | sh
z-harness setup --target all --dry-run
z-harness setup --target claude --install
```

The installer downloads the release wheel over HTTPS, verifies its SHA-256 digest, and installs it with `uv tool install`. Start with `--dry-run` to inspect the selected host changes.

### Source checkout

Use a source checkout when contributing or testing unreleased changes:

```bash
git clone https://github.com/zeke13dev/z-harness.git
cd z-harness
bash install.sh --target=claude
```

Other explicit source targets include `codex` and `all`:

```bash
bash install.sh --target=codex
bash install.sh --target=all
```

Source installs symlink the checkout into the selected host plugin location. Reload the host after installation.

For update, uninstall, tarball, OMP, and isolated setup instructions, see the [installation guide](docs/human/INSTALL.md).

## Start a workflow

The available skills depend on the selected host and release surface. A common path is:

```text
/z-sharpen <idea>
/z-plan <buildable objective>
/z-audit-plan <plan>
/z-execute <plan> --ack
/z-test <plan>
/z-review-all <plan>
```

Useful supporting workflows include `/z-debug` for unknown root causes, `/z-fix` for diagnosed problems, `/z-resume` for interrupted work, and `/z-report` for a human-readable completion report.

Research-heavy commands remain on the development surface until they are explicitly promoted through the release contract.

## Safety and release integrity

The public artifact set is defined by a positive, default-deny release contract. Unclassified files are rejected rather than silently shipped. Release candidates are assembled deterministically and bound to:

- the exact reviewed `main` and promoted `prod` commits;
- isolated installed wheel and plugin payloads;
- host-execution evidence for every public native claim; and
- the exact protected workflow run, artifacts, and SHA-256 digests used for publication.

The publication workflow fails closed when any identity, provenance, freshness, or host-evidence check does not match. See [CAPABILITIES.md](CAPABILITIES.md) and the [installation guide](docs/human/INSTALL.md) for the detailed contract.

## Development

```bash
make test
make test-sh
make export
Z_HARNESS_RELEASE_SURFACE=prod bash scripts/bundle-plugin.sh
```

Keep the primary `main` checkout clean and read-only for agent content edits. Create a linked worktree and topic branch from clean local `main`, verify there, then merge the reviewed branch back into local `main`.

Canonical sources live in:

- `skills/` — commands and skills;
- `agents/` — agent definitions;
- `runtime/` — host and export drivers;
- `z_harness_cli/` — setup and lifecycle CLI; and
- `docs/human/` — operator and contributor documentation.

Generated host exports belong under `temp/exports/` and are not committed release source.

## License

z-harness is available under the [MIT License](LICENSE).
