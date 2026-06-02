"""
Compat shim integration tests: resolve_provider and log_event.

Tests that:
  - resolve_provider("codex", repo_root) returns a dict with keys
    command, args_template, timeout_s when the codex provider is present.
  - log_event writes a line to z-harness/archive/<run_id>/events.jsonl
    containing schema_version: 1.

Run:
    cd /path/to/repo-root
    pytest runtime/tests/test_compat.py -v
"""

import importlib.util
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

from runtime.compat import log_event, resolve_provider

# ---------------------------------------------------------------------------
# Import scripts/resolve-provider.py as a module so we can clear its
# module-level _v1_upgrade_emitted set between tests.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
_RESOLVE_PROVIDER_SCRIPT = _SCRIPTS_DIR / "resolve-provider.py"
_spec = importlib.util.spec_from_file_location(
    "resolve_provider_script", _RESOLVE_PROVIDER_SCRIPT
)
_resolve_provider_module = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_resolve_provider_module)  # type: ignore[union-attr]

# Resolve repo root as the directory containing runtime/
_REPO_ROOT = Path(__file__).parent.parent.parent


def _events_path(run_id: str) -> Path:
    """Path to a run's events.jsonl under the resolved artifact base.

    The hermetic conftest fixture pins Z_HARNESS_BASE_DIR to a temp dir (the
    default base is now external), so events land at <base>/archive/<run>/.
    Falls back to the legacy in-repo path when the env var is unset.
    """
    base = os.environ.get("Z_HARNESS_BASE_DIR") or str(_REPO_ROOT / "z-harness")
    return Path(base) / "archive" / run_id / "events.jsonl"


# ---------------------------------------------------------------------------
# Autouse fixture: clear module-level upgrade tracker between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_upgrade_tracker() -> None:
    """
    Clear the _v1_upgrade_emitted set on the resolve-provider script module
    before each test to prevent cross-test state leakage.
    """
    _resolve_provider_module._v1_upgrade_emitted.clear()
    yield  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def unique_run_id() -> str:
    """Return a unique run_id with the test-compat- prefix."""
    return f"test-compat-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def archive_cleanup(unique_run_id: str):
    """Yield the run_id; clean up archive dir unconditionally after the test."""
    yield unique_run_id
    archive_dir = _events_path(unique_run_id).parent
    shutil.rmtree(archive_dir, ignore_errors=True)


@pytest.fixture()
def codex_providers_json(tmp_path: Path) -> Path:
    """
    Write a minimal v1 providers.json that defines 'codex' as both a role and
    provider, then return its path.

    Using Z_HARNESS_REPO_PROVIDERS avoids relying on repo's .z-harness layout
    and keeps the test hermetic.
    """
    providers = {
        "version": 1,
        "roles": {
            "codex": "codex",
        },
        "providers": {
            "codex": {
                "kind": "cli",
                "command": "codex",
                "args_template": ["exec", "-"],
                "stdin": True,
                "timeout_s": 300,
                "model_label": "gpt-5-codex",
            }
        },
    }
    path = tmp_path / "providers.json"
    path.write_text(json.dumps(providers), encoding="utf-8")
    return path


@pytest.fixture()
def codex_providers_v2_json(tmp_path: Path) -> Path:
    """
    Write a v2 providers.json with new optional fields populated.
    """
    providers = {
        "version": 2,
        "roles": {
            "codex": "codex-cli",
        },
        "providers": {
            "codex-cli": {
                "kind": "cli",
                "command": "codex",
                "args_template": ["exec", "-"],
                "model_arg_template": ["--model", "{model}"],
                "model_env_var": "OPENAI_MODEL",
                "default_model": "gpt-5-codex",
                "stdin": True,
                "timeout_s": 300,
                "model_label": "gpt-5-codex",
            }
        },
        "aliases": {
            "codex": "codex-cli",
        },
    }
    path = tmp_path / "providers_v2.json"
    path.write_text(json.dumps(providers), encoding="utf-8")
    return path


@pytest.fixture()
def codex_providers_v2_null_fields_json(tmp_path: Path) -> Path:
    """
    Write a v2 providers.json with the new optional fields explicitly null.
    """
    providers = {
        "version": 2,
        "roles": {
            "codex": "codex-cli",
        },
        "providers": {
            "codex-cli": {
                "kind": "cli",
                "command": "codex",
                "args_template": ["exec", "-"],
                "model_arg_template": None,
                "model_env_var": None,
                "default_model": None,
                "stdin": True,
                "timeout_s": 300,
                "model_label": "gpt-5-codex",
            }
        },
    }
    path = tmp_path / "providers_v2_null.json"
    path.write_text(json.dumps(providers), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests: resolve_provider
# ---------------------------------------------------------------------------


def test_resolve_provider_codex_returns_required_keys(
    codex_providers_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    resolve_provider("codex", repo_root) returns a dict containing at minimum
    command, args_template, and timeout_s when the codex provider is defined.
    """
    monkeypatch.setenv("Z_HARNESS_REPO_PROVIDERS", str(codex_providers_json))

    result = resolve_provider("codex", str(_REPO_ROOT))

    assert isinstance(result, dict), "resolve_provider must return a dict"
    for key in ("command", "args_template", "timeout_s"):
        assert key in result, f"Expected key {key!r} in result, got keys: {list(result.keys())}"


def test_resolve_provider_codex_command_value(
    codex_providers_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """command value must be the string 'codex'."""
    monkeypatch.setenv("Z_HARNESS_REPO_PROVIDERS", str(codex_providers_json))

    result = resolve_provider("codex", str(_REPO_ROOT))

    assert result["command"] == "codex"


def test_resolve_provider_codex_args_template_is_list(
    codex_providers_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """args_template must be a list."""
    monkeypatch.setenv("Z_HARNESS_REPO_PROVIDERS", str(codex_providers_json))

    result = resolve_provider("codex", str(_REPO_ROOT))

    assert isinstance(result["args_template"], list)


def test_resolve_provider_codex_timeout_s_is_positive_int(
    codex_providers_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """timeout_s must be a positive integer."""
    monkeypatch.setenv("Z_HARNESS_REPO_PROVIDERS", str(codex_providers_json))

    result = resolve_provider("codex", str(_REPO_ROOT))

    assert isinstance(result["timeout_s"], int) and result["timeout_s"] > 0


def test_resolve_provider_missing_script_raises_file_not_found(
    tmp_path: Path,
) -> None:
    """FileNotFoundError is raised when repo_root has no scripts/resolve-provider.py."""
    with pytest.raises(FileNotFoundError, match="resolve-provider.py"):
        resolve_provider("codex", str(tmp_path))


def test_resolve_provider_unknown_role_raises_runtime_error(
    codex_providers_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RuntimeError is raised when the role is not bound in the providers config."""
    monkeypatch.setenv("Z_HARNESS_REPO_PROVIDERS", str(codex_providers_json))

    with pytest.raises(RuntimeError):
        resolve_provider("nonexistent_role_xyz", str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Tests: log_event
# ---------------------------------------------------------------------------


def test_log_event_writes_events_jsonl(archive_cleanup: str) -> None:
    """
    log_event writes at least one line to z-harness/archive/<run_id>/events.jsonl.
    """
    run_id = archive_cleanup
    log_event(run_id, "test_event", {"x": 1}, str(_REPO_ROOT))

    events_path = _events_path(run_id)
    assert events_path.exists(), f"events.jsonl not found at {events_path}"


def test_log_event_schema_version_is_1(archive_cleanup: str) -> None:
    """
    Every line written to events.jsonl contains schema_version: 1.
    """
    run_id = archive_cleanup
    log_event(run_id, "test_event", {"x": 1}, str(_REPO_ROOT))

    events_path = _events_path(run_id)
    lines = [ln.strip() for ln in events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, "events.jsonl must contain at least one non-empty line"

    for line in lines:
        parsed = json.loads(line)
        assert parsed.get("schema_version") == 1, (
            f"Expected schema_version=1 in line: {line!r}"
        )


def test_log_event_payload_preserved(archive_cleanup: str) -> None:
    """
    The payload key 'x' is present in the written event line.
    """
    run_id = archive_cleanup
    log_event(run_id, "test_event", {"x": 42}, str(_REPO_ROOT))

    events_path = _events_path(run_id)
    lines = [ln.strip() for ln in events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    found = any(json.loads(ln).get("x") == 42 for ln in lines)
    assert found, "Payload key 'x' with value 42 not found in any events.jsonl line"


def test_log_event_kind_recorded(archive_cleanup: str) -> None:
    """
    The event kind is recorded in the written line.
    """
    run_id = archive_cleanup
    log_event(run_id, "test_event", {"x": 1}, str(_REPO_ROOT))

    events_path = _events_path(run_id)
    lines = [ln.strip() for ln in events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    found = any(json.loads(ln).get("kind") == "test_event" for ln in lines)
    assert found, "Expected kind='test_event' in at least one events.jsonl line"


def test_log_event_missing_script_raises_file_not_found(
    tmp_path: Path,
) -> None:
    """FileNotFoundError is raised when repo_root has no scripts/log-event.sh."""
    with pytest.raises(FileNotFoundError, match="log-event.sh"):
        log_event("test-run-xyz", "test_event", {"x": 1}, str(tmp_path))


def test_log_event_injects_schema_version_when_absent(archive_cleanup: str) -> None:
    """
    schema_version: 1 is injected even when not present in the input payload.

    This is the failure-class guard: if compat.py stops injecting schema_version,
    this test must fail.
    """
    run_id = archive_cleanup
    # Payload deliberately omits schema_version
    log_event(run_id, "test_event", {"only_key": "value"}, str(_REPO_ROOT))

    events_path = _events_path(run_id)
    lines = [ln.strip() for ln in events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    for line in lines:
        parsed = json.loads(line)
        assert parsed.get("schema_version") == 1, (
            f"schema_version not injected — found: {line!r}"
        )


# ---------------------------------------------------------------------------
# Tests: v1 → v2 in-memory upgrade
# ---------------------------------------------------------------------------


def test_resolve_provider_v1_returns_new_fields_as_null(
    codex_providers_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A v1 providers.json must load without error, and the resolved descriptor
    must include model_arg_template, model_env_var, and default_model as null.

    Failure class: if the in-memory v1→v2 upgrade is missing or broken, these
    keys will be absent from the result.
    """
    monkeypatch.setenv("Z_HARNESS_REPO_PROVIDERS", str(codex_providers_json))

    result = resolve_provider("codex", str(_REPO_ROOT))

    assert isinstance(result, dict), "resolve_provider must return a dict"
    assert "model_arg_template" in result, "model_arg_template must be present after v1 upgrade"
    assert result["model_arg_template"] is None, (
        f"model_arg_template must be null for v1 provider, got: {result['model_arg_template']!r}"
    )
    assert "model_env_var" in result, "model_env_var must be present after v1 upgrade"
    assert result["model_env_var"] is None, (
        f"model_env_var must be null for v1 provider, got: {result['model_env_var']!r}"
    )
    assert "default_model" in result, "default_model must be present after v1 upgrade"
    assert result["default_model"] is None, (
        f"default_model must be null for v1 provider, got: {result['default_model']!r}"
    )


def test_resolve_provider_v2_returns_populated_new_fields(
    codex_providers_v2_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A v2 providers.json with populated model_arg_template, model_env_var,
    and default_model must return those values in the resolved descriptor.

    Failure class: if the resolve() function drops or ignores new v2 fields,
    this test must fail.
    """
    monkeypatch.setenv("Z_HARNESS_REPO_PROVIDERS", str(codex_providers_v2_json))

    result = resolve_provider("codex", str(_REPO_ROOT))

    assert result.get("model_arg_template") == ["--model", "{model}"], (
        f"Expected model_arg_template=[\"--model\", \"{{model}}\"], got: {result.get('model_arg_template')!r}"
    )
    assert result.get("model_env_var") == "OPENAI_MODEL", (
        f"Expected model_env_var='OPENAI_MODEL', got: {result.get('model_env_var')!r}"
    )
    assert result.get("default_model") == "gpt-5-codex", (
        f"Expected default_model='gpt-5-codex', got: {result.get('default_model')!r}"
    )


def test_resolve_provider_v2_null_fields_returns_null(
    codex_providers_v2_null_fields_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A v2 providers.json with explicit null for new fields must return those
    fields as null in the resolved descriptor.
    """
    monkeypatch.setenv("Z_HARNESS_REPO_PROVIDERS", str(codex_providers_v2_null_fields_json))

    result = resolve_provider("codex", str(_REPO_ROOT))

    assert result.get("model_arg_template") is None
    assert result.get("model_env_var") is None
    assert result.get("default_model") is None


def test_resolve_provider_v1_existing_tests_pass_with_v2_upgrade(
    codex_providers_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Existing fields (command, args_template, timeout_s) are preserved correctly
    after the v1→v2 in-memory upgrade.

    Failure class: if the upgrade accidentally drops or corrupts required fields,
    this test must fail.
    """
    monkeypatch.setenv("Z_HARNESS_REPO_PROVIDERS", str(codex_providers_json))

    result = resolve_provider("codex", str(_REPO_ROOT))

    assert result["command"] == "codex"
    assert isinstance(result["args_template"], list)
    assert isinstance(result["timeout_s"], int) and result["timeout_s"] > 0
