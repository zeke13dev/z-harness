# Phase 1 — Reality check

## MUST EXIST verifications — all OK
All 12 files SPEC claims exist actually exist (`scripts/{resolve-provider.py,resolve-provider.sh,log-event.sh,plan-path.sh,version.sh}`, `README.md`, `docs/{llm/INDEX.json,human/INDEX.md}`, `commands/{z-plan,z-do}.md`, `skills/{z-do,z-plan}/SKILL.md`).

## WILL BE CREATED — no clashes
All 4 new files (`scripts/config.{py,sh}`, `docs/human/config.md`, `docs/llm/config-design.json`) do not currently exist.

## Findings

### F1 (BLOCKER): SPEC misreads /z-do's current behavior
SPEC §"File 8" claims `/z-do`'s `docs.always_apply = "auto"` "current heuristic preserved verbatim." But [commands/z-do.md:71-83](commands/z-do.md:71) and [skills/z-do/SKILL.md:72](skills/z-do/SKILL.md:72) show /z-do **unconditionally dispatches doc-fetcher** when `docs/llm/INDEX.json` exists — quoting: "Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading." There is no heuristic.

**Impact:** With SPEC as written, default `"auto"` would silently *demote* /z-do behavior to whatever "auto" means — but auto has no meaning in /z-do because there's no heuristic to preserve. Implementer would have to invent one. Either:
- (a) Change default to `"always"`. `"auto"` is reserved for future heuristic-bearing flows; in slice 1 it behaves identically to `"always"`. Document this in `docs/human/config.md` and TASKS T006.
- (b) Drop the tri-state. Make it binary `"always" | "never"` with default `"always"`. Cleaner; no reserved values.

**Recommendation:** (b). The tri-state was post-hoc rationalization; the brainstorm only called out two states ("force" / "skip"). KISS.

### F2 (MAJOR): Z_HARNESS_NOTIFY prose lingers in 16 non-migrated commands
`grep -l Z_HARNESS_NOTIFY` returns 18 files; SPEC migrates 2 (/z-plan, /z-do). The other 16 (`z-implement-all`, `z-debug`, `z-research`, `z-test`, `z-amend`, `z-brainstorm`, `z-fix`, `z-audit`, `z-maintain-docs`, `z-plan-light`, `z-plan-split`, `z-review-all`, `z-implement-next`, plus a few command .md files) still tell users "set `Z_HARNESS_NOTIFY=approval_only`" in prose.

**Doc-fetcher Phase 1 finding established Z_HARNESS_NOTIFY is never read by any script** — so this is cosmetic, not behavioral. But after slice 1 lands:
- /z-plan and /z-do prose: "see `notify.level` in docs/human/config.md."
- The other 16: "set `Z_HARNESS_NOTIFY=...`".
That's a user-facing inconsistency.

**Recommendation:** add T009 — mechanical pass updating prose-level Z_HARNESS_NOTIFY mentions to point at `docs/human/config.md`. Single sed-like edit per file. ~30 min work.

### F3 (MINOR): SPEC's "/z-plan and /z-debug always dispatch doc-fetcher" — partly aspirational
SPEC asserts heavy flows always dispatch doc-fetcher. Confirmed for /z-plan (Phase 1 of its SKILL.md). For /z-debug — verify before implementation. Not blocking.

### F4 (MINOR): docs/human/INDEX.md exists but TASKS doesn't say which sections to update
T001 acceptance says "Every section of the OLD README that's removed is preserved in `docs/human/`" but doesn't enumerate. Implementer has to make the call. Low risk because the README isn't huge, but flag for T001 implementer.
