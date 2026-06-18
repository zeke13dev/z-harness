---
description: "Diagnose and patch a misleading skill file — any SKILL.md under .claude/skills/ in the current repo, or any z-harness commands/*.md / agents/*.md when invoked inside the z-harness repo itself. Inline diagnosis note, surgical edit, reviewer safety ..."
role: workflow
---

You are running **z-harness `/z-skill-fix`** — a meta-command for patching skill / command / agent files that have misled. Treat these files as living documents, not specs.

Target (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question "Which skill misled, and how?" via their native channel. Silent omission is forbidden. -->
**If empty** — use `AskUserQuestion` to ask "Which skill misled, and how?" before proceeding.

Bias toward over-triggering: a skill that misled once will mislead again. The cost of a small edit is negligible compared to the cost of repeating the failure across future conversations.

## Triggers (any one)

1. **User-flagged** — "that skill was wrong", "qt-X led us astray", "the `/z-foo` command did the wrong thing", or direct invocation.
2. **Self-detected mid-skill** — while executing another skill/command, you hit an instruction that references a non-existent path, contradicts repo conventions, is silent on a recurring decision point, or conflicts with another skill. Finish or pause the current task safely, then run this command.
3. **Post-mortem** — after the user and you have worked around a skill problem in conversation. Even if immediate work is done, capture the fix here.

## Discovery — where skill-like files live

Patchable file types in the current working directory:

```bash
find . -path '*/.claude/skills/*/SKILL.md' -not -path './node_modules/*' 2>/dev/null
find . -path '*/.claude/skills/*/*.md' -not -path '*/SKILL.md' -not -path './node_modules/*' 2>/dev/null   # supporting files inside a skill dir
```

Additionally, if the current repo IS `z-harness` (detect via `[ -f .claude-plugin/plugin.json ] && grep -q '"name":\s*"z-harness"' .claude-plugin/plugin.json`):

```bash
find ./commands -maxdepth 1 -name '*.md' 2>/dev/null
find ./agents -maxdepth 1 -name '*.md' 2>/dev/null
```

If the failure originates from a z-harness command/agent and you're NOT inside the z-harness repo, the file is in the plugin install path — patch the source in the user's z-harness source checkout (e.g. `${CLAUDE_PLUGIN_ROOT}`, or wherever they cloned it) rather than the installed copy.

## Setup

1. Resolve the target file from `$ARGUMENTS` (skill name, path, or freeform description).
<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the file-disambiguation question via their native channel. Silent omission is forbidden. -->
2. If multiple files plausibly match, use `AskUserQuestion` to disambiguate.
3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-skill-fix`.

## Procedure

### 1. Diagnosis note (inline, in chat)

Before editing anything, write a short root-cause analysis directly in chat. This forces explicit reasoning and gives the user a chance to push back before the SKILL.md changes. Format:

```
## Skill failure: <name>

**What went wrong:** <one or two sentences — the specific instruction or omission that misled>.

**Surface symptom:** <what we observed: wrong file, missing config, broken handoff, etc.>.

**Root cause:** <why the skill said what it said: stale assumption, missing convention, ambiguous wording, untested handoff>.

**Fix:** <what to change — added clause, removed instruction, corrected path, new pushback line, clearer trigger>.
```

Keep it tight. If the root cause is **not** in the skill file (it's actually a bug in code, or a missing repo-level convention), state that and **stop**: this command only patches skill files. Tell the user the right next step (file an issue, `/z-plan-light` the code, update CLAUDE.md, add a memory) and let them drive it.

### 2. Patch the file

Edit the target file. Prefer the smallest correct change:

- **Wrong fact** (path, binary, command, table name, model name) → fix in place.
- **Missing decision guidance** → add a short bullet to the relevant section, not a new section.
- **Recurring ambiguity** → add one explicit line clarifying the default. No long preamble.
- **Bad handoff between skills** → fix on BOTH sides. Both files should agree on what gets handed off and when.
- **Wrong trigger phrasing** (skill not firing when it should, or firing when it shouldn't) → tighten the `description:` frontmatter, since that's what the harness uses to route.

**Avoid:**
- Don't rewrite a skill wholesale because of one bad instruction. Surgical edits compound; rewrites lose institutional knowledge.
- Don't add hedging language ("you might want to consider…"). Skills are stronger when prescriptive.
- Don't add a new "lessons learned" section. The skill itself should be correct, not a log of every failure.
- Don't bump any `version:` field unless the change is structural.

### 3. Pre-delete referrer check (mandatory if your fix deletes a referenced file)

When the fix (or any task spawned by it) deletes a manifest, config, or other cross-referenced file, **grep for referrers first** and update every hit in the same change. This is a general safety pattern — not qt-bot-specific. Before `git rm <path>`:

```bash
basename=$(basename <path> .<ext>)
grep -rn "$basename" .claude/ docs/ scripts/ manifests/ configs/ 2>/dev/null
```

If any hit is a real reference (not a passing mention in a comment), update or delete it in the same change. **Do not delete the file if you can't or won't update the referrers** — return to the user instead.

### 4. Re-read for consistency

After the edit, re-read the patched file end-to-end (not just your diff). Ask:
- Does the new wording contradict anything else in the same file?
- Does it conflict with a sibling skill that hands off to/from this one? (Grep for the skill name across `.claude/skills/`, `commands/`, `agents/`.)
- If a future Claude reads only this file cold, does it now lead them to the right action?

If any answer is no, iterate before proceeding to the safety gate.

### 5. Codex-reviewer safety gate (mandatory)

A skill file edit can silently contradict another section of the same file or another skill. Catch that here.

```bash
git diff -- <patched file> > /tmp/skill-fix-$RUN.patch
```

Spawn the reviewer:

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="reviewer",
  description="Codex review of skill fix",
  prompt="task id: skill-fix-$RUN\ntask description: <one-line root cause from diagnosis note>\nacceptance criteria: the patched skill file no longer misleads on <specific failure mode>; no contradictions introduced elsewhere in the file or in sibling skills.\ndiff.patch path: /tmp/skill-fix-$RUN.patch\nchanged files: <abs path>\nrelevant_docs: (none)\n$BASE: (n/a — meta-skill edit, no SPEC.md exists)\n\nNote to reviewer: this is a SKILL.md / command.md / agent.md edit, not application code. Scrutinize for (1) contradictions with other sections of the same file, (2) ambiguity the fix purports to remove but doesn't actually remove, (3) handoff drift if the file references other skills, (4) hedging language that weakens a gate. Skip generic code-review concerns (broad except, etc.) — they don't apply."
)
```

Parse the return:
<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the second-failure decision (proceed anyway / patch manually / abandon) via their native channel. Silent omission is forbidden. -->
- **Blockers/majors** → re-edit. Re-run the reviewer once more. Second failure → halt with `AskUserQuestion` (proceed anyway / patch manually / abandon).
- **No blockers/majors** → accept.

### 6. Commit decision (delegated to user)

Do NOT auto-commit. Tell the user:

> Skill patched at `<path>`. Codex review passed. Commit when ready — recommended message: `skills: fix <name> — <one-line root cause>`.

If the repo's `CLAUDE.md` has an explicit commit-on-every-step rule, mention it; otherwise leave the commit cadence to the user.

## When NOT to use this command

- **Bug in repo code, not in a skill instruction** → use `/z-plan-light` for the fix, write a regression test.
- **Missing project convention that doesn't belong in any one skill** → propose a `CLAUDE.md` addition or a memory entry, then stop.
- **Skill is correct but user disagrees with the policy** (e.g. wants to skip a gate the skill enforces) → that's a policy debate, not a fix. Do not weaken gates because they were inconvenient once.
- **Skill produced the right output but the user wanted something else** → clarify the request; the skill isn't broken.

## Pushback

- "Just delete that line, it's annoying" → push back if the line is a gate or pushback rule. Inconvenience is not a defect.
- "Add a workaround for this one case" → push back; one-case workarounds are how skills rot. Either the case generalizes (then patch cleanly), or it doesn't (then it's a one-off, not a skill change).
- "Don't bother with the codex review for a small fix" → push back; the review is the correctness guarantee that a contradictory edit didn't sneak in.

## Out of scope

- Repo code changes → `/z-plan-light` or normal edit cycle.
- `CLAUDE.md` edits → user-driven; this command stays in skill/command/agent files.
- Memory edits → handled by the auto-memory system; this command does not write memory.
- Adding a new skill from scratch → just create the file with the Write tool; this command patches existing ones.

## Hard rules

- **Always run the reviewer safety gate.** No exceptions.
- **Never commit on the user's behalf** unless they've explicitly said to.
- **Never weaken a gate or pushback rule** to make a skill more convenient.
- **No emojis** in patched skill files.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Step 5 reviewer |
| `ask_user` | yes | Empty-args question; Setup step 2 file disambiguation; Step 5 second-failure decision |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
