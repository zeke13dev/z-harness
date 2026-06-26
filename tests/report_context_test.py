"""
tests/report_context_test.py — Unit tests for scripts/report-context.py resolver.

T001 acceptance: every branch of resolve_target() is covered, including:
  - ISO run-id shape         → mode: run
  - #N                       → mode: pr
  - GitHub pull URL          → mode: pr
  - A..B range               → mode: range
  - exact slug match         → mode: slug
  - bare int (no #)          → mode: ambiguous  (with actionable message)
  - bare hex SHA             → mode: ambiguous  (with actionable message)
  - unrecognised token       → mode: not_found  (with actionable message)
  - flag conflict (>1 typed) → mode: error
  - no arg + no flags        → mode: run | ambiguous (via active-plan registry mock)
  - --resolve-only CLI       → correct JSON + exit code

T002 acceptance: bundle assembly for mode=run/slug:
  - decisions/phases/status populated from fixture run dir
  - missing events.jsonl → degraded:"no_events", bundle still valid
  - events_chars present in bundle
  - warnings[] never crashes the bundle

T003 acceptance: bundle assembly for mode=pr/range/base/worktree:
  - range bundle: diff_bytes > 0, commits populated, followups empty with note
  - base bundle: diff_bytes populated, commits populated, followups empty with note
  - worktree bundle: diff_bytes populated, commits populated, followups empty with note
  - pr mode with gh missing: clean error descriptor with message field
  - pr mode with gh unauth: clean error descriptor with message field
  - pr mode success: title/state/commits/diff/diff_bytes all present
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Locate fixture for T002 bundle tests
# ---------------------------------------------------------------------------

_REPO_ROOT_FOR_FIXTURES = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Load the module under test
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "report-context.py"

def _load_module():
    spec = importlib.util.spec_from_file_location("report_context", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()
resolve_target = _mod.resolve_target
main = _mod.main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(
    target=None,
    flag_run=None,
    flag_slug=None,
    flag_pr=None,
    flag_range=None,
    flag_base=None,
    *,
    slugs=(),
    active_records=(),
) -> dict:
    """Call resolve_target with mocked external helpers."""
    with (
        patch.object(_mod, "_all_plan_slugs", return_value=list(slugs)),
        patch.object(_mod, "_active_plan_records", return_value=list(active_records)),
        patch.object(_mod, "_slug_exists", side_effect=lambda s: s in slugs),
    ):
        return resolve_target(
            target=target,
            flag_run=flag_run,
            flag_slug=flag_slug,
            flag_pr=flag_pr,
            flag_range=flag_range,
            flag_base=flag_base,
        )


# ---------------------------------------------------------------------------
# Typed-flag precedence
# ---------------------------------------------------------------------------

class TestTypedFlags:
    def test_run_flag(self):
        desc = _resolve(flag_run="20260618T123456Z-myplan")
        assert desc["mode"] == "run"
        assert desc["run_id"] == "20260618T123456Z-myplan"

    def test_slug_flag(self):
        desc = _resolve(flag_slug="my-plan")
        assert desc["mode"] == "slug"
        assert desc["slug"] == "my-plan"

    def test_pr_flag_integer(self):
        desc = _resolve(flag_pr="42")
        assert desc["mode"] == "pr"
        assert desc["pr"] == "42"

    def test_range_flag(self):
        desc = _resolve(flag_range="abc123..def456")
        assert desc["mode"] == "range"
        assert desc["range"] == "abc123..def456"

    def test_base_flag_alone(self):
        desc = _resolve(flag_base="main")
        assert desc["mode"] == "range"
        assert desc["base"] == "main"

    def test_range_flag_with_base(self):
        desc = _resolve(flag_range="HEAD~5..HEAD", flag_base="main")
        assert desc["mode"] == "range"
        assert desc["range"] == "HEAD~5..HEAD"
        assert desc.get("base") == "main"

    def test_flag_conflict_run_pr(self):
        """--run and --pr together must produce mode: error."""
        desc = _resolve(flag_run="20260618T123456Z-x", flag_pr="5")
        assert desc["mode"] == "error"
        assert "Conflicting" in desc["message"]
        assert "--run" in desc["message"] or "run" in desc["message"]
        assert "--pr" in desc["message"] or "pr" in desc["message"]

    def test_flag_conflict_slug_range(self):
        desc = _resolve(flag_slug="my-plan", flag_range="a..b")
        assert desc["mode"] == "error"
        assert "Conflicting" in desc["message"]

    def test_flag_conflict_three_flags(self):
        desc = _resolve(flag_run="x", flag_slug="y", flag_pr="1")
        assert desc["mode"] == "error"


# ---------------------------------------------------------------------------
# No-arg / no-flag resolution (active registry lookup)
# ---------------------------------------------------------------------------

class TestNoArg:
    def test_single_active_slug(self):
        records = [{"slug": "my-plan", "status": "running"}]
        desc = _resolve(active_records=records)
        assert desc["mode"] == "run"
        assert desc.get("slug") == "my-plan"

    def test_multiple_active_slugs_ambiguous(self):
        records = [
            {"slug": "plan-a", "status": "running"},
            {"slug": "plan-b", "status": "running"},
        ]
        desc = _resolve(active_records=records)
        assert desc["mode"] == "ambiguous"
        assert "plan-a" in desc["message"]
        assert "plan-b" in desc["message"]

    def test_no_active_slugs_ambiguous(self):
        desc = _resolve(active_records=[])
        assert desc["mode"] == "ambiguous"
        assert "No active plan" in desc["message"] or "active" in desc["message"].lower()

    def test_records_without_slug_ignored(self):
        """Records missing 'slug' key should not count as active slugs."""
        records = [{"status": "running"}]
        desc = _resolve(active_records=records)
        assert desc["mode"] == "ambiguous"


# ---------------------------------------------------------------------------
# Positional shape matching
# ---------------------------------------------------------------------------

class TestPositionalShapes:
    # ISO run-id
    def test_run_id_exact(self):
        desc = _resolve("20260618T120000Z-myplan")
        assert desc["mode"] == "run"
        assert desc["run_id"] == "20260618T120000Z-myplan"

    def test_run_id_minimal(self):
        desc = _resolve("20260101T000000Z-x")
        assert desc["mode"] == "run"

    def test_run_id_with_trailing_content(self):
        desc = _resolve("20260618T123456Z-implement-all")
        assert desc["mode"] == "run"

    # PR shapes
    def test_pr_hash_prefix(self):
        desc = _resolve("#42")
        assert desc["mode"] == "pr"
        assert desc["pr"] == "42"

    def test_pr_github_url(self):
        desc = _resolve("https://github.com/acme/repo/pull/7")
        assert desc["mode"] == "pr"
        assert desc["pr"] == "7"

    def test_pr_github_url_no_trailing_slash(self):
        desc = _resolve("https://github.com/org/proj/pull/123")
        assert desc["mode"] == "pr"
        assert desc["pr"] == "123"

    # Range
    def test_range_dotdot(self):
        desc = _resolve("main..HEAD")
        assert desc["mode"] == "range"
        assert desc["range"] == "main..HEAD"

    def test_range_sha_dotdot_sha(self):
        desc = _resolve("abc1234..def5678")
        assert desc["mode"] == "range"

    def test_range_triple_dot(self):
        """Triple-dot (A...B) also contains '..' and should be mode: range."""
        desc = _resolve("main...HEAD")
        assert desc["mode"] == "range"

    # Slug match
    def test_exact_slug_match(self):
        desc = _resolve("my-plan", slugs=("my-plan", "other-plan"))
        assert desc["mode"] == "slug"
        assert desc["slug"] == "my-plan"

    def test_slug_match_takes_priority_over_ambiguity(self):
        """A token that matches a slug exactly should be mode: slug, not ambiguous."""
        desc = _resolve("cool-plan", slugs=("cool-plan",))
        assert desc["mode"] == "slug"

    # Bare integer ⇒ ambiguous
    def test_bare_integer_ambiguous(self):
        desc = _resolve("42")
        assert desc["mode"] == "ambiguous"

    def test_bare_integer_message_actionable(self):
        desc = _resolve("42")
        msg = desc.get("message", "")
        # Must mention how to disambiguate
        assert any(kw in msg for kw in ("--pr", "--run", "--slug", "ambiguous"))

    def test_bare_integer_zero(self):
        desc = _resolve("0")
        assert desc["mode"] == "ambiguous"

    def test_bare_integer_large(self):
        desc = _resolve("9999")
        assert desc["mode"] == "ambiguous"

    # Bare hex ⇒ ambiguous (no slug match)
    def test_bare_hex_7_chars(self):
        desc = _resolve("abc1234")
        assert desc["mode"] == "ambiguous"

    def test_bare_hex_40_chars(self):
        desc = _resolve("a" * 40)
        assert desc["mode"] == "ambiguous"

    def test_bare_hex_uppercase(self):
        desc = _resolve("ABCDEF1")
        assert desc["mode"] == "ambiguous"

    def test_bare_hex_ambiguous_message_mentions_range(self):
        desc = _resolve("abc1234")
        msg = desc.get("message", "")
        assert "--range" in msg or "range" in msg.lower()

    # Bare hex that IS a slug should be slug, not ambiguous
    def test_hex_like_slug_wins(self):
        desc = _resolve("abc1234", slugs=("abc1234",))
        assert desc["mode"] == "slug"

    # not_found
    def test_not_found_arbitrary_string(self):
        desc = _resolve("totally-nonexistent-plan-xyz")
        assert desc["mode"] == "not_found"

    def test_not_found_message_actionable(self):
        desc = _resolve("totally-nonexistent-plan-xyz")
        msg = desc.get("message", "")
        assert any(kw in msg for kw in ("--slug", "--run", "--pr", "--range", "not match", "did not match"))

    def test_not_found_with_path_like_string(self):
        desc = _resolve("scripts/some-file.py")
        assert desc["mode"] == "not_found"


# ---------------------------------------------------------------------------
# Edge cases and boundary conditions
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_bare_int_does_not_match_run_id(self):
        """A bare integer should NOT be mode: run (run-ids start with date stamp)."""
        desc = _resolve("42")
        assert desc["mode"] != "run"

    def test_six_char_hex_not_matched_as_hex(self):
        """6-char hex is below the 7-char minimum; if not a slug, it should be not_found."""
        desc = _resolve("abc123")
        # 6 chars = not a hex match (< 7), and unlikely to be a slug
        # Should be not_found if not in slugs
        assert desc["mode"] in ("not_found", "ambiguous", "slug")
        # Since 'abc123' not in slugs default, must be not_found
        if desc["mode"] not in ("slug",):
            assert desc["mode"] == "not_found"

    def test_run_id_shape_beats_slug(self):
        """An ISO run-id that also happens to be a slug name maps to mode: run."""
        # 20260618T000000Z-test looks like a run-id prefix
        desc = _resolve("20260618T000000Z-myslug", slugs=("20260618T000000Z-myslug",))
        assert desc["mode"] == "run"

    def test_flag_run_beats_positional(self):
        desc = _resolve(target="sometoken", flag_run="20260618T120000Z-x")
        assert desc["mode"] == "run"
        assert desc["run_id"] == "20260618T120000Z-x"

    def test_descriptor_always_has_mode(self):
        """Every code path must return a dict with a 'mode' key."""
        cases = [
            {},
            {"target": "42"},
            {"target": "#5"},
            {"target": "main..HEAD"},
            {"flag_run": "20260618T000000Z-x"},
            {"flag_run": "x", "flag_pr": "1"},
        ]
        for kwargs in cases:
            desc = _resolve(**kwargs)
            assert "mode" in desc, f"Missing 'mode' for {kwargs}"


# ---------------------------------------------------------------------------
# CLI integration (subprocess)
# ---------------------------------------------------------------------------

class TestCLI:
    """Test the --resolve-only CLI path end-to-end via subprocess."""

    def _run_cli(self, *args: str) -> tuple[int, dict | None]:
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), "--resolve-only", *args],
            capture_output=True,
            text=True,
        )
        try:
            desc = json.loads(result.stdout)
        except json.JSONDecodeError:
            desc = None
        return result.returncode, desc

    def test_run_id_exits_0(self):
        rc, desc = self._run_cli("20260618T120000Z-myplan")
        assert rc == 0
        assert desc is not None
        assert desc["mode"] == "run"

    def test_hash_pr_exits_0(self):
        rc, desc = self._run_cli("#7")
        assert rc == 0
        assert desc is not None
        assert desc["mode"] == "pr"

    def test_range_exits_0(self):
        rc, desc = self._run_cli("main..HEAD")
        assert rc == 0
        assert desc is not None
        assert desc["mode"] == "range"

    def test_bare_int_exits_2(self):
        """Bare integer ⇒ ambiguous ⇒ exit code 2."""
        rc, desc = self._run_cli("42")
        assert rc == 2
        assert desc is not None
        assert desc["mode"] == "ambiguous"

    def test_bare_int_message_present(self):
        rc, desc = self._run_cli("42")
        assert desc is not None
        assert "message" in desc
        assert len(desc["message"]) > 0

    def test_flag_conflict_exits_1(self):
        """Flag conflict ⇒ error ⇒ exit code 1."""
        rc, desc = self._run_cli("--pr", "5", "--run", "20260618T120000Z-x")
        assert rc == 1
        assert desc is not None
        assert desc["mode"] == "error"

    def test_not_found_exits_2(self):
        rc, desc = self._run_cli("totally-nonexistent-xyzzy-plan-name-that-cannot-exist")
        assert rc == 2
        assert desc is not None
        assert desc["mode"] == "not_found"

    def test_pr_flag_cli(self):
        rc, desc = self._run_cli("--pr", "99")
        assert rc == 0
        assert desc is not None
        assert desc["mode"] == "pr"
        assert desc["pr"] == "99"

    def test_slug_flag_cli(self):
        rc, desc = self._run_cli("--slug", "some-plan")
        assert rc == 0
        assert desc is not None
        assert desc["mode"] == "slug"
        assert desc["slug"] == "some-plan"

    def test_run_flag_cli(self):
        rc, desc = self._run_cli("--run", "20260618T120000Z-runid")
        assert rc == 0
        assert desc is not None
        assert desc["mode"] == "run"

    def test_range_flag_cli(self):
        rc, desc = self._run_cli("--range", "main..HEAD")
        assert rc == 0
        assert desc is not None
        assert desc["mode"] == "range"

    def test_output_is_valid_json(self):
        """--resolve-only must always emit valid JSON regardless of mode."""
        for token in ("42", "#3", "main..HEAD", "20260618T000000Z-x", "unknownxyzzy"):
            _, desc = self._run_cli(token)
            assert desc is not None, f"Invalid JSON for token {token!r}"

    def test_github_url_pr(self):
        rc, desc = self._run_cli("https://github.com/org/repo/pull/15")
        assert rc == 0
        assert desc is not None
        assert desc["mode"] == "pr"
        assert desc["pr"] == "15"


# ---------------------------------------------------------------------------
# T002 — bundle assembly helpers (unit tests on assemble_bundle internals)
# ---------------------------------------------------------------------------

def _make_run_dir(tmp_path: Path, run_id: str, *, with_events: bool = True) -> Path:
    """Create a minimal run directory structure under tmp_path."""
    # Layout: tmp_path/<slug>/archive/<run_id>/events.jsonl
    slug = "test-plan"
    run_dir = tmp_path / slug / "archive" / run_id
    run_dir.mkdir(parents=True)

    if with_events:
        events = [
            {
                "ts": "2026-06-18T10:00:00Z",
                "run": run_id,
                "kind": "run_start",
                "slug": slug,
            },
            {
                "ts": "2026-06-18T10:01:00Z",
                "run": run_id,
                "kind": "phase_end",
                "phase": 0,
                "name": "setup",
                "wall_ms": 120,
                "user_wait_ms": 0,
            },
            {
                "ts": "2026-06-18T10:05:00Z",
                "run": run_id,
                "kind": "phase_end",
                "phase": 1,
                "name": "implement",
                "wall_ms": 240000,
                "user_wait_ms": 5000,
            },
            {
                "ts": "2026-06-18T10:10:00Z",
                "run": run_id,
                "kind": "user_choice",
                "question_id": "rollout_scope",
                "chosen": "full",
                "options": ["pilot", "full"],
            },
            {
                "ts": "2026-06-18T10:15:00Z",
                "run": run_id,
                "kind": "run_end",
                "slug": slug,
            },
        ]
        events_path = run_dir / "events.jsonl"
        with events_path.open("w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    return run_dir


def _make_run_dir_with_halt(tmp_path: Path, run_id: str) -> Path:
    """Create a run directory with a halt event."""
    slug = "test-plan-halt"
    run_dir = tmp_path / slug / "archive" / run_id
    run_dir.mkdir(parents=True)
    events = [
        {
            "ts": "2026-06-18T10:00:00Z",
            "run": run_id,
            "kind": "run_start",
            "slug": slug,
        },
        {
            "ts": "2026-06-18T10:05:00Z",
            "run": run_id,
            "kind": "task_halt",
            "task_id": "T003",
            "reason": "decision_needed",
        },
    ]
    events_path = run_dir / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return run_dir


# Load assemble_bundle + helpers from the module
_assemble_bundle = _mod.assemble_bundle
_assemble_run_slug_bundle = _mod._assemble_run_slug_bundle


def _bundle_for_run_dir(run_dir: Path) -> dict:
    """Call _assemble_run_slug_bundle directly, mocking external calls."""
    descriptor = {"mode": "run", "run_id": run_dir.name}
    warnings: list[str] = []
    with (
        patch.object(_mod, "_classify_status", return_value="clean"),
        patch.object(_mod, "_resolve_followups", return_value=[]),
        patch.object(_mod, "_estimate_cost", return_value={}),
    ):
        return _assemble_run_slug_bundle(descriptor, run_dir, warnings)


class TestBundleRunSlug:
    """T002: bundle assembly for mode=run from a fixture run directory."""

    def test_bundle_has_required_keys(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        required = {
            "schema_version", "mode", "run_id", "status",
            "run_brief_present", "decisions", "phases",
            "halts", "followups", "cost", "artifacts", "events_chars",
        }
        missing = required - set(bundle.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_bundle_schema_version(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["schema_version"] == 1

    def test_bundle_mode_is_run(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["mode"] == "run"

    def test_bundle_decisions_populated(self, tmp_path):
        """decisions must contain the user_choice event from the fixture."""
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        decisions = bundle["decisions"]
        assert isinstance(decisions, list)
        assert len(decisions) >= 1
        qids = [d.get("question_id") for d in decisions]
        assert "rollout_scope" in qids

    def test_bundle_phases_populated(self, tmp_path):
        """phases must contain entries from phase_end events."""
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        phases = bundle["phases"]
        assert isinstance(phases, list)
        assert len(phases) == 2  # setup + implement
        names = [p["name"] for p in phases]
        assert "setup" in names
        assert "implement" in names

    def test_bundle_phases_have_wall_ms(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        for phase in bundle["phases"]:
            assert "wall_ms" in phase
            assert isinstance(phase["wall_ms"], int)

    def test_bundle_events_chars_positive(self, tmp_path):
        """events_chars must be > 0 when events.jsonl is present."""
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["events_chars"] > 0

    def test_bundle_run_brief_present_false(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["run_brief_present"] is False

    def test_bundle_run_brief_present_true(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        (run_dir / "run-brief.json").write_text('{"artifact":"run_brief"}', encoding="utf-8")
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["run_brief_present"] is True

    def test_bundle_run_brief_narrative_surfaced(self, tmp_path):
        """T001: intent/outcome/key_decisions from run-brief.json surface as bundle['run_brief']."""
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        (run_dir / "run-brief.json").write_text(
            json.dumps({
                "intent": "Do the thing",
                "outcome": "Thing done",
                "approach": ["chose A over B", "kept C"],
            }),
            encoding="utf-8",
        )
        bundle = _bundle_for_run_dir(run_dir)
        rb = bundle["run_brief"]
        assert rb["intent"] == "Do the thing"
        assert rb["outcome"] == "Thing done"
        assert rb["key_decisions"] == ["chose A over B", "kept C"]

    def test_bundle_run_brief_absent_when_no_file(self, tmp_path):
        """T001: no run-brief.json → no run_brief key (not an empty dict)."""
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        assert "run_brief" not in bundle

    def test_bundle_run_brief_malformed_does_not_raise(self, tmp_path):
        """T001: garbage run-brief.json must not raise; key absent, warning appended."""
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        (run_dir / "run-brief.json").write_text("{not json", encoding="utf-8")
        bundle = _bundle_for_run_dir(run_dir)
        assert "run_brief" not in bundle
        assert any("run-brief parse failed" in w for w in bundle["warnings"])

    def test_bundle_transcripts_dir_surfaced(self, tmp_path):
        """T001: transcripts_dir surfaces only when the directory exists."""
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        assert "transcripts_dir" not in _bundle_for_run_dir(run_dir)
        (run_dir / "transcripts").mkdir()
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["transcripts_dir"] == str(run_dir / "transcripts")

    def test_bundle_halts_empty_when_no_halt(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["halts"] == []

    def test_bundle_halts_populated_when_halt_present(self, tmp_path):
        run_dir = _make_run_dir_with_halt(tmp_path, "20260618T110000Z-test-plan-halt")
        descriptor = {"mode": "run", "run_id": run_dir.name}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_classify_status", return_value="halted"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            bundle = _assemble_run_slug_bundle(descriptor, run_dir, warnings)
        assert len(bundle["halts"]) == 1
        assert bundle["halts"][0]["kind"] == "task_halt"

    def test_bundle_artifacts_list(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        # Add a SPEC.md to the plan dir
        plan_dir = run_dir.parent.parent
        (plan_dir / "SPEC.md").write_text("# spec", encoding="utf-8")
        bundle = _bundle_for_run_dir(run_dir)
        assert isinstance(bundle["artifacts"], list)
        artifact_names = [Path(a).name for a in bundle["artifacts"]]
        assert "SPEC.md" in artifact_names

    def test_bundle_slug_present_when_inferable(self, tmp_path):
        """slug should be populated from events if not in descriptor."""
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        bundle = _bundle_for_run_dir(run_dir)
        # The fixture events include slug="test-plan"
        assert bundle.get("slug") == "test-plan"


class TestBundleDegradedMissingEvents:
    """T002 acceptance: missing events.jsonl → degraded:'no_events', bundle still valid."""

    def test_degraded_when_no_events(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T120000Z-no-events", with_events=False)
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle.get("degraded") == "no_events"

    def test_degraded_status_unknown(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T120000Z-no-events", with_events=False)
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["status"] == "unknown"

    def test_degraded_decisions_empty(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T120000Z-no-events", with_events=False)
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["decisions"] == []

    def test_degraded_phases_empty(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T120000Z-no-events", with_events=False)
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["phases"] == []

    def test_degraded_events_chars_zero(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T120000Z-no-events", with_events=False)
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["events_chars"] == 0

    def test_degraded_bundle_has_required_keys(self, tmp_path):
        """Degraded bundle must still have all required top-level keys."""
        run_dir = _make_run_dir(tmp_path, "20260618T120000Z-no-events", with_events=False)
        bundle = _bundle_for_run_dir(run_dir)
        required = {
            "schema_version", "mode", "run_id", "status",
            "run_brief_present", "decisions", "phases",
            "halts", "followups", "cost", "artifacts", "events_chars",
        }
        missing = required - set(bundle.keys())
        assert not missing, f"Degraded bundle missing keys: {missing}"

    def test_degraded_followups_empty(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T120000Z-no-events", with_events=False)
        bundle = _bundle_for_run_dir(run_dir)
        assert bundle["followups"] == []


class TestBundleOvernightSpecialCase:
    """T002: overnight run-id suffix sets morning_report_path when file is present."""

    def test_overnight_morning_report_path_set(self, tmp_path):
        run_id = "20260618T020000Z-overnight-test-plan"
        slug = "test-plan"
        run_dir = tmp_path / slug / "archive" / run_id
        run_dir.mkdir(parents=True)
        # Write events.jsonl
        events_path = run_dir / "events.jsonl"
        with events_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": "2026-06-18T02:00:00Z",
                "run": run_id,
                "kind": "run_start",
                "slug": slug,
            }) + "\n")
        # Write MORNING_REPORT.md in plan dir
        plan_dir = run_dir.parent.parent
        morning_report = plan_dir / "MORNING_REPORT.md"
        morning_report.write_text("# Morning Report\n", encoding="utf-8")

        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            bundle = _assemble_run_slug_bundle(descriptor, run_dir, warnings)

        assert "morning_report_path" in bundle
        assert bundle["morning_report_path"] == str(morning_report)

    def test_overnight_no_morning_report_path_when_file_absent(self, tmp_path):
        run_id = "20260618T020000Z-overnight-test-plan"
        slug = "test-plan"
        run_dir = tmp_path / slug / "archive" / run_id
        run_dir.mkdir(parents=True)
        events_path = run_dir / "events.jsonl"
        with events_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": "2026-06-18T02:00:00Z", "run": run_id,
                "kind": "run_start", "slug": slug,
            }) + "\n")

        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            bundle = _assemble_run_slug_bundle(descriptor, run_dir, warnings)

        assert "morning_report_path" not in bundle

    def test_non_overnight_no_morning_report_key(self, tmp_path):
        run_id = "20260618T100000Z-test-plan"
        run_dir = _make_run_dir(tmp_path, run_id)
        bundle = _bundle_for_run_dir(run_dir)
        assert "morning_report_path" not in bundle


class TestBundleWrittenToDisk:
    """T002: assemble_bundle writes context.json and returns exit code 0."""

    def test_bundle_written_to_out_path(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "run", "run_id": run_dir.name}
        with (
            patch.object(_mod, "_resolve_run_dir", return_value=run_dir),
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)

        assert rc == 0
        assert out_path.is_file()
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["schema_version"] == 1
        assert bundle["mode"] == "run"

    def test_bundle_json_is_valid(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260618T100000Z-test-plan")
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "run", "run_id": run_dir.name}
        with (
            patch.object(_mod, "_resolve_run_dir", return_value=run_dir),
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)

        assert rc == 0
        raw = out_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_bundle_pr_mode_returns_1_when_gh_unavailable(self, tmp_path):
        """PR mode returns exit 1 when gh is not available (error path), not crash."""
        descriptor = {"mode": "pr", "pr": "42"}
        with patch.object(_mod, "_gh_available", return_value=False):
            rc = _assemble_bundle(descriptor, out_path=None, base=None)
        assert rc == 1

    def test_bundle_range_mode_now_implemented(self, tmp_path):
        """Range mode is now implemented in T003 — must write bundle and return 0."""
        # We patch git calls so we don't need a real repo
        descriptor = {"mode": "range", "range": "base..HEAD"}
        out_path = tmp_path / "context.json"
        with (
            patch.object(_mod, "_run_cmd_capture", return_value=(0, "", "")),
        ):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)
        assert rc == 0
        assert out_path.is_file()

    def test_bundle_error_mode_returns_nonzero(self, tmp_path):
        descriptor = {"mode": "error", "message": "Conflicting flags"}
        rc = _assemble_bundle(descriptor, out_path=None, base=None)
        assert rc != 0


# ---------------------------------------------------------------------------
# T003 — diff-backed bundle assembly (pr / range / base / worktree)
# ---------------------------------------------------------------------------

def _make_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repository with two commits on a feature branch.

    Creates an initial commit on ``base`` branch, then a ``feature`` branch
    with one more commit.  Uses ``-b base`` so the test is not affected by
    the system's ``init.defaultBranch`` setting (which may be ``master`` or
    ``main`` depending on git version / user config).
    """
    repo = tmp_path / "testrepo"
    repo.mkdir()

    def _git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=str(repo),
        )
        return result.stdout.strip()

    _git("init", "-b", "base")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "Test")
    # Initial commit on base
    (repo / "README.md").write_text("# Hello\n", encoding="utf-8")
    _git("add", "README.md")
    _git("commit", "-m", "initial commit")
    # Feature branch with one more file
    _git("checkout", "-b", "feature")
    (repo / "feature.txt").write_text("feature content\n", encoding="utf-8")
    _git("add", "feature.txt")
    _git("commit", "-m", "add feature.txt")
    return repo


# Load the diff bundle helpers from the module
_assemble_range_bundle = _mod._assemble_range_bundle
_assemble_worktree_bundle = _mod._assemble_worktree_bundle
_assemble_pr_bundle = _mod._assemble_pr_bundle


class TestRangeBundleGitFixture:
    """T003: range bundle built against a real temp git repo fixture."""

    def test_range_diff_bytes_positive(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "range": "base..HEAD"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert bundle["diff_bytes"] > 0, "diff_bytes must be > 0 for a non-empty range"

    def test_range_diff_content_present(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "range": "base..HEAD"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert "feature.txt" in bundle["diff"], "diff must contain the added file"

    def test_range_commits_populated(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "range": "base..HEAD"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert len(bundle["commits"]) >= 1, "commits must be populated for the range"

    def test_range_commits_have_oid(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "range": "base..HEAD"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        for commit in bundle["commits"]:
            assert "oid" in commit

    def test_range_followups_empty(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "range": "base..HEAD"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert bundle["followups"] == []

    def test_range_followups_note_present(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "range": "base..HEAD"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert "followups_note" in bundle
        assert len(bundle["followups_note"]) > 0

    def test_range_required_keys(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "range": "base..HEAD"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        required = {"schema_version", "mode", "commits", "diff", "diff_bytes",
                    "followups", "followups_note"}
        missing = required - set(bundle.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_range_schema_version(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "range": "base..HEAD"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert bundle["schema_version"] == 1

    def test_range_no_crash_on_bad_range(self, tmp_path):
        """A bad range must produce a warning and an empty diff, not an exception."""
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "range": "nonexistent-branch-xyz..HEAD"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        # Must not raise; diff_bytes must still be populated (0 is fine for empty/failed diff)
        assert "diff_bytes" in bundle
        # At least one warning should mention the failure
        assert len(warnings) >= 1


class TestBaseBundleGitFixture:
    """T003: base-ref bundle (git diff <base>...HEAD) against a real temp git repo."""

    def test_base_diff_bytes_positive(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "base": "base"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert bundle["diff_bytes"] > 0

    def test_base_commits_populated(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "base": "base"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert len(bundle["commits"]) >= 1

    def test_base_followups_empty_with_note(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "base": "base"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert bundle["followups"] == []
        assert "followups_note" in bundle

    def test_base_diff_bytes_populated_even_if_zero(self, tmp_path):
        """diff_bytes key must always exist (size gate depends on it)."""
        repo = _make_git_repo(tmp_path)
        descriptor = {"mode": "range", "base": "base"}
        warnings: list[str] = []
        bundle = _assemble_range_bundle(descriptor, warnings, cwd=str(repo))
        assert "diff_bytes" in bundle
        assert isinstance(bundle["diff_bytes"], int)


class TestWorktreeBundleGitFixture:
    """T003: worktree bundle (git diff + git diff --staged) against a real temp git repo."""

    def _make_worktree_with_changes(self, tmp_path: Path) -> Path:
        """Create a repo with both staged and unstaged changes."""
        repo = _make_git_repo(tmp_path)
        # Add an unstaged change
        (repo / "README.md").write_text("# Hello\nchanged\n", encoding="utf-8")
        # Add a staged change
        (repo / "staged.txt").write_text("staged content\n", encoding="utf-8")
        subprocess.run(["git", "add", "staged.txt"], cwd=str(repo), capture_output=True)
        return repo

    def test_worktree_diff_bytes_positive(self, tmp_path):
        repo = self._make_worktree_with_changes(tmp_path)
        warnings: list[str] = []
        bundle = _assemble_worktree_bundle(warnings, cwd=str(repo))
        assert bundle["diff_bytes"] > 0

    def test_worktree_diff_contains_staged(self, tmp_path):
        repo = self._make_worktree_with_changes(tmp_path)
        warnings: list[str] = []
        bundle = _assemble_worktree_bundle(warnings, cwd=str(repo))
        # staged.txt was git-added, must appear in staged diff
        assert "staged.txt" in bundle["diff"]

    def test_worktree_diff_contains_unstaged(self, tmp_path):
        repo = self._make_worktree_with_changes(tmp_path)
        warnings: list[str] = []
        bundle = _assemble_worktree_bundle(warnings, cwd=str(repo))
        # README.md was modified but not staged, must appear in unstaged diff
        assert "README.md" in bundle["diff"]

    def test_worktree_commits_populated(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        warnings: list[str] = []
        bundle = _assemble_worktree_bundle(warnings, cwd=str(repo))
        # The fixture has 2 commits; -10 log should return at least 1
        assert len(bundle["commits"]) >= 1

    def test_worktree_followups_empty_with_note(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        warnings: list[str] = []
        bundle = _assemble_worktree_bundle(warnings, cwd=str(repo))
        assert bundle["followups"] == []
        assert "followups_note" in bundle

    def test_worktree_required_keys(self, tmp_path):
        repo = _make_git_repo(tmp_path)
        warnings: list[str] = []
        bundle = _assemble_worktree_bundle(warnings, cwd=str(repo))
        required = {"schema_version", "mode", "commits", "diff", "diff_bytes",
                    "followups", "followups_note"}
        missing = required - set(bundle.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_worktree_diff_bytes_always_int(self, tmp_path):
        """diff_bytes must always be an int, even when there are no changes."""
        repo = _make_git_repo(tmp_path)  # clean repo, no pending changes
        warnings: list[str] = []
        bundle = _assemble_worktree_bundle(warnings, cwd=str(repo))
        assert isinstance(bundle["diff_bytes"], int)


class TestPrModeGhAbsent:
    """T003: PR mode when gh CLI is absent or unauth → clean error descriptor."""

    def test_gh_absent_returns_message(self):
        """When gh is not on PATH, bundle must have a non-empty 'message' field."""
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with patch.object(_mod, "_gh_available", return_value=False):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert "message" in bundle
        assert len(bundle["message"]) > 0

    def test_gh_absent_message_mentions_install(self):
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with patch.object(_mod, "_gh_available", return_value=False):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        msg = bundle["message"].lower()
        assert any(kw in msg for kw in ("install", "gh", "cli"))

    def test_gh_absent_diff_bytes_zero(self):
        """diff_bytes must still be present (key exists, value 0) when gh missing."""
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with patch.object(_mod, "_gh_available", return_value=False):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert "diff_bytes" in bundle
        assert bundle["diff_bytes"] == 0

    def test_gh_absent_followups_empty_with_note(self):
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with patch.object(_mod, "_gh_available", return_value=False):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert bundle["followups"] == []
        assert "followups_note" in bundle

    def test_gh_unauth_returns_message(self):
        """When gh is present but not authenticated, bundle must have 'message'."""
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=False),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert "message" in bundle
        assert len(bundle["message"]) > 0

    def test_gh_unauth_message_mentions_auth(self):
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=False),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        msg = bundle["message"].lower()
        assert any(kw in msg for kw in ("auth", "login", "authenticated"))

    def test_gh_unauth_diff_bytes_zero(self):
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=False),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert "diff_bytes" in bundle
        assert bundle["diff_bytes"] == 0

    def test_gh_view_failure_returns_message(self):
        """If gh pr view fails (non-zero), bundle must have a 'message'."""
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=True),
            patch.object(_mod, "_run_cmd_capture",
                         return_value=(1, "", "Could not resolve to a pull request")),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert "message" in bundle
        assert len(warnings) >= 1

    def test_gh_absent_bundle_never_crashes(self):
        """_assemble_pr_bundle must never raise regardless of gh state."""
        descriptor = {"mode": "pr", "pr": "99"}
        warnings: list[str] = []
        # Simulate OSError from _gh_available
        with patch.object(_mod, "_gh_available", side_effect=OSError("no gh")):
            try:
                bundle = _assemble_pr_bundle(descriptor, warnings)
            except OSError:
                pytest.fail("_assemble_pr_bundle raised OSError — must not crash")


class TestPrModeGhSuccess:
    """T003: PR mode with a mocked successful gh response."""

    _FAKE_PR_JSON = json.dumps({
        "title": "Add feature X",
        "body": "This PR adds feature X.",
        "state": "OPEN",
        "commits": [
            {"oid": "abc1234", "messageHeadline": "add feature.txt"},
        ],
        "files": [{"path": "feature.txt", "additions": 1, "deletions": 0}],
    })
    _FAKE_DIFF = "diff --git a/feature.txt b/feature.txt\n+feature content\n"

    def _mock_run_cmd(self, cmd, **kwargs):
        if "gh" in cmd and "view" in cmd:
            return (0, self._FAKE_PR_JSON, "")
        if "gh" in cmd and "diff" in cmd:
            return (0, self._FAKE_DIFF, "")
        return (0, "", "")

    def test_pr_success_has_required_keys(self):
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=True),
            patch.object(_mod, "_run_cmd_capture", side_effect=self._mock_run_cmd),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        required = {"schema_version", "mode", "pr", "title", "state",
                    "commits", "diff", "diff_bytes", "followups", "followups_note"}
        missing = required - set(bundle.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_pr_success_diff_bytes_positive(self):
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=True),
            patch.object(_mod, "_run_cmd_capture", side_effect=self._mock_run_cmd),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert bundle["diff_bytes"] > 0

    def test_pr_success_commits_populated(self):
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=True),
            patch.object(_mod, "_run_cmd_capture", side_effect=self._mock_run_cmd),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert len(bundle["commits"]) >= 1
        assert bundle["commits"][0]["oid"] == "abc1234"

    def test_pr_success_title_state(self):
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=True),
            patch.object(_mod, "_run_cmd_capture", side_effect=self._mock_run_cmd),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert bundle["title"] == "Add feature X"
        assert bundle["state"] == "OPEN"

    def test_pr_success_followups_empty_with_note(self):
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=True),
            patch.object(_mod, "_run_cmd_capture", side_effect=self._mock_run_cmd),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert bundle["followups"] == []
        assert "followups_note" in bundle

    def test_pr_success_no_message_key(self):
        """Success path must NOT have 'message' key (that's reserved for error descriptors)."""
        descriptor = {"mode": "pr", "pr": "42"}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=True),
            patch.object(_mod, "_run_cmd_capture", side_effect=self._mock_run_cmd),
        ):
            bundle = _assemble_pr_bundle(descriptor, warnings)
        assert "message" not in bundle


class TestAssembleBundleDiffModes:
    """T003: assemble_bundle integration for diff-backed modes writes valid context.json."""

    def test_range_bundle_written(self, tmp_path):
        """assemble_bundle for mode=range writes a valid JSON file and returns 0."""
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "range", "range": "main..HEAD"}
        with patch.object(_mod, "_run_cmd_capture", return_value=(0, "", "")):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)
        assert rc == 0
        assert out_path.is_file()
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["mode"] == "range"
        assert "diff_bytes" in bundle

    def test_worktree_bundle_written(self, tmp_path):
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "worktree"}
        with patch.object(_mod, "_run_cmd_capture", return_value=(0, "", "")):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)
        assert rc == 0
        assert out_path.is_file()
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["mode"] == "worktree"
        assert "diff_bytes" in bundle

    def test_pr_bundle_gh_absent_returns_1(self, tmp_path):
        """assemble_bundle for mode=pr when gh missing must return 1 (error) not crash."""
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "pr", "pr": "42"}
        with patch.object(_mod, "_gh_available", return_value=False):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)
        assert rc == 1
        # Bundle file is still written (allows inspection)
        assert out_path.is_file()
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert "message" in bundle

    def test_pr_bundle_success_returns_0(self, tmp_path):
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "pr", "pr": "7"}
        fake_pr_json = json.dumps({
            "title": "T", "body": "", "state": "MERGED",
            "commits": [], "files": [],
        })

        def _mock(cmd, **kw):
            if "view" in cmd:
                return (0, fake_pr_json, "")
            if "diff" in cmd:
                return (0, "diff --git a/x b/x\n+line\n", "")
            return (0, "", "")

        with (
            patch.object(_mod, "_gh_available", return_value=True),
            patch.object(_mod, "_gh_auth_ok", return_value=True),
            patch.object(_mod, "_run_cmd_capture", side_effect=_mock),
        ):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)
        assert rc == 0


# ---------------------------------------------------------------------------
# T011-FIX — run-id resolver: glob search across <plans>/<slug>/archive/<run-id>
# ---------------------------------------------------------------------------

def _make_plans_archive(tmp_path: Path, slug: str, run_id: str,
                        *, with_events: bool = True) -> tuple[Path, Path]:
    """Create a fake plans-base tree: <tmp>/plans/<slug>/archive/<run_id>/events.jsonl.

    Returns (plans_base, run_dir).
    """
    plans_base = tmp_path / "zh-base"
    run_dir = plans_base / "plans" / slug / "archive" / run_id
    run_dir.mkdir(parents=True)
    if with_events:
        events_path = run_dir / "events.jsonl"
        events_path.write_text(
            json.dumps({
                "ts": "2026-06-18T10:00:00Z",
                "run": run_id,
                "kind": "run_start",
                "slug": slug,
            }) + "\n",
            encoding="utf-8",
        )
    return plans_base, run_dir


_resolve_run_dir = _mod._resolve_run_dir


class TestResolveRunDirByRunId:
    """T011-FIX: _resolve_run_dir must find the archive dir when given only run_id."""

    def _patch_base(self, plans_base: Path):
        """Return a context-manager that fakes plan-path.sh base_dir → plans_base."""
        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            # Fallback for any other subcommand
            return (1, "", "not mocked")
        return patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path)

    def test_run_dir_found_for_known_run_id(self, tmp_path):
        """_resolve_run_dir must return the correct path for a run-id that exists."""
        run_id = "20260619T005255Z-disposition-amend-brief-audit-plan"
        plans_base, expected_run_dir = _make_plans_archive(tmp_path, "my-slug", run_id)
        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with self._patch_base(plans_base):
            result = _resolve_run_dir(descriptor, warnings)
        assert result is not None, "Expected a non-None run_dir"
        assert result == expected_run_dir

    def test_run_dir_points_at_correct_archive_path(self, tmp_path):
        """run_dir must be exactly <plans_base>/plans/<slug>/archive/<run_id>."""
        run_id = "20260620T120000Z-my-plan"
        plans_base, expected = _make_plans_archive(tmp_path, "my-plan", run_id)
        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with self._patch_base(plans_base):
            result = _resolve_run_dir(descriptor, warnings)
        assert result is not None
        assert result.is_dir()
        assert result.name == run_id

    def test_run_dir_not_found_returns_none(self, tmp_path):
        """An ISO-shaped run_id with no matching archive must return None, not crash."""
        run_id = "20260101T000000Z-nonexistent-run"
        plans_base = tmp_path / "zh-base"
        plans_base.mkdir(parents=True)
        (plans_base / "plans").mkdir()
        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with self._patch_base(plans_base):
            result = _resolve_run_dir(descriptor, warnings)
        assert result is None

    def test_run_dir_not_found_emits_warning(self, tmp_path):
        """When run_id not found, a descriptive warning must be appended."""
        run_id = "20260101T000000Z-nonexistent-run"
        plans_base = tmp_path / "zh-base"
        (plans_base / "plans").mkdir(parents=True)
        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with self._patch_base(plans_base):
            _resolve_run_dir(descriptor, warnings)
        assert len(warnings) >= 1
        assert any(run_id in w for w in warnings)

    def test_run_dir_found_under_different_slug(self, tmp_path):
        """The resolver must find the archive even when the slug differs from run-id suffix."""
        run_id = "20260619T005255Z-disposition-amend-brief-audit-plan"
        # slug is a DIFFERENT name from what's embedded in the run-id
        plans_base, expected = _make_plans_archive(tmp_path, "totally-different-slug", run_id)
        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with self._patch_base(plans_base):
            result = _resolve_run_dir(descriptor, warnings)
        assert result is not None
        assert result == expected

    def test_assemble_bundle_events_chars_positive_when_run_id_given(self, tmp_path):
        """Regression: assemble_bundle with mode:run + run_id must populate events_chars > 0."""
        run_id = "20260619T100000Z-test-regression"
        plans_base, run_dir = _make_plans_archive(tmp_path, "my-plan", run_id)
        out_path = tmp_path / "ctx.json"
        descriptor = {"mode": "run", "run_id": run_id}

        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            return (1, "", "not mocked")

        with (
            patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path),
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["events_chars"] > 0, (
            "events_chars must be > 0 when the run-id archive exists and has events.jsonl"
        )
        assert bundle["status"] != "unknown" or bundle.get("degraded") is None

    def test_assemble_bundle_not_found_run_id_produces_degraded_bundle(self, tmp_path):
        """When run_id has no matching archive, bundle degrades gracefully (no crash)."""
        run_id = "20260101T000000Z-not-there"
        plans_base = tmp_path / "zh-base"
        (plans_base / "plans").mkdir(parents=True)
        out_path = tmp_path / "ctx.json"
        descriptor = {"mode": "run", "run_id": run_id}

        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            return (1, "", "not mocked")

        with patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)

        assert rc == 0  # graceful degradation, not a crash
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["events_chars"] == 0
        assert bundle.get("degraded") == "no_run_dir"


# ---------------------------------------------------------------------------
# T011-FIX2 — run_dir emitted in --resolve-only descriptor AND context.json
# ---------------------------------------------------------------------------

class TestRunDirInResolveOnly:
    """T011-FIX2: --resolve-only for run/slug modes must include run_dir."""

    def _patch_base(self, plans_base: Path):
        """Return a context-manager that fakes plan-path.sh base_dir → plans_base."""
        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            return (1, "", "not mocked")
        return patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path)

    def test_resolve_only_run_emits_run_dir(self, tmp_path):
        """--resolve-only --run <id> descriptor must contain run_dir pointing at the archive."""
        run_id = "20260619T100000Z-fix2-test"
        plans_base, expected_run_dir = _make_plans_archive(tmp_path, "fix2-slug", run_id)
        with (
            self._patch_base(plans_base),
            patch.object(_mod, "_active_plan_records", return_value=[]),
            patch.object(_mod, "_all_plan_slugs", return_value=[]),
            patch.object(_mod, "_slug_exists", return_value=False),
        ):
            rc = main(["--resolve-only", "--run", run_id])
        # We can't capture stdout from main() directly, so call _resolve_run_dir separately
        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with self._patch_base(plans_base):
            resolved = _mod._resolve_run_dir(descriptor, warnings)
        assert resolved is not None
        assert str(resolved) == str(expected_run_dir)

    def test_resolve_only_run_descriptor_has_run_dir(self, tmp_path):
        """Calling main() --resolve-only --run captures run_dir via stdout (subprocess test)."""
        run_id = "20260619T110000Z-fix2-runid"
        plans_base, expected_run_dir = _make_plans_archive(tmp_path, "fix2-slug2", run_id)

        # Use subprocess so we can capture stdout
        env_vars = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
        # Patch via monkeypatching not feasible in subprocess; use direct module invocation
        # via importlib to stay in-process and capture output.
        import io
        from contextlib import redirect_stdout

        captured = io.StringIO()
        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            return (1, "", "not mocked")

        with (
            patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path),
            patch.object(_mod, "_active_plan_records", return_value=[]),
            patch.object(_mod, "_all_plan_slugs", return_value=[]),
            patch.object(_mod, "_slug_exists", return_value=False),
            redirect_stdout(captured),
        ):
            rc = main(["--resolve-only", "--run", run_id])

        assert rc == 0
        descriptor = json.loads(captured.getvalue())
        assert "run_dir" in descriptor, (
            f"run_dir absent from --resolve-only descriptor; got keys: {list(descriptor.keys())}"
        )
        assert descriptor["run_dir"] == str(expected_run_dir)

    def test_resolve_only_slug_descriptor_has_run_dir(self, tmp_path):
        """--resolve-only --slug <s> descriptor must contain run_dir of the latest run."""
        slug = "fix2-slug3"
        run_id = "20260619T120000Z-fix2-slug-run"
        plans_base, expected_run_dir = _make_plans_archive(tmp_path, slug, run_id)

        import io
        from contextlib import redirect_stdout

        captured = io.StringIO()
        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            if subcommand == "resolve_plan_path":
                slug_arg = args[0] if args else ""
                plan_dir = plans_base / "plans" / slug_arg
                if plan_dir.is_dir():
                    return (0, str(plan_dir), "")
                return (1, "", "not found")
            return (1, "", "not mocked")

        with (
            patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path),
            patch.object(_mod, "_active_plan_records", return_value=[]),
            patch.object(_mod, "_all_plan_slugs", return_value=[slug]),
            patch.object(_mod, "_slug_exists", return_value=True),
            redirect_stdout(captured),
        ):
            rc = main(["--resolve-only", "--slug", slug])

        assert rc == 0
        descriptor = json.loads(captured.getvalue())
        assert "run_dir" in descriptor, (
            f"run_dir absent from --slug --resolve-only descriptor; got keys: {list(descriptor.keys())}"
        )
        assert descriptor["run_dir"] == str(expected_run_dir)

    def test_resolve_only_run_dir_absent_when_not_found(self, tmp_path):
        """If run_id has no matching archive, run_dir must be absent (not empty string)."""
        run_id = "20260101T000000Z-nonexistent-for-fix2"
        plans_base = tmp_path / "zh-base"
        (plans_base / "plans").mkdir(parents=True)

        import io
        from contextlib import redirect_stdout

        captured = io.StringIO()
        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            return (1, "", "not mocked")

        with (
            patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path),
            patch.object(_mod, "_active_plan_records", return_value=[]),
            patch.object(_mod, "_all_plan_slugs", return_value=[]),
            patch.object(_mod, "_slug_exists", return_value=False),
            redirect_stdout(captured),
        ):
            rc = main(["--resolve-only", "--run", run_id])

        assert rc == 0  # mode:run is still a valid descriptor, run_dir just absent
        descriptor = json.loads(captured.getvalue())
        # When run_dir cannot be resolved, it must be absent (not empty string)
        run_dir_val = descriptor.get("run_dir")
        assert not run_dir_val, (
            f"run_dir should be absent when archive not found; got: {run_dir_val!r}"
        )

    def test_resolve_only_pr_mode_has_no_run_dir(self):
        """--resolve-only for pr mode must NOT have run_dir (diff-backed modes are excluded)."""
        import io
        from contextlib import redirect_stdout

        captured = io.StringIO()
        with redirect_stdout(captured):
            rc = main(["--resolve-only", "--pr", "42"])

        assert rc == 0
        descriptor = json.loads(captured.getvalue())
        assert descriptor["mode"] == "pr"
        assert "run_dir" not in descriptor


class TestRunDirInBundle:
    """T011-FIX2: context.json bundle for run/slug modes must include run_dir."""

    def test_bundle_has_run_dir(self, tmp_path):
        """Normal (events present) bundle must contain run_dir as an absolute path string."""
        run_dir = _make_run_dir(tmp_path, "20260619T130000Z-fix2-bundle")
        descriptor = {"mode": "run", "run_id": run_dir.name}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            bundle = _assemble_run_slug_bundle(descriptor, run_dir, warnings)

        assert "run_dir" in bundle, (
            f"run_dir absent from bundle keys: {list(bundle.keys())}"
        )
        assert bundle["run_dir"] == str(run_dir)

    def test_bundle_run_dir_is_absolute(self, tmp_path):
        """run_dir in bundle must be an absolute path (starts with /)."""
        run_dir = _make_run_dir(tmp_path, "20260619T140000Z-fix2-abs")
        descriptor = {"mode": "run", "run_id": run_dir.name}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            bundle = _assemble_run_slug_bundle(descriptor, run_dir, warnings)

        assert bundle["run_dir"].startswith("/"), (
            f"run_dir must be absolute, got: {bundle['run_dir']!r}"
        )

    def test_degraded_bundle_has_run_dir(self, tmp_path):
        """Degraded (no events) bundle must also contain run_dir."""
        run_dir = _make_run_dir(tmp_path, "20260619T150000Z-fix2-degraded", with_events=False)
        bundle = _bundle_for_run_dir(run_dir)

        assert bundle.get("degraded") == "no_events"
        assert "run_dir" in bundle, (
            f"run_dir absent from degraded bundle keys: {list(bundle.keys())}"
        )
        assert bundle["run_dir"] == str(run_dir)

    def test_assemble_bundle_writes_run_dir_to_context_json(self, tmp_path):
        """assemble_bundle must write run_dir into the context.json output file."""
        run_id = "20260619T160000Z-fix2-ctx"
        plans_base, run_dir = _make_plans_archive(tmp_path, "fix2-ctx-slug", run_id)
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "run", "run_id": run_id}

        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            return (1, "", "not mocked")

        with (
            patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path),
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert "run_dir" in bundle, (
            f"run_dir absent from context.json keys: {list(bundle.keys())}"
        )
        assert bundle["run_dir"] == str(run_dir), (
            f"Expected run_dir={run_dir!r}, got {bundle['run_dir']!r}"
        )

    def test_bundle_run_dir_is_non_empty_string(self, tmp_path):
        """run_dir in bundle must be a non-empty string, not None or empty."""
        run_dir = _make_run_dir(tmp_path, "20260619T170000Z-fix2-nonempty")
        descriptor = {"mode": "run", "run_id": run_dir.name}
        warnings: list[str] = []
        with (
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            bundle = _assemble_run_slug_bundle(descriptor, run_dir, warnings)

        val = bundle.get("run_dir")
        assert val and isinstance(val, str), (
            f"run_dir must be a non-empty string, got: {val!r}"
        )


# T011-FIX3 — run-id resolver handles nested/archived plan graveyard layout
# ---------------------------------------------------------------------------


def _make_nested_plans_archive(
    tmp_path: Path, slug: str, run_id: str, *, with_events: bool = True
) -> tuple[Path, Path]:
    """Create a NESTED plans-base tree mimicking the archived plan graveyard layout:
    <tmp>/zh-base/plans/archive/<slug>/archive/<run_id>/events.jsonl

    This is deeper than the primary layout (<base>/plans/<slug>/archive/<run_id>)
    and was not matched by the old two-depth-level glob.

    Returns (plans_base, run_dir).
    """
    plans_base = tmp_path / "zh-base"
    run_dir = plans_base / "plans" / "archive" / slug / "archive" / run_id
    run_dir.mkdir(parents=True)
    if with_events:
        events_path = run_dir / "events.jsonl"
        events_path.write_text(
            json.dumps({
                "ts": "2026-06-12T03:46:21Z",
                "run": run_id,
                "kind": "run_start",
                "slug": slug,
            }) + "\n",
            encoding="utf-8",
        )
    return plans_base, run_dir


class TestResolveRunDirNestedLayout:
    """T011-FIX3: _resolve_run_dir must resolve the archived plan graveyard layout.

    Repro: plans/archive/<slug>/archive/<run_id> was silently skipped by the
    old two-fixed-depth globs; the recursive glob introduced in T011-FIX3 must
    find it correctly.
    """

    def _patch_base(self, plans_base: Path):
        """Return a context-manager that fakes plan-path.sh base_dir → plans_base."""
        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            return (1, "", "not mocked")
        return patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path)

    def test_nested_run_dir_found(self, tmp_path):
        """_resolve_run_dir must return the nested path for the graveyard layout."""
        run_id = "20260612T034621Z-implement"
        plans_base, expected_run_dir = _make_nested_plans_archive(
            tmp_path, "attended-chain", run_id
        )
        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with self._patch_base(plans_base):
            result = _resolve_run_dir(descriptor, warnings)
        assert result is not None, (
            f"Expected nested run_dir to be found; got None. "
            f"Expected path: {expected_run_dir}"
        )
        assert result == expected_run_dir, (
            f"Expected {expected_run_dir!r}, got {result!r}"
        )

    def test_nested_run_dir_is_a_directory(self, tmp_path):
        """Resolved nested run_dir must be an actual directory on disk."""
        run_id = "20260612T034621Z-implement"
        plans_base, expected_run_dir = _make_nested_plans_archive(
            tmp_path, "attended-chain", run_id
        )
        descriptor = {"mode": "run", "run_id": run_id}
        warnings: list[str] = []
        with self._patch_base(plans_base):
            result = _resolve_run_dir(descriptor, warnings)
        assert result is not None
        assert result.is_dir(), f"Resolved path {result!r} is not a directory"

    def test_nested_events_chars_positive(self, tmp_path):
        """assemble_bundle with a nested run-id layout must populate events_chars > 0."""
        run_id = "20260612T034621Z-implement"
        plans_base, _ = _make_nested_plans_archive(tmp_path, "attended-chain", run_id)
        out_path = tmp_path / "ctx.json"
        descriptor = {"mode": "run", "run_id": run_id}

        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base), "")
            return (1, "", "not mocked")

        with (
            patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path),
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
        ):
            rc = _assemble_bundle(descriptor, out_path=out_path, base=None)

        assert rc == 0, f"assemble_bundle returned non-zero rc={rc}"
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        events_chars = bundle.get("events_chars", 0)
        assert events_chars > 0, (
            "events_chars must be > 0 for nested graveyard layout; "
            f"got {events_chars!r}. bundle keys: {list(bundle.keys())}"
        )

    def test_nested_layout_not_broken_by_primary_layout_coexistence(self, tmp_path):
        """When BOTH primary and nested layouts exist for different slugs/run-ids,
        each run-id must resolve to its own correct archive directory."""
        primary_run_id = "20260619T005255Z-primary-plan"
        nested_run_id = "20260612T034621Z-implement"

        # Primary layout: <base>/plans/<slug>/archive/<run_id>
        plans_base_a, primary_expected = _make_plans_archive(
            tmp_path, "primary-slug", primary_run_id
        )
        # The nested layout must live under the SAME plans_base.
        # _make_nested_plans_archive would create a second zh-base; reuse the
        # same one by constructing the path manually.
        nested_run_dir = (
            plans_base_a / "plans" / "archive" / "attended-chain" / "archive" / nested_run_id
        )
        nested_run_dir.mkdir(parents=True)
        (nested_run_dir / "events.jsonl").write_text(
            json.dumps({"run": nested_run_id, "kind": "run_start"}) + "\n",
            encoding="utf-8",
        )

        def _fake_run_plan_path(subcommand, *args):
            if subcommand == "base_dir":
                return (0, str(plans_base_a), "")
            return (1, "", "not mocked")

        with patch.object(_mod, "_run_plan_path", side_effect=_fake_run_plan_path):
            result_primary = _resolve_run_dir(
                {"mode": "run", "run_id": primary_run_id}, []
            )
            result_nested = _resolve_run_dir(
                {"mode": "run", "run_id": nested_run_id}, []
            )

        assert result_primary == primary_expected, (
            f"Primary run_id resolved to wrong path: {result_primary!r}"
        )
        assert result_nested == nested_run_dir, (
            f"Nested run_id resolved to wrong path: {result_nested!r}"
        )


# ---------------------------------------------------------------------------
# T006 — surface-map attachment and repo-state aliases
# ---------------------------------------------------------------------------

def _surface_payload(*, status: str = "ok", path: str = "src/example.py") -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-06-25T00:00:00Z",
        "mode": "diff",
        "caller": "z-report",
        "status": status,
        "target": {
            "raw": "test",
            "repo_root": str(_REPO_ROOT),
            "inferred_kind": "diff",
        },
        "caps": {"max_primary_files": 10, "max_refs": 100, "max_bytes": 200000},
        "stats": {"files_scanned": 1, "candidate_files": 1, "refs": 1, "truncated": False},
        "primary": [
            {
                "path": path,
                "kind": "changed_file",
                "relation": "changes",
                "line_start": 1,
                "line_end": 2,
                "citations": [f"{path}:1"],
                "reason": "file appears in unified diff",
                "confidence": "high",
            }
        ],
        "related": [],
        "clusters": [{"id": "C1", "label": "Source", "paths": [path], "summary": "source files"}],
        "suggested_reads": [{"path": path, "ranges": ["1-2"], "reason": "changed hunks from diff"}],
        "warnings": [],
        "tried_strategies": ["test"],
    }


def _fake_diff(path: str = "src/example.py") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )


class TestSurfaceMapAttachment:
    def test_fresh_diff_surface_attached_for_standard_auto(self, tmp_path):
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "range", "range": "base..HEAD"}

        with patch.object(
            _mod,
            "_assemble_range_bundle",
            return_value={
                "schema_version": 1,
                "mode": "range",
                "followups": [],
                "followups_note": "diff-backed target",
                "commits": [],
                "diff": _fake_diff("src/fresh.py"),
                "diff_bytes": len(_fake_diff("src/fresh.py").encode("utf-8")),
                "warnings": [],
            },
        ):
            rc = _assemble_bundle(
                descriptor,
                out_path=out_path,
                base=None,
                surface_policy="auto",
                tier="standard",
            )

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["surface_map_status"] == "fresh"
        assert bundle["surface_map_source"] == "diff_context"
        assert "src/fresh.py" in bundle["surface_map_summary"]
        assert (tmp_path / "surface-map.json").is_file()
        assert (tmp_path / "surface-map.diff").is_file()

    def test_existing_only_policy_consumes_existing_artifact_without_refresh(self, tmp_path):
        out_path = tmp_path / "context.json"
        surface_path = tmp_path / "surface-map.json"
        surface_path.write_text(json.dumps(_surface_payload(path="src/existing.py")), encoding="utf-8")
        descriptor = {"mode": "worktree"}

        with (
            patch.object(
                _mod,
                "_assemble_worktree_bundle",
                return_value={
                    "schema_version": 1,
                    "mode": "worktree",
                    "followups": [],
                    "followups_note": "diff-backed target",
                    "commits": [],
                    "diff": _fake_diff("src/ignored.py"),
                    "diff_bytes": len(_fake_diff("src/ignored.py").encode("utf-8")),
                    "warnings": [],
                },
            ),
            patch.object(_mod, "_run_surface_mapper", side_effect=AssertionError("fresh mapper must not run")),
        ):
            rc = _assemble_bundle(
                descriptor,
                out_path=out_path,
                base=None,
                surface_policy="existing",
                tier="standard",
            )

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["surface_map_status"] == "existing"
        assert bundle["surface_map_path"] == str(surface_path)
        assert "src/existing.py" in bundle["surface_map_summary"]

    def test_summary_auto_consumes_existing_artifact_without_refresh(self, tmp_path):
        out_path = tmp_path / "context.json"
        surface_path = tmp_path / "surface-map.json"
        surface_path.write_text(json.dumps(_surface_payload(path="src/summary.py")), encoding="utf-8")
        descriptor = {"mode": "range", "range": "base..HEAD"}

        with (
            patch.object(
                _mod,
                "_assemble_range_bundle",
                return_value={
                    "schema_version": 1,
                    "mode": "range",
                    "followups": [],
                    "followups_note": "diff-backed target",
                    "commits": [],
                    "diff": _fake_diff("src/summary.py"),
                    "diff_bytes": len(_fake_diff("src/summary.py").encode("utf-8")),
                    "warnings": [],
                },
            ),
            patch.object(_mod, "_run_surface_mapper", side_effect=AssertionError("summary tier must not refresh")),
        ):
            rc = _assemble_bundle(
                descriptor,
                out_path=out_path,
                base=None,
                surface_policy="auto",
                tier="summary",
            )

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["surface_map_status"] == "existing"
        assert bundle["surface_map_path"] == str(surface_path)


    def test_surface_off_omits_surface_fields(self, tmp_path):
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "worktree"}

        with patch.object(
            _mod,
            "_assemble_worktree_bundle",
            return_value={
                "schema_version": 1,
                "mode": "worktree",
                "followups": [],
                "followups_note": "diff-backed target",
                "commits": [],
                "diff": _fake_diff(),
                "diff_bytes": len(_fake_diff().encode("utf-8")),
                "warnings": [],
            },
        ):
            rc = _assemble_bundle(
                descriptor,
                out_path=out_path,
                base=None,
                surface_policy="off",
                tier="standard",
            )

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert "surface_map_status" not in bundle
        assert "surface_map_path" not in bundle

    def test_mapper_failure_degrades_with_warning(self, tmp_path):
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "range", "range": "base..HEAD"}

        with (
            patch.object(
                _mod,
                "_assemble_range_bundle",
                return_value={
                    "schema_version": 1,
                    "mode": "range",
                    "followups": [],
                    "followups_note": "diff-backed target",
                    "commits": [],
                    "diff": _fake_diff("src/failure.py"),
                    "diff_bytes": len(_fake_diff("src/failure.py").encode("utf-8")),
                    "warnings": [],
                },
            ),
            patch.object(_mod, "_run_surface_mapper", return_value=(1, "", "boom")),
        ):
            rc = _assemble_bundle(
                descriptor,
                out_path=out_path,
                base=None,
                surface_policy="auto",
                tier="deep",
            )

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["surface_map_status"] == "failed"
        assert any("surface-map.py failed" in w for w in bundle["surface_map_warnings"])
        assert any("surface-map.py failed" in w for w in bundle["warnings"])

    def test_run_refresh_is_labeled_report_time_current_repo_state(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260625T000000Z-test-plan")
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "run", "run_id": run_dir.name}

        with (
            patch.object(_mod, "_resolve_run_dir", return_value=run_dir),
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
            patch.object(_mod, "_current_worktree_diff", return_value=_fake_diff("src/current.py")),
        ):
            rc = _assemble_bundle(
                descriptor,
                out_path=out_path,
                base=None,
                surface_policy="refresh",
                tier="standard",
            )

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["surface_map_status"] == "fresh"
        assert bundle["surface_map_source"] == "report_time_current_repo"
        assert "src/current.py" in bundle["surface_map_summary"]

    def test_run_existing_artifact_is_discovered_as_historical(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260625T010000Z-test-plan")
        surface_path = run_dir / "surface-map.json"
        surface_path.write_text(json.dumps(_surface_payload(path="src/historical.py")), encoding="utf-8")
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "run", "run_id": run_dir.name}

        with (
            patch.object(_mod, "_resolve_run_dir", return_value=run_dir),
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
            patch.object(_mod, "_run_surface_mapper", side_effect=AssertionError("existing historical map must not refresh")),
        ):
            rc = _assemble_bundle(
                descriptor,
                out_path=out_path,
                base=None,
                surface_policy="auto",
                tier="standard",
            )

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["surface_map_status"] == "existing"
        assert bundle["surface_map_source"] == "historical_run"
        assert bundle["surface_map_path"] == str(surface_path)

    def test_run_default_context_path_discovers_run_surface_artifact(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260625T011500Z-test-plan")
        surface_path = run_dir / "surface-map.json"
        surface_path.write_text(json.dumps(_surface_payload(path="src/default-context.py")), encoding="utf-8")
        out_path = run_dir / "context.json"
        descriptor = {"mode": "run", "run_id": run_dir.name}

        with (
            patch.object(_mod, "_resolve_run_dir", return_value=run_dir),
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
            patch.object(_mod, "_run_surface_mapper", side_effect=AssertionError("existing historical map must not refresh")),
        ):
            rc = _assemble_bundle(
                descriptor,
                out_path=out_path,
                base=None,
                surface_policy="auto",
                tier="standard",
            )

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["surface_map_status"] == "existing"
        assert bundle["surface_map_source"] == "historical_run"
        assert bundle["surface_map_path"] == str(surface_path)

    def test_run_existing_artifact_does_not_discover_sibling_archive_run(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, "20260625T020000Z-target-plan")
        sibling_dir = run_dir.parent / "20260625T030000Z-other-plan"
        sibling_dir.mkdir()
        sibling_surface = sibling_dir / "surface-map.json"
        sibling_surface.write_text(json.dumps(_surface_payload(path="src/sibling.py")), encoding="utf-8")
        out_path = tmp_path / "context.json"
        descriptor = {"mode": "run", "run_id": run_dir.name}

        with (
            patch.object(_mod, "_resolve_run_dir", return_value=run_dir),
            patch.object(_mod, "_classify_status", return_value="clean"),
            patch.object(_mod, "_resolve_followups", return_value=[]),
            patch.object(_mod, "_estimate_cost", return_value={}),
            patch.object(_mod, "_run_surface_mapper", side_effect=AssertionError("existing historical map must not refresh")),
        ):
            rc = _assemble_bundle(
                descriptor,
                out_path=out_path,
                base=None,
                surface_policy="auto",
                tier="standard",
            )

        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["surface_map_status"] == "skipped"
        assert bundle["surface_map_path"] == ""
        assert "src/sibling.py" not in bundle["surface_map_summary"]
        assert str(sibling_surface) not in bundle.get("surface_map_path", "")


class TestZReportSkillSurfacePropagation:
    def test_skill_passes_tier_and_surface_to_report_context(self):
        skill_text = (_REPO_ROOT / "skills" / "z-report" / "SKILL.md").read_text(encoding="utf-8")

        assert "--resolve-only $REPORT_CONTEXT_TARGET_ARGS \\\n  --tier \"$TIER\" \\\n  --surface \"$SURFACE_POLICY\"" in skill_text
        assert "$REPORT_CONTEXT_TARGET_ARGS \\\n  --tier \"$TIER\" \\\n  --surface \"$SURFACE_POLICY\" \\\n  --out \"$CONTEXT_PATH\"" in skill_text
        assert "must not pass `--tier`" not in skill_text
        assert "must not pass `--surface`" not in skill_text


    def test_skill_includes_report_profile_gate_and_skip_contract(self):
        skill_text = (_REPO_ROOT / "skills" / "z-report" / "SKILL.md").read_text(encoding="utf-8")

        assert "report-profile question" in skill_text
        assert "A complete explicit profile" in skill_text
        assert "Quick internal status" in skill_text
        assert "External/shareable update" in skill_text
        assert "Backtest writeup" in skill_text

    def test_skill_passes_profile_to_report_synth(self):
        skill_text = (_REPO_ROOT / "skills" / "z-report" / "SKILL.md").read_text(encoding="utf-8")

        assert "profile: <PROFILE>" in skill_text
        assert "audience: <AUDIENCE>" in skill_text
        assert "style: <STYLE>" in skill_text
        assert "purpose: <PURPOSE>" in skill_text

    def test_skill_preserves_explicit_target_flag_values_when_stripping_profile_tokens(self):
        skill_text = (_REPO_ROOT / "skills" / "z-report" / "SKILL.md").read_text(encoding="utf-8")

        assert 'target_value_flags = {"--run", "--slug", "--pr", "--range", "--base"}' in skill_text
        assert "preserve_next = True" in skill_text
        assert "out.append(tok)" in skill_text
        assert "target_seen = False" in skill_text
        assert "tok in profile_tokens and target_seen" in skill_text

    def test_skill_gates_fallback_internals_on_internal_audit_profile(self):
        skill_text = (_REPO_ROOT / "skills" / "z-report" / "SKILL.md").read_text(encoding="utf-8")

        assert 'PROFILE == "internal-audit"' in skill_text
        assert "deep internal audit evidence profile" in skill_text

    def test_report_synth_includes_profile_overlays_and_anti_bloat(self):
        agent_text = (_REPO_ROOT / "agents" / "report-synth.md").read_text(encoding="utf-8")

        assert "Profile: `technical-handoff`" in agent_text
        assert "Profile: `external-share`" in agent_text
        assert "Profile: `backtest`" in agent_text
        assert "Anti-bloat and professional self-check" in agent_text
        assert "every sentence must serve at least one of" in agent_text

class TestSurfaceAliases:
    def test_current_alias_resolves_to_worktree(self):
        desc = resolve_target(
            target="current",
            flag_run=None,
            flag_slug=None,
            flag_pr=None,
            flag_range=None,
            flag_base=None,
        )
        assert desc["mode"] == "worktree"

    def test_changes_alias_resolves_to_worktree(self):
        desc = resolve_target(
            target="changes",
            flag_run=None,
            flag_slug=None,
            flag_pr=None,
            flag_range=None,
            flag_base=None,
        )
        assert desc["mode"] == "worktree"

    def test_since_alias_cli_resolves_to_base_range(self):
        target, tier, base = _mod._parse_report_positionals(["since", "origin/main", "deep"], None)
        assert target is None
        assert tier == "deep"
        assert base == "origin/main"

    def test_current_standard_auto_cli_attaches_fresh_diff_surface(self, tmp_path):
        out_path = tmp_path / "context.json"
        diff_text = _fake_diff("src/current_alias.py")
        with patch.object(
            _mod,
            "_assemble_worktree_bundle",
            return_value={
                "schema_version": 1,
                "mode": "worktree",
                "followups": [],
                "followups_note": "diff-backed target",
                "commits": [],
                "diff": diff_text,
                "diff_bytes": len(diff_text.encode("utf-8")),
                "warnings": [],
            },
        ):
            rc = main(["current", "standard", "--surface=auto", "--out", str(out_path)])
        assert rc == 0
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["mode"] == "worktree"
        assert bundle["surface_map_status"] == "fresh"
        assert bundle["surface_map_source"] == "diff_context"
        assert "src/current_alias.py" in bundle["surface_map_summary"]

    def test_since_alias_surface_off_cli_uses_range_without_mapper(self, tmp_path):
        out_path = tmp_path / "context.json"
        diff_text = _fake_diff("src/since_alias.py")
        captured_descriptors = []
        def _fake_range_bundle(descriptor, warnings):
            captured_descriptors.append(dict(descriptor))
            return {
                "schema_version": 1,
                "mode": "range",
                "followups": [],
                "followups_note": "diff-backed target",
                "commits": [],
                "diff": diff_text,
                "diff_bytes": len(diff_text.encode("utf-8")),
                "warnings": [],
            }
        with (
            patch.object(_mod, "_assemble_range_bundle", side_effect=_fake_range_bundle),
            patch.object(_mod, "_run_surface_mapper", side_effect=AssertionError("surface=off must not run mapper")),
        ):
            rc = main(["since", "origin/main", "standard", "--surface=off", "--out", str(out_path)])
        assert rc == 0
        assert captured_descriptors == [{"mode": "range", "base": "origin/main"}]
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["mode"] == "range"
        assert "surface_map_status" not in bundle
        assert "surface_map_path" not in bundle

    def test_current_summary_surface_off_cli_passes_policy_and_tier(self, tmp_path):
        out_path = tmp_path / "context.json"
        with (
            patch.object(_mod, "resolve_target", return_value={"mode": "worktree"}) as resolve,
            patch.object(_mod, "assemble_bundle", return_value=0) as assemble,
        ):
            rc = main(["current", "summary", "--surface=off", "--out", str(out_path)])

        assert rc == 0
        resolve.assert_called_once()
        assert resolve.call_args.kwargs["target"] == "current"
        assert assemble.call_args.kwargs["out_path"] == out_path
        assert assemble.call_args.kwargs["surface_policy"] == "off"
        assert assemble.call_args.kwargs["tier"] == "summary"

    def test_save_alias_writes_context_bundle(self, tmp_path):
        out_path = tmp_path / "saved-context.json"
        with patch.object(_mod, "_run_cmd_capture", return_value=(0, "", "")):
            rc = main(["current", "--surface=off", "--save", str(out_path)])
        assert rc == 0
        assert out_path.is_file()
        bundle = json.loads(out_path.read_text(encoding="utf-8"))
        assert bundle["mode"] == "worktree"
        assert "surface_map_status" not in bundle
