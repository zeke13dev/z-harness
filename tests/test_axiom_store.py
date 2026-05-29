"""
Tests for scripts/axiom-store.py

Cases covered:
  path_global              — path --scope global resolves XDG_CONFIG_HOME-based dir
  path_project             — path --scope project resolves <repo-root>/.z-harness/axioms
  add_valid_candidate      — add writes candidate + assigns id
  add_duplicate_detection  — add returns STATUS: duplicate on same-id re-add
  add_missing_evidence     — add rejects a record with no evidence (exit 1)
  list_merge_shadow        — list merges global+project; project shadows global on same id
  list_status_filter       — list --status filters correctly
  list_discipline_filter   — list --discipline filters correctly
  get_found                — get returns the record when found
  get_not_found            — get returns STATUS: not_found when absent (exit 1)
  validate_rejects_no_evidence  — validate exits non-zero for missing evidence
  validate_obs_axiom_warn  — observation_not_axiom WARN fires to stderr when no boundaries

HERMETICITY: all tests set XDG_CONFIG_HOME and pass --repo-root to temp dirs;
they never touch the real ~/.config/z-harness or the repo's .z-harness/.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "axiom-store.py")


# ---------------------------------------------------------------------------
# Module-level import for unit tests
# ---------------------------------------------------------------------------

def _load_module():
    spec = importlib.util.spec_from_file_location("axiom_store", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_id(statement: str, scope: str = "global") -> str:
    """Compute ax-<sha256(statement+scope)[:8]> at fixture build time."""
    import hashlib
    digest = hashlib.sha256((statement + scope).encode("utf-8")).hexdigest()
    return f"ax-{digest[:8]}"


_VALID_STATEMENT = "Prefer explicit subcommands over flag-routed modes."
_VALID_RECORD = {
    "id": _make_id(_VALID_STATEMENT, "global"),
    "statement": _VALID_STATEMENT,
    "scope": "global",
    "status": "candidate",
    "confidence": 0.85,
    "evidence": [
        {"run": "20260529T120000-test", "event_id": "e-0001", "kind": "user_choice"}
    ],
    "source_run": "20260529T120000-test",
    "created_at": "2026-05-29T12:00:00Z",
    "boundary_conditions": ["does not apply to one-off internal helper flags"],
    "counterexamples": ["--dry-run is a modifier flag, not a mode"],
}

_VALID_NO_BOUNDARIES_STATEMENT = "Always review before approving."
_VALID_RECORD_NO_BOUNDARIES = {
    "id": _make_id(_VALID_NO_BOUNDARIES_STATEMENT, "global"),
    "statement": _VALID_NO_BOUNDARIES_STATEMENT,
    "scope": "global",
    "status": "candidate",
    "confidence": 0.75,
    "evidence": [
        {"run": "20260529T130000-test", "event_id": "e-0002"}
    ],
    "source_run": "20260529T130000-test",
    "created_at": "2026-05-29T13:00:00Z",
    # No boundary_conditions, no counterexamples → triggers observation_not_axiom warn
}

_INVALID_EVIDENCE_STATEMENT = "Use explicit commands always."
_INVALID_RECORD_NO_EVIDENCE = {
    "id": _make_id(_INVALID_EVIDENCE_STATEMENT, "global"),
    "statement": _INVALID_EVIDENCE_STATEMENT,
    "scope": "global",
    "status": "candidate",
    "confidence": 0.9,
    "evidence": [],   # empty — violates minItems: 1
    "source_run": "20260529T140000-test",
    "created_at": "2026-05-29T14:00:00Z",
}


def _run_script(args: list[str], env_extra: dict | None = None,
                stdin_data: str | None = None) -> subprocess.CompletedProcess:
    """Run axiom-store.py as subprocess with custom env."""
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, _SCRIPT] + args,
        env=env,
        capture_output=True,
        text=True,
        input=stdin_data,
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: path subcommand
# ---------------------------------------------------------------------------

class TestPathGlobal(unittest.TestCase):
    """path --scope global resolves to XDG_CONFIG_HOME/z-harness/axioms"""

    def test_resolves_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_CONFIG_HOME": tmp}
            result = _run_script(["path", "--scope", "global"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            expected = str(Path(tmp) / "z-harness" / "axioms")
            self.assertEqual(data["path"], expected)

    def test_resolves_default_when_xdg_absent(self):
        """Without XDG_CONFIG_HOME, falls back to ~/.config/z-harness/axioms."""
        env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        result = subprocess.run(
            [sys.executable, _SCRIPT, "path", "--scope", "global"],
            env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        expected = str(Path.home() / ".config" / "z-harness" / "axioms")
        self.assertEqual(data["path"], expected)


class TestPathProject(unittest.TestCase):
    """path --scope project resolves to <repo-root>/.z-harness/axioms"""

    def test_resolves_repo_root_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_script(
                ["path", "--scope", "project", "--repo-root", tmp]
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            expected = str(Path(tmp) / ".z-harness" / "axioms")
            self.assertEqual(data["path"], expected)

    def test_resolves_env_var(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"Z_HARNESS_PROJECT_ROOT": tmp}
            result = _run_script(
                ["path", "--scope", "project"], env_extra=env
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            expected = str(Path(tmp) / ".z-harness" / "axioms")
            self.assertEqual(data["path"], expected)


# ---------------------------------------------------------------------------
# Tests: add subcommand
# ---------------------------------------------------------------------------

class TestAddValid(unittest.TestCase):
    """add writes a valid candidate and assigns id."""

    def test_add_creates_candidate_file(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            record = {k: v for k, v in _VALID_RECORD.items() if k != "id"}  # let script assign

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tf:
                json.dump(record, tf)
                tf_path = tf.name

            try:
                result = _run_script(
                    ["add", "--scope", "global", "--from-json", tf_path],
                    env_extra=env,
                )
            finally:
                os.unlink(tf_path)

            self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")
            ax_id = data["id"]
            self.assertTrue(ax_id.startswith("ax-"), msg=f"id={ax_id!r}")
            self.assertEqual(len(ax_id), len("ax-") + 8)

            # File must exist
            candidate_file = Path(xdg) / "z-harness" / "axioms" / "candidates" / f"{ax_id}.json"
            self.assertTrue(candidate_file.exists(), msg=f"candidate file not found: {candidate_file}")

            # File must be valid JSON with the expected id
            written = json.loads(candidate_file.read_text())
            self.assertEqual(written["id"], ax_id)

    def test_add_accepts_stdin(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            record = {k: v for k, v in _VALID_RECORD.items() if k != "id"}

            result = _run_script(
                ["add", "--scope", "global", "--from-json", "-"],
                env_extra=env,
                stdin_data=json.dumps(record),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")

    def test_add_preserves_explicit_id(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            record = dict(_VALID_RECORD)
            expected_id = record["id"]  # already in fixture

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tf:
                json.dump(record, tf)
                tf_path = tf.name

            try:
                result = _run_script(
                    ["add", "--scope", "global", "--from-json", tf_path],
                    env_extra=env,
                )
            finally:
                os.unlink(tf_path)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["id"], expected_id)


class TestAddDuplicate(unittest.TestCase):
    """add returns STATUS: duplicate when same id already exists."""

    def test_duplicate_in_candidates(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            record = dict(_VALID_RECORD)
            record.pop("id", None)

            # First add
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tf:
                json.dump(record, tf)
                tf_path = tf.name

            try:
                r1 = _run_script(
                    ["add", "--scope", "global", "--from-json", tf_path],
                    env_extra=env,
                )
                self.assertEqual(r1.returncode, 0)

                # Second add (same record = same id)
                r2 = _run_script(
                    ["add", "--scope", "global", "--from-json", tf_path],
                    env_extra=env,
                )
            finally:
                os.unlink(tf_path)

            data2 = json.loads(r2.stdout)
            self.assertEqual(data2["status"], "duplicate")

    def test_duplicate_in_approved(self):
        """If id exists in approved/, adding again → duplicate."""
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            record = dict(_VALID_RECORD)
            ax_id = record["id"]  # already in fixture

            # Pre-plant a record in approved/
            approved_dir = Path(xdg) / "z-harness" / "axioms" / "approved"
            approved_dir.mkdir(parents=True)
            _write_json(approved_dir / f"{ax_id}.json", {**record, "status": "approved"})

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tf:
                json.dump(record, tf)
                tf_path = tf.name

            try:
                result = _run_script(
                    ["add", "--scope", "global", "--from-json", tf_path],
                    env_extra=env,
                )
            finally:
                os.unlink(tf_path)

            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "duplicate")


class TestAddInvalid(unittest.TestCase):
    """add rejects records that fail validation."""

    def test_missing_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            record = dict(_INVALID_RECORD_NO_EVIDENCE)

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tf:
                json.dump(record, tf)
                tf_path = tf.name

            try:
                result = _run_script(
                    ["add", "--scope", "global", "--from-json", tf_path],
                    env_extra=env,
                )
            finally:
                os.unlink(tf_path)

            self.assertNotEqual(result.returncode, 0,
                                msg="add must fail for invalid evidence")
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "invalid")
            self.assertTrue(any("evidence" in e for e in data["errors"]),
                            msg=f"expected 'evidence' error; got: {data['errors']}")


# ---------------------------------------------------------------------------
# Tests: list subcommand
# ---------------------------------------------------------------------------

class TestListMergeAndShadow(unittest.TestCase):
    """list merges global+project; project shadows global on same id."""

    def _setup_stores(self, xdg: str, repo: str) -> tuple[str, str, str]:
        """
        Plant:
          - global:  ax-00000001 (statement: 'Global statement one.')
          - global:  ax-00000002 (statement: 'Global statement two.')
          - project: ax-00000001 (statement: 'Project overrides global.')  ← shadows global
          - project: ax-00000003 (statement: 'Project only statement.')

        Returns (id1, id2, id3)
        """
        def _make_rec(ax_id, statement, scope, status="candidate", discipline=None):
            r = {
                "id": ax_id,
                "statement": statement,
                "scope": scope,
                "status": status,
                "confidence": 0.8,
                "evidence": [{"run": "r1", "event_id": "e1"}],
                "source_run": "r1",
                "created_at": "2026-05-29T00:00:00Z",
            }
            if discipline:
                r["discipline"] = discipline
            return r

        # Global store
        g_cands = Path(xdg) / "z-harness" / "axioms" / "candidates"
        g_cands.mkdir(parents=True)
        _write_json(g_cands / "ax-00000001.json",
                    _make_rec("ax-00000001", "Global statement one.", "global"))
        _write_json(g_cands / "ax-00000002.json",
                    _make_rec("ax-00000002", "Global statement two.", "global",
                              discipline="engineering"))

        # Project store
        p_cands = Path(repo) / ".z-harness" / "axioms" / "candidates"
        p_cands.mkdir(parents=True)
        _write_json(p_cands / "ax-00000001.json",
                    _make_rec("ax-00000001", "Project overrides global.", "project"))
        _write_json(p_cands / "ax-00000003.json",
                    _make_rec("ax-00000003", "Project only statement.", "project"))

        return "ax-00000001", "ax-00000002", "ax-00000003"

    def test_list_merged_contains_all_three_unique_ids(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            id1, id2, id3 = self._setup_stores(xdg, repo)

            result = _run_script(["list", "--repo-root", repo], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            records = json.loads(result.stdout)
            ids = {r["id"] for r in records}
            self.assertEqual(ids, {id1, id2, id3},
                             msg=f"Expected all 3 unique ids; got {ids}")

    def test_project_shadows_global(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            id1, _id2, _id3 = self._setup_stores(xdg, repo)

            result = _run_script(["list", "--repo-root", repo], env_extra=env)
            records = json.loads(result.stdout)
            matching = [r for r in records if r["id"] == id1]
            self.assertEqual(len(matching), 1)
            # The project record must win (statement = 'Project overrides global.')
            self.assertEqual(matching[0]["statement"], "Project overrides global.",
                             msg="Project record must shadow global record on same id")

    def test_list_status_filter(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            # Plant one candidate and one approved in global
            g_cands = Path(xdg) / "z-harness" / "axioms" / "candidates"
            g_approved = Path(xdg) / "z-harness" / "axioms" / "approved"
            g_cands.mkdir(parents=True)
            g_approved.mkdir(parents=True)

            def _rec(ax_id, status):
                return {
                    "id": ax_id,
                    "statement": f"Statement for {ax_id}.",
                    "scope": "global",
                    "status": status,
                    "confidence": 0.8,
                    "evidence": [{"run": "r", "event_id": "e"}],
                    "source_run": "r",
                    "created_at": "2026-05-29T00:00:00Z",
                }

            _write_json(g_cands / "ax-aaaaaa01.json", _rec("ax-aaaaaa01", "candidate"))
            _write_json(g_approved / "ax-bbbbbb02.json", _rec("ax-bbbbbb02", "approved"))

            # Filter by candidate
            r_cand = _run_script(
                ["list", "--scope", "global", "--status", "candidate"],
                env_extra=env,
            )
            self.assertEqual(r_cand.returncode, 0)
            records = json.loads(r_cand.stdout)
            self.assertTrue(all(r["status"] == "candidate" for r in records))
            self.assertTrue(any(r["id"] == "ax-aaaaaa01" for r in records))
            self.assertFalse(any(r["id"] == "ax-bbbbbb02" for r in records))

    def test_list_discipline_filter(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            g_cands = Path(xdg) / "z-harness" / "axioms" / "candidates"
            g_cands.mkdir(parents=True)

            _write_json(g_cands / "ax-cc000001.json", {
                "id": "ax-cc000001",
                "statement": "Engineering axiom here.",
                "scope": "global",
                "status": "candidate",
                "confidence": 0.8,
                "discipline": "engineering",
                "evidence": [{"run": "r", "event_id": "e"}],
                "source_run": "r",
                "created_at": "2026-05-29T00:00:00Z",
            })
            _write_json(g_cands / "ax-dd000002.json", {
                "id": "ax-dd000002",
                "statement": "Process axiom here.",
                "scope": "global",
                "status": "candidate",
                "confidence": 0.7,
                "discipline": "process",
                "evidence": [{"run": "r", "event_id": "e"}],
                "source_run": "r",
                "created_at": "2026-05-29T00:00:00Z",
            })

            result = _run_script(
                ["list", "--scope", "global", "--discipline", "engineering"],
                env_extra=env,
            )
            records = json.loads(result.stdout)
            self.assertTrue(all(r.get("discipline") == "engineering" for r in records))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["id"], "ax-cc000001")


# ---------------------------------------------------------------------------
# Tests: get subcommand
# ---------------------------------------------------------------------------

class TestGetRecord(unittest.TestCase):
    """get returns the record when found, STATUS: not_found when absent."""

    def _plant_global(self, xdg: str, ax_id: str, statement: str) -> Path:
        g_cands = Path(xdg) / "z-harness" / "axioms" / "candidates"
        g_cands.mkdir(parents=True)
        rec = {
            "id": ax_id,
            "statement": statement,
            "scope": "global",
            "status": "candidate",
            "confidence": 0.9,
            "evidence": [{"run": "r", "event_id": "e"}],
            "source_run": "r",
            "created_at": "2026-05-29T00:00:00Z",
        }
        p = g_cands / f"{ax_id}.json"
        _write_json(p, rec)
        return p

    def test_get_found(self):
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-1a2b3c4d"
            self._plant_global(xdg, ax_id, "Prefer explicit commands.")

            result = _run_script(
                ["get", ax_id, "--scope", "global"],
                env_extra=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            rec = json.loads(result.stdout)
            self.assertEqual(rec["id"], ax_id)
            self.assertEqual(rec["statement"], "Prefer explicit commands.")

    def test_get_not_found(self):
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            result = _run_script(
                ["get", "ax-ffffffff", "--scope", "global"],
                env_extra=env,
            )
            self.assertNotEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "not_found")
            self.assertEqual(data["id"], "ax-ffffffff")

    def test_get_project_scope(self):
        with tempfile.TemporaryDirectory() as repo:
            ax_id = "ax-abcd1234"
            p_cands = Path(repo) / ".z-harness" / "axioms" / "candidates"
            p_cands.mkdir(parents=True)
            _write_json(p_cands / f"{ax_id}.json", {
                "id": ax_id,
                "statement": "Project scoped axiom.",
                "scope": "project",
                "status": "candidate",
                "confidence": 0.8,
                "evidence": [{"run": "r", "event_id": "e"}],
                "source_run": "r",
                "created_at": "2026-05-29T00:00:00Z",
            })

            result = _run_script(
                ["get", ax_id, "--scope", "project", "--repo-root", repo],
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            rec = json.loads(result.stdout)
            self.assertEqual(rec["id"], ax_id)


# ---------------------------------------------------------------------------
# Tests: validate subcommand
# ---------------------------------------------------------------------------

class TestValidate(unittest.TestCase):
    """validate enforces single-record SPEC rules."""

    def test_valid_record_passes(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            json.dump(_VALID_RECORD, tf)
            tf_path = tf.name

        try:
            result = _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])

    def test_missing_evidence_rejected(self):
        record = dict(_INVALID_RECORD_NO_EVIDENCE)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            json.dump(record, tf)
            tf_path = tf.name

        try:
            result = _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

        self.assertNotEqual(result.returncode, 0,
                            msg="validate must exit non-zero for missing evidence")
        data = json.loads(result.stdout)
        self.assertFalse(data["ok"])
        self.assertTrue(any("evidence" in e for e in data["errors"]),
                        msg=f"Expected 'evidence' error; got {data['errors']}")

    def test_missing_required_field_rejected(self):
        """A record missing 'statement' must fail validation."""
        record = {k: v for k, v in _VALID_RECORD.items() if k != "statement"}

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            json.dump(record, tf)
            tf_path = tf.name

        try:
            result = _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

        data = json.loads(result.stdout)
        self.assertFalse(data["ok"])
        self.assertTrue(any("statement" in e for e in data["errors"]))

    def test_confidence_out_of_range_rejected(self):
        record = {**_VALID_RECORD, "confidence": 1.5}

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            json.dump(record, tf)
            tf_path = tf.name

        try:
            result = _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

        data = json.loads(result.stdout)
        self.assertFalse(data["ok"])
        self.assertTrue(any("confidence" in e for e in data["errors"]))

    def test_question_statement_rejected(self):
        """Statement that is a question must fail the imperative voice check."""
        record = {**_VALID_RECORD, "statement": "Should we prefer subcommands over flags?"}

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            json.dump(record, tf)
            tf_path = tf.name

        try:
            result = _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

        data = json.loads(result.stdout)
        self.assertFalse(data["ok"])

    def test_evidence_missing_event_id_and_quote_rejected(self):
        """Evidence item with only 'run' (no event_id or quote) must fail."""
        record = {
            **_VALID_RECORD,
            "evidence": [{"run": "20260529T000000-test"}],  # no event_id or quote
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            json.dump(record, tf)
            tf_path = tf.name

        try:
            result = _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

        data = json.loads(result.stdout)
        self.assertFalse(data["ok"])
        self.assertTrue(any("event_id" in e or "quote" in e for e in data["errors"]))


class TestSentenceBreakHeuristic(unittest.TestCase):
    """Sentence-break heuristic: abbreviations must not trigger false rejection."""

    def _run_validate(self, statement: str) -> subprocess.CompletedProcess:
        record = {
            **_VALID_RECORD,
            "statement": statement,
            "id": _make_id(statement, "global"),
        }
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            json.dump(record, tf)
            tf_path = tf.name
        try:
            return _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

    def test_abbreviation_etc_does_not_trigger_false_rejection(self):
        """A statement with 'etc. Capital' mid-sentence must PASS validation."""
        result = self._run_validate("Prefer ripgrep, rg, etc. Install it via brew.")
        # This should NOT be rejected as multi-sentence — abbreviation, not a sentence break.
        data = json.loads(result.stdout)
        self.assertFalse(
            any("single sentence" in e for e in data["errors"]),
            msg=f"'etc.' mid-sentence falsely rejected as multi-sentence: {data['errors']}",
        )

    def test_genuine_two_sentences_still_rejected(self):
        """A genuine two-sentence statement must still FAIL the sentence-break check."""
        result = self._run_validate("Prefer X. Avoid Y.")
        data = json.loads(result.stdout)
        self.assertTrue(
            any("single sentence" in e for e in data["errors"]),
            msg="Genuine two-sentence statement was not rejected as expected",
        )


class TestObservationAxiomWarn(unittest.TestCase):
    """WARN: observation_not_axiom fires to stderr when no boundaries or counterexamples."""

    def test_warn_fires_on_stderr(self):
        record = dict(_VALID_RECORD_NO_BOUNDARIES)
        # id is already in the fixture

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            json.dump(record, tf)
            tf_path = tf.name

        try:
            result = _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

        # Validate should still succeed (warn is non-blocking)
        self.assertEqual(result.returncode, 0,
                         msg=f"validate must pass (warn is non-blocking); stderr={result.stderr}")
        self.assertIn("observation_not_axiom", result.stderr,
                      msg="WARN: observation_not_axiom must appear on stderr")

    def test_warn_not_fired_when_boundary_conditions_present(self):
        record = dict(_VALID_RECORD)  # has boundary_conditions and id

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            json.dump(record, tf)
            tf_path = tf.name

        try:
            result = _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

        self.assertNotIn("observation_not_axiom", result.stderr,
                         msg="WARN must NOT fire when boundary_conditions is non-empty")

    def test_warn_in_warns_field_of_output(self):
        """The warns array in JSON output must include observation_not_axiom."""
        record = dict(_VALID_RECORD_NO_BOUNDARIES)
        # id is already in the fixture

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tf:
            json.dump(record, tf)
            tf_path = tf.name

        try:
            result = _run_script(["validate", "--from-json", tf_path])
        finally:
            os.unlink(tf_path)

        data = json.loads(result.stdout)
        self.assertIn("observation_not_axiom", data["warns"])


# ---------------------------------------------------------------------------
# Tests: id derivation
# ---------------------------------------------------------------------------

class TestIdDerivation(unittest.TestCase):
    """_derive_id produces stable ax-<8hex> identifiers."""

    def test_id_format(self):
        ax_id = _mod._derive_id("Prefer explicit subcommands.", "global")
        self.assertTrue(ax_id.startswith("ax-"))
        hex_part = ax_id[len("ax-"):]
        self.assertEqual(len(hex_part), 8)
        int(hex_part, 16)  # must not raise

    def test_id_stable(self):
        id1 = _mod._derive_id("Same statement.", "global")
        id2 = _mod._derive_id("Same statement.", "global")
        self.assertEqual(id1, id2)

    def test_id_scope_differentiates(self):
        id_global = _mod._derive_id("Same statement.", "global")
        id_project = _mod._derive_id("Same statement.", "project")
        self.assertNotEqual(id_global, id_project)


# ---------------------------------------------------------------------------
# Tests: atomic write hermeticity
# ---------------------------------------------------------------------------

class TestHermeticity(unittest.TestCase):
    """Tests must never touch real ~/.config/z-harness or real .z-harness/."""

    def test_global_store_uses_xdg(self):
        """Global store writes go to the temp XDG dir, not real ~/.config."""
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            record = dict(_VALID_RECORD)
            record.pop("id", None)

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tf:
                json.dump(record, tf)
                tf_path = tf.name

            try:
                result = _run_script(
                    ["add", "--scope", "global", "--from-json", tf_path],
                    env_extra=env,
                )
            finally:
                os.unlink(tf_path)

            self.assertEqual(result.returncode, 0)
            # Must have written to our temp xdg, NOT the real ~/.config
            real_home_config = Path.home() / ".config" / "z-harness" / "axioms"
            # The path in the result must be under xdg, not home
            data = json.loads(result.stdout)
            self.assertTrue(
                data["path"].startswith(xdg),
                msg=f"path {data['path']!r} must be under temp xdg {xdg!r}",
            )

    def test_project_store_uses_repo_root_flag(self):
        """Project store writes go to the --repo-root temp dir, not the real worktree."""
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg}
            record = {**_VALID_RECORD, "scope": "project"}
            record.pop("id", None)

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tf:
                json.dump(record, tf)
                tf_path = tf.name

            try:
                result = _run_script(
                    ["add", "--scope", "project", "--from-json", tf_path,
                     "--repo-root", repo],
                    env_extra=env,
                )
            finally:
                os.unlink(tf_path)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(
                data["path"].startswith(repo),
                msg=f"path {data['path']!r} must be under temp repo {repo!r}",
            )
            # Real worktree must be untouched
            real_worktree = Path(_REPO_ROOT) / ".z-harness" / "axioms"
            self.assertFalse(
                real_worktree.exists() and
                any((real_worktree / "candidates").glob("*.json")),
                msg="Real worktree .z-harness/axioms/candidates must not be written to",
            )


# ---------------------------------------------------------------------------
# Helpers for graph tests
# ---------------------------------------------------------------------------

def _make_approved_rec(ax_id: str, statement: str, scope: str = "global",
                       conflicts_with: list | None = None,
                       supersedes: str | None = None) -> dict:
    r: dict = {
        "id": ax_id,
        "statement": statement,
        "scope": scope,
        "status": "approved",
        "confidence": 0.8,
        "evidence": [{"run": "r1", "event_id": "e1"}],
        "source_run": "r1",
        "created_at": "2026-05-29T00:00:00Z",
        "boundary_conditions": ["applies to normal cases"],
    }
    if conflicts_with is not None:
        r["conflicts_with"] = conflicts_with
    if supersedes is not None:
        r["supersedes"] = supersedes
    return r


def _plant_approved(store_dir: Path, record: dict) -> Path:
    """Write a record into <store_dir>/approved/<id>.json."""
    p = store_dir / "approved" / f"{record['id']}.json"
    _write_json(p, record)
    return p


def _make_rejected_rec(ax_id: str, statement: str) -> dict:
    r = _make_approved_rec(ax_id, statement)
    r["status"] = "rejected"
    return r


def _plant_rejected(store_dir: Path, record: dict) -> Path:
    p = store_dir / "rejected" / f"{record['id']}.json"
    _write_json(p, record)
    return p


# ---------------------------------------------------------------------------
# Tests: validate_graph (module-level function, importable)
# ---------------------------------------------------------------------------

class TestValidateGraphDanglingSupersede(unittest.TestCase):
    """validate_graph catches a dangling supersedes target."""

    def test_dangling_supersede_is_error(self):
        records = [
            _make_approved_rec("ax-11111111", "Prefer X.", supersedes="ax-99999999"),
        ]
        result = _mod.validate_graph(records)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("supersedes" in e and "ax-99999999" in e for e in result["errors"]),
            msg=f"expected dangling supersedes error; got {result['errors']}",
        )

    def test_valid_supersede_passes(self):
        """A supersede that references an existing (demoted/rejected) record passes."""
        records = [
            _make_approved_rec("ax-11111111", "Prefer X."),
            _make_approved_rec("ax-22222222", "Prefer Y.", supersedes="ax-11111111"),
        ]
        # Both exist in record set — referential integrity is satisfied
        result = _mod.validate_graph(records)
        # No dangling-target error (there may be a mutual-conflict error if also
        # conflicts_with, but supersedes alone is fine)
        dangling_errors = [e for e in result["errors"] if "does not exist" in e]
        self.assertEqual(dangling_errors, [],
                         msg=f"unexpected dangling errors: {dangling_errors}")


class TestValidateGraphDanglingConflictsWith(unittest.TestCase):
    """validate_graph catches a dangling conflicts_with target."""

    def test_dangling_conflicts_with_is_error(self):
        records = [
            _make_approved_rec("ax-aaaaaaaa", "Prefer X.", conflicts_with=["ax-bbbbbbbb"]),
        ]
        result = _mod.validate_graph(records)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("conflicts_with" in e and "ax-bbbbbbbb" in e for e in result["errors"]),
            msg=f"expected dangling conflicts_with error; got {result['errors']}",
        )


class TestValidateGraphCycle(unittest.TestCase):
    """validate_graph catches cycles in the supersedes graph."""

    def test_direct_cycle_caught(self):
        """A -> B -> A cycle must produce a cycle error."""
        # A supersedes B and B supersedes A
        rec_a = _make_approved_rec("ax-aaaaaaaa", "Prefer X.", supersedes="ax-bbbbbbbb")
        rec_b = _make_approved_rec("ax-bbbbbbbb", "Prefer Y.", supersedes="ax-aaaaaaaa")
        result = _mod.validate_graph([rec_a, rec_b])
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("cycle" in e.lower() for e in result["errors"]),
            msg=f"expected cycle error; got {result['errors']}",
        )

    def test_three_node_cycle_caught(self):
        """A -> B -> C -> A cycle must be caught."""
        rec_a = _make_approved_rec("ax-aaaaaaaa", "Prefer X.", supersedes="ax-bbbbbbbb")
        rec_b = _make_approved_rec("ax-bbbbbbbb", "Prefer Y.", supersedes="ax-cccccccc")
        rec_c = _make_approved_rec("ax-cccccccc", "Prefer Z.", supersedes="ax-aaaaaaaa")
        result = _mod.validate_graph([rec_a, rec_b, rec_c])
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("cycle" in e.lower() for e in result["errors"]),
            msg=f"expected cycle error in 3-node chain; got {result['errors']}",
        )


class TestValidateGraphMutualConflict(unittest.TestCase):
    """validate_graph catches mutual conflicts between two approved records."""

    def test_mutual_conflict_both_approved_is_error(self):
        """Two approved records that list each other in conflicts_with → error."""
        rec_a = _make_approved_rec("ax-aaaaaaaa", "Prefer X.", conflicts_with=["ax-bbbbbbbb"])
        rec_b = _make_approved_rec("ax-bbbbbbbb", "Prefer Y.", conflicts_with=["ax-aaaaaaaa"])
        result = _mod.validate_graph([rec_a, rec_b])
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("mutual conflict" in e.lower() or "conflict" in e.lower() for e in result["errors"]),
            msg=f"expected mutual conflict error; got {result['errors']}",
        )

    def test_one_sided_conflict_with_approved_pair_is_error(self):
        """A lists B in conflicts_with; B is approved → error (A approved too)."""
        rec_a = _make_approved_rec("ax-aaaaaaaa", "Prefer X.", conflicts_with=["ax-bbbbbbbb"])
        rec_b = _make_approved_rec("ax-bbbbbbbb", "Prefer Y.")  # doesn't list A
        result = _mod.validate_graph([rec_a, rec_b])
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("conflict" in e.lower() for e in result["errors"]),
            msg=f"expected conflict error (one-sided); got {result['errors']}",
        )

    def test_conflict_with_non_approved_is_ok(self):
        """Conflict with a candidate (not approved) record does not trigger error."""
        rec_a = _make_approved_rec("ax-aaaaaaaa", "Prefer X.", conflicts_with=["ax-bbbbbbbb"])
        rec_b = _make_approved_rec("ax-bbbbbbbb", "Prefer Y.")
        rec_b["status"] = "candidate"  # not approved → no mutual conflict
        result = _mod.validate_graph([rec_a, rec_b])
        conflict_errors = [e for e in result["errors"] if "conflict" in e.lower()]
        self.assertEqual(conflict_errors, [],
                         msg=f"unexpected conflict errors: {conflict_errors}")


class TestValidateGraphLegalSupersede(unittest.TestCase):
    """A legal supersede (A supersedes B, B is demoted) passes graph validation."""

    def test_legal_supersede_passes(self):
        """A supersedes B; B is rejected (demoted) → should not produce errors."""
        rec_a = _make_approved_rec("ax-aaaaaaaa", "Prefer X.", supersedes="ax-bbbbbbbb")
        rec_b = _make_rejected_rec("ax-bbbbbbbb", "Prefer Y.")
        result = _mod.validate_graph([rec_a, rec_b])
        # No dangling errors (both exist); no mutual conflict (B is rejected)
        self.assertTrue(
            result["ok"],
            msg=f"legal supersede should pass; got errors: {result['errors']}",
        )

    def test_legal_supersede_with_acyclic_chain_passes(self):
        """A supersedes B, B supersedes C — all in record set, acyclic → pass."""
        rec_a = _make_approved_rec("ax-aaaaaaaa", "Prefer X.", supersedes="ax-bbbbbbbb")
        rec_b = _make_rejected_rec("ax-bbbbbbbb", "Prefer Y.")
        rec_b["supersedes"] = "ax-cccccccc"
        rec_c = _make_rejected_rec("ax-cccccccc", "Prefer Z.")
        result = _mod.validate_graph([rec_a, rec_b, rec_c])
        self.assertTrue(
            result["ok"],
            msg=f"legal acyclic supersede chain should pass; errors: {result['errors']}",
        )


# ---------------------------------------------------------------------------
# Tests: validate_graph Check 2b — approved supersedes approved (Finding 1)
# ---------------------------------------------------------------------------

class TestValidateGraphSupersedesApprovedTarget(unittest.TestCase):
    """Check 2b: approved A supersedes approved B → error; B rejected → no error."""

    def test_approved_supersedes_approved_is_error(self):
        """A approved with supersedes=B, B approved → validate_graph ok=False."""
        rec_a = _make_approved_rec("ax-11110001", "Prefer X.", supersedes="ax-22220001")
        rec_b = _make_approved_rec("ax-22220001", "Prefer Y.")
        result = _mod.validate_graph([rec_a, rec_b])
        self.assertFalse(result["ok"],
                         msg="both approved with supersedes must fail graph validation")
        self.assertTrue(
            any("supersedes" in e and "ax-22220001" in e and "approved" in e
                for e in result["errors"]),
            msg=f"expected Check 2b error; got: {result['errors']}",
        )

    def test_approved_supersedes_rejected_is_ok(self):
        """A approved with supersedes=B, B rejected (demoted) → validate_graph ok=True."""
        rec_a = _make_approved_rec("ax-11110002", "Prefer X.", supersedes="ax-22220002")
        rec_b = _make_rejected_rec("ax-22220002", "Prefer Y.")
        result = _mod.validate_graph([rec_a, rec_b])
        check2b_errors = [
            e for e in result["errors"]
            if "supersedes" in e and "ax-22220002" in e and "approved" in e
        ]
        self.assertEqual(check2b_errors, [],
                         msg=f"legal supersede (B rejected) must not trigger Check 2b; "
                             f"got: {result['errors']}")
        self.assertTrue(result["ok"],
                        msg=f"legal supersede (B rejected) must pass; errors: {result['errors']}")

    def test_approve_flow_not_broken(self):
        """
        Simulates the approve flow: superseded record removed from the active set entirely.
        After removal B is not in records → Check 2b does not fire (B not in approved_ids).
        """
        # Only A is in the prospective set (B was removed before validation, per approve algorithm)
        rec_a = _make_approved_rec("ax-11110003", "Prefer X.", supersedes="ax-22220003")
        # B is NOT passed in — approve removes it before calling validate_graph.
        # This produces a dangling-supersedes error (Check 1), which is expected;
        # but Check 2b must NOT fire (B is absent from approved_ids).
        result = _mod.validate_graph([rec_a])
        check2b_errors = [
            e for e in result["errors"]
            if "supersedes" in e and "ax-22220003" in e and "approved" in e
        ]
        self.assertEqual(check2b_errors, [],
                         msg=f"approve-flow (B removed) must not trigger Check 2b; "
                             f"got: {result['errors']}")


# ---------------------------------------------------------------------------
# Tests: validate --all CLI subcommand
# ---------------------------------------------------------------------------

class TestValidateAllCLI(unittest.TestCase):
    """validate --all runs graph-validate over the active set via CLI."""

    def test_validate_all_ok_on_empty_store(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            result = _run_script(
                ["validate", "--all", "--repo-root", repo],
                env_extra=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["errors"], [])

    def test_validate_all_catches_dangling_supersede(self):
        with tempfile.TemporaryDirectory() as xdg, \
             tempfile.TemporaryDirectory() as repo:
            env = {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_PROJECT_ROOT": repo}
            g_approved = Path(xdg) / "z-harness" / "axioms" / "approved"
            g_approved.mkdir(parents=True)
            rec = _make_approved_rec("ax-11111111", "Prefer X.", supersedes="ax-99999999")
            _plant_approved(Path(xdg) / "z-harness" / "axioms", rec)

            result = _run_script(
                ["validate", "--all", "--scope", "global"],
                env_extra=env,
            )
            self.assertNotEqual(result.returncode, 0,
                                msg="validate --all must fail when dangling supersede exists")
            data = json.loads(result.stdout)
            self.assertFalse(data["ok"])
            self.assertTrue(
                any("ax-99999999" in e for e in data["errors"]),
                msg=f"expected dangling-supersede error; got {data['errors']}",
            )


# ---------------------------------------------------------------------------
# Tests: reject subcommand
# ---------------------------------------------------------------------------

class TestReject(unittest.TestCase):
    """reject moves a candidate or approved file to rejected/ and stamps status."""

    def _setup_candidate(self, store_dir: Path, ax_id: str) -> Path:
        rec = {
            "id": ax_id,
            "statement": "Some candidate axiom.",
            "scope": "global",
            "status": "candidate",
            "confidence": 0.7,
            "evidence": [{"run": "r", "event_id": "e"}],
            "source_run": "r",
            "created_at": "2026-05-29T00:00:00Z",
            "boundary_conditions": ["applies normally"],
        }
        cands = store_dir / "candidates"
        cands.mkdir(parents=True, exist_ok=True)
        _write_json(cands / f"{ax_id}.json", rec)
        return cands / f"{ax_id}.json"

    def test_reject_candidate_moves_file(self):
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-11223344"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            src = self._setup_candidate(store_dir, ax_id)
            self.assertTrue(src.exists())

            result = _run_script(
                ["reject", ax_id, "--scope", "global"],
                env_extra=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["id"], ax_id)

            # Source file removed
            self.assertFalse(src.exists(), msg="candidate file must be removed after reject")
            # Destination exists
            dst = store_dir / "rejected" / f"{ax_id}.json"
            self.assertTrue(dst.exists(), msg="rejected file must exist after reject")
            # Status stamped
            written = json.loads(dst.read_text())
            self.assertEqual(written["status"], "rejected")

    def test_reject_approved_moves_file(self):
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-aabbccdd"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            rec = _make_approved_rec(ax_id, "Some approved axiom.")
            _plant_approved(store_dir, rec)
            src = store_dir / "approved" / f"{ax_id}.json"
            self.assertTrue(src.exists())

            result = _run_script(
                ["reject", ax_id, "--scope", "global"],
                env_extra=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertFalse(src.exists(), msg="approved file must be removed after reject")
            dst = store_dir / "rejected" / f"{ax_id}.json"
            self.assertTrue(dst.exists())
            written = json.loads(dst.read_text())
            self.assertEqual(written["status"], "rejected")

    def test_reject_stamps_status_rejected(self):
        """The rejected file must have status: rejected (not original status)."""
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-99aabb00"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            self._setup_candidate(store_dir, ax_id)

            _run_script(["reject", ax_id, "--scope", "global"], env_extra=env)

            dst = store_dir / "rejected" / f"{ax_id}.json"
            written = json.loads(dst.read_text())
            self.assertEqual(written["status"], "rejected",
                             msg="reject must stamp status: rejected")

    def test_reject_not_found_returns_error(self):
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            result = _run_script(
                ["reject", "ax-00000000", "--scope", "global"],
                env_extra=env,
            )
            self.assertNotEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "not_found")

    def test_reject_with_reason(self):
        """--reason is stored in the rejected file."""
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-ffee1234"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            self._setup_candidate(store_dir, ax_id)

            result = _run_script(
                ["reject", ax_id, "--scope", "global", "--reason", "superseded by policy"],
                env_extra=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            dst = store_dir / "rejected" / f"{ax_id}.json"
            written = json.loads(dst.read_text())
            self.assertIn("rejected_reason", written)
            self.assertEqual(written["rejected_reason"], "superseded by policy")


# ---------------------------------------------------------------------------
# Tests: edit subcommand
# ---------------------------------------------------------------------------

class TestEdit(unittest.TestCase):
    """edit patches a record atomically."""

    def _setup_candidate(self, store_dir: Path, ax_id: str) -> Path:
        rec = {
            "id": ax_id,
            "statement": "Original candidate statement.",
            "scope": "global",
            "status": "candidate",
            "confidence": 0.7,
            "evidence": [{"run": "r", "event_id": "e"}],
            "source_run": "r",
            "created_at": "2026-05-29T00:00:00Z",
            "boundary_conditions": ["applies normally"],
        }
        cands = store_dir / "candidates"
        cands.mkdir(parents=True, exist_ok=True)
        p = cands / f"{ax_id}.json"
        _write_json(p, rec)
        return p

    def test_edit_patches_candidate_atomically(self):
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-ee112233"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            p = self._setup_candidate(store_dir, ax_id)

            result = _run_script(
                ["edit", ax_id, "--set", "confidence=0.95", "--scope", "global"],
                env_extra=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "ok")

            # Verify the file was patched
            written = json.loads(p.read_text())
            self.assertAlmostEqual(written["confidence"], 0.95)

    def test_edit_patches_string_field(self):
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-ff223344"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            p = self._setup_candidate(store_dir, ax_id)

            result = _run_script(
                ["edit", ax_id, "--set", 'discipline=engineering', "--scope", "global"],
                env_extra=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            written = json.loads(p.read_text())
            self.assertEqual(written["discipline"], "engineering")

    def test_edit_approved_graph_invalid_is_rejected(self):
        """
        Editing an approved record to introduce a dangling supersedes target
        must be rejected (graph validation fails, original file untouched).
        """
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-dd445566"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            rec = _make_approved_rec(ax_id, "Some approved axiom.")
            _plant_approved(store_dir, rec)
            p = store_dir / "approved" / f"{ax_id}.json"
            original_content = p.read_text()

            # Patch supersedes to a non-existent id
            result = _run_script(
                ["edit", ax_id,
                 "--set", "supersedes=ax-99999999",  # dangling
                 "--scope", "global"],
                env_extra=env,
            )
            self.assertNotEqual(result.returncode, 0,
                                msg="edit on approved with dangling supersede must fail")
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "graph_validation_failed")

            # Original file must be untouched
            self.assertEqual(p.read_text(), original_content,
                             msg="original file must be untouched on graph validation failure")

    def test_edit_approved_valid_graph_succeeds(self):
        """
        Editing an approved record in a way that keeps the graph valid must succeed.
        """
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-cc556677"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            rec = _make_approved_rec(ax_id, "Some approved axiom.")
            _plant_approved(store_dir, rec)
            p = store_dir / "approved" / f"{ax_id}.json"

            result = _run_script(
                ["edit", ax_id, "--set", "confidence=0.9", "--scope", "global"],
                env_extra=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            written = json.loads(p.read_text())
            self.assertAlmostEqual(written["confidence"], 0.9)

    def test_edit_not_found_returns_error(self):
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            result = _run_script(
                ["edit", "ax-00000000", "--set", "confidence=0.5", "--scope", "global"],
                env_extra=env,
            )
            self.assertNotEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "not_found")

    def test_edit_approved_would_create_cycle_is_rejected(self):
        """
        Editing an approved record to create a supersedes cycle must be rejected.
        A supersedes B (approved), B exists. Editing A to supersede itself → cycle.
        """
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id_a = "ax-11223300"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            rec_a = _make_approved_rec(ax_id_a, "Prefer X.")
            _plant_approved(store_dir, rec_a)
            p = store_dir / "approved" / f"{ax_id_a}.json"
            original_content = p.read_text()

            # Try to make A supersede itself (trivial cycle)
            result = _run_script(
                ["edit", ax_id_a,
                 "--set", f"supersedes={ax_id_a}",
                 "--scope", "global"],
                env_extra=env,
            )
            # Either a graph error (cycle) or a graph_validation_failed status
            # self-supersede forms a cycle: A -> A
            self.assertNotEqual(result.returncode, 0,
                                msg="self-supersede must be rejected")
            # Original untouched
            self.assertEqual(p.read_text(), original_content,
                             msg="original file must be untouched on failure")


# ---------------------------------------------------------------------------
# Tests: edit schema validation (Finding 2)
# ---------------------------------------------------------------------------

class TestEditSchemaValidation(unittest.TestCase):
    """edit rejects unknown/invalid fields via _validate_record before any write."""

    def _setup_candidate(self, store_dir: Path, ax_id: str) -> Path:
        rec = {
            "id": ax_id,
            "statement": "Schema validation candidate.",
            "scope": "global",
            "status": "candidate",
            "confidence": 0.7,
            "evidence": [{"run": "r", "event_id": "e"}],
            "source_run": "r",
            "created_at": "2026-05-29T00:00:00Z",
            "boundary_conditions": ["applies normally"],
        }
        cands = store_dir / "candidates"
        cands.mkdir(parents=True, exist_ok=True)
        p = cands / f"{ax_id}.json"
        _write_json(p, rec)
        return p

    def test_edit_unknown_field_rejected_and_file_untouched(self):
        """
        edit with --set nosuchfield=foo must be rejected (status: invalid),
        and the original file must be left untouched.
        """
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-ee334455"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            p = self._setup_candidate(store_dir, ax_id)
            original_content = p.read_text()

            result = _run_script(
                ["edit", ax_id, "--set", "nosuchfield=foo", "--scope", "global"],
                env_extra=env,
            )
            self.assertNotEqual(result.returncode, 0,
                                msg="edit with unknown field must fail")
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "invalid",
                             msg=f"expected status: invalid; got: {data}")
            self.assertTrue(
                any("nosuchfield" in e for e in data.get("errors", [])),
                msg=f"expected 'nosuchfield' in errors; got: {data.get('errors')}",
            )
            # Original file must be untouched
            self.assertEqual(p.read_text(), original_content,
                             msg="original file must be untouched on schema rejection")

    def test_edit_valid_confidence_patch_succeeds_with_float(self):
        """
        A valid edit (--set confidence=0.8) must succeed and confidence must be a float
        (not the string "0.8") in the written file.
        """
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-ee445566"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            p = self._setup_candidate(store_dir, ax_id)

            result = _run_script(
                ["edit", ax_id, "--set", "confidence=0.8", "--scope", "global"],
                env_extra=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            written = json.loads(p.read_text())
            self.assertIsInstance(written["confidence"], float,
                                  msg="confidence must be stored as float, not string")
            self.assertAlmostEqual(written["confidence"], 0.8)

    def test_edit_unknown_field_on_approved_record_also_rejected(self):
        """
        Schema validation applies to approved records too — unknown field via edit must fail.
        """
        with tempfile.TemporaryDirectory() as xdg:
            env = {"XDG_CONFIG_HOME": xdg}
            ax_id = "ax-ee556677"
            store_dir = Path(xdg) / "z-harness" / "axioms"
            rec = _make_approved_rec(ax_id, "Some approved axiom.")
            _plant_approved(store_dir, rec)
            p = store_dir / "approved" / f"{ax_id}.json"
            original_content = p.read_text()

            result = _run_script(
                ["edit", ax_id, "--set", "unauthorizedfield=baz", "--scope", "global"],
                env_extra=env,
            )
            self.assertNotEqual(result.returncode, 0,
                                msg="edit with unknown field on approved record must fail")
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "invalid")
            # File untouched
            self.assertEqual(p.read_text(), original_content,
                             msg="original approved file must be untouched on schema rejection")


# ---------------------------------------------------------------------------
# Tests: validate_graph importability (R1 — module-level function)
# ---------------------------------------------------------------------------

class TestValidateGraphImportable(unittest.TestCase):
    """validate_graph must be a module-level importable function (R1)."""

    def test_validate_graph_is_callable(self):
        self.assertTrue(
            callable(getattr(_mod, "validate_graph", None)),
            msg="validate_graph must be a module-level callable in axiom-store.py",
        )

    def test_validate_graph_returns_dict_with_expected_keys(self):
        result = _mod.validate_graph([])
        self.assertIn("ok", result)
        self.assertIn("errors", result)
        self.assertIn("warns", result)

    def test_validate_graph_empty_set_is_ok(self):
        result = _mod.validate_graph([])
        self.assertTrue(result["ok"])
        self.assertEqual(result["errors"], [])


# ---------------------------------------------------------------------------
# Tests: approve subcommand (T004)
#
# HERMETICITY: the guarded kernel regen (T007 does full wiring) looks for
# build-kernel.py next to axiom-store.py. To avoid depending on the real
# compiler, these tests run a COPY of axiom-store.py placed in a temp scripts/
# dir WITHOUT build-kernel.py — so the guarded regen takes the "compiler
# absent → log skip note, STATUS: approved" branch deterministically.
# ---------------------------------------------------------------------------

import shutil


def _make_candidate_rec(ax_id: str, statement: str, scope: str = "global",
                        *, with_boundaries: bool = True,
                        supersedes: str | None = None) -> dict:
    r: dict = {
        "id": ax_id,
        "statement": statement,
        "scope": scope,
        "status": "candidate",
        "confidence": 0.8,
        "evidence": [{"run": "r1", "event_id": "e1"}],
        "source_run": "r1",
        "created_at": "2026-05-29T00:00:00Z",
    }
    if with_boundaries:
        r["boundary_conditions"] = ["applies to normal cases"]
    if supersedes is not None:
        r["supersedes"] = supersedes
    return r


def _plant_candidate(store_dir: Path, record: dict) -> Path:
    p = store_dir / "candidates" / f"{record['id']}.json"
    _write_json(p, record)
    return p


class _ApproveHarness:
    """Context manager: temp scripts/ dir (no build-kernel.py) + temp XDG home."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        scripts_dir = base / "scripts"
        scripts_dir.mkdir()
        # Copy axiom-store.py (and log-event.sh if used) but NOT build-kernel.py.
        shutil.copy(_SCRIPT, scripts_dir / "axiom-store.py")
        self.script = str(scripts_dir / "axiom-store.py")
        self.xdg = base / "xdg"
        self.xdg.mkdir()
        self.store_dir = self.xdg / "z-harness" / "axioms"
        self.env = {"XDG_CONFIG_HOME": str(self.xdg)}
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False

    def run(self, args: list[str]) -> subprocess.CompletedProcess:
        env = {**os.environ, **self.env}
        return subprocess.run(
            [sys.executable, self.script] + args,
            env=env, capture_output=True, text=True,
        )


class TestApproveSuccess(unittest.TestCase):
    """Successful approve moves candidate → approved, stamps status + approved_at."""

    def test_candidate_promoted(self):
        with _ApproveHarness() as h:
            ax_id = "ax-10000001"
            _plant_candidate(h.store_dir, _make_candidate_rec(ax_id, "Prefer X."))

            result = h.run(["approve", ax_id, "--scope", "global"])
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "approved")

            approved_file = h.store_dir / "approved" / f"{ax_id}.json"
            candidate_file = h.store_dir / "candidates" / f"{ax_id}.json"
            self.assertTrue(approved_file.exists(), msg="approved file missing")
            self.assertFalse(candidate_file.exists(), msg="candidate file must be gone")

            written = json.loads(approved_file.read_text())
            self.assertEqual(written["status"], "approved")
            self.assertIn("approved_at", written)

    def test_not_found(self):
        with _ApproveHarness() as h:
            result = h.run(["approve", "ax-deadbeef", "--scope", "global"])
            self.assertNotEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "not_found")


class TestApproveGraphAbort(unittest.TestCase):
    """A candidate whose approval breaks the graph leaves everything untouched."""

    def test_dangling_supersede_aborts(self):
        with _ApproveHarness() as h:
            ax_id = "ax-20000001"
            # supersedes a non-existent record → dangling target → graph_invalid
            rec = _make_candidate_rec(ax_id, "Prefer Y.", supersedes="ax-99999999")
            _plant_candidate(h.store_dir, rec)

            result = h.run(["approve", ax_id, "--scope", "global"])
            self.assertNotEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "graph_invalid")
            self.assertTrue(data["errors"])

            # Candidate must stay; approved/ must be empty.
            self.assertTrue((h.store_dir / "candidates" / f"{ax_id}.json").exists())
            self.assertFalse((h.store_dir / "approved" / f"{ax_id}.json").exists())


class TestApproveNeedsAck(unittest.TestCase):
    """Observation-like candidate gates on --ack-observation."""

    def test_needs_ack_without_flag(self):
        with _ApproveHarness() as h:
            ax_id = "ax-30000001"
            rec = _make_candidate_rec(ax_id, "Observe Z.", with_boundaries=False)
            _plant_candidate(h.store_dir, rec)

            result = h.run(["approve", ax_id, "--scope", "global"])
            self.assertNotEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "needs_ack")
            # Not approved.
            self.assertFalse((h.store_dir / "approved" / f"{ax_id}.json").exists())
            self.assertTrue((h.store_dir / "candidates" / f"{ax_id}.json").exists())

    def test_approved_with_ack_flag(self):
        with _ApproveHarness() as h:
            ax_id = "ax-30000002"
            rec = _make_candidate_rec(ax_id, "Observe Z.", with_boundaries=False)
            _plant_candidate(h.store_dir, rec)

            result = h.run(["approve", ax_id, "--scope", "global", "--ack-observation"])
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "approved")
            self.assertTrue((h.store_dir / "approved" / f"{ax_id}.json").exists())


class TestApproveSupersedeDemotes(unittest.TestCase):
    """Approving A (supersedes B, B approved) demotes B → rejected stamped superseded_by."""

    def test_supersede_demotes_target(self):
        with _ApproveHarness() as h:
            b_id = "ax-40000001"
            a_id = "ax-40000002"
            # B already approved; B is referenced by A.supersedes.
            _plant_approved(h.store_dir, _make_approved_rec(b_id, "Old rule."))
            _plant_candidate(
                h.store_dir,
                _make_candidate_rec(a_id, "New rule.", supersedes=b_id),
            )

            result = h.run(["approve", a_id, "--scope", "global"])
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "approved")

            # A approved, B demoted to rejected with superseded_by stamp.
            self.assertTrue((h.store_dir / "approved" / f"{a_id}.json").exists())
            self.assertFalse((h.store_dir / "approved" / f"{b_id}.json").exists())
            rejected_b = h.store_dir / "rejected" / f"{b_id}.json"
            self.assertTrue(rejected_b.exists(), msg="B must move to rejected/")
            b_written = json.loads(rejected_b.read_text())
            self.assertEqual(b_written["status"], "rejected")
            self.assertEqual(b_written["superseded_by"], a_id)


class TestApproveLockContention(unittest.TestCase):
    """A held .approve.lock makes approve exit STATUS: busy and change nothing."""

    def test_busy_when_lock_held(self):
        with _ApproveHarness() as h:
            ax_id = "ax-50000001"
            _plant_candidate(h.store_dir, _make_candidate_rec(ax_id, "Prefer Q."))

            # Pre-create the lockfile (O_EXCL semantics simulated by existence).
            h.store_dir.mkdir(parents=True, exist_ok=True)
            lock_path = h.store_dir / ".approve.lock"
            lock_path.write_text("held-by-other\n")

            result = h.run(["approve", ax_id, "--scope", "global"])
            self.assertNotEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "busy")

            # Nothing changed: candidate still present, no approved record.
            self.assertTrue((h.store_dir / "candidates" / f"{ax_id}.json").exists())
            self.assertFalse((h.store_dir / "approved" / f"{ax_id}.json").exists())
            # Lock not removed (it belongs to the other holder).
            self.assertTrue(lock_path.exists())


class TestApproveProjectScopeSeesGlobalConflict(unittest.TestCase):
    """
    R1 fix: project-scope approve must validate over the merged global+project set.

    A project candidate that conflicts_with a GLOBAL approved axiom must return
    graph_invalid with a CONFLICT error — not a dangling-reference error.

    This ensures the test fails for the right reason: the merged active set (after
    FIX 1) contains the global approved axiom, so approve detects a mutual conflict
    between the project candidate (being approved) and the global approved record.
    """

    def test_project_candidate_conflicts_with_global_approved_returns_graph_invalid(self):
        with _ApproveHarness() as h:
            # The harness already provides a global store under h.xdg.
            global_store_dir = h.store_dir  # xdg/z-harness/axioms

            # Plant a global approved axiom that the project candidate will conflict with.
            global_ax_id = "ax-a0000001"
            # The global record also lists the project id in conflicts_with so that
            # validate_graph detects the mutual conflict (both approved, both listing
            # each other) — this is the correct merged-set conflict detection path,
            # not a dangling-reference path.
            proj_ax_id = "ax-b0000001"
            global_rec = _make_approved_rec(
                global_ax_id, "Global rule.", scope="global",
                conflicts_with=[proj_ax_id],
            )
            _plant_approved(global_store_dir, global_rec)

            # Plant a project candidate that explicitly conflicts_with the global axiom.
            project_root = Path(h._tmp.name) / "proj"
            project_root.mkdir()
            proj_store_dir = project_root / ".z-harness" / "axioms"
            proj_rec = _make_candidate_rec(proj_ax_id, "Project rule.", scope="project")
            proj_rec["conflicts_with"] = [global_ax_id]
            _plant_candidate(proj_store_dir, proj_rec)

            # Approve the project candidate — must fail because it conflicts with a
            # global approved axiom that the merged active set includes.
            result = h.run([
                "approve", proj_ax_id,
                "--scope", "project",
                "--repo-root", str(project_root),
            ])

            self.assertNotEqual(result.returncode, 0,
                                msg=f"stdout: {result.stdout}\nstderr: {result.stderr}")
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "graph_invalid",
                             msg=f"expected graph_invalid; got {data}")
            self.assertTrue(data["errors"],
                            msg="graph_invalid must include error details")

            # The error must mention "conflict" — not "does not exist".
            # A dangling-reference error would say "does not exist", which would mean
            # the global axiom is NOT in the merged set (FIX 1 not applied).
            # A conflict error confirms the merged set is correctly populated.
            errors_text = " ".join(data["errors"])
            self.assertIn(
                "conflict", errors_text,
                msg=(
                    f"graph_invalid errors must mention 'conflict' (merged-set detection), "
                    f"not a dangling-reference error. errors: {data['errors']}"
                ),
            )
            self.assertNotIn(
                "does not exist", errors_text,
                msg=(
                    "error must NOT say 'does not exist' — that would indicate the global "
                    "axiom is absent from the merged set (FIX 1 not applied). "
                    f"errors: {data['errors']}"
                ),
            )

            # Candidate must be left untouched; no approved record written.
            self.assertTrue(
                (proj_store_dir / "candidates" / f"{proj_ax_id}.json").exists(),
                msg="candidate must remain after graph_invalid abort",
            )
            self.assertFalse(
                (proj_store_dir / "approved" / f"{proj_ax_id}.json").exists(),
                msg="approved record must NOT be written on graph_invalid",
            )


class TestApproveLockReleasedAfterGraphInvalid(unittest.TestCase):
    """
    R4 fix: the lock must be released even when approve aborts on graph_invalid.

    After a graph-invalid approve, the .approve.lock file must not exist, so a
    subsequent approve on the same store does not return busy.
    """

    def test_lock_released_after_graph_invalid(self):
        with _ApproveHarness() as h:
            # Candidate that will fail graph validation: dangling supersedes target.
            bad_id = "ax-60000001"
            bad_rec = _make_candidate_rec(bad_id, "Prefer Y.", supersedes="ax-99999999")
            _plant_candidate(h.store_dir, bad_rec)

            # First approve — must fail with graph_invalid.
            result1 = h.run(["approve", bad_id, "--scope", "global"])
            self.assertNotEqual(result1.returncode, 0, msg=result1.stderr)
            data1 = json.loads(result1.stdout)
            self.assertEqual(data1["status"], "graph_invalid",
                             msg=f"first approve must be graph_invalid; got {data1}")

            # Lock must be gone after the aborted approve.
            lock_path = h.store_dir / ".approve.lock"
            self.assertFalse(
                lock_path.exists(),
                msg=".approve.lock must be removed after graph_invalid abort",
            )

            # A subsequent approve attempt must NOT return busy (lock is free).
            # The candidate is still in place (graph_invalid did not move it).
            result2 = h.run(["approve", bad_id, "--scope", "global"])
            self.assertNotEqual(result2.returncode, 0, msg=result2.stderr)
            data2 = json.loads(result2.stdout)
            self.assertNotEqual(
                data2.get("status"), "busy",
                msg=f"second approve must not be busy; got {data2}",
            )


class TestLoadActiveSetMergeSemantics(unittest.TestCase):
    """
    Unit tests for _load_active_set merge / scope semantics (FIX 1).

    Verifies:
      - scope="global"  → global only (project records absent)
      - scope="project" → merged global+project (global axiom is present)
      - scope="project" → project record shadows global record on same id
      - scope=None      → same as scope="project" (both stores merged)
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.xdg = base / "xdg"
        self.xdg.mkdir()
        self.global_store = self.xdg / "z-harness" / "axioms"
        self.project_root = base / "proj"
        self.project_root.mkdir()
        self.project_store = self.project_root / ".z-harness" / "axioms"

    def tearDown(self):
        self._tmp.cleanup()

    def _call_load(self, scope, repo_root=None):
        """Call _load_active_set with patched XDG_CONFIG_HOME."""
        old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(self.xdg)
        try:
            return _mod._load_active_set(scope, repo_root)
        finally:
            if old_xdg is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old_xdg

    def test_global_scope_returns_global_only(self):
        """scope='global' must NOT include project records."""
        global_rec = _make_approved_rec("ax-g0000001", "Global only.", scope="global")
        _plant_approved(self.global_store, global_rec)

        proj_rec = _make_approved_rec("ax-p0000001", "Project only.", scope="project")
        _plant_approved(self.project_store, proj_rec)

        records = self._call_load("global", str(self.project_root))
        ids = {r["id"] for r in records}
        self.assertIn("ax-g0000001", ids, msg="global record must be present")
        self.assertNotIn("ax-p0000001", ids,
                         msg="project record must NOT appear for scope='global'")

    def test_project_scope_includes_global_record(self):
        """scope='project' must include global records (merged set)."""
        global_rec = _make_approved_rec("ax-g0000002", "Global axiom.", scope="global")
        _plant_approved(self.global_store, global_rec)

        proj_rec = _make_approved_rec("ax-p0000002", "Project axiom.", scope="project")
        _plant_approved(self.project_store, proj_rec)

        records = self._call_load("project", str(self.project_root))
        ids = {r["id"] for r in records}
        self.assertIn("ax-g0000002", ids,
                      msg="global record must be present for scope='project' (FIX 1)")
        self.assertIn("ax-p0000002", ids, msg="project record must also be present")

    def test_project_scope_shadows_global_on_same_id(self):
        """scope='project': project record wins on id collision."""
        shared_id = "ax-s0000001"
        global_rec = _make_approved_rec(shared_id, "Global version.", scope="global")
        _plant_approved(self.global_store, global_rec)

        proj_rec = _make_approved_rec(shared_id, "Project version.", scope="project")
        _plant_approved(self.project_store, proj_rec)

        records = self._call_load("project", str(self.project_root))
        by_id = {r["id"]: r for r in records}
        self.assertIn(shared_id, by_id)
        self.assertEqual(by_id[shared_id]["statement"], "Project version.",
                         msg="project record must shadow global on same id")

    def test_none_scope_merges_both(self):
        """scope=None must behave like scope='project': both stores merged."""
        global_rec = _make_approved_rec("ax-g0000003", "Global X.", scope="global")
        _plant_approved(self.global_store, global_rec)

        proj_rec = _make_approved_rec("ax-p0000003", "Project X.", scope="project")
        _plant_approved(self.project_store, proj_rec)

        records = self._call_load(None, str(self.project_root))
        ids = {r["id"] for r in records}
        self.assertIn("ax-g0000003", ids)
        self.assertIn("ax-p0000003", ids)


class TestApproveWithinScopeSupersede(unittest.TestCase):
    """
    Regression guard: within-scope supersede must still work after FIX 1 and FIX 2.

    A supersedes B where both are in the SAME store → B is demoted, A is approved.
    """

    def test_within_scope_global_supersede(self):
        """Global A supersedes global B → B demoted to rejected/, A approved."""
        with _ApproveHarness() as h:
            b_id = "ax-aa000001"
            a_id = "ax-aa000002"

            # Plant B as approved (it will be superseded).
            b_rec = _make_approved_rec(b_id, "Old rule.")
            _plant_approved(h.store_dir, b_rec)

            # Plant A as candidate, supersedes B.
            a_rec = _make_candidate_rec(a_id, "New rule.", supersedes=b_id)
            _plant_candidate(h.store_dir, a_rec)

            result = h.run(["approve", a_id, "--scope", "global"])
            self.assertEqual(result.returncode, 0,
                             msg=f"within-scope supersede must succeed; stdout={result.stdout}")
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "approved")

            # A is now approved.
            self.assertTrue((h.store_dir / "approved" / f"{a_id}.json").exists(),
                            msg="A must be in approved/")
            # B must be demoted to rejected/.
            self.assertTrue((h.store_dir / "rejected" / f"{b_id}.json").exists(),
                            msg="B must be demoted to rejected/")
            self.assertFalse((h.store_dir / "approved" / f"{b_id}.json").exists(),
                             msg="B must NOT remain in approved/")

            # Verify B's rejected record has superseded_by stamped.
            b_rejected = json.loads(
                (h.store_dir / "rejected" / f"{b_id}.json").read_text()
            )
            self.assertEqual(b_rejected.get("superseded_by"), a_id)


class TestApproveCrossStoreSupersedeForbidden(unittest.TestCase):
    """
    FIX 2: cross-store supersede must return cross_store_supersede_unsupported
    and leave both the candidate and the target untouched.

    Scenario: project candidate A supersedes global approved B.
    Expected: abort with cross_store_supersede_unsupported; B still in global approved/.
    """

    def test_project_supersedes_global_is_forbidden(self):
        with _ApproveHarness() as h:
            # Plant B as a GLOBAL approved record.
            b_id = "ax-bb000001"
            b_rec = _make_approved_rec(b_id, "Global rule to supersede.")
            _plant_approved(h.store_dir, b_rec)  # h.store_dir is global

            # Plant A as a PROJECT candidate that supersedes global B.
            a_id = "ax-bb000002"
            project_root = Path(h._tmp.name) / "proj_cs"
            project_root.mkdir()
            proj_store_dir = project_root / ".z-harness" / "axioms"
            a_rec = _make_candidate_rec(a_id, "Project rule.", scope="project",
                                        supersedes=b_id)
            _plant_candidate(proj_store_dir, a_rec)

            result = h.run([
                "approve", a_id,
                "--scope", "project",
                "--repo-root", str(project_root),
            ])

            self.assertNotEqual(result.returncode, 0,
                                msg=f"cross-store supersede must fail; stdout={result.stdout}")
            data = json.loads(result.stdout)
            self.assertEqual(
                data["status"], "cross_store_supersede_unsupported",
                msg=f"expected cross_store_supersede_unsupported; got {data}",
            )
            self.assertEqual(data.get("supersedes"), b_id)
            self.assertEqual(data.get("target_scope"), "global")

            # Candidate A must be untouched (still in project candidates/).
            self.assertTrue(
                (proj_store_dir / "candidates" / f"{a_id}.json").exists(),
                msg="candidate A must remain after cross-store-supersede abort",
            )
            self.assertFalse(
                (proj_store_dir / "approved" / f"{a_id}.json").exists(),
                msg="A must NOT be written to approved/",
            )

            # B must still be in global approved/ (untouched).
            self.assertTrue(
                (h.store_dir / "approved" / f"{b_id}.json").exists(),
                msg="global B must remain approved after cross-store-supersede abort",
            )
            self.assertFalse(
                (h.store_dir / "rejected" / f"{b_id}.json").exists(),
                msg="global B must NOT be moved to rejected/",
            )


# ---------------------------------------------------------------------------
# Tests: applies_to validation (T022 — value-encoding shape enforcement)
# ---------------------------------------------------------------------------

class TestAppliesToValidation(unittest.TestCase):
    """
    _validate_record enforces the applies_to shape rules from SPEC line 78:
      - each entry is a string with exactly one ':'
      - both halves non-empty
      - <question_id> half matches ^[a-z0-9_.]+$ (lowercase alnum, underscore, dot)
        so that config.py's dotted QUESTION_IDS like workflow.slug_confirm are valid
      - at most one entry per <question_id> (duplicate question-ids → error)
    Choice-membership (whether <value> is a legal choice) is NOT checked here;
    that is the resolver's responsibility (T012).
    """

    def _base_record(self, applies_to: list | None = None) -> dict:
        """Minimal valid record; supply applies_to to exercise that path."""
        r = {
            **_VALID_RECORD,
            "id": _make_id(_VALID_STATEMENT, "global"),
        }
        if applies_to is not None:
            r["applies_to"] = applies_to
        return r

    def _validate(self, applies_to: list | None = None) -> tuple[bool, list, list]:
        return _mod._validate_record(self._base_record(applies_to))

    def test_legal_applies_to_entry_passes(self):
        """A well-formed '<question_id>:<value>' entry must pass validation."""
        ok, errors, _warns = self._validate(["provider_for_task:gemini"])
        self.assertTrue(ok, msg=f"expected ok=True; errors: {errors}")
        self.assertEqual(errors, [])

    def test_multiple_legal_entries_different_qids_pass(self):
        """Two entries with distinct <question_id>s must pass."""
        ok, errors, _warns = self._validate(["provider_for_task:gemini", "model_size:large"])
        self.assertTrue(ok, msg=f"expected ok=True; errors: {errors}")
        self.assertEqual(errors, [])

    def test_missing_colon_rejected(self):
        """An entry with no ':' separator must be rejected."""
        ok, errors, _warns = self._validate(["provider_for_task"])
        self.assertFalse(ok)
        self.assertTrue(
            any(":" in e or "separator" in e for e in errors),
            msg=f"expected missing-separator error; got: {errors}",
        )

    def test_empty_question_id_rejected(self):
        """An entry with empty <question_id> (starts with ':') must be rejected."""
        ok, errors, _warns = self._validate([":gemini"])
        self.assertFalse(ok)
        self.assertTrue(
            any("empty" in e for e in errors),
            msg=f"expected empty-qid error; got: {errors}",
        )

    def test_empty_value_rejected(self):
        """An entry with empty <value> (ends with ':') must be rejected."""
        ok, errors, _warns = self._validate(["provider_for_task:"])
        self.assertFalse(ok)
        self.assertTrue(
            any("empty" in e for e in errors),
            msg=f"expected empty-value error; got: {errors}",
        )

    def test_non_charset_question_id_rejected(self):
        """A <question_id> with a hyphen (not in [a-z0-9_.]) must fail the charset check."""
        ok, errors, _warns = self._validate(["workflow-audit:amend"])
        self.assertFalse(ok)
        self.assertTrue(
            any("[a-z0-9_" in e or "charset" in e or "does not match" in e for e in errors),
            msg=f"expected charset error for hyphen-containing qid; got: {errors}",
        )

    def test_uppercase_question_id_rejected(self):
        """A <question_id> with uppercase letters must fail the charset check."""
        ok, errors, _warns = self._validate(["Workflow.audit_to_amend:amend"])
        self.assertFalse(ok)
        self.assertTrue(
            any("[a-z0-9_" in e or "does not match" in e for e in errors),
            msg=f"expected charset error for uppercase qid; got: {errors}",
        )

    def test_dotted_question_id_passes(self):
        """A dotted <question_id> like 'workflow.slug_confirm' must PASS validation."""
        ok, errors, _warns = self._validate(["workflow.slug_confirm:recommend_derived"])
        self.assertTrue(ok, msg=f"expected ok=True for dotted qid; errors: {errors}")
        self.assertEqual(errors, [])

    def test_real_config_question_ids_pass(self):
        """All real config.py QUESTION_IDS (dot-separated) must pass validation."""
        real_qids = [
            "workflow.audit_to_amend:amend",
            "workflow.slug_confirm:auto_accept",
            "workflow.implement_all_proceed:proceed",
            "workflow.review_all_proceed:proceed",
            "workflow.plan_decisions_approval:approve",
        ]
        for entry in real_qids:
            ok, errors, _warns = self._validate([entry])
            self.assertTrue(ok, msg=f"expected ok=True for {entry!r}; errors: {errors}")

    def test_duplicate_question_id_rejected(self):
        """Two entries with the same <question_id> must be rejected."""
        ok, errors, _warns = self._validate(
            ["provider_for_task:gemini", "provider_for_task:claude"]
        )
        self.assertFalse(ok)
        self.assertTrue(
            any("duplicate" in e for e in errors),
            msg=f"expected duplicate-qid error; got: {errors}",
        )

    def test_multi_colon_entry_rejected(self):
        """An applies_to entry with more than one colon must be rejected (SPEC line 78: exactly one ':')."""
        ok, errors, _warns = self._validate(["provider_for_task:some:compound:value"])
        self.assertFalse(ok, msg="expected ok=False for multi-colon entry")
        self.assertTrue(
            any("exactly one" in e for e in errors),
            msg=f"expected 'exactly one' error; got: {errors}",
        )

    def test_non_string_item_rejected(self):
        """A non-string item in applies_to must be rejected."""
        ok, errors, _warns = _mod._validate_record({
            **self._base_record(),
            "applies_to": [42],
        })
        self.assertFalse(ok)
        self.assertTrue(
            any("string" in e for e in errors),
            msg=f"expected string-type error; got: {errors}",
        )

    def test_empty_applies_to_array_rejected(self):
        """An empty applies_to array (violating minItems:1) must be rejected."""
        ok, errors, _warns = _mod._validate_record({
            **self._base_record(),
            "applies_to": [],
        })
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
