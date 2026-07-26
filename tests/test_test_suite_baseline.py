"""Contracts for the immutable historical test-suite baseline (criterion #6)."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "test-suite-baseline.py"
MANIFESTS = REPO_ROOT / "tests" / "manifests"
SOURCE_COMMIT = "83b4a976cf68635131394d3169b69593180bad93"
SPEC = importlib.util.spec_from_file_location("test_suite_baseline", SCRIPT)
assert SPEC and SPEC.loader
baseline_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = baseline_tool
SPEC.loader.exec_module(baseline_tool)


def _documents() -> tuple[
    dict[str, object], dict[str, object], dict[str, object], dict[str, object]
]:
    baseline = json.loads((MANIFESTS / "test-suite-baseline.json").read_text(encoding="utf-8"))
    prune = json.loads((MANIFESTS / "test-prune-provenance.json").read_text(encoding="utf-8"))
    recording_path = os.environ.get("Z_HARNESS_RECORDING_SNAPSHOT")
    if not recording_path:
        pytest.skip("retained post-refactor evidence is archived and verified by T012")
    snapshot = json.loads(Path(recording_path).read_text(encoding="utf-8"))
    equivalence = baseline_tool.build_equivalence(baseline, snapshot)
    return baseline, prune, equivalence, snapshot


def _canonical_digest(value: object) -> str:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    return hashlib.sha256(payload).hexdigest()


def test_normalization_is_path_and_order_stable(tmp_path: Path) -> None:
    checkout = tmp_path / "arbitrary" / "checkout"
    first = f"{checkout}/tests/test_b.py::test_second\n{checkout}/scripts/test_a.py::test_first\n"
    second = "scripts/test_a.py::test_first\ntests/test_b.py::test_second\n"

    assert baseline_tool.normalize_node_ids(first, checkout) == baseline_tool.normalize_node_ids(second)


def test_standalone_execution_is_isolated_from_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    (source / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "seed.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Recorder Test",
            "-c",
            "user.email=recorder@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "seed",
        ],
        check=True,
    )
    base_state = source / ".z-harness-base"
    base_state.mkdir()
    (base_state / "sentinel").write_text("primary\n", encoding="utf-8")
    observed = tmp_path / "standalone-observed"
    script = source / "assert-clean-config.sh"
    script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
[[ "$XDG_CACHE_HOME" != "/host/user/cache" ]]
[[ "$XDG_CONFIG_HOME" != "/host/user/config" ]]
[[ "$XDG_DATA_HOME" != "/host/user/data" ]]
[[ "$XDG_RUNTIME_DIR" != "/host/user/runtime" ]]
[[ "$XDG_STATE_HOME" != "/host/user/state" ]]
[[ "$PWD" != "{source}" ]]
[[ ! -e .z-harness-base ]]
mv .git .git-original
mkdir .git .z-harness-base
printf '%s\n' "$PWD" > "{observed}"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CACHE_HOME", "/host/user/cache")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/host/user/config")
    monkeypatch.setenv("XDG_DATA_HOME", "/host/user/data")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/host/user/runtime")
    monkeypatch.setenv("XDG_STATE_HOME", "/host/user/state")

    assert baseline_tool._execute_current_standalone(
        source, ["shell:assert-clean-config.sh"]
    ) == [{"id": "shell:assert-clean-config.sh", "exit_code": 0, "status": "passed"}]
    assert not Path(observed.read_text(encoding="utf-8").strip()).exists()
    assert (source / ".git").is_dir()
    assert (base_state / "sentinel").read_text(encoding="utf-8") == "primary\n"


@pytest.mark.parametrize("force_failure", [False, True])
def test_full_suite_executes_and_cleans_from_disposable_dirty_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, force_failure: bool
) -> None:
    source = tmp_path / "dirty-source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    (source / "tracked.txt").write_text("committed\n", encoding="utf-8")
    (source / "deleted.txt").write_text("remove after commit\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "tracked.txt", "deleted.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Recorder Test",
            "-c",
            "user.email=recorder@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "seed",
        ],
        check=True,
    )
    (source / "tracked.txt").write_text("dirty modification\n", encoding="utf-8")
    (source / "deleted.txt").unlink()
    (source / "safe-target.txt").write_text("source only\n", encoding="utf-8")
    (source / "safe-link.txt").symlink_to("safe-target.txt")
    for root in baseline_tool.CANONICAL_ROOTS:
        (source / root).mkdir()
    base_state = source / ".z-harness-base"
    base_state.mkdir()
    (base_state / "sentinel").write_text("primary\n", encoding="utf-8")
    observed = tmp_path / "observed.json"
    child_test = source / "tests" / "test_disposable_child.py"
    child_test.write_text(
        """from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def test_disposable_child() -> None:
    source = Path(os.environ["RECORDER_SOURCE_ROOT"]).resolve()
    execution_root = Path.cwd().resolve()
    recording_path = Path(os.environ["Z_HARNESS_RECORDING_SNAPSHOT"])
    assert execution_root != source
    assert recording_path.is_file()
    assert (execution_root / "tracked.txt").read_text(encoding="utf-8") == "dirty modification\\n"
    assert not (execution_root / "deleted.txt").exists()
    assert (execution_root / "safe-link.txt").read_text(encoding="utf-8") == "source only\\n"
    (execution_root / "safe-link.txt").write_text("clone only\\n", encoding="utf-8")
    assert not (execution_root / ".z-harness-base").exists()
    shutil.rmtree(execution_root / ".git")
    (execution_root / ".git").mkdir()
    (execution_root / ".z-harness-base").mkdir()
    Path(os.environ["RECORDER_OBSERVED_PATH"]).write_text(
        json.dumps({"execution_root": str(execution_root), "recording_path": str(recording_path)}),
        encoding="utf-8",
    )
    assert os.environ["RECORDER_FORCE_FAILURE"] == "0"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("RECORDER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("RECORDER_OBSERVED_PATH", str(observed))
    monkeypatch.setenv("RECORDER_FORCE_FAILURE", "1" if force_failure else "0")

    if force_failure:
        with pytest.raises(baseline_tool.BaselineError, match="pytest execution failed"):
            baseline_tool._execute_current_pytest(source, {"temporary": "candidate"})
    else:
        result = baseline_tool._execute_current_pytest(source, {"temporary": "candidate"})
        assert result["cases"] == 1
        assert result["failures"] == 0

    child_paths = json.loads(observed.read_text(encoding="utf-8"))
    assert not Path(child_paths["execution_root"]).exists()
    assert not Path(child_paths["recording_path"]).exists()
    assert (source / ".git").is_dir()
    assert (base_state / "sentinel").read_text(encoding="utf-8") == "primary\n"
    assert (source / "safe-target.txt").read_text(encoding="utf-8") == "source only\n"


@pytest.mark.parametrize("anchor_name", [".git", ".z-harness-base"])
def test_disposable_copy_rejects_symlinks_into_primary_anchors(
    tmp_path: Path, anchor_name: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    (source / "tracked.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Recorder Test",
            "-c",
            "user.email=recorder@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "seed",
        ],
        check=True,
    )
    anchor = source / anchor_name
    if anchor_name == ".z-harness-base":
        anchor.mkdir()
    sentinel = anchor / "recorder-sentinel"
    sentinel.write_text("primary\n", encoding="utf-8")
    (source / "anchor-escape").symlink_to(anchor)
    script = source / "mutate-anchor.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf 'mutated\\n' > anchor-escape/recorder-sentinel\n",
        encoding="utf-8",
    )

    with pytest.raises(baseline_tool.BaselineError, match="excluded source anchor"):
        baseline_tool._execute_current_standalone(source, ["shell:mutate-anchor.sh"])

    assert sentinel.read_text(encoding="utf-8") == "primary\n"


def test_disposable_copy_rejects_symlinks_outside_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    (source / "tracked.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "tracked.txt"], check=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("primary\n", encoding="utf-8")
    (source / "outside-escape").symlink_to(outside)
    script = source / "mutate-outside.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'mutated\\n' > outside-escape\n",
        encoding="utf-8",
    )

    with pytest.raises(baseline_tool.BaselineError, match="escapes disposable checkout"):
        baseline_tool._execute_current_standalone(source, ["shell:mutate-outside.sh"])

    assert outside.read_text(encoding="utf-8") == "primary\n"


def test_disposable_copy_excludes_ignored_venv_interpreter_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    (source / "tracked.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Recorder Test",
            "-c",
            "user.email=recorder@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "seed",
        ],
        check=True,
    )
    venv = source / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / ".gitignore").write_text("*\n", encoding="utf-8")
    external_interpreter = tmp_path / "python3"
    external_interpreter.write_text("ambient interpreter\n", encoding="utf-8")
    (venv / "bin" / "python3").symlink_to(external_interpreter)

    with baseline_tool._disposable_working_copy(source) as checkout:
        assert not (checkout / ".venv" / "bin").exists()


def test_disposable_copy_rejects_tracked_venv_interpreter_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    (source / ".gitignore").write_text(".venv/*\n", encoding="utf-8")
    (source / ".venv" / "bin").mkdir(parents=True)
    external_interpreter = tmp_path / "python3"
    external_interpreter.write_text("candidate interpreter\n", encoding="utf-8")
    interpreter_link = source / ".venv" / "bin" / "python3"
    interpreter_link.symlink_to(external_interpreter)
    subprocess.run(
        ["git", "-C", str(source), "add", ".gitignore", "-f", str(interpreter_link)],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Recorder Test",
            "-c",
            "user.email=recorder@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "tracked interpreter link",
        ],
        check=True,
    )

    with pytest.raises(baseline_tool.BaselineError, match="escapes disposable checkout"):
        with baseline_tool._disposable_working_copy(source):
            pass


def test_record_current_retains_no_candidate_when_execution_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "test-suite-baseline.json").write_text("{}\n", encoding="utf-8")
    retained_snapshot = b'{"retained":"snapshot"}\n'
    retained_equivalence = b'{"retained":"equivalence"}\n'
    snapshot_path = manifest_dir / "test-suite-after.json"
    equivalence_path = manifest_dir / "coverage-equivalence.json"
    snapshot_path.write_bytes(retained_snapshot)
    equivalence_path.write_bytes(retained_equivalence)

    def fail_execution(repo_root: Path) -> dict[str, object]:
        raise baseline_tool.BaselineError(f"forced execution failure in {repo_root}")

    monkeypatch.setattr(baseline_tool, "build_current_snapshot", fail_execution)

    with pytest.raises(baseline_tool.BaselineError, match="forced execution failure"):
        baseline_tool.main(
            [
                "record-current",
                "--manifest-dir",
                str(manifest_dir),
                "--repo-root",
                str(tmp_path),
            ]
        )

    assert snapshot_path.read_bytes() == retained_snapshot
    assert equivalence_path.read_bytes() == retained_equivalence


@pytest.mark.parametrize("failed_name", ["test-suite-after.json", "coverage-equivalence.json"])
def test_record_current_recovers_both_documents_when_pair_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_name: str
) -> None:
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "test-suite-baseline.json").write_text("{}\n", encoding="utf-8")
    retained_snapshot = b'{"retained":"snapshot"}\n'
    retained_equivalence = b'{"retained":"equivalence"}\n'
    snapshot_path = manifest_dir / "test-suite-after.json"
    equivalence_path = manifest_dir / "coverage-equivalence.json"
    snapshot_path.write_bytes(retained_snapshot)
    equivalence_path.write_bytes(retained_equivalence)
    monkeypatch.setattr(baseline_tool, "build_current_snapshot", lambda repo_root: {"new": "snapshot"})
    monkeypatch.setattr(
        baseline_tool,
        "build_equivalence",
        lambda baseline, snapshot: {"new": "equivalence"},
    )
    real_replace = baseline_tool.os.replace
    failed = False

    def fail_selected_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal failed
        if not failed and Path(destination).name == failed_name:
            failed = True
            raise OSError("forced pair publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(baseline_tool.os, "replace", fail_selected_replace)

    with pytest.raises(OSError, match="forced pair publication failure"):
        baseline_tool.main(
            [
                "record-current",
                "--manifest-dir",
                str(manifest_dir),
                "--repo-root",
                str(tmp_path),
            ]
        )

    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == {"new": "snapshot"}
    assert json.loads(equivalence_path.read_text(encoding="utf-8")) == {"new": "equivalence"}
    assert not (manifest_dir / baseline_tool._PAIR_TRANSACTION_NAME).exists()


@pytest.mark.parametrize(
    "crash_destination",
    [
        ".test-suite-recording.transaction.json",
        "test-suite-after.json",
        "coverage-equivalence.json",
    ],
)
def test_abrupt_pair_publication_recovers_before_evidence_is_loaded(
    tmp_path: Path, crash_destination: str
) -> None:
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    snapshot_path = manifest_dir / "test-suite-after.json"
    equivalence_path = manifest_dir / "coverage-equivalence.json"
    snapshot_path.write_text('{"generation":"old-snapshot"}\n', encoding="utf-8")
    equivalence_path.write_text('{"generation":"old-equivalence"}\n', encoding="utf-8")
    child = """
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("crash_baseline_tool", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
directory = Path(sys.argv[2])
crash_destination = sys.argv[3]
real_replace = module.os.replace

def crash_after_replace(source, destination):
    real_replace(source, destination)
    if Path(destination).name == crash_destination:
        os._exit(91)

module.os.replace = crash_after_replace
module._publish_json_pair(
    directory / "test-suite-after.json",
    {"generation": "new-snapshot"},
    directory / "coverage-equivalence.json",
    {"generation": "new-equivalence"},
)
"""

    crashed = subprocess.run(
        [sys.executable, "-c", child, str(SCRIPT), str(manifest_dir), crash_destination],
        check=False,
    )

    assert crashed.returncode == 91
    snapshot, equivalence = baseline_tool._load_json_pair(snapshot_path, equivalence_path)
    assert snapshot == {"generation": "new-snapshot"}
    assert equivalence == {"generation": "new-equivalence"}
    assert not (manifest_dir / baseline_tool._PAIR_TRANSACTION_NAME).exists()


def test_checked_snapshot_is_the_exact_pre_plan_collection() -> None:
    baseline, prune, equivalence, snapshot = _documents()
    baseline_tool.check_manifests(baseline, prune, equivalence, snapshot, REPO_ROOT)

    assert baseline["source"]["commit"] == SOURCE_COMMIT
    assert baseline["pytest"]["counts_by_root"] == {"runtime": 354, "scripts": 400, "tests": 4269}
    assert baseline["pytest"]["total"] == 5023
    assert baseline["pytest"]["execution_result"]["errors"] == 0
    assert prune["authorization"]["authorized_deletions"] == []
    assert equivalence["proposed_replacements"] == []
    assert equivalence["missing_baseline_ids"] == []
    assert snapshot["pytest"]["total"] >= baseline["pytest"]["total"]
    assert snapshot["pytest"]["execution_result"]["job_conclusion"] == "success"
    assert all(result["exit_code"] == 0 for result in snapshot["standalone"]["execution_results"])


def test_new_working_tree_tests_do_not_mutate_the_historical_snapshot(tmp_path: Path) -> None:
    baseline, prune, equivalence, snapshot = _documents()
    checkout = tmp_path / "post-baseline-checkout"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(REPO_ROOT), str(checkout)],
        check=True,
    )
    added = checkout / "tests" / "test_added_after_baseline.py"
    added.write_text("def test_added_after_baseline(): pass\n", encoding="utf-8")
    working_collection = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(added)],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    check_manifest_dir = MANIFESTS
    if os.environ.get("Z_HARNESS_RECORDING_SNAPSHOT"):
        check_manifest_dir = tmp_path / "recording-manifests"
        check_manifest_dir.mkdir()
        for name, document in (
            ("test-suite-baseline.json", baseline),
            ("test-prune-provenance.json", prune),
            ("coverage-equivalence.json", equivalence),
            ("test-suite-after.json", snapshot),
        ):
            (check_manifest_dir / name).write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    checked = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "check",
            "--manifest-dir",
            str(check_manifest_dir),
            "--repo-root",
            str(REPO_ROOT),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "test_added_after_baseline" in working_collection
    assert checked.stdout == ""
    assert all("test_added_after_baseline" not in node for node in baseline["pytest"]["node_ids"])


def test_equal_counts_cannot_substitute_a_different_test_identity() -> None:
    baseline, prune, equivalence, snapshot = _documents()
    changed = copy.deepcopy(baseline)
    changed["pytest"]["node_ids"][0] = "runtime/000_replacement.py::test_same_count"

    with pytest.raises(baseline_tool.BaselineError, match="semantic digest"):
        baseline_tool.check_manifests(changed, prune, equivalence, snapshot, REPO_ROOT)


def test_recomputed_digests_cannot_forge_a_historical_node_id() -> None:
    baseline, prune, equivalence, snapshot = _documents()
    changed_baseline = copy.deepcopy(baseline)
    changed_equivalence = copy.deepcopy(equivalence)
    forged = "tests/test_nonexistent_historical.py::test_forged"
    changed_baseline["pytest"]["node_ids"][0] = forged
    changed_baseline["pytest"]["node_ids"].sort()
    changed_baseline["pytest"]["counts_by_root"] = {
        root: sum(node.startswith(f"{root}/") for node in changed_baseline["pytest"]["node_ids"])
        for root in ("tests", "scripts", "runtime")
    }
    semantic_payload = {
        "node_ids": changed_baseline["pytest"]["node_ids"],
        "standalone_ids": changed_baseline["standalone"]["ids"],
        "inputs": changed_baseline["semantic_inputs"],
    }
    changed_baseline["semantic_sha256"] = _canonical_digest(semantic_payload)
    retained = [*changed_baseline["pytest"]["node_ids"], *changed_baseline["standalone"]["ids"]]
    changed_equivalence["baseline_semantic_sha256"] = changed_baseline["semantic_sha256"]
    changed_equivalence["retained_ids"] = retained
    changed_equivalence["equivalence_sha256"] = _canonical_digest(
        {
            "baseline_semantic_sha256": changed_baseline["semantic_sha256"],
            "retained_ids": retained,
        }
    )

    with pytest.raises(baseline_tool.BaselineError, match="fresh collection"):
        baseline_tool.check_manifests(
            changed_baseline, prune, changed_equivalence, snapshot, REPO_ROOT
        )


@pytest.mark.parametrize(
    ("document", "path", "value", "message"),
    [
        ("prune", ("source", "run_id"), "forged-run", "source provenance"),
        ("prune", ("source", "source_commit"), "0" * 40, "source provenance"),
        ("prune", ("report", "sha256"), "0" * 64, "report provenance"),
        ("prune", ("report", "bytes"), 1, "report provenance"),
        ("prune", ("report", "lines"), 1, "report provenance"),
        ("prune", ("report", "schema", "total_candidates"), 1, "report provenance"),
        ("equivalence", ("baseline_commit",), "0" * 40, "different baseline commit"),
    ],
)
def test_prune_and_cross_manifest_provenance_is_fail_closed(
    document: str, path: tuple[str, ...], value: object, message: str
) -> None:
    baseline, prune, equivalence, snapshot = _documents()
    changed = copy.deepcopy(prune if document == "prune" else equivalence)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(baseline_tool.BaselineError, match=message):
        baseline_tool.check_manifests(
            baseline,
            changed if document == "prune" else prune,
            changed if document == "equivalence" else equivalence,
            snapshot,
            REPO_ROOT,
        )


def test_zero_deletion_authorization_is_fail_closed() -> None:
    baseline, prune, equivalence, snapshot = _documents()
    changed = copy.deepcopy(equivalence)
    changed["authorized_deletions"] = [baseline["pytest"]["node_ids"][0]]

    with pytest.raises(baseline_tool.BaselineError, match="zero deletions"):
        baseline_tool.check_manifests(baseline, prune, changed, snapshot, REPO_ROOT)


def test_post_refactor_snapshot_cannot_drop_a_frozen_identity() -> None:
    baseline, prune, equivalence, snapshot = _documents()
    changed = copy.deepcopy(snapshot)
    changed["pytest"]["node_ids"][0] = "runtime/new_replacement.py::test_same_count"
    changed["pytest"]["node_ids"].sort()

    with pytest.raises(baseline_tool.BaselineError, match="dropped frozen baseline identities"):
        baseline_tool.check_manifests(baseline, prune, equivalence, changed, REPO_ROOT)


def test_post_refactor_snapshot_requires_every_standalone_success() -> None:
    baseline, prune, equivalence, snapshot = _documents()
    changed = copy.deepcopy(snapshot)
    changed["standalone"]["execution_results"][0]["exit_code"] = 1
    changed["standalone"]["execution_results"][0]["status"] = "failed"

    with pytest.raises(baseline_tool.BaselineError, match="standalone outcomes"):
        baseline_tool.check_manifests(baseline, prune, equivalence, changed, REPO_ROOT)


def test_equivalence_is_bound_to_the_executed_post_refactor_snapshot() -> None:
    baseline, prune, equivalence, snapshot = _documents()
    changed = copy.deepcopy(equivalence)
    changed["post_refactor_semantic_sha256"] = "0" * 64

    with pytest.raises(baseline_tool.BaselineError, match="post-refactor semantic digest"):
        baseline_tool.check_manifests(baseline, prune, changed, snapshot, REPO_ROOT)


def test_equivalence_builder_rejects_an_implied_deletion() -> None:
    baseline, _, _, snapshot = _documents()
    changed = copy.deepcopy(snapshot)
    changed["pytest"]["node_ids"].remove(baseline["pytest"]["node_ids"][0])

    with pytest.raises(baseline_tool.BaselineError, match="dropped frozen baseline identities"):
        baseline_tool.build_equivalence(baseline, changed)
