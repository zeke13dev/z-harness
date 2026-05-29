"""
tests/test_notion_push.py — pytest tests for scripts/notion-push.py

HTTP is mocked via unittest.mock.patch on urllib.request.urlopen.
All network calls are intercepted; no real HTTP requests are made.

Scenarios:
  - create-new path: entry without notion_remote_id → POST → 201, returns created + remote_id
  - update-existing (match): entry with notion_remote_id + matching z_harness_entry_id → GET + PATCH
  - update-existing (mismatch): GET returns page with wrong z_harness_entry_id → exit 5
  - retry-then-success on transient 429: first attempt returns 429, second succeeds
  - retry-exhausted on persistent 500: all 3 attempts return 500, exit 4
  - auth-missing: no token → exit 6
  - config-missing (no database_id on create): exit 7
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import urllib.error
import urllib.request
from http.client import HTTPMessage
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import importlib.util

import pytest

# Load notion-push.py via importlib since the filename contains a hyphen.
REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = REPO_ROOT / "scripts" / "notion-push.py"
_spec = importlib.util.spec_from_file_location("notion_push", _SCRIPT_PATH)
notion_push = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(notion_push)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENTRY_ID = "20260528T123456Z-fix-stale-readme-badge"
DATABASE_ID = "abc123-database-id"
REMOTE_PAGE_ID = "page-id-xyz"
TOKEN = "secret_testtoken"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    *,
    notion_remote_id: str | None = None,
    status: str = "open",
) -> dict:
    return {
        "id": ENTRY_ID,
        "schema_version": 1,
        "priority": "P2",
        "name": "Fix stale README badge",
        "status": status,
        "sink": "project",
        "notion_remote_id": notion_remote_id,
        "recommended_command": '/z-do "update README badge URL"',
    }


def _http_response(body: dict, status: int = 200) -> MagicMock:
    """Return a mock context-manager that yields a file-like HTTP response."""
    raw = json.dumps(body).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = raw
    resp.status = status
    # Support 'with urlopen(...) as resp:'
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(
    code: int,
    reason: str = "Server Error",
    retry_after: str | None = None,
) -> urllib.error.HTTPError:
    """Return an HTTPError with the given status code and optional Retry-After header."""
    msg = HTTPMessage()
    if retry_after is not None:
        msg["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        url="https://api.notion.com/v1/pages",
        code=code,
        msg=reason,
        hdrs=msg,
        fp=None,
    )


def _notion_page(entry_id: str = ENTRY_ID) -> dict:
    """Minimal Notion page JSON with z_harness_entry_id property."""
    return {
        "id": REMOTE_PAGE_ID,
        "object": "page",
        "properties": {
            "z_harness_entry_id": {
                "rich_text": [
                    {"plain_text": entry_id, "type": "text", "text": {"content": entry_id}}
                ]
            }
        },
    }


def _created_page() -> dict:
    """Notion page returned by POST /pages."""
    return {
        "id": REMOTE_PAGE_ID,
        "object": "page",
        "properties": {
            "z_harness_entry_id": {
                "rich_text": [
                    {"plain_text": ENTRY_ID, "type": "text", "text": {"content": ENTRY_ID}}
                ]
            }
        },
    }


# ---------------------------------------------------------------------------
# Tests: create-new path
# ---------------------------------------------------------------------------

class TestCreateNew:
    """entry has notion_remote_id=None → POST to /pages → returns action=created + remote_id."""

    def test_create_returns_created_action(self) -> None:
        entry = _make_entry()
        resp = _http_response(_created_page(), status=200)

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", return_value=resp):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append
            )

        assert exit_code == 0
        assert output["action"] == "created"
        assert output["remote_id"] == REMOTE_PAGE_ID
        assert output["attempts"] == 1
        assert "error" not in output

    def test_create_sends_z_harness_entry_id(self) -> None:
        """Verify the POST body includes z_harness_entry_id rich_text property."""
        entry = _make_entry()
        resp = _http_response(_created_page(), status=200)
        captured_bodies: list[bytes] = []

        original_urlopen = urllib.request.urlopen

        def capturing_urlopen(req, *a, **kw):
            if hasattr(req, "data") and req.data:
                captured_bodies.append(req.data)
            return resp

        with patch("urllib.request.urlopen", side_effect=capturing_urlopen):
            notion_push.push_entry(entry, TOKEN, DATABASE_ID)

        assert len(captured_bodies) == 1
        body = json.loads(captured_bodies[0].decode())
        prop = body["properties"]["z_harness_entry_id"]["rich_text"][0]["text"]["content"]
        assert prop == ENTRY_ID

    def test_create_no_sleep_on_first_success(self) -> None:
        entry = _make_entry()
        resp = _http_response(_created_page())
        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", return_value=resp):
            notion_push.push_entry(entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append)

        assert sleep_calls == []


# ---------------------------------------------------------------------------
# Tests: update-existing (match)
# ---------------------------------------------------------------------------

class TestUpdateMatch:
    """entry has notion_remote_id set; remote page z_harness_entry_id matches."""

    def test_update_match_returns_updated(self) -> None:
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID, status="verify")
        get_resp = _http_response(_notion_page(ENTRY_ID))
        patch_resp = _http_response({"id": REMOTE_PAGE_ID, "object": "page"})

        responses_iter = iter([get_resp, patch_resp])

        with patch("urllib.request.urlopen", side_effect=responses_iter):
            exit_code, output = notion_push.push_entry(entry, TOKEN, DATABASE_ID)

        assert exit_code == 0
        assert output["action"] == "updated"
        assert output["remote_id"] == REMOTE_PAGE_ID
        assert output["attempts"] == 2  # 1 GET + 1 PATCH

    def test_update_preserves_remote_id(self) -> None:
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        get_resp = _http_response(_notion_page(ENTRY_ID))
        patch_resp = _http_response({"id": REMOTE_PAGE_ID, "object": "page"})

        responses_iter = iter([get_resp, patch_resp])

        with patch("urllib.request.urlopen", side_effect=responses_iter):
            exit_code, output = notion_push.push_entry(entry, TOKEN, DATABASE_ID)

        assert output["remote_id"] == REMOTE_PAGE_ID


# ---------------------------------------------------------------------------
# Tests: update-existing (mismatch reject)
# ---------------------------------------------------------------------------

class TestUpdateMismatch:
    """Remote page z_harness_entry_id doesn't match → exit 5, action=failed."""

    def test_mismatch_exits_5(self) -> None:
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        # Remote page has a *different* entry id
        get_resp = _http_response(_notion_page("some-other-entry-id"))

        with patch("urllib.request.urlopen", return_value=get_resp):
            exit_code, output = notion_push.push_entry(entry, TOKEN, DATABASE_ID)

        assert exit_code == 5
        assert output["action"] == "failed"
        assert "mismatch" in output["error"].lower()

    def test_mismatch_does_not_patch(self) -> None:
        """On mismatch, no PATCH request should be issued."""
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        get_resp = _http_response(_notion_page("different-entry-id"))

        call_count = 0

        def counting_urlopen(req, *a, **kw):
            nonlocal call_count
            call_count += 1
            return get_resp

        with patch("urllib.request.urlopen", side_effect=counting_urlopen):
            notion_push.push_entry(entry, TOKEN, DATABASE_ID)

        # Only the GET should have been called, not PATCH
        assert call_count == 1

    def test_mismatch_logs_to_stderr(self, capsys) -> None:
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        get_resp = _http_response(_notion_page("wrong-entry-id"))

        with patch("urllib.request.urlopen", return_value=get_resp):
            notion_push.push_entry(entry, TOKEN, DATABASE_ID)

        captured = capsys.readouterr()
        assert "mismatch" in captured.err.lower()


# ---------------------------------------------------------------------------
# Tests: retry-then-success on transient 429
# ---------------------------------------------------------------------------

class TestRetryThenSuccess:
    """First attempt returns 429; second attempt succeeds."""

    def test_429_retry_then_success(self) -> None:
        entry = _make_entry()
        success_resp = _http_response(_created_page())

        call_count = 0

        def side_effect(req, *a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _http_error(429, "Too Many Requests")
            return success_resp

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", side_effect=side_effect):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append
            )

        assert exit_code == 0
        assert output["action"] == "created"
        assert output["attempts"] == 2
        # Should have slept once (BACKOFF_SCHEDULE[0] = 1s)
        assert sleep_calls == [1]

    def test_500_retry_twice_then_success(self) -> None:
        entry = _make_entry()
        success_resp = _http_response(_created_page())

        call_count = 0

        def side_effect(req, *a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise _http_error(500, "Internal Server Error")
            return success_resp

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", side_effect=side_effect):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append
            )

        assert exit_code == 0
        assert output["attempts"] == 3
        assert sleep_calls == [1, 4]  # backoff schedule positions 0 and 1


# ---------------------------------------------------------------------------
# Tests: retry exhausted on persistent 500
# ---------------------------------------------------------------------------

class TestRetryExhausted:
    """All 3 attempts return 500 → exit 4, action=failed."""

    def test_persistent_500_exits_4(self) -> None:
        entry = _make_entry()
        sleep_calls: list[float] = []

        with patch(
            "urllib.request.urlopen",
            side_effect=_http_error(500, "Internal Server Error"),
        ):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append
            )

        assert exit_code == 4
        assert output["action"] == "failed"
        assert output["attempts"] == 3
        assert "error" in output

    def test_persistent_500_sleep_schedule(self) -> None:
        """Verify backoff delays: 1s before attempt 2, 4s before attempt 3."""
        entry = _make_entry()
        sleep_calls: list[float] = []

        with patch(
            "urllib.request.urlopen",
            side_effect=_http_error(500, "Internal Server Error"),
        ):
            notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append
            )

        assert sleep_calls == [1, 4]

    def test_non_retryable_error_stops_immediately(self) -> None:
        """A 404 is non-retryable and should stop after 1 attempt."""
        entry = _make_entry()
        sleep_calls: list[float] = []

        with patch(
            "urllib.request.urlopen",
            side_effect=_http_error(404, "Not Found"),
        ):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append
            )

        # Non-retryable: only 1 attempt, no sleep
        assert output["attempts"] == 1
        assert sleep_calls == []
        assert exit_code == 4


# ---------------------------------------------------------------------------
# Tests: auth-missing
# ---------------------------------------------------------------------------

class TestAuthMissing:
    """No token → exit 6."""

    def test_no_env_no_file_exits_6(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("Z_HARNESS_NOTION_TOKEN", raising=False)
        entry = _make_entry()
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps(entry))

        result = notion_push.main([
            "--entry-json", str(entry_file),
            "--database-id", DATABASE_ID,
            "--secrets-path", str(tmp_path / "nonexistent-secrets.toml"),
        ])

        assert result == 6

    def test_env_token_bypasses_file(self, tmp_path, monkeypatch) -> None:
        """Z_HARNESS_NOTION_TOKEN env var provides the token even if secrets.toml absent."""
        monkeypatch.setenv("Z_HARNESS_NOTION_TOKEN", TOKEN)
        entry = _make_entry()
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps(entry))

        resp = _http_response(_created_page())
        with patch("urllib.request.urlopen", return_value=resp):
            result = notion_push.main([
                "--entry-json", str(entry_file),
                "--database-id", DATABASE_ID,
                "--secrets-path", str(tmp_path / "nonexistent.toml"),
            ])

        assert result == 0

    def test_token_from_secrets_toml(self, tmp_path, monkeypatch) -> None:
        """Token read from secrets.toml [notion].token when env is absent."""
        monkeypatch.delenv("Z_HARNESS_NOTION_TOKEN", raising=False)
        secrets = tmp_path / "secrets.toml"
        secrets.write_text(f'[notion]\ntoken = "{TOKEN}"\n')

        entry = _make_entry()
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps(entry))

        resp = _http_response(_created_page())
        with patch("urllib.request.urlopen", return_value=resp):
            result = notion_push.main([
                "--entry-json", str(entry_file),
                "--database-id", DATABASE_ID,
                "--secrets-path", str(secrets),
            ])

        assert result == 0


# ---------------------------------------------------------------------------
# Tests: config-missing (no database_id on create)
# ---------------------------------------------------------------------------

class TestConfigMissing:
    """No database_id when entry has no notion_remote_id → exit 7."""

    def test_missing_database_id_exits_7(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("Z_HARNESS_NOTION_TOKEN", TOKEN)
        entry = _make_entry()
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps(entry))

        result = notion_push.main([
            "--entry-json", str(entry_file),
            # No --database-id, no --config-database-id
        ])

        assert result == 7

    def test_database_id_via_flag_accepted(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("Z_HARNESS_NOTION_TOKEN", TOKEN)
        entry = _make_entry()
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps(entry))

        resp = _http_response(_created_page())
        with patch("urllib.request.urlopen", return_value=resp):
            result = notion_push.main([
                "--entry-json", str(entry_file),
                "--database-id", DATABASE_ID,
            ])

        assert result == 0

    def test_database_id_via_config_accepted(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("Z_HARNESS_NOTION_TOKEN", TOKEN)
        entry = _make_entry()
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps(entry))

        resp = _http_response(_created_page())
        with patch("urllib.request.urlopen", return_value=resp):
            result = notion_push.main([
                "--entry-json", str(entry_file),
                "--config-database-id", DATABASE_ID,
            ])

        assert result == 0


# ---------------------------------------------------------------------------
# Tests: stdout JSON structure invariant
# ---------------------------------------------------------------------------

class TestStdoutJson:
    """Output to stdout must always be valid JSON with the required fields."""

    def test_create_stdout_is_valid_json(self, tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.setenv("Z_HARNESS_NOTION_TOKEN", TOKEN)
        entry = _make_entry()
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps(entry))

        resp = _http_response(_created_page())
        with patch("urllib.request.urlopen", return_value=resp):
            notion_push.main([
                "--entry-json", str(entry_file),
                "--database-id", DATABASE_ID,
            ])

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "action" in output
        assert "attempts" in output
        assert output["action"] in {"created", "updated", "failed"}

    def test_failure_stdout_is_valid_json(self, tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.setenv("Z_HARNESS_NOTION_TOKEN", TOKEN)
        entry = _make_entry()
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps(entry))

        with patch(
            "urllib.request.urlopen",
            side_effect=_http_error(500, "Internal Server Error"),
        ):
            notion_push.main([
                "--entry-json", str(entry_file),
                "--database-id", DATABASE_ID,
            ])

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["action"] == "failed"
        assert "error" in output


# ---------------------------------------------------------------------------
# Tests: Retry-After header honored on 429
# ---------------------------------------------------------------------------

class TestRetryAfterHeader:
    """429 with Retry-After header: total sleep must be >= Retry-After value."""

    def test_retry_after_30_causes_extra_sleep(self) -> None:
        """
        Invariant: when a 429 includes Retry-After: 30, the total sleep before
        the next attempt must be >= 30 seconds.

        Without honoring Retry-After, the code would only sleep BACKOFF_SCHEDULE[0]=1.
        This test fails if Retry-After is ignored.
        """
        entry = _make_entry()
        success_resp = _http_response(_created_page())

        call_count = 0

        def side_effect(req, *a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _http_error(429, "Too Many Requests", retry_after="30")
            return success_resp

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", side_effect=side_effect):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append
            )

        assert exit_code == 0
        assert output["action"] == "created"
        # Total sleep must be >= 30; the implementation splits it across two calls
        # (extra portion first, then base backoff at loop top), but sum must be >= 30.
        assert sum(sleep_calls) >= 30, (
            f"Expected total sleep >= 30s to honor Retry-After, got {sum(sleep_calls)}s. "
            f"Individual sleeps: {sleep_calls}"
        )

    def test_retry_after_less_than_backoff_uses_backoff(self) -> None:
        """
        When Retry-After < BACKOFF_SCHEDULE[0], no extra sleep is added;
        the normal backoff schedule applies unchanged.
        """
        entry = _make_entry()
        success_resp = _http_response(_created_page())

        call_count = 0

        def side_effect(req, *a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Retry-After: 0 — less than BACKOFF_SCHEDULE[0] = 1
                raise _http_error(429, "Too Many Requests", retry_after="0")
            return success_resp

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", side_effect=side_effect):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append
            )

        assert exit_code == 0
        # Only the base backoff of 1s — no extra sleep added
        assert sleep_calls == [1], (
            f"Expected only base backoff [1], got {sleep_calls}"
        )

    def test_no_retry_after_header_unaffected(self) -> None:
        """
        Regression guard: 429 without Retry-After uses normal backoff (1s).
        """
        entry = _make_entry()
        success_resp = _http_response(_created_page())

        call_count = 0

        def side_effect(req, *a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _http_error(429, "Too Many Requests")  # no Retry-After
            return success_resp

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", side_effect=side_effect):
            notion_push.push_entry(entry, TOKEN, DATABASE_ID, sleep_fn=sleep_calls.append)

        assert sleep_calls == [1]

    def test_parse_retry_after_integer(self) -> None:
        """_parse_retry_after returns float seconds from integer string."""
        exc = _http_error(429, "Too Many Requests", retry_after="45")
        result = notion_push._parse_retry_after(exc)
        assert result == 45.0

    def test_parse_retry_after_missing_returns_none(self) -> None:
        """_parse_retry_after returns None when header absent."""
        exc = _http_error(429, "Too Many Requests")
        result = notion_push._parse_retry_after(exc)
        assert result is None

    def test_parse_retry_after_zero_returns_zero(self) -> None:
        """_parse_retry_after returns 0.0 for Retry-After: 0."""
        exc = _http_error(429, "Too Many Requests", retry_after="0")
        result = notion_push._parse_retry_after(exc)
        assert result == 0.0


# ---------------------------------------------------------------------------
# Tests: dedup query via --check-existing
# ---------------------------------------------------------------------------

def _notion_db_query_response(page_id: str | None) -> dict:
    """Minimal Notion database query response."""
    if page_id is None:
        return {"object": "list", "results": [], "has_more": False}
    return {
        "object": "list",
        "results": [
            {
                "id": page_id,
                "object": "page",
                "properties": {
                    "z_harness_entry_id": {
                        "rich_text": [
                            {
                                "plain_text": ENTRY_ID,
                                "type": "text",
                                "text": {"content": ENTRY_ID},
                            }
                        ]
                    }
                },
            }
        ],
        "has_more": False,
    }


class TestDedupQuery:
    """check_existing=True: query DB before creating to avoid duplicate pages."""

    def test_check_existing_found_patches_instead_of_post(self) -> None:
        """
        Invariant: when check_existing=True and DB query returns a matching page,
        the script PATCH-updates (not POST-creates) the found page.

        Failure class: duplicate Notion page creation for the same entry.
        """
        entry = _make_entry()  # notion_remote_id=None
        query_resp = _http_response(_notion_db_query_response(REMOTE_PAGE_ID))
        patch_resp = _http_response({"id": REMOTE_PAGE_ID, "object": "page"})

        responses_iter = iter([query_resp, patch_resp])
        methods_seen: list[str] = []

        def capturing_urlopen(req, *a, **kw):
            methods_seen.append(getattr(req, "method", "?"))
            return next(responses_iter)

        with patch("urllib.request.urlopen", side_effect=capturing_urlopen):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, check_existing=True
            )

        assert exit_code == 0
        assert output["action"] == "updated"
        assert output["remote_id"] == REMOTE_PAGE_ID
        # Must have used POST (DB query) then PATCH (update), never POST to /pages
        assert "POST" in methods_seen
        assert "PATCH" in methods_seen
        # Verify no second POST to /pages was issued (which would be a dup create)
        assert methods_seen.count("POST") == 1, (
            f"Expected exactly 1 POST (DB query), got {methods_seen.count('POST')}. "
            f"All methods: {methods_seen}"
        )

    def test_check_existing_not_found_creates_normally(self) -> None:
        """When check_existing=True but no matching page found, proceed with POST create."""
        entry = _make_entry()
        query_resp = _http_response(_notion_db_query_response(None))  # empty results
        create_resp = _http_response(_created_page())

        responses_iter = iter([query_resp, create_resp])

        with patch("urllib.request.urlopen", side_effect=lambda req, *a, **kw: next(responses_iter)):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, check_existing=True
            )

        assert exit_code == 0
        assert output["action"] == "created"
        assert output["remote_id"] == REMOTE_PAGE_ID

    def test_check_existing_false_skips_query(self) -> None:
        """When check_existing=False (default), no DB query is issued; goes straight to POST."""
        entry = _make_entry()
        create_resp = _http_response(_created_page())
        call_count = 0

        def side_effect(req, *a, **kw):
            nonlocal call_count
            call_count += 1
            return create_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            exit_code, output = notion_push.push_entry(
                entry, TOKEN, DATABASE_ID, check_existing=False
            )

        assert exit_code == 0
        # Only 1 call (POST create), no DB query
        assert call_count == 1

    def test_check_existing_cli_flag(self, tmp_path, monkeypatch) -> None:
        """--check-existing CLI flag is accepted and triggers DB query."""
        monkeypatch.setenv("Z_HARNESS_NOTION_TOKEN", TOKEN)
        entry = _make_entry()
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps(entry))

        # DB query returns empty → proceeds to create
        query_resp = _http_response(_notion_db_query_response(None))
        create_resp = _http_response(_created_page())
        responses_iter = iter([query_resp, create_resp])

        with patch("urllib.request.urlopen", side_effect=lambda req, *a, **kw: next(responses_iter)):
            result = notion_push.main([
                "--entry-json", str(entry_file),
                "--database-id", DATABASE_ID,
                "--check-existing",
            ])

        assert result == 0


# ---------------------------------------------------------------------------
# Tests: exit-4 output always includes error field
# ---------------------------------------------------------------------------

class TestExit4ErrorField:
    """On exit 4, stdout JSON must include an 'error' field (caller uses it for logging)."""

    def test_exit4_has_error_field(self) -> None:
        """
        Invariant: any exit-4 result dict must contain an 'error' key.

        Failure class: caller cannot log followup_notion_sync_failure without
        the error message from the script's stdout.
        """
        entry = _make_entry()

        with patch(
            "urllib.request.urlopen",
            side_effect=_http_error(500, "Internal Server Error"),
        ):
            exit_code, output = notion_push.push_entry(entry, TOKEN, DATABASE_ID)

        assert exit_code == 4
        assert "error" in output, (
            "exit-4 output must contain 'error' field for caller to log "
            "followup_notion_sync_failure event"
        )
