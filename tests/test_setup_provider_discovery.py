"""tests/test_setup_provider_discovery.py — Regression coverage for
z-setup's provider-discovery wizard step (criterion #12).

Cases:
  wizard_body_invokes_discover_providers
    — skills/z-setup/SKILL.md's wizard-form body invokes
      scripts/discover-providers.py before launching scripts/setup.py wizard.
  discover_providers_cli_exit_zero_with_contract_keys
    — `python3 scripts/discover-providers.py` exits 0 and emits JSON with
      "providers" and "roles" keys. Only the stable contract is asserted
      (key presence), not specific discovered provider entries, since
      discovery reads $PATH and is environment-dependent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILL_MD = _REPO_ROOT / "skills" / "z-setup" / "SKILL.md"
_DISCOVER_SCRIPT = _REPO_ROOT / "scripts" / "discover-providers.py"


def _wizard_form_body(text: str) -> str:
    """Slice out the '## Wizard form' section body from SKILL.md text."""
    start = text.index("## Wizard form")
    # Next top-level (##) heading after the wizard form section, or EOF.
    next_heading = text.find("\n## ", start + 1)
    return text[start:] if next_heading == -1 else text[start:next_heading]


def test_wizard_body_invokes_discover_providers():
    text = _SKILL_MD.read_text(encoding="utf-8")
    body = _wizard_form_body(text)

    assert "discover-providers.py" in body, (
        "wizard-form body must invoke scripts/discover-providers.py"
    )

    discovery_idx = body.index("discover-providers.py")
    # Locate the setup.py ... wizard launch line (tokens, not exact text,
    # to stay resilient to whitespace/prefix churn).
    setup_idx = body.index("setup.py")
    wizard_idx = body.index("wizard", setup_idx)

    assert discovery_idx < setup_idx < wizard_idx, (
        "discover-providers.py must be invoked before the setup.py wizard launch"
    )


def test_discover_providers_cli_exit_zero_with_contract_keys():
    proc = subprocess.run(
        [sys.executable, str(_DISCOVER_SCRIPT)],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, proc.stderr

    data = json.loads(proc.stdout)
    assert "providers" in data
    assert "roles" in data
    assert isinstance(data["providers"], dict)
    assert isinstance(data["roles"], dict)


def test_discovery_is_deterministic_and_proposes_three_distinct_roles():
    with tempfile.TemporaryDirectory() as temp_dir:
        bin_dir = Path(temp_dir)
        for command in ("codex", "gemini", "claude"):
            executable = bin_dir / command
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        env = {**os.environ, "PATH": str(bin_dir)}
        first = subprocess.run(
            [sys.executable, str(_DISCOVER_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        second = subprocess.run(
            [sys.executable, str(_DISCOVER_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

    assert first.stdout == second.stdout
    roles = json.loads(first.stdout)["roles"]
    assert set(roles) == {"consultant_primary", "consultant_secondary", "reviewer"}
    assert len(set(roles.values())) == 3


def test_discovery_with_too_few_providers_emits_no_partial_role_proposal():
    with tempfile.TemporaryDirectory() as temp_dir:
        executable = Path(temp_dir) / "codex"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        result = subprocess.run(
            [sys.executable, str(_DISCOVER_SCRIPT)],
            env={**os.environ, "PATH": temp_dir},
            capture_output=True,
            text=True,
            check=True,
        )

    assert json.loads(result.stdout)["roles"] == {}
