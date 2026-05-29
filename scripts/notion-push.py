#!/usr/bin/env python3
"""
scripts/notion-push.py — one-way push of a followup entry to Notion.

Exit codes:
  0  success
  4  retry exhausted (caller stamps notion_sync_pending)
       stdout JSON always includes `error` field on exit 4.
       The *caller* (sink-add.sh / sink-status-set.sh / followup-reconcile-notion.sh)
       is responsible for logging the `followup_notion_sync_failure` structured event
       from this script's exit-4 stdout output.
  5  idempotency mismatch (remote page z_harness_entry_id doesn't match entry id)
  6  auth missing (no token found)
  7  config missing (no database-id found)

Output: JSON to stdout — {action, remote_id?, attempts, error?}
Diagnostics: stderr only.
"""

from __future__ import annotations

import argparse
import email.utils
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
BACKOFF_SCHEDULE = [1, 4, 16]  # seconds before each retry (attempts 2, 3, 4 — 3 total)


# ---------------------------------------------------------------------------
# Auth / config resolution
# ---------------------------------------------------------------------------

def _resolve_token(secrets_path: str | None) -> str | None:
    """Read token from env override first, then secrets.toml.

    secrets.toml must be created by the user with mode 0600
    (e.g. ``install -m 0600 /dev/null ~/.z-harness/secrets.toml``).
    Callers and wrappers of this script MUST NOT run under ``set -x`` —
    doing so would leak the token value into logs or terminal output.
    """
    env_val = os.environ.get("Z_HARNESS_NOTION_TOKEN", "").strip()
    if env_val:
        return env_val

    # Resolve secrets TOML path
    if secrets_path:
        toml_path = Path(secrets_path).expanduser()
    else:
        toml_path = Path("~/.z-harness/secrets.toml").expanduser()

    if not toml_path.exists():
        return None

    try:
        import tomllib  # Python ≥ 3.11
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            print(
                "notion-push: tomllib/tomli not available; cannot parse secrets.toml",
                file=sys.stderr,
            )
            return None

    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        return data.get("notion", {}).get("token", None)
    except (OSError, ValueError) as exc:
        # OSError: file read failure; ValueError: covers tomllib.TOMLDecodeError (subclass)
        print(f"notion-push: failed to parse {toml_path}: {exc}", file=sys.stderr)
        return None


def _resolve_database_id(config_database_id: str, cli_database_id: str | None) -> str | None:
    """CLI flag wins over config value; both may be empty."""
    if cli_database_id and cli_database_id.strip():
        return cli_database_id.strip()
    if config_database_id and config_database_id.strip():
        return config_database_id.strip()
    return None


# ---------------------------------------------------------------------------
# Notion API helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _notion_get(url: str, token: str) -> dict:
    """
    GET a Notion page. Returns parsed JSON dict.
    Raises urllib.error.HTTPError on non-2xx.
    """
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _notion_post(url: str, token: str, body: dict) -> dict:
    """
    POST to Notion API. Returns parsed JSON dict.
    Raises urllib.error.HTTPError on non-2xx.
    """
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(token), method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _notion_patch(url: str, token: str, body: dict) -> dict:
    """
    PATCH a Notion page. Returns parsed JSON dict.
    Raises urllib.error.HTTPError on non-2xx.
    """
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(token), method="PATCH")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_entry_id_from_page(page: dict) -> str | None:
    """Extract z_harness_entry_id rich_text value from a Notion page."""
    props = page.get("properties", {})
    prop = props.get("z_harness_entry_id", {})
    rich_text = prop.get("rich_text", [])
    if not rich_text:
        return None
    return rich_text[0].get("plain_text", None)


def _query_db_for_entry_id(
    database_id: str,
    entry_id: str,
    token: str,
) -> str | None:
    """
    Query the Notion database for an existing page whose `z_harness_entry_id`
    rich_text property exactly matches `entry_id`.

    Returns the Notion page ID if found, or None if not found or on error.

    This is used as a dedup guard when `notion_remote_id` is null but
    `notion_sync_pending` is true, to avoid creating duplicate Notion pages
    for the same followup entry.
    """
    url = f"{NOTION_API_BASE}/databases/{database_id}/query"
    body = {
        "filter": {
            "property": "z_harness_entry_id",
            "rich_text": {
                "equals": entry_id,
            },
        },
        "page_size": 1,
    }
    try:
        result = _notion_post(url, token, body)
    except urllib.error.HTTPError as exc:
        print(
            f"notion-push: dedup query failed (HTTP {exc.code}); proceeding with create",
            file=sys.stderr,
        )
        return None
    except urllib.error.URLError as exc:
        print(
            f"notion-push: dedup query failed ({exc.reason}); proceeding with create",
            file=sys.stderr,
        )
        return None

    results = result.get("results", [])
    if results:
        return results[0].get("id")
    return None


def _build_create_body(entry: dict, database_id: str) -> dict:
    """Build the Notion page create request body from a followup entry."""
    entry_id = entry.get("id", "")
    name = entry.get("name", "")
    status = entry.get("status", "open")
    priority = entry.get("priority", "P2")
    sink = entry.get("sink", "project")

    return {
        "parent": {"database_id": database_id},
        "properties": {
            "z_harness_entry_id": {
                "rich_text": [{"type": "text", "text": {"content": entry_id}}]
            },
            "Name": {
                "title": [{"type": "text", "text": {"content": name}}]
            },
            "Status": {
                "select": {"name": status}
            },
            "Priority": {
                "select": {"name": priority}
            },
            "Sink": {
                "select": {"name": sink}
            },
        },
    }


def _build_update_body(entry: dict) -> dict:
    """Build the Notion page update (PATCH) request body from a followup entry."""
    status = entry.get("status", "open")
    priority = entry.get("priority", "P2")

    return {
        "properties": {
            "Status": {
                "select": {"name": status}
            },
            "Priority": {
                "select": {"name": priority}
            },
        },
    }


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _parse_retry_after(exc: urllib.error.HTTPError) -> float | None:
    """
    Parse the Retry-After header from an HTTPError, if present.

    Handles two formats:
    - Integer seconds: "Retry-After: 30"
    - HTTP-date:       "Retry-After: Wed, 29 May 2026 12:00:00 GMT"

    Returns the delay in seconds (float), or None if the header is absent or
    cannot be parsed.
    """
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    raw = headers.get("Retry-After", "").strip()
    if not raw:
        return None
    # Try integer seconds first
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    # Try HTTP-date format
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        delay = dt.timestamp() - time.time()
        return max(0.0, delay)
    except (ValueError, TypeError, OverflowError):
        return None


def _call_with_retry(
    fn,
    *args,
    max_attempts: int = 3,
    sleep_fn=None,
    **kwargs,
) -> tuple[dict | None, int, str | None]:
    """
    Call fn(*args, **kwargs) up to max_attempts times.
    Returns (result_dict, attempts_used, error_str_or_None).
    Retries on HTTPError with retryable status codes.

    On 429 responses, honors the Retry-After header when present:
    uses max(retry_after_value, BACKOFF_SCHEDULE[attempt_idx]) as the delay.
    """
    if sleep_fn is None:
        sleep_fn = time.sleep

    last_error: str | None = None
    for attempt_idx in range(max_attempts):
        if attempt_idx > 0:
            delay = BACKOFF_SCHEDULE[attempt_idx - 1]
            sleep_fn(delay)

        try:
            result = fn(*args, **kwargs)
            return result, attempt_idx + 1, None
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"
            if exc.code not in _RETRYABLE_STATUS_CODES:
                # Non-retryable error; stop immediately
                return None, attempt_idx + 1, last_error
            # For 429, check Retry-After header; schedule extra sleep before next attempt
            if exc.code == 429:
                retry_after = _parse_retry_after(exc)
                if retry_after is not None and attempt_idx + 1 < max_attempts:
                    # Determine the base backoff for the next sleep slot
                    base_backoff = BACKOFF_SCHEDULE[attempt_idx] if attempt_idx < len(BACKOFF_SCHEDULE) else BACKOFF_SCHEDULE[-1]
                    extra = retry_after - base_backoff
                    if extra > 0:
                        # Sleep the extra portion now; _call_with_retry will sleep base_backoff at loop top
                        sleep_fn(extra)
            # Retryable — continue loop
            print(
                f"notion-push: attempt {attempt_idx + 1} failed ({last_error}); retrying…",
                file=sys.stderr,
            )
        except urllib.error.URLError as exc:
            last_error = f"URLError: {exc.reason}"
            print(
                f"notion-push: attempt {attempt_idx + 1} failed ({last_error}); retrying…",
                file=sys.stderr,
            )

    return None, max_attempts, last_error


# ---------------------------------------------------------------------------
# High-level push logic
# ---------------------------------------------------------------------------

def push_entry(
    entry: dict,
    token: str,
    database_id: str,
    sleep_fn=None,
    check_existing: bool = False,
) -> tuple[int, dict]:
    """
    Push one followup entry to Notion.

    Returns (exit_code, output_dict).
    Caller prints output_dict as JSON to stdout.

    When check_existing=True and notion_remote_id is null, queries the Notion
    database by z_harness_entry_id before creating to avoid duplicate pages
    (used by the reconciler when notion_sync_pending=true).
    """
    notion_remote_id: str | None = entry.get("notion_remote_id") or None
    entry_id: str = entry.get("id", "")

    if notion_remote_id:
        # UPDATE PATH: GET page first and verify idempotency key
        get_url = f"{NOTION_API_BASE}/pages/{notion_remote_id}"
        page, attempts, err = _call_with_retry(
            _notion_get, get_url, token, sleep_fn=sleep_fn
        )
        if page is None:
            return 4, {
                "action": "failed",
                "attempts": attempts,
                "error": f"GET failed after {attempts} attempt(s): {err}",
            }

        remote_entry_id = _extract_entry_id_from_page(page)
        if remote_entry_id != entry_id:
            _log_event_mismatch(entry_id, notion_remote_id, remote_entry_id)
            return 5, {
                "action": "failed",
                "attempts": attempts,
                "error": (
                    f"z_harness_entry_id mismatch: expected {entry_id!r}, "
                    f"got {remote_entry_id!r}"
                ),
            }

        # Idempotency verified — PATCH the page
        patch_url = f"{NOTION_API_BASE}/pages/{notion_remote_id}"
        body = _build_update_body(entry)
        result, patch_attempts, patch_err = _call_with_retry(
            _notion_patch, patch_url, token, body, sleep_fn=sleep_fn
        )
        total_attempts = attempts + patch_attempts
        if result is None:
            return 4, {
                "action": "failed",
                "attempts": total_attempts,
                "error": f"PATCH failed after {patch_attempts} attempt(s): {patch_err}",
            }

        return 0, {
            "action": "updated",
            "remote_id": notion_remote_id,
            "attempts": total_attempts,
        }

    else:
        # CREATE PATH (or dedup-detected update path)
        if check_existing and database_id:
            # Query DB first to avoid duplicate creates when notion_sync_pending=true
            existing_page_id = _query_db_for_entry_id(database_id, entry_id, token)
            if existing_page_id:
                # Page already exists — PATCH-update instead of POST-create
                patch_url = f"{NOTION_API_BASE}/pages/{existing_page_id}"
                body = _build_update_body(entry)
                result, patch_attempts, patch_err = _call_with_retry(
                    _notion_patch, patch_url, token, body, sleep_fn=sleep_fn
                )
                if result is None:
                    return 4, {
                        "action": "failed",
                        "attempts": patch_attempts,
                        "error": f"PATCH (dedup) failed after {patch_attempts} attempt(s): {patch_err}",
                    }
                return 0, {
                    "action": "updated",
                    "remote_id": existing_page_id,
                    "attempts": patch_attempts,
                }

        create_url = f"{NOTION_API_BASE}/pages"
        body = _build_create_body(entry, database_id)
        result, attempts, err = _call_with_retry(
            _notion_post, create_url, token, body, sleep_fn=sleep_fn
        )
        if result is None:
            return 4, {
                "action": "failed",
                "attempts": attempts,
                "error": f"POST failed after {attempts} attempt(s): {err}",
            }

        new_remote_id = result.get("id", "")
        return 0, {
            "action": "created",
            "remote_id": new_remote_id,
            "attempts": attempts,
        }


def _log_event_mismatch(entry_id: str, remote_id: str, found_id: str | None) -> None:
    """Log a followup_notion_remote_id_mismatch event to stderr (best-effort)."""
    print(
        f"notion-push: followup_notion_remote_id_mismatch "
        f"entry_id={entry_id!r} remote_page={remote_id!r} found_entry_id={found_id!r}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="notion-push.py",
        description="One-way push of a followup entry to Notion.",
    )
    p.add_argument(
        "--entry-json",
        required=True,
        help="Path to JSON file containing the followup entry, or '-' for stdin.",
    )
    p.add_argument(
        "--database-id",
        default=None,
        help="Notion database ID (overrides followup.notion_database_id config).",
    )
    p.add_argument(
        "--secrets-path",
        default=None,
        help="Path to secrets.toml (default: ~/.z-harness/secrets.toml).",
    )
    p.add_argument(
        "--config-database-id",
        default="",
        help="Value of followup.notion_database_id from config (passed by caller).",
    )
    p.add_argument(
        "--check-existing",
        action="store_true",
        default=False,
        help=(
            "Query the Notion database for an existing page with matching "
            "z_harness_entry_id before creating. Use this when notion_remote_id "
            "is null but notion_sync_pending is true (e.g. in the reconciler) "
            "to avoid creating duplicate Notion pages."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    # --- Read entry ---
    if args.entry_json == "-":
        try:
            entry = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            print(
                json.dumps({"action": "failed", "attempts": 0, "error": f"Invalid entry JSON: {exc}"}),
            )
            return 4
    else:
        path = Path(args.entry_json)
        if not path.exists():
            print(
                json.dumps({"action": "failed", "attempts": 0, "error": f"Entry file not found: {path}"}),
            )
            return 4
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(
                json.dumps({"action": "failed", "attempts": 0, "error": f"Invalid entry JSON: {exc}"}),
            )
            return 4

    # --- Resolve auth token ---
    token = _resolve_token(args.secrets_path)
    if not token:
        out = {"action": "failed", "attempts": 0, "error": "auth missing: no token found"}
        print(json.dumps(out))
        return 6

    # --- Resolve database id ---
    database_id = _resolve_database_id(args.config_database_id, args.database_id)
    # For create path, database_id is required; for update path it's not strictly needed
    notion_remote_id = entry.get("notion_remote_id") or None
    if not notion_remote_id and not database_id:
        out = {
            "action": "failed",
            "attempts": 0,
            "error": "config missing: no database-id found; pass --database-id or set followup.notion_database_id",
        }
        print(json.dumps(out))
        return 7

    # --- Push ---
    exit_code, output = push_entry(
        entry, token, database_id or "", check_existing=args.check_existing
    )

    print(json.dumps(output))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
