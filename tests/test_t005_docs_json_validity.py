"""T005 documentation regression tests."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.resolve()
CHANGED_LLM_DOCS = (
    REPO_ROOT / "docs" / "llm" / "INDEX.json",
    REPO_ROOT / "docs" / "llm" / "capabilities-matrix.json",
    REPO_ROOT / "docs" / "llm" / "multi-ide-exports.json",
    REPO_ROOT / "docs" / "llm" / "pi-export.json",
)


def test_changed_llm_docs_are_valid_json() -> None:
    for path in CHANGED_LLM_DOCS:
        with path.open(encoding="utf-8") as handle:
            json.load(handle)
