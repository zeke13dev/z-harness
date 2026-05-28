"""
Helper for prepending persona body to a task prompt.

Orchestrators call this BEFORE constructing a Dispatcher.run() call.
The dispatcher itself stays thin — it accepts an already-composed prompt.
"""

from __future__ import annotations

from pathlib import Path


def prepend_persona(body_path: str | None, task_prompt: str) -> str:
    """Read persona body from body_path and prepend to task_prompt with a blank-line separator.

    If body_path is None or empty string, returns task_prompt unchanged.
    If body_path doesn't exist, raises FileNotFoundError.

    Frontmatter stripping: if the persona file begins with a YAML frontmatter
    block (delimited by ``---`` markers), only the content after the closing
    ``---`` is used as the body.

    Args:
        body_path: Absolute or relative path to the persona ``.md`` file, as
            returned in the ``persona_body_path`` field of ``resolve-persona.py
            resolve``.  Pass ``None`` or ``""`` to skip prepending.
        task_prompt: The role's task prompt text.

    Returns:
        ``body.rstrip() + "\\n\\n" + task_prompt`` when body_path is set, or
        ``task_prompt`` unchanged when body_path is falsy.
    """
    if not body_path:
        return task_prompt

    body = Path(body_path).read_text(encoding="utf-8")

    # Strip YAML frontmatter (between --- markers).
    if body.startswith("---\n"):
        end_idx = body.find("\n---\n", 4)
        if end_idx != -1:
            body = body[end_idx + 5:]

    return f"{body.rstrip()}\n\n{task_prompt}"
