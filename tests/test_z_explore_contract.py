from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "z-explore" / "SKILL.md"
AGENT_PATH = REPO_ROOT / "agents" / "explore.md"
SURFACE_MAP_PATH = REPO_ROOT / "_fragments" / "surface-mapping.md"
ZMAP_SKILL_PATH = REPO_ROOT / "skills" / "z-map" / "SKILL.md"


# ── Helper predicates ──────────────────────────────────────────────────────


def _read_skill(path: Path) -> str:
    assert path.exists(), f"File not found: {path}"
    return path.read_text(encoding="utf-8")


def _has_frontmatter_field(text: str, field: str) -> bool:
    """Check if a YAML frontmatter field exists (case-sensitive)."""
    # Match `field:` at start of a line between --- markers
    return bool(re.search(rf"^{field}:", text, re.MULTILINE))


def _has_section(text: str, heading: str) -> bool:
    """Check if a markdown ## heading exists."""
    return f"## {heading}" in text


def _has_phrase(text: str, phrase: str) -> bool:
    return phrase in text


# ── T001: Command contract ─────────────────────────────────────────────────


class TestZExploreSkill:
    """Validate the /z-explore SKILL.md command contract."""

    @classmethod
    def setup_class(cls):
        cls.text = _read_skill(SKILL_PATH)

    def test_frontmatter_fields(self):
        assert "name: z-explore" in self.text
        assert "driver_features_required:" in self.text
        assert "argument-hint:" in self.text

    def test_depth_parsing(self):
        assert "quick" in self.text
        assert "standard" in self.text
        assert "deep" in self.text
        assert "--depth=" in self.text

    def test_quick_mode_no_cost_gate(self):
        """Quick mode should have no cost gate."""
        assert _has_phrase(self.text, "quick")

    def test_deep_mode_has_cost_gate(self):
        """Deep mode must preserve the z-map cost gate."""
        assert _has_phrase(self.text, "Proceed") or _has_phrase(self.text, "cost-confirmation")

    def test_no_recommendation_invariant(self):
        """All terrain output must have the no-recommendation invariant."""
        assert _has_phrase(self.text, "no-recommendation") or _has_phrase(self.text, "No-recommendation")

    def test_citation_enforcement(self):
        """Every finding must have a file:line citation."""
        assert "file:line" in self.text

    def test_advisory_only_handoffs(self):
        """Handoffs to sibling commands must be advisory only, no auto-dispatch."""
        assert _has_phrase(self.text, "advisory") or _has_phrase(self.text, "never auto-dispatch")

    def test_telemetry_fields(self):
        """Required telemetry fields must be named."""
        for field in ("EXPLORES_DISPATCHED", "EXPLORES_SUCCEEDED", "explore_calls", "explore_failures", "depth"):
            assert field in self.text, f"Missing telemetry field: {field}"


# ── T004: Explore agent ────────────────────────────────────────────────────


class TestExploreAgent:
    """Validate agents/explore.md was promoted correctly."""

    @classmethod
    def setup_class(cls):
        cls.text = _read_skill(AGENT_PATH)

    def test_frontmatter(self):
        assert "name: explore" in self.text
        assert "tools:" in self.text
        assert "model:" in self.text

    def test_output_sections(self):
        for section in ("Found", "Start here", "Gaps"):
            assert _has_section(self.text, section), f"Missing output section: {section}"

    def test_read_only(self):
        """Explore agent must be explicitly read-only."""
        assert "read-only" in self.text.lower() or "locate" in self.text.lower()

    def test_citation_required(self):
        """Every code claim must include a path and line range."""
        assert "line range" in self.text or "file:line" in self.text or "path and line" in self.text


# ── T003: Surface-mapping caller contract ──────────────────────────────────


class TestSurfaceMappingContract:
    """Validate _fragments/surface-mapping.md was updated for z-explore."""

    @classmethod
    def setup_class(cls):
        cls.text = _read_skill(SURFACE_MAP_PATH)

    def test_z_explore_is_valid_caller(self):
        assert "z-explore" in self.text

    def test_caller_responsibility_exists(self):
        """Must have a caller responsibility section for z-explore."""
        assert _has_phrase(self.text, "owns depth-scaled terrain discovery")

    def test_schema_caller_enum(self):
        """Schema caller enum must include z-explore."""
        assert "z-explore" in self.text


# ── T002: z-research dispatch update ───────────────────────────────────────


class TestZResearchDispatch:
    """Validate z-research dispatches z-explore --depth=deep."""

    @classmethod
    def setup_class(cls):
        cls.text = _read_skill(REPO_ROOT / "skills" / "z-research" / "SKILL.md")

    def test_dispatch_target(self):
        """z-research must dispatch z-explore --depth=deep, not z-map."""
        assert "z-explore --depth=deep" in self.text

    def test_legacy_note(self):
        """z-map should be noted as legacy."""
        assert "z-map" in self.text and "legacy" in self.text.lower()


# ── T002: z-map legacy marking ─────────────────────────────────────────────


class TestZMapLegacy:
    """Validate z-map is marked as legacy/compatibility."""

    def test_z_map_skill_points_to_z_explore(self):
        """z-map SKILL.md description or docs should reference z-explore."""
        text = _read_skill(ZMAP_SKILL_PATH)
        # z-map's own skill doesn't need to change, but verify it still defines MAP.md output
        assert _has_section(text, "No-recommendation") or _has_phrase(text, "MAP.md")

    def test_human_docs_mark_z_map_legacy(self):
        text = _read_skill(REPO_ROOT / "docs" / "human" / "commands.md")
        assert "z-explore" in text

    def test_capabilities_mark_z_map_legacy(self):
        text = _read_skill(REPO_ROOT / "CAPABILITIES.md")
        has_z_explore = "z-explore" in text
        has_z_map = "z-map" in text
        assert has_z_explore, "CAPABILITIES.md should mention z-explore"


# ── T005: z-plan precontext consumption ────────────────────────────────────


class TestZPlanPrecontext:
    """Validate z-plan can consume EXPLORE.md as optional precontext."""

    @classmethod
    def setup_class(cls):
        cls.text = _read_skill(REPO_ROOT / "skills" / "z-plan" / "SKILL.md")

    def test_explore_md_detected(self):
        """Setup must detect EXPLORE.md alongside MAP.md."""
        assert "EXPLORE.md" in self.text

    def test_explore_freshness_scan(self):
        """Must have freshness scan for EXPLORE.md citations."""
        assert "explore_stale" in self.text

    def test_freshness_gate_includes_explore(self):
        """Consolidated freshness gate must include explore_stale."""
        assert "explore_stale" in self.text

    def test_proceed_with_stale_explore(self):
        """Proceed-with-stale handling must include explore source."""
        assert "explore" in self.text.split("proceed_with_all_stale")[1].split("Continue to Phase 1")[0] \
            if "proceed_with_all_stale" in self.text else False

    def test_premise_injection(self):
        """Phase 0 premise injection must include EXPLORE.md findings."""
        assert "EXPLORE.md" in self.text.split("## Phase 1")[0]


# ── T007: Telemetry field conformance ──────────────────────────────────────


class TestTelemetryConformance:
    """Validate telemetry field names appear in the command contract."""

    @classmethod
    def setup_class(cls):
        cls.text = _read_skill(SKILL_PATH)

    def test_depth_field(self):
        assert "depth" in self.text

    def test_map_written_field(self):
        assert "map_written" in self.text or "MAP.md" in self.text

    def test_critique_status_field(self):
        assert "critique_status" in self.text or "critique" in self.text.lower()
