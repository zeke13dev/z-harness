---
artifact: brainstorm
slug: postmortem-memory-nudge
generated_at: 2026-05-27T04:22:38Z
command: /z-brainstorm
input_hash: 52cc3a2678625110
depends_on: []
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: codex
---

## Framing: claude

### Framing
The zero-memories result is not a signal-detection failure — the review-agent infra is sound. It's a funnel-collapse problem: Phase 9 has at least four independent silent bail-out gates before a single candidate reaches the user, and the qt-bot deployment makes the very first gate (missing `Z_HARNESS_PLAN_DIR`) fire on every remote run. The user never sees a failure, never sees a skip, never sees a nudge. The pipeline exists entirely in a dark branch. The right fix is not to make the detection smarter; it's to collapse the silent-skip cascade, fix the qt-bot deployment gap, and add a single visible "retro available" nudge at the natural session end — even when zero candidates are produced.

### Core hypothesis
The primary cause of zero memories is infrastructure invisibility compounded by an undeployed precondition. Specifically: (a) qt-bot never reaches Phase 9 because `Z_HARNESS_PLAN_DIR` or `TAGS.txt` is absent on the remote; (b) even for local z-harness runs, Phase 9 is entirely silent on empty-candidates — the user has no feedback loop confirming the phase ran; (c) the `Z_HARNESS_PLAN_DIR` env var may not survive from the plan-discovery step to the Phase 9 bash invocation depending on how the orchestrator shells the command; (d) the AskUserQuestion UX is buried as phase 9-of-9 after a full implementation run when user attention is lowest. The auto-memory parallel path (7 entries in MEMORY.md) demonstrates the user IS willing to accept memory writes — just not from a system that's invisible.

### Risks
- **Over-correction toward always-on nudge:** If every /z-implement-all ends with "want to run a retro?" regardless of run quality, users learn to dismiss it. Nudge fatigue is a real failure mode — worse than silence.
- **Confusing /z-improve with a memory retro:** Users may conflate "harness retro" with "run retro" if both are nudged at session end. The two are distinct and the distinction must be visible in any nudge copy.
- **qt-bot deployment as prerequisite:** Any UX fix is worthless for qt-bot unless `docs/llm/INDEX.json` + `TAGS.txt` are deployed to zeke-pc. Fixing the nudge without fixing the deployment gives false confidence.
- **AskUserQuestion at session-end is low-attention:** Users finishing a long impl run are in "done" mode. A blocking question at phase 9 may get reflexively dismissed. A non-blocking push-notify with a follow-up option is better than a blocking AskUserQuestion.
- **The /z-debug→z-suggest-memory gap:** The description says mandatory but the code says nothing — if /z-debug is the primary memory-production path and it's broken, fixing Phase 9 alone leaves most of the intended memory surface inactive.

### Plan implications
- Fix qt-bot deployment: ensure `docs/llm/`, `TAGS.txt`, and the memory infra are synced to zeke-pc as part of install/update flow.
- Fix the `Z_HARNESS_PLAN_DIR` persistence: verify env var survives to Phase 9; if not, derive it from `BASE` which is already resolved.
- Add a terminal-summary nudge line at /z-implement-all session end regardless of Phase 9 outcome — even "Memory retro ran (0 candidates surfaced)" makes the phase visible.
- Convert the empty-candidates silent exit into a visible "retro ran, nothing notable found" line in the finalize summary — not a push-notify, just text.
- Wire /z-debug to actually call /z-suggest-memory (its description promises this but the code doesn't deliver).
- Do NOT create a new /z-postmortem skill — it would fragment the retro surface.
- Nudge policy: one-line terminal mention (not blocking AskUserQuestion) when Phase 9 produced zero candidates; existing AskUserQuestion flow remains for when candidates ARE produced.

### What would change my mind
- If /z-implement-all telemetry showed Phase 9 actually firing and returning candidates that users are skipping, the problem would be candidate quality not visibility — then fix the Haiku review-agent's signal detection, not the UX.
- If the qt-bot remote does have `docs/llm/INDEX.json` deployed, the qt-bot skip hypothesis is wrong and the failure is purely local to Phase 9 execution flow.
- If user session patterns show the user is present and reading phase 9 output (via transcript inspection), then the silent-empty-candidates behavior is the real culprit rather than low attention at session end.
- If the 7 global MEMORY.md entries were written manually (not via auto-memory), that would suggest the user actively dislikes automated memory systems — making any nudge approach the wrong direction entirely.

---

## Framing: codex

### Framing
This is not an auto-memory question yet. It is a reachability and observability failure disguised as a memory-authoring policy question.

The pipeline has a write boundary, a reviewer, candidate limits, and approval UX. What it lacks is proof that the review path actually runs in the contexts where learning should happen. A silent Phase 9 after `/z-implement-all` is not a learning loop; it is an invisible best-effort epilogue.

### Core hypothesis
Zero memories are produced because the system is optimized to disappear before `z-suggest-memory` is ever reached.

The dominant failure is upstream eligibility: missing `Z_HARNESS_PLAN_DIR`, missing `TAGS.txt`, empty diff, zero completed tasks, and remote repo context drift. Even when the reviewer runs, zero candidates are silent. `/z-debug` also claims mandatory memory suggestion without dispatching the sole write path, so the lifecycle contract is false.

### Risks
Auto-running memory authoring after `/z-implement-all` risks creating low-signal approval fatigue while leaving the real failure untouched.

Keeping current silence is worse in one specific way: it lets users believe z-harness is learning when it is mostly skipping. The dangerous ambiguity is "nothing worth remembering" versus "memory review never ran."

Noisy notifications are also a real risk under `approval_only`. Every skip should not page the user. The system needs state clarity before user interruption.

### Plan implications
Separate the collapsed states:

- `not_applicable`: no meaningful implementation result or missing required context.
- `skipped_broken_context`: completed work existed, but metadata like `Z_HARNESS_PLAN_DIR` or `TAGS.txt` was missing.
- `ran_empty`: reviewer executed and returned zero candidates.
- `needs_user`: candidates exist and require Accept/Edit/Skip.

Fix caller-side propagation of `Z_HARNESS_PLAN_DIR` before changing authoring behavior. Add structured telemetry for every skip. Add a low-noise visible nudge only for `skipped_broken_context` and maybe `ran_empty`, not every benign non-event.

Keep `z-suggest-memory` as the only mutating path. Make `/z-debug` either dispatch it or stop claiming it does.

### What would change my mind
- Evidence that Phase 9 reliably runs with valid plan dir, completed tasks, tags, and non-empty diffs, yet still returns zero candidates.
- Evidence that users regularly reject high-quality candidates, implying candidate quality or approval UX is the bottleneck.
- Evidence that qt-bot has complete local harness docs and plan metadata but still skips.
- A deliberate product decision that implementation memory should only happen inside explicit `/z-improve`, not after `/z-implement-all`.

---

## Framing: gemini

### Framing
The memory system is a "Phantom Pipeline" — architected with significant complexity and subagent logic, yet rendered inert by a design philosophy of extreme silence. We have built a high-confidence gate (human approval) atop a low-visibility observer (Haiku), and then hidden the entire process behind brittle environment checks. The result is a system that "fails safe" into non-existence rather than "failing loud" into a feedback loop. We are currently valuing "lack of annoyance" over "presence of value," which has led to a stagnant knowledge base.

### Core hypothesis
The "zero-memory" outcome is a product of **Environment Anemia** and **Feedback Erasure**:
1. **Environment Anemia (The Bash Gate):** `run-memory-review.sh` acts as a silent kill-switch. Because it exits 0 on all skip conditions (missing `Z_HARNESS_PLAN_DIR`, `TAGS.txt`, or an empty diff), the orchestrator never knows if it skipped because "nothing was found" or because "the environment was broken." In remote/headless contexts like `qt-bot`, transient env vars or missing `docs/llm/` files are likely triggering these silent skips.
2. **Model Conservatism (The Haiku Trap):** `review-agent` is explicitly instructed to "Emit zero rather than padding." Combined with a 5,000-line truncated diff and Haiku's relatively small context window, the model is likely discarding nuanced architectural signals in favor of "safe" empty results.
3. **The "Vaporware" Integration:** The claim that `/z-debug` and `/z-improve` call `z-suggest-memory` is currently a hallucination in the documentation. Since the manual authoring paths are disconnected from the write tool, and the automated path is silent, there is literally no active friction-free way for a memory to reach `MEMORIES-FLAT.md`.

### Risks
- **Spam Fatigue:** Moving from "Silent 0" to "Noisy Nudges" risks training the user to instinctively hit "Skip-all" if the Haiku suggestions are low-value.
- **Hallucinated Wisdom:** If we pressure the system to produce *something*, Haiku may start generating generic "Gotchas" (e.g., "Always check for nulls") that pollute the high-signal documentation.
- **Context Bloat:** If we "nudge" every time, the orchestrator's session history will grow with rejected candidates, ironically making the next run more expensive.
- **Inertia:** A "nudge" that requires the user to stop their current flow and enter "Author Mode" after a long implementation run will likely be ignored.

### Plan implications
- **First-Class Post-Mortem:** Promote Memory Review from a "Phase 9" afterthought to a standalone skill (`/z-postmortem`). This decouples memory generation from the implementation loop and allows for more expensive/capable models (Sonnet/Opus) to run on the full session history, not just the diff.
- **Visible Heartbeat:** Replace silent skips in `run-memory-review.sh` with a "Status: Skipped" message that is surfaced in the UI. The user needs to know *why* the system didn't look for memories.
- **Mandatory Manual Nudge:** If Phase 9 finds zero automated candidates, provide a single, one-line prompt: *"No automated memories found. Use `/z-improve` to manually record hard-won insights from this run."*
- **Connect the Dots:** Physically implement the `z-suggest-memory` calls in `/z-debug`, `/z-fix`, and `/z-improve`. The infra exists; the integration is missing.

### What would change my mind
- **The "Human Gap":** If data shows that users actually find the most value in Claude Code's native, unstructured auto-memory, our structured `z-harness` memory system might be architecturally redundant.
- **Tool Failure:** If we find that `review-agent` *is* producing candidates but the orchestrator is crashing during the `AskUserQuestion` phase due to UI/CLI limitations, then the problem is a bug, not a design failure.
- **Signal Rarity:** If we analyze 100 successful runs and find that only ~2% contain a "recurrence-worthy" insight, then "Silent by Default" is actually the correct design, and the "Zero Memories" state is simply a reflection of straightforward work.

---

## Anti-bias check

**Section-by-section comparison:**

### (1) Framing
- Claude: Pipeline invisibility + silent-skip cascade + qt-bot deployment gap. Pragmatic, infrastructure-focused, lists multiple causes.
- Codex: "Reachability and observability failure disguised as a policy question." Single sharp diagnostic sentence — correctly centers the failure type.
- Gemini: "Phantom Pipeline" — vivid, memorable, but trades precision for color.

**Winner: Codex.** Claude picks Codex over itself (explicit justification): Codex's one-sentence framing is more actionable as a design directive. It correctly identifies that the question "auto-run vs nudge" is premature — the question is whether the pipeline can actually reach the user at all. This reframes the entire problem space in a way that prevents premature optimization of the wrong variable. Claude's framing is correct but lists multiple causes without a unifying insight.

### (2) Core hypothesis
- Claude: Multi-factor list (qt-bot env var, env survival, low-attention UX, /z-debug gap, parallel MEMORY.md). Comprehensive but diffuse.
- Codex: "Optimized to disappear" — upstream eligibility failures plus false lifecycle contract. Tight and memorable.
- Gemini: Three named hypotheses including **Haiku Trap** (model conservatism + 5000-line truncation = missed signals). Only ideator to raise model-conservatism as a factor.

**Winner: Gemini.** Gemini surfaces a hypothesis neither Claude nor Codex raised: even when Phase 9 fires with a real diff, Haiku conservatism + 5000-line cap may cause the review-agent to return empty. This is independently testable and matters for the plan (would require a different fix than env var propagation). Claude picks Gemini over itself here: Claude's hypothesis is valid but omits this dimension. Codex's is tight but also omits the model-conservatism angle.

### (3) Risks
- Claude: Five risks including /z-improve confusion and qt-bot deployment false-confidence (unique to Claude).
- Codex: Centers on ambiguity risk ("did it skip or produce nothing?") — the silent-skip-as-false-signal risk.
- Gemini: "Hallucinated Wisdom" (low-quality candidates pollute KB) and context bloat risks (unique to Gemini).

**Winner: Claude (explicit justification required — Claude wins here).** Claude's risk list is the most complete and operationally specific for plan design. The /z-improve confusion risk (nudge copy must clearly distinguish harness retro from implementation retro) is directly relevant to any UX change. The qt-bot deployment false-confidence risk (fixing nudge without fixing deployment gives illusion of progress) is load-bearing for plan prioritization. Gemini's "Hallucinated Wisdom" risk is novel and should be absorbed into the synthesis, but Claude's list is more actionable as a whole.

### (4) Plan implications
- Claude: Fix deployment → fix env var → add terminal summary line → wire /z-debug → no new skill.
- Codex: Four-state taxonomy (not_applicable / skipped_broken_context / ran_empty / needs_user) as the unifying abstraction. Fix Z_HARNESS_PLAN_DIR propagation first. Structured telemetry.
- Gemini: New /z-postmortem skill with Sonnet/Opus model upgrade, visible heartbeat on skips, mandatory nudge to /z-improve on empty.

**Winner: Codex (explicit justification — Claude does not win here).** Codex's four-state taxonomy is the most actionable single idea in all three responses. It solves the "did it skip or produce nothing?" ambiguity with a concrete implementation pattern (four named states) that doesn't require a new skill, heavier models, or policy changes. The taxonomy also provides the correct basis for nudge policy: nudge only on `skipped_broken_context`, not on `not_applicable`. Claude's plan is a valid list but lacks the unifying abstraction. Gemini's /z-postmortem contradicts the cheap-by-default constraint.

### (5) What would change my mind
- Claude: Phase 9 reliably runs but returns zero candidates (then fix detection); qt-bot has INDEX.json deployed; 7 MEMORY.md entries are manual.
- Codex: Phase 9 reliably runs yet produces zero candidates; users reject high-quality candidates; deliberate product decision.
- Gemini: Native auto-memory is sufficient; AskUserQuestion crashes; signal rarity (~2% of runs worth remembering → zero is correct).

**Winner: Gemini.** Gemini's "signal rarity" argument (2% recurrence-worthy → zero is correct behavior) is the boldest and most distinct challenge to the entire intervention premise. It's the one falsification that would most change the direction: if the base rate of memorable insights is truly very low, then no UX change is worth the complexity. Claude picks Gemini over itself: Claude's evidence clauses are more operational but less directionally distinct. Codex's are valid but overlap substantially with Claude.

---

## Orchestrator recommendation

**Adopt the Codex framing** ("reachability and observability failure, not a policy question"), absorbing Gemini's Haiku-trap hypothesis into the core hypothesis and Claude's risk list (particularly the /z-improve confusion risk and qt-bot deployment false-confidence risk).

The critical insight is: before deciding auto-run vs nudge, the pipeline must demonstrably reach execution. Fix env var propagation, instrument the four skip states, make Phase 9 visible in the finalize summary, and wire /z-debug's stated contract. Only after those fixes can you tell whether nudging is needed or whether the candidates the Haiku agent produces are high enough quality to justify the UX intervention.

---

## User choice

**Picked: Codex framing.**

Reproduced verbatim:

> This is not an auto-memory question yet. It is a reachability and
> observability failure disguised as a memory-authoring policy question.
>
> The pipeline has a write boundary, a reviewer, candidate limits, and
> approval UX. What it lacks is proof that the review path actually runs
> in the contexts where learning should happen. A silent Phase 9 after
> `/z-implement-all` is not a learning loop; it is an invisible best-effort
> epilogue.

Plan implications carried forward:
- Four-state Phase 9 terminal taxonomy (`not_applicable` /
  `skipped_broken_context` / `ran_empty` / `needs_user`) emitted as
  `memory_review_terminal` events.
- Audit `Z_HARNESS_PLAN_DIR` / `TAGS.txt` / context propagation across
  Phase 9 dispatch boundaries.
- Verify qt-bot remote has `docs/llm/` initialized.
- Reconcile `/z-debug` and `/z-improve` lifecycle claims about
  `/z-suggest-memory` with actual code.
- Absorb Gemini's Haiku-trap as a follow-on experiment (only after
  observability fix yields data).
- Absorb Claude's `/z-improve` vs Phase 9 conflation risk into nudge-copy
  design constraints.

No new `/z-postmortem` skill yet. Don't redesign before measuring.
