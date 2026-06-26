from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "artifact-scout-inventory.py"

_spec = importlib.util.spec_from_file_location("artifact_scout_inventory", _SCRIPT)
assert _spec is not None and _spec.loader is not None
inventory = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = inventory
_spec.loader.exec_module(inventory)  # type: ignore[union-attr]


def _completed(argv: Sequence[str], rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), rc, stdout, stderr)


def _stub_commands(registry_stdout: str = "[]", git_stdout: str = ""):
    def run(argv: Sequence[str], cwd: Path, timeout: int = 5) -> subprocess.CompletedProcess[str]:
        if list(argv)[:3] == ["python3", "scripts/active-plan-registry.py", "list"]:
            return _completed(argv, 0, registry_stdout)
        if list(argv) == ["git", "worktree", "list", "--porcelain"]:
            return _completed(argv, 0, git_stdout)
        if len(argv) >= 2 and argv[0] == "bash" and str(argv[1]).endswith("plan-path.sh"):
            return _completed(argv, 1, "", "no helper")
        raise AssertionError(f"unexpected command: {argv}")

    return run


def _write_plan(plan_dir: Path, *, slug: str = "demo-plan", status: str = "active") -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "SPEC.md").write_text(
        f"---\nartifact_kind: SPEC\nslug: {slug}\nstatus: {status}\n---\n"
        "# Demo goal\n\n## Goal\n- Build the thing\n",
        encoding="utf-8",
    )
    (plan_dir / "PLAN.md").write_text(
        f"---\nartifact_kind: PLAN\nslug: {slug}\nstatus: {status}\n---\n"
        "# Demo plan\n\n## Approach\n- Keep it deterministic\n",
        encoding="utf-8",
    )
    (plan_dir / "TASKS.md").write_text(
        "# TASKS\n\n"
        "## T001 — Demo task — `[ ]`\n"
        "**Files:** `scripts/demo.py`, `tests/test_demo.py`\n",
        encoding="utf-8",
    )


def test_valid_output_writes_atomically_and_collects_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)
    prior_archive = plan_dir / "archive" / "20240101T000000Z-demo-plan"
    prior_archive.mkdir(parents=True)
    (prior_archive / "FIX.md").write_text("# Fix\n\n## Approach\n- Prior archive context\n", encoding="utf-8")
    current_archive = plan_dir / "archive" / "run-current"
    current_archive.mkdir(parents=True)
    (current_archive / "run-brief.json").write_text(json.dumps({"status": "running", "task": "current run"}), encoding="utf-8")

    registry_records = [
        {"run_id": "run-current", "slug": "demo-plan", "session_id": "same", "held_paths": [{"path": "scripts/demo.py"}]},
        {"run_id": "same-session", "slug": "demo-plan", "session_id": "same", "held_paths": [{"path": "scripts/demo.py"}]},
        {"run_id": "peer", "slug": "demo-plan", "session_id": "other", "scope": [{"path": "tests/test_demo.py"}], "held_paths": [{"path": "scripts/demo.py"}]},
    ]
    git_stdout = "worktree /tmp/demo-plan-worktree\nHEAD abc123\nbranch refs/heads/demo-plan-fix\n\n"
    monkeypatch.setattr(inventory, "_run_command", _stub_commands(json.dumps(registry_records), git_stdout))

    output = tmp_path / "out" / "artifact-scout-inventory.json"
    rc = inventory.main(
        [
            "--command", "/z-plan",
            "--slug", "demo-plan",
            "--run-id", "run-current",
            "--repo-root", str(repo),
            "--plan-dir", str(plan_dir),
            "--task", "Build demo inventory",
            "--output", str(output),
        ],
        environ={"Z_HARNESS_SESSION_ID": "same"},
    )

    assert rc == 0
    from_file = json.loads(output.read_text(encoding="utf-8"))
    from_stdout = json.loads(capsys.readouterr().out)
    assert from_stdout == from_file
    assert from_file["schema_version"] == "artifact-scout-inventory.v1"
    assert from_file["source_status"] == {"plans": "ok", "archives": "ok", "registry": "ok", "worktrees": "ok"}
    assert from_file["task_terms"][:2] == ["demo", "plan"]
    assert len(from_file["active_records"]) == 1
    assert from_file["active_records"][0]["run_id"] == "peer"
    candidate = from_file["mandatory_candidates"][0]
    assert candidate["slug"] == "demo-plan"
    assert {"SPEC", "PLAN", "TASKS", "FIX", "run-brief"}.issubset(set(candidate["artifact_kinds"]))
    assert "scripts/demo.py" in candidate["files"]
    assert "Prior archive context" in candidate["summary_excerpt"]
    assert from_file["signals"]["active_same_slug"] is True
    assert from_file["signals"]["active_path_overlap"] is True
    assert from_file["signals"]["held_paths_overlap"] is True
    assert from_file["signals"]["worktree_branch_overlap"] is True
    assert from_file["signals"]["unknown_due_to_partial_sources"] is False


def test_invalid_args_exit_2() -> None:
    assert inventory.main(["--command", "/z-plan"]) == 2
    assert inventory.main([
        "--command", "/z-plan",
        "--slug", "demo-plan",
        "--run-id", "run",
        "--repo-root", "relative/repo",
        "--plan-dir", "/tmp/base/plans/demo-plan",
        "--output", "/tmp/out.json",
    ]) == 2


def test_unwritable_output_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("file", encoding="utf-8")
    monkeypatch.setattr(inventory, "_run_command", _stub_commands())

    rc = inventory.main(
        [
            "--command", "/z-plan",
            "--slug", "demo-plan",
            "--run-id", "run-current",
            "--repo-root", str(repo),
            "--plan-dir", str(plan_dir),
            "--output", str(not_a_dir / "out.json"),
        ]
    )

    assert rc == 2


def test_registry_unavailable_is_partial_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)

    def run(argv: Sequence[str], cwd: Path, timeout: int = 5) -> subprocess.CompletedProcess[str]:
        if list(argv)[:3] == ["python3", "scripts/active-plan-registry.py", "list"]:
            return _completed(argv, 1, "", "boom")
        if list(argv) == ["git", "worktree", "list", "--porcelain"]:
            return _completed(argv, 0, "")
        return _completed(argv, 1, "", "")

    monkeypatch.setattr(inventory, "_run_command", run)
    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task=None)
    assert data["source_status"]["registry"] == "unavailable"
    assert data["active_records"] == []
    assert data["signals"]["unknown_due_to_partial_sources"] is True


def test_registry_warning_with_empty_json_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)

    def run(argv: Sequence[str], cwd: Path, timeout: int = 5) -> subprocess.CompletedProcess[str]:
        if list(argv)[:3] == ["python3", "scripts/active-plan-registry.py", "list"]:
            return _completed(argv, 0, "[]", "[active-plan-registry] WARNING: cannot resolve active_plans_dir")
        if list(argv) == ["git", "worktree", "list", "--porcelain"]:
            return _completed(argv, 0, "")
        return _completed(argv, 1, "", "")

    monkeypatch.setattr(inventory, "_run_command", run)

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task=None)

    assert data["source_status"]["registry"] == "unavailable"


def test_git_unavailable_is_partial_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)

    def run(argv: Sequence[str], cwd: Path, timeout: int = 5) -> subprocess.CompletedProcess[str]:
        if list(argv)[:3] == ["python3", "scripts/active-plan-registry.py", "list"]:
            return _completed(argv, 0, "[]")
        if list(argv) == ["git", "worktree", "list", "--porcelain"]:
            return _completed(argv, 128, "", "not a git repository")
        return _completed(argv, 1, "", "")

    monkeypatch.setattr(inventory, "_run_command", run)
    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task=None)
    assert data["source_status"]["worktrees"] == "unavailable"
    assert data["worktrees"] == []
    assert data["signals"]["unknown_due_to_partial_sources"] is True


def test_missing_base_still_outputs_partial_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "missing-base" / "plans" / "demo-plan"
    monkeypatch.setattr(inventory, "_run_command", _stub_commands())

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task="demo")

    assert data["source_status"]["plans"] == "missing"
    assert data["source_status"]["archives"] == "missing"
    assert data["mandatory_candidates"] == []
    assert data["signals"]["unknown_due_to_partial_sources"] is True


def test_corrupt_registry_json_marks_corrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)
    monkeypatch.setattr(inventory, "_run_command", _stub_commands("{not json", ""))

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task=None)

    assert data["source_status"]["registry"] == "corrupt"
    assert data["active_records"] == []
    assert data["signals"]["unknown_due_to_partial_sources"] is True


def test_current_run_and_same_session_registry_records_are_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)
    registry_records = [
        {"run_id": "run", "slug": "demo-plan", "session_id": "session-a"},
        {"run_id": "sibling", "slug": "demo-plan", "session_id": "session-a"},
        {"run_id": "peer", "slug": "other", "session_id": "session-b"},
    ]
    monkeypatch.setattr(inventory, "_run_command", _stub_commands(json.dumps(registry_records), ""))

    data = inventory.collect_inventory(
        command="/z-plan",
        slug="demo-plan",
        run_id="run",
        repo_root=repo,
        plan_dir=plan_dir,
        task=None,
        environ={},
    )

    assert [rec["run_id"] for rec in data["active_records"]] == ["peer"]
    assert data["signals"]["active_same_slug"] is False


def test_empty_legacy_directories_are_not_emitted_as_historical_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    (repo / "z-harness" / "logs").mkdir(parents=True)
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)
    monkeypatch.setattr(inventory, "_run_command", _stub_commands())

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task=None)

    assert all(candidate["slug"] != "logs" for candidate in data["historical_candidates"])


def test_caps_keep_mandatory_and_preserve_active_and_worktree_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans_root = tmp_path / "base" / "plans"
    plan_dir = plans_root / "demo-plan"
    _write_plan(plan_dir)
    for index in range(inventory.MAX_PLAN_DIRS + 25):
        slug = f"historical-{index:03d}"
        _write_plan(plans_root / slug, slug=slug)
    registry_records = [{"run_id": "peer", "slug": "demo-plan", "scope": [{"path": "scripts/demo.py"}]}]
    git_stdout = "worktree /tmp/demo-plan-worktree\nHEAD abc123\nbranch refs/heads/demo-plan-fix\n\n"
    monkeypatch.setattr(inventory, "_run_command", _stub_commands(json.dumps(registry_records), git_stdout))

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task="demo")

    assert [candidate["slug"] for candidate in data["mandatory_candidates"]] == ["demo-plan"]
    assert len(data["historical_candidates"]) == inventory.MAX_HISTORICAL_CANDIDATES
    assert data["dropped_counts"]["plan_dirs_over_cap"] == 25
    assert data["dropped_counts"]["historical_candidates_over_cap"] == inventory.MAX_PLAN_DIRS - inventory.MAX_HISTORICAL_CANDIDATES
    assert data["active_records"] == registry_records
    assert data["worktrees"][0]["branch"] == "demo-plan-fix"
    assert data["truncated"] is True
    assert data["signals"]["unknown_due_to_partial_sources"] is True


def test_huge_artifacts_are_byte_and_excerpt_truncated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)
    huge_body = "# Huge spec\n\n## Approach\n" + "\n".join(f"- item {index} {'x' * 120}" for index in range(200))
    (plan_dir / "SPEC.md").write_text(
        "---\nartifact_kind: SPEC\nslug: demo-plan\nstatus: active\n---\n" + huge_body,
        encoding="utf-8",
    )
    monkeypatch.setattr(inventory, "_run_command", _stub_commands())

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task=None)
    candidate = data["mandatory_candidates"][0]

    assert data["truncated"] is True
    assert data["source_status"]["plans"] == "truncated"
    assert candidate["source_status"]["plans"] == "truncated"
    assert candidate["truncated"] is True
    assert len(candidate["summary_excerpt"].encode("utf-8")) <= inventory.MAX_RETAINED_SECTION_BYTES


def test_transcripts_diffs_and_events_bodies_are_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)
    for name in ("events.jsonl", "transcript.md", "diff.patch"):
        (plan_dir / name).write_text("SHOULD_NOT_BE_READ", encoding="utf-8")
    read_names: list[str] = []
    real_safe_read_text = inventory._safe_read_text

    def spy_safe_read_text(path: Path, max_bytes: int = inventory.MAX_ARTIFACT_BYTES) -> tuple[str, bool]:
        assert path.name not in {"events.jsonl", "transcript.md", "diff.patch"}
        read_names.append(path.name)
        return real_safe_read_text(path, max_bytes)

    monkeypatch.setattr(inventory, "_safe_read_text", spy_safe_read_text)
    monkeypatch.setattr(inventory, "_run_command", _stub_commands())

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task=None)

    assert {"SPEC.md", "PLAN.md", "TASKS.md"}.issubset(set(read_names))
    assert "SHOULD_NOT_BE_READ" not in data["mandatory_candidates"][0]["summary_excerpt"]


def test_symlink_escapes_are_skipped_and_mark_sources_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans_root = tmp_path / "base" / "plans"
    plan_dir = plans_root / "demo-plan"
    _write_plan(plan_dir)
    outside_plan = tmp_path / "outside" / "escape"
    _write_plan(outside_plan, slug="escape")
    (plans_root / "escape").symlink_to(outside_plan, target_is_directory=True)
    outside_fix = tmp_path / "outside" / "FIX.md"
    outside_fix.write_text("# Escaped\n\n## Approach\n- ESCAPE SECRET\n", encoding="utf-8")
    (plan_dir / "FIX.md").symlink_to(outside_fix)
    monkeypatch.setattr(inventory, "_run_command", _stub_commands())

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task=None)

    assert "escape" not in {candidate["slug"] for candidate in data["historical_candidates"]}
    assert "ESCAPE SECRET" not in data["mandatory_candidates"][0]["summary_excerpt"]
    assert data["dropped_counts"]["symlink_escapes"] >= 2
    assert data["source_status"]["plans"] == "partial"
    assert data["signals"]["unknown_due_to_partial_sources"] is True


def test_artifact_file_cap_limits_reads_and_marks_inventory_truncated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = tmp_path / "base" / "plans" / "demo-plan"
    _write_plan(plan_dir)
    for name in inventory.ALLOWED_ARTIFACT_FILES:
        path = plan_dir / name
        if path.exists():
            continue
        if name == "run-brief.json":
            path.write_text(json.dumps({"status": "complete", "summary": "brief"}), encoding="utf-8")
        else:
            path.write_text(f"---\nartifact_kind: {path.stem}\nslug: demo-plan\n---\n# {path.stem}\n\n## Approach\n- extra\n", encoding="utf-8")
    read_names: list[str] = []
    real_safe_read_text = inventory._safe_read_text

    def spy_safe_read_text(path: Path, max_bytes: int = inventory.MAX_ARTIFACT_BYTES) -> tuple[str, bool]:
        read_names.append(path.name)
        return real_safe_read_text(path, max_bytes)

    monkeypatch.setattr(inventory, "_safe_read_text", spy_safe_read_text)
    monkeypatch.setattr(inventory, "_run_command", _stub_commands())

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task=None)

    assert read_names == list(inventory.ALLOWED_ARTIFACT_FILES[: inventory.MAX_ARTIFACT_FILES_PER_SLUG])
    assert data["dropped_counts"]["artifact_files_over_cap"] == len(inventory.ALLOWED_ARTIFACT_FILES) - inventory.MAX_ARTIFACT_FILES_PER_SLUG
    assert data["source_status"]["plans"] == "truncated"
    assert data["truncated"] is True


def test_historical_sort_and_latest_archive_per_slug_are_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans_root = tmp_path / "base" / "plans"
    plan_dir = plans_root / "demo-plan"
    _write_plan(plan_dir)

    def write_timed_plan(slug: str, timestamp: int) -> Path:
        path = plans_root / slug
        _write_plan(path, slug=slug)
        for child in path.iterdir():
            if child.is_file():
                os.utime(child, (timestamp, timestamp))
        os.utime(path, (timestamp, timestamp))
        return path

    shared_a = write_timed_plan("shared-a", 100)
    write_timed_plan("shared-b", 100)
    write_timed_plan("shared-c", 100)
    write_timed_plan("other-z", 500)
    old_archive = shared_a / "archive" / "old"
    old_archive.mkdir(parents=True)
    (old_archive / "FIX.md").write_text("# Old\n\n## Approach\n- Old archive\n", encoding="utf-8")
    new_archive = shared_a / "archive" / "new"
    new_archive.mkdir(parents=True)
    (new_archive / "FIX.md").write_text("# New\n\n## Approach\n- Newest archive\n", encoding="utf-8")
    os.utime(old_archive / "FIX.md", (200, 200))
    os.utime(old_archive, (200, 200))
    os.utime(new_archive / "FIX.md", (300, 300))
    os.utime(new_archive, (300, 300))
    monkeypatch.setattr(inventory, "_run_command", _stub_commands())

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task="shared")
    historical = data["historical_candidates"]

    assert [candidate["slug"] for candidate in historical[:3]] == ["shared-a", "shared-b", "shared-c"]
    assert "archive:new" in historical[0]["basis"]
    assert "Newest archive" in historical[0]["summary_excerpt"]
    assert "Old archive" not in historical[0]["summary_excerpt"]


def test_json_payload_cap_drops_historical_before_mandatory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans_root = tmp_path / "base" / "plans"
    plan_dir = plans_root / "demo-plan"
    _write_plan(plan_dir)
    for index in range(50):
        slug = f"json-cap-{index:02d}"
        historical = plans_root / slug
        _write_plan(historical, slug=slug)
        (historical / "SPEC.md").write_text(
            f"---\nartifact_kind: SPEC\nslug: {slug}\n---\n# {slug}\n\n## Approach\n- {'x' * 1500}\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(inventory, "MAX_JSON_PAYLOAD_BYTES", 6000)
    monkeypatch.setattr(inventory, "_run_command", _stub_commands())

    data = inventory.collect_inventory(command="/z-plan", slug="demo-plan", run_id="run", repo_root=repo, plan_dir=plan_dir, task="json cap")

    assert inventory._json_payload_size(data) <= inventory.MAX_JSON_PAYLOAD_BYTES
    assert [candidate["slug"] for candidate in data["mandatory_candidates"]] == ["demo-plan"]
    assert data["truncated"] is True
    assert any(key.endswith("json_cap") for key in data["dropped_counts"])
