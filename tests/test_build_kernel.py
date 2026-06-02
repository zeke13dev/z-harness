"""
Tests for scripts/build-kernel.py (the kernel compiler).

Cases (per R6 / R2 / budget, SPEC inherited-agents-axioms):
  idempotent_body_and_hash   — repeat run, same inputs: byte-identical body
                               BELOW the volatile generated_at line AND identical
                               source_hash; generated_at itself differs (R6).
  budget_truncation          — many axioms exceeding --budget: omitted-count
                               comment present with the correct count.
  graph_invalid_dropped      — an approved record with a dangling supersede is
                               DROPPED from the kernel AND an axiom_integrity_warning
                               event is emitted to the run's metrics.jsonl (R2).
  authority_precedence_verbatim — the authority block appears verbatim.
  empty_store                — no axioms => valid kernel with "Approved axioms (0)".

HERMETICITY: every test uses a temp XDG_CONFIG_HOME and a temp --repo-root that
is its own git repo (so log-event.sh writes metrics.jsonl inside the temp tree).
The real ~/.config/z-harness store and the repo's own KERNEL.md are never touched.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "build-kernel.py")

# The authority block as it must appear verbatim in the kernel.
_AUTHORITY_BLOCK = (
    "explicit user instruction  >  hard safety gates  >  config/env (explicit)\n"
    "   >  routing-preference memory  >  approved axioms (project > global)  >  persona / built-in defaults"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_repo(root: Path) -> None:
    """Make *root* a git repo with one command file (so the skill index is non-empty)."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    cmds = root / "commands"
    cmds.mkdir(parents=True, exist_ok=True)
    (cmds / "foo.md").write_text(
        "---\nname: foo\ndescription: do a foo\n---\nbody\n", encoding="utf-8"
    )


def _approved_record(idx: int, scope: str = "global", **extra) -> dict:
    statement = f"Prefer behavior number {idx} over the alternative."
    rid = extra.pop("id", None) or f"ax-{idx:08x}"
    rec = {
        "id": rid,
        "statement": statement,
        "scope": scope,
        "status": "approved",
        "confidence": 0.80,
        "evidence": [{"run": "20260529T120000-test", "event_id": f"e-{idx:04d}"}],
        "source_run": "20260529T120000-test",
        "created_at": f"2026-05-29T12:00:{idx:02d}Z",
        "boundary_conditions": ["does not apply to internal helpers"],
        "counterexamples": ["a one-off override is fine"],
    }
    rec.update(extra)
    return rec


def _write_axiom(repo_root: Path, rec: dict) -> None:
    d = repo_root / ".z-harness" / "axioms" / "approved"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{rec['id']}.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")


def _run(repo_root: Path, xdg: Path, run_id: str = "test-run",
         extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run build-kernel.py with cwd inside the temp repo so metrics land there."""
    # Pin the artifact base into the temp repo so emitted events land in
    # repo_root/z-harness/metrics.jsonl (the default base is now the external
    # XDG state dir, which _metrics_events does not read).
    env = {**os.environ, "XDG_CONFIG_HOME": str(xdg), "Z_HARNESS_RUN": run_id,
           "Z_HARNESS_BASE_DIR": str(repo_root / "z-harness")}
    args = [sys.executable, _SCRIPT, "--scope", "project", "--repo-root", str(repo_root)]
    args += extra_args or []
    return subprocess.run(
        args, cwd=str(repo_root), env=env, capture_output=True, text=True
    )


def _kernel_path(repo_root: Path) -> Path:
    return repo_root / ".z-harness" / "KERNEL.md"


def _body_below_header(text: str) -> str:
    """Drop the volatile generated_at line — the R6 idempotency target."""
    return "".join(
        line for line in text.splitlines(keepends=True)
        if not line.startswith("generated_at:")
    )


def _metrics_events(repo_root: Path) -> list[dict]:
    p = repo_root / "z-harness" / "metrics.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# R6: idempotency on the hashed region
# ---------------------------------------------------------------------------

class TestIdempotency(unittest.TestCase):
    def test_body_and_hash_identical_generated_at_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"
            for i in range(3):
                _write_axiom(repo, _approved_record(i, scope="project"))

            r1 = _run(repo, xdg, run_id="run1")
            self.assertEqual(r1.returncode, 0, msg=r1.stderr)
            text1 = _kernel_path(repo).read_text()

            r2 = _run(repo, xdg, run_id="run2")
            self.assertEqual(r2.returncode, 0, msg=r2.stderr)
            text2 = _kernel_path(repo).read_text()

            # Body below the generated_at line is byte-identical.
            self.assertEqual(_body_below_header(text1), _body_below_header(text2))
            # source_hash header line identical.
            hash1 = re.search(r"source_hash: (\w+)", text1).group(1)
            hash2 = re.search(r"source_hash: (\w+)", text2).group(1)
            self.assertEqual(hash1, hash2)
            # The summary source_hash from both runs agrees too.
            self.assertEqual(
                json.loads(r1.stdout)["source_hash"],
                json.loads(r2.stdout)["source_hash"],
            )


# ---------------------------------------------------------------------------
# Budget truncation
# ---------------------------------------------------------------------------

class TestBudgetTruncation(unittest.TestCase):
    def test_omitted_comment_and_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"
            n = 40
            for i in range(n):
                _write_axiom(repo, _approved_record(i, scope="project"))

            # Tiny budget so only a few axioms fit.
            r = _run(repo, xdg, extra_args=["--budget", "900"])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            summary = json.loads(r.stdout)
            self.assertGreater(summary["n_omitted"], 0)
            self.assertEqual(summary["n_axioms"] + summary["n_omitted"], n)

            text = _kernel_path(repo).read_text()
            m = re.search(r"<!-- (\d+) axioms omitted for budget -->", text)
            self.assertIsNotNone(m, msg="omitted-budget comment missing")
            self.assertEqual(int(m.group(1)), summary["n_omitted"])
            # The rendered axiom count matches n_axioms.
            rendered = len(re.findall(r"^- \[ax-", text, re.MULTILINE))
            self.assertEqual(rendered, summary["n_axioms"])

    def test_rendered_kernel_fits_budget(self):
        """
        Lock in accurate overhead accounting: with a small --budget and many
        axioms, the REAL written kernel (with a real 20-char generated_at value)
        must be <= budget. The whole kernel is counted — nothing is excluded from
        the budget — so this catches the prior generated_at-width and
        n_axioms-heading underestimation bugs that let the output exceed --budget.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"
            n = 40
            for i in range(n):
                _write_axiom(repo, _approved_record(i, scope="project"))

            budget = 900
            r = _run(repo, xdg, extra_args=["--budget", str(budget)])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            summary = json.loads(r.stdout)
            self.assertGreater(summary["n_omitted"], 0, msg="test needs truncation to be meaningful")

            text = _kernel_path(repo).read_text()
            # The real rendered kernel includes a 20-char ISO-8601 generated_at value.
            self.assertRegex(
                text, r"generated_at: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            )
            self.assertLessEqual(
                len(text), budget,
                msg=f"rendered kernel ({len(text)} chars) exceeds budget {budget}",
            )

    def test_single_oversize_axiom_still_included(self):
        """A single axiom larger than --budget is still included (never empty)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"
            _write_axiom(repo, _approved_record(0, scope="project"))
            # Budget far below even the static overhead.
            r = _run(repo, xdg, extra_args=["--budget", "1"])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            summary = json.loads(r.stdout)
            self.assertEqual(summary["n_axioms"], 1)
            self.assertEqual(summary["n_omitted"], 0)


# ---------------------------------------------------------------------------
# R2: graph-invalid approved record is dropped + warns
# ---------------------------------------------------------------------------

class TestGraphInvalidDropped(unittest.TestCase):
    def test_dangling_supersede_dropped_and_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"

            good = _approved_record(1, scope="project")
            # 'bad' supersedes an id that does not exist in the approved set
            # (dangling supersede) -> graph-invalid -> must be dropped.
            bad = _approved_record(2, scope="project", supersedes="ax-deadbeef")
            _write_axiom(repo, good)
            _write_axiom(repo, bad)

            r = _run(repo, xdg, run_id="drop-run")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            summary = json.loads(r.stdout)
            self.assertEqual(summary["drop_count"], 1)
            self.assertEqual(summary["n_axioms"], 1)

            text = _kernel_path(repo).read_text()
            # Bad record excluded; good record present.
            self.assertNotIn(bad["id"], text)
            self.assertIn(good["id"], text)
            self.assertIn("drop_count: 1", text)

            # The axiom_integrity_warning event was emitted (R2).
            events = _metrics_events(repo)
            warnings = [e for e in events if e.get("kind") == "axiom_integrity_warning"]
            self.assertEqual(len(warnings), 1, msg=f"events: {events}")
            self.assertEqual(warnings[0]["axiom_id"], bad["id"])


# ---------------------------------------------------------------------------
# Authority precedence verbatim
# ---------------------------------------------------------------------------

class TestAuthorityVerbatim(unittest.TestCase):
    def test_block_present_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"
            r = _run(repo, xdg)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            text = _kernel_path(repo).read_text()
            self.assertIn("### Authority precedence", text)
            self.assertIn(_AUTHORITY_BLOCK, text)


# ---------------------------------------------------------------------------
# Empty store
# ---------------------------------------------------------------------------

class TestEmptyStore(unittest.TestCase):
    def test_valid_kernel_zero_axioms(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"
            r = _run(repo, xdg)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            summary = json.loads(r.stdout)
            self.assertEqual(summary["n_axioms"], 0)
            text = _kernel_path(repo).read_text()
            self.assertIn("### Approved axioms (0)", text)
            self.assertIn("<!-- z-harness-kernel GENERATED", text)


_AXIOM_STORE_SCRIPT = str(_REPO_ROOT / "scripts" / "axiom-store.py")


def _run_store(args: list[str], env: dict,
               stdin_data: str | None = None) -> subprocess.CompletedProcess:
    """Run axiom-store.py with the given env."""
    return subprocess.run(
        [sys.executable, _AXIOM_STORE_SCRIPT] + args,
        env=env, capture_output=True, text=True, input=stdin_data,
    )


def _write_axiom_in_dir(store_dir: Path, subdir: str, rec: dict) -> None:
    d = store_dir / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{rec['id']}.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")


def _approved_rec_full(ax_id: str, statement: str, scope: str = "global",
                       **extra) -> dict:
    """Build a minimal valid approved record (with boundary_conditions)."""
    r = {
        "id": ax_id,
        "statement": statement,
        "scope": scope,
        "status": "approved",
        "confidence": 0.80,
        "evidence": [{"run": "20260529T120000-test", "event_id": "e-0001"}],
        "source_run": "20260529T120000-test",
        "created_at": "2026-05-29T12:00:00Z",
        "boundary_conditions": ["does not apply to internal helpers"],
        "counterexamples": ["a one-off override is fine"],
    }
    r.update(extra)
    return r


def _candidate_rec_full(ax_id: str, statement: str, scope: str = "global",
                        **extra) -> dict:
    """Build a minimal valid candidate record (with boundary_conditions)."""
    r = {
        "id": ax_id,
        "statement": statement,
        "scope": scope,
        "status": "candidate",
        "confidence": 0.80,
        "evidence": [{"run": "20260529T120000-test", "event_id": "e-0001"}],
        "source_run": "20260529T120000-test",
        "created_at": "2026-05-29T12:00:00Z",
        "boundary_conditions": ["does not apply to internal helpers"],
        "counterexamples": ["a one-off override is fine"],
    }
    r.update(extra)
    return r


# ---------------------------------------------------------------------------
# T007 Part B: Supersede round-trip integration test (R1-completeness fix)
# ---------------------------------------------------------------------------

class TestSupersederoundtrip(unittest.TestCase):
    """
    B is approved, then A is approved with supersedes=B (B demoted to rejected/).
    build-kernel.py must include A, exclude B, report drop_count: 0, and emit NO
    axiom_integrity_warning. Before the R1-completeness fix, A would be dropped
    because _filter_graph_valid only saw approved records and B was absent.
    """

    def test_supersede_roundtrip_no_false_drop(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"
            store_dir = repo / ".z-harness" / "axioms"

            # Plant B as approved (old rule).
            b_id = "ax-b0000001"
            b_rec = _approved_rec_full(b_id, "Prefer the old behavior.", scope="project")
            _write_axiom_in_dir(store_dir, "approved", b_rec)

            # A supersedes B — approved, B demoted to rejected/.
            a_id = "ax-a0000001"
            a_rec = _approved_rec_full(
                a_id, "Prefer the new behavior.",
                scope="project",
                supersedes=b_id,
            )
            _write_axiom_in_dir(store_dir, "approved", a_rec)

            # Demote B to rejected/ (as the approve flow would have done).
            b_rejected = dict(b_rec)
            b_rejected["status"] = "rejected"
            b_rejected["superseded_by"] = a_id
            _write_axiom_in_dir(store_dir, "rejected", b_rejected)
            # Remove B from approved/.
            (store_dir / "approved" / f"{b_id}.json").unlink()

            env = {**os.environ, "XDG_CONFIG_HOME": str(xdg), "Z_HARNESS_RUN": "supersede-test",
                   "Z_HARNESS_BASE_DIR": str(repo / "z-harness")}
            r = subprocess.run(
                [sys.executable, _SCRIPT, "--scope", "project",
                 "--repo-root", str(repo)],
                cwd=str(repo), env=env, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, msg=f"stderr: {r.stderr}\nstdout: {r.stdout}")
            summary = json.loads(r.stdout)

            # A must be in kernel; B must be absent.
            text = _kernel_path(repo).read_text()
            self.assertIn(a_id, text, msg="superseding axiom A must appear in kernel")
            self.assertNotIn(b_id, text, msg="demoted axiom B must NOT appear in kernel")

            # drop_count must be 0 — no false-positive integrity warnings.
            self.assertEqual(summary["drop_count"], 0,
                             msg="drop_count must be 0; A was falsely dropped before this fix")
            self.assertIn("drop_count: 0", text)

            # No axiom_integrity_warning events should have been emitted.
            events_file = repo / "z-harness" / "metrics.jsonl"
            if events_file.exists():
                events = [json.loads(ln) for ln in events_file.read_text().splitlines() if ln.strip()]
                warnings = [e for e in events if e.get("kind") == "axiom_integrity_warning"]
                self.assertEqual(warnings, [],
                                 msg=f"No axiom_integrity_warning expected; got: {warnings}")


# ---------------------------------------------------------------------------
# T007 Part A: Approve→fresh-kernel / reject→fresh-kernel integration test
# ---------------------------------------------------------------------------

class TestApproveRejectKernelRegen(unittest.TestCase):
    """
    End-to-end: axiom-store.py approve regenerates KERNEL.md with the new axiom;
    reject removes it. source_hash changes accordingly.
    """

    def _env(self, xdg: Path, repo: Path) -> dict:
        return {
            **os.environ,
            "XDG_CONFIG_HOME": str(xdg),
            "Z_HARNESS_RUN": "regen-test",
            # Pin the base into the temp repo (default base is now external).
            "Z_HARNESS_BASE_DIR": str(repo / "z-harness"),
        }

    def test_approve_regenerates_kernel_with_new_axiom(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"
            env = self._env(xdg, repo)

            # First, build an empty kernel to establish a baseline source_hash.
            r0 = subprocess.run(
                [sys.executable, _SCRIPT, "--scope", "project",
                 "--repo-root", str(repo)],
                cwd=str(repo), env=env, capture_output=True, text=True,
            )
            self.assertEqual(r0.returncode, 0, msg=r0.stderr)
            text0 = _kernel_path(repo).read_text()
            import re as _re
            hash0 = _re.search(r"source_hash: (\w+)", text0).group(1)

            # Plant a candidate and approve it (axiom-store.py will call build-kernel.py).
            store_dir = repo / ".z-harness" / "axioms"
            ax_id = "ax-cc000001"
            cand = _candidate_rec_full(ax_id, "Prefer the hermetic test approach.",
                                       scope="project")
            _write_axiom_in_dir(store_dir, "candidates", cand)

            r_approve = _run_store(
                ["approve", ax_id, "--scope", "project", "--repo-root", str(repo)],
                env=env,
            )
            self.assertEqual(r_approve.returncode, 0,
                             msg=f"approve failed: {r_approve.stdout}\n{r_approve.stderr}")
            approve_data = json.loads(r_approve.stdout)
            self.assertEqual(approve_data["status"], "approved")

            # KERNEL.md must now contain the new axiom.
            text1 = _kernel_path(repo).read_text()
            self.assertIn(ax_id, text1, msg="kernel must include newly approved axiom")
            hash1 = _re.search(r"source_hash: (\w+)", text1).group(1)
            self.assertNotEqual(hash0, hash1, msg="source_hash must change after approve")

            # Reject the approved axiom — kernel must no longer include it.
            r_reject = _run_store(
                ["reject", ax_id, "--scope", "project", "--repo-root", str(repo)],
                env=env,
            )
            self.assertEqual(r_reject.returncode, 0,
                             msg=f"reject failed: {r_reject.stdout}\n{r_reject.stderr}")
            reject_data = json.loads(r_reject.stdout)
            self.assertEqual(reject_data["status"], "ok")

            text2 = _kernel_path(repo).read_text()
            self.assertNotIn(ax_id, text2, msg="kernel must exclude rejected axiom")
            hash2 = _re.search(r"source_hash: (\w+)", text2).group(1)
            self.assertNotEqual(hash1, hash2, msg="source_hash must change after reject")
            # Back to the same hash as the empty kernel (no axioms).
            self.assertEqual(hash0, hash2,
                             msg="source_hash after reject must match the pre-approve baseline")


# ---------------------------------------------------------------------------
# T007 R2 regression guard: genuinely tampered approved record is still dropped
# ---------------------------------------------------------------------------

class TestTamperedApprovedDropped(unittest.TestCase):
    """
    A genuinely graph-invalid APPROVED record (e.g. dangling supersedes target
    that is NOT present in ANY status subdir) must still be dropped with an
    axiom_integrity_warning (R2 preserved). This guard ensures the R1-completeness
    fix did not accidentally suppress real integrity errors.
    """

    def test_genuine_dangling_supersede_still_dropped_and_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            xdg = Path(tmp) / "xdg"
            store_dir = repo / ".z-harness" / "axioms"

            good = _approved_rec_full("ax-good0001", "Prefer good behavior.", scope="project")
            # 'bad' supersedes a target that exists NOWHERE (not in any subdir).
            bad = _approved_rec_full(
                "ax-bad00001", "Prefer bad behavior.",
                scope="project",
                supersedes="ax-deadbeef",  # genuinely absent from all dirs
            )
            _write_axiom_in_dir(store_dir, "approved", good)
            _write_axiom_in_dir(store_dir, "approved", bad)

            env = {**os.environ, "XDG_CONFIG_HOME": str(xdg), "Z_HARNESS_RUN": "tamper-test",
                   "Z_HARNESS_BASE_DIR": str(repo / "z-harness")}
            r = subprocess.run(
                [sys.executable, _SCRIPT, "--scope", "project",
                 "--repo-root", str(repo)],
                cwd=str(repo), env=env, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, msg=f"stderr: {r.stderr}")
            summary = json.loads(r.stdout)

            # drop_count must be 1; good must be present, bad must be absent.
            self.assertEqual(summary["drop_count"], 1,
                             msg="genuinely invalid record must be dropped (drop_count=1)")
            text = _kernel_path(repo).read_text()
            self.assertIn(good["id"], text, msg="valid record must remain in kernel")
            self.assertNotIn(bad["id"], text, msg="tampered record must be excluded")
            self.assertIn("drop_count: 1", text)

            # axiom_integrity_warning event must have been emitted.
            events_file = repo / "z-harness" / "metrics.jsonl"
            self.assertTrue(events_file.exists(),
                            msg="metrics.jsonl must exist (events were emitted)")
            events = [json.loads(ln) for ln in events_file.read_text().splitlines() if ln.strip()]
            warnings = [e for e in events if e.get("kind") == "axiom_integrity_warning"]
            self.assertEqual(len(warnings), 1,
                             msg=f"exactly one axiom_integrity_warning expected; got: {warnings}")
            self.assertEqual(warnings[0]["axiom_id"], bad["id"])


if __name__ == "__main__":
    unittest.main()
