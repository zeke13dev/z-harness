"""Hermetic black-box tests for the retained production memory surface."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run-memory-review.sh"


def _run(
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
    script: Path = _SCRIPT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=cwd,
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _review_fixture(tmp_path: Path, *, changed: bool = True) -> tuple[Path, dict[str, str]]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "remote", "add", "origin", str(tmp_path))
    _git(tmp_path, "fetch", "-q", "origin", "HEAD:refs/remotes/origin/main")
    if changed:
        (tmp_path / "change.txt").write_text("candidate\n", encoding="utf-8")
        _git(tmp_path, "add", "change.txt")
        _git(tmp_path, "commit", "-qm", "candidate")

    plan = tmp_path / "z-harness" / "plan"
    plan.mkdir(parents=True)
    (plan / "TASKS.md").write_text("## T001 — done `[x]`\n", encoding="utf-8")
    llm = tmp_path / "docs" / "llm"
    llm.mkdir(parents=True)
    (llm / "TAGS.txt").write_text("correctness\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "Z_HARNESS_PLAN_DIR": str(plan),
            "Z_HARNESS_SLUG": "plan",
            "ANTIGRAVITY_PLUGIN_ROOT": "/nonexistent",
            "CLAUDE_PLUGIN_ROOT": "/nonexistent",
        }
    )
    env.pop("Z_HARNESS_RELEASE_SURFACE", None)
    return plan, env


def _author_fixture(tmp_path: Path, *, tags: bool = True) -> Path:
    _git(tmp_path, "init", "-q")
    llm = tmp_path / "docs" / "llm"
    llm.mkdir(parents=True)
    (llm / "INDEX.json").write_text(
        json.dumps({"version": "1", "concepts": []}) + "\n", encoding="utf-8"
    )
    if tags:
        (llm / "TAGS.txt").write_text("correctness\n", encoding="utf-8")
    return llm


def _candidate(path: Path, text: str, *, slug: str = "release-memory") -> None:
    path.write_text(
        json.dumps(
            {
                "type": "incident",
                "text": text,
                "tags": ["correctness"],
                "suggested_concept_slug": slug,
            }
        ),
        encoding="utf-8",
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _refresh_driver(path: Path, body: str) -> Path:
    path.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_unset_surface_in_installed_tree_never_dispatches_axiom(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plan, env = _review_fixture(repo)
    installed = tmp_path / "installed"
    (installed / "scripts").mkdir(parents=True)
    (installed / "runtime").mkdir()
    shutil.copy2(_SCRIPT, installed / "scripts" / _SCRIPT.name)
    shutil.copy2(_REPO_ROOT / "runtime" / "__init__.py", installed / "runtime" / "__init__.py")
    shutil.copy2(_REPO_ROOT / "runtime" / "release_surface.py", installed / "runtime" / "release_surface.py")

    result = _run(
        "run-1", "implement-all", cwd=repo, env=env,
        script=installed / "scripts" / _SCRIPT.name,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "STATUS: ready"
    assert Path(result.stdout.splitlines()[1]) == plan / "archive" / "run-1" / "cumulative.diff"
    assert "AXIOM_STATUS: skipped prod_surface" in result.stdout
    assert "AXIOM_READY " not in result.stdout


def test_review_no_op_and_malformed_statuses_are_deterministic(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _plan, env = _review_fixture(repo, changed=False)
    empty = _run("run-1", "implement-all", cwd=repo, env=env)
    malformed = _run(cwd=repo, env=env)

    assert empty.stdout.splitlines() == ["STATUS: skipped empty_diff"]
    assert malformed.stdout.splitlines() == ["STATUS: skipped missing_args"]


def test_candidate_create_uses_valid_source_and_refresh_status(tmp_path: Path) -> None:
    llm = _author_fixture(tmp_path)
    candidate = tmp_path / "candidate.json"
    _candidate(candidate, "Keep installed prod memory paths executable")

    result = _run("author", "--from-candidate-json", str(candidate), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "STATUS: ok" in result.stdout
    assert "HUMAN_REFRESH: skipped unsupported_driver" in result.stdout
    concept = json.loads((llm / "release-memory.json").read_text(encoding="utf-8"))
    assert concept["memories"][0]["source"] == "human_review:memory-review"
    assert (llm / "MEMORIES-FLAT.md").is_file()
    index = json.loads((llm / "INDEX.json").read_text(encoding="utf-8"))
    assert [item["slug"] for item in index["concepts"]] == ["release-memory"]


def test_edit_delete_and_no_refresh_execute_observable_mutations(tmp_path: Path) -> None:
    llm = _author_fixture(tmp_path)
    first = tmp_path / "first.json"
    replacement = tmp_path / "replacement.json"
    _candidate(first, "Original durable lesson")
    _candidate(replacement, "Replacement durable lesson")
    assert "STATUS: ok" in _run("author", "--from-candidate-json", str(first), cwd=tmp_path).stdout

    edited = _run(
        "author", "--edit", "release-memory", "0",
        "--from-candidate-json", str(replacement), "--no-refresh-human", cwd=tmp_path,
    )
    concept = json.loads((llm / "release-memory.json").read_text(encoding="utf-8"))
    deleted = _run("author", "--delete", "release-memory", "0", cwd=tmp_path)
    after_delete = json.loads((llm / "release-memory.json").read_text(encoding="utf-8"))

    assert "HUMAN_REFRESH: skipped no_refresh" in edited.stdout
    assert concept["memories"][0]["text"] == "Replacement durable lesson"
    assert "MEMORIES_WRITTEN: 0" in deleted.stdout
    assert after_delete["memories"] == []


def test_dry_run_and_malformed_candidate_never_seed_tags_or_mutate(tmp_path: Path) -> None:
    llm = _author_fixture(tmp_path, tags=False)
    candidate = tmp_path / "candidate.json"
    _candidate(candidate, "Preview without writes")
    before = (llm / "INDEX.json").read_bytes()

    dry_run = _run(
        "author", "--from-candidate-json", str(candidate), "--dry-run", cwd=tmp_path
    )
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{", encoding="utf-8")
    malformed = _run(
        "author", "--from-candidate-json", str(malformed_path), cwd=tmp_path
    )

    assert "STATUS: ok" in dry_run.stdout
    assert "HUMAN_REFRESH: skipped dry_run" in dry_run.stdout
    assert "STATUS: bad_input" in malformed.stdout
    assert (llm / "INDEX.json").read_bytes() == before
    assert sorted(path.name for path in llm.iterdir()) == ["INDEX.json"]


def test_structurally_invalid_index_members_are_bad_input_without_writes(
    tmp_path: Path,
) -> None:
    for name, member in (("scalar", 7), ("malformed-object", {"slug": []})):
        repo = tmp_path / name
        repo.mkdir()
        llm = _author_fixture(repo)
        (llm / "INDEX.json").write_text(
            json.dumps({"version": "1", "concepts": [member]}) + "\n",
            encoding="utf-8",
        )
        candidate = repo / "candidate.json"
        _candidate(candidate, f"Reject the {name} index member")
        before = _tree_bytes(llm)

        result = _run(
            "author", "--from-candidate-json", str(candidate), cwd=repo
        )

        assert result.returncode == 0, result.stderr
        assert "STATUS: bad_input" in result.stdout
        assert "WROTE:\n" in result.stdout
        assert _tree_bytes(llm) == before
        assert not (llm / "release-memory.json").exists()
        assert not list(repo.glob(".memory-prepare.*"))


def test_routing_preference_creates_registered_flattened_memory(tmp_path: Path) -> None:
    llm = _author_fixture(tmp_path)

    result = _run(
        "author", "--kind", "routing-preference", "--question-id", "workflow.audit_to_amend",
        "--value", "amend", "--strength", "very_strong", "--scope", "global",
        "--reason", "Preserve the reviewed workflow", cwd=tmp_path,
    )

    assert "STATUS: ok" in result.stdout
    workflow = json.loads((llm / "workflow.json").read_text(encoding="utf-8"))
    assert workflow["memories"][0]["question_id"] == "workflow.audit_to_amend"
    assert "routing-preference" in (llm / "MEMORIES-FLAT.md").read_text(encoding="utf-8")


def test_bad_delete_index_is_no_write(tmp_path: Path) -> None:
    llm = _author_fixture(tmp_path)
    concept = llm / "release-memory.json"
    concept.write_text(json.dumps({"concept": "release-memory", "memories": []}) + "\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in llm.iterdir()}

    result = _run("author", "--delete", "release-memory", "4", cwd=tmp_path)

    assert "STATUS: bad_input" in result.stdout
    assert {path.name: path.read_bytes() for path in llm.iterdir()} == before


def test_regeneration_failure_never_publishes_or_leaves_temp_debris(tmp_path: Path) -> None:
    llm = _author_fixture(tmp_path, tags=False)
    (llm / "unrelated-broken.json").write_text("{", encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    _candidate(candidate, "Rollback a failed regeneration")
    before = _tree_bytes(llm)

    result = _run("author", "--from-candidate-json", str(candidate), cwd=tmp_path)

    assert "STATUS: bad_input" in result.stdout
    assert "WROTE:\n" in result.stdout
    assert _tree_bytes(llm) == before
    assert not (llm / "release-memory.json").exists()
    assert not list(tmp_path.glob(".memory-prepare.*"))


def test_nth_publication_failure_restores_complete_memory_tree(tmp_path: Path) -> None:
    llm = _author_fixture(tmp_path, tags=False)
    (llm / "unrelated.txt").write_bytes(b"preserve-me\x00exactly")
    candidate = tmp_path / "candidate.json"
    _candidate(candidate, "Rollback a partial publication")
    before = _tree_bytes(llm)
    env = os.environ.copy()
    env["Z_HARNESS_MEMORY_FAIL_REPLACE_AT"] = "3"

    result = _run(
        "author", "--from-candidate-json", str(candidate), cwd=tmp_path, env=env
    )

    assert "STATUS: bad_input" in result.stdout
    assert "publication rolled back" in result.stdout
    assert _tree_bytes(llm) == before
    assert not list(llm.glob(".*.rollback.*"))
    assert not list(tmp_path.glob(".memory-prepare.*"))


def test_refresh_success_receives_honest_deterministic_request(tmp_path: Path) -> None:
    llm = _author_fixture(tmp_path)
    candidate = tmp_path / "candidate.json"
    _candidate(candidate, "Refresh the matching human concept")
    request_path = tmp_path / "request.json"
    driver = _refresh_driver(
        tmp_path / "refresh-driver",
        """import json, os, pathlib, sys
request = json.load(sys.stdin)
pathlib.Path(os.environ[\"REQUEST_CAPTURE\"]).write_text(
    json.dumps(request, sort_keys=True), encoding=\"utf-8\"
)
print(json.dumps({\"status\": \"ok\", \"memories_preserved\": request[\"post_count\"]}))""",
    )
    env = os.environ.copy()
    env.update(
        Z_HARNESS_MEMORY_REFRESH_DRIVER=str(driver),
        REQUEST_CAPTURE=str(request_path),
    )

    result = _run(
        "author", "--from-candidate-json", str(candidate), cwd=tmp_path, env=env
    )

    assert "HUMAN_REFRESH: ready" in result.stdout
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request == {
        "agent": "doc-updater",
        "concept": "release-memory",
        "human_path": str(tmp_path / "docs" / "human" / "release-memory.md"),
        "llm_path": str(llm / "release-memory.json"),
        "mode": "write",
        "post_count": 1,
        "reason": "memory_write",
        "repository": str(tmp_path),
        "source_files": [],
    }


def test_refresh_failures_are_skipped_without_rolling_back_commit(tmp_path: Path) -> None:
    bodies = {
        "nonzero": "import sys; sys.exit(7)",
        "malformed": "print('not-json')",
        "count-mismatch": (
            "import json; print(json.dumps({\"status\": \"ok\", "
            "\"memories_preserved\": 99}))"
        ),
    }
    for name, body in bodies.items():
        repo = tmp_path / name
        repo.mkdir()
        llm = _author_fixture(repo)
        candidate = repo / "candidate.json"
        _candidate(candidate, f"Keep canonical memory after {name}")
        driver = _refresh_driver(repo / "refresh-driver", body)
        env = os.environ.copy()
        env["Z_HARNESS_MEMORY_REFRESH_DRIVER"] = str(driver)

        result = _run(
            "author", "--from-candidate-json", str(candidate), cwd=repo, env=env
        )

        assert "STATUS: ok" in result.stdout
        assert "HUMAN_REFRESH: skipped updater_failed" in result.stdout
        concept = json.loads((llm / "release-memory.json").read_text(encoding="utf-8"))
        assert len(concept["memories"]) == 1
        assert (llm / "MEMORIES-FLAT.md").is_file()


def test_boolean_refresh_counts_are_not_accepted_as_integers(tmp_path: Path) -> None:
    cases = (("nonzero", True, "append"), ("zero", False, "delete"))
    for name, preserved, operation in cases:
        repo = tmp_path / name
        repo.mkdir()
        llm = _author_fixture(repo)
        candidate = repo / "candidate.json"
        _candidate(candidate, f"Reject boolean count for {name}")
        if operation == "delete":
            created = _run(
                "author", "--from-candidate-json", str(candidate),
                "--no-refresh-human", cwd=repo,
            )
            assert "STATUS: ok" in created.stdout
            arguments = ("author", "--delete", "release-memory", "0")
        else:
            arguments = ("author", "--from-candidate-json", str(candidate))
        driver = _refresh_driver(
            repo / "refresh-driver",
            f"import json; print(json.dumps({{'status': 'ok', 'memories_preserved': {preserved!r}}}))",
        )
        env = os.environ.copy()
        env["Z_HARNESS_MEMORY_REFRESH_DRIVER"] = str(driver)

        result = _run(*arguments, cwd=repo, env=env)

        assert "STATUS: ok" in result.stdout
        assert "HUMAN_REFRESH: skipped updater_failed" in result.stdout
        concept = json.loads((llm / "release-memory.json").read_text(encoding="utf-8"))
        assert len(concept["memories"]) == (1 if operation == "append" else 0)


def test_no_refresh_never_invokes_available_driver(tmp_path: Path) -> None:
    _author_fixture(tmp_path)
    candidate = tmp_path / "candidate.json"
    _candidate(candidate, "Do not dispatch the optional updater")
    marker = tmp_path / "driver-ran"
    driver = _refresh_driver(
        tmp_path / "refresh-driver",
        "import os, pathlib; pathlib.Path(os.environ['DRIVER_MARKER']).touch()",
    )
    env = os.environ.copy()
    env.update(
        Z_HARNESS_MEMORY_REFRESH_DRIVER=str(driver),
        DRIVER_MARKER=str(marker),
    )

    result = _run(
        "author", "--from-candidate-json", str(candidate), "--no-refresh-human",
        cwd=tmp_path, env=env,
    )

    assert "HUMAN_REFRESH: skipped no_refresh" in result.stdout
    assert not marker.exists()
