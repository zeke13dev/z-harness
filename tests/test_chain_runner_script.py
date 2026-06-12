"""
tests/test_chain_runner_script.py — Unit tests for scripts/chain-runner.sh IN
ISOLATION (T003 acceptance: "Unit-tested in isolation").

Unlike test_chain_runner_characterization.py (which pins the documented
ALGORITHM via inline re-implementation), this suite invokes the real
chain-runner.sh binary's subcommands as subprocesses and asserts their output
matches the four pinned byte-parity properties PLUS the two T003-specific
contracts:
  - `steps <preset>` emits `name:yield_after` per line; yield_after=true only for
    plan / implement-all, false otherwise (m1).
  - the state-file path is a PARAMETER (m3): the same runner writes overnight's
    `overnight-state.json` and an arbitrary attend state file with no hardcoded
    constant, and flock-guarded state-write never clobbers a good file with
    invalid JSON.

These run on every CI image (no bats dependency).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RUNNER = _REPO_ROOT / "scripts" / "chain-runner.sh"


def _run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_RUNNER), *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# 1. steps <preset> — ordering + yield_after format (property 1 + m1)
# ---------------------------------------------------------------------------

# (step, yield_after) golden — yield_after true only for plan / implement-all.
_PRESET_STEPS: dict[str, list[tuple[str, str]]] = {
    "full-build": [
        ("plan", "true"), ("test", "false"),
        ("implement-all", "true"), ("review-all", "false"),
    ],
    "research-build": [
        ("research", "false"), ("plan", "true"), ("test", "false"),
        ("implement-all", "true"), ("review-all", "false"),
    ],
    "quick-build": [("plan", "true"), ("implement-all", "true")],
    "attend-full": [
        ("plan", "true"), ("audit", "false"), ("test", "false"),
        ("implement-all", "true"), ("review-all", "false"),
    ],
}


class TestStepsSubcommand:
    @pytest.mark.parametrize("preset,expected", list(_PRESET_STEPS.items()))
    def test_steps_emit_name_yield_after_per_line(
        self, preset: str, expected: list[tuple[str, str]]
    ) -> None:
        proc = _run("steps", preset)
        assert proc.returncode == 0, proc.stderr
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        parsed = [tuple(ln.split(":", 1)) for ln in lines]
        assert parsed == expected

    def test_steps_ordering_matches_characterization_presets(self) -> None:
        """Step ORDER (names only) is byte-identical to the pinned characterization presets."""
        golden = {
            "full-build": ["plan", "test", "implement-all", "review-all"],
            "research-build": ["research", "plan", "test", "implement-all", "review-all"],
            "quick-build": ["plan", "implement-all"],
            "attend-full": ["plan", "audit", "test", "implement-all", "review-all"],
        }
        for preset, expected_steps in golden.items():
            proc = _run("steps", preset)
            names = [ln.split(":", 1)[0] for ln in proc.stdout.splitlines() if ln.strip()]
            assert names == expected_steps, preset

    def test_yield_after_true_only_for_plan_and_implement_all(self) -> None:
        proc = _run("steps", "attend-full")
        flags = dict(ln.split(":", 1) for ln in proc.stdout.splitlines() if ln.strip())
        assert flags["plan"] == "true"
        assert flags["implement-all"] == "true"
        assert flags["audit"] == "false"
        assert flags["test"] == "false"
        assert flags["review-all"] == "false"

    def test_unknown_preset_exits_2_no_output(self) -> None:
        proc = _run("steps", "no-such-preset")
        assert proc.returncode == 2
        assert proc.stdout.strip() == ""

    def test_attend_full_is_distinct_from_full_build(self) -> None:
        """attend-full has an audit step between plan and test; full-build does not."""
        af = [ln.split(":", 1)[0] for ln in _run("steps", "attend-full").stdout.splitlines() if ln.strip()]
        fb = [ln.split(":", 1)[0] for ln in _run("steps", "full-build").stdout.splitlines() if ln.strip()]
        assert "audit" in af and "audit" not in fb
        assert af.index("plan") < af.index("audit") < af.index("test")


# ---------------------------------------------------------------------------
# 2. state-init / state-read — shape (property 2) + path-is-a-parameter (m3)
# ---------------------------------------------------------------------------

_EXPECTED_TOP_KEYS = {
    "chain", "preset_used", "started_at", "ended_at", "status",
    "head_sha_at_start", "z_harness_version", "git_diff_stat_at_end", "step_runs",
}
_EXPECTED_SR_KEYS = {
    "step", "position", "run_id", "status", "head_sha_before", "head_sha_after",
    "started_at", "ended_at", "wall_ms", "terminal_event_kind",
    "artifact_paths", "exit_event", "error_event",
}


class TestStateInitShape:
    def test_state_init_writes_documented_shape(self, tmp_path: Path) -> None:
        sf = tmp_path / "run-q" / "overnight-state.json"
        proc = _run("state-init", str(sf), "plan,implement-all", "quick-build",
                    "2025-01-01T00:00:00Z", "abc1234", "v9")
        assert proc.returncode == 0, proc.stderr
        state = json.loads(sf.read_text())
        assert set(state.keys()) == _EXPECTED_TOP_KEYS
        assert state["chain"] == ["plan", "implement-all"]
        assert state["preset_used"] == "quick-build"
        assert state["status"] == "running"
        assert state["ended_at"] is None
        assert state["git_diff_stat_at_end"] is None
        assert len(state["step_runs"]) == 2
        for i, sr in enumerate(state["step_runs"]):
            assert set(sr.keys()) == _EXPECTED_SR_KEYS
            assert sr["status"] == "queued"
            assert sr["position"] == i
            assert sr["artifact_paths"] == []
            assert sr["exit_event"] is None and sr["error_event"] is None

    def test_preset_null_string_becomes_json_null(self, tmp_path: Path) -> None:
        sf = tmp_path / "s.json"
        _run("state-init", str(sf), "plan", "null", "t", "h", "v")
        assert json.loads(sf.read_text())["preset_used"] is None

    def test_state_file_path_is_a_parameter_not_hardcoded(self, tmp_path: Path) -> None:
        """m3: the SAME runner writes overnight's filename AND an attend-scoped one."""
        overnight = tmp_path / "ov" / "overnight-state.json"
        attend = tmp_path / "at" / "attend-state.json"
        _run("state-init", str(overnight), "plan,review-all", "full-build", "t", "h", "v")
        _run("state-init", str(attend), "plan,audit,implement-all", "attend-full", "t", "h", "v")
        assert overnight.exists() and attend.exists()
        # Distinct content keyed on the parameter, no shared hardcoded path.
        assert json.loads(overnight.read_text())["chain"] == ["plan", "review-all"]
        assert json.loads(attend.read_text())["chain"] == ["plan", "audit", "implement-all"]

    def test_state_read_missing_exits_3(self, tmp_path: Path) -> None:
        proc = _run("state-read", str(tmp_path / "nope.json"))
        assert proc.returncode == 3

    def test_state_read_roundtrips_init(self, tmp_path: Path) -> None:
        sf = tmp_path / "s.json"
        _run("state-init", str(sf), "plan", "quick-build", "t", "h", "v")
        proc = _run("state-read", str(sf))
        assert proc.returncode == 0
        assert json.loads(proc.stdout)["chain"] == ["plan"]


# ---------------------------------------------------------------------------
# 3. cursor — first non-complete (property 3)
# ---------------------------------------------------------------------------

class TestCursorSubcommand:
    def _init(self, tmp_path: Path, chain: str) -> Path:
        sf = tmp_path / "s.json"
        _run("state-init", str(sf), chain, "null", "t", "h", "v")
        return sf

    def _set_statuses(self, sf: Path, statuses: list[str]) -> None:
        state = json.loads(sf.read_text())
        for sr, s in zip(state["step_runs"], statuses):
            sr["status"] = s
        _run("state-write", str(sf), json.dumps(state))

    def test_all_queued_cursor_0(self, tmp_path: Path) -> None:
        sf = self._init(tmp_path, "plan,test,implement-all")
        assert _run("cursor", str(sf)).stdout.strip() == "0"

    def test_skips_complete_steps(self, tmp_path: Path) -> None:
        sf = self._init(tmp_path, "plan,test,implement-all")
        self._set_statuses(sf, ["complete", "complete", "queued"])
        assert _run("cursor", str(sf)).stdout.strip() == "2"

    def test_all_complete_returns_length(self, tmp_path: Path) -> None:
        sf = self._init(tmp_path, "plan,test")
        self._set_statuses(sf, ["complete", "complete"])
        assert _run("cursor", str(sf)).stdout.strip() == "2"

    def test_halt_counts_as_non_complete(self, tmp_path: Path) -> None:
        sf = self._init(tmp_path, "plan,test,implement-all")
        self._set_statuses(sf, ["complete", "halt", "queued"])
        assert _run("cursor", str(sf)).stdout.strip() == "1"

    def test_cursor_missing_state_exits_3(self, tmp_path: Path) -> None:
        assert _run("cursor", str(tmp_path / "nope.json")).returncode == 3


# ---------------------------------------------------------------------------
# 4. new-run-id — C14 set-difference (property 4)
# ---------------------------------------------------------------------------

class TestNewRunIdSubcommand:
    def _archive(self, tmp_path: Path, names: list[str]) -> Path:
        ar = tmp_path / "archive"
        ar.mkdir(exist_ok=True)
        for n in names:
            (ar / n).mkdir(exist_ok=True)
        return ar

    def test_single_new_dir_unambiguous(self, tmp_path: Path) -> None:
        ar = self._archive(tmp_path, [
            "20250101T000000Z-plan-feat", "20250101T000100Z-implement-all-feat",
        ])
        proc = _run("new-run-id", "run", "-", str(ar),
                    stdin="20250101T000000Z-plan-feat\n")
        out = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        assert out == ["20250101T000100Z-implement-all-feat"]

    def test_no_new_dirs_empty(self, tmp_path: Path) -> None:
        ar = self._archive(tmp_path, ["20250101T000000Z-plan-feat"])
        proc = _run("new-run-id", "run", "-", str(ar),
                    stdin="20250101T000000Z-plan-feat\n")
        assert [ln for ln in proc.stdout.splitlines() if ln.strip()] == []

    def test_multiple_new_dirs_all_returned(self, tmp_path: Path) -> None:
        ar = self._archive(tmp_path, [
            "20250101T000000Z-plan-feat",
            "20250101T000100Z-implement-all-feat",
            "20250101T000101Z-implement-all-feat-2",
        ])
        proc = _run("new-run-id", "run", "-", str(ar),
                    stdin="20250101T000000Z-plan-feat\n")
        out = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        assert len(out) == 2

    def test_overnight_dirs_excluded_both_sides(self, tmp_path: Path) -> None:
        ar = self._archive(tmp_path, [
            "20250101T000000Z-plan-feat",
            "20250101T000050Z-overnight-feat",   # excluded from after
            "20250101T000100Z-implement-all-feat",
        ])
        proc = _run(
            "new-run-id", "run", "-", str(ar),
            # before-set carries an overnight dir too — must be excluded.
            stdin="20250101T000000Z-plan-feat\n20250101T000000Z-overnight-old\n",
        )
        out = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        assert out == ["20250101T000100Z-implement-all-feat"]

    def test_output_is_sorted(self, tmp_path: Path) -> None:
        ar = self._archive(tmp_path, ["z-run", "a-run", "m-run"])
        proc = _run("new-run-id", "run", "-", str(ar), stdin="")
        out = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        assert out == sorted(out)

    def test_before_set_from_file(self, tmp_path: Path) -> None:
        ar = self._archive(tmp_path, ["d1", "d2"])
        before = tmp_path / "before.txt"
        before.write_text("d1\n")
        proc = _run("new-run-id", "run", str(before), str(ar))
        out = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        assert out == ["d2"]


# ---------------------------------------------------------------------------
# 5. Policy isolation + flock-guarded write robustness (Invariant 2 / m3)
# ---------------------------------------------------------------------------

class TestRunnerHygiene:
    def test_invalid_json_write_does_not_clobber_good_state(self, tmp_path: Path) -> None:
        sf = tmp_path / "s.json"
        _run("state-init", str(sf), "plan,test", "null", "t", "h", "v")
        good = sf.read_text()
        proc = _run("state-write", str(sf), "{not valid json")
        assert proc.returncode != 0
        assert sf.read_text() == good  # untouched

    def test_no_skill_or_gate_policy_tokens_in_runner(self) -> None:
        """Invariant 2: chain-runner.sh holds NO Skill dispatch / gate policy.

        Scans CODE only — comment lines (which legitimately NAME the policy that
        lives elsewhere, to assert it is absent here) are stripped first.
        """
        code = "\n".join(
            ln for ln in _RUNNER.read_text().splitlines()
            if not ln.lstrip().startswith("#")
        )
        for forbidden in ("Skill(", "AskUserQuestion", "Z_HARNESS_NO_ASK",
                          "AUTODECIDE", "resolve-question", "resolve-halt-category",
                          "halt_category"):
            assert forbidden not in code, f"runner must not reference {forbidden!r}"

    def test_unknown_subcommand_exits_usage(self, tmp_path: Path) -> None:
        proc = _run("frobnicate")
        assert proc.returncode == 64


# ---------------------------------------------------------------------------
# 6. state-write STDIN path — unbounded payload, no OS argv/env ceiling
# ---------------------------------------------------------------------------
#
# Overnight states can grow large (many step_runs with long artifact_paths,
# exit_event / error_event blobs, repeated metadata). The original state-write
# passed the entire JSON as argv $2, which a large run could push past the OS
# ARG_MAX / env ceiling — a silent parity violation (SPEC Invariant 3). The
# stdin form (json arg == "-" or omitted) routes the payload through stdin, which
# has no such ceiling. These tests prove the unbounded path round-trips intact
# AND that the original argv form still works (backward compatibility).

class TestStateWriteStdin:
    def _big_state(self, n_steps: int = 200, path_len: int = 4096) -> dict:
        """A state whose serialized size comfortably exceeds typical argv slack.

        n_steps=200 step_runs, each with a long artifact_path, yields hundreds of
        KB of JSON — well past the few-KB scale at which the argv ceiling bites on
        constrained shells, and large enough to fail loudly if the bytes were ever
        forced back through argv/env.
        """
        return {
            "chain": ["implement-all"],
            "preset_used": "quick-build",
            "started_at": "2025-01-01T00:00:00Z",
            "ended_at": None,
            "status": "running",
            "head_sha_at_start": "abc1234",
            "z_harness_version": "v9",
            "git_diff_stat_at_end": None,
            "step_runs": [
                {
                    "step": "implement-all",
                    "position": i,
                    "run_id": f"run-{i}",
                    "status": "complete",
                    "head_sha_before": "a" * 40,
                    "head_sha_after": "b" * 40,
                    "started_at": "2025-01-01T00:00:00Z",
                    "ended_at": "2025-01-01T01:00:00Z",
                    "wall_ms": 3600000,
                    "terminal_event_kind": "implement_end",
                    "artifact_paths": [
                        "/very/long/artifact/path/" + ("seg/" * (path_len // 4)) + f"f{i}.md"
                    ],
                    "exit_event": {"kind": "implement_end", "payload": "z" * path_len},
                    "error_event": None,
                }
                for i in range(n_steps)
            ],
        }

    def test_large_state_roundtrips_via_stdin_dash(self, tmp_path: Path) -> None:
        sf = tmp_path / "overnight-state.json"
        big = self._big_state()
        payload = json.dumps(big)
        # Sanity: the payload is genuinely large (hundreds of KB), the regime
        # where the old argv path was at risk.
        assert len(payload) > 200_000, len(payload)

        proc = _run("state-write", str(sf), "-", stdin=payload)
        assert proc.returncode == 0, proc.stderr
        # Read it back byte-for-byte at the structural level.
        written = json.loads(sf.read_text())
        assert written == big
        assert len(written["step_runs"]) == 200
        # A specific deep field survived intact (no truncation).
        assert written["step_runs"][199]["exit_event"]["payload"] == "z" * 4096

    def test_large_state_roundtrips_via_stdin_omitted(self, tmp_path: Path) -> None:
        """Omitting the json arg entirely is equivalent to passing '-' (stdin)."""
        sf = tmp_path / "overnight-state.json"
        big = self._big_state(n_steps=100)
        payload = json.dumps(big)
        proc = _run("state-write", str(sf), stdin=payload)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(sf.read_text()) == big

    def test_stdin_invalid_json_does_not_clobber_good_state(self, tmp_path: Path) -> None:
        sf = tmp_path / "s.json"
        _run("state-init", str(sf), "plan,test", "null", "t", "h", "v")
        good = sf.read_text()
        proc = _run("state-write", str(sf), "-", stdin="{not valid json")
        assert proc.returncode != 0
        assert sf.read_text() == good  # untouched

    def test_argv_and_stdin_paths_produce_identical_files(self, tmp_path: Path) -> None:
        """Backward-compat: the original argv form and the new stdin form write
        byte-identical state files for the same (small) payload."""
        state = {"chain": ["plan"], "step_runs": [], "status": "running"}
        payload = json.dumps(state)
        sf_argv = tmp_path / "argv.json"
        sf_stdin = tmp_path / "stdin.json"
        assert _run("state-write", str(sf_argv), payload).returncode == 0
        assert _run("state-write", str(sf_stdin), "-", stdin=payload).returncode == 0
        assert sf_argv.read_text() == sf_stdin.read_text()
