from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "resume-context.py"
_HELPERS = _REPO_ROOT / "scripts" / "session-helpers.sh"


def _load_module():
    spec = importlib.util.spec_from_file_location("resume_context_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["resume_context_under_test"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()


def _done_hash(tasks: Path) -> str:
    result = subprocess.run(
        ["bash", str(_HELPERS), "done_set_hash", str(tasks)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()

def _score_total(item: dict) -> int:
    return sum(int(value) for value in item["components"].values()) + sum(
        int(negative.get("penalty", 0)) for negative in item["negative_evidence"]
    )




def _write_plan(base: Path, slug: str, *, valid_session: bool = True, valid_handoff: bool = True, link_session_context: bool = True) -> Path:
    plan = base / "plans" / slug
    plan.mkdir(parents=True)
    tasks = plan / "TASKS.md"
    tasks.write_text(
        "# TASKS\n\n"
        "## T001 — Done `[x]`\n"
        "**Depends on:** —\n\n"
        "## T002 — Next `[ ]`\n"
        "**Depends on:** —\n",
        encoding="utf-8",
    )
    done_hash = _done_hash(tasks)
    session_hash = done_hash if valid_session else "0" * 64
    (plan / "SESSION.md").write_text(
        "---\n"
        f"slug: {slug}\n"
        "schema_version: 1\n"
        "done_count: 1\n"
        f"done_ids_hash: {session_hash}\n"
        "last_gate_task_id: T001\n"
        "next_pending: T002\n"
        "generated_by: context-curator\n"
        "context_hash: abc\n"
        "---\n"
        "\n## Summary\nTest session.\n",
        encoding="utf-8",
    )
    (plan / "SESSION_CONTEXT.md").write_text("live context side evidence\n", encoding="utf-8")
    if valid_handoff:
        (plan / "handoff.json").write_text(
            json.dumps(
                {
                    "protocol_version": "1.1",
                    "timestamp": "2026-06-29T00:00:00Z",
                    "agent": "test",
                    "slug": slug,
                    "status": "context_pressure",
                    "next_step": "Resume test plan.",
                    "context_files": ([{"path": str(plan / "SESSION_CONTEXT.md"), "role": "session_log"}] if link_session_context else []),
                    "attend_resume": {
                        "expected_head_sha": "abc",
                        "expected_phase": "execute",
                        "done_set_hash": done_hash,
                        "dirty_state_fingerprint": "clean",
                        "session_id": "test-session",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        (plan / "handoff.json").write_text("{not json", encoding="utf-8")
    return plan


def _env(base: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["Z_HARNESS_BASE_DIR"] = str(base)
    env.pop("Z_HARNESS_PLANS_DIR", None)
    return env


def _forbid_report_context_load(monkeypatch) -> None:
    original_loader = _mod._load_script_module

    def guarded_loader(module_name: str, path: Path):
        if path.name == "report-context.py":
            raise AssertionError("report context is selection-gated")
        return original_loader(module_name, path)

    monkeypatch.setattr(_mod, "_load_script_module", guarded_loader)


def test_exact_shortcut_parser_separates_controls_report_flags_and_fuzzy_topic() -> None:
    args, expanded, raw_arguments = _mod._parse_args(
        [
            "--arguments",
            "plan:parser-resume repo:repo-one --topic 'parser contracts' "
            "--lookback 2w --report deep --profile technical --surface current",
        ]
    )

    assert raw_arguments is not None
    assert "plan:parser-resume" in expanded
    assert args.slug == "parser-resume"
    assert args.repo == "repo-one"
    assert args.lookback_days == 14
    assert args.report == "deep"
    assert args.query == ["parser contracts"]
    assert args.unknown_arguments == ["--profile", "technical", "--surface", "current"]
    assert args.interaction_mode == "interactive"

    fuzzy_args, _, _ = _mod._parse_args(["--topic", "parser contracts", "fuzzy", "words"])
    assert fuzzy_args.query == ["parser contracts", "fuzzy", "words"]

    try:
        _mod._parse_args(["slug:one-resume", "run:20260629T010203Z-run"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - parser.error must exit
        raise AssertionError("multiple exact target shortcuts must be rejected")


def test_packet_provider_allowlist_taxonomy_scores_and_citations_are_contractual(tmp_path: Path) -> None:
    base = tmp_path / "state"
    _write_plan(base, "contract-resume")

    packet = _mod.build_context(
        ["--slug", "contract-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["provider_allowlist"] == [
        "repo_identity",
        "target_resolution",
        "artifact_inventory",
        "plan_state",
        "git_log",
        "decisions",
        "context_json",
        "run_brief",
        "followup_evidence",
        "memory_evidence",
        "side_evidence_policy",
    ]
    taxonomy = packet["current_state_taxonomy"]
    assert taxonomy["primary_states"] == [
        "active",
        "paused",
        "blocked",
        "completed",
        "landed",
        "archived_only",
        "stale",
        "superseded",
        "dirty",
        "divergent",
        "unknown",
    ]
    assert {"followup", "memory", "subagent_judgment", "session_context", "human_handoff"}.issubset(
        set(taxonomy["side_evidence_only"])
    )
    weights = packet["score_components"]["component_weights"]
    assert weights["report_available"] == 5
    assert weights["degraded_evidence"] < 0
    assert weights["conflicting_or_stale_evidence"] < 0

    citation_ids = {item["citation_id"] for item in packet["citation_metadata"]}
    assert packet["selected_target"]["citation_ids"]
    assert set(packet["selected_target"]["citation_ids"]).issubset(citation_ids)
    for record in packet["evidence_records"]:
        if record.get("citation"):
            assert record["citation"] in citation_ids


def test_exact_slug_packet_contains_durable_schema_and_validated_sources(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "demo-resume")

    packet = _mod.build_context(
        ["--slug", "demo-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["schema_version"] == "resume-context.v1"
    for key in (
        "query",
        "raw_arguments",
        "parsed_arguments",
        "interaction_mode",
        "requested_report",
        "report_target",
        "repo_identity",
        "lookback",
        "source_status",
        "candidates",
        "evidence_records",
        "score_components",
        "negative_evidence",
        "state_flags",
        "state_reasons",
        "provider_allowlist",
        "recommendation_matrix",
        "current_state_taxonomy",
        "flags",
        "ambiguity",
        "selected_target",
        "subagent_request_policy",
        "subagent_requests",
        "subagent_judgments",
        "warnings",
        "citations",
        "citation_metadata",
        "suggested_continuations",
    ):
        assert key in packet
    assert packet["selected_target"]["slug"] == "demo-resume"
    assert packet["selected_target"]["selection_kind"] == "explicit"
    assert packet["ambiguity"]["state"] == "none"
    assert packet["source_status"]["plan_state"]["status"] in {"ok", "missing"}
    assert packet["subagent_request_policy"]["agent"] == "resume-cluster"
    assert packet["subagent_request_policy"]["max_default_calls"] == 2
    assert len(packet["subagent_requests"]) <= 2

    records = {record["type"]: record for record in packet["evidence_records"] if record.get("source", "").startswith(str(plan))}
    assert records["tasks"]["source_path"].endswith("TASKS.md")
    assert records["tasks"]["collected_at"]
    assert records["tasks"]["candidate_refs"]
    assert records["tasks"]["validation_status"] == "valid"
    assert records["session"]["validation_status"] == "valid"
    assert records["handoff"]["validation_status"] == "valid"
    assert records["session_context"]["side_evidence"] is True
    assert records["session_context"]["stale"] is False

    assert records["session_context"]["data"]["freshly_linked"] is True


def test_session_context_stale_when_not_freshly_linked(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "unlinked-resume", link_session_context=False)

    packet = _mod.build_context(
        ["--slug", "unlinked-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    records = {record["type"]: record for record in packet["evidence_records"] if record.get("source", "").startswith(str(plan))}
    assert records["handoff"]["validation_status"] == "valid"
    assert records["session_context"]["validation_status"] == "unvalidated"
    assert records["session_context"]["stale"] is True
    assert records["session_context"]["data"]["freshly_linked"] is False


def test_session_context_stale_when_linked_by_stale_handoff(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "stale-linked-resume")
    (plan / "handoff.json").write_text(
        json.dumps(
            {
                "protocol_version": "1.1",
                "timestamp": "2026-06-29T00:00:00Z",
                "agent": "test",
                "slug": "stale-linked-resume",
                "status": "context_pressure",
                "next_step": "Resume test plan.",
                "context_files": [{"path": str(plan / "SESSION_CONTEXT.md"), "role": "session_log"}],
                "attend_resume": {"done_set_hash": "0" * 64},
            }
        ),
        encoding="utf-8",
    )

    packet = _mod.build_context(
        ["--slug", "stale-linked-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    records = {record["type"]: record for record in packet["evidence_records"] if record.get("source", "").startswith(str(plan))}
    assert records["handoff"]["validation_status"] == "conflict"
    assert records["session_context"]["validation_status"] == "unvalidated"
    assert records["session_context"]["stale"] is True
    assert records["session_context"]["data"]["freshly_linked"] is False

def test_session_and_handoff_conflicts_degrade_explicitly(tmp_path: Path) -> None:
    base = tmp_path / "state"
    _write_plan(base, "bad-resume", valid_session=False, valid_handoff=False)

    packet = _mod.build_context(
        ["--slug", "bad-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["source_status"]["plan_state"]["degraded"] is True
    assert packet["flags"]["has_stale_evidence"] is True
    warnings = "\n".join(packet["warnings"])
    assert "SESSION.md done_ids_hash" in warnings
    assert "handoff.json malformed" in warnings

    session_records = [r for r in packet["evidence_records"] if r["type"] == "session"]
    handoff_records = [r for r in packet["evidence_records"] if r["type"] == "handoff"]
    assert session_records[0]["validation_status"] == "conflict"
    assert session_records[0]["stale"] is True
    assert handoff_records[0]["validation_status"] == "degraded"
    assert handoff_records[0]["degraded"] is True


def test_session_done_count_last_gate_and_next_pending_are_validated(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "session-fields-resume")
    text = (plan / "SESSION.md").read_text(encoding="utf-8")
    text = text.replace("done_count: 1", "done_count: 2")
    text = text.replace("last_gate_task_id: T001", "last_gate_task_id: T999")
    text = text.replace("next_pending: T002", "next_pending: T999")
    (plan / "SESSION.md").write_text(text, encoding="utf-8")

    packet = _mod.build_context(
        ["--slug", "session-fields-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    session = [r for r in packet["evidence_records"] if r["type"] == "session"][0]
    warnings = "\n".join(session["data"]["warnings"])
    assert session["validation_status"] == "conflict"
    assert session["stale"] is True
    assert "done_count" in warnings
    assert "last_gate_task_id" in warnings
    assert "next_pending" in warnings
    score = next(item for item in packet["score_components"]["candidate_scores"] if item["candidate_id"] == session["candidate_id"])
    assert "session_valid" not in score["components"]


def test_minimal_protocol_only_handoff_is_degraded_not_valid(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "minimal-handoff-resume")
    (plan / "handoff.json").write_text(json.dumps({"protocol_version": "1.1"}), encoding="utf-8")

    packet = _mod.build_context(
        ["--slug", "minimal-handoff-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    handoff = [r for r in packet["evidence_records"] if r["type"] == "handoff"][0]
    session_context = [r for r in packet["evidence_records"] if r["type"] == "session_context"][0]
    assert handoff["validation_status"] == "degraded"
    assert handoff["degraded"] is True
    score = next(item for item in packet["score_components"]["candidate_scores"] if item["candidate_id"] == handoff["candidate_id"])
    assert "handoff_valid" not in score["components"]
    assert session_context["validation_status"] == "unvalidated"
    assert session_context["data"]["freshly_linked"] is False


def test_ambiguity_and_recommendation_primitives_are_deterministic() -> None:
    seed = _mod.ContextSeed(
        argv=[],
        query="resume",
        raw_query_tokens=["resume"],
        args=SimpleNamespace(slug=None, run=None, select=None),
        repo_root=_REPO_ROOT,
        generated_at="2026-06-29T00:00:00Z",
        environ={},
    )
    c1 = _mod.Candidate(
        candidate_id="cand-a",
        slug="alpha-resume",
        repo_id="repo-a",
        score=50,
        confidence="medium",
        evidence_ids=["ev-a1", "ev-a2"],
        citation_ids=["cit-a"],
        current_state=_mod._state_from_status("unknown", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-a|slug:alpha-resume|repo:repo-a",
    )
    c2 = _mod.Candidate(
        candidate_id="cand-b",
        slug="beta-resume",
        repo_id="repo-b",
        score=45,
        confidence="medium",
        evidence_ids=["ev-b1", "ev-b2"],
        citation_ids=["cit-b"],
        current_state=_mod._state_from_status("unknown", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-b|slug:beta-resume|repo:repo-b",
    )

    ambiguity = _mod._ambiguity([c1, c2], seed)
    assert ambiguity["needs_selection"] is True
    assert "close_scores" in ambiguity["triggers"]
    assert "cross_repo_conflict" in ambiguity["triggers"]

    continuations = _mod._continuations(None, [c1, c2], ambiguity)
    assert [item["selection_token"] for item in continuations] == ["candidate:cand-a|slug:alpha-resume|repo:repo-a", "candidate:cand-b|slug:beta-resume|repo:repo-b"]
    assert all(item["kind"] == "select_target" for item in continuations)
    assert continuations[0]["command"] == "/z-resume --select 'candidate:cand-a|slug:alpha-resume|repo:repo-a'"
    assert continuations[1]["command"] == "/z-resume --select 'candidate:cand-b|slug:beta-resume|repo:repo-b'"



def test_explicit_slug_collision_requires_full_selection_token() -> None:
    seed = _mod.ContextSeed(
        argv=[],
        query="",
        raw_query_tokens=[],
        args=SimpleNamespace(slug="same-resume", run=None, select=None),
        repo_root=_REPO_ROOT,
        generated_at="2026-06-29T00:00:00Z",
        environ={},
    )
    candidates = [
        _mod.Candidate(
            candidate_id="cand-one",
            slug="same-resume",
            repo_id="repo-one",
            score=80,
            confidence="high",
            evidence_ids=["ev-one", "ev-one-b"],
            current_state=_mod._state_from_status("paused", active=False, degraded=False, archived_only=False),
            selection_token="candidate:cand-one|slug:same-resume|repo:repo-one",
        ),
        _mod.Candidate(
            candidate_id="cand-two",
            slug="same-resume",
            repo_id="repo-two",
            score=79,
            confidence="high",
            evidence_ids=["ev-two", "ev-two-b"],
            current_state=_mod._state_from_status("paused", active=False, degraded=False, archived_only=False),
            selection_token="candidate:cand-two|slug:same-resume|repo:repo-two",
        ),
    ]

    ambiguity = _mod._ambiguity(candidates, seed)
    assert ambiguity["needs_selection"] is True
    assert "explicit_collision" in ambiguity["triggers"]
    assert _mod._select_target(candidates, seed, ambiguity) is None

    seed.args.select = "candidate:cand-two|slug:same-resume|repo:repo-two"
    selected = _mod._select_target(candidates, seed, {"needs_selection": False})
    assert selected["candidate_id"] == "cand-two"


def test_exact_branch_and_worktree_targets_select_unique_candidate(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    candidate = _mod.Candidate(
        candidate_id="cand-branch",
        slug="branch-resume",
        repo_id="repo-one",
        branch="feature/branch-resume",
        worktree_path=str(worktree),
        score=80,
        confidence="high",
        evidence_ids=["ev-plan", "ev-worktree"],
        current_state=_mod._state_from_status("paused", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-branch|slug:branch-resume|repo:repo-one",
    )
    branch_seed = _mod.ContextSeed(
        argv=[],
        query="",
        raw_query_tokens=[],
        args=SimpleNamespace(slug=None, run=None, select=None, branch="feature/branch-resume", worktree=None, artifact=None),
        repo_root=_REPO_ROOT,
        generated_at="2026-06-29T00:00:00Z",
        environ={},
    )
    worktree_seed = _mod.ContextSeed(
        argv=[],
        query="",
        raw_query_tokens=[],
        args=SimpleNamespace(slug=None, run=None, select=None, branch=None, worktree=str(worktree), artifact=None),
        repo_root=_REPO_ROOT,
        generated_at="2026-06-29T00:00:00Z",
        environ={},
    )

    branch_ambiguity = _mod._ambiguity([candidate], branch_seed)
    worktree_ambiguity = _mod._ambiguity([candidate], worktree_seed)

    assert branch_ambiguity["needs_selection"] is False
    assert _mod._select_target([candidate], branch_seed, branch_ambiguity)["branch"] == "feature/branch-resume"
    assert worktree_ambiguity["needs_selection"] is False
    assert _mod._select_target([candidate], worktree_seed, worktree_ambiguity)["worktree_path"] == str(worktree)


def test_report_target_prefers_worktree_and_rejects_cross_repo_slug(tmp_path: Path) -> None:
    worktree = tmp_path / "selected-worktree"
    worktree.mkdir()
    current_repo = tmp_path / "current-repo"
    current_repo.mkdir()
    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()

    worktree_args, worktree_mode = _mod._selected_report_target_args(
        {
            "slug": "shared-resume",
            "repo_root": str(other_repo),
            "worktree_path": str(worktree),
        },
        current_repo_root=current_repo,
    )
    assert worktree_args == ["--worktree", str(worktree)]
    assert worktree_mode == "worktree"

    payload = _mod._report_target(
        {"slug": "shared-resume", "run_id": "20260629T000000Z-other", "repo_root": str(other_repo), "repo_id": "other-repo-id"},
        SimpleNamespace(report="summary", unknown_arguments=[], repo_root=str(current_repo)),
        {"needs_selection": False},
        current_repo_id="current-repo-id",
    )
    assert payload["status"] == "not_reportable"
    assert payload["target_args"] == []


def test_merge_preserves_worktree_state_and_collision_safe_tokens() -> None:
    plan_dir = "/tmp/z-harness/plans/merge-resume"
    base_state = _mod._state_from_status("paused", active=False, degraded=False, archived_only=False)
    worktree_state = _mod._state_from_status("paused", active=False, degraded=False, archived_only=False)
    worktree_state["flags"]["dirty"] = True
    worktree_state["flags"]["dirty_worktree"] = True
    worktree_state["flags"]["divergent"] = True
    worktree_state["flags"]["divergent_branch"] = True
    c1 = _mod.Candidate(
        candidate_id="cand-merge",
        slug="merge-resume",
        plan_dir=plan_dir,
        current_state=base_state,
        selection_token="candidate:cand-merge",
        score=10,
    )
    c2 = _mod.Candidate(
        candidate_id="cand-merge",
        slug="merge-resume",
        plan_dir=plan_dir,
        current_state=worktree_state,
        selection_token="candidate:cand-merge",
        score=20,
        score_components={"worktree_association": 20},
    )

    merged = _mod._merge_candidates([c1, c2], [])

    assert len(merged) == 1
    assert merged[0].selection_token == "candidate:cand-merge"
    assert merged[0].current_state["flags"]["dirty_worktree"] is True
    assert merged[0].current_state["flags"]["divergent_branch"] is True


def test_repo_qualifier_degrades_without_unbounded_scan(tmp_path: Path) -> None:
    base = tmp_path / "state"
    _write_plan(base, "repo-resume")

    packet = _mod.build_context(
        ["--slug", "repo-resume", "--repo", "other-repo-id", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["source_status"]["repo_identity"]["degraded"] is True
    repo_records = [r for r in packet["evidence_records"] if r["type"] == "repo_qualifier"]
    assert repo_records
    assert repo_records[0]["validation_status"] == "degraded"
    assert "other-repo-id" in repo_records[0]["source"]


def test_non_current_repo_path_does_not_use_current_plan_evidence(tmp_path: Path) -> None:
    base = tmp_path / "state"
    current_plan = _write_plan(base, "repo-resume")
    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()

    packet = _mod.build_context(
        ["--slug", "repo-resume", "--repo", str(other_repo), "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["selected_target"] is None or packet["selected_target"].get("slug") != "repo-resume"
    assert not [
        record
        for record in packet["evidence_records"]
        if record.get("source", "").startswith(str(current_plan))
        and record["type"] in {"tasks", "session", "session_context", "handoff", "human_handoff", "known_artifacts"}
    ]
    assert not [candidate for candidate in packet["candidates"] if str(candidate.get("plan_dir", "")).startswith(str(current_plan))]

def test_non_current_repo_slug_does_not_guess_in_repo_plan_dirs(tmp_path: Path) -> None:
    base = tmp_path / "state"
    other_repo = tmp_path / "other-repo"
    other_plan = _write_plan(other_repo / "z-harness", "repo-resume")

    packet = _mod.build_context(
        ["--slug", "repo-resume", "--repo", str(other_repo), "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["selected_target"] is None or packet["selected_target"].get("plan_dir") != str(other_plan)
    assert not [
        record
        for record in packet["evidence_records"]
        if str(record.get("source", "")).startswith(str(other_plan))
        and record["type"] in {"tasks", "session", "session_context", "handoff", "human_handoff", "known_artifacts"}
    ]
    assert not [candidate for candidate in packet["candidates"] if str(candidate.get("plan_dir", "")).startswith(str(other_plan))]
    assert any("plan path unresolved" in warning for warning in packet["warnings"])


def test_non_current_git_repo_uses_plan_path_base_not_in_repo_guess(tmp_path: Path) -> None:
    base = tmp_path / "state"
    external_plan = _write_plan(base, "repo-resume")
    other_repo = tmp_path / "other-git-repo"
    other_repo.mkdir()
    subprocess.run(["git", "init"], cwd=other_repo, check=True, capture_output=True, text=True)
    in_repo_guess = _write_plan(other_repo / "z-harness", "repo-resume")

    packet = _mod.build_context(
        ["--slug", "repo-resume", "--repo", str(other_repo), "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["selected_target"] is not None
    assert packet["selected_target"]["plan_dir"] == str(external_plan)
    typed_records = [
        record
        for record in packet["evidence_records"]
        if str(record.get("source", "")).startswith(str(external_plan))
        and record["type"] in {"tasks", "session", "handoff", "known_artifacts"}
    ]
    assert {record["type"] for record in typed_records} >= {"tasks", "session", "handoff", "known_artifacts"}
    assert not [
        record
        for record in packet["evidence_records"]
        if str(record.get("source", "")).startswith(str(in_repo_guess))
        and record["type"] in {"tasks", "session", "session_context", "handoff", "human_handoff", "known_artifacts"}
    ]


def test_fuzzy_current_repo_discovery_gets_typed_plan_validation(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "fuzzy-resume-topic")

    packet = _mod.build_context(
        ["fuzzy", "resume", "topic", "--repo-root", str(_REPO_ROOT), "--max-candidates", "20"],
        environ=_env(base),
    )
    plan_prefix = _mod._safe_resolve(plan)
    typed_records = [
        record
        for record in packet["evidence_records"]
        if (_mod._safe_resolve(record.get("source", "")) or "").startswith(str(plan_prefix))
        and record["type"] in {"tasks", "session", "session_context", "handoff", "human_handoff", "known_artifacts"}
    ]
    assert {record["type"] for record in typed_records} >= {"tasks", "session", "session_context", "handoff", "known_artifacts"}
    assert [candidate for candidate in packet["candidates"] if candidate.get("slug") == "fuzzy-resume-topic"]


def test_git_provider_emits_typed_branch_evidence(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_run(argv, *, cwd=None, environ=None, timeout=10):
        if argv[:3] == ["git", "rev-parse", "--short=12"]:
            return 0, "abc123def456", ""
        if argv[:3] == ["git", "branch", "--show-current"]:
            return 0, "feature/resume-branch", ""
        if argv[:2] == ["git", "log"]:
            return 0, "abc123def456\tresume branch work", ""
        return 1, "", "unexpected command"

    monkeypatch.setattr(_mod, "_run", fake_run)
    seed = _mod.ContextSeed(
        argv=[],
        query="resume",
        raw_query_tokens=["resume"],
        args=SimpleNamespace(repo=None, all_repos=False, max_candidates=5, branch=None),
        repo_root=repo_root,
        generated_at="2026-06-29T00:00:00Z",
        environ={},
        repo_id="repo-one",
        repo_sources=[{"repo_id": "repo-one", "repo_root": str(repo_root), "repo_name": "repo", "current_repo": True, "source": "current"}],
    )

    result = _mod.GitLogProvider().collect(seed)

    branch_records = [record for record in result.records if record.evidence_type == "branch"]
    assert branch_records
    assert branch_records[0].source == "feature/resume-branch"
    assert branch_records[0].data["repo_id"] == "repo-one"

def test_hermes_branch_exact_selection_derives_worktree_candidate(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "registry-conflict-resume")
    worktree = tmp_path / "registry-conflict-resume"
    worktree.mkdir()
    branch = "hermes/registry-conflict-resume/T004"

    class FakeInventory:
        @staticmethod
        def collect_inventory(**kwargs):
            return {
                "source_status": {"plans": "missing", "archives": "missing", "registry": "missing", "worktrees": "ok"},
                "truncated": False,
                "signals": {},
                "dropped_counts": {},
                "mandatory_candidates": [],
                "historical_candidates": [],
                "active_records": [],
                "worktrees": [{"path": str(worktree), "branch": branch, "head": "abc123"}],
            }

    monkeypatch.setattr(_mod, "_artifact_inventory", lambda: FakeInventory)
    monkeypatch.setattr(_mod, "_worktree_state", lambda path: {"dirty": False, "divergent": False, "landed": False, "warnings": []})

    packet = _mod.build_context(
        ["--branch", branch, "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert plan.is_dir()
    worktree_candidate = next(candidate for candidate in packet["candidates"] if candidate["slug"] == "registry-conflict-resume")
    assert worktree_candidate["branch"] == branch
    assert worktree_candidate["worktree_path"] == str(worktree)
    assert worktree_candidate["score_components"]["branch_worktree_hint"] == 10


def test_hermes_worktree_path_exact_selection_derives_worktree_candidate(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "registry-conflict-resume")
    worktree = tmp_path / "hermes" / "registry-conflict-resume" / "T004"
    worktree.mkdir(parents=True)

    class FakeInventory:
        @staticmethod
        def collect_inventory(**kwargs):
            return {
                "source_status": {"plans": "missing", "archives": "missing", "registry": "missing", "worktrees": "ok"},
                "truncated": False,
                "signals": {},
                "dropped_counts": {},
                "mandatory_candidates": [],
                "historical_candidates": [],
                "active_records": [],
                "worktrees": [{"path": str(worktree), "branch": "", "head": "abc123"}],
            }

    monkeypatch.setattr(_mod, "_artifact_inventory", lambda: FakeInventory)
    monkeypatch.setattr(_mod, "_worktree_state", lambda path: {"dirty": False, "divergent": False, "landed": False, "warnings": []})

    packet = _mod.build_context(
        ["--worktree", str(worktree), "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert plan.is_dir()
    worktree_candidate = next(candidate for candidate in packet["candidates"] if candidate["slug"] == "registry-conflict-resume")
    assert worktree_candidate["worktree_path"] == str(worktree)
    assert worktree_candidate["repo_root"] == str(_REPO_ROOT)
    assert worktree_candidate["score_components"]["worktree_association"] == 20


def test_repo_root_matches_require_repo_id_and_do_not_use_worktree_index() -> None:
    candidate = _mod.Candidate(
        candidate_id="cand-repo-root",
        slug="repo-root-resume",
        repo_id="repo-one",
        repo_root="/tmp/shared-repo",
        current_state=_mod._state_from_status("paused", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-repo-root",
    )
    worktree_candidate = _mod.Candidate(
        candidate_id="cand-worktree",
        slug="worktree-resume",
        repo_id="repo-one",
        repo_root="/tmp/shared-repo",
        worktree_path="/tmp/shared-repo-worktree",
        status="worktree",
        score_components={"worktree_association": 20},
        current_state=_mod._state_from_status("paused", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-worktree",
    )
    mismatched_repo_record = _mod.EvidenceRecord(
        evidence_id="ev-git-other-repo",
        evidence_type="git_log",
        provider="git_log",
        source="main",
        status="ok",
        validation_status="valid",
        data={"repo_root": "/tmp/shared-repo", "repo_id": "repo-two", "entries": ["abc\tother repo"]},
    )
    root_only_record = _mod.EvidenceRecord(
        evidence_id="ev-git-root-only",
        evidence_type="git_log",
        provider="git_log",
        source="main",
        status="ok",
        validation_status="valid",
        data={"repo_root": "/tmp/shared-repo", "entries": ["def\troot only"]},
    )
    matching_worktree_repo_root_record = _mod.EvidenceRecord(
        evidence_id="ev-git-worktree-root",
        evidence_type="git_log",
        provider="git_log",
        source="main",
        status="ok",
        validation_status="valid",
        data={"repo_root": "/tmp/shared-repo-worktree", "repo_id": "repo-one", "entries": ["fed\tworktree root"]},
    )

    merged = _mod._merge_candidates([candidate, worktree_candidate], [mismatched_repo_record, root_only_record, matching_worktree_repo_root_record])

    assert mismatched_repo_record.candidate_id is None
    assert root_only_record.candidate_id is None
    assert matching_worktree_repo_root_record.candidate_id is None
    by_id = {item.candidate_id: item for item in merged}
    assert "ev-git-other-repo" not in by_id["cand-repo-root"].evidence_ids
    assert "ev-git-root-only" not in by_id["cand-repo-root"].evidence_ids
    assert "ev-git-worktree-root" not in by_id["cand-worktree"].evidence_ids


def test_ranking_score_reconciles_with_exposed_components_and_penalties() -> None:
    candidate = _mod.Candidate(
        candidate_id="cand-score",
        slug="score-resume",
        repo_id="repo-one",
        score=55,
        score_components={"active_registry": 40, "registry_branch_worktree": 15},
        evidence_ids=["ev-seed"],
        current_state=_mod._state_from_status("active", active=True, degraded=False, archived_only=False),
        selection_token="candidate:cand-score",
    )
    active_record = _mod.EvidenceRecord(
        evidence_id="ev-active",
        evidence_type="active_registry",
        provider="artifact_inventory",
        source="active-plan-registry.py list --json",
        status="active",
        validation_status="valid",
        candidate_id="cand-score",
    )
    stale_record = _mod.EvidenceRecord(
        evidence_id="ev-stale-session",
        evidence_type="session",
        provider="plan_state",
        source="/tmp/plan/SESSION.md",
        status="stale",
        validation_status="stale",
        candidate_id="cand-score",
    )

    merged = _mod._merge_candidates([candidate], [active_record, stale_record])
    score_item = {
        "components": merged[0].score_components,
        "negative_evidence": merged[0].negative_evidence,
    }

    assert merged[0].score_components["active_registry"] == 80
    assert all(value >= 0 for value in merged[0].score_components.values())
    assert merged[0].score == _score_total(score_item)



def test_active_registry_state_is_not_overwritten_by_tasks() -> None:
    tasks_record = _mod.EvidenceRecord(
        evidence_id="ev-tasks-complete",
        evidence_type="tasks",
        provider="plan_state",
        source="/tmp/plan/TASKS.md",
        status="completed",
        validation_status="valid",
        data={"status_counts": {"done": 2, "pending": 0, "in_progress": 0, "other": 0}},
    )
    active_record = _mod.EvidenceRecord(
        evidence_id="ev-active",
        evidence_type="active_registry",
        provider="artifact_inventory",
        source="active-plan-registry.py list --json",
        status="active",
        validation_status="valid",
    )
    after_active = _mod.Candidate(
        candidate_id="cand-active",
        slug="active-resume",
        current_state=_mod._state_from_status("unknown", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-active",
    )
    _mod._apply_record_to_candidate(after_active, active_record)
    _mod._apply_record_to_candidate(after_active, tasks_record)

    after_tasks = _mod.Candidate(
        candidate_id="cand-active",
        slug="active-resume",
        current_state=_mod._state_from_status("unknown", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-active",
    )
    _mod._apply_record_to_candidate(after_tasks, tasks_record)
    _mod._apply_record_to_candidate(after_tasks, active_record)

    assert after_active.current_state["primary"] == "active"
    assert after_tasks.current_state["primary"] == "active"
    assert after_active.current_state["flags"]["completed_tasks"] is True


def test_git_log_associates_by_branch_and_head_hints() -> None:
    candidate = _mod.Candidate(
        candidate_id="cand-branch",
        slug="branch-resume",
        repo_id="repo-one",
        branch="feature/branch-resume",
        head="abc123",
        current_state=_mod._state_from_status("paused", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-branch",
    )
    record = _mod.EvidenceRecord(
        evidence_id="ev-git-log",
        evidence_type="git_log",
        provider="git_log",
        source="feature/branch-resume",
        status="ok",
        validation_status="valid",
        data={"branch": "feature/branch-resume", "head": "abc123", "entries": ["abc123\tbranch work"]},
    )

    merged = _mod._merge_candidates([candidate], [record])

    assert len(merged) == 1
    assert record.candidate_id == "cand-branch"
    assert "ev-git-log" in merged[0].evidence_ids

def test_git_log_associates_by_commit_subject_alias() -> None:
    candidate = _mod.Candidate(
        candidate_id="cand-subject",
        slug="git-subject-resume",
        repo_id="repo-one",
        branch="feature/unrelated",
        head="abc123",
        current_state=_mod._state_from_status("paused", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-subject",
    )
    record = _mod.EvidenceRecord(
        evidence_id="ev-git-log-subject",
        evidence_type="git_log",
        provider="git_log",
        source="main",
        status="ok",
        validation_status="valid",
        data={
            "branch": "main",
            "head": "def456",
            "repo_id": "repo-one",
            "entries": ["def456\tcontinue git subject resume implementation"],
        },
    )

    merged = _mod._merge_candidates([candidate], [record])

    assert len(merged) == 1
    assert record.candidate_id == "cand-subject"
    assert "ev-git-log-subject" in merged[0].evidence_ids



def test_followups_and_memories_are_typed_side_evidence_with_real_sources(tmp_path: Path) -> None:
    base = tmp_path / "state"
    followups = base / "followups"
    followups.mkdir(parents=True)
    (followups / "index.view.json").write_text(
        json.dumps(
            {
                "entries": {
                    "fu1": {
                        "id": "fu1",
                        "name": "resume-context followup",
                        "status": "open",
                        "capture_head": "abc123",
                        "cited_paths": ["scripts/resume-context.py"],
                        "source_artifact": "TASKS.md",
                        "status_history": [{"ts": "2026-06-29T00:00:00Z", "to": "open"}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    repo_root = tmp_path / "repo"
    docs = repo_root / "docs" / "llm"
    docs.mkdir(parents=True)
    (docs / "MEMORIES-FLAT.md").write_text("- resume-context memory: keep side evidence bounded\n", encoding="utf-8")
    seed = _mod.ContextSeed(
        argv=[],
        query="resume-context",
        raw_query_tokens=["resume-context"],
        args=SimpleNamespace(slug="resume-context", run=None, branch=None, repo=None, all_repos=False, max_candidates=5),
        repo_root=repo_root,
        generated_at="2026-06-29T00:00:00Z",
        environ={"HOME": str(tmp_path / "home")},
        base_dir=str(base),
    )

    result = _mod.SideEvidenceProvider().collect(seed)
    followup_records = [record for record in result.records if record.evidence_type == "followup"]
    memory_records = [record for record in result.records if record.evidence_type == "memory"]

    assert followup_records and followup_records[0].source.endswith("index.view.json")
    assert followup_records[0].validation_status == "unvalidated"
    assert followup_records[0].side_evidence is True
    assert followup_records[0].data["current_state_proof"] is False
    assert memory_records and memory_records[0].source.endswith("MEMORIES-FLAT.md")
    assert memory_records[0].data["current_state_proof"] is False


def test_cli_writes_machine_readable_packet_to_stdout_only(tmp_path: Path, capsys) -> None:
    base = tmp_path / "state"
    _write_plan(base, "cli-resume")
    out = tmp_path / "packet.json"

    rc = _mod.main(
        ["--slug", "cli-resume", "--repo-root", str(_REPO_ROOT), "--json"],
        environ=_env(base),
    )

    assert rc == 0
    assert not out.exists()
    packet = json.loads(capsys.readouterr().out)
    assert packet["schema_version"] == "resume-context.v1"
    assert packet["selected_target"]["slug"] == "cli-resume"


def test_cli_default_renders_concise_human_sections(tmp_path: Path, capsys) -> None:
    base = tmp_path / "state"
    _write_plan(base, "human-resume")
    out = tmp_path / "packet.json"

    rc = _mod.main(
        ["--slug", "human-resume", "--repo-root", str(_REPO_ROOT)],
        environ=_env(base),
    )

    assert rc == 0
    assert not out.exists()
    rendered = capsys.readouterr().out
    assert "Resume target: human-resume" in rendered
    assert "Latest consensus" in rendered
    assert "Open ambiguity" in rendered
    assert "Stale/superseded/degraded evidence" in rendered
    assert "Recommendations" in rendered
    assert "[cit-" in rendered


def test_noninteractive_ambiguity_emits_structured_packet(monkeypatch, capsys) -> None:
    packet = {
        "schema_version": "resume-context.v1",
        "status": "needs_selection",
        "ambiguity": {"state": "needs_selection", "needs_selection": True, "triggers": ["close_scores"]},
        "selected_target": None,
        "candidates": [{"candidate_id": "cand-a", "slug": "alpha-resume", "selection_token": "candidate:cand-a|slug:alpha-resume"}],
        "suggested_continuations": [],
    }
    monkeypatch.setattr(_mod, "build_context", lambda argv, environ=None: packet)

    rc = _mod.main(["alpha", "--noninteractive"], environ={})

    assert rc == 0
    stdout_packet = json.loads(capsys.readouterr().out)
    assert stdout_packet["status"] == "needs_selection"
    assert stdout_packet["selected_target"] is None


def test_noninteractive_report_ambiguity_stops_with_needs_selection(monkeypatch, capsys) -> None:
    packet = {
        "schema_version": "resume-context.v1",
        "status": "needs_selection",
        "interaction_mode": "noninteractive",
        "requested_report": {"requested": True, "tier": "standard", "forwarded_args": []},
        "report_target": {"requested": True, "status": "needs_selection", "target_args": []},
        "ambiguity": {"state": "needs_selection", "needs_selection": True, "triggers": ["close_scores"]},
        "selected_target": None,
        "candidates": [{"candidate_id": "cand-a", "slug": "alpha-resume", "selection_token": "candidate:cand-a|slug:alpha-resume"}],
        "suggested_continuations": [],
    }
    monkeypatch.setattr(_mod, "build_context", lambda argv, environ=None: packet)

    def fail_report_entrypoint(*args, **kwargs):
        raise AssertionError("ambiguous --report reached report rendering")

    monkeypatch.setattr(_mod, "_prepare_report_handoff", fail_report_entrypoint)
    monkeypatch.setattr(_mod, "_render_human_packet", fail_report_entrypoint)
    _forbid_report_context_load(monkeypatch)

    def fail_report_side_command(argv, *, cwd=None, environ=None, timeout=10):
        command_text = " ".join(str(part) for part in argv)
        forbidden = ("z-report", "report-context.py", "report-synth", "render-run-brief.py")
        assert all(entry not in command_text for entry in forbidden)
        return (0, "", "")

    monkeypatch.setattr(_mod, "_run", fail_report_side_command)

    rc = _mod.main(["alpha", "--noninteractive", "--report"], environ={})

    assert rc == 0
    stdout_packet = json.loads(capsys.readouterr().out)
    assert stdout_packet["status"] == "needs_selection"
    assert stdout_packet["selected_target"] is None
    assert stdout_packet["report_target"]["status"] == "needs_selection"


def test_report_handoff_rejects_needs_selection_without_persistence(tmp_path: Path) -> None:
    packet = {
        "schema_version": "resume-context.v1",
        "status": "needs_selection",
        "requested_report": {"requested": True, "tier": "summary", "forwarded_args": []},
        "report_target": {"requested": True, "status": "needs_selection", "target_args": []},
        "ambiguity": {"state": "needs_selection", "needs_selection": True},
        "selected_target": None,
    }
    selected_packet_path = tmp_path / "must-not-exist.json"

    handoff = _mod._prepare_report_handoff(packet, selected_packet_path)

    assert handoff["status"] == "needs_selection"
    assert handoff["should_render"] is False
    assert not selected_packet_path.exists()


def test_z_resume_skill_report_handoff_uses_selected_context_env() -> None:
    skill_text = (_REPO_ROOT / "skills" / "z-resume" / "SKILL.md").read_text(encoding="utf-8")

    assert "export its path as `SELECTED_RESUME_CONTEXT_PATH`" in skill_text
    assert '--resume-context "$SELECTED_RESUME_CONTEXT_PATH"' in skill_text
    assert "Ambiguous `--report` in noninteractive mode" in skill_text
    assert "stops before any `report-context.py`, `report-synth`, or inline report-rendering branch runs" in skill_text



def test_unknown_flags_fail_without_report_and_forward_with_report(tmp_path: Path) -> None:
    base = tmp_path / "state"
    _write_plan(base, "flags-resume")

    assert _mod.main(["--slug", "flags-resume", "--unknown-flag", "--repo-root", str(_REPO_ROOT)], environ=_env(base)) == 2

    packet = _mod.build_context(
        ["--slug", "flags-resume", "--report", "summary", "--profile", "ops", "--repo-root", str(_REPO_ROOT)],
        environ=_env(base),
    )

    assert packet["requested_report"]["forwarded_args"] == ["--profile", "ops"]
    assert packet["selected_target"]["slug"] == "flags-resume"
    assert packet["report_target"]["status"] == "ready"
    assert packet["report_target"]["target_args"] == ["--slug", "flags-resume"]
    assert packet["report_target"]["forwarded_args"] == ["--profile", "ops"]

def test_fuzzy_noninteractive_does_not_invoke_report_context(monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "state"
    _write_plan(base, "fuzzy-resume")
    _forbid_report_context_load(monkeypatch)

    packet = _mod.build_context(
        ["fuzzy resume", "--noninteractive", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["interaction_mode"] == "noninteractive"
    assert packet["selected_target"] is None or packet["status"] == "selected"


def test_exact_slug_and_run_gathering_do_not_call_report_context(monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "gated-report-context")
    run_dir = plan / "archive" / "20260629T030405Z-run"
    run_dir.mkdir(parents=True)
    (run_dir / "context.json").write_text(json.dumps({"status": "ok", "slug": "gated-report-context"}), encoding="utf-8")
    (run_dir / "run-brief.json").write_text(json.dumps({"status": "ok", "outcome": "done"}), encoding="utf-8")
    _forbid_report_context_load(monkeypatch)

    slug_packet = _mod.build_context(
        ["--slug", "gated-report-context", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )
    run_packet = _mod.build_context(
        ["--run", run_dir.name, "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )
    slug_report_packet = _mod.build_context(
        ["--slug", "gated-report-context", "--report", "summary", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )
    run_report_packet = _mod.build_context(
        ["--run", run_dir.name, "--report", "summary", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    for packet in (slug_packet, run_packet, slug_report_packet, run_report_packet):
        assert "report_context" not in packet["provider_allowlist"]
    assert slug_packet["query"]["target_descriptor"]["slug"] == "gated-report-context"
    assert run_packet["query"]["target_descriptor"]["run_id"] == run_dir.name
    assert slug_report_packet["report_target"]["target_args"] == ["--run", run_dir.name]
    assert run_report_packet["report_target"]["target_args"] == ["--run", run_dir.name]


def test_e2e_fuzzy_ambiguity_selection_and_report_handoff_keep_cited_resume_context(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    base = repo_root
    branch_slug = "resume-recovery-branch"
    handoff_slug = "resume-recovery-handoff"
    branch_plan = _write_plan(base, branch_slug)
    handoff_plan = _write_plan(base, handoff_slug)
    for name in ("SESSION.md", "SESSION_CONTEXT.md", "handoff.json"):
        (branch_plan / name).unlink()
    branch_worktree = tmp_path / "hermes" / branch_slug / "T011"
    branch_worktree.mkdir(parents=True)
    old_run_id = "20250101T000000Z-canonical"
    old_run_dir = handoff_plan / "archive" / old_run_id
    old_run_dir.mkdir(parents=True)
    (old_run_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "ts": "2025-01-01T00:00:00Z",
                "run": old_run_id,
                "kind": "decision",
                "decision": "Canonical recovery path preserves report handoff evidence.",
                "slug": handoff_slug,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeInventory:
        @staticmethod
        def collect_inventory(**kwargs):
            return {
                "source_status": {"plans": "ok", "archives": "ok", "registry": "missing", "worktrees": "ok"},
                "truncated": False,
                "signals": {},
                "dropped_counts": {},
                "mandatory_candidates": [],
                "historical_candidates": [
                    {
                        "slug": branch_slug,
                        "path": str(branch_plan),
                        "score": 35,
                        "basis": ["fuzzy_topic"],
                        "status": "paused",
                        "updated_at": "2026-06-28T00:00:00Z",
                        "source_status": {"tasks": "ok", "worktree": "ok"},
                        "summary_excerpt": "Recent recovery smoke work with branch and worktree evidence.",
                    },
                    {
                        "slug": handoff_slug,
                        "path": str(handoff_plan),
                        "score": 20,
                        "basis": ["fuzzy_topic"],
                        "status": "paused",
                        "updated_at": "2026-06-28T00:00:00Z",
                        "source_status": {"tasks": "ok", "session": "ok", "handoff": "ok", "archive": "ok"},
                        "summary_excerpt": "Recent recovery smoke work with handoff and session evidence.",
                    },
                ],
                "active_records": [],
                "worktrees": [
                    {
                        "path": str(branch_worktree),
                        "branch": f"hermes/{branch_slug}/T011",
                        "head": "abc123def456",
                    }
                ],
            }

    monkeypatch.setattr(_mod, "_artifact_inventory", lambda: FakeInventory)
    monkeypatch.setattr(_mod, "_worktree_state", lambda path: {"dirty": False, "divergent": False, "landed": False, "warnings": []})
    original_run = _mod._run
    allowed_bash_scripts = {"plan-path.sh", "session-helpers.sh"}
    forbidden_dispatches = (
        "/z-execute",
        "/z-implement",
        "/z-plan",
        "/z-fix",
        "/z-debug",
        "/z-attend",
        "/z-overnight",
        "qtctl",
        "restart",
        "backfill",
        "migration",
        "migrate",
        "report-context.py",
        "report-synth",
        "render-run-brief.py",
        "subagent",
    )

    def guarded_run(argv, *, cwd=None, environ=None, timeout=10):
        parts = [str(part) for part in argv]
        command_text = " ".join(parts)
        lower_command_text = command_text.lower()
        assert all(dispatch not in lower_command_text for dispatch in forbidden_dispatches)
        executable = Path(parts[0]).name if parts else ""
        if executable == "bash" and len(parts) > 1:
            assert Path(parts[1]).name in allowed_bash_scripts
        else:
            assert executable == "git"
        return original_run(argv, cwd=cwd, environ=environ, timeout=timeout)

    monkeypatch.setattr(_mod, "_run", guarded_run)

    with monkeypatch.context() as guarded:
        _forbid_report_context_load(guarded)
        ambiguous = _mod.build_context(
            ["resume recovery smoke", "--noninteractive", "--report", "summary", "--repo-root", str(repo_root), "--max-candidates", "5"],
            environ=_env(base),
        )

    assert ambiguous["status"] == "needs_selection"
    assert ambiguous["selected_target"] is None
    assert ambiguous["report_target"]["status"] == "needs_selection"
    assert "close_scores" in ambiguous["ambiguity"]["triggers"]
    assert {candidate["slug"] for candidate in ambiguous["candidates"][:2]} == {branch_slug, handoff_slug}
    branch_candidate = next(candidate for candidate in ambiguous["candidates"] if candidate["slug"] == branch_slug)
    assert branch_candidate["branch"] == f"hermes/{branch_slug}/T011"
    assert branch_candidate["worktree_path"] == str(branch_worktree)

    handoff_candidate = next(candidate for candidate in ambiguous["candidates"] if candidate["slug"] == handoff_slug)
    selected = _mod.build_context(
        [
            "resume recovery smoke",
            "--select",
            handoff_candidate["selection_token"],
            "--noninteractive",
            "--report",
            "summary",
            "--repo-root",
            str(repo_root),
            "--max-candidates",
            "5",
        ],
        environ=_env(base),
    )

    assert selected["status"] == "selected"
    assert selected["ambiguity"]["state"] == "none"
    assert selected["selected_target"]["slug"] == handoff_slug
    assert selected["selected_target"]["selection_kind"] == "explicit"
    assert selected["report_target"]["status"] == "ready"
    assert selected["report_target"]["target_args"] == ["--run", old_run_id]
    selected_records = {
        record["evidence_id"]: record
        for record in selected["evidence_records"]
        if record.get("evidence_id") in selected["selected_target"]["evidence_ids"]
    }
    selected_types = {record["type"] for record in selected_records.values()}
    assert {"session", "handoff", "decisions"}.issubset(selected_types)
    decision_record = next(record for record in selected_records.values() if record["type"] == "decisions")
    assert decision_record["data"]["run_id"] == old_run_id
    selected_score = next(
        item for item in selected["score_components"]["candidate_scores"]
        if item["candidate_id"] == selected["selected_target"]["candidate_id"]
    )
    assert any(item["reason"] == "recency_decay_capped_for_canonical_decisions" for item in selected_score["negative_evidence"])

    rendered = _mod._render_human_packet(selected)
    assert f"Resume target: {handoff_slug}" in rendered
    assert "Latest consensus" in rendered
    assert "Recommendations" in rendered

    handoff = _mod._prepare_report_handoff(
        selected,
        tmp_path / "selected-resume-context.json",
        environ={"EXISTING_ENV": "kept"},
    )
    assert handoff["status"] == "ready"
    assert handoff["environment"]["EXISTING_ENV"] == "kept"
    resume_packet_path = Path(handoff["environment"]["SELECTED_RESUME_CONTEXT_PATH"])
    assert resume_packet_path == tmp_path / "selected-resume-context.json"
    assert json.loads(resume_packet_path.read_text(encoding="utf-8"))["selected_target"]["slug"] == handoff_slug
    report_context_args = handoff["report_context_args"]
    assert report_context_args == ["--run", old_run_id, "--resume-context", str(resume_packet_path)]
    assert handoff["render_source"] == "context.json:selected_resume_context"
    report_mod = _mod._load_script_module("report_context_t011", _REPO_ROOT / "scripts" / "report-context.py")
    out_path = tmp_path / "context.json"

    def guarded_report_command(cmd, *, cwd=None):
        command_text = " ".join(str(part) for part in cmd).lower()
        assert all(dispatch not in command_text for dispatch in forbidden_dispatches)
        return (0, "", "")

    with (
        patch.object(report_mod, "_resolve_run_dir", return_value=old_run_dir),
        patch.object(report_mod, "_classify_status", return_value="clean"),
        patch.object(report_mod, "_resolve_followups", return_value=[]),
        patch.object(report_mod, "_estimate_cost", return_value={}),
        patch.object(report_mod, "_run_cmd_capture", side_effect=guarded_report_command),
    ):
        rc = report_mod.main([*report_context_args, "--out", str(out_path)])

    assert rc == 0
    bundle = json.loads(out_path.read_text(encoding="utf-8"))
    handoff = bundle["selected_resume_context"]
    assert bundle["selected_resume_context_status"] == "attached"
    assert handoff["query"]["text"] == "resume recovery smoke"
    assert handoff["report_target"]["target_args"] == selected["report_target"]["target_args"]
    assert handoff["selected_target"]["selection_token"] == selected["selected_target"]["selection_token"]
    assert {record["type"] for record in handoff["selected_evidence"]} >= {"session", "handoff", "decisions"}
    assert {record.get("candidate_id") for record in handoff["selected_evidence"]} == {selected["selected_target"]["candidate_id"]}

    def render_from_context_json(context_path: Path) -> str:
        assembled = json.loads(context_path.read_text(encoding="utf-8"))
        selected_resume_context = assembled.get("selected_resume_context")
        assert assembled.get("selected_resume_context_status") == "attached"
        assert isinstance(selected_resume_context, dict)
        selected_evidence = selected_resume_context["selected_evidence"]
        assert {record.get("candidate_id") for record in selected_evidence} == {selected["selected_target"]["candidate_id"]}
        return selected_resume_context["selected_target"]["selection_token"]

    assert render_from_context_json(out_path) == selected["selected_target"]["selection_token"]


def test_interactive_ambiguity_renders_one_selection_question(monkeypatch, capsys) -> None:
    packet = {
        "schema_version": "resume-context.v1",
        "status": "needs_selection",
        "ambiguity": {"state": "needs_selection", "needs_selection": True, "triggers": ["close_scores"]},
        "selected_target": None,
        "candidates": [
            {
                "candidate_id": "cand-a",
                "slug": "alpha-resume",
                "selection_token": "candidate:cand-a|slug:alpha-resume",
                "confidence": "medium",
                "score": 50,
                "repo_id": "repo-one",
                "branch": "feature/alpha",
                "citation_ids": ["cit-a"],
                "score_components": {"artifact_inventory": 40},
                "current_state": {"primary": "paused", "flags": {}},
            }
        ],
        "suggested_continuations": [
            {"command": "/z-resume --select 'candidate:cand-a|slug:alpha-resume'", "reason": "select", "citation_ids": ["cit-a"]}
        ],
    }
    monkeypatch.setattr(_mod, "build_context", lambda argv, environ=None: packet)

    rc = _mod.main(["alpha"], environ={})

    assert rc == 0
    rendered = capsys.readouterr().out
    assert rendered.count("Which target should /z-resume use?") == 1
    assert "candidate:cand-a|slug:alpha-resume" in rendered
    assert "Latest consensus" not in rendered


def test_interactive_report_ambiguity_asks_selection_before_rendering(monkeypatch, capsys) -> None:
    packet = {
        "schema_version": "resume-context.v1",
        "status": "needs_selection",
        "interaction_mode": "interactive",
        "requested_report": {"requested": True, "tier": "standard", "forwarded_args": []},
        "report_target": {"requested": True, "status": "needs_selection", "target_args": []},
        "ambiguity": {"state": "needs_selection", "needs_selection": True, "triggers": ["close_scores"]},
        "selected_target": None,
        "candidates": [
            {
                "candidate_id": "cand-a",
                "slug": "alpha-resume",
                "selection_token": "candidate:cand-a|slug:alpha-resume",
                "confidence": "medium",
                "score": 50,
                "repo_id": "repo-one",
                "citation_ids": ["cit-a"],
                "score_components": {"artifact_inventory": 40},
                "current_state": {"primary": "paused", "flags": {}},
            }
        ],
        "suggested_continuations": [],
    }
    monkeypatch.setattr(_mod, "build_context", lambda argv, environ=None: packet)

    rc = _mod.main(["alpha", "--report"], environ={})

    assert rc == 0
    rendered = capsys.readouterr().out
    assert "Which target should /z-resume use?" in rendered
    assert "Latest consensus" not in rendered
    assert "NOTE: degraded deterministic fallback" not in rendered


def test_arguments_string_and_report_request_are_preserved(tmp_path: Path) -> None:
    base = tmp_path / "state"
    _write_plan(base, "args-resume")

    packet = _mod.build_context(
        ["--arguments", "--slug args-resume --lookback 2w --json --report summary", "--repo-root", str(_REPO_ROOT)],
        environ=_env(base),
    )

    assert packet["raw_arguments"][0] == "--arguments"
    assert packet["parsed_arguments"]["expanded_arguments"][:2] == ["--slug", "args-resume"]
    assert packet["lookback"]["days"] == 14
    assert packet["interaction_mode"] == "noninteractive"
    assert packet["requested_report"] == {"requested": True, "tier": "summary", "forwarded_args": []}
    assert packet["selected_target"]["slug"] == "args-resume"


def test_prefixed_exact_plan_target_selects_deterministically(tmp_path: Path) -> None:
    base = tmp_path / "state"
    _write_plan(base, "prefixed-resume")

    packet = _mod.build_context(
        ["plan:prefixed-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["query"]["raw_tokens"] == []
    assert packet["parsed_arguments"]["exact_targets"]["slug"] == "prefixed-resume"
    assert packet["selected_target"]["slug"] == "prefixed-resume"
    assert packet["selected_target"]["selection_kind"] == "explicit"


def test_run_provider_families_and_exact_run_selection(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "run-resume")
    run_dir = plan / "archive" / "20260629T010203Z-run"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(
        json.dumps({"kind": "user_choice", "choice": "ship it", "timestamp": "2026-06-29T01:02:03Z"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "context.json").write_text(json.dumps({"status": "ok", "slug": "run-resume"}), encoding="utf-8")
    (run_dir / "run-brief.json").write_text(json.dumps({"status": "ok", "intent": "resume run", "outcome": "done"}), encoding="utf-8")
    (run_dir / "REPORT.md").write_text("# Report\n\nRun report.\n", encoding="utf-8")

    packet = _mod.build_context(
        ["--run", run_dir.name, "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    for provider in ("git_log", "decisions", "context_json", "run_brief"):
        assert provider in packet["provider_allowlist"]
        assert provider in packet["source_status"]
    assert "report_context" not in packet["provider_allowlist"]
    record_types = {record["type"] for record in packet["evidence_records"]}
    assert {"git_commit", "git_log", "decisions", "context_json", "run_brief"}.issubset(record_types)
    assert "report" not in record_types
    assert packet["selected_target"]["run_id"] == run_dir.name


def test_prefixed_exact_run_target_selects_deterministically(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "prefixed-run-resume")
    run_dir = plan / "archive" / "20260629T020304Z-run"
    run_dir.mkdir(parents=True)
    (run_dir / "context.json").write_text(json.dumps({"status": "ok", "slug": "prefixed-run-resume"}), encoding="utf-8")
    (run_dir / "run-brief.json").write_text(json.dumps({"status": "ok", "outcome": "prefixed done"}), encoding="utf-8")

    packet = _mod.build_context(
        [f"run:{run_dir.name}", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["query"]["raw_tokens"] == []
    assert packet["parsed_arguments"]["exact_targets"]["run"] == run_dir.name
    assert packet["selected_target"]["run_id"] == run_dir.name
    assert packet["selected_target"]["selection_kind"] == "explicit"


def test_iso_timestamp_run_prefix_selects_unique_run(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "iso-prefix-resume")
    run_dir = plan / "archive" / "20260629T020304Z-run"
    run_dir.mkdir(parents=True)
    (run_dir / "context.json").write_text(json.dumps({"status": "ok", "slug": "iso-prefix-resume"}), encoding="utf-8")
    (run_dir / "run-brief.json").write_text(json.dumps({"status": "ok", "outcome": "prefixed done"}), encoding="utf-8")

    packet = _mod.build_context(
        ["--run", "2026-06-29T02:03", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["selected_target"]["run_id"] == run_dir.name
    assert packet["selected_target"]["selection_kind"] == "explicit"


def test_ambiguous_run_prefix_requires_selection(tmp_path: Path) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "ambiguous-prefix-resume")
    for run_name in ("20260629T020304Z-run", "20260629T020305Z-run"):
        run_dir = plan / "archive" / run_name
        run_dir.mkdir(parents=True)
        (run_dir / "context.json").write_text(json.dumps({"status": "ok", "slug": "ambiguous-prefix-resume"}), encoding="utf-8")
        (run_dir / "run-brief.json").write_text(json.dumps({"status": "ok", "outcome": run_name}), encoding="utf-8")

    packet = _mod.build_context(
        ["--run", "20260629T0203", "--noninteractive", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["status"] == "needs_selection"
    assert "explicit_collision" in packet["ambiguity"]["triggers"]
    assert packet["suggested_selection_args"]


def test_run_discovery_ignores_unbounded_archive_matches(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "bounded-run-resume")
    run_name = "20260629T010203Z-run"
    bounded_run = plan / "archive" / run_name
    bounded_run.mkdir(parents=True)
    (bounded_run / "context.json").write_text(json.dumps({"status": "ok", "slug": "bounded-run-resume"}), encoding="utf-8")
    rogue_run = base / "unrelated" / "deep" / "archive" / run_name
    rogue_run.mkdir(parents=True)
    (rogue_run / "context.json").write_text(json.dumps({"status": "ok", "slug": "rogue-resume"}), encoding="utf-8")

    _forbid_report_context_load(monkeypatch)

    def fail_glob(self, pattern):
        raise AssertionError(f"unbounded glob called with {pattern}")

    monkeypatch.setattr(_mod.Path, "glob", fail_glob)

    packet = _mod.build_context(
        ["--run", run_name, "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    context_records = [record for record in packet["evidence_records"] if record["type"] == "context_json"]
    assert any(str(record.get("source", "")).startswith(str(bounded_run)) for record in context_records)
    assert not [record for record in packet["evidence_records"] if str(record.get("source", "")).startswith(str(rogue_run))]


def test_current_mode_selects_one_active_candidate_or_requires_selection() -> None:
    active = _mod.Candidate(
        candidate_id="cand-active",
        slug="active-resume",
        score=80,
        confidence="high",
        evidence_ids=["ev-active", "ev-plan"],
        current_state={"primary": "active", "flags": {"active_registry": True}, "precedence": []},
        selection_token="candidate:cand-active|slug:active-resume",
    )
    paused = _mod.Candidate(
        candidate_id="cand-paused",
        slug="paused-resume",
        score=70,
        confidence="high",
        evidence_ids=["ev-paused", "ev-plan"],
        current_state={"primary": "paused", "flags": {}, "precedence": []},
        selection_token="candidate:cand-paused|slug:paused-resume",
    )
    seed = _mod.ContextSeed(argv=["current"], query="", raw_query_tokens=[], args=SimpleNamespace(resume_mode="current", select=None), repo_root=_REPO_ROOT, generated_at="2026-06-29T00:00:00Z", environ={})

    ambiguity = _mod._ambiguity([active, paused], seed)
    selected = _mod._select_target([active, paused], seed, ambiguity)

    assert ambiguity["needs_selection"] is False
    assert selected["slug"] == "active-resume"

    second_active = _mod.Candidate(
        candidate_id="cand-active-two",
        slug="second-active",
        score=75,
        confidence="high",
        evidence_ids=["ev-active-two", "ev-plan"],
        current_state={"primary": "active", "flags": {"active_registry": True}, "precedence": []},
        selection_token="candidate:cand-active-two|slug:second-active",
    )
    ambiguous = _mod._ambiguity([active, second_active], seed)

    assert ambiguous["needs_selection"] is True
    assert "explicit_collision" in ambiguous["triggers"]


def test_latest_mode_selects_unique_newest_run_or_requires_selection() -> None:
    older = _mod.Candidate(
        candidate_id="cand-old",
        slug="old-resume",
        run_id="20260629T010203Z-run",
        score=80,
        confidence="high",
        evidence_ids=["ev-old", "ev-plan"],
        current_state={"primary": "completed", "flags": {}, "precedence": []},
        selection_token="candidate:cand-old|slug:old-resume|run:20260629T010203Z-run",
    )
    newest = _mod.Candidate(
        candidate_id="cand-new",
        slug="new-resume",
        run_id="20260629T020203Z-run",
        score=70,
        confidence="high",
        evidence_ids=["ev-new", "ev-plan"],
        current_state={"primary": "completed", "flags": {}, "precedence": []},
        selection_token="candidate:cand-new|slug:new-resume|run:20260629T020203Z-run",
    )
    seed = _mod.ContextSeed(argv=["latest"], query="", raw_query_tokens=[], args=SimpleNamespace(resume_mode="latest", select=None), repo_root=_REPO_ROOT, generated_at="2026-06-29T00:00:00Z", environ={})

    ambiguity = _mod._ambiguity([older, newest], seed)
    selected = _mod._select_target([older, newest], seed, ambiguity)

    assert ambiguity["needs_selection"] is False
    assert selected["run_id"] == "20260629T020203Z-run"



def test_latest_mode_requires_selection_without_real_recency_evidence(tmp_path: Path) -> None:
    alpha_dir = tmp_path / "alpha-resume"
    zeta_dir = tmp_path / "zeta-resume"
    alpha_dir.mkdir()
    zeta_dir.mkdir()
    alpha = _mod.Candidate(
        candidate_id="cand-alpha",
        slug="alpha-resume",
        plan_dir=str(alpha_dir),
        run_id="alpha-run",
        score=80,
        confidence="high",
        evidence_ids=["ev-alpha", "ev-alpha-plan"],
        current_state={"primary": "completed", "flags": {}, "precedence": []},
        selection_token="candidate:cand-alpha|slug:alpha-resume|run:alpha-run",
    )
    zeta = _mod.Candidate(
        candidate_id="cand-zeta",
        slug="zeta-resume",
        plan_dir=str(zeta_dir),
        run_id="zeta-run",
        score=75,
        confidence="high",
        evidence_ids=["ev-zeta", "ev-zeta-plan"],
        current_state={"primary": "completed", "flags": {}, "precedence": []},
        selection_token="candidate:cand-zeta|slug:zeta-resume|run:zeta-run",
    )
    seed = _mod.ContextSeed(argv=["latest"], query="", raw_query_tokens=[], args=SimpleNamespace(resume_mode="latest", select=None), repo_root=_REPO_ROOT, generated_at="2026-06-29T00:00:00Z", environ={})

    ambiguity = _mod._ambiguity([alpha, zeta], seed)
    selected = _mod._select_target([alpha, zeta], seed, ambiguity)

    assert ambiguity["needs_selection"] is True
    assert "explicit_unresolved" in ambiguity["triggers"]
    assert selected is None


def test_latest_mode_requires_selection_with_partial_recency_evidence() -> None:
    dated = _mod.Candidate(
        candidate_id="cand-dated",
        slug="dated-resume",
        run_id="20260629T020203Z-run",
        score=80,
        confidence="high",
        evidence_ids=["ev-dated", "ev-dated-plan"],
        current_state={"primary": "completed", "flags": {}, "precedence": []},
        selection_token="candidate:cand-dated|slug:dated-resume|run:20260629T020203Z-run",
    )
    undated = _mod.Candidate(
        candidate_id="cand-undated",
        slug="undated-resume",
        run_id="undated-run",
        score=75,
        confidence="high",
        evidence_ids=["ev-undated", "ev-undated-plan"],
        current_state={"primary": "completed", "flags": {}, "precedence": []},
        selection_token="candidate:cand-undated|slug:undated-resume|run:undated-run",
    )
    seed = _mod.ContextSeed(argv=["latest"], query="", raw_query_tokens=[], args=SimpleNamespace(resume_mode="latest", select=None), repo_root=_REPO_ROOT, generated_at="2026-06-29T00:00:00Z", environ={})

    ambiguity = _mod._ambiguity([dated, undated], seed)
    selected = _mod._select_target([dated, undated], seed, ambiguity)

    assert ambiguity["needs_selection"] is True
    assert "explicit_unresolved" in ambiguity["triggers"]
    assert selected is None

def test_exact_selection_still_blocks_thin_low_confidence_candidate() -> None:
    seed = _mod.ContextSeed(
        argv=[],
        query="",
        raw_query_tokens=[],
        args=SimpleNamespace(slug=None, run=None, select="candidate:cand-thin|slug:thin-resume"),
        repo_root=_REPO_ROOT,
        generated_at="2026-06-29T00:00:00Z",
        environ={},
    )
    candidate = _mod.Candidate(
        candidate_id="cand-thin",
        slug="thin-resume",
        score=10,
        confidence="low",
        evidence_ids=["ev-one"],
        current_state=_mod._state_from_status("unknown", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-thin|slug:thin-resume",
    )

    ambiguity = _mod._ambiguity([candidate], seed)

    assert ambiguity["needs_selection"] is True
    assert {"low_confidence", "thin_evidence"}.issubset(set(ambiguity["triggers"]))
    assert _mod._select_target([candidate], seed, ambiguity) is None
    safe_next = _mod._safe_next_command(candidate.as_dict(), [candidate], ambiguity)
    assert safe_next["command"] == "/z-resume --select 'candidate:cand-thin|slug:thin-resume'"


def test_worktree_dirty_divergent_reduce_to_primary_states() -> None:
    candidate = _mod.Candidate(
        candidate_id="cand-wt",
        slug="worktree-resume",
        current_state=_mod._state_from_status("paused", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-wt",
    )
    record = _mod.EvidenceRecord(
        evidence_id="ev-worktree",
        evidence_type="worktree",
        provider="artifact_inventory",
        source="git worktree list --porcelain",
        status="ok",
        validation_status="valid",
        data={"git_state": {"dirty": True, "divergent": True}},
    )

    _mod._apply_record_to_candidate(candidate, record)
    _mod._reduce_primary_state(candidate)

    assert candidate.current_state["primary"] == "dirty"
    assert candidate.current_state["flags"]["dirty_worktree"] is True
    assert candidate.current_state["flags"]["divergent_branch"] is True


def test_unprobed_worktree_records_are_unvalidated_and_degraded(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "state"
    worktree = tmp_path / "weak-resume"
    worktree.mkdir()
    _write_plan(base, "different-resume")

    class FakeInventory:
        @staticmethod
        def collect_inventory(**kwargs):
            return {
                "source_status": {"plans": "missing", "archives": "missing", "registry": "missing", "worktrees": "ok"},
                "truncated": False,
                "signals": {},
                "dropped_counts": {},
                "mandatory_candidates": [],
                "historical_candidates": [],
                "active_records": [],
                "worktrees": [{"path": str(worktree), "branch": "feature/weak-resume", "head": "abc123"}],
            }

    monkeypatch.setattr(_mod, "_artifact_inventory", lambda: FakeInventory)
    monkeypatch.setattr(_mod, "_worktree_state", lambda path: (_ for _ in ()).throw(AssertionError("weak worktree must not be probed")))
    seed = _mod.ContextSeed(
        argv=[],
        query="",
        raw_query_tokens=[],
        args=SimpleNamespace(
            slug="different-resume",
            run=None,
            plan_dir=None,
            artifact=None,
            max_candidates=5,
            worktree=None,
            branch=None,
            repo=None,
            all_repos=False,
        ),
        repo_root=_REPO_ROOT,
        generated_at="2026-06-29T00:00:00Z",
        environ=_env(base),
        repo_id="repo-one",
        base_dir=str(base),
        repo_sources=[{"repo_id": "repo-one", "repo_root": str(_REPO_ROOT), "repo_name": "z-harness", "current_repo": True, "source": "current"}],
    )

    result = _mod.ArtifactInventoryProvider().collect(seed)

    worktree_records = [record for record in result.records if record.evidence_type == "worktree"]
    assert worktree_records
    assert worktree_records[0].validation_status == "unvalidated"
    assert worktree_records[0].degraded is True
    assert worktree_records[0].data["git_state"] == {"warnings": ["worktree not probed; association is unvalidated"], "not_probed": True}


def test_worktree_landed_detection_checks_head_ancestor_not_branch_merged(tmp_path: Path, monkeypatch) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()

    def fake_run(argv, *, cwd=None, environ=None, timeout=10):
        if argv[:3] == ["git", "branch", "--merged"]:
            raise AssertionError("landed detection must not use git branch --merged HEAD")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return 0, "", ""
        if argv[:3] == ["git", "branch", "--show-current"]:
            return 0, "feature/resume", ""
        if argv[:4] == ["git", "rev-parse", "--verify", "--quiet"]:
            return 0, argv[-1], ""
        if argv[:3] == ["git", "merge-base", "--is-ancestor"]:
            return 1, "", ""
        if argv[:3] == ["git", "rev-list", "--left-right"]:
            return 0, "0 0", ""
        return 1, "", "unexpected command"

    monkeypatch.setattr(_mod, "_run", fake_run)

    state = _mod._worktree_state(str(worktree))

    assert state["landed"] is False



def test_safe_next_command_and_ranking_are_exposed_for_selected_plan(tmp_path: Path) -> None:
    base = tmp_path / "state"
    _write_plan(base, "safe-next-resume")

    packet = _mod.build_context(
        ["--slug", "safe-next-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["selected_target"]["slug"] == "safe-next-resume"
    assert packet["safe_next_command"]["kind"] == "continue_plan"
    assert packet["safe_next_command"]["command"] == "/z-execute safe-next-resume"
    matrix_key = packet["safe_next_command"]["matrix_key"]
    assert matrix_key["selected_target_type"] == "plan"
    assert matrix_key["confidence"] in {"medium", "high"}
    assert matrix_key["branch_worktree_state"] in {"none", "associated_clean_or_unknown"}
    assert packet["ranking"][0]["score_components"]["recency_decay"] == 0
    assert "source_status" in packet["ranking"][0]
    assert "ambiguity_state" in packet["ranking"][0]
    selected_score = next(
        item for item in packet["score_components"]["candidate_scores"]
        if item["candidate_id"] == packet["selected_target"]["candidate_id"]
    )
    assert selected_score["score"] == _score_total(selected_score)
    assert all(value >= 0 for value in selected_score["components"].values())


def test_branch_and_git_conflicts_create_candidate_warning_and_ambiguity() -> None:
    seed = _mod.ContextSeed(
        argv=[],
        query="branch conflict resume",
        raw_query_tokens=["branch", "conflict", "resume"],
        args=SimpleNamespace(slug=None, run=None, select=None, lookback_days=14),
        repo_root=_REPO_ROOT,
        generated_at="2026-06-29T00:00:00Z",
        environ={},
    )
    candidate = _mod.Candidate(
        candidate_id="cand-conflict",
        slug="branch-conflict-resume",
        repo_id="repo-one",
        branch="feature/branch-conflict-resume",
        score=80,
        confidence="high",
        evidence_ids=["ev-plan", "ev-session"],
        current_state=_mod._state_from_status("paused", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-conflict|slug:branch-conflict-resume|repo:repo-one",
    )
    record = _mod.EvidenceRecord(
        evidence_id="ev-git-log-conflict",
        evidence_type="git_log",
        provider="git_log",
        source="main",
        status="ok",
        validation_status="valid",
        data={
            "branch": "main",
            "repo_id": "repo-one",
            "entries": ["abc123\tcontinue branch conflict resume work"],
        },
    )

    merged = _mod._merge_candidates([candidate], [record], seed)
    ambiguity = _mod._ambiguity(merged, seed)

    assert record.candidate_id == "cand-conflict"
    assert merged[0].current_state["flags"]["conflicting_current_state"] is True
    assert any("conflicting branch evidence" in warning for warning in merged[0].ambiguity_warnings)
    assert "conflicting_current_state" in ambiguity["triggers"]


def test_old_canonical_decisions_keep_bounded_recency_penalty() -> None:
    seed = _mod.ContextSeed(
        argv=[],
        query="old canonical resume",
        raw_query_tokens=["old", "canonical", "resume"],
        args=SimpleNamespace(slug=None, run=None, select=None, lookback_days=14),
        repo_root=_REPO_ROOT,
        generated_at="2026-06-29T00:00:00Z",
        environ={},
    )
    old = _mod.Candidate(
        candidate_id="cand-old",
        slug="old-canonical-resume",
        run_id="20250101T000000Z-run",
        score=80,
        confidence="high",
        evidence_ids=["ev-old-plan", "ev-old-session"],
        current_state=_mod._state_from_status("completed", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-old|slug:old-canonical-resume|run:20250101T000000Z-run",
    )
    decisions = _mod.EvidenceRecord(
        evidence_id="ev-old-decisions",
        evidence_type="decisions",
        provider="decisions",
        source="/tmp/events.jsonl",
        status="ok",
        validation_status="valid",
        candidate_id="cand-old",
        data={"run_id": "20250101T000000Z-run", "decision_count": 2},
    )
    recent = _mod.Candidate(
        candidate_id="cand-recent",
        slug="recent-light-resume",
        run_id="20260629T000000Z-run",
        score=70,
        confidence="medium",
        evidence_ids=["ev-recent-plan", "ev-recent-session"],
        current_state=_mod._state_from_status("completed", active=False, degraded=False, archived_only=False),
        selection_token="candidate:cand-recent|slug:recent-light-resume|run:20260629T000000Z-run",
    )

    merged = _mod._merge_candidates([old, recent], [decisions], seed)

    assert merged[0].candidate_id == "cand-old"
    assert merged[0].score_components["decisions_available"] == 10
    assert merged[0].score_components["recency_decay"] >= -3
    assert any(item["reason"] == "recency_decay_capped_for_canonical_decisions" for item in merged[0].negative_evidence)


def test_completed_registry_conflict_blocks_safe_execution(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "state"
    plan = _write_plan(base, "registry-conflict-resume")
    (plan / "TASKS.md").write_text(
        "# TASKS\n\n"
        "## T001 — Done `[x]`\n"
        "**Depends on:** —\n\n",
        encoding="utf-8",
    )

    class FakeInventory:
        @staticmethod
        def collect_inventory(**kwargs):
            return {
                "source_status": {"plans": "ok", "archives": "missing", "registry": "ok", "worktrees": "missing"},
                "truncated": False,
                "signals": {},
                "dropped_counts": {},
                "mandatory_candidates": [
                    {
                        "slug": "registry-conflict-resume",
                        "path": str(plan),
                        "score": 100,
                        "basis": ["exact_slug"],
                        "status": "paused",
                        "source_status": {"tasks": "ok"},
                    }
                ],
                "historical_candidates": [],
                "active_records": [
                    {
                        "slug": "registry-conflict-resume",
                        "repo_id": "repo-one",
                        "repo_root": str(_REPO_ROOT),
                        "worktree_path": str(tmp_path / "wt"),
                        "branch": "hermes/registry-conflict-resume/T004",
                        "status": "active",
                    }
                ],
                "worktrees": [],
            }

    monkeypatch.setattr(_mod, "_artifact_inventory", lambda: FakeInventory)
    packet = _mod.build_context(
        ["--slug", "registry-conflict-resume", "--repo-root", str(_REPO_ROOT), "--max-candidates", "5"],
        environ=_env(base),
    )

    assert packet["selected_target"] is None
    assert "conflicting_current_state" in packet["ambiguity"]["triggers"]
    assert packet["safe_next_command"]["kind"] == "select_target"
    assert any("completed TASKS conflict with active registry evidence" in warning for warning in packet["warnings"])


def test_resume_cluster_agent_contract_forbids_external_discovery() -> None:
    contract = (_REPO_ROOT / "agents" / "resume-cluster.md").read_text(encoding="utf-8")

    assert "No external discovery" in contract
    assert "Do not read files, run commands, browse, inspect repo state" in contract
    assert "Return exactly one JSON object" in contract
    assert "current_or_landed_state" in contract
    assert "citation ids present in the supplied evidence" in contract


def test_z_resume_skill_contract_preserves_read_only_report_and_dispatch_boundaries() -> None:
    contract = (_REPO_ROOT / "skills" / "z-resume" / "SKILL.md").read_text(encoding="utf-8")

    assert "does **not** execute, restart, mutate, or auto-dispatch" in contract
    assert "Selection before story" in contract
    assert "Noninteractive ambiguity returns `needs_selection` with `selected_target: null`" in contract
    assert "scripts/resume-context.py` is a pure gather/score/packet producer" in contract
    assert "Do not invoke `report-context.py`, `report-synth`, `/z-report`, or any report renderer for `needs_selection`" in contract
    assert "Dispatch **zero** calls when subagents are unavailable" in contract
    assert "Default dispatch must never exceed `subagent_request_policy.max_default_calls`" in contract

def test_subagent_requests_are_bounded_and_use_only_supplied_evidence() -> None:
    candidate = _mod.Candidate(
        candidate_id="cand-alpha",
        slug="alpha-resume",
        repo_id="repo-one",
        score=90,
        confidence="high",
        current_state={"primary": "active", "flags": {"active_registry": True}},
        evidence_ids=["ev-alpha-task", "ev-alpha-session"],
        citation_ids=["cit-alpha-task", "cit-alpha-session"],
        selection_token="candidate:cand-alpha|slug:alpha-resume|repo:repo-one",
    )
    unrelated = _mod.EvidenceRecord(
        evidence_id="ev-unrelated",
        evidence_type="tasks",
        provider="plan_state",
        source="/tmp/unrelated/TASKS.md",
        status="ok",
        validation_status="valid",
        candidate_id="cand-other",
        citation_id="cit-other",
        data={"summary": "must not leak"},
    )
    records = [
        _mod.EvidenceRecord(
            evidence_id="ev-alpha-task",
            evidence_type="tasks",
            provider="plan_state",
            source="/tmp/alpha/TASKS.md",
            status="ok",
            validation_status="valid",
            candidate_id="cand-alpha",
            citation_id="cit-alpha-task",
            data={"summary": "T006 in progress"},
        ),
        _mod.EvidenceRecord(
            evidence_id="ev-alpha-session",
            evidence_type="session",
            provider="plan_state",
            source="/tmp/alpha/SESSION.md",
            status="ok",
            validation_status="valid",
            candidate_id="cand-alpha",
            citation_id="cit-alpha-session",
            data={"next_step": "continue bounded inference integration"},
        ),
        unrelated,
    ]
    citations = [
        _mod.Citation("cit-alpha-task", "tasks", path="/tmp/alpha/TASKS.md", line_start=1),
        _mod.Citation("cit-alpha-session", "session", path="/tmp/alpha/SESSION.md", line_start=1),
        _mod.Citation("cit-other", "tasks", path="/tmp/unrelated/TASKS.md", line_start=1),
    ]

    requests = _mod._subagent_requests([candidate], records, citations, {"state": "none", "triggers": []}, None)

    assert len(requests) == 1
    assert requests[0]["max_default_calls"] == 2
    assert requests[0]["agent"] == "resume-cluster"
    assert requests[0]["input_boundary"] == "provided_evidence_only"
    assert set(requests[0]["candidate_ids"]) == {"cand-alpha"}
    assert set(requests[0]["citation_ids"]) == {"cit-alpha-task", "cit-alpha-session"}
    assert "must not leak" not in requests[0]["prompt"]
    assert "Do not read files, run commands" in requests[0]["prompt"]
    assert "likely_work_thread" in requests[0]["prompt"]


def test_ambiguous_subagent_request_compares_only_top_bounded_cluster() -> None:
    candidates = []
    records = []
    citations = []
    for idx in range(5):
        candidate_id = f"cand-{idx}"
        citation_id = f"cit-{idx}"
        evidence_id = f"ev-{idx}"
        candidates.append(
            _mod.Candidate(
                candidate_id=candidate_id,
                slug=f"resume-{idx}",
                score=80 - idx,
                confidence="medium",
                current_state={"primary": "paused", "flags": {}},
                evidence_ids=[evidence_id],
                citation_ids=[citation_id],
                selection_token=f"candidate:{candidate_id}|slug:resume-{idx}",
            )
        )
        records.append(
            _mod.EvidenceRecord(
                evidence_id=evidence_id,
                evidence_type="tasks",
                provider="plan_state",
                source=f"/tmp/resume-{idx}/TASKS.md",
                status="ok",
                validation_status="valid",
                candidate_id=candidate_id,
                citation_id=citation_id,
            )
        )
        citations.append(_mod.Citation(citation_id, "tasks", path=f"/tmp/resume-{idx}/TASKS.md"))

    requests = _mod._subagent_requests(
        candidates,
        records,
        citations,
        {"state": "needs_selection", "triggers": ["close_scores"], "needs_selection": True},
        None,
    )

    assert len(requests) <= 2
    assert requests[0]["request_kind"] == "top_cluster_comparison"
    assert requests[0]["candidate_ids"] == ["cand-0", "cand-1", "cand-2"]
    assert "resume-4" not in requests[0]["prompt"]


def test_oversized_subagent_prompt_hard_cap_keeps_request_metadata_consistent() -> None:
    candidates = []
    records = []
    citations = []
    for idx in range(3):
        candidate_id = f"cand-{idx}"
        citation_id = f"cit-{idx}"
        evidence_id = f"ev-{idx}"
        candidates.append(
            _mod.Candidate(
                candidate_id=candidate_id,
                slug=f"oversized-resume-{idx}",
                score=90 - idx,
                confidence="medium",
                current_state={"primary": "active", "flags": {"active_registry": True}},
                evidence_ids=[evidence_id],
                citation_ids=[citation_id],
                selection_token=f"candidate:{candidate_id}|slug:oversized-resume-{idx}",
                negative_evidence=[
                    {"reason": f"oversized-negative-{item}", "details": "n" * 1000, "penalty": -1}
                    for item in range(20)
                ],
                source_warnings=[f"oversized-source-warning-{item}-" + ("s" * 1000) for item in range(20)],
                ambiguity_warnings=[f"oversized-ambiguity-warning-{item}-" + ("a" * 1000) for item in range(20)],
                summary="candidate-summary-" + ("c" * 20000),
            )
        )
        records.append(
            _mod.EvidenceRecord(
                evidence_id=evidence_id,
                evidence_type="tasks",
                provider="plan_state",
                source=f"/tmp/oversized-resume-{idx}/TASKS.md",
                status="ok",
                validation_status="valid",
                candidate_id=candidate_id,
                citation_id=citation_id,
                data={f"wide-field-{item}": "e" * 1000 for item in range(80)},
            )
        )
        citations.append(_mod.Citation(citation_id, "tasks", path=f"/tmp/oversized-resume-{idx}/TASKS.md"))

    request = _mod._subagent_requests(
        candidates,
        records,
        citations,
        {"state": "needs_selection", "triggers": ["close_scores"], "needs_selection": True},
        None,
    )[0]

    assert len(request["prompt"]) <= _mod.MAX_SUBAGENT_PROMPT_CHARS
    prompt_payload = json.loads(request["prompt"].split("SUPPLIED_EVIDENCE_JSON:\n", 1)[1])
    prompt_candidate_ids = [candidate["candidate_id"] for candidate in prompt_payload["candidates"]]
    assert prompt_payload["request_kind"] == request["request_kind"] == request["payload"]["request_kind"]
    assert prompt_candidate_ids == request["candidate_ids"]
    assert len(prompt_candidate_ids) == 1
    assert request["request_kind"] == "single_candidate"
    assert prompt_payload["prompt_degraded_reason"] in {
        "prompt_budget_reduced_to_single_candidate",
        "prompt_budget_minimal_payload",
        "prompt_budget_emergency_payload",
    }


def test_malformed_or_contradictory_subagent_output_degrades_without_source_status_changes() -> None:
    candidate = _mod.Candidate(
        candidate_id="cand-alpha",
        slug="alpha-resume",
        score=90,
        confidence="high",
        current_state={"primary": "active", "flags": {"active_registry": True}},
        evidence_ids=["ev-alpha"],
        citation_ids=["cit-alpha"],
        selection_token="candidate:cand-alpha|slug:alpha-resume",
    )
    record = _mod.EvidenceRecord(
        evidence_id="ev-alpha",
        evidence_type="tasks",
        provider="plan_state",
        source="/tmp/alpha/TASKS.md",
        status="ok",
        validation_status="valid",
        candidate_id="cand-alpha",
        citation_id="cit-alpha",
    )
    request = _mod._subagent_requests(
        [candidate],
        [record],
        [_mod.Citation("cit-alpha", "tasks", path="/tmp/alpha/TASKS.md")],
        {"state": "none", "triggers": []},
        None,
    )[0]
    packet = {
        "source_status": {"plan_state": {"status": "ok", "degraded": False, "warnings": [], "citation_ids": ["cit-alpha"]}},
        "evidence_records": [record.as_dict()],
        "selected_target": candidate.as_dict(),
        "subagent_requests": [request],
        "subagent_judgments": [],
    }
    before_status = json.loads(json.dumps(packet["source_status"]))
    before_records = json.loads(json.dumps(packet["evidence_records"]))

    malformed = _mod.attach_subagent_judgments(packet, ["not json"])

    assert malformed["source_status"] == before_status
    assert malformed["evidence_records"] == before_records
    assert malformed["selected_target"]["current_state"]["primary"] == "active"
    assert malformed["subagent_judgments"][0]["status"] == "degraded"
    assert malformed["subagent_judgments"][0]["degraded_reason"] == "malformed_json"

    unavailable = _mod.attach_subagent_judgments(packet, [])

    assert unavailable["source_status"] == before_status
    assert unavailable["subagent_judgments"][0]["status"] == "degraded"
    assert unavailable["subagent_judgments"][0]["degraded_reason"] == "missing_output"

    accepted = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "alpha-resume",
                "current_or_landed_state": "active",
                "latest_consensus": "<unknown>",
                "unresolved_questions": ["confirm next task before execution"],
                "confidence": "medium",
                "confidence_reasons": ["active state and citation are supplied"],
                "suggested_next_command_or_prompt": "/z-resume --select 'candidate:cand-alpha|slug:alpha-resume'",
                "citations": ["cit-alpha"],
            }
        ],
    )

    assert accepted["source_status"] == before_status
    assert accepted["evidence_records"] == before_records
    assert accepted["subagent_judgments"][0]["status"] == "ok"

    contradictory = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "alpha-resume",
                "current_or_landed_state": "landed",
                "latest_consensus": "<unknown>",
                "unresolved_questions": [],
                "confidence": "high",
                "confidence_reasons": ["claimed a state not in supplied deterministic evidence"],
                "suggested_next_command_or_prompt": "/z-review-all",
                "citations": ["cit-alpha"],
            }
        ],
    )

    assert contradictory["source_status"] == before_status
    assert contradictory["subagent_judgments"][0]["status"] == "degraded"
    assert contradictory["subagent_judgments"][0]["degraded_reason"] == "state_contradicts_deterministic_evidence"

    uncited = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "alpha-resume",
                "current_or_landed_state": "active",
                "latest_consensus": "<unknown>",
                "unresolved_questions": [],
                "confidence": "medium",
                "confidence_reasons": ["claims active state without a citation"],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": [],
            }
        ],
    )

    assert uncited["subagent_judgments"][0]["status"] == "degraded"
    assert uncited["subagent_judgments"][0]["degraded_reason"] == "missing_citations"

    mixed_state = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "alpha-resume",
                "current_or_landed_state": "active and landed",
                "latest_consensus": "<unknown>",
                "unresolved_questions": [],
                "confidence": "high",
                "confidence_reasons": ["mixed state text must match deterministic state tokens"],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": ["cit-alpha"],
            }
        ],
    )

    assert mixed_state["subagent_judgments"][0]["status"] == "degraded"
    assert mixed_state["subagent_judgments"][0]["degraded_reason"] == "state_contradicts_deterministic_evidence"

    uncited_reason = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "<unknown>",
                "current_or_landed_state": "<unknown>",
                "latest_consensus": "<unknown>",
                "unresolved_questions": [],
                "confidence": "medium",
                "confidence_reasons": ["active registry evidence supports this candidate"],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": [],
            }
        ],
    )

    assert uncited_reason["subagent_judgments"][0]["status"] == "degraded"
    assert uncited_reason["subagent_judgments"][0]["degraded_reason"] == "missing_citations"

    procedural_prefix_with_facts = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "<unknown>",
                "current_or_landed_state": "<unknown>",
                "latest_consensus": "<unknown>",
                "unresolved_questions": [],
                "confidence": "medium",
                "confidence_reasons": ["confirm active registry evidence supports this candidate"],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": [],
            }
        ],
    )

    assert procedural_prefix_with_facts["subagent_judgments"][0]["status"] == "degraded"
    assert procedural_prefix_with_facts["subagent_judgments"][0]["degraded_reason"] == "missing_citations"

    uncited_question = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "<unknown>",
                "current_or_landed_state": "<unknown>",
                "latest_consensus": "<unknown>",
                "unresolved_questions": ["why does active registry evidence still point here?"],
                "confidence": "low",
                "confidence_reasons": [],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": [],
            }
        ],
    )

    assert uncited_question["subagent_judgments"][0]["status"] == "degraded"
    assert uncited_question["subagent_judgments"][0]["degraded_reason"] == "missing_citations"

    procedural_only = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "<unknown>",
                "current_or_landed_state": "<unknown>",
                "latest_consensus": "<unknown>",
                "unresolved_questions": ["which task should run next?"],
                "confidence": "low",
                "confidence_reasons": ["needs user choice before execution"],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": [],
            }
        ],
    )

    assert procedural_only["subagent_judgments"][0]["status"] == "ok"

    unknown_alias_state = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "<unknown>",
                "current_or_landed_state": "unknown",
                "latest_consensus": "<unknown>",
                "unresolved_questions": ["confirm next task before execution"],
                "confidence": "low",
                "confidence_reasons": ["ask user to choose before execution"],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": [],
            }
        ],
    )

    assert unknown_alias_state["subagent_judgments"][0]["status"] == "ok"
    assert unknown_alias_state["subagent_judgments"][0]["current_or_landed_state"] == "<unknown>"

    supplied_state_set = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "<unknown>",
                "current_or_landed_state": ["active"],
                "latest_consensus": "<unknown>",
                "unresolved_questions": [],
                "confidence": "low",
                "confidence_reasons": [],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": ["cit-alpha"],
            }
        ],
    )

    assert supplied_state_set["subagent_judgments"][0]["status"] == "ok"
    assert supplied_state_set["subagent_judgments"][0]["current_or_landed_state"] == "active"

    arbitrary_state = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "<unknown>",
                "current_or_landed_state": "currently running",
                "latest_consensus": "<unknown>",
                "unresolved_questions": [],
                "confidence": "low",
                "confidence_reasons": [],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": ["cit-alpha"],
            }
        ],
    )

    assert arbitrary_state["subagent_judgments"][0]["status"] == "degraded"
    assert arbitrary_state["subagent_judgments"][0]["degraded_reason"] == "state_contradicts_deterministic_evidence"

    unsupported_state = _mod.attach_subagent_judgments(
        packet,
        [
            {
                "likely_work_thread": "<unknown>",
                "current_or_landed_state": "shipped",
                "latest_consensus": "<unknown>",
                "unresolved_questions": [],
                "confidence": "low",
                "confidence_reasons": [],
                "suggested_next_command_or_prompt": "<unknown>",
                "citations": ["cit-alpha"],
            }
        ],
    )

    assert unsupported_state["subagent_judgments"][0]["status"] == "degraded"
    assert unsupported_state["subagent_judgments"][0]["degraded_reason"] == "state_contradicts_deterministic_evidence"