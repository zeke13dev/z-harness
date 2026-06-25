from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "surface-map.py"


def _load_surface_map():
    spec = importlib.util.spec_from_file_location("surface_map", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["surface_map"] = module
    spec.loader.exec_module(module)
    return module


surface_map = _load_surface_map()


def _valid_payload(tmp_path: Path) -> dict:
    return surface_map.empty_payload(
        "repo",
        "z-explain",
        tmp_path,
        "repo",
        surface_map.Caps(max_primary_files=10, max_refs=100, max_bytes=200_000),
    )


def _run_surface_map(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
    )


class TestSchemaAndStatuses:
    def test_repo_cli_writes_schema_version_1_and_approved_status(self, tmp_path: Path):
        repo = tmp_path / "repo"
        (repo / "scripts").mkdir(parents=True)
        (repo / "tests").mkdir()
        (repo / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
        out = tmp_path / "surface-map.json"

        result = _run_surface_map(
            "--repo-root",
            str(repo),
            "--mode",
            "repo",
            "--caller",
            "z-explain",
            "--target",
            "repo",
            "--out",
            str(out),
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["mode"] == "repo"
        assert payload["caller"] == "z-explain"
        assert payload["status"] in surface_map.STATUSES
        for key in (
            "generated_at",
            "target",
            "caps",
            "stats",
            "primary",
            "related",
            "clusters",
            "suggested_reads",
            "warnings",
            "tried_strategies",
        ):
            assert key in payload
        assert payload["target"]["repo_root"] == str(repo.resolve())

    def test_status_vocabulary_is_validated(self, tmp_path: Path):
        payload = _valid_payload(tmp_path)
        payload["status"] = "surprising"

        with pytest.raises(ValueError, match="invalid surface-map status"):
            surface_map.validate_payload(payload)



class TestSymbolMode:
    def test_symbol_mode_collects_filename_and_identifier_candidates(self, tmp_path: Path):
        repo = tmp_path / "repo"
        module_dir = repo / "pkg"
        module_dir.mkdir(parents=True)
        (module_dir / "widget.py").write_text(
            "class Widget:\n    pass\n\nvalue = Widget()\n",
            encoding="utf-8",
        )
        out = tmp_path / "surface-map.json"

        result = _run_surface_map(
            "--repo-root",
            str(repo),
            "--mode",
            "symbol",
            "--caller",
            "z-explain",
            "--target",
            "Widget",
            "--out",
            str(out),
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["status"] == "ok"
        assert payload["primary"][0]["path"] == "pkg/widget.py"
        assert payload["primary"][0]["kind"] == "type"
        assert payload["primary"][0]["relation"] == "defines"
        assert payload["primary"][0]["line_start"] == 1

class TestDiffMode:
    def test_diff_parsing_groups_changed_files_and_hunk_ranges(self):
        diff_text = """diff --git a/scripts/alpha.py b/scripts/alpha.py
index 1111111..2222222 100644
--- a/scripts/alpha.py
+++ b/scripts/alpha.py
@@ -1,3 +1,4 @@
 def alpha():
+    return 1
@@ -20,2 +21,3 @@
 value = 2
+value = 3
diff --git a/tests/test_alpha.py b/tests/test_alpha.py
index 3333333..4444444 100644
--- a/tests/test_alpha.py
+++ b/tests/test_alpha.py
@@ -5 +5,2 @@
 def test_alpha():
+    assert True
"""
        changed = surface_map.parse_unified_diff(diff_text)

        assert [item.path for item in changed] == ["scripts/alpha.py", "tests/test_alpha.py"]
        assert [h.range_label for h in changed[0].hunks] == ["1-4", "21-23"]
        assert [h.range_label for h in changed[1].hunks] == ["5-6"]


    def test_diff_mode_uses_old_side_ranges_for_deleted_files(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        diff_path = tmp_path / "delete.diff"
        diff_path.write_text(
            """diff --git a/deleted.py b/deleted.py
deleted file mode 100644
index 1111111..0000000
--- a/deleted.py
+++ /dev/null
@@ -1 +0,0 @@
-def gone(): pass
""",
            encoding="utf-8",
        )
        out = tmp_path / "surface-map.json"

        result = _run_surface_map(
            "--repo-root",
            str(repo),
            "--mode",
            "diff",
            "--caller",
            "z-report",
            "--target",
            "changes",
            "--diff-path",
            str(diff_path),
            "--out",
            str(out),
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["status"] == "ok"
        assert payload["primary"][0]["path"] == "deleted.py"
        assert payload["primary"][0]["line_start"] == 1
        assert payload["primary"][0]["line_end"] == 1
        assert payload["primary"][0]["citations"] == ["deleted.py:1"]
        assert payload["related"][0]["line_start"] == 1
        assert payload["related"][0]["line_end"] == 1
        assert payload["related"][0]["citations"] == ["deleted.py:1"]
        assert payload["suggested_reads"][0]["ranges"] == ["1-1"]

    def test_diff_mode_outputs_changed_file_clusters_and_suggested_reads(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        diff_path = tmp_path / "change.diff"
        diff_path.write_text(
            """diff --git a/scripts/alpha.py b/scripts/alpha.py
--- a/scripts/alpha.py
+++ b/scripts/alpha.py
@@ -1 +1,2 @@
+print('alpha')
diff --git a/tests/test_alpha.py b/tests/test_alpha.py
--- a/tests/test_alpha.py
+++ b/tests/test_alpha.py
@@ -10,2 +10,4 @@
+assert True
""",
            encoding="utf-8",
        )

        out = tmp_path / "surface-map.json"
        result = _run_surface_map(
            "--repo-root",
            str(repo),
            "--mode",
            "diff",
            "--caller",
            "z-report",
            "--target",
            "changes",
            "--diff-path",
            str(diff_path),
            "--out",
            str(out),
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["status"] == "ok"
        assert [entry["path"] for entry in payload["primary"]] == [
            "scripts/alpha.py",
            "tests/test_alpha.py",
        ]
        assert {cluster["label"] for cluster in payload["clusters"]} == {
            "scripts and helpers",
            "tests",
        }
        reads = {entry["path"]: entry["ranges"] for entry in payload["suggested_reads"]}
        assert reads["scripts/alpha.py"] == ["1-2"]
        assert reads["tests/test_alpha.py"] == ["10-13"]


class TestCapsAndAtomicWrite:
    def test_caps_produce_truncated_repo_output_not_unbounded_output(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        for name in ["scripts", "skills", "agents", "tests"]:
            (repo / name).mkdir()
        out = tmp_path / "surface-map.json"

        result = _run_surface_map(
            "--repo-root",
            str(repo),
            "--mode",
            "repo",
            "--caller",
            "z-learn",
            "--target",
            "repo",
            "--out",
            str(out),
            "--max-primary-files",
            "1",
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["status"] in {"truncated", "too_broad"}
        assert payload["stats"]["truncated"] is True
        assert len(payload["primary"]) == 1

    def test_diff_caps_produce_truncated_or_too_broad_output(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        diff_path = tmp_path / "change.diff"
        diff_path.write_text(
            """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
+x
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1 +1,2 @@
+y
""",
            encoding="utf-8",
        )
        out = tmp_path / "surface-map.json"

        result = _run_surface_map(
            "--repo-root",
            str(repo),
            "--mode",
            "diff",
            "--caller",
            "z-report",
            "--target",
            "changes",
            "--diff-path",
            str(diff_path),
            "--out",
            str(out),
            "--max-primary-files",
            "1",
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["status"] in {"truncated", "too_broad"}
        assert len(payload["primary"]) == 1
        assert payload["stats"]["truncated"] is True

    def test_atomic_write_does_not_leave_partial_output_on_replace_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        out = tmp_path / "surface-map.json"
        out.write_text('{"existing": true}\n', encoding="utf-8")
        payload = _valid_payload(tmp_path)

        def fail_replace(_src: str, _dst: Path | str):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(surface_map.os, "replace", fail_replace)

        with pytest.raises(OSError, match="simulated replace failure"):
            surface_map.atomic_write_json(out, payload)

        assert out.read_text(encoding="utf-8") == '{"existing": true}\n'
        assert list(tmp_path.glob(".surface-map.json.*.tmp")) == []
