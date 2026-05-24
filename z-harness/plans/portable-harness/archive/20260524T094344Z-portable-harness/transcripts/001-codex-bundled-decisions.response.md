**D3**
- Tentative weakness: one-shot migration assumes users run it before continuing in-flight work. With plugin install workflows, many users will update commands without running repo-local scripts.
- Better alternative: keep migration script, but add dual-read for one release and dual-write only for metadata needed to find the plan. Prefer `z-harness/plans/<slug>/`, warn on `z-harness/<slug>/PLAN.md`, and offer the exact migration command.
- Failure mode: active plans become invisible; `/z-implement-next` appears to have "no plan" while files still exist.

**D4**
- Tentative weakness: hybrid config can make runs non-reproducible unless merge precedence is explicit and visible.
- Better alternative: repo-local `.z-harness/providers.json` should override user-global only for `roles`; provider definitions should resolve by name with explicit shadowing warnings. Also print the resolved provider/role at run start.
- Failure mode: teammate says "reviewer = gpt-5" in repo config, but another user's global `codex` provider silently means a different command/model.

**D5**
- Tentative weakness: a generic `consultant.md` that "takes a role" depends on every caller passing the role correctly. Existing agent invocation may not have a clean typed parameter surface.
- Better alternative: keep one shared implementation/template, but expose stable role-specific entrypoints: `consultant-a.md`, `consultant-b.md`, `reviewer.md`; make legacy `codex-consultant.md` and `gemini-consultant.md` shims.
- Failure mode: both consultants accidentally route to the same role/provider, destroying the intended cross-model critique.

**D7**
- Tentative weakness: a discovery command that writes the registry can encode transient PATH/local-machine state as durable config, especially if it writes repo-local config.
- Better alternative: `/z-providers-discover` should emit a proposed user-global config by default and require explicit confirmation for writes; repo-local output should be opt-in and roles-only unless the user asks to pin commands.
- Failure mode: repo gets committed with `/opt/homebrew/bin/codex` or a user-specific `ollama` setup that breaks everyone else.

**D8**
- Tentative weakness: Claude Code shape as canonical may bake Claude-specific semantics into exports, making Codex/Cursor/agy support permanently lossy in non-obvious ways.
- Better alternative: acceptable if you add an export compatibility manifest per target, e.g. `exports/<target>/CAPABILITIES.md` or generated warnings listing unsupported constructs. Do not silently emit degraded behavior.
- Failure mode: exported IDE commands look installed but miss agent routing, skill assumptions, or filesystem conventions, so failures happen during execution instead of install/export.

**Cross-Decision Interactions**
- D4 + D5: role routing must be resolved centrally. Thin shims should not hardcode provider names, or D4's registry becomes decorative.
- D4 + D7: discovery must know whether it is writing user-global providers, repo-local role overrides, or both. Mixing these creates portability bugs.
- D3 + D8: exporters must agree on the new canonical plan path `z-harness/plans/<slug>/`; otherwise different IDE targets will operate on different plan locations.
- D5 + D8: target IDEs may not support parameterized agents. Stable role-specific shim files are safer for export than one generic consultant requiring runtime parameters.
- D7 + D8: exported packages should not include discovered local providers by default. Provider discovery is machine-local; IDE export is distribution-facing.
