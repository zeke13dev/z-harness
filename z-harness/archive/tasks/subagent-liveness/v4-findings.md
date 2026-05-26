## Codex Review: subagent-liveness (v4)

### Blockers

1. **Location:** scripts/liveness.sh:161 (reporting loop)
   - Issue: match_key() now returns a 3-tuple (base, tid, discriminator), but the reporting loop still unpacks it as (base, tid), causing ValueError when reporting stuck agents instead of displaying them correctly.
   - Fix: Update the reporting loop at line 444 to unpack (base, tid, discriminator) correctly, or restructure the row construction to use the full key tuple.

2. **Location:** scripts/liveness.sh:114 plus agents/consultant-primary.md:41 / agents/consultant-secondary.md:41
   - Issue: Consultant consult_start events have no 'id' field, and match_key() doesn't include 'role' as a discriminator, so concurrent primary/secondary consults share the same key and one completed consult can erase the tracking of another hung consult.
   - Fix: Add 'role' (or role+mode) as a discriminator in match_key(), and ensure both consult_start and the closing consult event payloads include this discriminator so the pair can be matched correctly.
