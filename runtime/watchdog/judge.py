"""Judge dispatch module for the session-watchdog daemon.

Purpose (T007, criteria #3/#9): dispatch the ``watchdog_judge`` provider role
for a context-threshold stop-point decision, under a hard per-attempt timeout
with exactly one retry, and degrade gracefully to a mechanical, threshold-only
fallback verdict — never raising — whenever the judge is unbound or
unavailable after the retry.

Public surface:
- ``dispatch_judge_verdict`` — the entry point. Resolves ``role`` (default
  ``watchdog_judge``) via ``runtime.compat.resolve_provider``, dispatches
  ``prompt`` to the resolved provider CLI, retries exactly once on failure,
  and returns ``{"verdict": dict, "judge_degraded": dict | None}``.
- ``mechanical_fallback_verdict`` — the threshold-only stop-point decision
  used both as the degrade path and available standalone for callers that
  want to pre-compute it.

Design decisions:
- Reuse over reimplementation (STYLE.md:P-004 / WL-002 rung 2): provider role
  resolution shells out via ``runtime.compat.resolve_provider`` (itself a
  thin wrapper around ``scripts/resolve-provider.py``) rather than
  re-invoking or re-parsing that script directly. The actual model dispatch
  follows the same stdin/positional-arg protocol every other consumer of a
  resolved descriptor uses (see ``scripts/audit-preview-misses.sh``): when
  the descriptor's ``stdin`` field is true the prompt is piped to the
  provider command's stdin (the contract every registry entry declares,
  including the ``omp-consult.sh`` shim — see
  ``docs/llm/providers-registry.json``'s ``omp_consult_boundary``); otherwise
  the prompt is appended as the final positional argument.
- ``timeout_s`` is a caller-supplied argument, not resolved internally from
  ``watchdog.judge_timeout_s`` — mirrors the config-free stance already
  established by ``notify.py`` and ``adapters/base.py`` ("adapters/notify
  never shell out to ``scripts/config.py`` themselves; the poll loop resolves
  the knob once via ``registry.get_config_int`` and passes it in"). This
  module keeps ``DEFAULT_TIMEOUT_S`` in sync with the documented
  ``watchdog.judge_timeout_s`` default (60) purely as a same-value fallback
  for direct/manual callers (e.g. tests), not as a hidden config read.
- Exactly one retry (STYLE.md:EH-001 — best-effort, documented): a role
  resolution failure (unbound/unresolvable role) degrades immediately with
  zero dispatch attempts, since retrying a resolution that cannot succeed
  wastes the timeout budget for no benefit. A *resolved* provider gets up to
  two dispatch attempts (the initial try plus exactly one retry) before
  degrading; both attempts share the same per-attempt ``timeout_s``, no
  backoff.
- ``judge_degraded`` is returned as a plain dict, never written to
  ``signals.jsonl`` by this module — the destination contract (T003's
  ``registry.append_signal``) belongs to the caller, which already owns the
  session record and the resolved ``signals_path``/``watchdog.signals_max_mb``
  knob (STYLE.md:P-003 — every field is enumerated explicitly, never spread).
- Non-scope (a later level owns these): building the judge prompt itself and
  parsing a structured verdict schema out of the judge's free-text response.
  No prompt-building or verdict schema has been defined anywhere in this
  plan yet, so a successful dispatch's raw provider output is returned
  verbatim under ``verdict["raw_output"]`` rather than guessing an
  unspecified structure — the level that wires the context-threshold state
  machine is the one that will define and parse that contract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from runtime.compat import resolve_provider

# ── constants (frozen-ish; see design decisions above) ───────────────────────

JUDGE_ROLE = "watchdog_judge"
"""Default provider role this module resolves (INTENT public surface)."""

DEFAULT_TIMEOUT_S = 60
"""Same-value fallback mirroring ``watchdog.judge_timeout_s``'s documented
default (T002) — callers should resolve the live config value and pass it in
via ``timeout_s`` rather than relying on this constant (see module design
decisions: this module stays config-free)."""

_MAX_ATTEMPTS = 2
"""Initial dispatch attempt plus exactly one retry (criterion #3/#9)."""


# ── verdict builders ─────────────────────────────────────────────────────────

def mechanical_fallback_verdict(context_pct: float, threshold_pct: float) -> dict:
    """Build the mechanical, threshold-only stop-point verdict.

    Hard-fail-free by construction: pure arithmetic comparison, never raises.
    This is the degrade-path verdict used whenever the judge is unbound or
    unavailable after the retry (criterion #3 — "a threshold crossing still
    triggers the handoff sequence via mechanical fallback").

    Args:
        context_pct: Current measured context usage percentage.
        threshold_pct: The configured ``watchdog.context_threshold_pct``.

    Returns:
        ``{"source": "mechanical_fallback", "stop": bool, "context_pct":
        float, "threshold_pct": float}`` — ``stop`` is ``True`` iff
        ``context_pct >= threshold_pct``.
    """
    return {
        "source": "mechanical_fallback",
        "stop": context_pct >= threshold_pct,
        "context_pct": context_pct,
        "threshold_pct": threshold_pct,
    }


def _judge_verdict_from_output(raw_output: str) -> dict:
    """Wrap a successful judge dispatch's raw stdout as a verdict dict.

    Non-scope (see module docstring): no structured verdict schema exists
    yet, so the provider's text response is stored verbatim rather than
    parsed.
    """
    return {"source": "judge", "raw_output": raw_output.strip()}


def _judge_degraded_event(role: str, reason: str, attempts: int, timeout_s: float) -> dict:
    """Build the ``judge_degraded`` event payload (STYLE.md:P-003 — every
    field enumerated explicitly). The caller is responsible for appending
    this to ``signals.jsonl`` (via T003's ``registry.append_signal``); this
    module only returns the dict.
    """
    return {
        "role": role,
        "reason": reason,
        "attempts": attempts,
        "timeout_s": timeout_s,
    }


# ── provider dispatch ─────────────────────────────────────────────────────────

def _dispatch_once(descriptor: dict, prompt: str, timeout_s: float) -> str:
    """Invoke the resolved provider CLI once with ``prompt``. Hard-fail.

    Follows the stdin/positional-arg protocol every resolved-descriptor
    consumer uses (see module docstring): pipes ``prompt`` to stdin when
    ``descriptor["stdin"]`` is true, else appends it as the final positional
    argument.

    Raises:
        subprocess.TimeoutExpired: if the call exceeds ``timeout_s``.
        RuntimeError: if the process exits non-zero or produces no usable
            (non-whitespace) stdout.
        OSError: if the provider command cannot be launched (e.g. not on
            PATH — should not normally happen post-preflight, but is not
            swallowed here; the retry loop in ``dispatch_judge_verdict``
            treats it the same as a timeout).

    Returns:
        The raw stdout text (not yet stripped/parsed).
    """
    command = str(descriptor.get("command") or "")
    args = list(descriptor.get("args_template") or [])
    argv = [command, *args]
    use_stdin = bool(descriptor.get("stdin"))

    if use_stdin:
        result = subprocess.run(
            argv, input=prompt, capture_output=True, text=True, timeout=timeout_s
        )
    else:
        result = subprocess.run(
            [*argv, prompt], capture_output=True, text=True, timeout=timeout_s
        )

    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"judge provider {descriptor.get('provider')!r} exited "
            f"{result.returncode} with no usable output: "
            f"{result.stderr.strip()[:500]}"
        )
    return result.stdout


# ── entry point ───────────────────────────────────────────────────────────────

def dispatch_judge_verdict(
    *,
    context_pct: float,
    threshold_pct: float,
    prompt: str,
    repo_root: str | Path,
    role: str = JUDGE_ROLE,
    timeout_s: float | None = None,
) -> dict:
    """Dispatch ``role`` for a stop-point verdict; never raises.

    Best-effort overall (STYLE.md:EH-001): a missing/unresolvable ``role``,
    or a resolved provider that still fails/times out after exactly one
    retry, both degrade to ``mechanical_fallback_verdict`` plus a
    ``judge_degraded`` event dict instead of propagating an exception — a
    daemon poll cycle must never crash because the judge is unavailable
    (criterion #3).

    Args:
        context_pct: Current measured context usage percentage.
        threshold_pct: The configured ``watchdog.context_threshold_pct``.
        prompt: The already-built judge prompt (opaque string; prompt
            construction is a later level's concern — see module docstring).
        repo_root: Absolute repo root, forwarded to
            ``runtime.compat.resolve_provider``.
        role: Provider role to resolve. Defaults to ``watchdog_judge``.
        timeout_s: Hard per-attempt timeout in seconds. Defaults to
            ``DEFAULT_TIMEOUT_S`` when omitted; callers should pass the
            resolved ``watchdog.judge_timeout_s`` config value (this module
            stays config-free — see module design decisions).

    Returns:
        ``{"verdict": dict, "judge_degraded": dict | None}``.
        ``judge_degraded`` is ``None`` on a successful dispatch; otherwise a
        fully-enumerated event payload (``role``, ``reason``, ``attempts``,
        ``timeout_s``) describing why the fallback path was taken. The
        caller — not this module — is responsible for appending
        ``judge_degraded`` to ``signals.jsonl``.
    """
    effective_timeout = float(timeout_s) if timeout_s is not None else float(DEFAULT_TIMEOUT_S)

    try:
        descriptor = resolve_provider(role, str(repo_root))
    except (FileNotFoundError, RuntimeError) as exc:
        return {
            "verdict": mechanical_fallback_verdict(context_pct, threshold_pct),
            "judge_degraded": _judge_degraded_event(
                role, f"role_unresolved: {exc}", attempts=0, timeout_s=effective_timeout
            ),
        }

    last_reason = ""
    attempts = 0
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        attempts = attempt
        try:
            raw_output = _dispatch_once(descriptor, prompt, effective_timeout)
        except (subprocess.TimeoutExpired, RuntimeError, OSError) as exc:
            last_reason = str(exc)
            continue
        return {
            "verdict": _judge_verdict_from_output(raw_output),
            "judge_degraded": None,
        }

    return {
        "verdict": mechanical_fallback_verdict(context_pct, threshold_pct),
        "judge_degraded": _judge_degraded_event(
            role, last_reason, attempts=attempts, timeout_s=effective_timeout
        ),
    }
