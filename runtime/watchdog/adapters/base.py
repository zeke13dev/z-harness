"""``HostAdapter`` seam for the session-watchdog daemon.

Purpose (T005, criterion #10): define the four-capability interface every
per-host adapter (``claude`` here; ``codex``/``omp`` follow at level 1 per
``runtime/watchdog/HOST_MECHANICS.md``) must implement so the daemon's poll
loop, notify module, and judge dispatch never special-case a host directly:

- ``read_context`` — offset-tracked incremental transcript usage read (D2).
- ``injection_ready`` — is the pane's composer idle enough to safely type
  into right now (nudge / handoff prompt / clear command)?
- ``needs_input`` — is the session showing a prompt/menu the human must
  answer before it can proceed?
- ``handoff_command`` / ``clear_command`` — the literal text to submit for
  the host's ``/z-handoff``-equivalent and clear-equivalent actions.

Design decisions:
- ``ContextReading.pct_used`` (and ``used_tokens``) is ``None`` when the
  cycle's read yields no confident usage signal (no new usage-bearing event,
  or a malformed/truncated trailing line) — this is the ``context_unknown``
  sentinel described in the acceptance criteria. Callers (the level-1 poll
  loop) must treat ``None`` as "skip the context-threshold check this cycle",
  never as 0% (STYLE.md:WL-002 — the sentinel is documented here and must be
  handled at the call site, not silently propagated as a false reading).
- ``window_tokens`` is a required caller-supplied argument, not resolved
  internally: adapters are host-mechanics-only and never shell out to
  ``scripts/config.py`` themselves (STYLE.md:P-004) — the poll loop resolves
  ``watchdog.context_window_tokens`` once via ``registry.get_config_int`` and
  passes it in.
- Interface note (explicitly sanctioned, not scope creep): this seam is
  deliberately scoped to what the ``claude`` adapter needs today. T001's
  grounding (``HOST_MECHANICS.md``) documents that ``omp`` needs a second,
  cached model-context-window data source composed with its transcript read,
  and ``codex`` needs a degraded byte-length fallback estimator when no
  ``token_count`` event exists yet. Both are real per-host requirements that
  the level-1 ``omp``/``codex`` adapter tasks may need to widen this
  interface (e.g. an optional ``degraded`` flag on ``ContextReading``) to
  express — a bounded revision at that point is expected and acceptable, not
  a failure of this seam.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextReading:
    """Result of one incremental context-usage read against a transcript.

    Attributes:
        new_offset: Byte offset to persist (``sessions.json``'s
            ``transcript_offset``) and pass as ``offset`` on the next read.
            Always >= the offset passed in; only advances past bytes the
            reader actually consumed (D2 — never re-reads the whole file).
        used_tokens: Total tokens the transcript reports as occupying the
            model's context window as of the newest usage-bearing event seen
            in this read, or ``None`` when unknown this cycle (no new
            usage-bearing line appeared, or the only candidate line was
            malformed/truncated).
        window_tokens: The context-window ceiling used as the denominator
            (caller-supplied; see module docstring).
        pct_used: ``used_tokens / window_tokens * 100``, or ``None`` exactly
            when ``used_tokens`` is ``None`` (the ``context_unknown``
            sentinel for this cycle).
        degraded: ``True`` when ``used_tokens``/``pct_used`` come from a
            low-confidence fallback estimator rather than a real usage event
            (e.g. codex's/omp's byte-length heuristic when no usage-bearing
            event exists yet — see ``HOST_MECHANICS.md``). ``False`` for a
            confident reading and for the ``context_unknown`` (``None``)
            case alike. Added as the bounded interface widening this
            module's original docstring anticipated for the codex/omp
            adapters (T008/T009); ``claude.py`` never sets it, so it
            defaults to ``False`` and is fully backward compatible.
    """

    new_offset: int
    used_tokens: int | None
    window_tokens: int
    pct_used: float | None
    degraded: bool = False


class HostAdapter(abc.ABC):
    """The four-capability contract each babysat host implements.

    Attributes:
        host: The ``VALID_HOSTS`` name this adapter implements (``"claude"``,
            ``"codex"``, or ``"omp"`` — see ``runtime/watchdog/registry.py``).
    """

    host: str

    @abc.abstractmethod
    def read_context(
        self, transcript_path: str, offset: int, *, window_tokens: int
    ) -> ContextReading:
        """Read usage-bearing transcript lines appended since ``offset``.

        Hard-fail is NOT the contract here: a missing file, an I/O error, or
        a malformed/truncated trailing line all degrade to the
        ``context_unknown`` sentinel (see ``ContextReading``) rather than
        raising — the daemon's poll loop must keep running even when a single
        cycle's read is inconclusive.

        Args:
            transcript_path: Absolute path to the host's transcript file.
            offset: The last byte offset consumed from this file (0 on the
                first read for a session).
            window_tokens: The model's context-window ceiling (denominator).

        Returns:
            A ``ContextReading`` whose ``new_offset`` is safe to persist
            regardless of whether a confident usage reading was found.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def injection_ready(self, pane_text: str) -> bool:
        """Return whether ``pane_text`` shows the pane ready to receive typed
        input right now (safe to nudge / send a handoff prompt / clear).
        """
        raise NotImplementedError

    @abc.abstractmethod
    def needs_input(self, pane_text: str) -> bool:
        """Return whether ``pane_text`` shows the session waiting on the
        human (a prompt or a selection menu) before it can proceed.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def handoff_command(self) -> str:
        """Return the literal text to submit to invoke this host's
        ``/z-handoff``-equivalent action."""
        raise NotImplementedError

    @abc.abstractmethod
    def clear_command(self) -> str:
        """Return the literal text to submit to invoke this host's
        clear-equivalent action."""
        raise NotImplementedError
