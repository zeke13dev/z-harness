"""
Tests for scripts/export-common.py fragment-include expansion.

Wires the script's own ``--self-test`` into the pytest suite so CI actually
exercises it. Before this, ``cmd_self_test`` (added per the T007 review to cover
fence-skip / circular-include / missing-fragment / path-escape) passed only when
a human ran ``python3 scripts/export-common.py --self-test`` by hand — it was in
neither ``make test`` (pytest does not collect a ``--self-test`` CLI subcommand)
nor ``make test-sh`` (which loops shell scripts only), so a regression in fence
detection or path-escape guarding would have merged green.

Cases covered:
  self_test_subcommand_passes  — the bundled ``--self-test`` CLI exits 0 in the real repo
  fenced_marker_preserved      — a marker inside a ``` fence is NOT expanded (T007 BLOCKER-1)
  path_escape_rejected         — an include escaping repo_root raises ValueError (path-escape guard)
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "export-common.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("export_common", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ExportCommonSelfTest(unittest.TestCase):
    def test_self_test_subcommand_passes(self):
        """The bundled --self-test must exit 0 in the real repo (CI gate)."""
        result = subprocess.run(
            [sys.executable, _SCRIPT, "--self-test"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"export-common --self-test failed:\n{result.stdout}\n{result.stderr}",
        )

    def test_fenced_marker_preserved(self):
        """A whole-line include marker inside a fence is left verbatim —
        for backtick (incl. 4+) and tilde fences alike."""
        mod = _load_module()
        marker = "<!-- include: commands/_fragments/run-brief-finalize.md -->"
        for fence in ("```markdown", "````", "~~~"):
            close = "~~~" if fence == "~~~" else fence.rstrip("markdown")
            fenced = f"{fence}\n{marker}\n{close}\n"
            expanded = mod.expand_includes(fenced, _REPO_ROOT)
            self.assertIn(marker, expanded, msg=f"fence {fence!r} should preserve marker")
            self.assertNotIn("Run Brief finalize (shared fragment)", expanded)

    def test_path_escape_rejected(self):
        """An include path escaping repo_root must raise ValueError."""
        mod = _load_module()
        with self.assertRaises(ValueError):
            mod.expand_includes("<!-- include: ../../../etc/passwd -->\n", _REPO_ROOT)


if __name__ == "__main__":
    unittest.main()
