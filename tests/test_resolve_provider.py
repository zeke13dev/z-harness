"""
Tests for scripts/resolve-provider.py

Invokes the script as a subprocess so we exercise the real exit-code contract.
Three cases:
  1. happy_path       — valid config, two providers, 3 roles → correct JSON output
  2. collision        — consultant_primary == consultant_secondary → nonzero exit
  3. malformed_args   — args_template is a string, not list[str] → nonzero + message
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = str(Path(__file__).parent.parent / "scripts" / "resolve-provider.py")

# resolve-provider.py validates that a provider's `command` is on PATH
# (shutil.which) before returning it. The real provider CLIs (gemini, codex,
# claude, ...) are not installed in CI, so we stage no-op stub executables on a
# temp PATH for the duration of the module. This replicates a dev box where the
# CLIs are present, exercising the resolution logic without the real binaries.
_STUB_BIN = None


def setUpModule() -> None:
    global _STUB_BIN
    _STUB_BIN = tempfile.mkdtemp(prefix="zh-stub-bin-")
    for name in ("gemini", "codex", "claude", "agy", "cursor"):
        p = os.path.join(_STUB_BIN, name)
        with open(p, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)


def tearDownModule() -> None:
    if _STUB_BIN:
        shutil.rmtree(_STUB_BIN, ignore_errors=True)

# A minimal valid provider entry shape.
def _make_provider(command: str, model_label: str) -> dict:
    return {
        "kind": "cli",
        "command": command,
        "args_template": ["--model", model_label],
        "stdin": True,
        "timeout_s": 60,
        "model_label": model_label,
    }


def _write_config(path: str, providers: dict, roles: dict) -> None:
    data = {"version": 1, "providers": providers, "roles": roles}
    with open(path, "w") as fh:
        json.dump(data, fh)


def _run(role: str, config_path: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "Z_HARNESS_REPO_PROVIDERS": config_path}
    if _STUB_BIN:
        env["PATH"] = _STUB_BIN + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [sys.executable, SCRIPT, role],
        env=env,
        capture_output=True,
        text=True,
    )


class TestResolveProvider(unittest.TestCase):

    def test_happy_path(self):
        """Valid config with two providers + 3 distinct roles returns correct JSON."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
            "codex": _make_provider("codex", "codex-v1"),
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "codex",
            "reviewer": "gemini",
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config(tf_path, providers, roles)

            for role, expected_provider in [
                ("consultant_primary", "gemini"),
                ("consultant_secondary", "codex"),
                ("reviewer", "gemini"),
            ]:
                with self.subTest(role=role):
                    result = _run(role, tf_path)
                    self.assertEqual(result.returncode, 0, msg=result.stderr)
                    out = json.loads(result.stdout)
                    self.assertEqual(out["role"], role)
                    self.assertEqual(out["provider"], expected_provider)
                    self.assertEqual(out["model_label"], providers[expected_provider]["model_label"])
                    self.assertEqual(out["args_template"], providers[expected_provider]["args_template"])
                    self.assertIsInstance(out["stdin"], bool)
                    self.assertIsInstance(out["timeout_s"], int)
                    self.assertGreater(out["timeout_s"], 0)
        finally:
            os.unlink(tf_path)

    def test_collision_primary_equals_secondary(self):
        """consultant_primary == consultant_secondary must exit nonzero."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "gemini",
            "reviewer": "gemini",
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config(tf_path, providers, roles)
            result = _run("consultant_primary", tf_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("DISTINCT", result.stderr)
        finally:
            os.unlink(tf_path)

    def test_malformed_args_template(self):
        """args_template that is a string (not list[str]) must exit nonzero with message."""
        providers = {
            "gemini": {
                "kind": "cli",
                "command": "gemini",
                "args_template": "not-a-list",   # <-- malformed
                "stdin": True,
                "timeout_s": 60,
                "model_label": "gemini-2.5-pro",
            },
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "codex-placeholder",
            "reviewer": "gemini",
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config(tf_path, providers, roles)
            result = _run("consultant_primary", tf_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid args_template", result.stderr)
            self.assertIn("gemini", result.stderr)
        finally:
            os.unlink(tf_path)


if __name__ == "__main__":
    unittest.main()
