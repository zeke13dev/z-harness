"""
pytest tests for scripts/extract-dismissals.py

Fixture layout (created in tmp_path):
  z-harness/
    myslug/
      archive/
        run-001/
          MR-REVIEW.md          (snapshot: findings A, B, C)
        run-002/
          MR-REVIEW.md          (snapshot: findings A, D)
          MR-REVIEW.md.previous-1  (user kept A, deleted B and C)
        run-003/
          MR-REVIEW.md          (snapshot: findings D, E)
          MR-REVIEW.md.previous-1  (user kept D, deleted A)

Expected dismissals:
  run-001 → run-002 pair: B and C dismissed (not in .previous-1 of run-002)
  run-002 → run-003 pair: A dismissed (not in .previous-1 of run-003)
"""

import json
import os
import sys
import time
from pathlib import Path

import importlib.util

import pytest

# The production module has a hyphenated filename which is not directly importable.
# Use importlib to load it by path.
SCRIPTS_DIR = Path(__file__).parent
_spec = importlib.util.spec_from_file_location(
    "extract_dismissals",
    SCRIPTS_DIR / "extract-dismissals.py",
)
assert _spec is not None and _spec.loader is not None
ed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ed)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helpers to build synthetic MR-REVIEW.md files
# ---------------------------------------------------------------------------

def make_mr_review(
    findings: list[dict],
    slug: str = "myslug",
    run_id: str = "run-001",
) -> str:
    """
    Produce a minimal MR-REVIEW.md string with YAML frontmatter.

    Each finding dict must have: id, severity, category, file, title.
    """
    index_lines = "\n".join(
        f"  - {{id: {f['id']}, severity: {f['severity']}, "
        f"category: {f['category']}, file: {f['file']}, title: {f['title']}}}"
        for f in findings
    )
    return (
        f"---\n"
        f"artifact: mr-review\n"
        f"slug: {slug}\n"
        f"run_id: {run_id}\n"
        f"findings_index:\n"
        f"{index_lines}\n"
        f"---\n\n"
        f"# MR Review — {slug}\n"
    )


FINDING_A = {
    "id": "T-MR-001",
    "severity": "P1",
    "category": "defensive-bloat",
    "file": "src/foo.rs",
    "title": "Unnecessary clone in hot path",
}
FINDING_B = {
    "id": "T-MR-002",
    "severity": "P2",
    "category": "hygiene",
    "file": "src/bar.rs",
    "title": "Stale TODO comment from 2023",
}
FINDING_C = {
    "id": "T-MR-003",
    "severity": "P3",
    "category": "style-drift",
    "file": "src/baz.rs",
    "title": "Inconsistent naming convention for error type",
}
FINDING_D = {
    "id": "T-MR-004",
    "severity": "P0",
    "category": "abstraction",
    "file": "src/lib.rs",
    "title": "Duplicate price formatting logic",
}
FINDING_E = {
    "id": "T-MR-005",
    "severity": "P2",
    "category": "style-drift",
    "file": "src/main.rs",
    "title": "Missing doc comment on public fn",
}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def archive_root(tmp_path: Path):
    """
    Build the full synthetic archive under tmp_path and return the slug_dir.

    Directory layout:
      <tmp_path>/z-harness/myslug/archive/
        run-001/   mtime = T+0   (snapshot: A, B, C)
        run-002/   mtime = T+1   (snapshot: A, D) + .previous-1 (user kept A; B+C gone)
        run-003/   mtime = T+2   (snapshot: D, E) + .previous-1 (user kept D; A gone)
    """
    slug_dir = tmp_path / "z-harness" / "myslug"
    archive_dir = slug_dir / "archive"

    runs_data = [
        {
            "name": "run-001",
            "snapshot_findings": [FINDING_A, FINDING_B, FINDING_C],
            "previous_findings": None,  # no previous for first run
        },
        {
            "name": "run-002",
            "snapshot_findings": [FINDING_A, FINDING_D],
            # user edited: kept A, deleted B and C
            "previous_findings": [FINDING_A],
        },
        {
            "name": "run-003",
            "snapshot_findings": [FINDING_D, FINDING_E],
            # user edited: kept D, deleted A
            "previous_findings": [FINDING_D],
        },
    ]

    base_mtime = time.time() - 1000  # use past timestamps so they're stable

    for i, run in enumerate(runs_data):
        run_dir = archive_dir / run["name"]
        run_dir.mkdir(parents=True)

        # Write snapshot
        snapshot_text = make_mr_review(
            run["snapshot_findings"],
            slug="myslug",
            run_id=run["name"],
        )
        snapshot_path = run_dir / "MR-REVIEW.md"
        snapshot_path.write_text(snapshot_text, encoding="utf-8")

        # Write previous snapshot if applicable
        if run["previous_findings"] is not None:
            prev_text = make_mr_review(
                run["previous_findings"],
                slug="myslug",
                run_id=f"{run['name']}-prev",
            )
            prev_path = run_dir / "MR-REVIEW.md.previous-1"
            prev_path.write_text(prev_text, encoding="utf-8")

        # Set mtime so ordering is deterministic
        mtime = base_mtime + i * 10
        os.utime(run_dir, (mtime, mtime))

    return slug_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_lowercase(self):
        assert ed.normalize_snippet("Hello World") == "hello world"

    def test_collapse_whitespace(self):
        assert ed.normalize_snippet("foo   bar\tbaz") == "foo bar baz"

    def test_strip_leading_trailing_punctuation(self):
        assert ed.normalize_snippet("...foo bar...") == "foo bar"

    def test_combined(self):
        result = ed.normalize_snippet("  !! Stale TODO Comment  !! ")
        assert result == "stale todo comment"

    def test_empty_string(self):
        assert ed.normalize_snippet("") == ""


class TestFrontmatterParsing:
    def test_parses_findings_index(self):
        text = make_mr_review([FINDING_A, FINDING_B])
        path_obj = None  # we'll write to a temp path manually; use the function directly
        fm = ed._parse_frontmatter_block(text.split("---\n", 2)[1])
        assert "findings_index" in fm
        assert isinstance(fm["findings_index"], list)
        assert len(fm["findings_index"]) == 2

    def test_missing_frontmatter_returns_empty(self, tmp_path):
        p = tmp_path / "no-fm.md"
        p.write_text("# Just a heading\nno frontmatter here\n")
        result = ed.parse_mr_review_frontmatter(p)
        assert result == {}

    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / "nonexistent.md"
        result = ed.parse_mr_review_frontmatter(p)
        assert result == {}


class TestSignatureExtraction:
    def test_extracts_file_category_snippet(self):
        fm = {"findings_index": [
            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
             "file": "src/foo.rs", "title": "Stale TODO comment"}
        ]}
        sigs = ed.findings_to_signatures(fm)
        assert len(sigs) == 1
        assert sigs[0]["file"] == "src/foo.rs"
        assert sigs[0]["category"] == "hygiene"
        assert sigs[0]["normalized_snippet"] == "stale todo comment"

    def test_no_line_range_in_signature(self):
        fm = {"findings_index": [
            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
             "file": "src/foo.rs", "title": "Bad naming",
             "line_start": 10, "line_end": 20}  # line range present in finding
        ]}
        sigs = ed.findings_to_signatures(fm)
        # Signature must NOT include line range
        assert "line_start" not in sigs[0]
        assert "line_end" not in sigs[0]
        assert set(sigs[0].keys()) == {"file", "category", "normalized_snippet"}

    def test_empty_findings_index(self):
        sigs = ed.findings_to_signatures({"findings_index": []})
        assert sigs == []

    def test_missing_findings_index(self):
        sigs = ed.findings_to_signatures({})
        assert sigs == []


class TestArchiveDiscovery:
    def test_no_archive_returns_empty(self, tmp_path):
        slug_dir = tmp_path / "slug"
        slug_dir.mkdir()
        run_dirs = ed.collect_run_dirs_for_slug(slug_dir)
        assert run_dirs == []

    def test_discovers_run_dirs(self, archive_root):
        run_dirs = ed.collect_run_dirs_for_slug(archive_root)
        assert len(run_dirs) == 3
        # Should be sorted chronologically ascending
        names = [d.name for d in run_dirs]
        assert names == ["run-001", "run-002", "run-003"]


class TestDismissalExtraction:
    def test_correct_dismissals_identified(self, archive_root):
        """
        Core invariant: B and C are dismissed in run-001→run-002 pair;
        A is dismissed in run-002→run-003 pair.
        """
        run_dirs = ed.collect_run_dirs_for_slug(archive_root)
        signatures, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)

        dismissed_snippets = {s["normalized_snippet"] for s in signatures}

        # B and C were deleted by user between run-001 and run-002
        assert ed.normalize_snippet(FINDING_B["title"]) in dismissed_snippets
        assert ed.normalize_snippet(FINDING_C["title"]) in dismissed_snippets

        # A was deleted by user between run-002 and run-003
        assert ed.normalize_snippet(FINDING_A["title"]) in dismissed_snippets

    def test_non_dismissed_not_in_output(self, archive_root):
        """
        D was kept (it appears in run-002 snapshot and also in run-003's .previous-1).
        E was never dismissed (it's in run-003 snapshot but there's no following run).
        Neither should appear as dismissed.
        """
        run_dirs = ed.collect_run_dirs_for_slug(archive_root)
        signatures, _ = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)

        dismissed_snippets = {s["normalized_snippet"] for s in signatures}

        assert ed.normalize_snippet(FINDING_D["title"]) not in dismissed_snippets
        assert ed.normalize_snippet(FINDING_E["title"]) not in dismissed_snippets

    def test_n_runs_scanned_correct(self, archive_root):
        run_dirs = ed.collect_run_dirs_for_slug(archive_root)
        _, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
        assert n_runs == 3

    def test_signature_has_prior_run_id(self, archive_root):
        run_dirs = ed.collect_run_dirs_for_slug(archive_root)
        signatures, _ = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
        for sig in signatures:
            assert "prior_run_id" in sig
            assert sig["prior_run_id"] in {"run-001", "run-002", "run-003"}

    def test_signature_format_no_line_range(self, archive_root):
        """Each signature dict must have exactly: file, category, normalized_snippet, prior_run_id."""
        run_dirs = ed.collect_run_dirs_for_slug(archive_root)
        signatures, _ = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
        assert len(signatures) > 0
        for sig in signatures:
            assert set(sig.keys()) == {"file", "category", "normalized_snippet", "prior_run_id"}

    def test_max_runs_limits_scope(self, archive_root):
        """max_runs=2 caps to the 2 most recent runs (run-002, run-003)."""
        run_dirs = ed.collect_run_dirs_for_slug(archive_root)
        signatures, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=2)
        assert n_runs == 2

        dismissed_snippets = {s["normalized_snippet"] for s in signatures}

        # Only A is dismissed in run-002→run-003 pair
        assert ed.normalize_snippet(FINDING_A["title"]) in dismissed_snippets

        # B and C belong to run-001→run-002 pair, which is excluded by max_runs=2
        assert ed.normalize_snippet(FINDING_B["title"]) not in dismissed_snippets
        assert ed.normalize_snippet(FINDING_C["title"]) not in dismissed_snippets

    def test_missing_archive_graceful(self, tmp_path):
        """Slug dir with no archive/ subdirectory returns empty result."""
        slug_dir = tmp_path / "empty-slug"
        slug_dir.mkdir()
        run_dirs = ed.collect_run_dirs_for_slug(slug_dir)
        sigs, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
        assert sigs == []
        assert n_runs == 0

    def test_empty_archive_graceful(self, tmp_path):
        """archive/ dir that exists but has no run dirs returns empty result."""
        slug_dir = tmp_path / "empty-slug"
        (slug_dir / "archive").mkdir(parents=True)
        run_dirs = ed.collect_run_dirs_for_slug(slug_dir)
        sigs, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
        assert sigs == []
        assert n_runs == 0


class TestJsonOutput:
    """Run the CLI as a subprocess and verify stdout JSON structure."""

    def test_output_json_structure(self, archive_root, tmp_path):
        """
        The CLI must emit valid JSON with 'signatures' list and 'n_runs_scanned' int.
        Each signature must have file, category, normalized_snippet (no line range).
        """
        import subprocess

        script = SCRIPTS_DIR / "extract-dismissals.py"
        result = subprocess.run(
            [sys.executable, str(script), str(archive_root)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)

        assert "signatures" in data
        assert "n_runs_scanned" in data
        assert isinstance(data["signatures"], list)
        assert isinstance(data["n_runs_scanned"], int)
        assert data["n_runs_scanned"] == 3

        for sig in data["signatures"]:
            # Invariant: signature format is (file, category, normalized_snippet) + prior_run_id
            assert "file" in sig
            assert "category" in sig
            assert "normalized_snippet" in sig
            assert "prior_run_id" in sig
            # MUST NOT include line range
            assert "line_start" not in sig
            assert "line_end" not in sig

    def test_missing_slug_dir_returns_empty(self, tmp_path):
        import subprocess

        script = SCRIPTS_DIR / "extract-dismissals.py"
        nonexistent = tmp_path / "no-such-slug"
        result = subprocess.run(
            [sys.executable, str(script), str(nonexistent)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == {"signatures": [], "n_runs_scanned": 0}

    def test_global_flag(self, archive_root, tmp_path):
        """--global scans all slugs under z-harness/ from repo root."""
        import subprocess

        # archive_root is <tmp_path>/z-harness/myslug
        # repo root for --global is tmp_path (contains z-harness/)
        script = SCRIPTS_DIR / "extract-dismissals.py"
        result = subprocess.run(
            [sys.executable, str(script), "--global"],
            capture_output=True,
            text=True,
            cwd=str(archive_root.parent.parent),  # tmp_path (repo root)
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "signatures" in data
        assert "n_runs_scanned" in data
        assert data["n_runs_scanned"] >= 3


# ---------------------------------------------------------------------------
# Fix #1 — title field required; T-MR-NNN id fallback removed
# ---------------------------------------------------------------------------

class TestTitleRequired:
    def test_finding_without_title_is_dropped(self):
        """A finding that lacks a `title` key must be silently dropped."""
        fm = {"findings_index": [
            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
             "file": "src/foo.rs"},  # no 'title'
        ]}
        sigs = ed.findings_to_signatures(fm)
        assert sigs == [], "Finding without title must be dropped, not included via id fallback"

    def test_t_mr_nnn_id_not_used_as_snippet(self):
        """
        Regression: T-MR-NNN ids must NOT appear as normalized_snippet.
        They are re-numbered each run and would produce spurious dismissals.
        """
        fm = {"findings_index": [
            {"id": "T-MR-042", "severity": "P2", "category": "style-drift",
             "file": "src/foo.rs"},  # title absent
        ]}
        sigs = ed.findings_to_signatures(fm)
        for sig in sigs:
            assert "t-mr-" not in sig["normalized_snippet"], (
                "T-MR-NNN id must not appear in normalized_snippet"
            )

    def test_finding_with_title_is_included(self):
        """Presence of a non-empty title means the finding is included normally."""
        fm = {"findings_index": [
            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
             "file": "src/foo.rs", "title": "Stale TODO"},
        ]}
        sigs = ed.findings_to_signatures(fm)
        assert len(sigs) == 1
        assert sigs[0]["normalized_snippet"] == "stale todo"

    def test_drop_count_incremented_for_missing_title(self):
        """_drop_count[0] must be incremented for each finding dropped due to absent title."""
        fm = {"findings_index": [
            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
             "file": "src/foo.rs"},  # no title → dropped
            {"id": "T-MR-002", "severity": "P2", "category": "hygiene",
             "file": "src/bar.rs", "title": "Real title"},  # kept
        ]}
        drop_count = [0]
        sigs = ed.findings_to_signatures(fm, _drop_count=drop_count)
        assert drop_count[0] == 1, "Exactly one finding should have been dropped"
        assert len(sigs) == 1


# ---------------------------------------------------------------------------
# Fix #2 — ISO timestamp sort order
# ---------------------------------------------------------------------------

class TestIsoTimestampSort:
    def _make_iso_run(self, archive_dir: Path, timestamp: str, finding: dict, mtime: float) -> None:
        """
        Create a run dir named "<timestamp>-mr-review" with an MR-REVIEW.md snapshot.
        Deliberately sets mtime to a value OPPOSITE to chronological order to verify
        that mtime is NOT the primary sort key.
        """
        run_dir = archive_dir / f"{timestamp}-mr-review"
        run_dir.mkdir(parents=True)
        content = make_mr_review([finding])
        (run_dir / "MR-REVIEW.md").write_text(content, encoding="utf-8")
        os.utime(run_dir, (mtime, mtime))

    def test_iso_prefix_sort_overrides_mtime(self, tmp_path):
        """
        Three run dirs with ISO-prefix names but REVERSED mtime order.
        discover_archive_runs must return them in ISO timestamp order, not mtime order.
        """
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        base_t = time.time() - 3000
        # Write dirs in ISO order but assign mtime in REVERSE (newest mtime = oldest timestamp)
        self._make_iso_run(archive_dir, "20260101T000000Z", FINDING_A, mtime=base_t + 200)
        self._make_iso_run(archive_dir, "20260201T000000Z", FINDING_B, mtime=base_t + 100)
        self._make_iso_run(archive_dir, "20260301T000000Z", FINDING_C, mtime=base_t + 0)

        runs = ed.discover_archive_runs(archive_dir)
        names = [d.name for d in runs]
        assert names == [
            "20260101T000000Z-mr-review",
            "20260201T000000Z-mr-review",
            "20260301T000000Z-mr-review",
        ], f"Expected ISO order but got: {names}"

    def test_iso_prefix_dismissal_order_correct(self, tmp_path):
        """
        End-to-end: with ISO-named runs whose mtimes are reversed, the dismissal
        algorithm must still identify findings dismissed in the chronologically
        correct R_i → R_{i+1} pair.
        """
        slug_dir = tmp_path / "slug"
        archive_dir = slug_dir / "archive"
        archive_dir.mkdir(parents=True)

        base_t = time.time() - 3000

        # Run 1 (oldest ISO): snapshot has A and B; mtime is NEWEST (reversed)
        run1_dir = archive_dir / "20260101T000000Z-mr-review"
        run1_dir.mkdir()
        (run1_dir / "MR-REVIEW.md").write_text(
            make_mr_review([FINDING_A, FINDING_B]), encoding="utf-8"
        )
        os.utime(run1_dir, (base_t + 200, base_t + 200))

        # Run 2 (newer ISO): snapshot has A; .previous-1 shows user kept A (dropped B)
        run2_dir = archive_dir / "20260201T000000Z-mr-review"
        run2_dir.mkdir()
        (run2_dir / "MR-REVIEW.md").write_text(
            make_mr_review([FINDING_A]), encoding="utf-8"
        )
        (run2_dir / "MR-REVIEW.md.previous-1").write_text(
            make_mr_review([FINDING_A]), encoding="utf-8"
        )
        os.utime(run2_dir, (base_t + 0, base_t + 0))  # oldest mtime — opposite of ISO order

        run_dirs = ed.collect_run_dirs_for_slug(slug_dir)
        sigs, _ = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)

        dismissed = {s["normalized_snippet"] for s in sigs}
        assert ed.normalize_snippet(FINDING_B["title"]) in dismissed, (
            "B must be dismissed (dropped by user between run1 and run2)"
        )
        assert ed.normalize_snippet(FINDING_A["title"]) not in dismissed, (
            "A must NOT be dismissed (user kept it)"
        )


# ---------------------------------------------------------------------------
# Fix #3 — --global mode: pairwise per-slug, not interleaved
# ---------------------------------------------------------------------------

class TestGlobalPerSlug:
    def _make_slug(
        self,
        harness_root: Path,
        slug: str,
        runs: list[dict],
    ) -> Path:
        """
        Create a slug dir with the given archive runs.
        Each run dict: {name, snapshot_findings, previous_findings (or None)}.
        Uses ISO-prefix names so sort order is deterministic.
        """
        slug_dir = harness_root / slug
        archive_dir = slug_dir / "archive"

        base_t = time.time() - 5000
        for i, run in enumerate(runs):
            run_dir = archive_dir / run["name"]
            run_dir.mkdir(parents=True)
            (run_dir / "MR-REVIEW.md").write_text(
                make_mr_review(run["snapshot_findings"], slug=slug, run_id=run["name"]),
                encoding="utf-8",
            )
            if run.get("previous_findings") is not None:
                (run_dir / "MR-REVIEW.md.previous-1").write_text(
                    make_mr_review(run["previous_findings"], slug=slug, run_id=f"{run['name']}-prev"),
                    encoding="utf-8",
                )
            mtime = base_t + i * 10
            os.utime(run_dir, (mtime, mtime))

        return slug_dir

    def test_global_pairwise_per_slug(self, tmp_path):
        """
        Two slugs, each with their own run series.  The pairwise algorithm must
        not cross slug boundaries: a run from slug-A must never be paired with a
        run from slug-B.
        """
        harness_root = tmp_path / "z-harness"

        # slug-alpha: run-001 (A+B snapshot) → run-002 (A kept, B dropped)
        self._make_slug(harness_root, "slug-alpha", [
            {"name": "20260101T000000Z-mr-review",
             "snapshot_findings": [FINDING_A, FINDING_B],
             "previous_findings": None},
            {"name": "20260102T000000Z-mr-review",
             "snapshot_findings": [FINDING_A],
             "previous_findings": [FINDING_A]},  # user kept A, dropped B
        ])

        # slug-beta: run-001 (C+D snapshot) → run-002 (C kept, D dropped)
        self._make_slug(harness_root, "slug-beta", [
            {"name": "20260103T000000Z-mr-review",
             "snapshot_findings": [FINDING_C, FINDING_D],
             "previous_findings": None},
            {"name": "20260104T000000Z-mr-review",
             "snapshot_findings": [FINDING_C],
             "previous_findings": [FINDING_C]},  # user kept C, dropped D
        ])

        slug_runs = ed.collect_slug_run_dirs_global(tmp_path)
        all_sigs: list[dict] = []
        total_n = 0
        for run_dirs in slug_runs.values():
            sigs, n = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
            all_sigs.extend(sigs)
            total_n += n

        dismissed = {s["normalized_snippet"] for s in all_sigs}

        # B dismissed in slug-alpha; D dismissed in slug-beta
        assert ed.normalize_snippet(FINDING_B["title"]) in dismissed
        assert ed.normalize_snippet(FINDING_D["title"]) in dismissed

        # A and C were kept, not dismissed
        assert ed.normalize_snippet(FINDING_A["title"]) not in dismissed
        assert ed.normalize_snippet(FINDING_C["title"]) not in dismissed

        # n_runs_scanned sums across slugs
        assert total_n == 4  # 2 per slug × 2 slugs

    def test_global_cli_pairwise_per_slug(self, tmp_path):
        """
        CLI --global must not interleave: dismissal signatures from each slug
        are computed independently and merged into the output.
        """
        import subprocess

        harness_root = tmp_path / "z-harness"

        # slug-alpha: B dismissed
        self._make_slug(harness_root, "slug-alpha", [
            {"name": "20260101T000000Z-mr-review",
             "snapshot_findings": [FINDING_A, FINDING_B],
             "previous_findings": None},
            {"name": "20260102T000000Z-mr-review",
             "snapshot_findings": [FINDING_A],
             "previous_findings": [FINDING_A]},
        ])
        # slug-beta: D dismissed
        self._make_slug(harness_root, "slug-beta", [
            {"name": "20260103T000000Z-mr-review",
             "snapshot_findings": [FINDING_C, FINDING_D],
             "previous_findings": None},
            {"name": "20260104T000000Z-mr-review",
             "snapshot_findings": [FINDING_C],
             "previous_findings": [FINDING_C]},
        ])

        script = SCRIPTS_DIR / "extract-dismissals.py"
        result = subprocess.run(
            [sys.executable, str(script), "--global"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)

        dismissed_snippets = {s["normalized_snippet"] for s in data["signatures"]}
        assert ed.normalize_snippet(FINDING_B["title"]) in dismissed_snippets
        assert ed.normalize_snippet(FINDING_D["title"]) in dismissed_snippets
        # n_runs_scanned = 2 per slug × 2 slugs
        assert data["n_runs_scanned"] == 4


# ---------------------------------------------------------------------------
# Fix #4 — quote-aware comma splitting
# ---------------------------------------------------------------------------

class TestQuoteAwareSplitting:
    def test_quoted_comma_not_split(self):
        """A comma inside double-quoted value must NOT split the field."""
        result = ed._split_respecting_nesting('title: "Foo, bar"')
        # The whole string is one item; comma inside quotes is not a separator
        assert len(result) == 1, f"Expected 1 part but got: {result}"

    def test_single_quoted_comma_not_split(self):
        """A comma inside single-quoted value must NOT split the field."""
        result = ed._split_respecting_nesting("title: 'Foo, bar'")
        assert len(result) == 1, f"Expected 1 part but got: {result}"

    def test_unquoted_comma_does_split(self):
        """A comma outside quotes must still split normally."""
        result = ed._split_respecting_nesting("a, b, c")
        assert len(result) == 3, f"Expected 3 parts but got: {result}"

    def test_inline_dict_with_quoted_comma_title(self):
        """
        An inline dict like {id: T-MR-001, title: "Foo, bar", category: hygiene}
        must parse correctly: title value is "Foo, bar" (one field, not two).
        """
        inner = 'id: T-MR-001, title: "Foo, bar", category: hygiene'
        result = ed._parse_inline_dict(inner)
        assert result.get("title") == "Foo, bar", (
            f"title should be 'Foo, bar' but got: {result.get('title')!r}"
        )
        assert result.get("id") == "T-MR-001"
        assert result.get("category") == "hygiene"

    def test_findings_index_with_quoted_comma_title_parses(self, tmp_path):
        """
        End-to-end: an MR-REVIEW.md whose findings_index has a title with a
        comma inside quotes must yield a single finding with the full title.
        """
        fm_text = (
            "findings_index:\n"
            '  - {id: T-MR-001, severity: P1, category: hygiene, '
            'file: src/foo.rs, title: "Unused import, remove it"}\n'
        )
        parsed = ed._parse_frontmatter_block(fm_text)
        sigs = ed.findings_to_signatures(parsed)
        assert len(sigs) == 1, f"Expected 1 sig but got {len(sigs)}: {sigs}"
        assert sigs[0]["normalized_snippet"] == "unused import, remove it"

    def test_apostrophe_in_plain_scalar_does_not_merge_fields(self):
        """
        Regression: an apostrophe inside a plain YAML scalar (e.g. "Don't")
        must NOT trigger quote state, which would cause it to swallow the
        subsequent comma and merge two separate fields into one.

        _split_respecting_nesting("title: Don't merge this, file: src/x.rs")
        must return exactly 2 items.
        """
        result = ed._split_respecting_nesting("title: Don't merge this, file: src/x.rs")
        assert len(result) == 2, (
            f"Apostrophe in plain scalar must not enter quote state; "
            f"expected 2 parts but got {len(result)}: {result}"
        )
        assert result[0].strip() == "title: Don't merge this"
        assert result[1].strip() == "file: src/x.rs"

    def test_apostrophe_variants_dont_merge(self):
        """Other contractions (It's, won't, can't) must also not merge fields."""
        for contraction in ("It's", "won't", "can't"):
            text = f"title: {contraction} important, file: src/x.rs"
            result = ed._split_respecting_nesting(text)
            assert len(result) == 2, (
                f"Contraction '{contraction}' caused field merge; "
                f"got {len(result)} parts: {result}"
            )

    def test_doubled_single_quote_escape_stays_in_quote(self):
        """
        Regression: a YAML single-quoted string with a doubled '' escape must be
        treated as a single field.

        _split_respecting_nesting("title: 'Don''t split, this title', file: src/x.rs")
        must return 2 parts (not 3), because the '' is an escaped apostrophe, not
        the end of the quoted string followed by a bare t.
        """
        result = ed._split_respecting_nesting(
            "title: 'Don''t split, this title', file: src/x.rs"
        )
        assert len(result) == 2, (
            f"Doubled '' in single-quoted string must stay in quote state; "
            f"expected 2 parts but got {len(result)}: {result}"
        )
        assert result[0].strip() == "title: 'Don''t split, this title'"
        assert result[1].strip() == "file: src/x.rs"
