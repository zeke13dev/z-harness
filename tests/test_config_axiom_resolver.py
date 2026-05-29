"""
Tests for the axiom resolver layer + axiom_conflict branch in scripts/config.py
(T012). Exercises `_load_axiom_matches` and the axiom layer inside
`_build_resolve_envelope`, surfaced through `config.py resolve-question <qid>`.

Precedence cases covered (SPEC `## scripts/config.py`, R3 / R7 / R10):
  agree           — axiom value == already-resolved (config) value: config wins,
                    axiom appears in `sources` only, NO nested `axiom` object.
  gap_fill        — config at default AND memory silent: axiom fills the gap →
                    source="axiom", strength="soft", result from RESULT_MAP,
                    nested axiom:{id, statement} with NO `conflict` key.
  direct_conflict — config set a DIFFERENT value: higher layer wins the
                    value/result/strength; source="axiom_conflict", nested
                    axiom:{id, statement, conflict: true}.
  no_match        — no axiom answers the question: envelope BYTE-IDENTICAL to the
                    pre-axiom baseline; the `axiom` key is ABSENT (R7).
  disabled        — axioms.enabled=false: no axiom participation at all.
  choice_drop     — an axiom whose applies_to value is NOT a legal choice for the
                    question is dropped (choice-membership lives in the resolver,
                    SPEC line 78), so it never participates.

R10 snapshot note: each resolve-question invocation reads config, memory, and the
axiom store within a SINGLE process invocation; the precedence assertions below
are scoped to that per-invocation snapshot. No cross-invocation atomicity is
asserted (acceptable for the CLI flow). Tests are hermetic: a temp
XDG_CONFIG_HOME and a temp Z_HARNESS_PROJECT_ROOT host the seeded axiom store, so
the real global/project store, metrics.jsonl, and KERNEL.md are never touched.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(_REPO_ROOT / "scripts" / "config.py")

# Question under test and its choices (mirrors QUESTION_IDS in config.py).
QID = "workflow.slug_confirm"
CHOICE_PREFILL = "recommend_derived"   # RESULT_MAP → "prefill"
CHOICE_SKIP = "auto_accept"            # RESULT_MAP → "skip"


def _seed_axiom(approved_dir: Path, axiom_id: str, applies_to: list[str], scope="project"):
    """Write a minimal schema-shaped, graph-valid, approved axiom record."""
    rec = {
        "id": axiom_id,
        "statement": f"Test axiom {axiom_id}.",
        "scope": scope,
        "status": "approved",
        "confidence": 0.9,
        "evidence": [{"run": "20260529T000000-test", "event_id": "e-0001"}],
        "applies_to": applies_to,
        "boundary_conditions": ["does not apply to one-off cases"],
        "counterexamples": ["a modifier flag is allowed"],
        "conflicts_with": [],
        "supersedes": None,
        "source_run": "20260529T000000-test",
        "created_at": "2026-05-29T00:00:00Z",
        "approved_at": "2026-05-29T00:00:00Z",
    }
    approved_dir.mkdir(parents=True, exist_ok=True)
    (approved_dir / f"{axiom_id}.json").write_text(
        json.dumps(rec, indent=2) + "\n", encoding="utf-8"
    )


class _AxiomResolverBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        # Hermetic global store under a temp XDG_CONFIG_HOME.
        self.xdg = root / "xdg"
        (self.xdg / "z-harness").mkdir(parents=True, exist_ok=True)
        # Hermetic project store under a temp project root.
        self.proj = root / "proj"
        self.proj.mkdir(parents=True, exist_ok=True)
        self.approved = self.proj / ".z-harness" / "axioms" / "approved"

    def tearDown(self):
        self._tmp.cleanup()

    def _resolve(self, env_extra=None):
        env = {**os.environ}
        # Strip any inherited config-related env that could perturb the snapshot.
        for k in list(env):
            if k.startswith("Z_HARNESS_") or k == "XDG_CONFIG_HOME":
                env.pop(k, None)
        env["XDG_CONFIG_HOME"] = str(self.xdg)
        env["Z_HARNESS_PROJECT_ROOT"] = str(self.proj)
        if env_extra:
            env.update(env_extra)
        cp = subprocess.run(
            [sys.executable, SCRIPT, "resolve-question", QID],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)
        return json.loads(cp.stdout)


class TestNoMatchByteIdentical(_AxiomResolverBase):
    """no_match: no axiom answers the question → envelope byte-identical, `axiom` absent."""

    def test_no_axiom_key_when_no_match(self):
        # Empty store → no axiom participates.
        env = self._resolve()
        self.assertNotIn("axiom", env)
        self.assertEqual(env["source"], "none")
        self.assertEqual(env["result"], "ask")
        # Full structural baseline (R7): byte-identical to pre-axiom shape.
        self.assertEqual(
            set(env.keys()),
            {"result", "default", "source", "rule_id", "strength", "reason", "sources"},
        )

    def test_axiom_for_other_question_does_not_participate(self):
        # Axiom answers a DIFFERENT question → must not enter this resolution.
        _seed_axiom(self.approved, "ax-other001",
                    ["workflow.audit_to_amend:amend"])
        env = self._resolve()
        self.assertNotIn("axiom", env)
        self.assertEqual(env["source"], "none")


class TestGapFill(_AxiomResolverBase):
    """gap_fill: config default + memory silent → axiom fills the gap."""

    def test_gap_fill_sets_axiom_source_soft_and_result(self):
        _seed_axiom(self.approved, "ax-gap00001", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve()
        self.assertEqual(env["source"], "axiom")
        self.assertEqual(env["strength"], "soft")
        # RESULT_MAP[(slug_confirm, recommend_derived)] == "prefill"
        self.assertEqual(env["result"], "prefill")
        self.assertIn("axiom", env)
        self.assertEqual(env["axiom"]["id"], "ax-gap00001")
        self.assertIn("statement", env["axiom"])
        # gap-fill carries NO conflict key.
        self.assertNotIn("conflict", env["axiom"])


class TestDirectConflict(_AxiomResolverBase):
    """direct_conflict: config set a different value → higher layer wins, conflict surfaced."""

    def test_conflict_higher_layer_wins_value_surfaces_axiom(self):
        # Config explicitly sets auto_accept (→ result skip); axiom recommends
        # recommend_derived (→ prefill). Config (higher) must win the value.
        _seed_axiom(self.approved, "ax-conf0001", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve(env_extra={"Z_HARNESS_WORKFLOW_SLUG_CONFIRM": CHOICE_SKIP})
        self.assertEqual(env["source"], "axiom_conflict")
        # Higher layer (config=auto_accept) wins the value/result/strength.
        self.assertEqual(env["result"], "skip")
        self.assertEqual(env["strength"], "hard")
        self.assertIn("axiom", env)
        self.assertEqual(env["axiom"]["id"], "ax-conf0001")
        self.assertTrue(env["axiom"]["conflict"])


class TestAgree(_AxiomResolverBase):
    """agree: axiom value == resolved config value → config wins, axiom in sources only."""

    def test_agree_records_axiom_in_sources_no_nested_object(self):
        # Config sets recommend_derived; axiom also recommends recommend_derived.
        _seed_axiom(self.approved, "ax-agree001", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve(env_extra={"Z_HARNESS_WORKFLOW_SLUG_CONFIRM": CHOICE_PREFILL})
        # Config still wins: source unchanged, result unchanged.
        self.assertEqual(env["source"], "config")
        self.assertEqual(env["result"], "prefill")
        # NO nested axiom object on agree.
        self.assertNotIn("axiom", env)
        # Axiom IS recorded in sources.
        axiom_sources = [s for s in env["sources"] if s.get("kind") == "axiom"]
        self.assertEqual(len(axiom_sources), 1)
        self.assertEqual(axiom_sources[0]["id"], "ax-agree001")


class TestDisabled(_AxiomResolverBase):
    """disabled: axioms.enabled=false → no axiom participation."""

    def test_disabled_drops_axiom(self):
        _seed_axiom(self.approved, "ax-gap00001", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve(env_extra={"Z_HARNESS_AXIOMS_ENABLED": "false"})
        self.assertNotIn("axiom", env)
        self.assertEqual(env["source"], "none")


class TestChoiceMembershipDrop(_AxiomResolverBase):
    """choice_drop: axiom value not a legal choice → dropped (SPEC line 78)."""

    def test_illegal_choice_value_is_ignored(self):
        # "yes_please" is not in QUESTION_IDS[slug_confirm].choices.
        _seed_axiom(self.approved, "ax-bad00001", [f"{QID}:yes_please"])
        env = self._resolve()
        self.assertNotIn("axiom", env)
        self.assertEqual(env["source"], "none")


class TestDeterministicSelection(_AxiomResolverBase):
    """
    Tiebreak determinism: two approved axioms targeting the SAME question_id with
    DIFFERENT legal values → the one with the lexicographically-smallest id is
    always chosen, across repeated calls (R-stable).

    The gap-fill path (no config value set) is used so the resolver must pick ONE
    axiom to fill the gap; if selection were non-deterministic the chosen value/id
    would vary across runs.  The test seeds two axioms in alphabetically-reversed
    insertion order ("ax-zzz" before "ax-aaa") and asserts "ax-aaa" wins.
    """

    def test_lexicographically_smallest_id_wins_gap_fill(self):
        # Seed in reverse alpha order to prove insertion order doesn't decide.
        _seed_axiom(self.approved, "ax-zzz00001", [f"{QID}:{CHOICE_SKIP}"])
        _seed_axiom(self.approved, "ax-aaa00001", [f"{QID}:{CHOICE_PREFILL}"])

        # Resolve multiple times and collect chosen axiom ids.
        chosen_ids = set()
        chosen_values = set()
        for _ in range(5):
            env = self._resolve()
            # Both axioms target the same qid but with different values, so
            # source must be "axiom" (gap-fill) and exactly one axiom chosen.
            self.assertEqual(env["source"], "axiom",
                             msg="Expected gap-fill; got: " + repr(env))
            self.assertIn("axiom", env)
            chosen_ids.add(env["axiom"]["id"])
            chosen_values.add(env["result"])

        # Must be deterministic: only one distinct id across all five calls.
        self.assertEqual(len(chosen_ids), 1,
                         msg=f"Non-deterministic selection; saw ids: {chosen_ids}")

        # Must be the lex-smallest id.
        self.assertIn("ax-aaa00001", chosen_ids,
                      msg="Expected lex-smallest id 'ax-aaa00001' to win")

        # And therefore only one distinct result (since a fixed axiom → fixed value).
        self.assertEqual(len(chosen_values), 1,
                         msg=f"Non-deterministic result; saw results: {chosen_values}")


if __name__ == "__main__":
    unittest.main()
