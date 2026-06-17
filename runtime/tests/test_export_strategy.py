"""
runtime/tests/test_export_strategy.py

Unit tests for the T010 strategy helpers added to
``runtime/drivers/_export_utils.py``:

  - ``_ALWAYS_ON_AGENTS``        — frozenset constant
  - ``select_sources``           — pure subset-selection helper
  - ``resolve_strategy``         — subprocess-based effective-strategy reader

Strategy semantics under test
------------------------------
  pointer  → exactly 1 entry, in "agents"; "commands"/"skills" are empty.
  curated  → agents filtered to _ALWAYS_ON_AGENTS; commands/skills pass through.
  full     → all sources returned unchanged.

Effective-strategy fallback
----------------------------
  When config.py returns a recognised value → use it.
  When config.py is missing / returns non-zero → fall back to default_strategy.
  When config.py returns an unrecognised value → fall back to default_strategy.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from runtime.drivers._export_utils import (
    _ALWAYS_ON_AGENTS,
    _POINTER_ENTRY,
    _VALID_STRATEGIES,
    select_sources,
    resolve_strategy,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _make_agent(agent_id: str) -> dict[str, Any]:
    """Return a minimal agent entry dict for testing."""
    return {
        "id": agent_id,
        "source_path": Path(f"/repo/agents/{agent_id}.md"),
        "frontmatter": {"description": f"Test agent {agent_id}"},
        "body": f"# {agent_id}\n",
    }


def _make_command(cmd_id: str) -> dict[str, Any]:
    return {
        "id": cmd_id,
        "source_path": Path(f"/repo/commands/{cmd_id}.md"),
        "frontmatter": {"description": f"Test command {cmd_id}"},
        "body": f"# {cmd_id}\n",
    }


def _make_skill(skill_id: str) -> dict[str, Any]:
    return {
        "id": skill_id,
        "source_path": Path(f"/repo/skills/{skill_id}/SKILL.md"),
        "frontmatter": {"description": f"Test skill {skill_id}"},
        "body": f"# {skill_id}\n",
    }


def _make_sources(
    agent_ids: list[str] | None = None,
    command_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build a synthetic sources dict for select_sources tests."""
    return {
        "commands": [_make_command(c) for c in (command_ids or [])],
        "agents":   [_make_agent(a) for a in (agent_ids or [])],
        "skills":   [_make_skill(s) for s in (skill_ids or [])],
    }


# ---------------------------------------------------------------------------
# _ALWAYS_ON_AGENTS
# ---------------------------------------------------------------------------

class TestAlwaysOnAgents:
    """_ALWAYS_ON_AGENTS is a frozenset and contains the canonical IDs."""

    def test_is_frozenset(self):
        assert isinstance(_ALWAYS_ON_AGENTS, frozenset)

    def test_contains_canonical_ids(self):
        expected = {"implementer", "reviewer", "auditor", "mr-reviewer", "remote-runner"}
        assert _ALWAYS_ON_AGENTS == expected, (
            f"_ALWAYS_ON_AGENTS mismatch: got {_ALWAYS_ON_AGENTS}, want {expected}"
        )

    def test_antigravity_import_matches(self):
        """antigravity/export.py must import the SAME object from _export_utils."""
        from runtime.drivers.antigravity.export import _ALWAYS_ON_AGENTS as agy_set
        assert agy_set is _ALWAYS_ON_AGENTS or agy_set == _ALWAYS_ON_AGENTS, (
            "antigravity/export.py _ALWAYS_ON_AGENTS differs from _export_utils._ALWAYS_ON_AGENTS"
        )


# ---------------------------------------------------------------------------
# select_sources — pointer strategy
# ---------------------------------------------------------------------------

class TestSelectSourcesPointer:
    """pointer strategy: exactly 1 item total; only in 'agents'; commands/skills empty."""

    def _full_sources(self) -> dict:
        return _make_sources(
            agent_ids=["implementer", "reviewer", "auditor", "doc-fetcher"],
            command_ids=["z-plan", "z-implement-all"],
            skill_ids=["z-debug"],
        )

    def test_pointer_returns_exactly_one_item(self):
        result = select_sources("pointer", self._full_sources())
        total = sum(len(v) for v in result.values())
        assert total == 1, f"pointer strategy should emit 1 item, got {total}"

    def test_pointer_item_is_in_agents(self):
        result = select_sources("pointer", self._full_sources())
        assert len(result["agents"]) == 1

    def test_pointer_commands_empty(self):
        result = select_sources("pointer", self._full_sources())
        assert result["commands"] == []

    def test_pointer_skills_empty(self):
        result = select_sources("pointer", self._full_sources())
        assert result["skills"] == []

    def test_pointer_default_doc_is_pointer_entry(self):
        result = select_sources("pointer", self._full_sources())
        agent = result["agents"][0]
        assert agent["id"] == _POINTER_ENTRY["id"]

    def test_pointer_custom_doc_override(self):
        """Callers can override the pointer doc via pointer_doc=."""
        custom = {"id": "custom-ptr", "source_path": None, "frontmatter": {}, "body": ""}
        result = select_sources("pointer", self._full_sources(), pointer_doc=custom)
        assert result["agents"][0]["id"] == "custom-ptr"

    def test_pointer_empty_sources_still_one_item(self):
        """pointer must still return 1 item even when all sources are empty."""
        result = select_sources("pointer", _make_sources())
        total = sum(len(v) for v in result.values())
        assert total == 1

    def test_full_strategy_would_return_more_than_one(self):
        """Regression guard: confirm full returns >1 so pointer ≠ full."""
        sources = self._full_sources()
        full_result = select_sources("full", sources)
        total = sum(len(v) for v in full_result.values())
        assert total > 1


# ---------------------------------------------------------------------------
# select_sources — curated strategy
# ---------------------------------------------------------------------------

class TestSelectSourcesCurated:
    """curated strategy: agents filtered to _ALWAYS_ON_AGENTS; others pass through."""

    def _sources_with_mixed_agents(self) -> dict:
        # Mix of always-on and non-always-on agents
        return _make_sources(
            agent_ids=["implementer", "reviewer", "doc-fetcher", "complexity-classifier"],
            command_ids=["z-plan"],
            skill_ids=["z-debug"],
        )

    def test_curated_agents_are_subset_of_always_on(self):
        result = select_sources("curated", self._sources_with_mixed_agents())
        for entry in result["agents"]:
            assert entry["id"] in _ALWAYS_ON_AGENTS, (
                f"curated result contains non-always-on agent: {entry['id']}"
            )

    def test_curated_excludes_non_always_on_agents(self):
        result = select_sources("curated", self._sources_with_mixed_agents())
        agent_ids = {e["id"] for e in result["agents"]}
        assert "doc-fetcher" not in agent_ids
        assert "complexity-classifier" not in agent_ids

    def test_curated_includes_always_on_agents_present_in_sources(self):
        result = select_sources("curated", self._sources_with_mixed_agents())
        agent_ids = {e["id"] for e in result["agents"]}
        # implementer and reviewer are in sources AND in _ALWAYS_ON_AGENTS
        assert "implementer" in agent_ids
        assert "reviewer" in agent_ids

    def test_curated_commands_pass_through(self):
        result = select_sources("curated", self._sources_with_mixed_agents())
        assert len(result["commands"]) == 1
        assert result["commands"][0]["id"] == "z-plan"

    def test_curated_skills_pass_through(self):
        result = select_sources("curated", self._sources_with_mixed_agents())
        assert len(result["skills"]) == 1
        assert result["skills"][0]["id"] == "z-debug"

    def test_curated_no_always_on_agents_in_sources_gives_empty_agents(self):
        """When no always-on agents exist in sources, agents list is empty."""
        sources = _make_sources(agent_ids=["doc-fetcher", "complexity-classifier"])
        result = select_sources("curated", sources)
        assert result["agents"] == []

    def test_curated_mirrors_always_on_agents_exactly(self):
        """All 5 canonical always-on agents in sources → all 5 in curated result."""
        all_always_on = list(_ALWAYS_ON_AGENTS) + ["doc-fetcher"]
        sources = _make_sources(agent_ids=all_always_on)
        result = select_sources("curated", sources)
        result_ids = {e["id"] for e in result["agents"]}
        assert result_ids == _ALWAYS_ON_AGENTS, (
            f"curated did not mirror _ALWAYS_ON_AGENTS exactly: got {result_ids}"
        )


# ---------------------------------------------------------------------------
# select_sources — full strategy
# ---------------------------------------------------------------------------

class TestSelectSourcesFull:
    """full strategy: all sources returned unchanged."""

    def _rich_sources(self) -> dict:
        return _make_sources(
            agent_ids=["implementer", "reviewer", "doc-fetcher", "complexity-classifier"],
            command_ids=["z-plan", "z-implement-all", "z-review-all"],
            skill_ids=["z-debug", "z-suggest-memory"],
        )

    def test_full_returns_all_agents(self):
        sources = self._rich_sources()
        result = select_sources("full", sources)
        assert len(result["agents"]) == len(sources["agents"])

    def test_full_returns_all_commands(self):
        sources = self._rich_sources()
        result = select_sources("full", sources)
        assert len(result["commands"]) == len(sources["commands"])

    def test_full_returns_all_skills(self):
        sources = self._rich_sources()
        result = select_sources("full", sources)
        assert len(result["skills"]) == len(sources["skills"])

    def test_full_preserves_entry_order(self):
        sources = self._rich_sources()
        result = select_sources("full", sources)
        assert [e["id"] for e in result["agents"]] == [e["id"] for e in sources["agents"]]
        assert [e["id"] for e in result["commands"]] == [e["id"] for e in sources["commands"]]

    def test_full_returns_new_dict(self):
        """select_sources must return a new dict (not the original) to avoid mutation."""
        sources = self._rich_sources()
        result = select_sources("full", sources)
        assert result is not sources

    def test_full_result_lists_are_copies(self):
        sources = self._rich_sources()
        result = select_sources("full", sources)
        result["agents"].clear()
        assert len(sources["agents"]) > 0, "original agents list was mutated"


# ---------------------------------------------------------------------------
# select_sources — invalid strategy
# ---------------------------------------------------------------------------

class TestSelectSourcesInvalidStrategy:
    def test_unknown_strategy_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            select_sources("bogus", _make_sources())

    def test_empty_strategy_raises_value_error(self):
        with pytest.raises(ValueError):
            select_sources("", _make_sources())


# ---------------------------------------------------------------------------
# resolve_strategy — config subprocess
# ---------------------------------------------------------------------------

class TestResolveStrategy:
    """resolve_strategy reads config.py and falls back to default_strategy."""

    def test_falls_back_when_repo_root_is_none(self):
        """When repo_root is None, must return the default_strategy."""
        result = resolve_strategy("curated", repo_root=None)
        assert result == "curated"

    def test_falls_back_when_repo_root_has_no_config_py(self, tmp_path):
        """When scripts/config.py does not exist, must return the default_strategy."""
        result = resolve_strategy("pointer", repo_root=tmp_path)
        assert result == "pointer"

    def test_reads_config_py_value(self, tmp_path):
        """When a minimal config.py prints a valid strategy, resolve_strategy returns it."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        # Write a minimal stub config.py that prints "full" for get export.strategy
        stub = textwrap.dedent("""\
            import sys
            if len(sys.argv) >= 3 and sys.argv[1] == "get" and sys.argv[2] == "export.strategy":
                print("full")
                sys.exit(0)
            sys.exit(1)
        """)
        (scripts_dir / "config.py").write_text(stub, encoding="utf-8")
        result = resolve_strategy("curated", repo_root=tmp_path)
        assert result == "full"

    def test_falls_back_on_nonzero_exit(self, tmp_path):
        """When config.py exits non-zero, return the default_strategy."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "config.py").write_text("import sys; sys.exit(1)", encoding="utf-8")
        result = resolve_strategy("curated", repo_root=tmp_path)
        assert result == "curated"

    def test_falls_back_on_unrecognised_value(self, tmp_path):
        """When config.py prints an unrecognised value, return the default_strategy."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "config.py").write_text(
            "import sys\nprint('unknown-strategy')\nsys.exit(0)", encoding="utf-8"
        )
        result = resolve_strategy("pointer", repo_root=tmp_path)
        assert result == "pointer"

    def test_falls_back_on_empty_output(self, tmp_path):
        """When config.py prints nothing, return the default_strategy."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "config.py").write_text(
            "import sys\nprint('')\nsys.exit(0)", encoding="utf-8"
        )
        result = resolve_strategy("full", repo_root=tmp_path)
        assert result == "full"

    def test_all_valid_strategies_accepted(self, tmp_path):
        """All three valid strategy values round-trip through resolve_strategy."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        for strategy in _VALID_STRATEGIES:
            (scripts_dir / "config.py").write_text(
                f"print({strategy!r})\nimport sys; sys.exit(0)", encoding="utf-8"
            )
            result = resolve_strategy("curated", repo_root=tmp_path)
            assert result == strategy, f"strategy {strategy!r} was not returned correctly"

    def test_real_repo_returns_valid_strategy(self):
        """resolve_strategy against the real repo must return a valid strategy."""
        result = resolve_strategy("curated", repo_root=_REPO_ROOT)
        assert result in _VALID_STRATEGIES, (
            f"resolve_strategy returned unrecognised value: {result!r}"
        )

    def test_default_strategy_used_as_fallback_not_discarded(self, tmp_path):
        """Explicitly verify default_strategy is the return value on failure."""
        # No scripts/config.py in tmp_path
        for default in ["pointer", "curated", "full"]:
            result = resolve_strategy(default, repo_root=tmp_path)
            assert result == default, (
                f"default_strategy {default!r} was not used as fallback"
            )

    def test_empty_string_from_config_falls_back_to_default(self, tmp_path):
        """When config.py returns '' (the sentinel), resolve_strategy must use default_strategy.

        Invariant: DEFAULTS['export']['strategy'] = "" means "defer to per-driver default".
        Failure class: sentinel '' treated as a valid strategy, overriding per-driver default.
        """
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        # Stub that emits the sentinel (empty string) — mimics the new DEFAULTS value
        (scripts_dir / "config.py").write_text(
            "import sys\nprint('')\nsys.exit(0)", encoding="utf-8"
        )
        for default in ["pointer", "curated", "full"]:
            result = resolve_strategy(default, repo_root=tmp_path)
            assert result == default, (
                f"sentinel '' should fall back to default_strategy {default!r}, "
                f"but resolve_strategy returned {result!r}"
            )
