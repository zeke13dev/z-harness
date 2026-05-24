### (1) Framing
The fundamental problem isn't that AI agents write incorrect code; it's that they write *AI-flavored* code. They are prone to hyper-defensive error handling, tautological "1+1=2" tests, over-commenting the obvious, and a gradual drift away from the project's idiomatic terseness. The existing `/z-audit` command with `cleanliness` or `design` dimensions is too generic and academic—it operates like a static analysis tool looking for standard code smells. An MR-style reviewer must be an aggressively opinionated, adversarial persona (the "Senior Nitpicker") explicitly tuned to hunt down and eradicate AI-generated cruft, forcing the codebase back to a human-like, idiomatic baseline.

### (2) Core hypothesis
The MR-style reviewer should **not** be an add-on to `/z-audit`. It must be an integrated, unavoidable gatekeeper fused directly into `/z-review-all` as a mandatory, cross-LLM "Vibe Check" phase. 

Instead of generating a generic audit report, it generates an aggressive "PR Review Comments" list targeting specific line numbers, focusing exclusively on AI failure modes (redundancy, bloat, over-defensiveness) against an interactive `STYLE.md`. To handle the init flow, a new `/z-init-style` command will use Gemini to interview the user, analyze the existing codebase for implicit conventions, and draft a `STYLE.md` that Claude and Codex will ruthlessly enforce. 

### (3) Risks
- **Subjective Blocking:** "Style" and "AI cruft" are highly subjective. An overly aggressive reviewer might trigger infinite loops of trivial refactoring (e.g., arguing over comment phrasing) that stall the delivery of functional code.
- **Workflow Bloat:** Injecting a new, intensive review phase into `/z-review-all` adds significant latency and token cost to an already heavy operation.
- **User Confusion:** Users may struggle to understand the boundary between `/z-audit --dimension=cleanliness` (which finds architectural/design flaws) and the MR reviewer (which targets style and AI anti-patterns), leading to misuse of the tools.

### (4) Plan implications
- Create a `/z-init-style` command: A standalone interactive flow where an agent analyzes the repo, interviews the user, and drafts a robust `STYLE.md` with explicit anti-patterns.
- Build `mr-reviewer.md`: A new agent prompt entirely distinct from `auditor.md`. It assumes correctness and is hyper-focused on code brevity, idiomatic patterns, and eliminating defensive AI boilerplate.
- Modify `/z-review-all`: Inject the `mr-reviewer.md` agent as a parallel pass alongside the correctness checks. Have it output direct action items rather than a generalized report.
- Redefine `/z-audit`: Strictly scope the `cleanliness` and `design` dimensions of the auditor to structural patterns (e.g., SOLID principles, dependency injection) to prevent overlap with the MR reviewer's stylistic focus.

### (5) What would change my mind
If empirical testing demonstrates that simply feeding a detailed `STYLE.md` to the existing `auditor.md` (using `/z-audit --dimension=cleanliness --rubric=STYLE.md`) effectively eliminates AI code smells without requiring a specialized prompt or persona, then the overhead of creating and maintaining a distinct MR reviewer workflow would be unjustified.
