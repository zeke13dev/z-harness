Ship **Option B**.

It is the best minimum viable fix: it gives users a second-terminal inspector for stuck `*_start` without adding token/noisy heartbeat traffic, and it records the known silent-disable timeout failure as structured data. Option C does not help the blocked orchestrator because calls are synchronous, so the extra events only help users manually tailing logs and likely are not worth the surface area yet.

What to watch:

- Make `liveness.sh` accept run path or default to latest run, and use a configurable stale threshold.
- Treat `*_end` absence as "possibly stuck," not proof of failure.
- Include consultant/reviewer timeout status in `timeout_availability`: command found, command name, timeout seconds, and whether timeout enforcement is disabled.
- Consider multiple concurrent runs and malformed partial JSONL lines.
- Give the script useful exit codes so future automation can consume it.

So: **B now, leave C as a later enhancement only if users actually tail `events.jsonl` and ask for finer-grained progress.**
