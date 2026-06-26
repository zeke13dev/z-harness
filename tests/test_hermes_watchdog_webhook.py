"""Tests for Hermes watchdog webhook routing."""

from pathlib import Path
import hashlib
import hmac
import json
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.so_jobs import SoJobRecord, SoJobRegistry  # noqa: E402
from hermes.watchdog_webhook import (  # noqa: E402
    WatchdogPayload,
    WatchdogPayloadError,
    WatchdogSignatureError,
    handle_watchdog_payload,
    parse_signed_payload,
)


class FakeDiscord:
    def __init__(self):
        self.thread_posts = []
        self.ops_posts = []

    def post_thread(self, *, channel_id, thread_id, requester_user_id, text):
        self.thread_posts.append(
            {
                "channel_id": channel_id,
                "thread_id": thread_id,
                "requester_user_id": requester_user_id,
                "text": text,
            }
        )

    def post_ops(self, text):
        self.ops_posts.append(text)


class FakeSubscriptions:
    def __init__(self):
        self.deliveries = []

    def deliver(self, *, job, payload, text):
        self.deliveries.append((job, payload, text))


def _record(job_id="so-test", thread_id="thread-1", **changes) -> SoJobRecord:
    data = dict(
        job_id=job_id,
        discord_channel_id="chan-1",
        discord_message_id="msg-1",
        discord_thread_id=thread_id,
        requester_user_id="user-1",
        host="omp",
        project="qt-bot",
        repo_root="ssh://zeke-pc/qt-bot",
        execution_host="zeke-pc",
        transport="ssh",
        ssh_target="zeke-pc",
        workdir="/home/zeke/dev/qt-bot",
        z_command="z-debug",
        task="fix blah",
        pid=1234,
        z_harness_run_id="run-1",
        slug="slug-1",
    )
    data.update(changes)
    return SoJobRecord(**data)


def _payload(**changes) -> WatchdogPayload:
    data = {
        "event": "watchdog_stall",
        "event_id": "evt-1",
        "severity": "warning",
        "reason": "agent hung",
        "job_id": "so-test",
        "run_id": "run-1",
        "slug": "slug-1",
        "pid": 1234,
    }
    data.update(changes)
    return WatchdogPayload(**data)


def test_signed_payload_validates_and_maps_to_original_thread(tmp_path):
    raw = json.dumps(
        {
            "event": "watchdog_stall",
            "event_id": "evt-1",
            "severity": "warning",
            "reason": "agent hung",
            "job_id": "so-test",
            "run_id": "run-1",
        }
    ).encode()
    secret = "secret"
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    sig = "sha256=" + digest
    payload = parse_signed_payload(raw, signature=sig, secret=secret)
    registry = SoJobRegistry(tmp_path)
    registry.create(_record())
    discord = FakeDiscord()

    result = handle_watchdog_payload(
        payload, registry=registry, discord=discord
    )

    assert result.status == "delivered"
    assert result.delivered_via == "thread"
    assert discord.thread_posts == [
        {
            "channel_id": "chan-1",
            "thread_id": "thread-1",
            "requester_user_id": "user-1",
            "text": discord.thread_posts[0]["text"],
        }
    ]
    assert "<@user-1>" in discord.thread_posts[0]["text"]
    assert "so-test" in discord.thread_posts[0]["text"]
    assert registry.get("so-test").last_watchdog_event_id == "evt-1"


def test_duplicate_event_is_ignored(tmp_path):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record(last_watchdog_event_id="evt-1"))
    discord = FakeDiscord()

    result = handle_watchdog_payload(
        _payload(), registry=registry, discord=discord
    )

    assert result.status == "duplicate"
    assert discord.thread_posts == []


def test_bad_signature_rejected():
    with pytest.raises(WatchdogSignatureError):
        parse_signed_payload(
            b'{"event":"watchdog_stall"}',
            signature="sha256:bad",
            secret="secret",
        )


def test_unknown_run_posts_ops_only(tmp_path):
    registry = SoJobRegistry(tmp_path)
    discord = FakeDiscord()

    result = handle_watchdog_payload(
        _payload(job_id="missing", run_id="missing", pid=None, slug=None),
        registry=registry,
        discord=discord,
    )

    assert result.status == "unknown"
    assert discord.thread_posts == []
    assert len(discord.ops_posts) == 1


def test_subscription_fallback_when_thread_missing(tmp_path):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record(thread_id=""))
    discord = FakeDiscord()
    subscriptions = FakeSubscriptions()

    result = handle_watchdog_payload(
        _payload(),
        registry=registry,
        discord=discord,
        subscriptions=subscriptions,
    )

    assert result.status == "delivered"
    assert result.delivered_via == "subscription"
    assert discord.thread_posts == []
    assert subscriptions.deliveries[0][0].job_id == "so-test"


def test_missing_optional_fields_tolerated_but_not_guessed(tmp_path):
    registry = SoJobRegistry(tmp_path)
    registry.create(_record())
    discord = FakeDiscord()
    payload = WatchdogPayload(
        event="watchdog_timeout",
        event_id="evt-2",
        severity="error",
        reason="timeout",
        job_id="so-test",
    )

    result = handle_watchdog_payload(
        payload, registry=registry, discord=discord
    )

    assert result.status == "delivered"
    assert discord.thread_posts[0]["thread_id"] == "thread-1"


def test_payload_schema_rejects_missing_required_fields():
    with pytest.raises(WatchdogPayloadError):
        parse_signed_payload(b'{"event":"watchdog_stall"}')
