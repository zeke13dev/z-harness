"""
Backward-compat fail-fast test: .z-harness/providers.json must validate
against provider.schema.json via runtime.validate.

This test surfaces schema-too-strict mistakes before T007-T013 work locks in
(per audit MAJOR M5).

Also covers compose_argv (scripts/resolve-provider.py) and the extended
build_env (runtime/dispatch/env.py) added in T004.

To run:
    cd /path/to/repo-root
    python -m pytest runtime/tests/test_compat_providers.py -v
"""

import importlib.util
import json
import types
from pathlib import Path

import pytest

import jsonschema

from runtime.validate import validate
from runtime.dispatch.env import build_env

# ---------------------------------------------------------------------------
# Import scripts/resolve-provider.py as a module so compose_argv and
# resolve-related functions are callable.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
_RESOLVE_PROVIDER_SCRIPT = _SCRIPTS_DIR / "resolve-provider.py"
_rp_spec = importlib.util.spec_from_file_location(
    "resolve_provider_script_t004", _RESOLVE_PROVIDER_SCRIPT
)
_rp_module = importlib.util.module_from_spec(_rp_spec)  # type: ignore[arg-type]
_rp_spec.loader.exec_module(_rp_module)  # type: ignore[union-attr]
compose_argv = _rp_module.compose_argv
_apply_aliases = _rp_module._apply_aliases
_emit_alias_used = _rp_module._emit_alias_used


# Resolve repo root as the directory containing .z-harness/
_REPO_ROOT = Path(__file__).parent.parent.parent
_PROVIDERS_PATH = _REPO_ROOT / ".z-harness" / "providers.json"


def test_providers_json_exists():
    """The providers.json file must be present at .z-harness/providers.json."""
    assert _PROVIDERS_PATH.exists(), (
        f"providers.json not found at {_PROVIDERS_PATH}. "
        "This file is required for backward-compat validation."
    )


def test_providers_json_validates_against_schema():
    """Existing .z-harness/providers.json must conform to provider.schema.json.

    Failure here means provider.schema.json is too strict for the live config
    and must be loosened before T007-T013 work proceeds.
    """
    with _PROVIDERS_PATH.open("r", encoding="utf-8") as fh:
        providers_data = json.load(fh)

    # Should not raise — if it does, the schema is too strict
    validate("provider", providers_data)


def test_validate_command_valid_instance():
    """validate('command', ...) succeeds for a valid command fixture."""
    valid_command = {
        "id": "z-plan",
        "description": "Generate a task plan from a spec file.",
        "body": "## Usage\n\nRun `/z-plan` to generate a plan.",
        "schema_version": 1,
    }
    # Should not raise
    validate("command", valid_command)


def test_validate_command_empty_raises():
    """validate('command', {}) raises jsonschema.ValidationError."""
    with pytest.raises(jsonschema.ValidationError):
        validate("command", {})


def test_validate_unknown_schema_name_raises():
    """validate with an unknown schema name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown schema name"):
        validate("nonexistent", {})


def test_meta_schema_cached():
    """Calling validate twice uses the cached schema (no re-meta-validation)."""
    from runtime.validate import _schema_cache

    # Clear cache to test first-load path
    _schema_cache.clear()

    instance = {
        "id": "z-test",
        "description": "Test command.",
        "body": "Body.",
        "schema_version": 1,
    }
    validate("command", instance)
    assert "command" in _schema_cache

    # Second call must still work (uses cache)
    validate("command", instance)


def test_corrupted_schema_raises_clear_error(tmp_path, monkeypatch):
    """A deliberately corrupted schema file raises SchemaError naming the file."""
    from runtime import validate as validate_module

    # Write a corrupted schema to a temp contract dir
    fake_contract_dir = tmp_path / "contract"
    fake_contract_dir.mkdir()
    corrupted = fake_contract_dir / "command.schema.json"
    # "type" must be a string or array, not an integer — invalid Draft 7
    corrupted.write_text(json.dumps({"type": 42}), encoding="utf-8")

    # Patch the module-level _CONTRACT_DIR and clear cache
    original_dir = validate_module._CONTRACT_DIR
    validate_module._CONTRACT_DIR = fake_contract_dir
    validate_module._schema_cache.clear()

    try:
        with pytest.raises(jsonschema.SchemaError, match="Contract schema"):
            validate_module._load_schema("command")
    finally:
        validate_module._CONTRACT_DIR = original_dir
        validate_module._schema_cache.clear()


def test_schema_invariants_enforced(tmp_path):
    """Spec invariants are enforced: missing schema_version raises RuntimeError naming the file."""
    from runtime import validate as validate_module

    # Write a schema that passes Draft 7 syntax check but is missing schema_version
    fake_contract_dir = tmp_path / "contract"
    fake_contract_dir.mkdir()
    bad_schema = fake_contract_dir / "command.schema.json"
    # Valid JSON Schema Draft 7 syntax, but missing required top-level schema_version field
    bad_schema.write_text(
        json.dumps({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            # schema_version intentionally omitted
        }),
        encoding="utf-8",
    )

    original_dir = validate_module._CONTRACT_DIR
    validate_module._CONTRACT_DIR = fake_contract_dir
    validate_module._schema_cache.clear()

    try:
        with pytest.raises(RuntimeError) as exc_info:
            validate_module._load_schema("command")
        # Error message must name the offending file
        assert str(bad_schema) in str(exc_info.value), (
            f"Expected file path in error message, got: {exc_info.value}"
        )
        assert "schema_version" in str(exc_info.value)
    finally:
        validate_module._CONTRACT_DIR = original_dir
        validate_module._schema_cache.clear()


# ---------------------------------------------------------------------------
# compose_argv tests (T004)
# ---------------------------------------------------------------------------

# Shared provider fixtures
_V2_PROVIDER_WITH_MODEL_ARG = {
    "args_template": ["exec", "-"],
    "model_arg_template": ["--model", "{model}"],
    "model_env_var": None,
    "default_model": "gpt-5-codex",
}

_V1_PROVIDER_NULL_TEMPLATE = {
    "args_template": ["exec", "-"],
    "model_arg_template": None,
    "model_env_var": None,
    "default_model": "gpt-5-codex",
}


def test_compose_argv_v2_returns_args_template_plus_model_arg():
    """compose_argv on a v2 provider returns args_template + rendered model_arg_template."""
    result = compose_argv(_V2_PROVIDER_WITH_MODEL_ARG, "claude-3-opus")
    assert result == ["exec", "-", "--model", "claude-3-opus"], (
        f"Expected args_template + rendered model_arg, got: {result!r}"
    )


def test_compose_argv_v1_null_template_returns_args_template_only():
    """compose_argv on a v1 provider (null template) returns args_template only — no exception."""
    result = compose_argv(_V1_PROVIDER_NULL_TEMPLATE, "claude-3-opus")
    assert result == ["exec", "-"], (
        f"Expected args_template only for v1 provider, got: {result!r}"
    )


def test_compose_argv_empty_model_falls_back_to_default_model():
    """compose_argv with effective_model='' uses default_model from provider."""
    result = compose_argv(_V2_PROVIDER_WITH_MODEL_ARG, "")
    # default_model is "gpt-5-codex"
    assert result == ["exec", "-", "--model", "gpt-5-codex"], (
        f"Expected default_model fallback, got: {result!r}"
    )


def test_compose_argv_none_model_falls_back_to_default_model():
    """compose_argv with effective_model=None uses default_model from provider."""
    result = compose_argv(_V2_PROVIDER_WITH_MODEL_ARG, None)
    assert result == ["exec", "-", "--model", "gpt-5-codex"], (
        f"Expected default_model fallback, got: {result!r}"
    )


def test_compose_argv_both_empty_raises_value_error():
    """compose_argv raises ValueError when both effective_model and default_model are empty/null."""
    provider_no_default = {
        "args_template": ["run"],
        "model_arg_template": ["--model", "{model}"],
        "model_env_var": None,
        "default_model": None,
    }
    with pytest.raises(ValueError):
        compose_argv(provider_no_default, "")


def test_compose_argv_does_not_substitute_partial_placeholder():
    """{models} (not {model}) is NOT substituted — only exact {model} placeholder."""
    provider = {
        "args_template": [],
        "model_arg_template": ["--filter", "{models}", "--model", "{model}"],
        "model_env_var": None,
        "default_model": "gpt-5-codex",
    }
    result = compose_argv(provider, "my-model")
    assert result == ["--filter", "{models}", "--model", "my-model"], (
        f"Partial placeholder {{models}} should not be substituted, got: {result!r}"
    )


def test_compose_argv_returns_new_list_not_mutating_provider():
    """compose_argv returns a new list; the original provider dict is not mutated."""
    provider = dict(_V2_PROVIDER_WITH_MODEL_ARG)
    original_template = list(provider["args_template"])
    compose_argv(provider, "test-model")
    assert provider["args_template"] == original_template, (
        "compose_argv must not mutate provider['args_template']"
    )


# ---------------------------------------------------------------------------
# build_env extended tests (T004)
# ---------------------------------------------------------------------------


def test_build_env_model_env_var_set_when_model_arg_template_null():
    """build_env sets model_env_var when model_arg_template is null and effective_model passed."""
    provider = {
        "model_env_var": "OPENAI_MODEL",
        "model_arg_template": None,
    }
    base = {"OTHER": "value"}
    result = build_env(provider, base_env=base, effective_model="gpt-5-codex")
    assert result["OPENAI_MODEL"] == "gpt-5-codex", (
        f"Expected OPENAI_MODEL='gpt-5-codex', got: {result.get('OPENAI_MODEL')!r}"
    )
    assert result["OTHER"] == "value"


def test_build_env_no_model_env_var_set_when_neither_configured():
    """build_env returns base_env unchanged (plus CLAUDECODE) when neither model field is set."""
    provider: dict = {}
    base = {"SOME_VAR": "val"}
    result = build_env(provider, base_env=base)
    assert result["SOME_VAR"] == "val"
    assert result["CLAUDECODE"] == ""
    # No extra keys beyond what base has + CLAUDECODE
    extra_keys = set(result.keys()) - set(base.keys()) - {"CLAUDECODE"}
    assert not extra_keys, f"Unexpected extra keys: {extra_keys}"


def test_build_env_both_model_arg_and_env_var_does_not_set_env_var(capsys):
    """build_env does NOT set model_env_var when model_arg_template is also set (arg takes precedence)."""
    provider = {
        "model_env_var": "MY_MODEL_VAR",
        "model_arg_template": ["--model", "{model}"],
    }
    base: dict = {}
    result = build_env(provider, base_env=base, effective_model="my-model")
    assert "MY_MODEL_VAR" not in result, (
        "model_env_var must not be set when model_arg_template is also present"
    )
    # The warning must be emitted to stderr.
    captured = capsys.readouterr()
    assert "model_env_var_ignored" in captured.err, (
        f"Expected 'model_env_var_ignored' in stderr; got: {captured.err!r}"
    )


def test_build_env_no_model_injection_when_effective_model_empty():
    """build_env does not inject model_env_var when effective_model is empty string."""
    provider = {
        "model_env_var": "MY_MODEL_VAR",
        "model_arg_template": None,
    }
    base: dict = {}
    result = build_env(provider, base_env=base, effective_model="")
    assert "MY_MODEL_VAR" not in result


def test_build_env_backward_compat_no_effective_model():
    """build_env without effective_model param behaves identically to pre-T004 behavior."""
    provider = {"auth_env": "MY_TOKEN"}
    base = {"MY_TOKEN": "secret", "OTHER": "val"}
    result = build_env(provider, base_env=base)
    assert result["MY_TOKEN"] == "secret"
    assert result["OTHER"] == "val"
    assert result["CLAUDECODE"] == ""


# ---------------------------------------------------------------------------
# T005: Provider alias resolution + memoized provider_alias_used event
# ---------------------------------------------------------------------------

def _make_merged(
    roles: dict,
    providers: dict,
    aliases: dict,
) -> dict:
    """Build a minimal merged config dict for resolve() calls."""
    return {"roles": roles, "providers": providers, "aliases": aliases}


def _make_fake_provider(command: str = "true") -> dict:
    """Return a minimal v2-upgraded provider descriptor."""
    return {
        "kind": "cli",
        "command": command,
        "args_template": [],
        "stdin": False,
        "timeout_s": 30,
        "model_label": "Test",
        "model_arg_template": None,
        "model_env_var": None,
        "default_model": None,
    }


def _fresh_rp_module() -> types.ModuleType:
    """
    Return a freshly-imported copy of resolve-provider.py with its module-level
    sets reset to empty.  Used to isolate memoization state between tests.
    """
    spec = importlib.util.spec_from_file_location(
        f"resolve_provider_fresh_{id(object())}",
        _RESOLVE_PROVIDER_SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestAliasSubstitution:
    """resolve() passes the looked-up provider name through alias resolution."""

    def test_alias_substitutes_old_name_to_new(self, monkeypatch):
        """aliases: {codex: codex-cli} + role bound to 'codex' resolves to 'codex-cli'."""
        mod = _fresh_rp_module()
        aliases = {"codex": "codex-cli"}
        providers = {"codex-cli": _make_fake_provider()}
        merged = _make_merged(
            roles={"consultant_primary": "codex"},
            providers=providers,
            aliases=aliases,
        )

        emitted: list[tuple] = []

        def fake_emit_alias(old, new):
            emitted.append((old, new))

        monkeypatch.setattr(mod, "_emit_alias_used", fake_emit_alias)
        # Patch shutil.which to make the 'true' command appear on PATH
        monkeypatch.setattr(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        result = mod.resolve("consultant_primary", merged)

        assert result["provider"] == "codex-cli", (
            f"Expected provider='codex-cli' after alias substitution, got {result['provider']!r}"
        )
        assert ("codex", "codex-cli") in emitted, (
            "Expected provider_alias_used event for (codex → codex-cli)"
        )

    def test_no_alias_match_resolves_directly(self, monkeypatch):
        """When provider name is NOT in aliases, resolution is direct (no event)."""
        mod = _fresh_rp_module()
        aliases = {"codex": "codex-cli"}
        providers = {"gemini-cli": _make_fake_provider()}
        merged = _make_merged(
            roles={"consultant_secondary": "gemini-cli"},
            providers=providers,
            aliases=aliases,
        )

        emitted: list = []
        monkeypatch.setattr(mod, "_emit_alias_used", lambda old, new: emitted.append((old, new)))
        monkeypatch.setattr(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        result = mod.resolve("consultant_secondary", merged)

        assert result["provider"] == "gemini-cli"
        assert emitted == [], f"Expected no alias events, got: {emitted}"


class TestMemoization:
    """provider_alias_used fires exactly once per (process, old_name)."""

    def test_same_alias_100_times_emits_once(self, monkeypatch):
        """Resolving the same alias 100 times emits provider_alias_used exactly once."""
        mod = _fresh_rp_module()
        aliases = {"codex": "codex-cli"}
        providers = {"codex-cli": _make_fake_provider()}
        merged = _make_merged(
            roles={"consultant_primary": "codex"},
            providers=providers,
            aliases=aliases,
        )

        emit_count = 0

        def counting_emit(old, new):
            nonlocal emit_count
            emit_count += 1

        monkeypatch.setattr(mod, "_emit_alias_used", counting_emit)
        monkeypatch.setattr(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        for _ in range(100):
            mod.resolve("consultant_primary", merged)

        assert emit_count == 1, (
            f"Expected exactly 1 provider_alias_used emission for 100 resolves; got {emit_count}"
        )

    def test_two_different_aliases_emit_two_events(self, monkeypatch):
        """Two distinct aliases (codex, gemini) each emit one provider_alias_used event."""
        mod = _fresh_rp_module()
        aliases = {"codex": "codex-cli", "gemini": "gemini-cli"}
        providers = {
            "codex-cli": _make_fake_provider(),
            "gemini-cli": _make_fake_provider(),
        }

        emitted: list[tuple] = []

        def capturing_emit(old, new):
            emitted.append((old, new))

        monkeypatch.setattr(mod, "_emit_alias_used", capturing_emit)
        monkeypatch.setattr(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        merged_primary = _make_merged(
            roles={"consultant_primary": "codex"},
            providers=providers,
            aliases=aliases,
        )
        merged_secondary = _make_merged(
            roles={"consultant_secondary": "gemini"},
            providers=providers,
            aliases=aliases,
        )

        mod.resolve("consultant_primary", merged_primary)
        mod.resolve("consultant_secondary", merged_secondary)

        assert len(emitted) == 2, f"Expected 2 alias events (one per alias), got: {emitted}"
        old_names = {e[0] for e in emitted}
        assert old_names == {"codex", "gemini"}, (
            f"Expected events for 'codex' and 'gemini', got: {old_names}"
        )


class TestLegacyRolesFallback:
    """legacy_provider_roles_used fires alongside provider_alias_used when roles mapping is used."""

    def test_legacy_roles_with_alias_emits_both_events(self, monkeypatch):
        """When providers.json.roles[role]='codex' (alias), both events fire."""
        mod = _fresh_rp_module()
        aliases = {"codex": "codex-cli"}
        providers = {"codex-cli": _make_fake_provider()}
        # The roles section IS the legacy path; 'codex' is an alias
        merged = _make_merged(
            roles={"consultant_primary": "codex"},
            providers=providers,
            aliases=aliases,
        )

        alias_events: list[tuple] = []
        legacy_events: list[tuple] = []

        def capture_alias(old, new):
            alias_events.append((old, new))

        def capture_legacy(role, provider):
            legacy_events.append((role, provider))

        monkeypatch.setattr(mod, "_emit_alias_used", capture_alias)
        monkeypatch.setattr(mod, "_emit_legacy_roles_used", capture_legacy)
        monkeypatch.setattr(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        mod.resolve("consultant_primary", merged)

        assert len(alias_events) == 1, (
            f"Expected 1 provider_alias_used event, got: {alias_events}"
        )
        assert alias_events[0] == ("codex", "codex-cli"), (
            f"Wrong alias event payload: {alias_events[0]}"
        )
        assert len(legacy_events) == 1, (
            f"Expected 1 legacy_provider_roles_used event, got: {legacy_events}"
        )
        assert legacy_events[0] == ("consultant_primary", "codex"), (
            f"Wrong legacy event payload: {legacy_events[0]}"
        )

    def test_legacy_roles_without_alias_emits_only_legacy_event(self, monkeypatch):
        """When providers.json.roles[role]='codex-cli' (canonical), only legacy event fires."""
        mod = _fresh_rp_module()
        aliases = {"codex": "codex-cli"}
        providers = {"codex-cli": _make_fake_provider()}
        # canonical name in roles — no alias substitution needed
        merged = _make_merged(
            roles={"consultant_primary": "codex-cli"},
            providers=providers,
            aliases=aliases,
        )

        alias_events: list = []
        legacy_events: list = []

        monkeypatch.setattr(
            mod, "_emit_alias_used",
            lambda old, new: alias_events.append((old, new)),
        )
        monkeypatch.setattr(
            mod, "_emit_legacy_roles_used",
            lambda role, provider: legacy_events.append((role, provider)),
        )
        monkeypatch.setattr(mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        mod.resolve("consultant_primary", merged)

        assert alias_events == [], (
            f"Expected no alias events for canonical provider name, got: {alias_events}"
        )
        assert len(legacy_events) == 1, (
            f"Expected 1 legacy_provider_roles_used event, got: {legacy_events}"
        )


# ---------------------------------------------------------------------------
# T100: providers.json v2 upgrade with aliases
# ---------------------------------------------------------------------------

class TestProvidersJsonV2Upgrade:
    """Shipped .z-harness/providers.json must be version 2 with old + new entries and aliases."""

    def test_providers_json_is_version_2(self):
        """providers.json must declare version: 2 (not version 1)."""
        with _PROVIDERS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        assert data.get("version") == 2, (
            f"Expected version=2, got version={data.get('version')!r}. "
            "Run the T100 task to upgrade providers.json to v2."
        )

    def test_old_entries_still_present(self):
        """Backward-compat: codex, gemini entries must still exist after v2 upgrade."""
        with _PROVIDERS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        providers = data.get("providers", {})
        for old_name in ("codex", "gemini"):
            assert old_name in providers, (
                f"Old provider entry '{old_name}' must still be present in providers.json "
                f"for backward compatibility."
            )

    def test_new_cli_entries_present(self):
        """New -cli entries (codex-cli, gemini-cli, claude-cli) must exist in providers.json."""
        with _PROVIDERS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        providers = data.get("providers", {})
        for new_name in ("codex-cli", "gemini-cli", "claude-cli"):
            assert new_name in providers, (
                f"New provider entry '{new_name}' must exist in providers.json "
                f"after the v2 upgrade."
            )

    def test_aliases_map_populated(self):
        """Top-level aliases must map old names to new -cli names."""
        with _PROVIDERS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        aliases = data.get("aliases", {})
        expected = {"codex": "codex-cli", "gemini": "gemini-cli", "claude": "claude-cli"}
        for old_name, new_name in expected.items():
            assert aliases.get(old_name) == new_name, (
                f"aliases['{old_name}'] must be '{new_name}', got {aliases.get(old_name)!r}"
            )

    def test_new_entries_match_old_command_and_args(self):
        """-cli entries must have identical command/args_template/timeout_s as their old counterparts."""
        with _PROVIDERS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        providers = data.get("providers", {})
        for old_name, new_name in (("codex", "codex-cli"), ("gemini", "gemini-cli")):
            if old_name not in providers or new_name not in providers:
                continue
            old = providers[old_name]
            new = providers[new_name]
            assert old["command"] == new["command"], (
                f"{new_name}.command must match {old_name}.command: "
                f"{new['command']!r} != {old['command']!r}"
            )
            assert old["args_template"] == new["args_template"], (
                f"{new_name}.args_template must match {old_name}.args_template"
            )
            assert old["timeout_s"] == new["timeout_s"], (
                f"{new_name}.timeout_s must match {old_name}.timeout_s"
            )

    def test_resolve_consultant_primary_via_cli_entry(self, monkeypatch):
        """Integration: resolve(consultant_primary) succeeds when role points at a -cli entry.

        Simulates ensure-defaults writing runtime='codex-cli' into roles, then
        resolve-provider resolving it to a valid provider record (no 'provider not found' error).
        """
        with _PROVIDERS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        # Simulate ensure-defaults having written codex-cli as the runtime for consultant_primary.
        merged = {
            "roles": {"consultant_primary": "codex-cli"},
            "providers": data.get("providers", {}),
            "aliases": data.get("aliases", {}),
        }

        # Make shutil.which always succeed so we don't need real CLIs installed.
        import importlib
        resolve_provider_spec = importlib.util.spec_from_file_location(
            "resolve_provider_t100", _RESOLVE_PROVIDER_SCRIPT
        )
        resolve_provider_mod = importlib.util.module_from_spec(resolve_provider_spec)  # type: ignore[arg-type]
        resolve_provider_spec.loader.exec_module(resolve_provider_mod)  # type: ignore[union-attr]
        monkeypatch.setattr(resolve_provider_mod.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        result = resolve_provider_mod.resolve("consultant_primary", merged)

        assert result["provider"] == "codex-cli", (
            f"Expected provider='codex-cli' for consultant_primary, got {result['provider']!r}"
        )
        assert result["command"] == "codex", (
            f"Expected command='codex' for codex-cli provider, got {result['command']!r}"
        )
        assert isinstance(result["args_template"], list), (
            "Expected args_template to be a list in provider record"
        )
