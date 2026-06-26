"""Ask-first supervisor for Hermes `so` jobs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Optional, Protocol

from hermes.so_jobs import SoJobRecord, SoJobRegistry, utc_now


class TmuxIO(Protocol):
    def capture_pane(self, job: SoJobRecord, *, limit: int = 80) -> str:
        ...

    def send_keys(self, job: SoJobRecord, text: str) -> None:
        ...

    def session_exists(self, job: SoJobRecord) -> bool:
        ...

    def pid_alive(self, job: SoJobRecord) -> bool:
        ...

    def attach_guidance(self, job: SoJobRecord) -> str:
        ...

    def abort(self, job: SoJobRecord) -> None:
        ...

    def restart(self, job: SoJobRecord) -> tuple[str, Optional[int]]:
        ...


class DiscordPromptSink(Protocol):
    def ask_user(
        self,
        *,
        channel_id: str,
        thread_id: str,
        requester_user_id: str,
        text: str,
    ) -> None:
        ...

    def post_checkup(
        self,
        *,
        channel_id: str,
        thread_id: str,
        requester_user_id: str,
        text: str,
    ) -> None:
        ...


@dataclass(frozen=True)
class PendingPrompt:
    job_id: str
    channel_id: str
    thread_id: str
    requester_user_id: str
    pane_digest: str
    pane_excerpt: str
    prompt_features: dict[str, object]


@dataclass(frozen=True)
class SupervisorResult:
    status: str
    job: Optional[SoJobRecord] = None


class HermesSupervisor:
    def __init__(
        self,
        *,
        registry: SoJobRegistry,
        tmux: TmuxIO,
        discord: DiscordPromptSink,
    ):
        self.registry = registry
        self.tmux = tmux
        self.discord = discord
        self.pending_by_thread: dict[tuple[str, str], PendingPrompt] = {}

    def inspect_and_ask(self, job_id: str) -> SupervisorResult:
        job = self.registry.get(job_id)
        if job is None:
            return SupervisorResult(status="unknown")

        pane_excerpt = self.tmux.capture_pane(job, limit=80)
        digest = pane_digest(pane_excerpt)
        thread_key = (job.discord_channel_id, job.discord_thread_id)
        duplicate_digest = job.last_pane_digest == digest
        duplicate_pending = thread_key in self.pending_by_thread
        if duplicate_digest or duplicate_pending:
            return SupervisorResult(status="duplicate_prompt", job=job)

        features = prompt_features(pane_excerpt)
        pending = PendingPrompt(
            job_id=job.job_id,
            channel_id=job.discord_channel_id,
            thread_id=job.discord_thread_id,
            requester_user_id=job.requester_user_id,
            pane_digest=digest,
            pane_excerpt=pane_excerpt,
            prompt_features=features,
        )
        self.pending_by_thread[thread_key] = pending
        ask_text = (
            f"<@{job.requester_user_id}> Hermes needs your input for "
            f"job {job.job_id}.\n\n```text\n{pane_excerpt}\n```"
        )
        self.discord.ask_user(
            channel_id=job.discord_channel_id,
            thread_id=job.discord_thread_id,
            requester_user_id=job.requester_user_id,
            text=ask_text,
        )
        updated = self.registry.transition(
            job.job_id,
            "asking_user",
            last_pane_digest=digest,
        )
        return SupervisorResult(status="asked", job=updated)

    def handle_discord_reply(
        self,
        *,
        channel_id: str,
        thread_id: str,
        requester_user_id: str,
        text: str,
    ) -> SupervisorResult:
        key = (str(channel_id), str(thread_id))
        pending = self.pending_by_thread.get(key)
        if pending is None:
            return SupervisorResult(status="ignored")
        wrong_requester = pending.requester_user_id != str(requester_user_id)
        if wrong_requester:
            return SupervisorResult(status="ignored")

        job = self.registry.get(pending.job_id)
        if job is None:
            self.pending_by_thread.pop(key, None)
            return SupervisorResult(status="unknown")

        self.tmux.send_keys(job, text)
        record = {
            "recorded_at": utc_now(),
            "pane_digest": pending.pane_digest,
            "pane_excerpt": pending.pane_excerpt,
            "prompt_features": pending.prompt_features,
            "user_answer": text,
            "sent_text": text,
            "job_context": {
                "job_id": job.job_id,
                "host": job.host,
                "project": job.project,
                "z_command": job.z_command,
                "task": job.task,
            },
            "outcome": "sent_to_tmux",
        }
        records = list(job.prompt_records)
        records.append(record)
        updated = self.registry.transition(
            job.job_id,
            "running",
            prompt_records=records,
            last_progress_at=utc_now(),
        )
        self.pending_by_thread.pop(key, None)
        return SupervisorResult(status="sent", job=updated)

    def check_session_health(self, job_id: str) -> SupervisorResult:
        job = self.registry.get(job_id)
        if job is None:
            return SupervisorResult(status="unknown")
        if job.status in {"dead", "stale", "aborted"}:
            return SupervisorResult(status="already_checkup", job=job)

        if not self.tmux.session_exists(job):
            return self._mark_checkup(job, "dead", "tmux session is missing")
        if job.pid is not None and not self.tmux.pid_alive(job):
            return self._mark_checkup(job, "dead", "process is dead")

        pane_excerpt = self.tmux.capture_pane(job, limit=80)
        digest = pane_digest(pane_excerpt)
        if job.last_watchdog_event_id and job.last_pane_digest == digest:
            return self._mark_checkup(job, "stale", "pane output is unchanged")

        updated = self.registry.transition(
            job.job_id, "running", last_pane_digest=digest
        )
        return SupervisorResult(status="running", job=updated)

    def handle_checkup_action(self, job_id: str, action: str) -> SupervisorResult:
        job = self.registry.get(job_id)
        if job is None:
            return SupervisorResult(status="unknown")
        if action == "attach":
            text = self.tmux.attach_guidance(job)
            self._post_checkup(job, text)
            return SupervisorResult(status="attach_guidance", job=job)
        if action == "abort":
            self.tmux.abort(job)
            updated = self.registry.transition(job.job_id, "aborted")
            self._post_checkup(job, f"Job {job.job_id} aborted.")
            return SupervisorResult(status="aborted", job=updated)
        if action == "restart":
            session_name, pid = self.tmux.restart(job)
            updated = self.registry.transition(
                job.job_id,
                "running",
                tmux_session=session_name,
                pid=pid,
            )
            self._post_checkup(job, f"Job {job.job_id} restarted.")
            return SupervisorResult(status="restarted", job=updated)
        return SupervisorResult(status="ignored", job=job)

    def apply_promoted_reply(
        self, job_id: str, rules: "LearnedReplyRules"
    ) -> SupervisorResult:
        job = self.registry.get(job_id)
        if job is None:
            return SupervisorResult(status="unknown")
        pane_excerpt = self.tmux.capture_pane(job, limit=80)
        features = prompt_features(pane_excerpt)
        candidate = rules.match(features)
        if candidate is None:
            return SupervisorResult(status="no_match", job=job)
        self.tmux.send_keys(job, candidate.reply_text)
        record = {
            "recorded_at": utc_now(),
            "pane_digest": pane_digest(pane_excerpt),
            "pane_excerpt": pane_excerpt,
            "prompt_features": features,
            "user_answer": candidate.reply_text,
            "sent_text": candidate.reply_text,
            "job_context": {
                "job_id": job.job_id,
                "host": job.host,
                "project": job.project,
                "z_command": job.z_command,
                "task": job.task,
            },
            "outcome": "sent_to_tmux",
            "candidate_id": candidate.candidate_id,
            "source_evidence": candidate.source_evidence,
        }
        records = list(job.prompt_records)
        records.append(record)
        updated = self.registry.transition(
            job.job_id,
            "running",
            prompt_records=records,
            last_progress_at=utc_now(),
        )
        return SupervisorResult(status="auto_replied", job=updated)

    def _mark_checkup(
        self, job: SoJobRecord, status: str, reason: str
    ) -> SupervisorResult:
        updated = self.registry.transition(job.job_id, status)
        self._post_checkup(
            updated,
            f"Job {job.job_id} is {status}: {reason}. "
            "Choose attach, abort, or restart.",
        )
        return SupervisorResult(status=status, job=updated)

    def _post_checkup(self, job: SoJobRecord, text: str) -> None:
        self.discord.post_checkup(
            channel_id=job.discord_channel_id,
            thread_id=job.discord_thread_id,
            requester_user_id=job.requester_user_id,
            text=text,
        )


@dataclass(frozen=True)
class ReplyPatternCandidate:
    candidate_id: str
    reply_text: str
    required_tokens: tuple[str, ...]
    source_evidence: tuple[str, ...]
    status: str = "candidate"


class LearnedReplyRules:
    def __init__(self, candidates: list[ReplyPatternCandidate] | None = None):
        self.candidates = {c.candidate_id: c for c in candidates or []}

    def promote(self, candidate_id: str) -> ReplyPatternCandidate:
        candidate = self.candidates[candidate_id]
        promoted = ReplyPatternCandidate(
            candidate_id=candidate.candidate_id,
            reply_text=candidate.reply_text,
            required_tokens=candidate.required_tokens,
            source_evidence=candidate.source_evidence,
            status="promoted",
        )
        self.candidates[candidate_id] = promoted
        return promoted

    def revoke(self, candidate_id: str) -> ReplyPatternCandidate:
        candidate = self.candidates[candidate_id]
        revoked = ReplyPatternCandidate(
            candidate_id=candidate.candidate_id,
            reply_text=candidate.reply_text,
            required_tokens=candidate.required_tokens,
            source_evidence=candidate.source_evidence,
            status="revoked",
        )
        self.candidates[candidate_id] = revoked
        return revoked

    def match(self, features: dict[str, object]) -> Optional[ReplyPatternCandidate]:
        tokens = set(features.get("tokens", []))
        for candidate in self.candidates.values():
            if candidate.status != "promoted":
                continue
            if set(candidate.required_tokens).issubset(tokens):
                return candidate
        return None


def mine_reply_candidates(
    records: list[dict[str, object]], *, min_count: int = 2
) -> list[ReplyPatternCandidate]:
    groups: dict[tuple[str, tuple[str, ...]], list[dict[str, object]]] = {}
    for record in records:
        if record.get("outcome") != "sent_to_tmux":
            continue
        reply_text = str(record.get("sent_text") or "")
        if not reply_text:
            continue
        features = record.get("prompt_features") or {}
        if not isinstance(features, dict):
            continue
        tokens = tuple(_candidate_tokens(features.get("tokens", [])))
        if not tokens:
            continue
        groups.setdefault((reply_text, tokens), []).append(record)

    candidates = []
    for (reply_text, tokens), evidence in sorted(groups.items()):
        if len(evidence) < min_count:
            continue
        evidence_ids = tuple(
            str((item.get("job_context") or {}).get("job_id", "unknown"))
            for item in evidence
        )
        seed = reply_text + "|" + " ".join(tokens) + "|" + ",".join(evidence_ids)
        candidate_id = "reply-" + hashlib.sha256(seed.encode()).hexdigest()[:12]
        candidates.append(
            ReplyPatternCandidate(
                candidate_id=candidate_id,
                reply_text=reply_text,
                required_tokens=tokens,
                source_evidence=evidence_ids,
            )
        )
    return candidates


def _candidate_tokens(tokens: object) -> list[str]:
    stop = {"the", "a", "an", "to", "for", "job", "hermes"}
    if not isinstance(tokens, list):
        return []
    result = []
    for token in tokens:
        text = str(token)
        if text in stop:
            continue
        if text not in result:
            result.append(text)
        if len(result) == 6:
            break
    return result


def pane_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def prompt_features(text: str) -> dict[str, object]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_/.-]+", lowered)
    return {
        "tokens": tokens[:40],
        "has_destructive_terms": any(
            token in {"delete", "drop", "truncate", "kill", "overwrite"}
            for token in tokens
        ),
        "has_credential_terms": any(
            token in {"password", "token", "secret", "credential"}
            for token in tokens
        ),
        "has_cost_terms": any(
            token in {"cost", "billing", "spend"} for token in tokens
        ),
    }
