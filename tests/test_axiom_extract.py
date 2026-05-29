"""
Tests for scripts/axiom-extract.py (T014 — axiom mining, R8 + Invariant 8).

HERMETICITY: every test builds a synthetic metrics.jsonl under a fresh tmpdir
and passes ``--repo-root <tmpdir>``.  The real z-harness/metrics.jsonl is never
read or written.  Synthetic decision events use log-decision.sh's payload shape
({question_id, decision_key, chosen, options, tentative, source_command,
event_id}); synthetic gate events use the {choice}/{override} shape the
orchestrators emit.

Cases:
  recurrence_threshold_proposes        — repeat >= min yields one candidate
  recurrence_below_threshold_none      — repeat < min yields none
  confidence_formula                   — min(0.95, rec/(rec+2)) for known rec
  dedup_exact                          — two identical groups → one candidate
  dedup_fuzzy_annotates                — near-identical statements → possible_duplicate_of
  run_scoping                          — --run filters to one run
  historical_scoping                   — --historical sees all runs
  graceful_zero_result                 — no decision/gate events → [] exit 0
  candidates_schema_valid              — emitted records validate (candidate + evidence)
  mines_decision_and_gate_kinds        — user_choice AND a gate event in one scan
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "axiom-extract.py")
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

# Import axiom-store's validator the same way the extractor does (read-only).
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_axiom_store = importlib.import_module("axiom-store")
_validate_record = _axiom_store._validate_record


def _decision_event(
    run: str,
    question_id: str,
    chosen: str,
    *,
    kind: str = "user_choice",
    event_id: str | None = None,
    ts: str = "2026-05-29T00:00:00Z",
) -> dict:
    """Build a metrics.jsonl line matching log-decision.sh's emitted shape."""
    return {
        "ts": ts,
        "run": run,
        "kind": kind,
        "question_id": question_id,
        "decision_key": question_id,
        "chosen": chosen,
        "options": [],
        "tentative": None,
        "source_command": None,
        "event_id": event_id or f"e-{abs(hash((run, question_id, chosen))) % (10 ** 8):08d}",
    }


def _gate_event(
    run: str,
    kind: str,
    *,
    choice: str | None = None,
    override: bool | None = None,
    ts: str = "2026-05-29T00:00:00Z",
) -> dict:
    """Build a structured gate event line (no event_id, as orchestrators emit)."""
    obj: dict = {"ts": ts, "run": run, "kind": kind}
    if choice is not None:
        obj["choice"] = choice
    if override is not None:
        obj["override"] = override
    return obj


def _write_metrics(repo_root: Path, events: list[dict]) -> None:
    z = repo_root / "z-harness"
    z.mkdir(parents=True, exist_ok=True)
    with open(z / "metrics.jsonl", "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


def _run_extract(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, _SCRIPT, "--repo-root", str(repo_root), *args],
        capture_output=True,
        text=True,
    )


class AxiomExtractTest(unittest.TestCase):

    def _extract(self, events: list[dict], *args: str) -> tuple[list[dict], subprocess.CompletedProcess]:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_metrics(root, events)
            proc = _run_extract(root, *args)
            self.assertEqual(proc.returncode, 0, msg=f"stderr: {proc.stderr}")
            data = json.loads(proc.stdout)
            return data, proc

    # --- recurrence threshold ------------------------------------------------

    def test_recurrence_threshold_proposes(self):
        # 3 identical decisions (default min_recurrence=3) → one candidate.
        events = [_decision_event("r1", "workflow.audit_to_amend", "amend") for _ in range(3)]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["status"], "candidate")
        self.assertNotIn("id", cands[0])

    def test_recurrence_below_threshold_none(self):
        # 2 identical decisions (< default min 3) → no candidate.
        events = [_decision_event("r1", "workflow.audit_to_amend", "amend") for _ in range(2)]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(cands, [])

    # --- confidence ----------------------------------------------------------

    def test_confidence_formula(self):
        # rec=4 → min(0.95, 4/6) = 0.6666...
        events = [
            _decision_event("r1", "workflow.slug_confirm", "auto_accept", event_id=f"e-{i:08d}")
            for i in range(4)
        ]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1)
        self.assertAlmostEqual(cands[0]["confidence"], 4 / 6, places=9)

    def test_confidence_capped(self):
        # rec=100 → min(0.95, 100/102) = 0.95 cap.
        events = [
            _decision_event("r1", "workflow.slug_confirm", "ask", event_id=f"e-{i:08d}")
            for i in range(100)
        ]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1)
        self.assertAlmostEqual(cands[0]["confidence"], 0.95, places=9)

    # --- dedup ---------------------------------------------------------------

    def test_dedup_exact(self):
        # Two groups that synthesize the SAME statement+scope → one candidate.
        # Same kind+decision_key+normalized_value but different casing of chosen
        # normalizes to the same value → exact collapse within grouping itself,
        # so to force two *groups* that hash-collide we vary event_id only.
        events = [_decision_event("r1", "workflow.audit_to_amend", "AMEND", event_id=f"e-{i:08d}")
                  for i in range(3)]
        events += [_decision_event("r1", "workflow.audit_to_amend", "amend", event_id=f"e-1{i:07d}")
                   for i in range(3)]
        cands, _ = self._extract(events, "--run", "r1")
        # "AMEND" and "amend" normalize identically → single group → one candidate.
        self.assertEqual(len(cands), 1)

    def test_dedup_fuzzy_annotates(self):
        # Two distinct groups whose synthesized statements share >=0.9 token-set.
        # decision_key "deploy strategy" vs "deploy strategies", same value →
        # near-identical statements → second gets a possible_duplicate_of
        # advisory.  The advisory lives on STDERR; the stdout records stay clean.
        events = [_decision_event("r1", "deploy strategy", "blue green", event_id=f"e-{i:08d}")
                  for i in range(3)]
        events += [_decision_event("r1", "deploy strategy now", "blue green", event_id=f"e-1{i:07d}")
                   for i in range(3)]
        cands, proc = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 2)
        # No stdout record carries the extractor-only annotation field.
        for c in cands:
            self.assertNotIn("possible_duplicate_of", c)
        # The dedup hint surfaces on stderr as a structured advisory bound to the
        # affected candidate by index + statement.
        advisory = json.loads(proc.stderr)
        flagged = [a for a in advisory["advisories"] if "possible_duplicate_of" in a]
        self.assertEqual(len(flagged), 1, msg=f"advisories: {advisory}")
        a = flagged[0]
        # The advisory binds back to a real stdout record.
        self.assertIn(a["candidate_index"], range(len(cands)))
        self.assertEqual(cands[a["candidate_index"]]["statement"], a["statement"])

    # --- scoping -------------------------------------------------------------

    def test_run_scoping(self):
        # r1 has a recurring group; r2 has a different one. --run r1 sees only r1.
        events = [_decision_event("r1", "q.a", "x", event_id=f"e-a{i:07d}") for i in range(3)]
        events += [_decision_event("r2", "q.b", "y", event_id=f"e-b{i:07d}") for i in range(3)]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1)
        # The single candidate's evidence is all from r1.
        runs = {ev["run"] for ev in cands[0]["evidence"]}
        self.assertEqual(runs, {"r1"})

    def test_historical_scoping(self):
        # Same decision recurs across r1+r2+r3 → --historical aggregates to 3.
        events = [_decision_event(r, "q.shared", "pick", event_id=f"e-{r}0000000") for r in ("r1", "r2", "r3")]
        cands, _ = self._extract(events, "--historical")
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["source_run"], "historical")
        self.assertEqual(len(cands[0]["evidence"]), 3)

    # --- graceful degradation (Invariant 8) ----------------------------------

    def test_graceful_zero_result(self):
        # metrics.jsonl with only unrelated kinds → [] and exit 0, no error.
        events = [
            {"ts": "2026-05-29T00:00:00Z", "run": "r1", "kind": "consult", "llm": "gemini"},
            {"ts": "2026-05-29T00:00:01Z", "run": "r1", "kind": "implement_start", "id": "T001"},
        ]
        cands, proc = self._extract(events, "--historical")
        self.assertEqual(cands, [])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.strip(), "")

    def test_missing_metrics_file_graceful(self):
        # No metrics.jsonl at all → empty array, exit 0.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proc = _run_extract(root, "--historical")
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertEqual(json.loads(proc.stdout), [])

    # --- schema validity -----------------------------------------------------

    # Allowed top-level keys on a candidate record (axiom schema minus `id`,
    # which candidates ship without per spec).
    _CANDIDATE_KEYS = {
        "statement", "scope", "status", "confidence", "evidence",
        "source_run", "created_at", "discipline", "applies_to",
        "boundary_conditions", "counterexamples", "conflicts_with",
        "supersedes", "approved_at", "review_after",
    }

    def test_candidates_schema_valid(self):
        events = [_decision_event("r1", "workflow.audit_to_amend", "amend", event_id=f"e-{i:08d}")
                  for i in range(3)]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1)
        cand = cands[0]
        self.assertEqual(cand["status"], "candidate")
        # evidence has run + event_id per schema.
        for ev in cand["evidence"]:
            self.assertIn("run", ev)
            self.assertIn("event_id", ev)
        # Validates against the store's single-record validator once an id is
        # assigned (candidates ship without one per spec).
        probe = dict(cand)
        probe["id"] = "ax-00000000"
        ok, errors, _warns = _validate_record(probe)
        self.assertTrue(ok, msg=f"validation errors: {errors}")

    def test_emitted_records_have_no_extra_keys(self):
        # REGRESSION LOCK (the T014 blocker): every stdout record must validate
        # with ZERO errors against axiom-store's _validate_record AND carry NO
        # keys outside the axiom schema.  Use a scenario that exercises BOTH the
        # fuzzy-dedup path and the MEMORY-overlap path so the extractor-only
        # `possible_duplicate_of` / `notes` fields would be present in-memory —
        # then assert they are absent from every emitted record.
        events = [_decision_event("r1", "deploy strategy", "blue green", event_id=f"e-{i:08d}")
                  for i in range(3)]
        events += [_decision_event("r1", "deploy strategy now", "blue green", event_id=f"e-1{i:07d}")
                   for i in range(3)]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_metrics(root, events)
            # A MEMORY.md line that strongly overlaps a synthesized statement,
            # to force a `notes` annotation in-memory.
            (root / "MEMORY.md").write_text(
                "- When facing the deploy strategy decision prefer blue green\n",
                encoding="utf-8",
            )
            proc = _run_extract(root, "--run", "r1")
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            cands = json.loads(proc.stdout)
        self.assertTrue(cands)
        for cand in cands:
            # No forbidden / extractor-only keys leaked into the record.
            self.assertNotIn("possible_duplicate_of", cand)
            self.assertNotIn("notes", cand)
            extra = set(cand) - self._CANDIDATE_KEYS
            self.assertEqual(extra, set(), msg=f"unexpected keys: {extra}")
            # Validates with ZERO errors once an id is assigned.
            probe = dict(cand)
            probe["id"] = "ax-00000000"
            ok, errors, _warns = _validate_record(probe)
            self.assertTrue(ok, msg=f"validation errors: {errors}")
            self.assertEqual(errors, [])

    def test_emitted_candidate_accepted_by_store_add(self):
        # PIPELINE ACCEPTANCE: feed an emitted candidate straight into
        # `axiom-store.py add` in a hermetic temp store and assert it is accepted
        # (status != "invalid").  Proves the scan→add pipeline no longer breaks.
        events = [_decision_event("r1", "deploy strategy", "blue green", event_id=f"e-{i:08d}")
                  for i in range(3)]
        events += [_decision_event("r1", "deploy strategy now", "blue green", event_id=f"e-1{i:07d}")
                   for i in range(3)]
        store_script = str(_SCRIPTS_DIR / "axiom-store.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_metrics(root, events)
            proc = _run_extract(root, "--run", "r1")
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            cands = json.loads(proc.stdout)
            self.assertTrue(cands)
            for cand in cands:
                add = subprocess.run(
                    [sys.executable, store_script, "add",
                     "--scope", "project", "--repo-root", str(root),
                     "--from-json", "-"],
                    input=json.dumps(cand),
                    capture_output=True,
                    text=True,
                )
                result = json.loads(add.stdout)
                self.assertNotEqual(
                    result.get("status"), "invalid",
                    msg=f"store rejected emitted candidate: {add.stdout}\nstderr: {add.stderr}",
                )
                self.assertEqual(result.get("status"), "ok",
                                 msg=f"store add did not accept: {add.stdout}")

    # --- mixed kinds ---------------------------------------------------------

    def test_mines_decision_and_gate_kinds(self):
        # A recurring user_choice AND a recurring cost_gate_decision in one scan.
        events = [_decision_event("r1", "q.choice", "go", event_id=f"e-c{i:07d}") for i in range(3)]
        events += [_gate_event("r1", "cost_gate_decision", choice="proceed") for _ in range(3)]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 2)
        kinds = set()
        for c in cands:
            kinds.update(ev.get("kind") for ev in c["evidence"])
        self.assertIn("user_choice", kinds)
        self.assertIn("cost_gate_decision", kinds)

    def test_gate_event_evidence_uses_quote_fallback(self):
        # Gate events lack event_id → evidence uses {run, quote} (schema anyOf).
        events = [_gate_event("r1", "map_collision_decision", choice="continue") for _ in range(3)]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1)
        for ev in cands[0]["evidence"]:
            self.assertIn("run", ev)
            self.assertIn("quote", ev)
        probe = dict(cands[0])
        probe["id"] = "ax-00000000"
        ok, errors, _warns = _validate_record(probe)
        self.assertTrue(ok, msg=f"validation errors: {errors}")


# ---------------------------------------------------------------------------
# Tests: applies_to population (T022 — Option A value-encoding)
# ---------------------------------------------------------------------------

class TestAppliesToPopulation(unittest.TestCase):
    """
    Verify that the miner populates applies_to for routing-question groups and
    omits it for free-form behavioral (gate-kind) groups.

    Routing-question events (user_choice / user_override) with a decision_key
    that matches [a-z0-9_.]+ get applies_to: ["<decision_key>:<normalized_value>"].
    Dots are admitted so that real config.py QUESTION_IDS like workflow.slug_confirm
    round-trip correctly (the old [a-z0-9_]+ charset excluded dots, making the
    routing channel dead-on-arrival for all real question ids).
    Gate-kind events (cost_gate_decision, etc.) are behavioral axioms with no
    routing target — applies_to must be absent.
    """

    def _extract(self, events: list[dict], *args: str) -> tuple[list[dict], str]:
        """Write events to a tmp metrics.jsonl, run the extractor, return (candidates, stderr)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_metrics(root, events)
            proc = _run_extract(root, *args)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return json.loads(proc.stdout), proc.stderr

    def test_routing_question_group_emits_applies_to(self):
        """
        A user_choice group whose decision_key matches [a-z0-9_]+ must emit
        applies_to: ["<decision_key>:<normalized_value>"].
        """
        # Use a decision_key that matches [a-z0-9_]+ (no dots).
        events = [
            _decision_event("r1", "provider_for_task", "gemini", event_id=f"e-{i:08d}")
            for i in range(3)
        ]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1, msg="expected exactly one candidate")
        cand = cands[0]
        self.assertIn("applies_to", cand,
                      msg="routing-question group must have applies_to")
        self.assertEqual(cand["applies_to"], ["provider_for_task:gemini"])

    def test_routing_question_group_applies_to_schema_valid(self):
        """The emitted record (with applies_to) must pass _validate_record."""
        events = [
            _decision_event("r1", "provider_for_task", "gemini", event_id=f"e-{i:08d}")
            for i in range(3)
        ]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1)
        probe = dict(cands[0])
        probe["id"] = "ax-00000000"
        ok, errors, _warns = _validate_record(probe)
        self.assertTrue(ok, msg=f"validation errors after adding id: {errors}")

    def test_gate_kind_group_omits_applies_to(self):
        """
        A gate-kind group (cost_gate_decision) is a behavioral axiom with no
        routing target — applies_to must be absent from the emitted candidate.
        """
        events = [
            _gate_event("r1", "cost_gate_decision", choice="continue")
            for _ in range(3)
        ]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1, msg="expected exactly one candidate")
        cand = cands[0]
        self.assertNotIn("applies_to", cand,
                         msg="gate-kind behavioral group must NOT have applies_to")

    def test_normalized_value_in_applies_to(self):
        """The <value> half of applies_to must be the normalized (lowercase, trimmed) chosen."""
        events = [
            _decision_event("r1", "model_size", "Large Model", event_id=f"e-{i:08d}")
            for i in range(3)
        ]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1)
        cand = cands[0]
        self.assertIn("applies_to", cand)
        # normalized_value of "Large Model" is "large model"
        self.assertEqual(cand["applies_to"], ["model_size:large model"])

    def test_user_override_routing_question_emits_applies_to(self):
        """user_override events also trigger applies_to population (same kind set)."""
        events = [
            _decision_event("r1", "deploy_target", "staging",
                            kind="user_override", event_id=f"e-{i:08d}")
            for i in range(3)
        ]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1)
        cand = cands[0]
        self.assertIn("applies_to", cand)
        self.assertEqual(cand["applies_to"], ["deploy_target:staging"])

    def test_dotted_decision_key_emits_applies_to(self):
        """
        A real dotted decision_key like workflow.slug_confirm must populate
        applies_to (previously the [a-z0-9_]+ charset excluded dots, making
        the routing channel dead-on-arrival for all real config.py QUESTION_IDS).
        """
        events = [
            _decision_event("r1", "workflow.slug_confirm", "recommend_derived",
                            event_id=f"e-{i:08d}")
            for i in range(3)
        ]
        cands, _ = self._extract(events, "--run", "r1")
        self.assertEqual(len(cands), 1, msg="expected exactly one candidate")
        cand = cands[0]
        self.assertIn("applies_to", cand,
                      msg="dotted decision_key must produce applies_to entry")
        self.assertEqual(cand["applies_to"], ["workflow.slug_confirm:recommend_derived"],
                         msg="applies_to must round-trip the dotted decision_key unchanged")

    def test_real_config_question_ids_all_emit_applies_to(self):
        """
        All real config.py QUESTION_IDS (dot-separated) must produce applies_to
        entries, confirming the routing channel is live for actual workflows.
        """
        real_qids = [
            "workflow.audit_to_amend",
            "workflow.slug_confirm",
            "workflow.implement_all_proceed",
            "workflow.review_all_proceed",
            "workflow.plan_decisions_approval",
        ]
        for qid in real_qids:
            events = [
                _decision_event("r1", qid, "proceed", event_id=f"e-{i:08d}")
                for i in range(3)
            ]
            cands, _ = self._extract(events, "--run", "r1")
            self.assertEqual(len(cands), 1,
                             msg=f"expected one candidate for qid={qid!r}")
            cand = cands[0]
            self.assertIn("applies_to", cand,
                          msg=f"real qid {qid!r} must produce applies_to entry")
            expected = f"{qid}:proceed"
            self.assertEqual(cand["applies_to"], [expected],
                             msg=f"applies_to mismatch for {qid!r}")


if __name__ == "__main__":
    unittest.main()
