# z explore — GRILL.md

## What's the question?

A user-facing command called `z explore` that replaces `z map` as the primary terrain-discovery surface. It should scale by depth: cheap cited scouting at `--depth=quick`, reusable bounded terrain at `--depth=standard`, and full MAP.md + cross-LLM critique at `--depth=deep`.

## What triggered this?

The original framing treated `z explore` as a lightweight scout beside `z map`. The corrected intent is different: the user has never actually used `z map` and was thinking of `z explore` as the command they would reach for instead. The command name should own the whole terrain-discovery ladder, with `z map` becoming legacy/obsolete rather than a parallel heavier sibling.

## Pain magnitude

High. The current command split makes the natural verb (`explore`) unavailable or artificially small, while the formal verb (`map`) owns the durable artifact path. That forces users to know whether they need a scout or a formal map before they have explored anything.

The desired surface is:
- one command for terrain discovery;
- an explicit depth knob to control cost and artifact durability;
- the same citation/no-recommendation discipline at every depth;
- a deep path that keeps existing MAP.md consumers working;
- a standard path that can later feed `/z-plan` without forcing full `/z-map` ceremony.

## Audience

Anyone using z-harness who needs codebase terrain before deciding what to do. New users should learn `/z-explore`, not `/z-map`; advanced workflows can still request deep mode when they need durable MAP.md terrain.

## The 80% version

A command that:
1. Takes a natural-language terrain question about the codebase
2. Parses `--depth=quick|standard|deep` (`standard` likely default)
3. Runs doc-fetcher first when docs/llm exists
4. Dispatches bounded Explore facets for uncached/source gaps
5. Enforces citations for every finding and demotes uncited claims
6. At `quick`, returns inline findings/gaps/start-here with no cost gate, no MAP.md, no critique
7. At `standard`, persists reusable `EXPLORE.md` and `surface-map.json` with caps/truncation status
8. At `deep`, runs the existing `/z-map` pipeline and writes MAP.md with cross-LLM critique
9. Marks `/z-map` as legacy compatibility for `/z-explore --depth=deep`
10. Leaves sibling commands as advisory next steps only

## Killable scope

- **Approach recommendations** — never part of terrain discovery; keep the no-recommendation invariant.
- **Automatic sibling dispatch** — do not call `/z-plan`, `/z-report`, `/z-explain`, `/z-learn`, `/z-brainstorm`, or `/z-research` automatically.
- **Immediate MAP.md redesign** — deep mode must preserve compatibility first.
- **Interactive tutoring** — remains `/z-learn`.
- **Audit/bug-finding semantics** — remains `/z-audit` and `/z-debug`.
- **Unlimited depth knobs** — start with exactly `quick`, `standard`, `deep`; avoid per-phase micro-flags until real use proves a need.

## Hard constraints

- Must reuse/promote the existing `explore` agent definition and `doc-fetcher` grounding path
- Must use existing logging infrastructure (`log-event.sh`, `plan-path.sh`)
- Must preserve existing MAP.md downstream compatibility at deep depth
- Must update `/z-plan` precontext direction instead of preserving v1 isolation
- Must make `/z-map` legacy/obsolete in docs or as a compatibility wrapper
- Must not duplicate mechanisms from `/z-explain`, `/z-learn`, `/z-report`, `/z-brainstorm`, or `/z-plan`
- Must follow the same SKILL.md structure as other commands

## Success signal

The user can run:
```
/z-explore "how is X connected to Y" --depth=quick
```
and get cited findings/gaps inline.

They can later run:
```
/z-explore "how is X connected to Y" --depth=standard --slug=x-y-terrain
```
and get reusable bounded terrain artifacts.

They can run:
```
/z-explore "how is X connected to Y" --depth=deep --slug=x-y-terrain
```
and get a MAP.md equivalent to current `/z-map`, including cross-LLM critique and the no-recommendation section.

`/z-plan` can eventually use those fresh findings instead of re-discovering the same terrain.

## Open branches

1. **Default depth**: Should omitted `--depth` mean `standard` (recommended) or `quick`? Standard best matches “primary surface command” while quick optimizes cost.
2. **Artifact names**: Standard mode should likely write `EXPLORE.md` plus `surface-map.json`; deep keeps `MAP.md`.
3. **Legacy wrapper**: Should `/z-map` physically delegate to `/z-explore --depth=deep` or keep its current implementation with a deprecation notice until migration is complete?
4. **Plan consumption**: Should `/z-plan` consume standard `EXPLORE.md` immediately in this implementation, or should this plan only define the schema and leave consumption to a follow-up? The corrected intent argues to include it.
5. **Research migration**: Should `/z-research` dispatch `/z-explore --depth=deep` now or continue using `/z-map` until the wrapper is proven?
