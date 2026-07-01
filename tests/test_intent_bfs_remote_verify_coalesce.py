"""tests/test_intent_bfs_remote_verify_coalesce.py

T005 — one coalesced remote-runner build per multi-task REMOTE_VERIFY BFS level.

skills/z-execute/SKILL.md is a Markdown orchestration spec, not executable code
(same testing constraint documented in tests/test_session_handoff.py's
TestResumeIntegration). We therefore combine two kinds of assertions:

  A) STRUCTURAL invariants on the SKILL.md text itself — the per-task
     remote-runner dispatch (Main-loop step 5's "REMOTE_VERIFY pre-dispatch")
     must be gated off (suppressed) when LEVEL_EXECUTE_ACTIVE=1, and exactly
     one coalesced remote-runner dispatch must exist at the BFS level-boundary
     seam, positioned after the level's done_set_hash checkpoint and before
     the intent_bfs_level_complete log-event, with a failure path that halts
     the whole level.

  B) FUNCTIONAL proof that the documented union pipeline turns N REMOTE_VERIFY
     tasks into exactly ONE unioned command. We extract the real
     grep | sed | sort -u | awk pipeline from SKILL.md (falling back to a
     faithful replication, commented with the source region, only if
     extraction is impractical) and run it via subprocess against a fixture
     "level TASKS.md" containing 3 distinct REMOTE_VERIFY-tagged task blocks,
     one of which itself contains an embedded `&&`.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "z-execute" / "SKILL.md"


def _read_skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Section A — structural invariants on SKILL.md
# ---------------------------------------------------------------------------


class TestPerTaskDispatchGatedOffInBFS(unittest.TestCase):
    """Main-loop step 5's per-task REMOTE_VERIFY dispatch must be suppressed
    when LEVEL_EXECUTE_ACTIVE=1 (the coalesced BFS path)."""

    def setUp(self):
        self.text = _read_skill_text()

    def test_remote_verify_pre_dispatch_heading_exists(self):
        self.assertIn("**REMOTE_VERIFY pre-dispatch.**", self.text)

    def test_per_task_dispatch_is_wrapped_in_level_execute_active_guard(self):
        # Anchor on the "REMOTE_VERIFY pre-dispatch" heading and take the
        # window up to the next top-level heading/section marker, then verify
        # the Agent(subagent_type="remote-runner", ...) call inside that
        # window sits between an `if [ "${LEVEL_EXECUTE_ACTIVE:-0}" -eq 0 ]`
        # open and its matching `fi`.
        heading_idx = self.text.index("**REMOTE_VERIFY pre-dispatch.**")
        window = self.text[heading_idx:heading_idx + 4000]

        guard_open_match = re.search(
            r'if \[ "\$\{LEVEL_EXECUTE_ACTIVE:-0\}" -eq 0 \]; then', window
        )
        self.assertIsNotNone(
            guard_open_match,
            "expected an `if [ \"${LEVEL_EXECUTE_ACTIVE:-0}\" -eq 0 ]; then` "
            "guard following the REMOTE_VERIFY pre-dispatch heading",
        )

        # The matching `fi` closing this specific guard is commented to name
        # LEVEL_EXECUTE_ACTIVE explicitly (see SKILL.md ~line 2176) so we can
        # anchor on that comment rather than the first bare `fi` (which could
        # belong to a nested/unrelated block).
        fi_match = re.search(
            r"fi\s+# LEVEL_EXECUTE_ACTIVE", window[guard_open_match.end():]
        )
        self.assertIsNotNone(
            fi_match,
            "expected the guard to close with `fi   # LEVEL_EXECUTE_ACTIVE ...`",
        )

        between = window[
            guard_open_match.end():guard_open_match.end() + fi_match.start()
        ]
        self.assertIn(
            'subagent_type="remote-runner"',
            between,
            "the per-task remote-runner Agent() call must be inside the "
            "LEVEL_EXECUTE_ACTIVE==0 guard so it is suppressed under the "
            "coalesced BFS path",
        )

    def test_coalesced_path_suppression_prose_present(self):
        # The spec must explicitly say the per-task dispatch is suppressed
        # when LEVEL_EXECUTE_ACTIVE=1 (not just implicitly via the guard).
        self.assertIn(
            "Coalesced-path suppression (INTENT BFS)", self.text
        )
        idx = self.text.index("Coalesced-path suppression (INTENT BFS)")
        para = self.text[idx:idx + 800]
        self.assertIn("LEVEL_EXECUTE_ACTIVE=1", para)
        self.assertIn("SUPPRESSED", para)


class TestExactlyOneCoalescedDispatchAtLevelBoundary(unittest.TestCase):
    """Exactly one coalesced remote-runner dispatch exists at the BFS
    level-boundary seam, positioned after the level done_set_hash checkpoint
    and before intent_bfs_level_complete, with a halt-on-failure branch."""

    def setUp(self):
        self.text = _read_skill_text()

    def test_coalesced_region_heading_exists_exactly_once(self):
        # The phrase appears twice in SKILL.md: once as the actual seam
        # comment heading (`# ── Coalesced remote build ... ────`), and once
        # as a cross-reference inside the "Coalesced-path suppression" prose
        # ("see ... below"). Only the comment-heading form marks the seam
        # itself, so match specifically on that form.
        heading_occurrences = len(
            re.findall(
                r"#\s*──\s*Coalesced remote build \(INTENT BFS level boundary\)",
                self.text,
            )
        )
        self.assertEqual(
            heading_occurrences,
            1,
            "expected exactly one 'Coalesced remote build (INTENT BFS level "
            "boundary)' seam comment-heading in SKILL.md",
        )

    def test_region_bounds_and_ordering(self):
        # Locate the three anchors that define seam ordering:
        #   1. Level-boundary done_set_hash checkpoint write (LEVEL_STATE_FILE)
        #   2. Coalesced remote build region
        #   3. intent_bfs_level_complete log-event
        done_hash_idx = self.text.index(
            'printf \'%d %s\\n\' "$CURRENT_LEVEL" "$LEVEL_DONE_HASH" > "$LEVEL_STATE_FILE"'
        )
        coalesce_idx = self.text.index(
            "Coalesced remote build (INTENT BFS level boundary)"
        )
        complete_event_idx = self.text.index(
            '"orchestration" intent_bfs_level_complete'
        )

        self.assertLess(
            done_hash_idx,
            coalesce_idx,
            "coalesced remote build region must come AFTER the level "
            "done_set_hash checkpoint",
        )
        self.assertLess(
            coalesce_idx,
            complete_event_idx,
            "coalesced remote build region must come BEFORE the "
            "intent_bfs_level_complete log-event",
        )

        # Extract just the coalesced-build region text for the sub-assertions
        # below (bounded by the two anchors we just ordered against).
        self.region = self.text[coalesce_idx:complete_event_idx]

    def test_exactly_one_remote_runner_dispatch_in_region(self):
        self.test_region_bounds_and_ordering()
        dispatch_count = self.region.count('subagent_type="remote-runner"')
        self.assertEqual(
            dispatch_count,
            1,
            "the coalesced BFS level-boundary seam must dispatch exactly "
            "ONE remote-runner Agent() call, not one per task",
        )

    def test_failure_path_halts_the_level_before_complete_event(self):
        self.test_region_bounds_and_ordering()
        region = self.region

        # Non-zero exit branch must exist.
        self.assertIn('LEVEL_REMOTE_EXIT_CODE:-0}" -ne 0', region)

        # The halt branch must set FINALIZE_STATUS=aborted, deregister with
        # status aborted, and exit 1 — all strictly inside the region (i.e.
        # before intent_bfs_level_complete, which we already proved is after
        # the region boundary above).
        halt_idx = region.index('LEVEL_REMOTE_EXIT_CODE:-0}" -ne 0')
        halt_branch = region[halt_idx:]
        self.assertIn("FINALIZE_STATUS=aborted", halt_branch)
        self.assertIn('--status aborted', halt_branch)
        self.assertIn("exit 1", halt_branch)

    def test_union_command_construction_present_in_region(self):
        self.test_region_bounds_and_ordering()
        region = self.region
        self.assertIn("LEVEL_VERIFY_UNION", region)
        self.assertIn("sort -u", region)
        # The join must use a literal " && " separator (not corrupt embedded &&).
        self.assertIn('printf " && "', region)


# ---------------------------------------------------------------------------
# Section B — functional proof: N REMOTE_VERIFY tasks -> ONE unioned command
# ---------------------------------------------------------------------------


def _extract_union_pipeline() -> tuple[str, str]:
    """Extract the two documented shell fragments (grep|sed|sort -u, and the
    awk union-join) from SKILL.md verbatim. Returns (extract_cmd, union_cmd)
    as shell command *templates* with a `{FILE}` placeholder for the level
    TASKS.md path.

    Falls back to a faithful replication (commented with the SKILL.md source
    region) if extraction proves brittle, per the task instructions.
    """
    text = _read_skill_text()

    # Locate the two assignment lines by their unique variable-name prefixes,
    # then grab everything between the `$(` that opens the command
    # substitution and the closing `)"` that ends the assignment (the body
    # spans a `\`-continued line, so DOTALL is required).
    extract_start = text.find('LEVEL_REMOTE_VERIFY_CMDS="$(')
    union_start = text.find('LEVEL_VERIFY_UNION="$(')

    def _extract_body(start_idx: int, var_prefix: str) -> str | None:
        if start_idx == -1:
            return None
        open_idx = start_idx + len(var_prefix)
        end_idx = text.find(')"', open_idx)
        if end_idx == -1:
            return None
        body = text[open_idx:end_idx]
        # Collapse the documented line-continuation (`\` + newline + leading
        # whitespace) back into a single-line pipeline, verbatim otherwise.
        return re.sub(r"\\\n\s*", " ", body).strip()

    extract_body = _extract_body(extract_start, 'LEVEL_REMOTE_VERIFY_CMDS="$(')
    union_body = _extract_body(union_start, 'LEVEL_VERIFY_UNION="$(')

    if extract_body and union_body:
        # extract_body looks like:
        #   grep -h '^\*\*REMOTE_VERIFY:\*\*' "$LEVEL_TASKS_FILE" 2>/dev/null | sed '...' | sort -u
        # Swap the $LEVEL_TASKS_FILE reference for the {FILE} placeholder so
        # the caller can bind it to the fixture path.
        extract_cmd = extract_body.replace('"$LEVEL_TASKS_FILE"', "{FILE}")
        # union_body looks like:
        #   printf '%s\n' "$LEVEL_REMOTE_VERIFY_CMDS" | awk '...'
        # We only need the trailing `awk '...'` half — the printf half is
        # replaced by the caller piping extract_cmd's stdout directly in.
        awk_idx = union_body.find("| awk ")
        if awk_idx != -1 and "$LEVEL_TASKS_FILE" not in extract_cmd:
            union_cmd = union_body[awk_idx + 2:]  # drop leading "| "
            return extract_cmd, union_cmd

    # Fallback: faithful replication of the exact lines documented at
    # skills/z-execute/SKILL.md ~lines 1048-1058 ("Coalesced remote build
    # (INTENT BFS level boundary)" region). Kept byte-for-byte identical to
    # the spec text so a spec edit that changes behavior (not just
    # reformats) will require updating this fallback too.
    extract_cmd = (
        "grep -h '^\\*\\*REMOTE_VERIFY:\\*\\*' {FILE} 2>/dev/null "
        "| sed 's/^\\*\\*REMOTE_VERIFY:\\*\\* *//' | sort -u"
    )
    union_cmd = "awk 'NR>1{printf \" && \"} {printf \"%s\", $0} END{if(NR)print \"\"}'"
    return extract_cmd, union_cmd


class TestUnionPipelineFunctional(unittest.TestCase):
    """Runs the documented grep/sed/sort/awk pipeline against a fixture level
    TASKS.md with 3 REMOTE_VERIFY-tagged tasks and proves the result is ONE
    unioned command covering every task, with embedded && preserved."""

    def setUp(self):
        self.extract_cmd, self.union_cmd = _extract_union_pipeline()

    def _run_pipeline(self, fixture_path: Path) -> str:
        full_cmd = f"{self.extract_cmd.format(FILE=str(fixture_path))} | {self.union_cmd}"
        result = subprocess.run(
            ["bash", "-c", full_cmd],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"union pipeline failed: stderr={result.stderr!r}",
        )
        return result.stdout.strip()

    def _write_fixture(self, tmp_path: Path) -> Path:
        fixture = tmp_path / "level-1-TASKS.md"
        fixture.write_text(
            "## T101 — build crate a `[ ]`\n"
            "**Files:** crates/a/\n"
            "**REMOTE_VERIFY:** cargo build -p a && cargo test -p a\n"
            "**Acceptance:** builds\n\n"
            "## T102 — build crate b `[ ]`\n"
            "**Files:** crates/b/\n"
            "**REMOTE_VERIFY:** cargo test -p b\n"
            "**Acceptance:** builds\n\n"
            "## T103 — build crate c `[ ]`\n"
            "**Files:** crates/c/\n"
            "**REMOTE_VERIFY:** cargo check -p c\n"
            "**Acceptance:** builds\n",
            encoding="utf-8",
        )
        return fixture

    def test_union_yields_exactly_one_string(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._write_fixture(Path(tmp))
            union = self._run_pipeline(fixture)
            # A single line, non-empty — exactly ONE unioned command.
            self.assertNotIn("\n", union)
            self.assertTrue(union)

    def test_union_contains_every_task_command(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._write_fixture(Path(tmp))
            union = self._run_pipeline(fixture)
            self.assertIn("cargo build -p a", union)
            self.assertIn("cargo test -p a", union)
            self.assertIn("cargo test -p b", union)
            self.assertIn("cargo check -p c", union)

    def test_embedded_ampersand_ampersand_preserved_verbatim(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._write_fixture(Path(tmp))
            union = self._run_pipeline(fixture)
            # T101's own "cargo build -p a && cargo test -p a" must survive
            # intact (not double-joined, not truncated at the embedded &&).
            self.assertIn(
                "cargo build -p a && cargo test -p a",
                union,
                "embedded && within a single task's REMOTE_VERIFY command "
                "must be preserved verbatim by the join",
            )

    def test_dispatch_count_is_one_not_n(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._write_fixture(Path(tmp))

            # N = number of distinct REMOTE_VERIFY lines contributed by the
            # fixture's tasks.
            extract_only = self.extract_cmd.format(FILE=str(fixture))
            extract_result = subprocess.run(
                ["bash", "-c", extract_only],
                capture_output=True,
                text=True,
                timeout=10,
            )
            n_tasks = len(
                [
                    line
                    for line in extract_result.stdout.splitlines()
                    if line.strip()
                ]
            )
            self.assertEqual(n_tasks, 3, "fixture must contribute 3 distinct commands")

            union = self._run_pipeline(fixture)
            dispatch_count = len([line for line in union.splitlines() if line.strip()])
            self.assertEqual(
                dispatch_count,
                1,
                f"expected 1 dispatched command covering all {n_tasks} tasks, "
                f"got {dispatch_count}",
            )
            self.assertNotEqual(dispatch_count, n_tasks)

    def test_sort_u_dedupes_identical_remote_verify_lines(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "level-dup-TASKS.md"
            fixture.write_text(
                "## T201 — a `[ ]`\n"
                "**REMOTE_VERIFY:** cargo test -p shared\n\n"
                "## T202 — b `[ ]`\n"
                "**REMOTE_VERIFY:** cargo test -p shared\n",
                encoding="utf-8",
            )
            union = self._run_pipeline(fixture)
            # sort -u must collapse the duplicate before the union join, so
            # the command should appear only once in the result.
            self.assertEqual(union.count("cargo test -p shared"), 1)


if __name__ == "__main__":
    unittest.main()
