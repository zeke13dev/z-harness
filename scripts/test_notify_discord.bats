#!/usr/bin/env bats
# test_notify_discord.bats — Smoke tests for notify-discord.sh
#
# Requires: bats-core (https://github.com/bats-core/bats-core)
# Run: bats scripts/test_notify_discord.bats
#
# Tests that the script is syntactically valid and handles its
# required arguments without crashing.  Does NOT send real webhooks.

setup() {
    SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    NOTIFY_SCRIPT="$SCRIPT_DIR/notify-discord.sh"
}

@test "notify-discord.sh exists and is executable" {
    [ -f "$NOTIFY_SCRIPT" ]
    [ -x "$NOTIFY_SCRIPT" ]
}

@test "notify-discord.sh runs without crashing (no webhook configured)" {
    # When no Discord webhook URL is configured, the script should
    # exit 0 silently (Discord disabled is not an error).
    run "$NOTIFY_SCRIPT" "test title" "test body"
    [ "$status" -eq 0 ]
}

@test "notify-discord.sh handles missing body argument" {
    run "$NOTIFY_SCRIPT" "title only"
    [ "$status" -eq 0 ]
}

@test "notify-discord.sh handles empty arguments" {
    run "$NOTIFY_SCRIPT" "" ""
    [ "$status" -eq 0 ]
}

@test "notify-discord.sh has correct shebang" {
    head -1 "$NOTIFY_SCRIPT" | grep -q '^#!/usr/bin/env bash'
}
