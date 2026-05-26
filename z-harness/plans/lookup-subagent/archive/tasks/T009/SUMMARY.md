# T009 — Static verification PASS

- external-lookup.md frontmatter parses, has name/description/model/tools, model=haiku, name=external-lookup
- verb-blocklist found in fenced block, all 14 regex patterns compile under re.IGNORECASE (0 bad)
- docs/llm/{lookup-contract,external-lookup-agent,INDEX}.json all parse
- INDEX.json contains lookup-contract and external-lookup-agent slugs
- z-harness/lookup-cache/.gitignore = "*\n!.gitignore\n" exactly
