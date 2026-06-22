<!-- Host sets RB_HALT_REASON, BASE, RUN before include -->
```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/PLAN.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS="$BASE/SPEC.md"
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
NEXT_JSON="$(mktemp -t z-rb-next.XXXXXX.json)"
python3 -c 'import json; print(json.dumps({"label":"Resolve halt and re-run /z-execute","command":"/z-execute"}))' > "$NEXT_JSON"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON"
rm -f "$NEXT_JSON"
```
<!-- include: _fragments/run-brief-finalize.md -->
