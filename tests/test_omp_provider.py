"""
Tests for the oh-my-pi (omp) consult-arm provider entries.

Covers the pi-first-class plan: the `omp-codex` provider and `omp-gemini` alias dispatch
through the `omp-consult.sh` stdin->arg adapter, and the consultant roles resolve through them.

T007 (host-aware-model-tiers) supersedes the earlier D2 decision ("reviewer gate is not
routed through omp"): the reviewer and consultant_secondary roles now resolve to the
`cursor`-backed omp providers (`omp-cursor-terra` / `omp-cursor-sol`, gpt-5.6 terra/sol
medium), because omp v16 only serves the gpt-5.6 family via the `cursor` provider. An OAuth
hiccup on that provider fails loud through the shared preflight (`resolve-provider.py`
`_preflight_provider` / `omp-consult.sh`'s own auth check) rather than silently degrading, so
the original "never stall a review" intent is preserved via fail-loud, not via avoiding omp.

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
    omp = os.path.join(_STUB_BIN, "omp")
    with open(omp, "w") as fh:
        fh.write("#!/bin/sh\nif [ \"$1\" = token ]; then exit \"${OMP_TOKEN_RC:-0}\"; fi\nexit 0\n")
    os.chmod(omp, 0o755)


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
                        "consultant_secondary": "omp-cursor-sol",
                        "reviewer": "omp-cursor-terra",
                    },
                    "providers": {
                        "omp-codex": _omp_provider(
                            "openai-codex/gpt-5.5", "gpt-5.5 (omp/openai-codex OAuth)"
                        ),
                        "omp-antigravity-pro": _omp_provider(
                            "google-antigravity/gemini-3.1-pro",
                            "Antigravity Gemini 3.1 Pro (omp/google-antigravity OAuth)",
                        ),
                        "omp-cursor-terra": _omp_provider(
                            "cursor/gpt-5.6-terra-medium",
                            "GPT-5.6 Terra medium (omp/cursor OAuth)",
                        ),
                        "omp-cursor-sol": _omp_provider(
                            "cursor/gpt-5.6-sol-medium",
                            "GPT-5.6 Sol medium (omp/cursor OAuth)",
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
                    "aliases": {"omp-gemini": "omp-antigravity-pro"},
                },
                fh,
            )
        # config.toml fixture: consult ON, so consultant/reviewer roles resolve normally.
        self._config = os.path.join(self._tmp, "config.toml")
        with open(self._config, "w") as fh:
            fh.write('schema_version = 2\n\n[runtime]\nconsult = "on"\n')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, role: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "Z_HARNESS_REPO_PROVIDERS": self._providers,
            "Z_HARNESS_REPO_CONFIG": self._config,
        }
        if extra_env:
            env.update(extra_env)
        env["PATH"] = _STUB_BIN + os.pathsep + env.get("PATH", "")
        return subprocess.run(
            [sys.executable, SCRIPT, role], env=env, capture_output=True, text=True
        )

    def test_consultant_primary_resolves_omp_gemini_alias(self):
        r = self._run("consultant_primary")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["provider"], "omp-antigravity-pro")
        self.assertEqual(d["command"], "omp-consult.sh")
        self.assertEqual(d["args_template"], ["google-antigravity/gemini-3.1-pro"])
        self.assertEqual(d["auth_backend"], "OMP OAuth / Antigravity")
        self.assertEqual(d["auth_provider"], "google-antigravity")
        self.assertTrue(d["stdin"])

    def test_consultant_secondary_resolves_omp_cursor_sol(self):
        r = self._run("consultant_secondary")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["provider"], "omp-cursor-sol")
        self.assertEqual(d["command"], "omp-consult.sh")
        self.assertEqual(d["auth_backend"], "OMP OAuth / Cursor")
        self.assertEqual(d["auth_provider"], "cursor")
        self.assertEqual(d["args_template"], ["cursor/gpt-5.6-sol-medium"])

    def test_omp_auth_failure_fails_preflight_actionably(self):
        r = self._run("consultant_secondary", {"OMP_TOKEN_RC": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("provider_preflight_failed", r.stderr)
        self.assertIn("role=consultant_secondary", r.stderr)
        self.assertIn("provider=omp-cursor-sol", r.stderr)
        self.assertIn("auth_backend=OMP OAuth / Cursor", r.stderr)
        self.assertIn("auth not ready", r.stderr)

    def test_reviewer_resolves_omp_cursor_terra(self):
        """T007: the reviewer role now routes through the cursor-backed gpt-5.6 terra provider
        (supersedes the earlier D2 "reviewer stays native codex" decision); an auth hiccup
        still fails loud via preflight rather than silently degrading."""
        r = self._run("reviewer")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["provider"], "omp-cursor-terra")
        self.assertEqual(d["command"], "omp-consult.sh")
        self.assertEqual(d["auth_backend"], "OMP OAuth / Cursor")
        self.assertEqual(d["auth_provider"], "cursor")
        self.assertEqual(d["args_template"], ["cursor/gpt-5.6-terra-medium"])

    def test_reviewer_auth_failure_fails_preflight_actionably(self):
        """The cursor-backed reviewer provider fails loud (never silently falls back)
        when omp is not authed for cursor."""
        r = self._run("reviewer", {"OMP_TOKEN_RC": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("provider_preflight_failed", r.stderr)
        self.assertIn("role=reviewer", r.stderr)
        self.assertIn("provider=omp-cursor-terra", r.stderr)
        self.assertIn("auth_backend=OMP OAuth / Cursor", r.stderr)
        self.assertIn("auth not ready", r.stderr)

    def test_consultant_roles_remain_distinct_providers(self):
        """consultant_primary (antigravity/gemini) and consultant_secondary (cursor/sol)
        must resolve to distinct providers even after the T007 reconfiguration."""
        primary = self._run("consultant_primary")
        secondary = self._run("consultant_secondary")
        self.assertEqual(primary.returncode, 0, primary.stderr)
        self.assertEqual(secondary.returncode, 0, secondary.stderr)
        primary_provider = json.loads(primary.stdout)["provider"]
        secondary_provider = json.loads(secondary.stdout)["provider"]
        self.assertNotEqual(primary_provider, secondary_provider)
        self.assertEqual(primary_provider, "omp-antigravity-pro")
        self.assertEqual(secondary_provider, "omp-cursor-sol")

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
        # Stub `omp`: auth token succeeds by default, but print mode fails so
        # fallback behavior is exercised without a real OMP install.
        omp = os.path.join(self._bin, "omp")
        with open(omp, "w") as fh:
            fh.write(
                "#!/bin/sh\n"
                "if [ \"$1\" = token ]; then exit \"${OMP_TOKEN_RC:-0}\"; fi\n"
                "exit 1\n"
            )
        os.chmod(omp, 0o755)

    def tearDown(self):
        shutil.rmtree(self._bin, ignore_errors=True)

    def _run(self, args, prompt, extra_env=None):
        env = {**os.environ, "PATH": self._bin + os.pathsep + os.environ.get("PATH", "")}
        if extra_env:
            env.update(extra_env)
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

    def test_fallback_emits_provider_fallback_used_without_prompt(self):
        base = tempfile.mkdtemp(prefix="zh-omp-events-")
        try:
            r = self._run(
                ["openai-codex/gpt-5.5", "--fallback", "cat"],
                "PROMPT_BODY_42",
                {
                    "Z_HARNESS_BASE_DIR": base,
                    "Z_HARNESS_RUN_ID": "test-fallback-run",
                    "Z_HARNESS_SLUG": "",
                    "Z_HARNESS_PROVIDER_ROLE": "consultant_secondary",
                },
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            metrics = Path(base) / "metrics.jsonl"
            rows = [
                json.loads(line)
                for line in metrics.read_text().splitlines()
                if line.strip()
            ]
            event = next(row for row in rows if row.get("kind") == "provider_fallback_used")
            self.assertEqual(event["role"], "consultant_secondary")
            self.assertEqual(event["provider"], "omp-codex")
            self.assertEqual(event["attempted_model"], "openai-codex/gpt-5.5")
            self.assertEqual(event["auth_backend"], "OMP OAuth / Codex")
            self.assertEqual(event["fallback_provider"], "cat")
            self.assertNotIn("PROMPT_BODY_42", json.dumps(event))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_fails_loud_when_omp_fails_and_no_fallback(self):
        r = self._run(["bogus/model"], "PROMPT_BODY_42")
        self.assertEqual(r.returncode, 3)
        self.assertIn("no --fallback configured", r.stderr)

    def test_auth_failure_does_not_fallback(self):
        base = tempfile.mkdtemp(prefix="zh-omp-auth-events-")
        try:
            r = self._run(
                ["openai-codex/gpt-5.5", "--fallback", "cat"],
                "PROMPT_BODY_42",
                {
                    "OMP_TOKEN_RC": "1",
                    "Z_HARNESS_BASE_DIR": base,
                    "Z_HARNESS_RUN_ID": "test-auth-failure-run",
                    "Z_HARNESS_SLUG": "",
                    "Z_HARNESS_PROVIDER_ROLE": "consultant_secondary",
                },
            )
            self.assertEqual(r.returncode, 3)
            self.assertEqual(r.stdout, "")
            self.assertIn("auth not ready", r.stderr)
            self.assertNotIn("DEGRADED", r.stderr)
            rows = [
                json.loads(line)
                for line in (Path(base) / "metrics.jsonl").read_text().splitlines()
                if line.strip()
            ]
            event = next(row for row in rows if row.get("kind") == "provider_preflight_failed")
            self.assertEqual(event["role"], "consultant_secondary")
            self.assertEqual(event["provider"], "omp-codex")
            self.assertEqual(event["auth_backend"], "OMP OAuth / Codex")
            self.assertIn("auth not ready", event["reason"])
            self.assertNotIn("PROMPT_BODY_42", json.dumps(event))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_primary_auth_session_failure_does_not_fallback(self):
        omp = os.path.join(self._bin, "omp")
        with open(omp, "w") as fh:
            fh.write(
                "#!/bin/sh\n"
                "if [ \"$1\" = token ]; then exit 0; fi\n"
                "printf '%s\\n' 'Cloud Code Assist API error (404): Requested entity was not found' >&2\n"
                "exit 1\n"
            )
        os.chmod(omp, 0o755)

        base = tempfile.mkdtemp(prefix="zh-omp-primary-auth-events-")
        try:
            r = self._run(
                ["openai-codex/gpt-5.5", "--fallback", "cat"],
                "PROMPT_BODY_42",
                {
                    "Z_HARNESS_BASE_DIR": base,
                    "Z_HARNESS_RUN_ID": "test-primary-auth-failure-run",
                    "Z_HARNESS_SLUG": "",
                    "Z_HARNESS_PROVIDER_ROLE": "consultant_secondary",
                },
            )
            self.assertEqual(r.returncode, 3)
            self.assertEqual(r.stdout, "")
            self.assertIn("provider_preflight_failed", r.stderr)
            self.assertIn("auth/session not ready", r.stderr)
            self.assertNotIn("DEGRADED", r.stderr)
            rows = [
                json.loads(line)
                for line in (Path(base) / "metrics.jsonl").read_text().splitlines()
                if line.strip()
            ]
            event = next(row for row in rows if row.get("kind") == "provider_preflight_failed")
            self.assertEqual(event["role"], "consultant_secondary")
            self.assertEqual(event["provider"], "omp-codex")
            self.assertEqual(event["auth_backend"], "OMP OAuth / Codex")
            self.assertIn("auth/session not ready", event["reason"])
            self.assertNotIn("PROMPT_BODY_42", json.dumps(event))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_empty_prompt_rejected(self):
        r = self._run(["bogus/model", "--fallback", "cat"], "   \n")
        self.assertEqual(r.returncode, 2)

    def test_primary_invocation_disables_rule_loading(self):
        # AGENTS.md auto-rules are huge in z-harness; the adapter must prevent
        # omp from loading them when it is used as a lightweight consult shim.
        omp = os.path.join(self._bin, "omp")
        with open(omp, "w") as fh:
            fh.write("#!/bin/sh\nif [ \"$1\" = token ]; then exit 0; fi\nprintf '%s\\n' \"$*\"\n")
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
        data = json.loads(cfg.read_text())
        providers = data["providers"]
        aliases = data.get("aliases", {})

        self.assertEqual(aliases.get("omp-gemini"), "omp-antigravity-pro")
        for name, native in (
            ("omp-codex", "codex"),
            (aliases["omp-gemini"], "gemini"),
            ("omp-cursor-terra", "cursor-agent"),
            ("omp-cursor-sol", "cursor-agent"),
        ):
            self.assertIn(name, providers, f"{name} missing from providers.json")
            argt = providers[name]["args_template"]
            self.assertEqual(providers[name]["command"], "omp-consult.sh")
            self.assertIn("--fallback", argt, f"{name} has no --fallback clause")
            self.assertIn(native, argt, f"{name} fallback does not invoke {native}")
            # model id is the first positional arg (before --fallback)
            self.assertEqual(
                argt[0].split("/")[0] in ("openai-codex", "google-antigravity", "cursor"),
                True,
            )

    def test_live_roles_route_reviewer_and_secondary_to_openai_gpt56(self):
        """T009: reviewer -> gpt-5.6-terra, consultant_secondary -> gpt-5.6-sol,
        consultant_primary stays gemini-3.1-pro; the two consultants remain distinct providers."""
        cfg = Path(__file__).parent.parent / ".z-harness" / "providers.json"
        data = json.loads(cfg.read_text())
        roles = data["roles"]
        providers = data["providers"]

        self.assertEqual(roles["reviewer"], "omp-openai-terra")
        self.assertEqual(roles["consultant_secondary"], "omp-openai-sol")
        self.assertEqual(roles["consultant_primary"], "omp-antigravity-pro")

        self.assertEqual(
            providers["omp-openai-terra"]["args_template"][0],
            "openai-codex/gpt-5.6-terra",
        )
        self.assertEqual(
            providers["omp-openai-sol"]["args_template"][0],
            "openai-codex/gpt-5.6-sol",
        )
        self.assertEqual(
            providers["omp-antigravity-pro"]["args_template"][0],
            "google-antigravity/gemini-3.1-pro",
        )

        # Distinctness: consultant_primary and consultant_secondary are different providers.
        self.assertNotEqual(roles["consultant_primary"], roles["consultant_secondary"])

    def test_project_omp_config_disables_agents_md_autoload(self):
        cfg = Path(__file__).parent.parent / ".omp" / "config.yml"
        body = cfg.read_text()
        self.assertIn("skills:", body)
        self.assertIn("OMP_PLUGIN_ROOT", body)
        self.assertIn("enableAgentsProject: false", body)
        self.assertNotIn("enableAgentsProject: true", body)
        for secret_bearing_key in ("oauth", "model:", "profile:"):
            self.assertNotIn(secret_bearing_key, body.lower())

    def test_root_agents_md_is_omp_safe_stub(self):
        agents = Path(__file__).parent.parent / "AGENTS.md"
        body = agents.read_text()
        self.assertLess(len(body), 5000)
        self.assertIn("intentionally small", body)
        self.assertNotIn("## auditor", body)


class TestOmpSupervisedProviderPath(unittest.TestCase):
    """Integration coverage for resolve-provider -> supervised-run -> omp-consult."""

    SUPERVISED_RUN = str(Path(__file__).parent.parent / "scripts" / "supervised-run.sh")
    ADAPTER = str(Path(__file__).parent.parent / "scripts" / "omp-consult.sh")

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="zh-omp-supervised-")
        self._providers = os.path.join(self._tmp, "providers.json")
        with open(self._providers, "w") as fh:
            json.dump(
                {
                    "version": 2,
                    "roles": {"consultant_secondary": "omp-codex"},
                    "providers": {
                        "omp-codex": {
                            **_omp_provider(
                                "openai-codex/gpt-5.5",
                                "gpt-5.5 (omp/openai-codex OAuth)",
                            ),
                            "command": self.ADAPTER,
                            "args_template": [
                                "openai-codex/gpt-5.5",
                                "--fallback",
                                "cat",
                            ],
                        }
                    },
                },
                fh,
            )
        self._config = os.path.join(self._tmp, "config.toml")
        with open(self._config, "w") as fh:
            fh.write('schema_version = 2\n\n[runtime]\nconsult = "on"\n')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_supervised_run_propagates_provider_metadata_to_omp_adapter(self):
        base = tempfile.mkdtemp(prefix="zh-omp-supervised-events-")
        slug = "supervised-omp"
        run_id = "test-supervised-omp-run"
        try:
            Path(base, "plans", slug, "archive", run_id).mkdir(parents=True)
            env = {
                **os.environ,
                "Z_HARNESS_BASE_DIR": base,
                "Z_HARNESS_SLUG": slug,
                "Z_HARNESS_PLANS_DIR": str(Path(base) / "plans"),
                "Z_HARNESS_REPO_PROVIDERS": self._providers,
                "Z_HARNESS_REPO_CONFIG": self._config,
                "PATH": _STUB_BIN + os.pathsep + os.environ.get("PATH", ""),
            }
            env.pop("Z_HARNESS_RUN_ID", None)
            env.pop("Z_HARNESS_PROVIDER_ROLE", None)

            resolved = subprocess.run(
                [sys.executable, SCRIPT, "consultant_secondary"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            descriptor = json.loads(resolved.stdout)
            command = [descriptor["command"], *descriptor["args_template"]]

            r = subprocess.run(
                [
                    "bash",
                    self.SUPERVISED_RUN,
                    "--run",
                    run_id,
                    "--type",
                    "consultant_secondary",
                    "--timeout",
                    "5",
                    "--",
                    *command,
                ],
                input="PROMPT_BODY_42",
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("PROMPT_BODY_42", r.stdout)

            events = Path(base) / "plans" / slug / "archive" / run_id / "events.jsonl"
            rows = [json.loads(line) for line in events.read_text().splitlines() if line.strip()]
            event = next(row for row in rows if row.get("kind") == "provider_fallback_used")
            self.assertEqual(event["run"], run_id)
            self.assertEqual(event["role"], "consultant_secondary")
            self.assertEqual(event["provider"], "omp-codex")
            self.assertEqual(event["attempted_model"], "openai-codex/gpt-5.5")
            self.assertEqual(event["auth_backend"], "OMP OAuth / Codex")
            self.assertEqual(event["fallback_provider"], "cat")
            self.assertNotIn("PROMPT_BODY_42", json.dumps(event))
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
