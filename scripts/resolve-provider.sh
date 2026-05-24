#!/usr/bin/env bash
# resolve-provider.sh <role>
# Thin wrapper — all logic lives in resolve-provider.py.
exec python3 "$(dirname "$0")/resolve-provider.py" "$@"
