1. Framing

This should be a shared pre-dispatch router with command-specific adapters, not a new standalone z-command and not logic pasted into every skill.

The reusable layer owns cheap signal extraction, LIGHT/MEDIUM/HEAVY classification, route artifacts, child-run manifests, telemetry, loop prevention, and fanout limits. Each command owns what split axes are valid and what synthesis means.

The key distinction: this router does not ask "which z-command should this become?" It asks "what execution topology should this requested command use before expensive work starts?"

2. Core hypothesis

The real primitive is:

`intent -> command profile -> terrain sketch -> candidate axes -> chunk contract -> synthesis contract`

Natural-axis discovery should be constrained and evidence-seeking, not open-ended invention. Use cheap signals first: explicit noun phrases, docs concepts, candidate files, changed files, prior artifacts, command defaults, and known phase thresholds. Use an advisory router only to rank or arbitrate candidate axes.

Per command:

- `/z-audit`: axes by component, risk domain, invariant, workflow, or existing audit dimension.
- `/z-debug`: axes by hypothesis, failure mode, suspected subsystem, or repro path.
- `/z-plan`: axes by feature cluster, architecture boundary, migration phase, data/control boundary.
- `/z-review-all`: axes by task range, changed module, risk tier, or ownership boundary.

Router output should be structured: route class, confidence, reason codes, chosen axis, rejected axes, chunk specs, shared surfaces, child routing mode, and synthesis contract.

3. Risks

The biggest risk is fake decomposition. Broad-looking topics can still be one tightly coupled state machine, schema change, or public contract. Splitting early can hide the central invariant.

The second risk is artifact incoherence. Multiple locally valid sub-runs can produce outputs that cannot become one canonical audit, debug conclusion, plan, or review result.

The third risk is recursive orchestration sprawl. Child runs should default to `router_mode=child`: they may narrow, but they cannot HEAVY fan out again without explicit parent permission.

The fourth risk is lossy synthesis. The main thread must preserve contradictions and shared-surface warnings, not smooth everything into a generic summary.

The fifth risk is cost inversion. If axis discovery requires real exploration, the router becomes `/z-research` or `/z-plan` Phase 1 in disguise.

4. Plan Implications

Build `scope-router` as a scripts/lib package plus small command adapters.

Likely pieces:

- `classify_scope(command, topic, context) -> LIGHT | MEDIUM | HEAVY`
- `discover_axes(command, topic, context) -> ranked axis candidates`
- `build_chunks(axis, command, topic, context) -> bounded child specs`
- `build_synthesis_contract(command, axis) -> merge schema`
- `ROUTE.md` or `SCOPE.md` written before command execution
- parent manifest for HEAVY runs recording child run ids, chunk scopes, input hashes, route chain, and synthesis status

Synthesis must be command-specific:

- Audit synthesis dedupes findings, normalizes severity, preserves dissent, and calls out cross-chunk systemic risks.
- Debug synthesis compares hypotheses by evidence, maintains shared repro facts, and chooses the next isolation or fix path.
- Plan synthesis reconciles shared files/contracts and emits either one coherent SPEC/PLAN/TASKS or explicit split artifacts.
- Review synthesis collapses findings into blocker/non-blocker sets and identifies systemic regressions across chunks.

This differs from current escalation because current chains mostly discover "too big/uncertain/wrong command" after partial work. This router decides the execution shape before committing the run, while retaining mid-flight checks as correction points.

5. What Would Change My Mind

I would narrow or reject the universal router if the only truly shared pieces are logging and manifests, while every useful axis and synthesis rule is command-local.

I would also back away if pre-flight axis discovery needs enough exploration that it duplicates existing command phases.

The strongest evidence for the design would be successful pilots where HEAVY improves outcomes: `/z-audit trader` finds sharper non-duplicated issues, `/z-debug <broad bug>` isolates faster without losing repro discipline, and `/z-plan <large feature>` produces a cleaner task graph than today's `/z-plan` followed by `/z-plan-split`.
