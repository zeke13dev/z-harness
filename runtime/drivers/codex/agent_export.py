"""Native Codex custom agent export helpers."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class NativeAgentExportResult:
    """Files and warnings produced while exporting native Codex agents."""

    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _toml_string(value: str) -> str:
    """Return *value* as a TOML basic string using JSON-compatible escaping."""
    return json.dumps(value, ensure_ascii=True)


def _comment_value(value: str) -> str:
    """Collapse untrusted comment text to one line."""
    return " ".join(str(value).splitlines())


def _developer_instructions(entry: dict[str, Any]) -> str:
    return str(entry.get("body", "")).lstrip("\n")


def _contract_payload(entry: dict[str, Any]) -> dict[str, Any]:
    fm = entry.get("frontmatter", {})
    payload: dict[str, Any] = {
        "name": str(fm.get("name", "")).strip(),
        "description": str(fm.get("description", "")).strip(),
        "developer_instructions": _developer_instructions(entry),
    }

    model = str(fm.get("model", "")).strip()
    if model:
        payload["model"] = model

    schema_version = str(fm.get("schema_version", "")).strip()
    if schema_version:
        try:
            payload["schema_version"] = int(schema_version)
        except ValueError:
            payload["schema_version"] = schema_version

    return payload


def _manual_contract_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field_name in ("name", "description", "developer_instructions"):
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field_name} must be a non-empty string")

    name = payload.get("name")
    if isinstance(name, str) and name and not _AGENT_NAME_RE.fullmatch(name):
        errors.append(
            "name must start with an ASCII letter or digit and contain only "
            "ASCII letters, digits, underscores, or hyphens"
        )

    if "schema_version" in payload and payload["schema_version"] != 1:
        errors.append("schema_version must be 1 when present")

    return errors


def validate_agent_entry(entry: dict[str, Any]) -> list[str]:
    """Validate an enumerated source agent entry for native Codex export."""
    payload = _contract_payload(entry)
    manual_errors = _manual_contract_errors(payload)
    if manual_errors:
        return manual_errors

    try:
        from runtime.validate import validate

        validate("agent", payload)
    except ImportError:
        # Minimal installations may omit jsonschema; the manual checks above
        # cover the source fields needed for a valid Codex custom agent.
        return []
    except Exception as exc:  # noqa: BLE001 - preserve schema failure detail
        message = getattr(exc, "message", str(exc))
        return [f"agent contract validation failed: {message}"]

    return []


def safe_agent_filename(name: str) -> str:
    """Return the conventional safe TOML filename stem for a Codex agent name."""
    safe = _SAFE_FILENAME_RE.sub("-", name.strip()).strip("-")
    return safe or "agent"


def render_agent_toml(entry: dict[str, Any]) -> str:
    """Render one enumerated source agent entry as Codex custom-agent TOML."""
    payload = _contract_payload(entry)
    source_path = entry.get("source_path")
    source_label = (
        f"agents/{source_path.name}"
        if isinstance(source_path, Path)
        else str(entry.get("id", payload["name"]))
    )
    model = payload.get("model", "")

    lines = [
        f"# Source: {_comment_value(source_label)}\n",
    ]
    if model:
        lines.append(f"model = {_toml_string(model)}\n")
    lines.extend(
        [
            f"name = {_toml_string(payload['name'])}\n",
            f"description = {_toml_string(payload['description'])}\n",
            f"developer_instructions = {_toml_string(payload['developer_instructions'])}\n",
        ]
    )
    return "".join(lines)


def export_native_agents(
    agents: list[dict[str, Any]],
    export_root: Path,
) -> NativeAgentExportResult:
    """Write Codex native custom agents under ``.codex/agents/``."""
    export_root = Path(export_root).resolve()
    agents_dir = export_root / ".codex" / "agents"

    files: list[Path] = []
    warnings: list[str] = []
    seen_filenames: set[str] = set()

    for entry in agents:
        agent_id = str(entry.get("id", "<unknown>"))
        source_path = entry.get("source_path")
        source_label = (
            str(source_path)
            if isinstance(source_path, Path)
            else f"agents/{agent_id}.md"
        )

        entry_errors = validate_agent_entry(entry)
        if entry_errors:
            warnings.extend(f"{source_label}: {error}" for error in entry_errors)
            continue

        name = _contract_payload(entry)["name"]
        if name != agent_id:
            warnings.append(
                f"{source_label}: frontmatter name {name!r} does not match "
                f"source filename stem {agent_id!r}"
            )
            continue

        filename = f"{safe_agent_filename(name)}.toml"
        if filename in seen_filenames:
            warnings.append(
                f"{source_label}: duplicate native Codex agent filename {filename!r}"
            )
            continue
        seen_filenames.add(filename)

        text = render_agent_toml(entry)
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            warnings.append(f"{source_label}: rendered TOML is invalid: {exc}")
            continue

        out_path = agents_dir / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        files.append(out_path)

    return NativeAgentExportResult(files=files, warnings=warnings)
