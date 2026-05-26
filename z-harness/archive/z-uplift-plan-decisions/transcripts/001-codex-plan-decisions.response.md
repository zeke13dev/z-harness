## Codex consultation: /z-uplift plan decisions (D1–D4 recommendations)

**Recommendation:** Keep tentative choices D1(c), D2(a), D3(b), D4(b). Main adjustment: add manifest preview/manual override for D2, and classify CROSS-CUTTING.md findings to avoid duplication across component task files.

**Reasoning:**

**D1 — Output Layout (c):** Directly supports /z-implement-all --tasks=<path> fast path. Each component becomes a self-contained, resumable plan unit with its own SPEC/PLAN. Failure isolation is clean. Tradeoff is more directory boilerplate.

**D2 — Component Decomposition (a):** Polyglot detection is necessary for a bulk codebase uplift tool. Rust-only is too narrow; always top-level too crude for workspaces. But add two guardrails: (i) emit COMPONENTS.md preview before expensive audits start so user can accept/override; (ii) include --components/--component flags for manual override when autodetection misfires.

**D3 — Cross-Cutting Pass (b):** Reuses existing Gemini+Codex review infrastructure, avoids a new agent. Pre-audit CROSS-CUTTING.md gives each component auditor shared architectural context. Tradeoff: without a SPEC, findings may be broad. Mitigate by classifying findings: `global-task` (needs dedicated plan), `per-component-context` (informs audits, no direct task), `risk` (watch item).

**D4 — Per-Component Audit Dispatch (b):** Inline replication avoids re-entrant slash problems (run IDs, notifications, state). Owns manifest and bail logic directly. Tradeoff: duplication with /z-audit, future drift risk. Mitigate: document that /z-uplift mirrors /z-audit Phases 2-6 intentionally; define a small shared contract now (inputs, outputs, severity, bail thresholds, task format) to make extraction easier later.

**Tradeoffs / risks flagged:**

- **D1 collisions:** Slug collisions possible if components have similar names or nested packages. Recommend stable component IDs in MANIFEST.md, not just path-derived slugs, to survive path moves.
- **D2 detection errors:** Autodetection can create too-many components (noise) or too-few (giant blobs), both triggering artificial bailouts. Mitigate by emitting preview + override flags.
- **D3 broad findings:** Cross-cutting review without a SPEC can be vague. Mitigate by strict classification and optional synthetic `<slug>-cross-cutting/` plan for global work.
- **D4 drift:** Inline duplication means /z-uplift and /z-audit may diverge. Mitigate with shared contract doc and a comment noting intentional parity.

**Additional considerations Codex raised:**

- **D6 clarification:** Component plans are implemented sequentially at the component level; each component internally uses `/z-implement-all --tasks=<path>` for task parallelism. AskUser gates happen between components or batches. (Clarifies "sequential" vs "parallel" intent.)
- **D5 visibility:** Bailed components need visible manifest state (`bailed:crit_high_volume`, `excluded_from_implementation`), not silent omission. Preserve links to partial REPORT.md.
- **D7 manifest fields:** Record component detection method, audit status, implementation status, bail reason, task path, timestamps/run IDs, and dependency notes. Makes resume after /clear straightforward.
- **D8 scoping question:** Define whether /z-uplift is one-time-only or can be rerun incrementally. Affects manifest/resume semantics.

**Raw response excerpt (if useful):**

From Codex on D1: "This matches `/z-implement-all --tasks=<path>` cleanly because `$BASE = dirname(TASKS.md)` gives each component its own `SPEC.md` and `PLAN.md`... keeps failure isolation simple: one component can bail, retry, or complete without corrupting others."

From Codex on D2: "Include a manual override path early: `--components=<file>` or `--component <path>` will save the workflow when autodetection is wrong... Emit `COMPONENTS.md` or a manifest preview before audits begin."

From Codex on D3 guidance: "Classify findings as: `global-task` (belongs in dedicated cross-cutting plan), `per-component-context` (inform audits but do not create direct tasks), `risk` (watch item)."
