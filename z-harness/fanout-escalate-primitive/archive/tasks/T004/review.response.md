(Full Codex output preserved. Key findings extracted below.)

## Codex Review Findings

### Blockers
None identified.

### Major

**1. HEAVY schema example includes dimensions_hint (line 186):** The Full Schema JSON example shows `dimensions_hint: ["security", "performance"]` inside a HEAVY mode case. However, field reference at line 206 explicitly states `dimensions_hint` is LIGHT-only for `/z-audit` phase 0. Remove `dimensions_hint` from the HEAVY example, or replace with a LIGHT case example.

**2. Field Reference says "scope-probe" writes all fields (line 194):** Writer column lists `scope-probe` for `host_command`, `slug`, `last_run_id`, `last_updated`, and `scope_probe_version`. However, scope-probe is read-only and only emits `chunks`, `seams_counted`, and `candidates_walked` in its output contract. These metadata fields are written by the host Phase 0 dispatcher, not by scope-probe. Correct the Writer column to "host Phase 0" for metadata fields and "scope-probe" only for `chunks`, `seams_counted`, `candidates_walked`, `mode`, `axis`, `confidence`, `reason_codes`.

**3. chunks field documentation contradicts output contract (line 202):** Field Reference says chunks is always empty for LIGHT and MEDIUM, but Output Contract section (lines 92–94) permits LIGHT/MEDIUM to "contain a single entry summarizing the entire topic." Align the Field Reference to match: refused=always empty, HEAVY=one per sub-run, LIGHT/MEDIUM=empty or single summary chunk.
