## Codex review: task T005

### Blockers
1. **Scope expansion beyond task spec**: The diff adds source_file entries and entry_points for 'z-mr-review' and 'z-style-init' commands, but the T005 acceptance criteria specify only 'z-fix' should be added. Remove the extraneous entries unless they are part of a separate task.

2. **Summary text does not match spec skeleton**: The z-fix summary in entry_points is 231 characters and expands beyond the specification skeleton. Use the exact summary from SPEC.md line 181: 'Lightweight bug-fix command for the case where the user already has a diagnosis; single light-fix consult, inline implementation, non-negotiable Codex review, optional post-mortem.'
