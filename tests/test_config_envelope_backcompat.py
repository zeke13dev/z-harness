"""
Backward-compatibility tests for the resolve-question envelope (T013).

ENVELOPE CONSUMERS AUDIT
=========================

The following consumers read from the resolve-question envelope produced by
scripts/config.py. They are identified by grepping for jq .result / .default /
.source across skills/*, commands/*, scripts/*.

  Consumer                              Keys read      Branches on SOURCE
  ─────────────────────────────────────────────────────────────────────────────
  commands/z-plan.md                    result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  commands/z-fix.md                     result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  commands/z-uplift.md                  result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  commands/z-audit-plan.md              result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  commands/z-audit-plan-style.md        result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  commands/z-review-all.md              result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  skills/z-execute/SKILL.md             result         (no SOURCE branch;
                                                        only check-no-ask path)
  skills/z-map/SKILL.md                 result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  skills/z-brainstorm/SKILL.md          result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  skills/z-debug/SKILL.md               result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  skills/z-review-all/SKILL.md          result,        SOURCE == "conflict"
                                        default,       (UI note only)
                                        source
  scripts/lint-askuser.sh               (invokes       n/a
                                         resolve-q,
                                         does not
                                         parse JSON)

CONSUMER-COMPAT CONTRACT
========================

All consumers branch on $RESULT (ask / skip / prefill / halt), NOT on $SOURCE.
$SOURCE is only inspected via a literal `== "conflict"` guard, whose sole effect
is to add a UI annotation to an AskUserQuestion prompt. The new "axiom" and
"axiom_conflict" source values do NOT match that guard — so the guard is simply
a no-op and the question is presented without the conflict annotation. This is
correct behaviour: an axiom gap-fill or conflict is a different kind of hint
(see nested `axiom` key), and no existing consumer breaks.

No consumer reads the optional nested `axiom` key, so its presence or absence
is fully backward-compatible.

KNOWN SOURCE VALUES (as of scripts/config.py post-T012):
  "none"           — no layer answered the question
  "default"        — only the question's default value applies
  "config"         — config layer answered
  "memory"         — memory layer answered
  "conflict"       — config and memory disagree; higher layer wins
  "axiom"          — NEW (T012): axiom gap-fill (config at default, memory silent)
  "axiom_conflict" — NEW (T012): axiom recommends a different value than config

The full envelope shape (R7 invariant):
  Mandatory keys (always present, axiom-free path):
    result, default, source, rule_id, strength, reason, sources
  Optional nested object (only when axiom participates and does not merely agree):
    axiom: {id, statement[, conflict: true]}

Tests in this module assert (a) the no-axiom path produces an envelope with
NO `axiom` key and all legacy keys well-typed, and (b) the new source values
"axiom" and "axiom_conflict" are in the documented set and are produced on the
correct code paths (gap-fill and direct-conflict), confirming consumer compat.
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

# Question under test — mirrors QID / choices in test_config_axiom_resolver.py.
QID = "workflow.slug_confirm"
CHOICE_PREFILL = "recommend_derived"   # RESULT_MAP → "prefill"
CHOICE_SKIP = "auto_accept"            # RESULT_MAP → "skip"

# All source values the envelope may legitimately emit.
KNOWN_SOURCES = frozenset({"none", "default", "config", "memory", "conflict",
                            "axiom", "axiom_conflict"})

# Legacy mandatory keys — must be present in every envelope regardless of axiom.
LEGACY_KEYS = frozenset({"result", "default", "source", "rule_id", "strength",
                          "reason", "sources"})


def _seed_axiom(approved_dir: Path, axiom_id: str, applies_to: list) -> None:
    """Write a minimal schema-shaped, approved axiom record (mirrors T012 helper)."""
    rec = {
        "id": axiom_id,
        "statement": f"Test axiom {axiom_id}.",
        "scope": "project",
        "status": "approved",
        "confidence": 0.9,
        "evidence": [{"run": "20260529T000000-test", "event_id": "e-bc01"}],
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


class _EnvelopeBase(unittest.TestCase):
    """
    Hermetic base: temp XDG_CONFIG_HOME + temp project root.
    Never touches the real global/project store, metrics.jsonl, or KERNEL.md.
    Mirrors _AxiomResolverBase from test_config_axiom_resolver.py exactly.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.xdg = root / "xdg"
        (self.xdg / "z-harness").mkdir(parents=True, exist_ok=True)
        self.proj = root / "proj"
        self.proj.mkdir(parents=True, exist_ok=True)
        self.approved = self.proj / ".z-harness" / "axioms" / "approved"

    def tearDown(self):
        self._tmp.cleanup()

    def _resolve(self, env_extra=None):
        env = {**os.environ}
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


# ---------------------------------------------------------------------------
# (a) No-axiom path: envelope must have NO `axiom` key; all legacy keys present
# ---------------------------------------------------------------------------

class TestNoAxiomKeyAbsent(_EnvelopeBase):
    """
    Assertion (a): when NO axiom participates the envelope must:
      1. Not contain the `axiom` key (not null — completely absent).
      2. Contain all seven legacy mandatory keys with correct types.
      3. source value is in KNOWN_SOURCES (backward-compat guard).
    """

    def test_empty_store_no_axiom_key(self):
        """Empty axiom store → no-axiom path → `axiom` key absent."""
        env = self._resolve()
        # Primary invariant (R7): axiom key is ABSENT, not null.
        self.assertNotIn("axiom", env,
                         msg="axiom key must be absent (not null) on no-match path")

    def test_legacy_keys_all_present(self):
        """All seven legacy envelope keys must be present on no-axiom path."""
        env = self._resolve()
        missing = LEGACY_KEYS - env.keys()
        self.assertFalse(missing, msg=f"Legacy keys missing: {missing}")

    def test_legacy_key_types(self):
        """Legacy key types: result/default/source/rule_id/strength/reason=str, sources=list."""
        env = self._resolve()
        for key in ("result", "default", "source", "rule_id", "strength", "reason"):
            self.assertIsInstance(env[key], str,
                                  msg=f"env[{key!r}] must be str, got {type(env[key])}")
        self.assertIsInstance(env["sources"], list,
                              msg="env['sources'] must be list")

    def test_no_axiom_path_source_in_known_set(self):
        """source value on no-axiom path must be in the documented set."""
        env = self._resolve()
        self.assertIn(env["source"], KNOWN_SOURCES,
                      msg=f"Unexpected source value: {env['source']!r}")

    def test_axiom_for_different_question_no_participation(self):
        """Axiom targeting a different question → still no-axiom path for QID."""
        _seed_axiom(self.approved, "ax-bc-other01", ["workflow.audit_to_amend:amend"])
        env = self._resolve()
        self.assertNotIn("axiom", env,
                         msg="Axiom for a different qid must not produce axiom key")
        # Legacy shape still intact.
        self.assertEqual(LEGACY_KEYS, LEGACY_KEYS & env.keys())

    def test_no_axiom_path_result_and_default_are_strings(self):
        """result and default are non-null strings on no-axiom path (consumer compat)."""
        env = self._resolve()
        # Consumers do: RESULT="$(jq -r .result)" — must not be null/missing.
        self.assertIsNotNone(env.get("result"))
        self.assertIsNotNone(env.get("default"))
        self.assertIsInstance(env["result"], str)
        self.assertIsInstance(env["default"], str)

    def test_axiom_disabled_no_axiom_key(self):
        """axioms.enabled=false with a seeded axiom → still no axiom key."""
        _seed_axiom(self.approved, "ax-bc-dis001", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve(env_extra={"Z_HARNESS_AXIOMS_ENABLED": "false"})
        self.assertNotIn("axiom", env)
        missing = LEGACY_KEYS - env.keys()
        self.assertFalse(missing, msg=f"Legacy keys missing when disabled: {missing}")


# ---------------------------------------------------------------------------
# (b) New source values "axiom" / "axiom_conflict" are produced correctly
# ---------------------------------------------------------------------------

class TestNewSourceValues(_EnvelopeBase):
    """
    Assertion (b): the resolver emits source in KNOWN_SOURCES (which now includes
    "axiom" and "axiom_conflict"), and these values are produced on the correct
    code paths (gap-fill and direct-conflict).

    CONSUMER-COMPAT NOTE:
    All consumers inspect SOURCE only for `== "conflict"`. The new values
    "axiom" and "axiom_conflict" do NOT match that literal check, so no consumer
    alters behaviour — the UI conflict-annotation is simply suppressed (correct).
    The `result` and `default` fields remain strings on both new paths, so all
    consumer reads of jq .result and jq .default are safe.
    """

    def test_known_sources_contains_new_values(self):
        """KNOWN_SOURCES set must include 'axiom' and 'axiom_conflict'."""
        self.assertIn("axiom", KNOWN_SOURCES)
        self.assertIn("axiom_conflict", KNOWN_SOURCES)

    def test_gap_fill_emits_axiom_source(self):
        """Gap-fill path → source == "axiom" (new value in documented set)."""
        _seed_axiom(self.approved, "ax-bc-gap001", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve()
        self.assertEqual(env["source"], "axiom",
                         msg="Gap-fill axiom must emit source='axiom'")
        # source is in the known set.
        self.assertIn(env["source"], KNOWN_SOURCES)
        # All legacy keys still present.
        missing = LEGACY_KEYS - env.keys()
        self.assertFalse(missing, msg=f"Legacy keys missing on axiom path: {missing}")

    def test_gap_fill_result_and_default_are_strings(self):
        """On source='axiom' path: result and default are still plain strings."""
        _seed_axiom(self.approved, "ax-bc-gap002", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve()
        self.assertEqual(env["source"], "axiom")
        self.assertIsInstance(env["result"], str,
                              msg="result must remain str on axiom path")
        self.assertIsInstance(env["default"], str,
                              msg="default must remain str on axiom path")

    def test_gap_fill_has_nested_axiom_object(self):
        """Gap-fill path includes nested axiom object with id and statement."""
        _seed_axiom(self.approved, "ax-bc-gap003", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve()
        self.assertEqual(env["source"], "axiom")
        self.assertIn("axiom", env,
                      msg="Nested axiom object must be present on gap-fill path")
        self.assertIn("id", env["axiom"])
        self.assertIn("statement", env["axiom"])
        # No conflict key on gap-fill.
        self.assertNotIn("conflict", env["axiom"],
                         msg="conflict must be absent in nested axiom on gap-fill")

    def test_direct_conflict_emits_axiom_conflict_source(self):
        """Direct-conflict path → source == "axiom_conflict" (new value in documented set)."""
        _seed_axiom(self.approved, "ax-bc-con001", [f"{QID}:{CHOICE_PREFILL}"])
        # Config set a different value (CHOICE_SKIP) → conflict.
        env = self._resolve(env_extra={"Z_HARNESS_WORKFLOW_SLUG_CONFIRM": CHOICE_SKIP})
        self.assertEqual(env["source"], "axiom_conflict",
                         msg="Direct conflict must emit source='axiom_conflict'")
        self.assertIn(env["source"], KNOWN_SOURCES)
        # Legacy keys intact.
        missing = LEGACY_KEYS - env.keys()
        self.assertFalse(missing, msg=f"Legacy keys missing on axiom_conflict path: {missing}")

    def test_direct_conflict_result_and_default_are_strings(self):
        """On source='axiom_conflict' path: result and default are still plain strings."""
        _seed_axiom(self.approved, "ax-bc-con002", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve(env_extra={"Z_HARNESS_WORKFLOW_SLUG_CONFIRM": CHOICE_SKIP})
        self.assertEqual(env["source"], "axiom_conflict")
        self.assertIsInstance(env["result"], str)
        self.assertIsInstance(env["default"], str)

    def test_direct_conflict_has_nested_axiom_with_conflict_true(self):
        """Direct-conflict path includes nested axiom object with conflict=true."""
        _seed_axiom(self.approved, "ax-bc-con003", [f"{QID}:{CHOICE_PREFILL}"])
        env = self._resolve(env_extra={"Z_HARNESS_WORKFLOW_SLUG_CONFIRM": CHOICE_SKIP})
        self.assertEqual(env["source"], "axiom_conflict")
        self.assertIn("axiom", env)
        self.assertTrue(env["axiom"].get("conflict"),
                        msg="conflict must be true in nested axiom on conflict path")

    def test_consumer_source_conflict_guard_unaffected(self):
        """
        Consumer compat: source='axiom' and source='axiom_conflict' do NOT equal
        the literal string "conflict", so the consumer guard `$SOURCE == "conflict"`
        evaluates to false — no UI annotation is added. This is the intended behaviour.
        """
        _seed_axiom(self.approved, "ax-bc-compat01", [f"{QID}:{CHOICE_PREFILL}"])
        env_gap = self._resolve()
        self.assertEqual(env_gap["source"], "axiom")
        self.assertNotEqual(env_gap["source"], "conflict",
                            msg="'axiom' != 'conflict': consumer guard is safe no-op")

        _seed_axiom(self.approved, "ax-bc-compat02", [f"{QID}:{CHOICE_PREFILL}"])
        env_conf = self._resolve(
            env_extra={"Z_HARNESS_WORKFLOW_SLUG_CONFIRM": CHOICE_SKIP}
        )
        self.assertEqual(env_conf["source"], "axiom_conflict")
        self.assertNotEqual(env_conf["source"], "conflict",
                            msg="'axiom_conflict' != 'conflict': consumer guard is safe no-op")

    def test_all_emitted_sources_in_known_set(self):
        """
        Whatever source value is emitted on each path, it must be in KNOWN_SOURCES.
        Exercises: none, axiom, axiom_conflict paths in one test.
        """
        # none path (empty store)
        env_none = self._resolve()
        self.assertIn(env_none["source"], KNOWN_SOURCES,
                      msg=f"Unexpected source on none path: {env_none['source']!r}")

        # axiom path (gap-fill)
        _seed_axiom(self.approved, "ax-bc-all001", [f"{QID}:{CHOICE_PREFILL}"])
        env_axiom = self._resolve()
        self.assertIn(env_axiom["source"], KNOWN_SOURCES,
                      msg=f"Unexpected source on axiom path: {env_axiom['source']!r}")

        # axiom_conflict path
        env_conflict = self._resolve(
            env_extra={"Z_HARNESS_WORKFLOW_SLUG_CONFIRM": CHOICE_SKIP}
        )
        self.assertIn(env_conflict["source"], KNOWN_SOURCES,
                      msg=f"Unexpected source on axiom_conflict path: {env_conflict['source']!r}")


if __name__ == "__main__":
    unittest.main()
