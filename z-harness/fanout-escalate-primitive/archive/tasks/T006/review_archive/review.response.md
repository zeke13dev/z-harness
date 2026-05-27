## Codex review: task T006

### Blockers

**1. Unused import `os` introduces code smell at line 33.**
The `import os` is never called anywhere in the script. Remove it.

### Major

No majors found on closer review. The `--fixture-mode` flag is actually IN the acceptance criteria (stated as "reads JSON fixture in --fixture-mode"), despite not appearing in the flags list. The fixture-mode implementation correctly handles three fixture formats (flat dict, nested list, or single string). The classify_ground_truth function matches CALIBRATION.md rubric exactly. Archive discovery walk, majority voting, confusion matrix, tripwire logic (Tripwires 1–2 fire at >= 70% MEDIUM and < 20% HEAVY respectively, setting exit code 1), and JSON emission all meet spec. The scope-probe stub returning MEDIUM in normal mode is explicitly allowed per acceptance criteria ("shim stub returning MEDIUM in normal mode").
