"""
Auth validation helper for the Antigravity (agy) driver.

Checks for:
- CLI-tier auth: presence of ~/.gemini/oauth_creds.json (no content validation)
- SDK-tier auth: GEMINI_API_KEY env var set and non-empty

Does NOT perform OAuth, read token content, or make network calls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypedDict


class AuthStatus(TypedDict):
    cli_auth: bool
    sdk_auth: bool
    warnings: list[str]


_OAUTH_CREDS_PATH = Path("~/.gemini/oauth_creds.json")
_SDK_DEFERRED_WARNING = (
    "SDK tier is deferred to v2; GEMINI_API_KEY is not required for CLI-tier dispatch"
)
_CLI_AUTH_MISSING_WARNING = (
    "~/.gemini/oauth_creds.json not found; run `agy auth login` to authenticate"
)


def check_auth() -> AuthStatus:
    """
    Return auth status without performing OAuth, reading token content, or
    making any network calls.

    Returns a dict with:
      cli_auth  — True if ~/.gemini/oauth_creds.json exists
      sdk_auth  — True if GEMINI_API_KEY env var is set and non-empty
      warnings  — always includes SDK-deferred note; adds cli_auth warning when absent
    """
    creds_path = _OAUTH_CREDS_PATH.expanduser()
    cli_auth = creds_path.exists()

    sdk_key = os.environ.get("GEMINI_API_KEY", "")
    sdk_auth = bool(sdk_key)

    warnings: list[str] = [_SDK_DEFERRED_WARNING]
    if not cli_auth:
        warnings.append(_CLI_AUTH_MISSING_WARNING)

    return AuthStatus(cli_auth=cli_auth, sdk_auth=sdk_auth, warnings=warnings)


if __name__ == "__main__":
    import sys

    status = check_auth()
    print(json.dumps(status, indent=2))
    sys.exit(0)
