"""
T006: cross-cutting integration tests for the host-aware four-tier model
routing system (host-aware-model-tiers plan).

T001-T004/T007 each ship their own per-layer tests (schema validation in
scripts/test_config.py, resolver unit tests in runtime/tests/test_dispatch.py,
provider-role tests in tests/test_resolve_provider.py). Those per-layer suites
mostly assert against a synthetic mirror of the matrix (a literal dict copied
from scripts/config.py DEFAULTS), so a future edit to the real DEFAULTS could
drift out of sync with the mirror and still leave every existing test green.

This module instead loads the REAL config via
``runtime.dispatch.dispatcher.load_model_routing_config`` and exercises the
whole routing matrix in one place: all four classes, both host families, the
implementer tier->class mapping with its applied-vs-advisory effort rule, and
the fixed native-agent fleet routing. A regression in any one of those layers
should fail a test in this file even if that layer's own dedicated test still
passes.

Run with:
    python -m pytest tests/test_config.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.dispatch.dispatcher import (
    load_model_routing_config,
    resolve_implementer_model,
    resolve_model_route,
    resolve_native_agent_model,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# The four-tier host-keyed matrix (INTENT.md "The four-tier host-keyed matrix").
_CLAUDE_MATRIX = {
    "cheap": ("haiku", ""),
    "low": ("sonnet", "medium"),
    "standard": ("sonnet", "high"),
    "deep": ("opus", "high"),
}
_GPT56_MATRIX = {
    "cheap": ("gpt-5.6-luna-low", ""),
    "low": ("gpt-5.6-terra-low", ""),
    "standard": ("gpt-5.6-terra-medium", ""),
    "deep": ("gpt-5.6-sol-medium", ""),
}


# ---------------------------------------------------------------------------
# 1. Full-matrix integration: all four classes, real DEFAULTS, both families.
# ---------------------------------------------------------------------------

def test_full_matrix_claude_host_resolves_real_config(monkeypatch):
    """Every class on a forced claude host resolves to the exact Claude column,
    read from the REAL scripts/config.py DEFAULTS (not a synthetic mirror)."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    values = load_model_routing_config(REPO_ROOT)
    for class_name, (expected_model, expected_effort) in _CLAUDE_MATRIX.items():
        resolved = resolve_model_route(class_name, values, source="test")
        assert resolved.route_kind == "class", class_name
        assert resolved.effective_model == expected_model, class_name
        assert resolved.effort == expected_effort, class_name


def test_full_matrix_pi_host_resolves_real_config(monkeypatch):
    """Every class on a forced pi host resolves to the exact gpt-5.6 column."""
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")
    values = load_model_routing_config(REPO_ROOT)
    for class_name, (expected_model, expected_effort) in _GPT56_MATRIX.items():
        resolved = resolve_model_route(class_name, values, source="test")
        assert resolved.route_kind == "class", class_name
        assert resolved.effective_model == expected_model, class_name
        assert resolved.effort == expected_effort, class_name


@pytest.mark.parametrize("host", ["codex", "cursor"])
def test_full_matrix_non_pi_non_claude_hosts_map_to_gpt56_family(host, monkeypatch):
    """Every non-claude host -- not just pi -- maps to the gpt-5.6 family column
    ("everything non-claude routes to gpt-5.6")."""
    monkeypatch.setenv("Z_HARNESS_HOST", host)
    values = load_model_routing_config(REPO_ROOT)
    for class_name, (expected_model, expected_effort) in _GPT56_MATRIX.items():
        resolved = resolve_model_route(class_name, values, source="test")
        assert resolved.effective_model == expected_model, (host, class_name)
        assert resolved.effort == expected_effort, (host, class_name)


# ---------------------------------------------------------------------------
# 2. Implementer tier->class mapping + applied-vs-advisory effort telemetry.
# ---------------------------------------------------------------------------

# Shipped default implementer tier -> class mapping (scripts/config.py DEFAULTS).
_IMPL_TIER_CLASS = {"low": "low", "medium": "standard", "high": "deep", "retry": "deep"}


@pytest.mark.parametrize("tier", ["low", "medium", "high", "retry"])
def test_implementer_tier_maps_to_expected_class_on_claude(tier, monkeypatch):
    """Each tier resolves through its class to the Claude (model, effort) pair;
    the resolved effort is a distinct non-empty value, i.e. advisory (Agent()
    applies model= per-call but has no per-call effort parameter)."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    values = load_model_routing_config(REPO_ROOT)
    resolved = resolve_implementer_model(tier, values)

    expected_class = _IMPL_TIER_CLASS[tier]
    expected_model, expected_effort = _CLAUDE_MATRIX[expected_class]
    assert resolved.route == expected_class
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort
    assert resolved.effort != ""  # non-empty -> advisory on claude (no per-call effort param)


@pytest.mark.parametrize("tier", ["low", "medium", "high", "retry"])
def test_implementer_tier_maps_to_expected_class_on_pi(tier, monkeypatch):
    """Each tier resolves through its class to the gpt-5.6 (model, effort) pair
    on pi; effort is baked into the model name, so it is applied (never advisory)."""
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")
    values = load_model_routing_config(REPO_ROOT)
    resolved = resolve_implementer_model(tier, values)

    expected_class = _IMPL_TIER_CLASS[tier]
    expected_model, expected_effort = _GPT56_MATRIX[expected_class]
    assert resolved.route == expected_class
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort == ""  # baked into the omp catalog model name


# ---------------------------------------------------------------------------
# 3. Fixed native-agent fleet routing: representative cheap/standard/deep
#    agents, plus the unmapped-agent frontmatter fallback.
# ---------------------------------------------------------------------------

_FLEET_REPRESENTATIVES = {
    "cheap": ("doc_fetcher", "haiku"),
    "standard": ("auditor", "sonnet"),
    "deep": ("research_judge", "opus"),
}


@pytest.mark.parametrize(
    "class_name,agent_id,frontmatter",
    [(c, a, f) for c, (a, f) in _FLEET_REPRESENTATIVES.items()],
)
def test_fleet_agent_routes_host_correct_model_on_claude(
    class_name, agent_id, frontmatter, monkeypatch
):
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    values = load_model_routing_config(REPO_ROOT)
    resolved = resolve_native_agent_model(agent_id, frontmatter, values)

    expected_model, expected_effort = _CLAUDE_MATRIX[class_name]
    assert resolved.route == class_name
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort


@pytest.mark.parametrize(
    "class_name,agent_id,frontmatter",
    [(c, a, f) for c, (a, f) in _FLEET_REPRESENTATIVES.items()],
)
def test_fleet_agent_routes_host_correct_model_on_pi(
    class_name, agent_id, frontmatter, monkeypatch
):
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")
    values = load_model_routing_config(REPO_ROOT)
    resolved = resolve_native_agent_model(agent_id, frontmatter, values)

    expected_model, expected_effort = _GPT56_MATRIX[class_name]
    assert resolved.route == class_name
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort


def test_unmapped_fleet_agent_falls_back_to_frontmatter_real_config(monkeypatch):
    """An agent id absent from model_routing.native_agents resolves via
    frontmatter, proving the fallback stays intact against the real config."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    values = load_model_routing_config(REPO_ROOT)
    resolved = resolve_native_agent_model("not_a_real_agent_xyz", "haiku", values)

    assert resolved.source == "frontmatter"
    assert resolved.route_kind == "exact"
    assert resolved.effective_model == "haiku"
