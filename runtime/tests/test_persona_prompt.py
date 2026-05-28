"""
Unit tests for runtime.dispatch.persona_prompt.prepend_persona.

Invariants tested:
- Body + "\\n\\n" + task_prompt when body_path is a valid file.
- task_prompt unchanged when body_path is None or empty string.
- YAML frontmatter is stripped from the persona file body.
- FileNotFoundError raised when body_path points to a missing file.

Run with:
    python -m pytest runtime/tests/test_persona_prompt.py -v
"""

from __future__ import annotations

import pytest

from runtime.dispatch.persona_prompt import prepend_persona


# ---------------------------------------------------------------------------
# None / empty body_path — passthrough
# ---------------------------------------------------------------------------


def test_prepend_persona_none_body_path_returns_task_prompt_unchanged():
    """prepend_persona(None, task) returns task unchanged."""
    task = "Do the thing."
    result = prepend_persona(None, task)
    assert result == task


def test_prepend_persona_empty_string_body_path_returns_task_prompt_unchanged():
    """prepend_persona('', task) returns task unchanged."""
    task = "Do the other thing."
    result = prepend_persona("", task)
    assert result == task


# ---------------------------------------------------------------------------
# Valid file — body + separator + task_prompt
# ---------------------------------------------------------------------------


def test_prepend_persona_appends_body_with_double_newline(tmp_path):
    """prepend_persona returns body.rstrip() + '\\n\\n' + task_prompt for a plain body file."""
    persona_file = tmp_path / "my-persona.md"
    persona_file.write_text("You are a skeptical consultant.\n", encoding="utf-8")

    task = "Review this code."
    result = prepend_persona(str(persona_file), task)

    assert result == "You are a skeptical consultant.\n\nReview this code."


def test_prepend_persona_strips_trailing_whitespace_from_body(tmp_path):
    """Trailing whitespace in the body is stripped before the separator."""
    persona_file = tmp_path / "persona.md"
    persona_file.write_text("Body text.   \n\n\n", encoding="utf-8")

    result = prepend_persona(str(persona_file), "task")

    # Body should be rstripped, then exactly two newlines before task.
    assert result == "Body text.\n\ntask"


# ---------------------------------------------------------------------------
# Frontmatter stripping
# ---------------------------------------------------------------------------


def test_prepend_persona_strips_yaml_frontmatter(tmp_path):
    """YAML frontmatter delimited by --- markers is excluded from the prepended body."""
    content = (
        "---\n"
        "name: codex-default-reviewer\n"
        "description: Adversarial reviewer.\n"
        "compatible_roles: [reviewer]\n"
        "contract: review-verdict\n"
        "---\n"
        "You are an adversarial code reviewer.\n"
    )
    persona_file = tmp_path / "reviewer.md"
    persona_file.write_text(content, encoding="utf-8")

    result = prepend_persona(str(persona_file), "task prompt")

    assert result.startswith("You are an adversarial code reviewer.")
    assert "name:" not in result
    assert "compatible_roles:" not in result


def test_prepend_persona_frontmatter_body_correctly_separated_from_task(tmp_path):
    """After frontmatter strip, body and task_prompt are joined by exactly two newlines."""
    content = "---\nname: test\n---\nPersona body line.\n"
    persona_file = tmp_path / "p.md"
    persona_file.write_text(content, encoding="utf-8")

    result = prepend_persona(str(persona_file), "My task.")

    assert result == "Persona body line.\n\nMy task."


def test_prepend_persona_no_frontmatter_uses_full_body(tmp_path):
    """A file without frontmatter uses the full file content as the body."""
    persona_file = tmp_path / "no-frontmatter.md"
    persona_file.write_text("Plain body without frontmatter.\n", encoding="utf-8")

    result = prepend_persona(str(persona_file), "task")

    assert result == "Plain body without frontmatter.\n\ntask"


def test_prepend_persona_unclosed_frontmatter_treated_as_plain_body(tmp_path):
    """A file starting with --- but missing a closing --- is treated as plain body (no strip)."""
    content = "---\nname: broken\nno closing marker\n"
    persona_file = tmp_path / "broken.md"
    persona_file.write_text(content, encoding="utf-8")

    result = prepend_persona(str(persona_file), "task")

    # Full content used as body since there's no closing ---.
    assert "---" in result
    assert result.endswith("\n\ntask")


# ---------------------------------------------------------------------------
# Missing file — FileNotFoundError
# ---------------------------------------------------------------------------


def test_prepend_persona_missing_file_raises_file_not_found_error(tmp_path):
    """prepend_persona raises FileNotFoundError when body_path does not exist."""
    missing = str(tmp_path / "does_not_exist.md")
    with pytest.raises(FileNotFoundError):
        prepend_persona(missing, "task prompt")
