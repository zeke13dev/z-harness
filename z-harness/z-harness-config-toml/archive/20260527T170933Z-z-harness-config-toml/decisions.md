# Decisions — z-harness TOML config slice 1

## D1: TOML parser dependency
- **Decision:** Use Python stdlib `tomllib` (3.11+); declare minimum Python = 3.11 in `scripts/config.py` shebang/check.
- **Options:**
  - (a) `tomllib` only — no extra deps, but rejects users on Python < 3.11.
  - (b) `tomllib` + `tomli` fallback — broader compat, one extra runtime dep.
  - (c) Pure-shell parser (yq/dasel) — no python at all but adds external tool dep.
- **Tentative call:** (a). The harness already requires Python 3 freely; 3.11 is 2.5+ years old. tomllib is read-only, but slice 1 only needs reads (defaults written via templated string, not round-tripping).
- **Consult?** No. Mechanical; reversible in 5 min if a user complains.

## D2: Defaults source-of-truth location
- **Decision:** Module constant in `scripts/config.py` (a Python dict literal), rendered to TOML on demand via a tiny serializer.
- **Options:**
  - (a) Python dict literal in `scripts/config.py`.
  - (b) Shipped `scripts/config_defaults.toml` next to the script.
  - (c) Embedded TOML string in `scripts/config.py`.
- **Tentative call:** (a). Codex's framing explicitly says "schema lives in code, not a separate file, so resolver and schema cannot drift." Matches.
- **Consult?** No. Followed-from-brainstorm convention.

## D3: Layering precedence
- **Decision:** Built-in defaults → `$XDG_CONFIG_HOME/z-harness/config.toml` (default `~/.config/z-harness/`) → `<repo>/.z-harness/config.toml` (detected via `git rev-parse --show-toplevel`, fallback cwd) → env override (`Z_HARNESS_<SECTION>_<KEY>` style).
- **Options:**
  - (a) As above (4 layers, env wins last) — matches providers.json + adds env compat.
  - (b) No env layer (TOML is sole truth) — cleaner, breaks CI overrides.
  - (c) Reverse global/repo — repo loses to global.
- **Tentative call:** (a). Matches providers.json precedent exactly + preserves the CI override use case.
- **Consult?** No. Direct copy of established precedent.

## D4: `ensure-defaults` write target
- **Decision:** User-global only. `ensure-defaults` writes `~/.config/z-harness/config.toml` if missing, with all defaults plus comments. **Never** writes repo-local automatically.
- **Options:**
  - (a) User-global only (BRAINSTORM guardrail).
  - (b) Also offer `--init-repo` flag for explicit repo seeding.
  - (c) Auto-create repo-local on first repo invocation (rejected — git pollution).
- **Tentative call:** (a) for slice 1. (b) deferred to slice 2 if anyone asks.
- **Consult?** No.

## D5: How migrated commands read config
- **Decision:** Two complementary surfaces.
  - `scripts/config.py export-env --for <command>` emits shell `export FOO=bar` lines for `eval`. Commands eval at setup. Sets `Z_HARNESS_NOTIFY_LEVEL`, `Z_HARNESS_DOCS_ALWAYS_APPLY`, etc.
  - `scripts/config.py get <dotted.key>` for one-off Python/shell reads.
  - `scripts/config.py explain <key>` for debuggability (effective value + source layer).
- **Options:**
  - (a) Above (both export-env and get).
  - (b) `should-notify` exit-code subcommand for boolean gates.
  - (c) Generate a sourceable env file once per command run.
- **Tentative call:** (a). export-env is the universal shape (matches "schema'd env-var replacement layer" framing); get is for ad-hoc inspection. `should-notify` adds API surface for one knob — handle via env test (`[ "$Z_HARNESS_NOTIFY_LEVEL" = "off" ]`).
- **Consult?** **Yes.** This is the public API surface of the loader — hard to rename later; affects every command that ever migrates.
- **Trigger:** Defines/changes public API; names something on a public surface; affects >1 module.

## D6: Event-emission de-dup pattern
- **Decision:** Emit `config_resolved` **once per command run**, keyed by `$RUN`. No PPID stamp.
- **Options:**
  - (a) Once per run.
  - (b) PPID-stamp de-dup like providers.json `provider_shadowed`.
- **Tentative call:** (a). providers.json emits per-key shadows that can fire multiple times in a run; config_resolved is one snapshot of effective state, fires once.
- **Consult?** No. Local behavior, easy to change.

## D7: `docs.always_apply` semantics
- **Decision:** Tri-state enum: `"always"` | `"smart"` (default — current behavior, doc-fetcher dispatched only in heavy flows) | `"never"` (light flows skip doc-fetcher; heavy flows still call it).
- **Options:**
  - (a) Bool — `true`/`false`.
  - (b) Tri-state enum as above.
  - (c) Per-command override map.
- **Tentative call:** (b). Bool conflates "force everywhere" vs "respect current heuristics" vs "kill the optional invocations." Three states is the natural shape.
- **Consult?** **Yes.** This is user-facing semantics; renaming the enum values later breaks user configs.
- **Trigger:** Names something on public surface (config key value); reversibility (changing enum values requires user config migration).

## D8: Config file location for repo-local
- **Decision:** `.z-harness/config.toml` (same directory as `.z-harness/providers.json`).
- **Options:**
  - (a) `.z-harness/config.toml`.
  - (b) `z-harness.toml` at repo root (no dotdir).
  - (c) Inside `z-harness/` (the artifact dir).
- **Tentative call:** (a). Co-locates with providers.json; the `.z-harness/` directory is already a configured concept.
- **Consult?** No. Established convention.

## D9: notify.level enum values + implementation
- **Decision:** Enum `"off" | "approval_only" | "all"` (matches existing README documentation). Slice 1 implements the gate: a `config.py should-notify --event <kind>` subcommand returns exit 0 if a PushNotification should fire, exit 1 otherwise. Commands that currently emit `PushNotification` add a guard: `bash $PLUGIN_ROOT/scripts/config.py should-notify --event approval && <emit notification>`.
- **Options:**
  - (a) Enum + `should-notify` subcommand.
  - (b) Enum + env var test in shell (`[ "$Z_HARNESS_NOTIFY_LEVEL" != "off" ]`).
  - (c) Bool `notify = true/false`.
- **Tentative call:** (a). The `--event <kind>` parameter makes future-proofing trivial (e.g. distinguish phase-end vs approval-gate events) without API churn.
- **Consult?** **Yes.** This is the first behavioral gate; the API shape sets precedent for future gates.
- **Trigger:** Public API surface; affects every command that emits notifications.

## D10: docs.always_apply enforcement point
- **Decision:** Loader exports `Z_HARNESS_DOCS_ALWAYS_APPLY` env var. The light flows (e.g. /z-do, /z-plan-light) read it and dispatch doc-fetcher unconditionally when value is `"always"`, skip when `"never"`, fall back to current heuristic when `"smart"`. Heavy flows (e.g. /z-plan, /z-debug) ignore this knob — they always dispatch doc-fetcher.
- **Options:**
  - (a) As above (env var read in command setup).
  - (b) Make doc-fetcher itself respect the knob (return early).
  - (c) Add a wrapper script that decides whether to call doc-fetcher.
- **Tentative call:** (a). doc-fetcher is dumb-by-design; the orchestrator decides whether to dispatch.
- **Consult?** No. Local convention.

## D11: Documentation tier (docs/human + docs/llm) shape
- **Decision:** New `docs/human/config.md` describing layering, knobs, examples. New `docs/llm/config-design.json` with the schema and load-bearing invariants for future planning runs. Add an entry to `docs/llm/INDEX.json` with `source_file: scripts/config.py`.
- **Consult?** No. Direct application of established two-tier pattern.

## D12: README slim — target shape
- **Decision:** README contains exactly: (1) one-paragraph pitch ("What is z-harness?"), (2) install/uninstall, (3) 3 named quickstart commands (`/z-do`, `/z-plan`, `/z-implement-all`), (4) "Where to look next" with pointers to `docs/human/INDEX.md` and `docs/llm/INDEX.json`. Cut content moves into `docs/human/` (preserved, just relocated).
- **Options:**
  - (a) Target shape above.
  - (b) Abstract "less stuff" (rejected — too vague + Gemini risk).
  - (c) Keep README, move ref material in parallel.
- **Tentative call:** (a).
- **Consult?** No. Editorial decision, easily reverted.

---

## Consult-flagged decisions (3 — under the 5 cap)
- **D5** — public API shape of `scripts/config.py`.
- **D7** — `docs.always_apply` tri-state enum values.
- **D9** — `notify.level` API shape + first behavioral gate precedent.

All within the 5-decision bundle cap. Bundled cross-LLM consultation in Phase 3.
