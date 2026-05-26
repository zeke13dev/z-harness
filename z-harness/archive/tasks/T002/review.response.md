   465	        components.append({"path": rel, "method": "manual"})
   466	
   467	# Re-filter unclaimed: remove any path that was explicitly added via --component
   468	unclaimed = [u for u in unclaimed if u not in manual_paths]
   469	
   470	# Compute slugs

codex
- **Blocker** — [commands/z-uplift.md](/Users/zeke/dev/z-harness/commands/z-uplift.md:556): collision resolution is still incomplete for groups larger than two, or when a chosen/custom slug creates a new collision, because the apply pass runs once and never re-checks before `COMPONENTS.md` is written. Fix by looping `find_collisions()` after every applied choice until empty, handling all members in a collision group, and failing before Step 3 if any duplicate slug remains.

- **Major** — [commands/z-uplift.md](/Users/zeke/dev/z-harness/commands/z-uplift.md:559): missing `USER_COLLISION_CHOICES` entries silently default to choice `"1"`, so a collision can be “resolved” without the required AskUser gate. Fix by requiring an explicit choice for every colliding slug and exiting with an error if any choice is absent.

- **Major** — [commands/z-uplift.md](/Users/zeke/dev/z-harness/commands/z-uplift.md:566): custom collision slugs are accepted without validation or uniqueness checks, allowing invalid path-like slugs or fresh duplicates to reach `COMPONENTS.md` and later MANIFEST paths. Fix by validating custom slugs against the same kebab-case slug regex and re-running duplicate detection before writing artifacts.
tokens used
126,825
