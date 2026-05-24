You are reviewing code that Claude just wrote for task T001: STYLE.md schema spec + example file.

Spec (excerpt from SPEC.md — "STYLE.md schema" section):

```
### STYLE.md schema

**Frontmatter:**
```yaml
---
schema_version: 1
source: capture | interview | ingest | natural-language | amend
source_files: [list of files Capture used]
repo: <repo name>
revision: <git-sha at init time>
generated_at: <iso>
---
```

**Required sections** (each populated by init flow; empty sections allowed but discouraged):

- `## Error handling` — rules `EH-NNN`
- `## Tests` — rules `T-NNN`
- `## Comments` — rules `C-NNN`
- `## Naming` — rules `N-NNN`
- `## Project-specific` — rules `P-NNN`

**Rule format:**

```markdown
### EH-001: <short rule title>
<one-paragraph rule prose>
Rationale: <one sentence>
```

Rule IDs are append-only and never reused. Reviewer cites by ID.
```

Acceptance criteria:
1. Document the STYLE.md frontmatter fields (`schema_version`, `source`, `source_files`, `repo`, `revision`, `generated_at`) verbatim from SPEC.md.
2. Document the 5 required sections + rule-ID format (`EH-001`, etc.).
3. Include one fully-worked example STYLE.md (≥3 rules per section) as an appendix; this will be used as a test fixture by later tasks.
4. No runtime code in this task.
