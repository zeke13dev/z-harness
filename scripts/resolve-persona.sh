#!/usr/bin/env bash
# resolve-persona.sh — thin wrapper around resolve-persona.py
exec python3 "$(dirname "$0")/resolve-persona.py" "$@"
