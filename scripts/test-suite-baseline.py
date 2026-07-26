#!/usr/bin/env python3
"""Generate and verify the immutable pre-lane test-suite baseline.

The baseline is deliberately commit-addressed.  New tests on the working tree
must not change its meaning, and count equality is never accepted as coverage
equivalence.  The public surface is ``build_manifests``,
``build_current_snapshot``, ``build_equivalence``, ``check_manifests``, and the
``generate``/``record-current``/``check`` command-line interface. Paired
publication assumes one ``record-current`` writer per manifest directory;
readers recover its durable transaction marker before loading either document.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1
CANONICAL_ROOTS = ("tests", "scripts", "runtime")
COLLECTION_ARGS = ("python3", "-m", "pytest", "--collect-only", "-q", *CANONICAL_ROOTS)
STANDALONE_GLOBS = ("scripts/*test*.sh", "tests/*test*.sh")
STANDALONE_EXCLUDES = ("*research*",)
POST_REFACTOR_STANDALONE_EXCLUDES = (
    *STANDALONE_EXCLUDES,
    "scripts/run-network-isolated-tests.sh",
)
EXPLICIT_SELF_TESTS = (
    "scripts/overnight-preflight.sh",
    "scripts/normalize-task-state.sh",
)
SEMANTIC_CONFIG_PATHS = (
    "Makefile",
    "pyproject.toml",
    ".github/workflows/tests.yml",
)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PAIR_TRANSACTION_NAME = ".test-suite-recording.transaction.json"
_PAIR_TRANSACTION_SCHEMA = 1
_BASELINE_SOURCE = {
    "commit": "83b4a976cf68635131394d3169b69593180bad93",
    "commit_timestamp": "2026-07-21T14:08:56-07:00",
    "canonical_roots": list(CANONICAL_ROOTS),
    "collection_command": list(COLLECTION_ARGS),
    "collection_environment": {
        "python": "3.11",
        "pytest": "9.0.3",
        "runner_image": "ubuntu-latest",
    },
}
_EXECUTION_RESULT = {
    "by_root": {
        "runtime": {"cases": 354, "skipped": 0, "errors": 0, "failures": 0},
        "scripts": {"cases": 400, "skipped": 0, "errors": 0, "failures": 0},
        "tests": {"cases": 4269, "skipped": 23, "errors": 0, "failures": 0},
    },
    "cases": 5023,
    "skipped": 23,
    "errors": 0,
    "failures": 0,
    "job_conclusion": "success",
}
_PRUNE_SOURCE = {
    "artifact": "TEST-PRUNE.md",
    "plan_slug": "cheap-flow-test-prune",
    "run_id": "20260721T215719Z-test-prune",
}
_PRUNE_REPORT = {
    "sha256": "deb003aae252e2ace7afd02670760d184d2c6e83913f37b3c93448fd25e53199",
    "bytes": 633916,
    "lines": 6698,
    "bulk_survivors": 0,
    "integration_entries": 741,
    "first_task": "T-TP-001",
    "last_task": "T-TP-741",
}
_PRUNE_SCHEMA = {
    "artifact": "test-prune",
    "slug": "cheap-flow-test-prune",
    "run_id": "20260721T215719Z-test-prune",
    "generated_at": "2026-07-21T23:19:51Z",
    "total_candidates": 0,
    "high_confidence": 0,
    "med_confidence": 0,
    "low_confidence": 0,
    "integration_boundary": 741,
    "consult_available": True,
    "consult_degraded": True,
}


class BaselineError(ValueError):
    """Raised when baseline evidence is incomplete or internally inconsistent."""


def _run_git(repo_root: Path, *args: str) -> bytes:
    """Return stdout for a read-only Git query.

    Args:
        repo_root: Checkout whose object database contains the source commit.
        *args: Arguments following ``git -C <repo>``.

    Returns:
        Raw command stdout.

    Raises:
        subprocess.CalledProcessError: The commit or requested object is absent.
    """

    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
    ).stdout


@contextmanager
def _historical_checkout(repo_root: Path, source_commit: str) -> Iterator[Path]:
    """Yield a disposable checkout of an exact commit and always remove it.

    Args:
        repo_root: Checkout whose object database contains the source commit.
        source_commit: Full commit identifier to materialize.

    Yields:
        Path to a detached linked worktree at ``source_commit``.

    Raises:
        subprocess.CalledProcessError: The commit cannot be checked out or cleanup fails.
    """

    with tempfile.TemporaryDirectory(prefix="z-harness-baseline-") as temporary:
        checkout = Path(temporary) / "checkout"
        subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "add", "--detach", str(checkout), source_commit],
            check=True,
            capture_output=True,
        )
        try:
            yield checkout
        finally:
            subprocess.run(
                ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(checkout)],
                check=True,
                capture_output=True,
            )


def _source_inventory(
    repo_root: Path, source_commit: str
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Recollect exact IDs and inputs from an immutable Git commit.

    Args:
        repo_root: Checkout whose object database contains the source commit.
        source_commit: Full commit identifier to verify.

    Returns:
        Normalized pytest IDs, standalone IDs, and semantic inputs.

    Raises:
        BaselineError: Historical pytest collection fails.
        subprocess.CalledProcessError: Git cannot materialize the commit.
    """

    with _historical_checkout(repo_root, source_commit) as checkout:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(
            COLLECTION_ARGS,
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise BaselineError(f"historical pytest collection failed with exit {result.returncode}")
        nodes = normalize_node_ids(result.stdout, checkout)
    standalone = _standalone_ids(_tracked_paths(repo_root, source_commit))
    return nodes, standalone, _semantic_inputs(repo_root, source_commit, nodes, standalone)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _fsync_directory(path: Path) -> None:
    """Durably commit directory-entry changes or raise ``OSError``."""

    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_json(path: Path, value: object) -> None:
    """Write canonical JSON with same-directory atomic replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _recover_json_pair(first_path: Path, second_path: Path) -> bool:
    """Roll a durably announced paired publication forward to completion.

    The transaction marker is the commit record. It remains present until both
    fixed documents and their directory entries are durable, so repeating this
    function after any interruption is safe.

    Returns:
        ``True`` when an interrupted transaction was recovered, else ``False``.

    Raises:
        BaselineError: The marker is malformed or names a different pair.
        OSError: Recovery cannot durably replace both documents.
    """

    transaction_path = first_path.parent / _PAIR_TRANSACTION_NAME
    if not transaction_path.exists():
        return False
    try:
        transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError("paired JSON transaction marker is unreadable") from exc
    expected_fields = {
        "schema_version",
        "first_name",
        "first_value",
        "second_name",
        "second_value",
    }
    if not isinstance(transaction, dict) or set(transaction) != expected_fields:
        raise BaselineError("paired JSON transaction marker has an invalid shape")
    if (
        transaction["schema_version"] != _PAIR_TRANSACTION_SCHEMA
        or transaction["first_name"] != first_path.name
        or transaction["second_name"] != second_path.name
    ):
        raise BaselineError("paired JSON transaction marker names an unexpected document pair")
    _atomic_write_json(first_path, transaction["first_value"])
    _atomic_write_json(second_path, transaction["second_value"])
    transaction_path.unlink()
    _fsync_directory(first_path.parent)
    return True


def _publish_json_pair(
    first_path: Path,
    first_value: object,
    second_path: Path,
    second_value: object,
) -> None:
    """Publish two fixed JSON documents through a recoverable commit marker.

    Raises:
        BaselineError: Paths are invalid or an earlier marker is malformed.
        OSError: Publication fails after best-effort roll-forward recovery.
    """

    if first_path.parent != second_path.parent or first_path == second_path:
        raise BaselineError("paired JSON documents must have distinct same-directory paths")
    first_path.parent.mkdir(parents=True, exist_ok=True)
    _recover_json_pair(first_path, second_path)
    transaction_path = first_path.parent / _PAIR_TRANSACTION_NAME
    _atomic_write_json(
        transaction_path,
        {
            "schema_version": _PAIR_TRANSACTION_SCHEMA,
            "first_name": first_path.name,
            "first_value": first_value,
            "second_name": second_path.name,
            "second_value": second_value,
        },
    )
    try:
        _atomic_write_json(first_path, first_value)
        _atomic_write_json(second_path, second_value)
    except OSError:
        _recover_json_pair(first_path, second_path)
        raise
    transaction_path.unlink()
    _fsync_directory(first_path.parent)


def normalize_node_ids(collection_output: str, source_root: Path | None = None) -> list[str]:
    """Extract sorted, path-independent pytest node IDs from collect output.

    Args:
        collection_output: Text emitted by ``pytest --collect-only -q``.
        source_root: Optional absolute checkout prefix to remove.

    Returns:
        Unique node IDs sorted by Unicode code point.

    Raises:
        BaselineError: No nodes were found or a node escapes the canonical roots.
    """

    prefix = source_root.resolve().as_posix().rstrip("/") + "/" if source_root else None
    nodes: set[str] = set()
    for raw_line in collection_output.splitlines():
        line = _ANSI_ESCAPE.sub("", raw_line.strip()).replace("\\", "/")
        if prefix and line.startswith(prefix):
            line = line[len(prefix) :]
        line = line.removeprefix("./")
        if "::" not in line or not line.startswith(tuple(f"{root}/" for root in CANONICAL_ROOTS)):
            continue
        path = line.split("::", 1)[0]
        if "/../" in f"/{path}/" or path.startswith("/"):
            raise BaselineError(f"unsafe node id: {line}")
        nodes.add(line)
    if not nodes:
        raise BaselineError("collection output contained no canonical pytest node IDs")
    return sorted(nodes)


def _tracked_paths(repo_root: Path, source_commit: str) -> list[str]:
    raw = _run_git(repo_root, "ls-tree", "-r", "--name-only", source_commit).decode()
    return sorted(path for path in raw.splitlines() if path)


def _standalone_ids(tracked_paths: list[str]) -> list[str]:
    discovered = [
        path
        for path in tracked_paths
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in STANDALONE_GLOBS)
        and not any(fnmatch.fnmatchcase(path, pattern) for pattern in STANDALONE_EXCLUDES)
    ]
    missing = sorted(set(EXPLICIT_SELF_TESTS) - set(tracked_paths))
    if missing:
        raise BaselineError(f"explicit self-test paths absent at source commit: {missing}")
    return sorted(
        [*(f"shell:{path}" for path in discovered),
         *(f"shell:{path}::--self-test" for path in EXPLICIT_SELF_TESTS)]
    )


def _semantic_inputs(
    repo_root: Path, source_commit: str, node_ids: list[str], standalone_ids: list[str]
) -> list[dict[str, str]]:
    paths = {node.split("::", 1)[0] for node in node_ids}
    paths.update(identifier.removeprefix("shell:").split("::", 1)[0] for identifier in standalone_ids)
    tracked = set(_tracked_paths(repo_root, source_commit))
    paths.update(path for path in SEMANTIC_CONFIG_PATHS if path in tracked)
    return [
        {
            "path": path,
            "sha256": _sha256(_run_git(repo_root, "show", f"{source_commit}:{path}")),
        }
        for path in sorted(paths)
    ]


def _working_standalone_ids(repo_root: Path) -> list[str]:
    """Discover the current canonical standalone test identities.

    Args:
        repo_root: Working checkout containing the standalone test scripts.

    Returns:
        Sorted identifiers under the frozen standalone discovery contract.

    Raises:
        BaselineError: An explicit self-test is missing from the checkout.
    """

    paths = {
        path.relative_to(repo_root).as_posix()
        for pattern in STANDALONE_GLOBS
        for path in repo_root.glob(pattern)
        if path.is_file()
    }
    paths = {
        path
        for path in paths
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in POST_REFACTOR_STANDALONE_EXCLUDES)
    }
    paths.update(path for path in EXPLICIT_SELF_TESTS if (repo_root / path).is_file())
    return _standalone_ids(sorted(paths))


def _working_semantic_inputs(
    repo_root: Path, node_ids: list[str], standalone_ids: list[str]
) -> list[dict[str, str]]:
    """Hash every current source/config input that defines the suite.

    Args:
        repo_root: Working checkout containing the post-refactor suite.
        node_ids: Canonical current pytest identities.
        standalone_ids: Canonical current standalone identities.

    Returns:
        Sorted relative paths and SHA-256 content digests.

    Raises:
        OSError: A collected suite input cannot be read.
    """

    paths = {node.split("::", 1)[0] for node in node_ids}
    paths.update(identifier.removeprefix("shell:").split("::", 1)[0] for identifier in standalone_ids)
    paths.update(path for path in SEMANTIC_CONFIG_PATHS if (repo_root / path).is_file())
    return [
        {"path": path, "sha256": _sha256((repo_root / path).read_bytes())}
        for path in sorted(paths)
    ]


def _current_pytest_ids(repo_root: Path) -> list[str]:
    """Collect the current canonical pytest identities or fail hard.

    Raises:
        BaselineError: Current pytest collection fails.
    """

    result = subprocess.run(
        COLLECTION_ARGS,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BaselineError(f"current pytest collection failed with exit {result.returncode}")
    return normalize_node_ids(result.stdout, repo_root)


def _scoped_junit(junit_path: Path) -> dict[str, object]:
    root = ET.parse(junit_path).getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    by_root = {name: {"cases": 0, "skipped": 0, "errors": 0, "failures": 0} for name in CANONICAL_ROOTS}
    for suite in suites:
        for case in suite.findall("testcase"):
            area = case.get("classname", "").split(".", 1)[0]
            if area not in by_root:
                continue
            result = by_root[area]
            result["cases"] += 1
            result["skipped"] += int(case.find("skipped") is not None)
            result["errors"] += int(case.find("error") is not None)
            result["failures"] += int(case.find("failure") is not None)
    totals = {
        key: sum(int(area[key]) for area in by_root.values())
        for key in ("cases", "skipped", "errors", "failures")
    }
    return {"by_root": by_root, **totals}


def _execute_current_pytest(
    repo_root: Path, recording_snapshot: dict[str, object]
) -> dict[str, object]:
    """Execute all canonical pytest roots and summarize a successful JUnit run.

    Args:
        repo_root: Working checkout whose complete suite must pass.
        recording_snapshot: Optimistic in-memory candidate exposed only to the
            recorder's own manifest contract tests. It is never retained.

    Returns:
        Aggregate and per-root case outcomes.

    Raises:
        BaselineError: Pytest exits nonzero or does not emit readable JUnit XML.
    """

    with _disposable_working_copy(repo_root) as execution_root:
        with tempfile.TemporaryDirectory(prefix="z-harness-after-pytest-") as temporary:
            temporary_path = Path(temporary)
            junit_path = temporary_path / "pytest.xml"
            recording_path = temporary_path / "recording-snapshot.json"
            _atomic_write_json(recording_path, recording_snapshot)
            environment = os.environ.copy()
            environment["Z_HARNESS_RECORDING_SNAPSHOT"] = str(recording_path)
            result = subprocess.run(
                [sys.executable, "-m", "pytest", *CANONICAL_ROOTS, "--junitxml", str(junit_path)],
                cwd=execution_root,
                env=environment,
            )
            if result.returncode != 0:
                raise BaselineError(
                    f"post-refactor pytest execution failed with exit {result.returncode}"
                )
            try:
                summary = _scoped_junit(junit_path)
            except (OSError, ET.ParseError) as exc:
                raise BaselineError("post-refactor pytest did not emit valid JUnit evidence") from exc
    return {**summary, "job_conclusion": "success"}


@contextmanager
def _disposable_working_copy(repo_root: Path) -> Iterator[Path]:
    """Yield an independent Git checkout overlaid with the dirty working tree.

    The clone owns its object database, while the overlay preserves modified,
    deleted, and untracked implementation files. Root Git and z-harness state
    anchors are intentionally excluded so child tests can recreate them without
    mutating the recorder checkout or invalidating recorder teardown.

    Args:
        repo_root: Dirty implementation checkout to reproduce.

    Yields:
        Disposable checkout containing the exact non-anchor working tree.

    Raises:
        subprocess.CalledProcessError: Git cannot create or index the clone.
        BaselineError: An overlay symlink escapes the clone or reaches an anchor.
        OSError: The working tree cannot be copied or removed.
    """

    source_root = repo_root.resolve()
    _validate_overlay_symlinks(source_root)
    with tempfile.TemporaryDirectory(prefix="z-harness-after-checkout-") as temporary:
        checkout = Path(temporary) / "checkout"
        subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--no-checkout",
                "--no-hardlinks",
                str(source_root),
                str(checkout),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(checkout), "reset", "--mixed", "HEAD"],
            check=True,
            capture_output=True,
        )

        def exclude_overlay_paths(directory: str, names: list[str]) -> set[str]:
            current = Path(directory).resolve()
            excluded = _ignored_venv_names(source_root, current, names)
            if current == source_root:
                excluded.update({name for name in (".git", ".z-harness-base") if name in names})
            return excluded

        shutil.copytree(
            source_root,
            checkout,
            dirs_exist_ok=True,
            ignore=exclude_overlay_paths,
            symlinks=True,
        )
        yield checkout


def _validate_overlay_symlinks(source_root: Path) -> None:
    """Reject symlinks that would reconnect a disposable clone to source state.

    Relative symlinks whose fully resolved targets stay inside the non-anchor
    source tree remain safe because their copied targets rebase naturally into
    the clone. Absolute, escaping, and anchor-targeting links fail closed.

    Raises:
        BaselineError: A copied symlink resolves outside the safe overlay tree.
        OSError: The source tree cannot be inspected.
    """

    anchors = frozenset({".git", ".z-harness-base"})
    for directory, directory_names, file_names in os.walk(source_root, followlinks=False):
        current = Path(directory)
        ignored_names = _ignored_venv_names(source_root, current, [*directory_names, *file_names])
        directory_names[:] = [name for name in directory_names if name not in ignored_names]
        file_names = [name for name in file_names if name not in ignored_names]
        if current == source_root:
            directory_names[:] = [name for name in directory_names if name not in anchors]
            file_names = [name for name in file_names if name not in anchors]
        for name in [*directory_names, *file_names]:
            link = current / name
            if not link.is_symlink():
                continue
            raw_target = Path(os.readlink(link))
            try:
                target = link.resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                relative_link = link.relative_to(source_root)
                raise BaselineError(
                    f"overlay symlink cannot be safely resolved: {relative_link}"
                ) from exc
            try:
                relative_target = target.relative_to(source_root)
            except ValueError as exc:
                relative_link = link.relative_to(source_root)
                raise BaselineError(
                    f"overlay symlink escapes disposable checkout: {relative_link}"
                ) from exc
            if relative_target.parts and relative_target.parts[0] in anchors:
                relative_link = link.relative_to(source_root)
                raise BaselineError(
                    f"overlay symlink reaches excluded source anchor: {relative_link}"
                )
            if raw_target.is_absolute():
                relative_link = link.relative_to(source_root)
                raise BaselineError(
                    f"overlay symlink retains an absolute source target: {relative_link}"
                )


def _ignored_venv_names(source_root: Path, directory: Path, names: list[str]) -> set[str]:
    """Return repository-ignored ambient virtualenv entries at ``directory``.

    Tracked paths are intentionally not excluded: ``git check-ignore`` reports
    only ignored, untracked candidates, so tracked links and candidate paths
    outside ignored ambient virtualenv content remain fail-closed.
    """

    relative_directory = directory.relative_to(source_root)
    ignored: set[str] = set()
    for name in names:
        relative_path = relative_directory / name
        if not relative_path.parts or relative_path.parts[0] != ".venv":
            continue
        result = subprocess.run(
            ["git", "-C", str(source_root), "check-ignore", "--quiet", "--", str(relative_path)],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            ignored.add(name)
        elif result.returncode != 1:
            raise BaselineError(f"cannot determine overlay ignore status: {relative_path}")
    return ignored


def _execute_current_standalone(
    repo_root: Path, standalone_ids: list[str]
) -> list[dict[str, object]]:
    """Execute every canonical standalone test and retain only safe outcomes.

    Raw output is captured rather than copied into the manifest. This is a
    hard-fail recorder: every identity must exit zero.

    Args:
        repo_root: Working checkout containing the standalone scripts.
        standalone_ids: Exact sorted identities to execute once each.

    Returns:
        One successful outcome record per identity.

    Raises:
        BaselineError: Any standalone test exits nonzero.
    """

    outcomes: list[dict[str, object]] = []
    with _disposable_working_copy(repo_root) as execution_root:
        with tempfile.TemporaryDirectory(prefix="z-harness-after-xdg-") as xdg_root:
            xdg_paths = {
                name: Path(xdg_root) / suffix
                for name, suffix in (
                    ("XDG_CACHE_HOME", "cache"),
                    ("XDG_CONFIG_HOME", "config"),
                    ("XDG_DATA_HOME", "data"),
                    ("XDG_RUNTIME_DIR", "runtime"),
                    ("XDG_STATE_HOME", "state"),
                )
            }
            for path in xdg_paths.values():
                path.mkdir(mode=0o700)
            environment = os.environ.copy()
            environment.update({name: str(path) for name, path in xdg_paths.items()})
            for identifier in standalone_ids:
                target, separator, argument = identifier.removeprefix("shell:").partition("::")
                command = ["bash", target]
                if separator:
                    command.append(argument)
                result = subprocess.run(
                    command,
                    cwd=execution_root,
                    env=environment,
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise BaselineError(
                        f"post-refactor standalone execution failed for {identifier} "
                        f"with exit {result.returncode}"
                    )
                outcomes.append({"id": identifier, "exit_code": 0, "status": "passed"})
    return outcomes


def _prune_frontmatter(report: bytes) -> dict[str, object]:
    """Parse the small scalar frontmatter contract emitted by z-test-prune."""

    lines = report.decode("utf-8").splitlines()
    if len(lines) < 3 or lines[0] != "---":
        raise BaselineError("prune report is missing YAML frontmatter")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise BaselineError("prune report frontmatter is unterminated") from error
    values: dict[str, object] = {}
    for line in lines[1:closing]:
        key, separator, raw = line.partition(":")
        if not separator:
            raise BaselineError(f"invalid prune report frontmatter line: {line}")
        value = raw.strip()
        if value.isdigit():
            values[key] = int(value)
        elif value in {"true", "false"}:
            values[key] = value == "true"
        else:
            values[key] = value
    required = {
        "artifact",
        "slug",
        "run_id",
        "total_candidates",
        "high_confidence",
        "med_confidence",
        "low_confidence",
        "integration_boundary",
        "consult_available",
        "consult_degraded",
    }
    missing = sorted(required - values.keys())
    if missing:
        raise BaselineError(f"prune report frontmatter missing fields: {missing}")
    return values


def build_manifests(
    *,
    repo_root: Path,
    source_commit: str,
    junit_path: Path,
    runtime_profile_path: Path,
    prune_report_path: Path,
    prune_metadata_path: Path,
    python_version: str,
    pytest_version: str,
    runner_image: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Build the baseline, prune provenance, and exact-equivalence manifests."""

    nodes, standalone, inputs = _source_inventory(repo_root, source_commit)
    counts = {root: sum(node.startswith(f"{root}/") for node in nodes) for root in CANONICAL_ROOTS}
    junit = _scoped_junit(junit_path)
    profile = json.loads(runtime_profile_path.read_text(encoding="utf-8"))
    profile_counts = {root: profile["areas"][root]["cases"] for root in CANONICAL_ROOTS}
    if profile.get("source_sha") != source_commit or profile_counts != counts:
        raise BaselineError("runtime profile does not match source commit collection")
    if junit["cases"] != len(nodes):
        raise BaselineError("scoped JUnit cases do not match collected node IDs")

    source_timestamp = _run_git(repo_root, "show", "-s", "--format=%cI", source_commit).decode().strip()
    semantic_payload = {
        "node_ids": nodes,
        "standalone_ids": standalone,
        "inputs": inputs,
    }
    semantic_digest = _sha256(_canonical_json(semantic_payload))
    baseline: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "commit": source_commit,
            "commit_timestamp": source_timestamp,
            "canonical_roots": list(CANONICAL_ROOTS),
            "collection_command": list(COLLECTION_ARGS),
            "collection_environment": {
                "python": python_version,
                "pytest": pytest_version,
                "runner_image": runner_image,
            },
        },
        "pytest": {
            "node_ids": nodes,
            "counts_by_root": counts,
            "total": len(nodes),
            "execution_result": {**junit, "job_conclusion": "success"},
        },
        "standalone": {
            "glob_patterns": list(STANDALONE_GLOBS),
            "glob_excludes": list(STANDALONE_EXCLUDES),
            "explicit_self_tests": list(EXPLICIT_SELF_TESTS),
            "ids": standalone,
            "total": len(standalone),
        },
        "classifications": {
            "pytest": {root: root for root in CANONICAL_ROOTS},
            "standalone": "shell",
        },
        "semantic_inputs": inputs,
        "semantic_sha256": semantic_digest,
    }

    prune_metadata = json.loads(prune_metadata_path.read_text(encoding="utf-8"))
    report_bytes = prune_report_path.read_bytes()
    metadata_facts = {key: prune_metadata.get(key) for key in _PRUNE_REPORT}
    actual_report_facts = {
        "sha256": _sha256(report_bytes),
        "bytes": len(report_bytes),
        "lines": len(report_bytes.splitlines()),
    }
    if metadata_facts != _PRUNE_REPORT or actual_report_facts != {
        key: _PRUNE_REPORT[key] for key in actual_report_facts
    }:
        raise BaselineError("prune report digest does not match its write metadata")
    report_schema = _prune_frontmatter(report_bytes)
    if report_schema != _PRUNE_SCHEMA:
        raise BaselineError("prune report schema disagrees with the zero-deletion audit")
    prune: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            **_PRUNE_SOURCE,
            "source_commit": source_commit,
        },
        "report": {
            "format": "z-harness-test-prune-frontmatter-v1",
            "schema": report_schema,
            "sha256": prune_metadata["sha256"],
            "bytes": prune_metadata["bytes"],
            "lines": prune_metadata["lines"],
            "bulk_survivors": prune_metadata["bulk_survivors"],
            "integration_entries": prune_metadata["integration_entries"],
            "first_task": prune_metadata["first_task"],
            "last_task": prune_metadata["last_task"],
        },
        "authorization": {
            "authorized_deletions": [],
            "safe_to_delete": 0,
            "consult_degraded": True,
            "individual_integration_reviews_required": prune_metadata["integration_entries"],
        },
    }

    retained = [*nodes, *standalone]
    equivalence_payload = {"baseline_semantic_sha256": semantic_digest, "retained_ids": retained}
    equivalence: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "baseline_commit": source_commit,
        "baseline_semantic_sha256": semantic_digest,
        "equivalence_basis": "exact-id-and-semantic-input-hash",
        "count_only_equivalence": False,
        "retained_ids": retained,
        "proposed_replacements": [],
        "authorized_deletions": [],
        "equivalence_sha256": _sha256(_canonical_json(equivalence_payload)),
    }
    return baseline, prune, equivalence


def build_current_snapshot(repo_root: Path) -> dict[str, object]:
    """Collect and execute the complete post-refactor suite.

    The recorder derives identities independently from execution evidence and
    binds both to current semantic inputs. It has no success fallback: any
    collection or execution failure prevents a snapshot from being written.

    Args:
        repo_root: Working checkout containing the refactored suite.

    Returns:
        Canonical post-refactor snapshot document.

    Raises:
        BaselineError: Collection or execution is incomplete or unsuccessful.
        OSError: A suite input or executable cannot be read or started.
    """

    nodes = _current_pytest_ids(repo_root)
    standalone_ids = _working_standalone_ids(repo_root)
    inputs = _working_semantic_inputs(repo_root, nodes, standalone_ids)
    standalone_results = _execute_current_standalone(repo_root, standalone_ids)
    counts = {root: sum(node.startswith(f"{root}/") for node in nodes) for root in CANONICAL_ROOTS}
    semantic_payload = {
        "node_ids": nodes,
        "standalone_ids": standalone_ids,
        "inputs": inputs,
    }
    recording_result = {
        "by_root": {
            root: {"cases": cases, "skipped": 0, "errors": 0, "failures": 0}
            for root, cases in counts.items()
        },
        "cases": len(nodes),
        "skipped": 0,
        "errors": 0,
        "failures": 0,
        "job_conclusion": "success",
    }
    recording_snapshot = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "kind": "post-refactor-working-tree",
            "canonical_roots": list(CANONICAL_ROOTS),
            "collection_command": list(COLLECTION_ARGS),
            "execution_command": ["python3", "-m", "pytest", *CANONICAL_ROOTS],
            "collection_environment": {
                "python": platform.python_version(),
                "pytest": _pytest_version(repo_root),
            },
        },
        "pytest": {
            "node_ids": nodes,
            "counts_by_root": counts,
            "total": len(nodes),
            "execution_result": recording_result,
        },
        "standalone": {
            "glob_patterns": list(STANDALONE_GLOBS),
            "glob_excludes": list(POST_REFACTOR_STANDALONE_EXCLUDES),
            "explicit_self_tests": list(EXPLICIT_SELF_TESTS),
            "ids": standalone_ids,
            "total": len(standalone_ids),
            "execution_results": standalone_results,
        },
        "classifications": {
            "pytest": {root: root for root in CANONICAL_ROOTS},
            "standalone": "shell",
        },
        "semantic_inputs": inputs,
        "semantic_sha256": _sha256(_canonical_json(semantic_payload)),
    }
    pytest_result = _execute_current_pytest(repo_root, recording_snapshot)
    if pytest_result["cases"] != len(nodes):
        raise BaselineError("post-refactor JUnit cases do not match collected node IDs")
    return {
        **recording_snapshot,
        "pytest": {
            **recording_snapshot["pytest"],
            "execution_result": pytest_result,
        },
    }


def _pytest_version(repo_root: Path) -> str:
    """Return the executing pytest version or fail hard.

    Raises:
        BaselineError: The installed pytest version cannot be queried.
    """

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BaselineError("cannot query pytest version for post-refactor evidence")
    match = re.search(r"pytest (\S+)", result.stdout)
    if match is None:
        raise BaselineError("pytest version output is not recognized")
    return match.group(1)


def build_equivalence(
    baseline: dict[str, object], snapshot: dict[str, object]
) -> dict[str, object]:
    """Reconcile the post-refactor suite against every frozen identity.

    Args:
        baseline: Frozen pre-plan snapshot.
        snapshot: Executed post-refactor snapshot.

    Returns:
        Exact identity-based coverage equivalence document.

    Raises:
        BaselineError: A frozen identity is absent or deletion is implied.
    """

    baseline_ids = [*baseline["pytest"]["node_ids"], *baseline["standalone"]["ids"]]
    current_ids = [*snapshot["pytest"]["node_ids"], *snapshot["standalone"]["ids"]]
    missing = sorted(set(baseline_ids) - set(current_ids))
    if missing:
        raise BaselineError(f"post-refactor snapshot dropped frozen baseline identities: {missing[:3]}")
    additions = sorted(set(current_ids) - set(baseline_ids))
    payload = {
        "baseline_semantic_sha256": baseline["semantic_sha256"],
        "post_refactor_semantic_sha256": snapshot["semantic_sha256"],
        "retained_ids": baseline_ids,
        "post_refactor_additions": additions,
        "authorized_deletions": [],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_commit": baseline["source"]["commit"],
        "baseline_semantic_sha256": baseline["semantic_sha256"],
        "post_refactor_manifest": "tests/manifests/test-suite-after.json",
        "post_refactor_semantic_sha256": snapshot["semantic_sha256"],
        "equivalence_basis": "exact-baseline-subset-and-current-semantic-input-hash",
        "count_only_equivalence": False,
        "retained_ids": baseline_ids,
        "post_refactor_additions": additions,
        "missing_baseline_ids": [],
        "proposed_replacements": [],
        "authorized_deletions": [],
        "reconciliation_result": "success",
        "equivalence_sha256": _sha256(_canonical_json(payload)),
    }


def check_current_snapshot(
    snapshot: dict[str, object], baseline: dict[str, object], repo_root: Path
) -> None:
    """Validate successful post-refactor evidence against the current checkout.

    Args:
        snapshot: Parsed post-refactor suite snapshot.
        baseline: Parsed frozen pre-plan snapshot.
        repo_root: Checkout whose current suite must match the snapshot.

    Raises:
        BaselineError: The snapshot is incomplete, unsuccessful, or stale.
        OSError: A current semantic input cannot be read.
    """

    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise BaselineError("unsupported post-refactor snapshot schema version")
    source = snapshot.get("source")
    if not isinstance(source, dict):
        raise BaselineError("post-refactor snapshot source must be an object")
    expected_source = {
        "kind": "post-refactor-working-tree",
        "canonical_roots": list(CANONICAL_ROOTS),
        "collection_command": list(COLLECTION_ARGS),
        "execution_command": ["python3", "-m", "pytest", *CANONICAL_ROOTS],
    }
    if any(source.get(key) != value for key, value in expected_source.items()):
        raise BaselineError("post-refactor source contract is not canonical")
    environment = source.get("collection_environment")
    if not isinstance(environment, dict) or set(environment) != {"python", "pytest"}:
        raise BaselineError("post-refactor collection environment is incomplete")
    if not all(isinstance(environment[key], str) and environment[key] for key in environment):
        raise BaselineError("post-refactor collection environment values are invalid")

    pytest_data = snapshot.get("pytest")
    standalone = snapshot.get("standalone")
    if not isinstance(pytest_data, dict) or not isinstance(standalone, dict):
        raise BaselineError("post-refactor suite inventories must be objects")
    nodes = pytest_data.get("node_ids")
    shell_ids = standalone.get("ids")
    if not isinstance(nodes, list) or not isinstance(shell_ids, list):
        raise BaselineError("post-refactor exact IDs must be lists")
    if nodes != sorted(set(nodes)) or shell_ids != sorted(set(shell_ids)):
        raise BaselineError("post-refactor IDs must be unique and sorted")
    if pytest_data.get("total") != len(nodes) or standalone.get("total") != len(shell_ids):
        raise BaselineError("post-refactor totals do not match exact ID sets")
    expected_counts = {
        root: sum(node.startswith(f"{root}/") for node in nodes) for root in CANONICAL_ROOTS
    }
    if pytest_data.get("counts_by_root") != expected_counts:
        raise BaselineError("post-refactor root counts do not match exact IDs")

    baseline_ids = set(baseline["pytest"]["node_ids"]) | set(baseline["standalone"]["ids"])
    current_ids = set(nodes) | set(shell_ids)
    missing = sorted(baseline_ids - current_ids)
    if missing:
        raise BaselineError(f"post-refactor snapshot dropped frozen baseline identities: {missing[:3]}")

    result = pytest_data.get("execution_result")
    if not isinstance(result, dict) or result.get("job_conclusion") != "success":
        raise BaselineError("post-refactor pytest outcome is not successful")
    if any(result.get(key) != value for key, value in (("cases", len(nodes)), ("errors", 0), ("failures", 0))):
        raise BaselineError("post-refactor pytest outcome is incomplete or unsuccessful")
    by_root = result.get("by_root")
    if not isinstance(by_root, dict) or set(by_root) != set(CANONICAL_ROOTS):
        raise BaselineError("post-refactor pytest root outcomes are incomplete")
    for root, cases in expected_counts.items():
        area = by_root[root]
        if not isinstance(area, dict) or any(
            area.get(key) != value for key, value in (("cases", cases), ("errors", 0), ("failures", 0))
        ):
            raise BaselineError(f"post-refactor pytest outcome is invalid for {root}")
        if not isinstance(area.get("skipped"), int) or not 0 <= area["skipped"] <= cases:
            raise BaselineError(f"post-refactor skipped outcome is invalid for {root}")
    if not isinstance(result.get("skipped"), int) or result["skipped"] != sum(
        by_root[root]["skipped"] for root in CANONICAL_ROOTS
    ):
        raise BaselineError("post-refactor skipped total disagrees with root outcomes")

    expected_standalone_contract = {
        "glob_patterns": list(STANDALONE_GLOBS),
        "glob_excludes": list(POST_REFACTOR_STANDALONE_EXCLUDES),
        "explicit_self_tests": list(EXPLICIT_SELF_TESTS),
    }
    if any(standalone.get(key) != value for key, value in expected_standalone_contract.items()):
        raise BaselineError("post-refactor standalone discovery contract is not canonical")
    standalone_results = standalone.get("execution_results")
    expected_results = [{"id": identifier, "exit_code": 0, "status": "passed"} for identifier in shell_ids]
    if standalone_results != expected_results:
        raise BaselineError("post-refactor standalone outcomes are incomplete or unsuccessful")
    if snapshot.get("classifications") != {
        "pytest": {root: root for root in CANONICAL_ROOTS},
        "standalone": "shell",
    }:
        raise BaselineError("post-refactor classifications are not canonical")

    inputs = snapshot.get("semantic_inputs")
    semantic_payload = {"node_ids": nodes, "standalone_ids": shell_ids, "inputs": inputs}
    if snapshot.get("semantic_sha256") != _sha256(_canonical_json(semantic_payload)):
        raise BaselineError("post-refactor semantic digest mismatch")
    current_nodes = _current_pytest_ids(repo_root)
    current_shell_ids = _working_standalone_ids(repo_root)
    if nodes != current_nodes or shell_ids != current_shell_ids:
        raise BaselineError("post-refactor identities do not match current authoritative collection")
    if inputs != _working_semantic_inputs(repo_root, current_nodes, current_shell_ids):
        raise BaselineError("post-refactor semantic inputs do not match the current checkout")


def check_manifests(
    baseline: dict[str, object],
    prune: dict[str, object],
    equivalence: dict[str, object],
    snapshot: dict[str, object],
    repo_root: Path,
) -> None:
    """Validate manifests against their independent commit-addressed sources.

    Args:
        baseline: Parsed exact-suite manifest.
        prune: Parsed prune-provenance manifest.
        equivalence: Parsed coverage-equivalence manifest.
        snapshot: Parsed executed post-refactor suite manifest.
        repo_root: Checkout containing the recorded historical commit.

    Raises:
        BaselineError: Any manifest or historical-source contract is invalid.
        subprocess.CalledProcessError: The source commit is unavailable.
    """

    if any(
        document.get("schema_version") != SCHEMA_VERSION
        for document in (baseline, prune, equivalence, snapshot)
    ):
        raise BaselineError("unsupported manifest schema version")
    if baseline.get("source") != _BASELINE_SOURCE:
        raise BaselineError("baseline source and collection environment do not match the frozen anchor")
    pytest_data = baseline["pytest"]
    standalone = baseline["standalone"]
    nodes = pytest_data["node_ids"]
    shell_ids = standalone["ids"]
    if nodes != sorted(set(nodes)) or shell_ids != sorted(set(shell_ids)):
        raise BaselineError("baseline IDs must be unique and sorted")
    if pytest_data["total"] != len(nodes) or standalone["total"] != len(shell_ids):
        raise BaselineError("declared totals do not match exact ID sets")
    expected_counts = {
        root: sum(node.startswith(f"{root}/") for node in nodes) for root in CANONICAL_ROOTS
    }
    if pytest_data.get("counts_by_root") != expected_counts:
        raise BaselineError("pytest root counts do not match exact ID sets")
    if pytest_data.get("execution_result") != _EXECUTION_RESULT:
        raise BaselineError("historical execution outcome does not match the frozen evidence")
    expected_standalone_contract = {
        "glob_patterns": list(STANDALONE_GLOBS),
        "glob_excludes": list(STANDALONE_EXCLUDES),
        "explicit_self_tests": list(EXPLICIT_SELF_TESTS),
    }
    if any(standalone.get(key) != value for key, value in expected_standalone_contract.items()):
        raise BaselineError("standalone discovery contract does not match the frozen anchor")
    if baseline.get("classifications") != {
        "pytest": {root: root for root in CANONICAL_ROOTS},
        "standalone": "shell",
    }:
        raise BaselineError("baseline classifications do not match the frozen anchor")
    semantic_payload = {
        "node_ids": nodes,
        "standalone_ids": shell_ids,
        "inputs": baseline["semantic_inputs"],
    }
    if baseline["semantic_sha256"] != _sha256(_canonical_json(semantic_payload)):
        raise BaselineError("baseline semantic digest mismatch")
    if equivalence["baseline_semantic_sha256"] != baseline["semantic_sha256"]:
        raise BaselineError("coverage ledger points at a different baseline semantic digest")
    expected_retained = [*nodes, *shell_ids]
    if equivalence["retained_ids"] != expected_retained:
        raise BaselineError("coverage ledger does not retain every exact baseline ID")
    if equivalence["count_only_equivalence"] is not False:
        raise BaselineError("count-only equivalence is forbidden")
    commit = baseline["source"]["commit"]
    if prune.get("source") != {**_PRUNE_SOURCE, "source_commit": commit}:
        raise BaselineError("prune source provenance is not anchored to the baseline commit")
    if equivalence.get("baseline_commit") != commit:
        raise BaselineError("coverage ledger points at a different baseline commit")
    expected_report = {
        "format": "z-harness-test-prune-frontmatter-v1",
        "schema": _PRUNE_SCHEMA,
        **_PRUNE_REPORT,
    }
    if prune.get("report") != expected_report:
        raise BaselineError("prune report provenance does not match the committed audit anchor")
    expected_authorization = {
        "authorized_deletions": [],
        "safe_to_delete": 0,
        "consult_degraded": True,
        "individual_integration_reviews_required": _PRUNE_REPORT["integration_entries"],
    }
    if prune.get("authorization") != expected_authorization:
        raise BaselineError("prune authorization does not preserve the zero-deletion audit")
    if equivalence.get("authorized_deletions"):
        raise BaselineError("the source prune report authorized zero deletions")
    if equivalence.get("equivalence_basis") != "exact-baseline-subset-and-current-semantic-input-hash":
        raise BaselineError("coverage equivalence basis is not exact identity and semantic inputs")
    if equivalence.get("proposed_replacements") != []:
        raise BaselineError("the frozen coverage ledger contains no proposed replacements")
    historical_nodes, historical_shell_ids, historical_inputs = _source_inventory(repo_root, commit)
    if nodes != historical_nodes:
        raise BaselineError("pytest IDs do not match fresh collection from the historical commit")
    if shell_ids != historical_shell_ids:
        raise BaselineError("standalone IDs do not match the historical commit")
    if baseline["semantic_inputs"] != historical_inputs:
        raise BaselineError("semantic inputs do not match the historical commit")

    check_current_snapshot(snapshot, baseline, repo_root)
    current_ids = [*snapshot["pytest"]["node_ids"], *snapshot["standalone"]["ids"]]
    additions = sorted(set(current_ids) - set(expected_retained))
    if equivalence.get("post_refactor_manifest") != "tests/manifests/test-suite-after.json":
        raise BaselineError("coverage ledger points at an unknown post-refactor manifest")
    if equivalence.get("post_refactor_semantic_sha256") != snapshot["semantic_sha256"]:
        raise BaselineError("coverage ledger points at a different post-refactor semantic digest")
    if equivalence.get("post_refactor_additions") != additions:
        raise BaselineError("coverage ledger additions do not match the post-refactor snapshot")
    if equivalence.get("missing_baseline_ids") != []:
        raise BaselineError("coverage ledger reports missing frozen baseline identities")
    if equivalence.get("reconciliation_result") != "success":
        raise BaselineError("coverage ledger reconciliation is not successful")
    payload = {
        "baseline_semantic_sha256": baseline["semantic_sha256"],
        "post_refactor_semantic_sha256": snapshot["semantic_sha256"],
        "retained_ids": expected_retained,
        "post_refactor_additions": additions,
        "authorized_deletions": [],
    }
    if equivalence["equivalence_sha256"] != _sha256(_canonical_json(payload)):
        raise BaselineError("coverage equivalence digest mismatch")


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BaselineError(f"manifest must be a JSON object: {path}")
    return value


def _load_json_pair(
    first_path: Path, second_path: Path
) -> tuple[dict[str, object], dict[str, object]]:
    """Recover and load one committed paired publication or fail hard."""

    _recover_json_pair(first_path, second_path)
    return _load(first_path), _load(second_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate")
    generate.add_argument("--repo-root", type=Path, required=True)
    generate.add_argument("--source-commit", required=True)
    generate.add_argument("--junitxml", type=Path, required=True)
    generate.add_argument("--runtime-profile", type=Path, required=True)
    generate.add_argument("--prune-report", type=Path, required=True)
    generate.add_argument("--prune-metadata", type=Path, required=True)
    generate.add_argument("--output-dir", type=Path, required=True)
    generate.add_argument("--python-version", required=True)
    generate.add_argument("--pytest-version", required=True)
    generate.add_argument("--runner-image", required=True)
    record = subparsers.add_parser("record-current")
    record.add_argument("--manifest-dir", type=Path, required=True)
    record.add_argument("--repo-root", type=Path, required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--manifest-dir", type=Path, required=True)
    check.add_argument("--repo-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the deterministic manifest generator or fail-closed checker."""

    args = _parser().parse_args(argv)
    if args.command == "generate":
        documents = build_manifests(
            repo_root=args.repo_root,
            source_commit=args.source_commit,
            junit_path=args.junitxml,
            runtime_profile_path=args.runtime_profile,
            prune_report_path=args.prune_report,
            prune_metadata_path=args.prune_metadata,
            python_version=args.python_version,
            pytest_version=args.pytest_version,
            runner_image=args.runner_image,
        )
        names = ("test-suite-baseline.json", "test-prune-provenance.json", "coverage-equivalence.json")
        for name, document in zip(names, documents, strict=True):
            _atomic_write_json(args.output_dir / name, document)
    elif args.command == "record-current":
        baseline = _load(args.manifest_dir / "test-suite-baseline.json")
        snapshot_path = args.manifest_dir / "test-suite-after.json"
        equivalence_path = args.manifest_dir / "coverage-equivalence.json"
        _recover_json_pair(snapshot_path, equivalence_path)
        snapshot = build_current_snapshot(args.repo_root.resolve())
        equivalence = build_equivalence(baseline, snapshot)
        _publish_json_pair(
            snapshot_path,
            snapshot,
            equivalence_path,
            equivalence,
        )
    else:
        directory = args.manifest_dir
        baseline = _load(directory / "test-suite-baseline.json")
        snapshot, equivalence = _load_json_pair(
            directory / "test-suite-after.json",
            directory / "coverage-equivalence.json",
        )
        check_manifests(
            baseline,
            _load(directory / "test-prune-provenance.json"),
            equivalence,
            snapshot,
            args.repo_root,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
