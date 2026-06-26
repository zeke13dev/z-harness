"""Deprecated watchdog webhook backend for Discord ``so``.

Replaced by ``hermes/so_mcp.py``. This module remains only as historical
reference; production gateway and ``discord_relay`` code must not import it.
Set ``HERMES_ALLOW_DEPRECATED_SO_BACKEND=1`` only for archaeology.
"""

from __future__ import annotations
import os

if os.environ.get("HERMES_ALLOW_DEPRECATED_SO_BACKEND") != "1":
    raise RuntimeError(
        "hermes.watchdog_webhook is deprecated; use hermes.so_mcp for `so` orchestration"
    )


from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Any, Optional, Protocol

from hermes.so_jobs import SoJobRecord, SoJobRegistry

VALID_EVENTS = {"watchdog_stall", "watchdog_timeout"}
VALID_SEVERITIES = {"warning", "error"}


class WatchdogPayloadError(ValueError):
    pass


class WatchdogSignatureError(PermissionError):
    pass


@dataclass(frozen=True)
class WatchdogPayload:
    event: str
    event_id: str
    severity: str
    reason: str
    job_id: Optional[str] = None
    run_id: Optional[str] = None
    slug: Optional[str] = None
    pid: Optional[int] = None
    next_step: Optional[str] = None


@dataclass(frozen=True)
class WatchdogResult:
    status: str
    job: Optional[SoJobRecord] = None
    delivered_via: Optional[str] = None


class DiscordSink(Protocol):
    def post_thread(
        self,
        *,
        channel_id: str,
        thread_id: str,
        requester_user_id: str,
        text: str,
    ) -> None:
        ...

    def post_ops(self, text: str) -> None:
        ...


class WatchdogSubscriptionSink(Protocol):
    def deliver(
        self,
        *,
        job: SoJobRecord,
        payload: WatchdogPayload,
        text: str,
    ) -> None:
        ...


def verify_signature(raw_body: bytes, signature: str, secret: str) -> None:
    if not secret:
        return
    prefix = "sha256="
    if not signature.startswith(prefix):
        raise WatchdogSignatureError("missing sha256 signature")
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    supplied = signature[len(prefix):]
    if not hmac.compare_digest(expected, supplied):
        raise WatchdogSignatureError("bad watchdog signature")


def parse_payload(data: dict[str, Any]) -> WatchdogPayload:
    event = str(data.get("event", ""))
    event_id = str(data.get("event_id", ""))
    severity = str(data.get("severity", "warning") or "warning")
    reason = str(data.get("reason", ""))
    if event not in VALID_EVENTS:
        raise WatchdogPayloadError("invalid watchdog event")
    if not event_id:
        raise WatchdogPayloadError("watchdog event_id is required")
    if severity not in VALID_SEVERITIES:
        raise WatchdogPayloadError("invalid watchdog severity")
    if not reason:
        raise WatchdogPayloadError("watchdog reason is required")

    pid = data.get("pid")
    if pid in (None, ""):
        parsed_pid = None
    else:
        try:
            parsed_pid = int(pid)
        except (TypeError, ValueError) as exc:
            raise WatchdogPayloadError("invalid watchdog pid") from exc

    return WatchdogPayload(
        event=event,
        event_id=event_id,
        severity=severity,
        reason=reason,
        job_id=_optional_str(data.get("job_id")),
        run_id=_optional_str(data.get("run_id")),
        slug=_optional_str(data.get("slug")),
        pid=parsed_pid,
        next_step=_optional_str(data.get("next_step")),
    )


def parse_signed_payload(
    raw_body: bytes, *, signature: str = "", secret: str = ""
) -> WatchdogPayload:
    verify_signature(raw_body, signature, secret)
    try:
        data = json.loads(raw_body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WatchdogPayloadError("invalid watchdog JSON") from exc
    if not isinstance(data, dict):
        raise WatchdogPayloadError("watchdog payload must be an object")
    return parse_payload(data)


def handle_watchdog_payload(
    payload: WatchdogPayload,
    *,
    registry: SoJobRegistry,
    discord: DiscordSink,
    subscriptions: Optional[WatchdogSubscriptionSink] = None,
) -> WatchdogResult:
    job = registry.resolve(
        job_id=payload.job_id,
        run_id=payload.run_id,
        pid=payload.pid,
        slug=payload.slug,
    )
    if job is None:
        discord.post_ops(
            "Unknown watchdog payload: "
            f"event={payload.event} run_id={payload.run_id or ''} "
            f"job_id={payload.job_id or ''} slug={payload.slug or ''}"
        )
        return WatchdogResult(status="unknown")

    if job.last_watchdog_event_id == payload.event_id:
        return WatchdogResult(status="duplicate", job=job)

    text = _thread_message(job, payload)
    if job.discord_thread_id:
        discord.post_thread(
            channel_id=job.discord_channel_id,
            thread_id=job.discord_thread_id,
            requester_user_id=job.requester_user_id,
            text=text,
        )
        registry.mark_watchdog_event_seen(job.job_id, payload.event_id)
        return WatchdogResult(
            status="delivered", job=job, delivered_via="thread"
        )

    if subscriptions is not None:
        subscriptions.deliver(job=job, payload=payload, text=text)
        registry.mark_watchdog_event_seen(job.job_id, payload.event_id)
        return WatchdogResult(
            status="delivered", job=job, delivered_via="subscription"
        )

    discord.post_ops(
        f"Watchdog event for job {job.job_id} could not resume "
        "a Discord thread."
    )
    return WatchdogResult(status="unroutable", job=job)


def _thread_message(job: SoJobRecord, payload: WatchdogPayload) -> str:
    parts = [
        f"<@{job.requester_user_id}> watchdog reported {payload.event}",
        f"severity={payload.severity}",
        f"reason={payload.reason}",
        f"job_id={job.job_id}",
    ]
    if payload.next_step:
        parts.append(f"next_step={payload.next_step}")
    return " | ".join(parts)


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if text else None
