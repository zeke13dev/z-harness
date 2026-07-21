"""Interactive-ish first-run setup for z-harness.

This is the small public CLI surface: detect the user's existing harnesses,
show provider/auth status, optionally install supported plugin targets, and
then hand off to the in-harness `/z-setup` wizard for deeper configuration.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import typer
from z_harness_cli import release_surface

_SUPPORTED_TARGETS = release_surface.explicit_setup_target_ids()
_PROVIDER_BINS = (
    ("claude", "Claude Code / Anthropic"),
    ("codex", "Codex / OpenAI"),
    ("gemini", "Gemini"),
    ("ollama", "Ollama local models"),
    ("agy", "Antigravity"),
)
_MANDATORY_PROVIDER_ROLES = (
    "consultant_primary",
    "consultant_secondary",
    "reviewer",
)
_SECRET_FIELD_TOKENS = frozenset(
    {
        "accesstoken",
        "apikey",
        "authtoken",
        "authorization",
        "bearer",
        "bearertoken",
        "clientsecret",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "idtoken",
        "password",
        "privatekey",
        "refreshtoken",
        "secret",
        "sessiontoken",
        "token",
        "tokens",
    }
)
_CREDENTIAL_HEADER_FAMILIES = frozenset(
    {
        "accesstoken",
        "apikey",
        "apitoken",
        "authtoken",
    }
)
_SECRET_HEADER_TOKENS = frozenset(
    {
        "authorization",
        "cookie",
        "proxyauthorization",
        "setcookie",
        *(
            f"{prefix}{family}"
            for prefix in ("", "x")
            for family in _CREDENTIAL_HEADER_FAMILIES
        ),
    }
)
_AUTH_ENV_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_BEARER_VALUE_RE = re.compile(r"(?i)(?:^|\s)bearer\s+\S+")
_ARGUMENT_FIELD_RE = re.compile(
    r"^\s*--?(?P<field>[^=\s]+)(?:=|\s+)"
)
_HEADER_ARGUMENT_RE = re.compile(
    r"^\s*(?:--headers?|-[Hh])(?:\s*=\s*|\s+)(?P<payload>.+?)\s*$",
    re.IGNORECASE,
)
_HEADER_OPTION_RE = re.compile(r"^\s*(?:--headers?|-[Hh])\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class HostSummary:
    name: str
    installed: bool
    version: str | None
    fidelity: str
    note: str


def _harness_root() -> Path:
    return Path(__file__).parent.parent.parent.resolve()


def _normalize_targets(target: str, *, surface: str | None = None) -> list[str]:
    if target == "all":
        return list(release_surface.setup_target_ids(surface))
    requested = [part.strip() for part in target.split(",") if part.strip()]
    invalid = [part for part in requested if part not in _SUPPORTED_TARGETS]
    if invalid:
        valid = ", ".join((*_SUPPORTED_TARGETS, "all"))
        typer.echo(f"Error: unknown setup target(s): {', '.join(invalid)}. Valid: {valid}", err=True)
        raise typer.Exit(code=2)
    return requested or list(release_surface.setup_target_ids(surface))


def _detect_hosts(selected: set[str], *, surface: str | None = None) -> list[HostSummary]:
    from z_harness_cli.adapters.registry import detect_all

    public_hosts = set(release_surface.public_release_hosts())
    prod_surface = release_surface.default_surface(surface) == "prod"
    summaries: list[HostSummary] = []
    for adapter, result in detect_all():
        if adapter.name not in _SUPPORTED_TARGETS:
            continue
        if prod_surface and adapter.name not in public_hosts and adapter.name not in selected:
            continue
        note = result.notes or ""
        if prod_surface and adapter.name not in public_hosts:
            note = f"{note}; dev/advanced explicit target".strip("; ")
        summaries.append(
            HostSummary(
                name=adapter.name,
                installed=result.installed,
                version=result.version,
                fidelity=adapter.fidelity_tier,
                note=note,
            )
        )
    if not prod_surface or "pi" in selected:
        summaries.append(
            HostSummary(
                name="pi",
                installed=True,
                version=None,
                fidelity="export-only",
                note="dev/advanced compatibility export target; no local binary probe"
                if prod_surface
                else "compatibility export target; no local binary probe",
            )
        )
    return summaries


def _provider_rows() -> list[tuple[str, str, bool, str | None]]:
    rows: list[tuple[str, str, bool, str | None]] = []
    for binary, label in _PROVIDER_BINS:
        path = shutil.which(binary)
        rows.append((binary, label, path is not None, path))
    return rows


def _run_provider_discovery() -> dict:
    script = _harness_root() / "scripts" / "discover-providers.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "provider discovery failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"provider discovery returned invalid JSON: {exc}") from exc


def _contains_literal_secret(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalize_field_name(str(key))
            if normalized == "authenv":
                if child is not None and not (
                    isinstance(child, str) and _AUTH_ENV_RE.fullmatch(child)
                ):
                    return True
                continue
            if _is_secret_field(str(key)) or _contains_literal_secret(child):
                return True
        return False
    if isinstance(value, list):
        for index, child in enumerate(value):
            if _contains_literal_secret(child):
                return True
            if (
                isinstance(child, str)
                and _HEADER_OPTION_RE.fullmatch(child)
                and index + 1 < len(value)
                and isinstance(value[index + 1], str)
                and _is_credential_header(value[index + 1])
            ):
                return True
        return False
    if isinstance(value, str):
        header_argument = _HEADER_ARGUMENT_RE.match(value)
        if header_argument and _is_credential_header(header_argument.group("payload")):
            return True
        if _is_credential_header(value):
            return True
        argument = _ARGUMENT_FIELD_RE.match(value)
        if argument and _is_secret_field(argument.group("field")):
            return True
        normalized = _normalize_field_name(value.strip().lstrip("-"))
        return _is_secret_field(normalized) or bool(_BEARER_VALUE_RE.search(value))
    return False


def _normalize_field_name(key: str) -> str:
    """Fold case and separators so apiKey, api-key, and api_key compare equally."""
    return "".join(character for character in key.casefold() if character.isalnum())


def _is_secret_field(key: str) -> bool:
    normalized = _normalize_field_name(key)
    if normalized == "authenv":
        return False
    return normalized in _SECRET_FIELD_TOKENS or normalized in _SECRET_HEADER_TOKENS


def _is_credential_header(value: str) -> bool:
    """Return whether a header literal has a known credential-bearing name."""
    name, separator, _ = value.partition(":")
    return bool(separator) and _normalize_field_name(name) in _SECRET_HEADER_TOKENS


def _canonical_role_bindings(data: dict) -> list[str]:
    """Apply the resolver's supported one-hop alias semantics to mandatory roles."""
    providers = data["providers"]
    aliases = data.get("aliases", {})
    if not isinstance(aliases, dict) or not all(
        isinstance(source, str) and isinstance(target, str)
        for source, target in aliases.items()
    ):
        raise ValueError("provider registry aliases must map strings to strings")
    for source in sorted(aliases):
        target = aliases[source]
        if target in aliases:
            reason = (
                "cyclic alias"
                if target == source or aliases.get(target) == source
                else "chained aliases are unsupported"
            )
            raise ValueError(f"provider alias {source!r} -> {target!r} is invalid: {reason}")
        if target not in providers:
            raise ValueError(
                f"provider alias {source!r} -> {target!r} is dangling"
            )
    return [aliases.get(data["roles"][role], data["roles"][role]) for role in _MANDATORY_PROVIDER_ROLES]


def _validate_provider_proposal(data: dict) -> None:
    providers = data.get("providers")
    roles = data.get("roles")
    if not isinstance(providers, dict) or not isinstance(roles, dict):
        raise ValueError("provider discovery must emit providers and roles objects")
    missing = [role for role in _MANDATORY_PROVIDER_ROLES if not roles.get(role)]
    if missing:
        raise ValueError(
            f"provider proposal is missing mandatory roles: {', '.join(missing)}"
        )
    if not all(isinstance(roles[role], str) for role in _MANDATORY_PROVIDER_ROLES):
        raise ValueError("mandatory provider role bindings must be strings")
    selected = _canonical_role_bindings(data)
    if len(set(selected)) != len(selected):
        raise ValueError("mandatory primary, secondary, and reviewer roles must be distinct")
    undefined = [name for name in selected if name not in providers]
    if undefined:
        raise ValueError(
            f"provider proposal references undefined providers: {', '.join(undefined)}"
        )
    if _contains_literal_secret(data):
        raise ValueError("provider proposal contains secret-bearing literal credential material")


def _preflight_provider_registry(data: dict) -> None:
    resolver = _harness_root() / "scripts" / "resolve-provider.py"
    with tempfile.TemporaryDirectory(prefix="z-harness-provider-preflight-") as temp_dir:
        root = Path(temp_dir)
        registry = root / "providers.json"
        registry.write_text(json.dumps(data), encoding="utf-8")
        config = root / "config.toml"
        config.write_text(
            'schema_version = 2\n\n[runtime]\nconsult = "on"\n',
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(root / "xdg")
        env["Z_HARNESS_REPO_PROVIDERS"] = str(registry)
        env["Z_HARNESS_REPO_CONFIG"] = str(config)
        result = subprocess.run(
            [sys.executable, str(resolver), "--preflight-all"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "provider role preflight failed")


def _provider_registry_path() -> Path:
    config_root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_root / "z-harness" / "providers.json"


def _load_provider_registry() -> dict:
    """Load the user-global registry; malformed input is a hard failure."""
    target = _provider_registry_path()
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load existing provider registry: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("existing provider registry must be a JSON object")
    version = data.get("version")
    if version not in (1, 2):
        raise ValueError(f"existing provider registry has unsupported version: {version!r}")
    for field in ("providers", "roles"):
        if not isinstance(data.get(field), dict):
            raise ValueError(f"existing provider registry {field} must be an object")
    aliases = data.get("aliases", {})
    if not isinstance(aliases, dict) or not all(
        isinstance(source, str) and isinstance(target_name, str)
        for source, target_name in aliases.items()
    ):
        raise ValueError("existing provider registry aliases must map strings to strings")
    return data


def _merge_provider_registry(existing: dict, proposal: dict) -> dict:
    """Merge onboarding data without replacing existing user choices."""
    if not existing:
        return proposal

    merged = dict(existing)
    providers = dict(existing["providers"])
    for name, descriptor in proposal["providers"].items():
        if name in providers and providers[name] != descriptor:
            raise ValueError(
                f"provider {name!r} conflicts with the existing registry; "
                "rename or remove that entry before approving onboarding"
            )
        providers.setdefault(name, descriptor)

    roles = dict(existing["roles"])
    for role in _MANDATORY_PROVIDER_ROLES:
        roles.setdefault(role, proposal["roles"][role])

    merged["version"] = max(existing["version"], proposal.get("version", 1))
    merged["providers"] = providers
    merged["roles"] = roles
    return merged


def _write_provider_registry(data: dict) -> Path:
    target = _provider_registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return target


def _onboard_providers(*, approved: bool, dry_run: bool) -> None:
    _echo_section("Provider onboarding")
    try:
        proposal = _run_provider_discovery()
        _validate_provider_proposal(proposal)
        registry = _merge_provider_registry(_load_provider_registry(), proposal)
        _validate_provider_proposal(registry)
        _preflight_provider_registry(registry)
    except ValueError as exc:
        typer.echo(f"provider registry not ready: {exc}", err=True)
        if dry_run or not approved:
            typer.echo(
                "provider onboarding unavailable; continuing without registry changes",
                err=True,
            )
            return
        raise typer.Exit(code=1) from exc

    roles = registry["roles"]
    for role in _MANDATORY_PROVIDER_ROLES:
        typer.echo(f"- {role}: {roles[role]}")
    typer.echo(f"user-global registry: {_provider_registry_path()}")
    if dry_run:
        typer.echo("provider registry dry run: no changes made")
        return
    if not approved:
        typer.echo(
            "provider registry approval required; rerun with --yes to persist this proposal"
        )
        return
    try:
        target = _write_provider_registry(registry)
    except OSError as exc:
        typer.echo(f"provider registry write failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"provider registry written: {target}")


def _echo_section(title: str) -> None:
    typer.echo(f"\n== {title} ==")


def _print_host_summary(hosts: Iterable[HostSummary], selected: set[str]) -> None:
    _echo_section("Harnesses")
    for host in hosts:
        marker = "*" if host.name in selected else " "
        status = "found" if host.installed else "missing"
        version = f" ({host.version})" if host.version else ""
        note = f" — {host.note}" if host.note else ""
        typer.echo(f"{marker} {host.name:<7} {status:<7} fidelity={host.fidelity}{version}{note}")


def _print_provider_summary() -> None:
    _echo_section("Provider/auth CLIs")
    for binary, label, installed, path in _provider_rows():
        status = "found" if installed else "missing"
        suffix = f" at {path}" if path else ""
        typer.echo(f"- {binary:<7} {status:<7} {label}{suffix}")


def _run_plugin_install(target: str, *, force: bool) -> None:
    from z_harness_cli.commands import install as install_cmd

    install_cmd.run(
        typer.Context(typer.Typer()),
        target=target,
        tarball=None,
        force=force,
        generate_exports=False,
    )


def _run_setup_py(args: list[str]) -> int:
    setup_py = _harness_root() / "scripts" / "setup.py"
    if not setup_py.is_file():
        typer.echo("setup.py is not available in this z-harness installation.", err=True)
        return 1
    return subprocess.run([sys.executable, str(setup_py), *args], check=False).returncode


def _next_steps(targets: list[str]) -> None:
    _echo_section("Next steps")
    if "claude" in targets:
        typer.echo("- Claude: restart/open Claude Code, then run `/z-setup status` or `/z-plan <task>`.")
    if "omp" in targets:
        typer.echo("- OMP: export or inject the OMP package, then launch OMP with `OMP_PLUGIN_ROOT` set.")
    if "pi" in targets:
        typer.echo("- pi (dev/advanced export-only): generate the compatibility export and copy it into the pi/Oh My Pi project as documented.")
    if "cursor" in targets:
        typer.echo("- Cursor (dev/advanced export-only): export `.cursor/skills`/rules into a project, then open Cursor Agent there.")
    if "codex" in targets:
        typer.echo("- Codex: restart Codex after plugin install; MCP registration is global and removable with `doctor --clear-mcp`.")
    typer.echo("- Deep config remains in-harness: run `/z-setup wizard` from your chosen harness.")


def run(
    *,
    target: str,
    install: bool,
    force: bool,
    posture: str | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """Run first-time setup/onboarding."""
    surface = release_surface.default_surface()
    targets = _normalize_targets(target, surface=surface)
    selected = set(targets)

    typer.echo(
        "z-harness setup — release defaults: "
        "Claude Code plugin + OMP package/export + Codex plugin"
    )
    _print_host_summary(_detect_hosts(selected, surface=surface), selected)
    _print_provider_summary()
    _onboard_providers(approved=yes, dry_run=dry_run)

    _echo_section("Plan")
    typer.echo(f"selected harnesses: {', '.join(targets)}")
    if posture:
        typer.echo(f"posture preset: {posture}")
    else:
        typer.echo("posture preset: unchanged (use --posture interactive|ci-batch|overnight)")

    plugin_install_targets = release_surface.plugin_install_target_ids(surface)
    installable = [name for name in targets if name in plugin_install_targets]
    export_only = [name for name in targets if name not in plugin_install_targets]
    if installable:
        typer.echo(f"plugin install targets: {', '.join(installable)}")
    if export_only:
        typer.echo(f"package/export or dev/advanced targets: {', '.join(export_only)}")

    if dry_run:
        typer.echo("dry run: no changes made")
        _next_steps(targets)
        return

    if posture:
        args = ["apply", "--posture", posture]
        if yes:
            args.append("--yes")
        rc = _run_setup_py(args)
        if rc:
            raise typer.Exit(code=rc)

    if install and installable:
        install_target = "all" if set(installable) == plugin_install_targets else installable[0]
        if len(installable) == 1:
            install_target = installable[0]
        typer.echo(f"\nInstalling plugin target: {install_target}")
        _run_plugin_install(install_target, force=force)
    elif install and not installable:
        typer.echo("No selected harness has a direct plugin installer in this surface; use export/inject next steps.")
    else:
        typer.echo("\nNo plugin install run. Pass --install to install direct plugin targets for this surface.")

    _next_steps(targets)
