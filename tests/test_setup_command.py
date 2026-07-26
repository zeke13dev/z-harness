from __future__ import annotations

import json
import os
import subprocess
import tempfile
import sys
import unittest

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.__main__ import app  # noqa: E402
from z_harness_cli.adapters.base import DetectResult  # noqa: E402


def _provider_proposal() -> dict:
    provider = {
        "kind": "cli",
        "command": sys.executable,
        "args_template": [],
        "stdin": True,
        "timeout_s": 30,
        "model_label": "test-model",
    }
    return {
        "version": 1,
        "providers": {
            "primary": dict(provider),
            "secondary": dict(provider),
            "review": dict(provider),
        },
        "roles": {
            "consultant_primary": "primary",
            "consultant_secondary": "secondary",
            "reviewer": "review",
        },
    }


def _existing_provider_registry() -> dict:
    proposal = _provider_proposal()
    provider = next(iter(proposal["providers"].values()))
    return {
        "version": 2,
        "providers": {
            "chosen-primary": dict(provider),
            "chosen-secondary": dict(provider),
            "chosen-review": dict(provider),
            "custom-provider": dict(provider),
        },
        "roles": {
            "consultant_primary": "chosen-primary",
            "consultant_secondary": "chosen-secondary",
            "reviewer": "chosen-review",
            "watchdog_judge": "custom-provider",
            "pre-reviewer": "custom-provider",
        },
        "aliases": {"legacy-custom": "custom-provider"},
    }


class SetupCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self._xdg = tempfile.TemporaryDirectory()
        self._xdg_patch = patch.dict(
            os.environ, {"XDG_CONFIG_HOME": self._xdg.name}, clear=False
        )
        self._xdg_patch.start()

    def tearDown(self) -> None:
        self._xdg_patch.stop()
        self._xdg.cleanup()

    def test_setup_dry_run_lists_selected_harnesses_without_installing(self) -> None:
        claude = MagicMock()
        claude.name = "claude"
        claude.fidelity_tier = "native"
        cursor = MagicMock()
        cursor.name = "cursor"
        cursor.fidelity_tier = "flattened"

        with patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[
                (claude, DetectResult(installed=True, version="1.0.0")),
                (cursor, DetectResult(installed=False)),
            ],
        ), patch("z_harness_cli.commands.setup.shutil.which", return_value=None), patch(
            "z_harness_cli.commands.setup._run_plugin_install"
        ) as install_mock:
            result = self.runner.invoke(app, ["setup", "--target", "claude,cursor", "--dry-run"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("z-harness setup", result.output)
        self.assertIn("* claude", result.output)
        self.assertIn("* cursor", result.output)
        self.assertIn("dry run: no changes made", result.output)
        install_mock.assert_not_called()


    def test_prod_setup_default_all_selects_claude_omp_and_codex(self) -> None:
        claude = MagicMock()
        claude.name = "claude"
        claude.fidelity_tier = "native"
        omp = MagicMock()
        omp.name = "omp"
        omp.fidelity_tier = "native"
        codex = MagicMock()
        codex.name = "codex"
        codex.fidelity_tier = "flattened"
        cursor = MagicMock()
        cursor.name = "cursor"
        cursor.fidelity_tier = "flattened"

        with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[
                (claude, DetectResult(installed=True, version="1.0.0")),
                (cursor, DetectResult(installed=True, version="2.0.0")),
                (omp, DetectResult(installed=False)),
                (codex, DetectResult(installed=True, version="0.42.0")),
            ],
        ), patch("z_harness_cli.commands.setup.shutil.which", return_value=None), patch(
            "z_harness_cli.commands.setup._run_plugin_install"
        ) as install_mock:
            result = self.runner.invoke(app, ["setup", "--dry-run"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("selected harnesses: claude, omp, codex", result.output)
        self.assertIn("* claude", result.output)
        self.assertIn("* omp", result.output)
        self.assertIn("* codex", result.output)
        self.assertNotIn("cursor", result.output.lower())
        install_mock.assert_not_called()

    def test_prod_setup_all_install_runs_all_direct_plugin_targets(self) -> None:
        claude = MagicMock()
        claude.name = "claude"
        claude.fidelity_tier = "native"
        omp = MagicMock()
        omp.name = "omp"
        omp.fidelity_tier = "native"
        codex = MagicMock()
        codex.name = "codex"
        codex.fidelity_tier = "flattened"

        with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[
                (claude, DetectResult(installed=True, version="1.0.0")),
                (omp, DetectResult(installed=True, version="0.1.0")),
                (codex, DetectResult(installed=True, version="0.42.0")),
            ],
        ), patch("z_harness_cli.commands.setup.shutil.which", return_value=None), patch(
            "z_harness_cli.commands.setup._run_plugin_install"
        ) as install_mock:
            result = self.runner.invoke(app, ["setup", "--target", "all", "--install"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("selected harnesses: claude, omp, codex", result.output)
        install_mock.assert_called_once_with("all", force=False)

    def test_prod_setup_explicit_non_core_target_is_labeled_advanced(self) -> None:
        cursor = MagicMock()
        cursor.name = "cursor"
        cursor.fidelity_tier = "flattened"

        with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[(cursor, DetectResult(installed=True, version="2.0.0"))],
        ), patch("z_harness_cli.commands.setup.shutil.which", return_value=None):
            result = self.runner.invoke(app, ["setup", "--target", "cursor", "--dry-run"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("* cursor", result.output)
        self.assertIn("dev/advanced", result.output)

    def test_public_help_names_claude_omp_codex_release_defaults(self) -> None:
        result = self.runner.invoke(app, ["setup", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Release default/all", result.output)
        self.assertIn("claude, omp, codex", result.output)
        self.assertIn("Dev/advanced explicit", result.output)
        self.assertIn("targets: pi, cursor", result.output)

    def test_root_help_presents_claude_omp_release_surface(self) -> None:
        result = self.runner.invoke(app, ["--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Claude Code plugin + OMP package/export + Codex plugin", result.output)
        self.assertIn("Claude Code, OMP, and Codex", result.output)
        self.assertIn("release", result.output)
        self.assertIn("surfaces", result.output)

    def test_setup_rejects_unknown_target(self) -> None:
        result = self.runner.invoke(app, ["setup", "--target", "unknown", "--dry-run"])
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("unknown setup target", result.output)

    def test_provider_registry_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as xdg, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
        ), patch(
            "z_harness_cli.commands.setup._run_provider_discovery",
            return_value=_provider_proposal(),
        ), patch(
            "z_harness_cli.adapters.registry.detect_all", return_value=[]
        ):
            result = self.runner.invoke(app, ["setup", "--target", "claude"])
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry_exists = registry.exists()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("approval required", result.output)
        self.assertFalse(registry_exists)

    def test_clean_runner_dry_run_continues_without_provider_registry(self) -> None:
        with tempfile.TemporaryDirectory() as xdg, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
        ), patch(
            "z_harness_cli.commands.setup._run_provider_discovery",
            return_value={"version": 1, "providers": {}, "roles": {}},
        ), patch(
            "z_harness_cli.adapters.registry.detect_all", return_value=[]
        ):
            result = self.runner.invoke(
                app, ["setup", "--target", "claude", "--dry-run"]
            )
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry_exists = registry.exists()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("provider onboarding unavailable", result.output)
        self.assertIn("dry run: no changes made", result.output)
        self.assertFalse(registry_exists)

    def test_clean_runner_unapproved_setup_continues_without_provider_registry(self) -> None:
        with tempfile.TemporaryDirectory() as xdg, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
        ), patch(
            "z_harness_cli.commands.setup._run_provider_discovery",
            return_value={"version": 1, "providers": {}, "roles": {}},
        ), patch(
            "z_harness_cli.adapters.registry.detect_all", return_value=[]
        ):
            result = self.runner.invoke(app, ["setup", "--target", "claude"])
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry_exists = registry.exists()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("provider onboarding unavailable", result.output)
        self.assertFalse(registry_exists)

    def test_clean_runner_dry_run_with_yes_remains_non_writing(self) -> None:
        with tempfile.TemporaryDirectory() as xdg, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
        ), patch(
            "z_harness_cli.commands.setup._run_provider_discovery",
            side_effect=ValueError("no provider CLIs discovered"),
        ), patch(
            "z_harness_cli.adapters.registry.detect_all", return_value=[]
        ):
            result = self.runner.invoke(
                app, ["setup", "--target", "claude", "--dry-run", "--yes"]
            )
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry_exists = registry.exists()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("provider onboarding unavailable", result.output)
        self.assertIn("dry run: no changes made", result.output)
        self.assertFalse(registry_exists)

    def test_clean_runner_approved_setup_fails_closed_without_registry(self) -> None:
        with tempfile.TemporaryDirectory() as xdg, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
        ), patch(
            "z_harness_cli.commands.setup._run_provider_discovery",
            return_value={"version": 1, "providers": {}, "roles": {}},
        ), patch(
            "z_harness_cli.adapters.registry.detect_all", return_value=[]
        ):
            result = self.runner.invoke(
                app, ["setup", "--target", "claude", "--yes"]
            )
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry_exists = registry.exists()

        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("provider registry not ready", result.output)
        self.assertNotIn("provider onboarding unavailable", result.output)
        self.assertFalse(registry_exists)

    def test_approved_provider_registry_passes_all_role_preflight_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as xdg, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
        ), patch(
            "z_harness_cli.commands.setup._run_provider_discovery",
            return_value=_provider_proposal(),
        ), patch(
            "z_harness_cli.adapters.registry.detect_all", return_value=[]
        ):
            result = self.runner.invoke(app, ["setup", "--target", "claude", "--yes"])
            registry = Path(xdg) / "z-harness" / "providers.json"
            persisted = json.loads(registry.read_text(encoding="utf-8"))

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("provider registry written", result.output)
        self.assertEqual(persisted["roles"], _provider_proposal()["roles"])

    def test_approved_onboarding_preserves_existing_registry_extensions(self) -> None:
        existing = _existing_provider_registry()
        with tempfile.TemporaryDirectory() as xdg:
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(existing), encoding="utf-8")
            with patch.dict(
                os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
            ), patch(
                "z_harness_cli.commands.setup._run_provider_discovery",
                return_value=_provider_proposal(),
            ), patch(
                "z_harness_cli.adapters.registry.detect_all", return_value=[]
            ):
                result = self.runner.invoke(
                    app, ["setup", "--target", "claude", "--yes"]
                )
            persisted = json.loads(registry.read_text(encoding="utf-8"))

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(persisted["version"], 2)
        self.assertEqual(persisted["aliases"], existing["aliases"])
        self.assertEqual(persisted["roles"], existing["roles"])
        self.assertEqual(
            persisted["providers"]["custom-provider"],
            existing["providers"]["custom-provider"],
        )
        self.assertTrue(
            set(_provider_proposal()["providers"]) <= set(persisted["providers"])
        )

    def test_alias_bound_roles_preserve_original_strings_and_extensions(self) -> None:
        existing = _existing_provider_registry()
        existing["roles"]["consultant_primary"] = "Primary Legacy"
        existing["aliases"]["Primary Legacy"] = "chosen-primary"
        existing["custom_extension"] = {"owner": "user", "enabled": True}
        with tempfile.TemporaryDirectory() as xdg:
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(existing), encoding="utf-8")
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False), patch(
                "z_harness_cli.commands.setup._run_provider_discovery",
                return_value=_provider_proposal(),
            ), patch("z_harness_cli.adapters.registry.detect_all", return_value=[]):
                result = self.runner.invoke(
                    app, ["setup", "--target", "claude", "--yes"]
                )
            persisted = json.loads(registry.read_text(encoding="utf-8"))

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(persisted["roles"]["consultant_primary"], "Primary Legacy")
        self.assertEqual(persisted["aliases"]["Primary Legacy"], "chosen-primary")
        self.assertEqual(persisted["custom_extension"], existing["custom_extension"])

    def test_invalid_alias_graphs_and_canonical_collapse_are_write_free(self) -> None:
        cases = (
            ("dangling", {"old": "missing"}, "old", "dangling"),
            ("self-cycle", {"old": "old"}, "old", "cyclic"),
            ("cycle", {"old": "older", "older": "old"}, "old", "cyclic"),
            ("chain", {"old": "older", "older": "chosen-primary"}, "old", "chained"),
            ("collapse", {"old": "chosen-primary"}, "old", "distinct"),
        )
        for label, aliases, secondary_binding, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as xdg:
                existing = _existing_provider_registry()
                existing["aliases"].update(aliases)
                existing["roles"]["consultant_secondary"] = secondary_binding
                registry = Path(xdg) / "z-harness" / "providers.json"
                registry.parent.mkdir(parents=True)
                original = json.dumps(existing, indent=2) + "\n"
                registry.write_text(original, encoding="utf-8")
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False), patch(
                    "z_harness_cli.commands.setup._run_provider_discovery",
                    return_value=_provider_proposal(),
                ), patch("z_harness_cli.adapters.registry.detect_all", return_value=[]):
                    result = self.runner.invoke(
                        app, ["setup", "--target", "claude", "--yes"]
                    )

                self.assertNotEqual(result.exit_code, 0, result.output)
                self.assertIn(message, result.output.lower())
                self.assertEqual(registry.read_text(encoding="utf-8"), original)
                self.assertEqual(list(registry.parent.glob(f".{registry.name}.*")), [])

    def test_approved_onboarding_rejects_provider_conflict_without_writing(self) -> None:
        existing = _existing_provider_registry()
        existing["providers"]["primary"] = {
            **_provider_proposal()["providers"]["primary"],
            "model_label": "user-selected-model",
        }
        with tempfile.TemporaryDirectory() as xdg:
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry.parent.mkdir(parents=True)
            original = json.dumps(existing, indent=2) + "\n"
            registry.write_text(original, encoding="utf-8")
            with patch.dict(
                os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
            ), patch(
                "z_harness_cli.commands.setup._run_provider_discovery",
                return_value=_provider_proposal(),
            ), patch(
                "z_harness_cli.adapters.registry.detect_all", return_value=[]
            ):
                result = self.runner.invoke(
                    app, ["setup", "--target", "claude", "--yes"]
                )
            persisted_text = registry.read_text(encoding="utf-8")

        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("conflicts with the existing registry", result.output)
        self.assertEqual(persisted_text, original)

    def test_provider_registry_dry_run_never_persists_even_with_yes(self) -> None:
        with tempfile.TemporaryDirectory() as xdg, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
        ), patch(
            "z_harness_cli.commands.setup._run_provider_discovery",
            return_value=_provider_proposal(),
        ), patch(
            "z_harness_cli.adapters.registry.detect_all", return_value=[]
        ):
            result = self.runner.invoke(
                app, ["setup", "--target", "claude", "--dry-run", "--yes"]
            )
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry_exists = registry.exists()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("provider registry dry run", result.output)
        self.assertFalse(registry_exists)

    def test_invalid_provider_proposals_fail_command_without_writing(self) -> None:
        collision = _provider_proposal()
        collision["roles"]["reviewer"] = collision["roles"]["consultant_primary"]
        missing = _provider_proposal()
        del missing["roles"]["reviewer"]
        secret = _provider_proposal()
        secret["providers"]["primary"]["api_key"] = "do-not-persist"
        malformed = _provider_proposal()
        malformed["providers"] = []

        for label, proposal, message in (
            ("collision", collision, "must be distinct"),
            ("missing", missing, "missing mandatory roles"),
            ("secret", secret, "secret-bearing"),
            ("malformed", malformed, "providers and roles objects"),
        ):
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory() as xdg,
                patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False),
                patch(
                    "z_harness_cli.commands.setup._run_provider_discovery",
                    return_value=proposal,
                ),
                patch("z_harness_cli.adapters.registry.detect_all", return_value=[]),
            ):
                result = self.runner.invoke(
                    app, ["setup", "--target", "claude", "--yes"]
                )
                registry = Path(xdg) / "z-harness" / "providers.json"

                self.assertNotEqual(result.exit_code, 0, result.output)
                self.assertIn(message, result.output)
                self.assertFalse(registry.exists())

    def test_nested_and_value_level_credentials_fail_without_writing(self) -> None:
        cases = {
            "camel-api-key": {"apiKey": "literal"},
            "authorization-header": {"headers": {"Authorization": "Basic literal"}},
            "bearer-value": {"metadata": ["Bearer literal-token"]},
            "argv-token": {"args_template": ["--client-secret", "literal"]},
            "argv-client-secret-equals": {
                "args_template": ["--client-secret=literal"]
            },
            "argv-camel-api-key-equals": {
                "metadata": {"nested": [["--apiKey=literal"]]}
            },
            "argv-authorization-equals": {
                "args_template": ["--authorization=Bearer literal"]
            },
            "private-key": {"nested": [{"private_key": "literal"}]},
            "cookie": {"headers": [{"Cookie": "session=literal"}]},
        }
        for label, injected in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as xdg:
                proposal = _provider_proposal()
                proposal["providers"]["primary"].update(injected)
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False), patch(
                    "z_harness_cli.commands.setup._run_provider_discovery",
                    return_value=proposal,
                ), patch("z_harness_cli.adapters.registry.detect_all", return_value=[]):
                    result = self.runner.invoke(
                        app, ["setup", "--target", "claude", "--yes"]
                    )
                registry = Path(xdg) / "z-harness" / "providers.json"
                self.assertNotEqual(result.exit_code, 0, result.output)
                self.assertIn("secret-bearing", result.output)
                self.assertFalse(registry.exists())

    def test_argument_credentials_fail_byte_stably_and_leave_no_temporary_file(
        self,
    ) -> None:
        argument_forms = (
            ["--client-secret=literal"],
            ["--api_key=literal"],
            ["--authorization=Bearer literal"],
            ["--header=Authorization: Basic literal"],
            [" --HEADER = authorization :Bearer literal"],
            ["--header", "Authorization:Bearer literal"],
            ["--header", " X-Api-Key : literal"],
            ["--header=X-API-Token: literal"],
            ["--HEADER", "x_api_token : literal"],
            ["-H", "X Api Token: literal"],
            ["--header=X-Auth-Token: literal"],
            ["--header", "Proxy-Authorization: Digest literal"],
            [{"headers": {"X-Api-Key": "literal"}}],
            [{"headers": {"x_api_token": "literal"}}],
            [{"headers": [{"X API TOKEN": "literal"}]}],
            [{"headers": ["x_api_key:literal"]}],
            [{"headers": ["X-Api-Token:literal"]}],
        )
        for arguments in argument_forms:
            for existing in (False, True):
                with (
                    self.subTest(arguments=arguments, existing=existing),
                    tempfile.TemporaryDirectory() as xdg,
                ):
                    registry = Path(xdg) / "z-harness" / "providers.json"
                    original = ""
                    if existing:
                        registry.parent.mkdir(parents=True)
                        original = json.dumps(
                            _existing_provider_registry(), indent=2
                        ) + "\n"
                        registry.write_text(original, encoding="utf-8")
                    proposal = _provider_proposal()
                    proposal["providers"]["primary"]["args_template"] = [
                        {"nested": arguments}
                    ]
                    with patch.dict(
                        os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
                    ), patch(
                        "z_harness_cli.commands.setup._run_provider_discovery",
                        return_value=proposal,
                    ), patch(
                        "z_harness_cli.adapters.registry.detect_all", return_value=[]
                    ):
                        result = self.runner.invoke(
                            app, ["setup", "--target", "claude", "--yes"]
                        )

                    self.assertNotEqual(result.exit_code, 0, result.output)
                    self.assertIn("secret-bearing", result.output)
                    if existing:
                        self.assertEqual(
                            registry.read_text(encoding="utf-8"), original
                        )
                    else:
                        self.assertFalse(registry.exists())
                    self.assertEqual(
                        list(registry.parent.glob(f".{registry.name}.*")), []
                    )

    def test_benign_generic_headers_are_accepted(self) -> None:
        benign_extensions = (
            {"args_template": ["--header=Content-Type: json"]},
            {"args_template": ["--header", "Accept: text"]},
            {"args_template": ["--header=X-Request-Token: correlation-id"]},
            {"headers": {"X-Request-Id": "request-123"}},
            {"headers": {"X-Max-Tokens": "4096"}},
            {"headers": ["Cache-Control: no-cache"]},
        )
        for extension in benign_extensions:
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as xdg:
                proposal = _provider_proposal()
                proposal["providers"]["primary"].update(extension)
                proposal["providers"]["primary"]["auth_env"] = "SAFE_TEST_AUTH"
                with patch.dict(
                    os.environ,
                    {"XDG_CONFIG_HOME": xdg, "SAFE_TEST_AUTH": "present"},
                    clear=False,
                ), patch(
                    "z_harness_cli.commands.setup._run_provider_discovery",
                    return_value=proposal,
                ), patch("z_harness_cli.adapters.registry.detect_all", return_value=[]):
                    result = self.runner.invoke(
                        app, ["setup", "--target", "claude", "--yes"]
                    )
                registry = Path(xdg) / "z-harness" / "providers.json"

                self.assertEqual(result.exit_code, 0, result.output)
                self.assertTrue(registry.exists())

    def test_benign_token_named_extensions_are_preserved(self) -> None:
        existing = _existing_provider_registry()
        existing["custom_extension"] = {
            "max_tokens": 4096,
            "input_tokens": 2048,
            "token_budget": 8192,
        }
        with tempfile.TemporaryDirectory() as xdg:
            registry = Path(xdg) / "z-harness" / "providers.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(existing), encoding="utf-8")
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False), patch(
                "z_harness_cli.commands.setup._run_provider_discovery",
                return_value=_provider_proposal(),
            ), patch("z_harness_cli.adapters.registry.detect_all", return_value=[]):
                result = self.runner.invoke(
                    app, ["setup", "--target", "claude", "--yes"]
                )
            persisted = json.loads(registry.read_text(encoding="utf-8"))

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(persisted["custom_extension"], existing["custom_extension"])

    def test_valid_auth_env_name_is_accepted_and_persisted(self) -> None:
        proposal = _provider_proposal()
        proposal["providers"]["primary"]["auth_env"] = "Z_HARNESS_TEST_TOKEN"
        with tempfile.TemporaryDirectory() as xdg, patch.dict(
            os.environ,
            {"XDG_CONFIG_HOME": xdg, "Z_HARNESS_TEST_TOKEN": "present"},
            clear=False,
        ), patch(
            "z_harness_cli.commands.setup._run_provider_discovery",
            return_value=proposal,
        ), patch("z_harness_cli.adapters.registry.detect_all", return_value=[]):
            result = self.runner.invoke(
                app, ["setup", "--target", "claude", "--yes"]
            )
            registry = Path(xdg) / "z-harness" / "providers.json"
            persisted = json.loads(registry.read_text(encoding="utf-8"))

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            persisted["providers"]["primary"]["auth_env"], "Z_HARNESS_TEST_TOKEN"
        )

    def test_atomic_replace_failure_is_nonzero_byte_stable_and_temp_free(self) -> None:
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as xdg:
                registry = Path(xdg) / "z-harness" / "providers.json"
                original = ""
                if existing:
                    registry.parent.mkdir(parents=True)
                    original = json.dumps(_existing_provider_registry(), indent=2) + "\n"
                    registry.write_text(original, encoding="utf-8")
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False), patch(
                    "z_harness_cli.commands.setup._run_provider_discovery",
                    return_value=_provider_proposal(),
                ), patch("z_harness_cli.adapters.registry.detect_all", return_value=[]), patch(
                    "z_harness_cli.commands.setup.os.replace",
                    side_effect=OSError("replacement denied"),
                ):
                    result = self.runner.invoke(
                        app, ["setup", "--target", "claude", "--yes"]
                    )

                self.assertNotEqual(result.exit_code, 0, result.output)
                self.assertIn("write failed", result.output)
                if existing:
                    self.assertEqual(registry.read_text(encoding="utf-8"), original)
                else:
                    self.assertFalse(registry.exists())
                self.assertEqual(list(registry.parent.glob(f".{registry.name}.*")), [])

    def test_real_aggregate_preflight_failure_is_write_free(self) -> None:
        proposal = _provider_proposal()
        proposal["providers"]["primary"]["command"] = "z-harness-missing-provider"
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as xdg:
                registry = Path(xdg) / "z-harness" / "providers.json"
                original = ""
                if existing:
                    registry.parent.mkdir(parents=True)
                    original = json.dumps(
                        {**proposal, "custom_extension": {"preserve": True}}, indent=2
                    ) + "\n"
                    registry.write_text(original, encoding="utf-8")
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False), patch(
                    "z_harness_cli.commands.setup._run_provider_discovery",
                    return_value=proposal,
                ), patch("z_harness_cli.adapters.registry.detect_all", return_value=[]):
                    result = self.runner.invoke(
                        app, ["setup", "--target", "claude", "--yes"]
                    )

                self.assertNotEqual(result.exit_code, 0, result.output)
                self.assertIn("provider_preflight_failed", result.output)
                if existing:
                    self.assertEqual(registry.read_text(encoding="utf-8"), original)
                else:
                    self.assertFalse(registry.exists())
                self.assertEqual(list(registry.parent.glob(f".{registry.name}.*")), [])

    def test_dry_run_and_unapproved_onboarding_leave_existing_registry_unchanged(self) -> None:
        for extra_args in (["--dry-run", "--yes"], []):
            with self.subTest(args=extra_args), tempfile.TemporaryDirectory() as xdg:
                registry = Path(xdg) / "z-harness" / "providers.json"
                registry.parent.mkdir(parents=True)
                original = json.dumps(_existing_provider_registry(), indent=2) + "\n"
                registry.write_text(original, encoding="utf-8")
                with patch.dict(
                    os.environ, {"XDG_CONFIG_HOME": xdg}, clear=False
                ), patch(
                    "z_harness_cli.commands.setup._run_provider_discovery",
                    return_value=_provider_proposal(),
                ), patch(
                    "z_harness_cli.adapters.registry.detect_all", return_value=[]
                ):
                    result = self.runner.invoke(
                        app, ["setup", "--target", "claude", *extra_args]
                    )

                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(registry.read_text(encoding="utf-8"), original)


class InstallCommandProdScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_prod_install_all_passes_all_direct_plugin_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dirname in (".git", "skills", "agents", "runtime"):
                (root / dirname).mkdir()
            script = root / "install.sh"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            completed = MagicMock(returncode=0)

            with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
                "z_harness_cli.commands.install._harness_root",
                return_value=root,
            ), patch(
                "z_harness_cli.commands.install.subprocess.run",
                return_value=completed,
            ) as run_mock:
                result = self.runner.invoke(
                    app,
                    ["install", "--target", "all", "--tarball", "file:///tmp/z-harness.tgz"],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        args = run_mock.call_args[0][0]
        self.assertIn("--target=all", args)
        self.assertNotIn("--target=claude", args)
        self.assertNotIn("--target=codex", args)

    def test_prod_install_accepts_codex_plugin_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dirname in (".git", "skills", "agents", "runtime"):
                (root / dirname).mkdir()
            script = root / "install.sh"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            completed = MagicMock(returncode=0)

            with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
                "z_harness_cli.commands.install._harness_root",
                return_value=root,
            ), patch(
                "z_harness_cli.commands.install.subprocess.run",
                return_value=completed,
            ) as run_mock:
                result = self.runner.invoke(app, ["install", "--target", "codex"])

        self.assertEqual(result.exit_code, 0, result.output)
        args = run_mock.call_args[0][0]
        self.assertIn("--target=codex", args)

    def test_prod_install_codex_does_not_short_circuit_before_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
                "z_harness_cli.commands.install._harness_root",
                return_value=Path(tmp),
            ), patch(
                "z_harness_cli.commands.install.subprocess.run",
            ) as run_mock:
                result = self.runner.invoke(app, ["install", "--target", "codex"])

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("install.sh is missing", result.output)
        run_mock.assert_not_called()

    def test_dev_source_install_all_remains_explicitly_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dirname in (".git", "skills", "agents", "runtime"):
                (root / dirname).mkdir()
            script = root / "install.sh"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            completed = MagicMock(returncode=0)

            with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "dev"}, clear=False), patch(
                "z_harness_cli.commands.install._harness_root",
                return_value=root,
            ), patch(
                "z_harness_cli.commands.install.subprocess.run",
                return_value=completed,
            ) as run_mock:
                result = self.runner.invoke(app, ["install", "--target", "all"])

        self.assertEqual(result.exit_code, 0, result.output)
        args = run_mock.call_args[0][0]
        self.assertIn("--target=all", args)

    def _bootstrap_codex_plugin_manifest(self) -> None:
        """Materialize REPO_ROOT/.codex-plugin/plugin.json for install.sh's
        is_codex_plugin_source() compatibility check.

        This dev monorepo checkout is gitignored for .codex-plugin/ (it is
        generated at export/install time); a real prod-shaped codex-plugin
        source clone ships that manifest already. Reuses the driver's own
        manifest renderer rather than duplicating its logic.
        """
        from runtime.drivers.codex.export import _render_plugin_manifest

        manifest_path = REPO_ROOT / ".codex-plugin" / "plugin.json"
        if manifest_path.exists():
            # A developer already generated this locally; leave it alone.
            self._created_codex_plugin_manifest = False
            return
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(_render_plugin_manifest(REPO_ROOT), encoding="utf-8")
        self._created_codex_plugin_manifest = True

    def _teardown_codex_plugin_manifest(self) -> None:
        if getattr(self, "_created_codex_plugin_manifest", False):
            manifest_path = REPO_ROOT / ".codex-plugin" / "plugin.json"
            manifest_path.unlink(missing_ok=True)
            try:
                manifest_path.parent.rmdir()
            except OSError:
                pass  # directory not empty (e.g. other generated files present)

    def _repo_clone_cwd(self) -> Path:
        """Return a directory install.sh's is_repo_clone()/is_codex_plugin_source()
        checks will recognize as a valid repo clone.

        REPO_ROOT (this worktree checkout) has `.git` as a gitdir-pointer *file*,
        not a directory -- a normal git-worktree invariant, not a defect. install.sh's
        `[[ -d ".git" ]]` gate is correct and must not be weakened, so we must not
        mutate the real `.git` (that would also corrupt this worktree). Instead,
        materialize a disposable mirror: symlink every real top-level entry from
        REPO_ROOT (including the now-materialized .codex-plugin/) except `.git`,
        which becomes a plain, content-less directory -- install.sh only ever
        checks `-d ".git"` in this code path and never runs a git command against it.
        """
        self._bootstrap_codex_plugin_manifest()
        self.addCleanup(self._teardown_codex_plugin_manifest)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mirror = Path(tmp.name)
        for entry in REPO_ROOT.iterdir():
            if entry.name == ".git":
                (mirror / ".git").mkdir()
            else:
                (mirror / entry.name).symlink_to(entry)
        return mirror

    def test_install_sh_prod_codex_repo_mode_is_valid(self) -> None:
        repo_clone_cwd = self._repo_clone_cwd()
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as bin_dir:
            fake_codex = Path(bin_dir) / "codex"
            fake_codex.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$HOME/codex-calls.log\"\n"
                "if [ \"$1 $2\" = \"plugin list\" ]; then [ -e \"$HOME/codex-registration\" ] && printf 'z-harness@personal\\n'; exit 0; fi\n"
                "if [ \"$1 $2\" = \"plugin add\" ]; then touch \"$HOME/codex-registration\"; exit 0; fi\n"
                "if [ \"$1 $2\" = \"plugin remove\" ]; then rm -f \"$HOME/codex-registration\"; exit 0; fi\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            env = {
                **os.environ,
                "HOME": home,
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "Z_HARNESS_RELEASE_SURFACE": "prod",
            }
            result = subprocess.run(
                ["bash", "install.sh", "--target=codex"],
                cwd=repo_clone_cwd,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("z-harness installed for Codex", result.stdout)

    def test_install_sh_prod_all_repo_mode_installs_claude_and_codex(self) -> None:
        repo_clone_cwd = self._repo_clone_cwd()
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as bin_dir:
            fake_codex = Path(bin_dir) / "codex"
            fake_codex.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$HOME/codex-calls.log\"\n"
                "if [ \"$1 $2\" = \"plugin list\" ]; then [ -e \"$HOME/codex-registration\" ] && printf 'z-harness@personal\\n'; exit 0; fi\n"
                "if [ \"$1 $2\" = \"plugin add\" ]; then touch \"$HOME/codex-registration\"; exit 0; fi\n"
                "if [ \"$1 $2\" = \"plugin remove\" ]; then rm -f \"$HOME/codex-registration\"; exit 0; fi\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            env = {
                **os.environ,
                "HOME": home,
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "Z_HARNESS_RELEASE_SURFACE": "prod",
            }
            result = subprocess.run(
                ["bash", "install.sh", "--target=all"],
                cwd=repo_clone_cwd,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            claude_link = Path(home) / ".claude" / "plugins" / "z-harness@zeke-tools"
            codex_link = Path(home) / "plugins" / "z-harness"
            claude_installed = claude_link.is_symlink()
            codex_installed = codex_link.is_dir()

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("z-harness installed for Claude Code", result.stdout)
        self.assertIn("z-harness installed for Codex", result.stdout)
        self.assertTrue(claude_installed)
        self.assertTrue(codex_installed)


class ProdSurfaceExportFilterTest(unittest.TestCase):
    def test_prod_surface_hides_experimental_skills(self) -> None:
        from runtime.drivers._export_utils import enumerate_sources

        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        os.environ["Z_HARNESS_RELEASE_SURFACE"] = "prod"
        try:
            sources = enumerate_sources(REPO_ROOT)
        finally:
            if previous is None:
                os.environ.pop("Z_HARNESS_RELEASE_SURFACE", None)
            else:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

        skill_ids = {entry["id"] for entry in sources["skills"]}
        self.assertIn("z-brainstorm", skill_ids)
        self.assertIn("z-learn", skill_ids)
        self.assertIn("z-sharpen", skill_ids)
        self.assertIn("z-grill", skill_ids)
        self.assertNotIn("z-research", skill_ids)
        self.assertNotIn("z-explore", skill_ids)
        self.assertNotIn("z-overnight", skill_ids)
        self.assertNotIn("z-attend", skill_ids)
        self.assertFalse(any(skill_id.startswith("z-axiom-") for skill_id in skill_ids))

    def test_dev_surface_keeps_experimental_skills(self) -> None:
        from runtime.drivers._export_utils import enumerate_sources

        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        os.environ["Z_HARNESS_RELEASE_SURFACE"] = "dev"
        try:
            sources = enumerate_sources(REPO_ROOT)
        finally:
            if previous is None:
                os.environ.pop("Z_HARNESS_RELEASE_SURFACE", None)
            else:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

        skill_ids = {entry["id"] for entry in sources["skills"]}
        self.assertIn("z-research", skill_ids)
        self.assertIn("z-explore", skill_ids)
        self.assertIn("z-overnight", skill_ids)
        self.assertIn("z-attend", skill_ids)



class ProdSurfaceMcpFilterTest(unittest.TestCase):
    def test_prod_surface_hides_experimental_mcp_tools(self) -> None:
        import z_harness_cli.mcp.server as server

        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        os.environ["Z_HARNESS_RELEASE_SURFACE"] = "prod"
        try:
            active = server._active_command_tools()
        finally:
            if previous is None:
                os.environ.pop("Z_HARNESS_RELEASE_SURFACE", None)
            else:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

        self.assertIn("z_brainstorm", active)
        self.assertIn("z_sharpen", active)
        self.assertIn("z_learn", active)
        self.assertIn("z_grill", active)
        self.assertNotIn("z_research", active)
        self.assertNotIn("z_map", active)
        self.assertNotIn("z_explore", active)
        self.assertNotIn("z_overnight", active)
        self.assertNotIn("z_axiom_scan", active)

    def test_packaged_prod_surface_hides_mcp_tools_without_env(self) -> None:
        import z_harness_cli.mcp.server as server

        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        if previous is not None:
            os.environ.pop("Z_HARNESS_RELEASE_SURFACE")
        try:
            with patch("z_harness_cli.release_surface._module_in_source_checkout", return_value=False):
                active = server._active_command_tools()
        finally:
            if previous is not None:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

        self.assertIn("z_brainstorm", active)
        self.assertNotIn("z_research", active)
        self.assertNotIn("z_map", active)
        self.assertNotIn("z_explore", active)
        self.assertNotIn("z_overnight", active)
        self.assertNotIn("z_axiom_scan", active)

class UxSmokeScriptExistsTest(unittest.TestCase):
    def test_ux_smoke_script_exists(self) -> None:
        script = REPO_ROOT / "scripts" / "ux-setup-smoke.sh"
        self.assertTrue(script.exists())
        self.assertIn("Z_HARNESS_UX_SMOKE_HOME", script.read_text(encoding="utf-8"))
