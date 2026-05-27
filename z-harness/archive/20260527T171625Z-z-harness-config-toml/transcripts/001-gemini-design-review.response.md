### D5 — config.py public API surface
**(a) Why tentative is wrong:** `export-env` couples the Python config resolver to shell escaping semantics and risks shell injection if a value contains arbitrary characters (e.g., spaces in paths).
**(b) Recommendation:** Align with the `resolve-provider.py` precedent: output a single parsed JSON object and let the caller extract specific keys safely using `jq`, or stick strictly to `get <key>` returning a raw string. 
**(c) What would change my mind:** If the project already has a strict, established convention of `eval`-ing dynamically generated shell variables for configuration and possesses robust escaping helpers.

### D7 — docs.always_apply semantics
**(a) Why tentative is wrong:** The `"smart"` option relies on an implicit, undocumented heuristic for "light" vs. "heavy" flows, making it an opaque footgun if command behaviors or definitions drift over time.
**(b) Recommendation:** Use a per-command override map (e.g., `docs.always_apply = { "z-plan-light": false, "z-plan": true }`) to make the explicit behavior visible and deterministic for each command.
**(c) What would change my mind:** If the definition of "smart" is strictly centralized, logically rigorous (e.g., based on git diff size rather than command names), and the rules are shared explicitly with the commands.

### D9 — notify.level API and gate
**(a) Why tentative is wrong:** Relying on exit codes (`should-notify`) for boolean logic inside shell pipelines is brittle, and it forces `config.py` to maintain a hidden registry of valid event types that shell scripts must guess.
**(b) Recommendation:** Expose the raw `notify.level` string directly via a standard `get notify.level` call, and let the shell scripts perform explicit string comparisons (e.g., `[ "$LEVEL" == "all" ]`).
**(c) What would change my mind:** If notification routing rules become highly complex (e.g., filtering based on tags, urgency, or channel mappings) making shell-side evaluation overly cumbersome or repetitive.
