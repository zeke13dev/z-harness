"""
Hermes orchestrator — executes z-harness plans in parallel git worktrees.

Module structure (C1 architecture):
  schema.py   — workstreams.json + session-status.json dataclasses
  state.py    — OrchestratorState model for crash recovery
  config.py   — Configuration loading (YAML + env)

To be implemented by sibling clusters:
  worktree.py      — C2: git worktree lifecycle
  session.py       — C3: pi session spawn/monitor
  discord_relay.py — C4: Discord question relay
  merge.py         — C5: merge orchestration
  recovery.py      — C6: crash recovery + state reconstruction

Interface contracts (function signatures documented in hermes-execute.py
section "Interface stubs for C2-C6").
"""
