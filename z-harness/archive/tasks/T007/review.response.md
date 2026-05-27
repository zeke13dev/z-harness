No blockers or majors found.

Verified:
- Both files add the config setup snippet (export Z_HARNESS_RUN + eval export-env)
- All 3 PushNotification calls per file are guarded with should-notify --event checks
- Event mapping is correct: Phase 2.5=approval, Phase 5=approval, Phase 9=phase_end
- No Z_HARNESS_NOTIFY references remain
- Doc-fetcher logic unchanged
- Files symmetric for the migrated changes
