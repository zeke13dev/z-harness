"""
Tests for the oh-my-pi (omp) consult-arm provider entries.

Covers the pi-first-class plan: the `omp-codex` / `omp-gemini` provider entries dispatch
through the `omp-consult.sh` stdin->arg adapter, the consultant roles resolve to them, and
the reviewer role stays on native codex (D2 — reviewer gate is not routed through omp).

These tests are fully isolated from the live repo config: both Z_HARNESS_REPO_PROVIDERS
(providers.json) and Z_HARNESS_REPO_CONFIG (config.toml with consult=on) are pinned, so the
repo's own `runtime.consult = off` pacing setting cannot turn the roles into the "none" sentinel.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = str(Path(__file__).parent.parent / "scripts" / "resolve-provider.py")

# The adapter command resolve-provider validates via shutil.which.
_STUB_BIN = None


def setUpModule() -> None:
    global _STUB_BIN
    _STUB_BIN = tempfile.mkdtemp(prefix="zh-omp-stub-")
    for name in ("omp-consult.sh", "codex"):
        p = os.path.join(_STUB_BIN, name)
        with open(p, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)


def tearDownModule() -> None:
    if _STUB_BIN:
        shutil.rmtree(_STUB_BIN, ignore_errors=True)


def _omp_provider(model_id: str, label: str) -> dict:
    """An omp-* entry: model id lives in args_template (the agent dispatch path reads
    args_template directly and never applies model_arg_template)."""
    return {
        "kind": "cli",
        "command": "omp-consult.sh",
        "args_template": [model_id],
        "stdin": True,
        "timeout_s": 300,
        "model_label": label,
        "model_arg_template": None,
        "model_env_var": None,
        "default_model": None,
    }


class TestOmpProvider(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="zh-omp-cfg-")
        # providers.json fixture: omp consult arms + native codex reviewer.
        self._providers = os.path.join(self._tmp, "providers.json")
        with open(self._providers, "w") as fh:
            json.dump(
                {
                    "version": 2,
                    "roles": {
                        "consultant_primary": "omp-gemini",
                        "consultant_secondary": "omp-codex",
                        "reviewer": "codex-cli",
                    },
                    "providers": {
                        "omp-codex": _omp_provider(
                            "openai-codex/gpt-5.5", "gpt-5.5 (omp/openai-codex OAuth)"
                        ),
                        "omp-gemini": _omp_provider(
                            "google-antigravity/gemini-3.1-pro",
                            "gemini-3.1-pro (omp/google-antigravity OAuth)",
                        ),
                        "codex-cli": {
                            "kind": "cli",
                            "command": "codex",
                            "args_template": ["exec", "-"],
                            "stdin": True,
                            "timeout_s": 300,
                            "model_label": "gpt-5-codex",
                            "model_arg_template": None,
                            "model_env_var": None,
                            "default_model": None,
                        },
                    },
                },
                fh,
            )
        # config.toml fixture: consult ON, so consultant/reviewer roles resolve normally.
        self._config = os.path.join(self._tmp, "config.toml")
        with open(self._config, "w") as fh:
            fh.write('schema_version = 2\n\n[runtime]\nconsult = "on"\n')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, role: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "Z_HARNESS_REPO_PROVIDERS": self._providers,
            "Z_HARNESS_REPO_CONFIG": self._config,
        }
        env["PATH"] = _STUB_BIN + os.pathsep + env.get("PATH", "")
        return subprocess.run(
            [sys.executable, SCRIPT, role], env=env, capture_output=True, text=True
        )

    def test_consultant_primary_resolves_omp_gemini(self):
        r = self._run("consultant_primary")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["provider"], "omp-gemini")
        self.assertEqual(d["command"], "omp-consult.sh")
        self.assertEqual(d["args_template"], ["google-antigravity/gemini-3.1-pro"])
        self.assertTrue(d["stdin"])

    def test_consultant_secondary_resolves_omp_codex(self):
        r = self._run("consultant_secondary")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["provider"], "omp-codex")
        self.assertEqual(d["command"], "omp-consult.sh")
        self.assertEqual(d["args_template"], ["openai-codex/gpt-5.5"])

    def test_reviewer_stays_native_codex(self):
        """D2: the blocking reviewer gate is NOT routed through omp."""
        r = self._run("reviewer")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["provider"], "codex-cli")
        self.assertEqual(d["command"], "codex")

    def test_compose_argv_renders_model_as_positional(self):
        """compose_argv on an omp entry yields `omp-consult.sh <provider/model>`."""
        spec = importlib.util.spec_from_file_location("resolve_provider_mod", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        entry = _omp_provider("openai-codex/gpt-5.5", "x")
        argv = [entry["command"]] + mod.compose_argv(entry, None)
        self.assertEqual(argv, ["omp-consult.sh", "openai-codex/gpt-5.5"])


class TestOmpAdapterFallback(unittest.TestCase):
    """Exercise scripts/omp-consult.sh's --fallback clause without needing a real omp."""

    ADAPTER = str(Path(__file__).parent.parent / "scripts" / "omp-consult.sh")

    def setUp(self):
        self._bin = tempfile.mkdtemp(prefix="zh-omp-fb-")
        # Stub `omp` that always fails, so the adapter must take the fallback path.
        omp = os.path.join(self._bin, "omp")
        with open(omp, "w") as fh:
            fh.write("#!/bin/sh\nexit 1\n")
        os.chmod(omp, 0o755)

    def tearDown(self):
        shutil.rmtree(self._bin, ignore_errors=True)

    def _run(self, args, prompt):
        env = {**os.environ, "PATH": self._bin + os.pathsep + os.environ.get("PATH", "")}
        return subprocess.run(
            ["bash", self.ADAPTER, *args],
            input=prompt,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_falls_back_to_native_when_omp_fails(self):
        # omp stub fails -> adapter pipes the prompt to the fallback (`cat` echoes stdin).
        r = self._run(["bogus/model", "--fallback", "cat"], "PROMPT_BODY_42")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PROMPT_BODY_42", r.stdout)
        self.assertIn("DEGRADED", r.stderr)

    def test_fails_loud_when_omp_fails_and_no_fallback(self):
        r = self._run(["bogus/model"], "PROMPT_BODY_42")
        self.assertEqual(r.returncode, 3)

    def test_empty_prompt_rejected(self):
        r = self._run(["bogus/model", "--fallback", "cat"], "   \n")
        self.assertEqual(r.returncode, 2)

    def test_primary_invocation_disables_rule_loading(self):
        # AGENTS.md auto-rules are huge in z-harness; the adapter must prevent
        # omp from loading them when it is used as a lightweight consult shim.
        omp = os.path.join(self._bin, "omp")
        with open(omp, "w") as fh:
            fh.write("#!/bin/sh\nprintf '%s\\n' \"$*\"\n")
        os.chmod(omp, 0o755)

        r = self._run(["bogus/model"], "PROMPT_BODY_42")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--no-rules", r.stdout)
        self.assertIn("--no-session", r.stdout)
        self.assertIn("--model bogus/model", r.stdout)


class TestOmpLiveEntries(unittest.TestCase):
    """Sanity-check the real .z-harness/providers.json omp entries."""

    def test_live_omp_entries_carry_fallback(self):
        cfg = Path(__file__).parent.parent / ".z-harness" / "providers.json"
        providers = json.loads(cfg.read_text())["providers"]
        for name, native in (("omp-codex", "codex"), ("omp-gemini", "gemini")):
            self.assertIn(name, providers, f"{name} missing from providers.json")
            argt = providers[name]["args_template"]
            self.assertEqual(providers[name]["command"], "omp-consult.sh")
            self.assertIn("--fallback", argt, f"{name} has no --fallback clause")
            self.assertIn(native, argt, f"{name} fallback does not invoke {native}")
            # model id is the first positional arg (before --fallback)
            self.assertEqual(argt[0].split("/")[0] in ("openai-codex", "google-antigravity"), True)

    def test_project_omp_config_disables_agents_md_autoload(self):
        cfg = Path(__file__).parent.parent / ".omp" / "config.yml"
        body = cfg.read_text()
        self.assertIn("enableAgentsProject: false", body)

    def test_root_agents_md_is_omp_safe_stub(self):
        agents = Path(__file__).parent.parent / "AGENTS.md"
        body = agents.read_text()
        self.assertLess(len(body), 5000)
        self.assertIn("intentionally small", body)
        self.assertNotIn("## auditor", body)


if __name__ == "__main__":
    unittest.main()
