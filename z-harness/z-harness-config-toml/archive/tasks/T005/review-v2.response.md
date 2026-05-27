**Majors**

1. Prior finding 1: The repo `explain` assertion is still looser than claimed because it checks `source:`, the repo path, and `.z-harness` independently, not the actual `source: <repo-config-path>` label.
Fix: Assert the exact source fragment, e.g. `source: {self.repo_cfg}` or the full expected output shape.

2. Prior finding 2: The env `explain` assertion is still looser than claimed because it checks `source:`, `env`, and `Z_HARNESS_NOTIFY_LEVEL` independently, not `source: env Z_HARNESS_NOTIFY_LEVEL`.
Fix: Assert the exact source fragment `source: env Z_HARNESS_NOTIFY_LEVEL`.

No blockers found. The other prior findings appear actually addressed: event de-dup now checks `events.jsonl` payload/counts, side-effect tests assert `returncode == 0`, baseline-style tests use isolated non-git cwd, idempotency/non-overwrite checks use byte equality, and global schema/malformed TOML coverage was added with real subprocess assertions.
