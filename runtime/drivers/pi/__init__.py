"""
runtime/drivers/pi — pi export-only package.

pi (https://pi.dev) has no native subagent primitive — fan-out runs through
pi's *subagent extension*.  Unlike Cursor, Codex, or Antigravity, pi is an
EXPORT-ONLY target: there is no adapter, HostDriver, or launch/inject host
implementation here.  This package owns only the export pipeline.

Export entry point:

    from runtime.drivers.pi.export import export

    result = export(repo_root, export_root)

Output layout
-------------
<export_root>/
    AGENTS.md          — generated: fan-out preamble + agent index
    CAPABILITIES.md    — copied asset
    README.md          — copied asset
    agents/<id>.md     — generated: every z-harness agent + pi-only explore.md
    prompts/<id>.md    — generated: commands + skills, Agent()/Skill() rewritten
    extensions/        — copied asset: vendored subagent extension

Export-only asymmetry
---------------------
pi does not have a driver (no subprocess / SDK tier).  The z-harness runtime
cannot *launch* pi or inject sessions into it.  All interaction with pi happens
through the exported resource files consumed by pi's native skill/prompt loader.
"""

from runtime.drivers.pi.export import export

__all__ = ["export"]
