MODE: brainstorm

TOPIC: Rethink z-fix (the existing /z-debug command) to be more rigorously Cursor-style hypothesis-driven — generate N hypotheses, test each, determine which worked, iterate, be more disciplined so the command actually fixes issues; keep exploiting the project's multi-LLM (Claude + Codex + Gemini) advantage.

USER FRAMING:
"i'm thinking of editing the idea of z-fix to be more like cursor's where the framework is identify a bunch of hypothesis -> test each hypothesis -> determine which one worked / iterate again. i want to be more disciplined so we have a higher chance that z-fix actually debugs/fixes issues. i still want to take advantage of the multi-llm idea of this project"

CURRENT STATE OF /z-debug:
- 8-phase pipeline, ~30 min wall target
- P1: problem statement (clarifying questions)
- P2: reproduce + evidence (no debug without repro)
- P3: hypothesize (2-3 ranked hypotheses only)
- P4: cross-LLM consult (Codex + Gemini parallel, rank + surface disagreement)
- P5: isolate (cap 3 cycles, one experiment per cycle, refuted hypotheses loop back to P3)
- P6: root-cause + fix (reuses /z-plan-light, light-fix mode consult, non-negotiable Codex review)
- P7: post-mortem (mandatory preventative analysis)
- P8: finalize
- Auto-bail on: >5 files / >3 isolation cycles / multi-module / architectural

CURRENT GAP THE USER IS POINTING AT:
Current /z-debug is hypothesis-driven but loose:
- Small N (2-3 hypotheses only), one ranking pass
- No explicit per-hypothesis discriminating-test design (what data would prove or refute each?)
- No batch / parallel test execution (one experiment per cycle is serial)
- No scoring loop / Bayesian update across cycles (no running tally of hypothesis likelihood after each test result)
- No enforced write-down of structured tuple: (hypothesis, discriminating test design, actual result, what was eliminated)

MULTI-LLM PATTERN IN PROJECT:
- codex-consultant + gemini-consultant are Haiku CLI proxies
- Modes include debug-hypotheses, light-fix
- Standard return: Recommendation/Reasoning/Tradeoffs/Considerations/Raw excerpt
- Always parallel for hypothesis + fix consults
- Re-rank or surface disagreement

ASK (from z-brainstorm template):
Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as <missing>. Do not add other sections or a recommendation. Be bold and distinct — diversity across ideators is the point.
