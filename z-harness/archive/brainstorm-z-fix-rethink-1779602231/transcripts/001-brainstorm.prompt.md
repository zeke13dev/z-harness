MODE: brainstorm

Topic: Rethink z-fix / the existing /z-debug command to be more rigorously Cursor-style hypothesis-driven.

User framing: identify many hypotheses → test each hypothesis → determine which one worked → iterate. Be disciplined so /z-debug actually debugs/fixes issues. Keep exploiting multi-LLM (Claude + Codex + Gemini) advantage.

Current /z-debug architecture (executive summary):
- 8-phase pipeline, targets ≤30 min wall time.
- P1: Problem statement
- P2: Reproduce + evidence (no debug without repro)
- P3: Hypothesize (2-3 ranked hypotheses)
- P4: Cross-LLM consult (Codex + Gemini parallel, debug-hypotheses mode, rank + surface disagreement)
- P5: Isolate (cap 3 cycles, one experiment per cycle, refuted hypotheses loop back to P3)
- P6: Root cause + fix (reuses /z-plan-light, light-fix mode consult)
- P7: Post-mortem (mandatory preventative analysis)
- P8: Finalize

Auto-bail: >5 files / >3 isolation cycles / multi-module / architectural → escalate to /z-plan.

Gap user points out:
Current /z-debug is hypothesis-driven but loose: N is small (2-3), one ranking pass, user picks one, runs ONE experiment per cycle. No explicit per-hypothesis discriminating-test design, no batch / parallel test execution, no scoring loop / Bayesian update across cycles, no enforced write-down of (hypothesis, discriminating test, result, what was eliminated).

Task: Brainstorm a rethink of /z-debug that brings Cursor-style rigor to the z-harness multi-LLM model.

Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as <missing>. Do not add other sections or a recommendation.
