# SKILL-STYLE.md — authoring contract for z-harness skills and agents

Distilled 2026-07-10 from the blessed read-through of post-cleanup z-plan,
z-explore, and z-fix (skill-overhaul-phase1, T103). Binding for every
`skills/*/SKILL.md` and `agents/*.md` write per the Enforcement section.

**The generating rule: a skill is judgment prose around a handful of calls to
shared mechanisms.** If a line is not a decision, a gate, or a phase's
purpose, it belongs in a script, fragment, or referenced contract — not in
the skill. Every rule below is this rule applied somewhere.

**The whole shape:**

```
frontmatter                          ≤6 lines (§1)
mission + argument gate + boundary   ~5 lines (§1)
flag parse + preflight               ~10 lines (§2, §4)
Phase 1..N                           judgment prose; 1 telemetry line each (§3, §5)
teardown                             ~3 lines (§2)
Hard rules                           ≤10 lines
```

Size targets (soft tripwire): simple command ≤250 lines, standard ≤400,
orchestrator ≤1,500. Corpus grounding: post-cleanup z-fix 426, z-explore 623 —
both should shrink further under this contract. Oversize is presumptive
evidence of inlined ceremony: the remedy is EXTRACTION into scripts/fragments/
shared contracts (§2, §6), never compressing judgment prose (§3).

---

## 1. Structure + frontmatter

Frontmatter — omit any field sitting at its default:

```yaml
---
name: z-<command>                # matches directory name
description: <what it does + when to reach for it; front-load the keywords
  the model routes on>
argument-hint: "<args> [--flags]"   # quote if it contains [ ] or ': '
audience: user | maintainer | internal
driver_features_required: [subagent, ask_user]   # only what's actually used
---
```

Defaults, omitted unless overridden: `disable-model-invocation: false`,
`runtime: c1`, `unsupported_driver_behavior: explicit_gate`. `audience`
semantics: `user` = normal-work command (z-plan, z-fix); `maintainer` =
operates on z-harness itself (z-update, z-export); `internal` = invoked by
skills/watchers, not humans — pair with `disable-model-invocation: true`
(precedent: z-suggest-memory, T004).

Body opens with exactly three moves (z-fix:13-24 is the model):
1. Mission line — `You are running **z-harness \`/z-x\`** — <one sentence>.`
   plus the envelope if one exists ("Target: ≤15 min wall time").
2. `$ARGUMENTS` + empty-args ask — never invent the missing input.
3. Wrong-tool boundary — what this is NOT for and where to route
   ("root cause unclear → STOP, recommend /z-debug").

Then phases, in execution order. A phase is the unit of resumability: it ends
by making its output durable (artifact or archive checkpoint) before the next
begins. Close with `## Hard rules` — only invariants unique to this skill.

Artifacts: ONE primary artifact per command (FIX.md, MAP.md, INTENT.md),
sections inside it, no satellite files (z-fix:246). Frontmatter on persistent
artifacts: `artifact, slug, generated_at, command, input_hash, depends_on`.
All writes under `$Z_HARNESS_PLAN_DIR/` (+ `archive/$RUN/`). No emojis.

Gated callsites (`ask_user` / `subagent`) keep the one-line
`<!-- RUNTIME-GATE: ... -->` comment. The closing "Runtime contract
conformance" table is RETIRED for rewritten skills — frontmatter declares the
features, inline comments mark the sites; one source each, no summary table.
(Tooling note: no test or script consumes the table; rewrites delete it.)

---

## 2. Ceremony delegation

Run lifecycle is one call each way — z-preflight.sh / z-teardown.sh own
resolve, session-id, RUN stamp, claim, register, run-brief init, run_start,
kernel resolution, and the reverse sequence (contracts in the script headers;
LEDGER T005). Never re-inline any of it.

```bash
# Capture BEFORE eval — $? after eval loses the script's exit-code contract.
PREFLIGHT_OUT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-preflight.sh" \
  --command /z-x --slug "$SLUG" --intent "$TASK_TEXT")"
PREFLIGHT_RC=$?; [ "$PREFLIGHT_RC" -eq 0 ] && eval "$PREFLIGHT_OUT"
...
bash ".../scripts/z-teardown.sh" --run "$RUN" --slug "$Z_HARNESS_SLUG" \
  --command /z-x --status "${FINALIZE_STATUS:-complete}"
```

**Standard outcomes are referenced, not restated.** On contention
(exit 10) present the standard menu — proceed-anyway / abort / new-slug,
unattended default abort — documented ONCE in the z-preflight.sh header. A
skill writes only its deviations from the standard menu. Same principle for
the corrupt-lock case (exit 11).

**Read-only commands run the lifecycle minus the claim** (`--no-claim`;
`CLAIM_HELD=0`). They still register and run-brief — that's what makes them
visible to managed sessions and watchers. A claim is a write-intent mutex;
read-only work never contends. Writer commands preflight in ALL their modes —
no per-mode ceremony branching (z-explore quick preflights because deep does).

**Checkpoint seams are one call.** At a durable boundary:
`checkpoint-seam.sh <seam-id> <artifact> <resume-cmd>` (thin wrapper over
check-compaction.sh + write-clear-checkpoint.sh; Level-2 canary authors it —
today's inline 40-line env-var blocks are exactly what it absorbs). A skill
contributes only its seam TABLE: where the boundaries are, what artifact makes
each durable (z-explore:139-149). Never write handoff.json directly.

**Every controlled exit funnels through teardown — one funnel, no exceptions
but one.** Success, user stop, wrong-tool exit, auto-bail, halt on blocker:
all run the SAME `z-teardown.sh` call, differing only in
`--status complete|aborted` (halts set `RB_HALT_REASON` first so the brief
records why). A skill never writes a bespoke cleanup path per exit, and never
`exit`s past the funnel — an exit that skips teardown leaks a claim, a
registry record, and an unfinalized brief. The ONE exception: a
clear-checkpoint PAUSE is not an exit — no teardown, the next invocation
resumes. Teardown is idempotent, so a doubtful path calls it anyway.

**Crash safety is the reap layers' job, not the skill's.** A killed session
cannot run teardown; the system self-heals instead: claims carry heartbeat
TTLs with stale-takeover, registry records are reaped on staleness by any
later reader, and `/z-reconcile` sweeps worktrees/plans/locks. The skill's
obligation is containment: **never create durable state outside the managed
set** (claim, registry record, run-brief, worktree, `$Z_HARNESS_PLAN_DIR/`
artifacts). Anything novel lands under the plan dir where the sweep can see
it — no ad-hoc lock files, no state in repo root or /tmp that outlives the
run.

**Inline bash survives only as**: a command-specific mechanical one-off with
no owning script and no second consumer (z-fix's `git diff > archive/diff.patch`,
z-explore's input_hash). The test: a second consumer → script/fragment; a
decision inside → prose; otherwise it stays, and stays short.

---

## 3. Prose where judgment lives; script where it doesn't

**Judgment — prose, keep:** z-plan's premise check ("Does the stated goal
actually solve the underlying problem? … Do not plan around a flawed
premise."), z-fix's auto-bail thresholds and one-reason-it-might-be-wrong
rule, z-explore's citation demotion rule (no file:line → it's a Gap; never
fabricate a citation). No script can own these; they ARE the skill.

**Ceremony — delegate, cut:** pre-rewrite z-plan Setup step 5 spent ~140
lines on version stamp, session-id persist/restore, five-way claim table,
register with graduated failure, kernel resolution — all mechanical, all
byte-duplicated across skills, now one preflight call plus a short branch.

**The mixed case is the trap.** A block interleaving mechanics with a
decision gets SPLIT — mechanics to the wrapper/script, decision to prose —
never kept whole. Precedent: the resolver gate (§4): one call inline, prose
for the branches that matter.

Corollaries: never restate what a script header or contract doc already
documents — reference it. Never paste the same ≥10-line block into two skills
— fragment or script (§6). A canonical mechanism is defined once and pointed
to, never copy-pasted.

---

## 4. Flags, config, and asking

**Precedence: flags > config > resolver-mediated ask.**

**Flags are modifiers, not modes** (`--depth=deep`, `--ack`, `--tasks=`); a
different job is a different command. Grandfathered exception: `z-plan --full`
(legacy SDD) stays, intent remains the default, `--full` fires only on
explicit flag/config/SPEC.md-guard; no NEW flag-routed modes, and rewrites
don't fork grandfathered ones into new commands. Parse flags first, strip
them from the cleaned argument text (never leak into slugs/prompts/input_hash),
enumerate all flags in `argument-hint`.

**Config** reads via `config.py get <key>` (or one `export-env` at setup) with
an explicit default at every callsite. Env vars are per-run plumbing, never
preference transport.

**Asking:**
- `AskUserQuestion` = finite control-flow forks only (collision,
  proceed/abort, approve/amend/stop).
- Judgment calls = conversational prose with tradeoffs and a stated
  recommendation — not a popup (z-fix Phase 5; z-plan's single prose brief +
  one gate).
- Never ask what the codebase can answer (self-serve via doc-fetcher/Explore
  first). Batch decisions into one gate, not a popup sequence.
- Soft asks with a stable `question_id` go through
  `config.py resolve-question` and branch on the envelope; the four-branch
  semantics (skip / prefill / ask / halt) are documented ONCE in
  docs/human/config.md — reference, don't restate. Resolver errors fall
  through to ask; never silently skip.
- Hard safety gates (collision, wrong-tool, cost) run UNCONDITIONALLY; the
  resolver never bypasses them (z-fix:63). State the unattended default per
  risk gate (abort). Resolved asks emit their decision event (log-decision.sh).

---

## 5. Telemetry + run-brief

The wrappers own the run envelope (`run_start`/`run_end` with version blob and
status). The skill owes exactly three things:

1. **One line per phase**: `log-phase.sh` wrap/start-end for wall_ms (state on
   disk — never a T0 shell variable across tool calls), with
   `user_wait_start/end` bracketing any user wait.
2. **Events at the moments that matter**: dispatch, gate resolution, halt
   (with `reason`), route decision, skip, failure, drift. `snake_case`,
   command-prefixed where skill-specific (`fix_halt`, `explore_failure`);
   payloads via `json.dumps` when any field can carry quotes. Best-effort
   (`|| true`) — telemetry never breaks a run; no dead `|| log` after
   self-logging scripts.
3. **Run-brief sections before teardown**: `outcome` (one sentence, real
   counts) and `next` (label + command, `null` when nothing follows).
   Chat/push completion text renders FROM run-brief.json — never author
   independent completion prose. Every terminal halt routes through the
   halt-finalize fragment (`RB_HALT_REASON`) before teardown. A
   clear-checkpoint pause is NOT a terminal: no finalize, no teardown; the
   next invocation resumes.

Notifications: resolve from config (`notify.level`, `should-notify`);
reference docs/human/config.md. Halts and approval gates notify regardless of
level.

---

## 6. Fragments

`_fragments/*.md` is the include tier between "inline once" and "script":
shared orchestration TEXT the model must read and act on identically across
skills (finalize sequences, halt protocols).

- Include at the execution point (`<!-- include: _fragments/... -->`); never
  paste a fragment body inline. Two skills sharing a ≥10-line block = that
  block becomes a fragment or script.
- Per-command variants are distinct files named for their host
  (`run-brief-halt-finalize-execute.md` vs `-plan.md`) — fork, don't
  parameterize prose with conditionals.
- A fragment documents the variables it expects; the caller sets them
  immediately before the include. Fragments read, never invent, caller state.
- Fragments are leaf-level: no nested includes, no decision gates inside —
  a fragment that wants to ask a question is a skill section.
- Cross-skill canonical sections live in the owning SKILL.md under a stable
  anchor; others reference by name.
- Run-brief-family fragments are covered by `scripts/lint-run-brief.sh`.

---

## 7. Agent files (`agents/*.md`)

An agent file is a role, a contract, and a return shape — small.

- **Models are config-routed, not declared.** Frontmatter `model:` is the
  checked-in FALLBACK only; selection resolves via `[model_routing]`
  (`native_agents.<agent>` override; implementer via
  `model_routing.implementer.<tier>` from the task's complexity stamp). Skill
  dispatch blocks resolve via config before any `Agent(model=…)` call — never
  a hardcoded label as the routing decision.
- **The return contract is part of the file** — STATUS-headed, field-by-field,
  size-capped (implementer's `STATUS:/FILES_CHANGED:/LEDGER_DECISIONS:`;
  reviewer's verdict/blockers/majors). Orchestrators parse blind; changing a
  return shape is a breaking change and is called out as such.
- **Read-only agents omit Edit/Write** and state the invariant in the body.
- **The description states dispatch conditions**, not capabilities — it is
  the routing surface ("ALWAYS dispatch BEFORE Explore in any planning
  phase").

---

## Enforcement

- **Ratchet scope.** Binds in full: (a) all NEW skills/agents, present and
  future; (b) the phase-1 Level-2 rewrite set. Binds hunk-wise: (c) any
  touched section of an existing file — pre-existing violations outside the
  touched hunks are follow-up candidates, not findings. The corpus converges
  file-by-file.
- **Generation-side and review-side.** The implementer loads this file and
  AUTHORS to it whenever touching `skills/*/SKILL.md` or `agents/*.md`;
  reviewer, auditor, and plan-style-reviewer enforce it and cite section
  numbers in findings ("SKILL-STYLE §2: re-inlined claim ceremony"). Wiring
  lives in those four agent files (criterion #13).
- Level-2 rewrites are held to: same phases, same gates, same event
  vocabulary; lines removed must be ceremony absorbed per §2/§6, never
  judgment prose per §3.
- **Mechanical lint: deferred.** A full lint-skill-style.sh is a post-phase
  follow-up once the corpus is uniform. Level 2 only teaches
  lint-frontmatter.sh the `audience` field and omitted-default fields
  (absent-at-default passes).

---

## Appendix — example skill (the whole shape, ~70 lines)

A fictional `/z-triage` showing every section of this contract in place.

```markdown
---
name: z-triage
description: Classify an incoming bug report as fix-now / plan / debug and
  hand off with evidence. Use when a report arrives without a diagnosis.
argument-hint: "<bug report or symptom>"
audience: user
driver_features_required: [subagent, ask_user]
---

You are running **z-harness `/z-triage`** — route a raw bug report to the
right command with evidence attached. Target: ≤5 min.

Report (from `$ARGUMENTS`): $ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed -->
**If empty**, ask "What's the symptom?" — do not invent. (Pre-preflight: a
plain exit here is fine — nothing is registered yet.)

This is NOT a fix or investigation command — it only classifies and routes.
If the user already has a diagnosis, recommend `/z-fix` and stop (via the
Halt funnel below once preflight has run).

## Setup

Parse flags (none yet). Derive slug `triage-<short>`; then:

    PREFLIGHT_OUT="$(bash ".../scripts/z-preflight.sh" \
      --command /z-triage --slug "$SLUG" --no-claim --intent "$ARGUMENTS")"
    PREFLIGHT_RC=$?; [ "$PREFLIGHT_RC" -eq 0 ] && eval "$PREFLIGHT_OUT"

Read-only command: `--no-claim` (registers for watcher visibility, never
contends). On exit 10/11 follow the standard preflight menus (script header).

## Phase 1 — Evidence scan

One `log-phase.sh` wrap. If `docs/llm/INDEX.json` exists, dispatch
doc-fetcher (Haiku) with the symptom keywords; Read at most 3 files to fill
gaps. Do not spawn Explore — too heavy for triage.

Judgment: does the report contain (a) a repro, (b) a plausible cause, (c)
neither? Weigh contradicting signals explicitly — a stack trace is not a
diagnosis.

## Phase 2 — Route + hand off

Write `$Z_HARNESS_PLAN_DIR/TRIAGE.md` (the one artifact): symptom, evidence
with file:line citations (uncited claims go under Gaps — never fabricate),
and the routing call with one-line rationale.

<!-- RUNTIME-GATE: ask_user; category=decision -->
Present the routing recommendation conversationally with the tradeoff
(fix-now vs plan vs debug), then one gate: accept route / change route /
stop. Emit `triage_route` with the choice. Do not auto-dispatch the target
command.

## Finalize

Set run-brief `outcome` ("Routed to /z-fix; repro captured") and `next`
(the chosen command), then:

    bash ".../scripts/z-teardown.sh" --run "$RUN" --slug "$Z_HARNESS_SLUG" \
      --command /z-triage --status complete

## Halt funnel

EVERY non-complete exit after preflight (wrong-tool, user picked "stop",
evidence scan came up empty) lands here — never a bare `exit`:

    RB_HALT_REASON="<why>"   # recorded into the brief by the halt fragment
    bash ".../scripts/z-teardown.sh" --run "$RUN" --slug "$Z_HARNESS_SLUG" \
      --command /z-triage --status aborted

(Only exception: a checkpoint PAUSE — no teardown; next invocation resumes.)

## Hard rules

- Never fix anything here — classify and route only.
- Never auto-dispatch the routed command.
- Citations or Gaps — no uncited findings.
- No exit past the funnel: complete → Finalize, everything else → Halt funnel.
```
