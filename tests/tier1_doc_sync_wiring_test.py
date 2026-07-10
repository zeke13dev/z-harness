"""
tests/tier1_doc_sync_wiring_test.py — Regression guard for the Tier-1 doc-sync wiring.

Root cause this locks down: `agents/tier1-doc-updater.md` + `scripts/reconcile-tier1-staged.py`
were ported into the repo but never referenced by any command, so per-run doc sync silently
never ran and docs went stale. These assertions fail if the wiring is removed again.

Design invariant (see docs/human/tier1-doc-updater.md): the updater is dispatched EXACTLY ONCE
at /z-execute Finalize over the run's combined task-diff set, then reconciled — one staged doc
per concept, no cross-task staging race.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
Z_EXECUTE_SKILL = REPO_ROOT / "skills" / "z-execute" / "SKILL.md"
AGENT_CONTRACT = REPO_ROOT / "agents" / "tier1-doc-updater.md"
RECONCILE_SCRIPT = REPO_ROOT / "scripts" / "reconcile-tier1-staged.py"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _index_after(text: str, needle: str, start: int = 0) -> int:
    idx = text.find(needle, start)
    assert idx != -1, f"missing marker {needle!r}"
    return idx


def test_reconcile_script_and_agent_exist() -> None:
    assert RECONCILE_SCRIPT.is_file(), "reconcile-tier1-staged.py must exist"
    assert AGENT_CONTRACT.is_file(), "tier1-doc-updater agent contract must exist"


def test_finalize_dispatches_updater_and_reconciles() -> None:
    text = _text(Z_EXECUTE_SKILL)
    finalize = _index_after(text, "## Finalize")
    # The doc-sync step lives in Finalize, before the Telemetry section.
    telemetry = _index_after(text, "## Telemetry", finalize)
    block = text[finalize:telemetry]

    # The updater is actually spawned...
    assert 'subagent_type="tier1-doc-updater"' in block, (
        "z-execute Finalize must spawn the tier1-doc-updater — otherwise doc sync never runs"
    )
    # ...and its staged output is reconciled into live docs.
    assert "reconcile-tier1-staged.py" in block, (
        "z-execute Finalize must invoke reconcile-tier1-staged.py after the updater"
    )


def test_doc_sync_is_gated_and_best_effort() -> None:
    text = _text(Z_EXECUTE_SKILL)
    finalize = _index_after(text, "## Finalize")
    telemetry = _index_after(text, "## Telemetry", finalize)
    block = text[finalize:telemetry]

    # Gated on the repo actually having a two-tier docs system.
    assert "docs/llm/INDEX.json" in block, "doc sync must be gated on docs/llm/INDEX.json existing"
    assert "DOCSYNC_ELIGIBLE" in block, "doc sync must compute an eligibility gate"
    # Must not run on an aborted finalize.
    assert 'FINALIZE_STATUS:-complete' in block and 'aborted' in block, (
        "doc sync must be skipped when the run aborted"
    )


def test_doc_sync_precedes_deregister() -> None:
    text = _text(Z_EXECUTE_SKILL)
    finalize = _index_after(text, "## Finalize")
    updater = _index_after(text, 'subagent_type="tier1-doc-updater"', finalize)
    # The normal-completion deregister call comes AFTER the doc-sync step so docs
    # land while the registry lock is still held.
    deregister = _index_after(text, 'deregister \\\n       --run-id "$RUN"', updater)
    assert updater < deregister, "doc sync must run before the run deregisters"


def test_agent_contract_is_run_end_not_per_task() -> None:
    text = _text(AGENT_CONTRACT)
    # Inputs are the combined diff set + explicit staging dir.
    assert "diff_paths" in text, "agent must accept a diff_paths set (run's combined diffs)"
    assert "staging_dir" in text, "agent must accept an explicit staging_dir"
    # The once-per-run guarantee is the whole point.
    assert "exactly once per run" in text, (
        "agent contract must state the once-per-run (no cross-task race) guarantee"
    )
