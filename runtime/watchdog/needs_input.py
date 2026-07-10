"""needs_input detection + Discord brief dispatch for the session-watchdog daemon.

Purpose (T012, criterion #5): given one session record, an injected
``HostAdapter``, and the session's already-captured tmux pane text, decide
whether this poll cycle should dispatch a needs_input Discord brief, and
perform the dispatch — exactly once per distinct (question, options) prompt.

Public surface:
- ``evaluate_needs_input`` — the entry point. Gates on
  ``adapter.needs_input(pane_text)``, extracts the question/options from
  ``pane_text``, digest-dedupes against the caller-supplied ``last_digest``,
  and dispatches via ``notify.send_needs_input_alert`` on a genuinely new
  prompt.
- ``extract_question_and_options`` — the pragmatic pane-text parser: finds a
  numbered (``1. ...``) or bulleted (``- ``/``* ``/``›/``❯``) option block and
  the nearest preceding non-footer line as the question.

Design decisions:
- Dependency-injection seam discipline (mirrors T005's ``HostAdapter`` seam,
  T007's ``judge.py``, and T011's ``stuck.py``): ``adapter`` and ``alert_fn``
  are caller-supplied. This module never captures a pane itself (the caller
  supplies the already-captured ``pane_text``) and never resolves any
  ``watchdog.*`` config knob.
- Dedup contract (frozen T003 registry schema has no
  ``last_needs_input_digest`` field and must not be widened): this module is
  stateless with respect to persistence. The caller passes in the
  previously-sent digest (``last_digest``, ``None`` if no prior send this
  episode) and this module returns the newly computed digest alongside
  whether a send happened this cycle. The level-2 poll loop owns *where*
  that digest is persisted across polls (daemon memory or a sidecar file) —
  deliberately NOT a ``sessions.json`` schema change, per ``notify.py``'s own
  documented non-scope note and ``stuck.py``'s precedent for keeping
  escalation state out of new schema fields.
- Extraction is a pragmatic heuristic, not a per-host parser: real claude /
  omp / codex menu renderings diverge in glyphs and footer phrasing (see
  ``HOST_MECHANICS.md`` and the ``tests/fixtures/watchdog/{omp,codex}/
  prompt_ready_pane.txt`` STATE captures), so ``extract_question_and_options``
  looks for the two common shapes (a numbered list, or a bullet/glyph-prefixed
  list) and takes the nearest preceding non-footer line as the question. A
  per-host precision extractor is an explicit non-scope note here, same as
  ``base.py``'s interface-widening note for the codex/omp adapters.
- ``needs_input_digest`` (T006) is reused verbatim rather than re-implemented
  here — one source of truth for the dedup key, consistent with ``stuck.py``
  reusing ``notify.escalation_action``.

Non-scope (the level-2 poll loop owns these — deliberately absent here):
capturing the pane text, persisting ``last_digest`` across polls, resolving
any ``watchdog.*`` config knob, and deciding when a session transitions into
(or out of) the ``needs_input`` lifecycle state.
"""

from __future__ import annotations

import re
from typing import Callable

from runtime.watchdog import notify
from runtime.watchdog.adapters.base import HostAdapter

_NUMBERED_OPTION_RE = re.compile(r"^(\d+)\.\s+(.+)$")
"""Matches a numbered menu option line (e.g. codex's ``1. gpt-5.5 (default)``)
after glyph-prefix stripping."""

_BULLET_PREFIXES: tuple[str, ...] = ("- ", "* ", "› ", "❯ ")
"""Leading bullet/cursor markers for a non-numbered option line: ``- ``,
``* ``, ``› `` (codex ready-glyph), ``❯ `` (omp ready-glyph)."""

_FOOTER_MARKERS: tuple[str, ...] = (
    "press enter",
    "esc to",
    "esc cancel",
    "enter select",
    "tab to cycle",
)
"""Substrings (matched case-insensitively) identifying a menu footer/hint
line — never treated as the question or an option."""


def _option_text(line: str) -> str | None:
    """Return the option label if ``line`` looks like a menu option line.

    Recognizes a numbered option (``N. text``, with an optional leading
    cursor glyph already stripped by ``extract_question_and_options``) or a
    bullet/glyph-prefixed option (``- text`` / ``* text`` / ``› text`` /
    ``❯ text``). Returns ``None`` for anything else.
    """
    match = _NUMBERED_OPTION_RE.match(line)
    if match:
        return match.group(2).strip()
    for prefix in _BULLET_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _is_footer_line(line: str) -> bool:
    """Return True if ``line`` is a menu footer/hint line, never a question
    or option (case-insensitive substring match against ``_FOOTER_MARKERS``)."""
    low = line.lower()
    return any(marker in low for marker in _FOOTER_MARKERS)


def _strip_leading_glyph(line: str) -> str:
    """Strip a single leading cursor glyph (``›``/``❯``/``>``) plus
    following whitespace, so a glyph-prefixed numbered option (e.g. codex's
    ``› 1. gpt-5.5 (default)``) still matches ``_NUMBERED_OPTION_RE``."""
    for glyph in ("›", "❯", ">"):
        if line.startswith(glyph):
            return line[len(glyph) :].strip()
    return line


def extract_question_and_options(pane_text: str) -> tuple[str, list[str]]:
    """Extract a (question, options) pair from raw tmux pane text.

    Args:
        pane_text: The session's already-captured tmux pane text.

    Returns:
        A ``(question, options)`` tuple. When a numbered or bulleted option
        block is found, ``question`` is the nearest preceding non-blank,
        non-footer line and ``options`` is the ordered list of extracted
        option labels. When no option block is found, ``question`` is the
        last non-blank, non-footer line and ``options`` is ``[]`` (a bare
        yes/no or free-text prompt).
    """
    non_blank = [line.strip() for line in pane_text.splitlines() if line.strip()]
    normalized = [_strip_leading_glyph(line) for line in non_blank]

    option_start: int | None = None
    options: list[str] = []
    for idx, line in enumerate(normalized):
        text = _option_text(line)
        if text is not None:
            if option_start is None:
                option_start = idx
            options.append(text)
        elif option_start is not None:
            break  # contiguous option block ended

    if option_start is not None:
        for line in reversed(non_blank[:option_start]):
            if not _is_footer_line(line):
                return line, options
        return "", options

    for line in reversed(non_blank):
        if not _is_footer_line(line):
            return line, []
    return "", []


def evaluate_needs_input(
    record: dict,
    *,
    pane_text: str,
    adapter: HostAdapter,
    last_digest: str | None,
    alert_fn: Callable[..., bool] = notify.send_needs_input_alert,
) -> dict:
    """Decide and perform this cycle's needs_input Discord dispatch.

    Args:
        record: The session record (``registry.py`` schema); read-only —
            only ``tmux_target`` (falling back to ``session_id``) is read,
            for the Discord brief's session label.
        pane_text: The session's already-captured tmux pane text.
        adapter: The session's ``HostAdapter`` (used for ``needs_input``).
        last_digest: The digest of the last needs_input prompt already
            alerted for this session (``None`` if none this episode) —
            caller-supplied and caller-persisted; see module docstring.
        alert_fn: The Discord sender; defaults to
            ``notify.send_needs_input_alert`` (injected so tests never hit a
            real webhook).

    Returns:
        ``{"action": "skip" | "sent" | "send_failed", "digest": str | None,
        "sent": bool}``, plus ``"question"``/``"options"`` when an alert was
        attempted this cycle. ``action`` is:
        - ``"skip"`` — ``adapter.needs_input(pane_text)`` is False, or the
          extracted prompt's digest matches ``last_digest`` (already
          alerted); ``digest`` echoes ``last_digest`` unchanged and ``sent``
          is ``False``.
        - ``"sent"`` — a genuinely new prompt (or the first one this
          episode) and ``alert_fn`` reported success; ``digest`` is the new
          prompt's digest.
        - ``"send_failed"`` — a genuinely new prompt but ``alert_fn``
          reported failure (e.g. Discord webhook unreachable); ``digest`` is
          still the new prompt's digest so the caller does not re-attempt an
          identical failed send every subsequent poll (mirrors
          ``send_discord_alert``'s fail-open contract: a lost notification
          must never crash or wedge the daemon's poll loop).
    """
    if not adapter.needs_input(pane_text):
        return {"action": "skip", "digest": last_digest, "sent": False}

    question, options = extract_question_and_options(pane_text)
    digest = notify.needs_input_digest(question, options)

    if digest == last_digest:
        return {"action": "skip", "digest": digest, "sent": False}

    session_label = record.get("tmux_target") or record.get("session_id", "")
    sent = alert_fn(session_label, question, options)
    return {
        "action": "sent" if sent else "send_failed",
        "digest": digest,
        "sent": sent,
        "question": question,
        "options": options,
    }
