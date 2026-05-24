## Codex review: task T001

### Major

1. **Contradictory constraint on required sections (docs/human/STYLE-md-schema.md:35 and :45):** The doc states "must contain **exactly** these five top-level sections" but then permits "Additional sections" in the very next section. This contradicts SPEC.md, which establishes required sections without the "exactly" constraint and explicitly allows additional sections. Remove "exactly" from line 35 or clarify the intended constraint to match SPEC.md unambiguously.

### Example fixture validation

- **Frontmatter:** all 6 fields present (schema_version, source, source_files, repo, revision, generated_at). Valid YAML.
- **Rule counts:** Error handling 4, Tests 4, Comments 4, Naming 4, Project-specific 4. All exceed the ≥3 minimum.
- **Rule IDs:** All correctly formatted (EH-001 through EH-004, T-001 through T-004, etc.) and unique within section.
- **Rationale lines:** All present and concise.

Example passes schema validation as a test fixture.
