#!/usr/bin/env python3
"""
resolve-persona.py <subcommand> [args]

Persona registry loader and resolver for z-harness.

Subcommands (T006 scope):
  list-personas       Print JSON array of {name, source_layer, path} — winner per name only.
  where <name>        Print all layer paths defining <name>, one per line, in load order.
                      Exits 1 with actionable error if name not found in any layer.

Subcommands (T007 scope):
  resolve <command> <role>  Resolve persona/model/runtime triple for a (command, role) pair.
  list-bindings [--command] Walk all configured bindings and print as JSON tree.
  validate                  Check that all bound personas exist + compatible_roles are known.
  read <name>               Print frontmatter + body of the winning persona file.

Layer load order (lowest → highest priority — later layer wins per name):
  1. personas/builtin/         (shipped with the harness)
  2. ~/.config/z-harness/personas/   (user-global; XDG_CONFIG_HOME respected)
  3. <repo>/.z-harness/personas/     (repo-local; git root discovered or Z_HARNESS_REPO_ROOT override)

On name collision across layers: emit persona_shadowed event ONCE per (process, name).

Output: stdout = JSON or plain text per subcommand; diagnostics → stderr.

Exit codes:
  0  success
  1  name not found, I/O error, or invariant violation
  2  bad usage or frontmatter parse error
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

# Kebab-case: starts with letter, contains only [a-z0-9-], no trailing hyphen.
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_NAME_TRAILING_HYPHEN_RE = re.compile(r"-$")


def _is_valid_persona_name(name: str) -> bool:
    """Return True if name matches ^[a-z][a-z0-9-]*$ and does not end with a hyphen."""
    return bool(_NAME_RE.match(name)) and not name.endswith("-")


# ---------------------------------------------------------------------------
# Shadow-event memoization (once per process per name)
# ---------------------------------------------------------------------------

# Module-level set of (name,) tuples for which persona_shadowed has already
# been emitted in this process.
_shadowed_emitted: set[str] = set()


def _emit_persona_shadowed(name: str, layers: list[str], winning_layer: str) -> None:
    """Emit persona_shadowed once per (process, name)."""
    if name in _shadowed_emitted:
        return
    _shadowed_emitted.add(name)

    print(
        f"[personas] persona_shadowed: {name!r} defined in {len(layers)} layers; "
        f"winner is {winning_layer!r}",
        file=sys.stderr,
    )

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if log_event.exists() and shutil.which("bash"):
        payload = json.dumps({
            "persona": name,
            "layers": layers,
            "winning_layer": winning_layer,
        })
        run_id = os.environ.get("Z_HARNESS_RUN_ID", "unknown-run")
        try:
            subprocess.run(
                ["bash", str(log_event), run_id, "persona_shadowed", payload],
                check=False,
                capture_output=True,
            )
        except OSError:
            pass  # log-event.sh unavailable — ignore


# ---------------------------------------------------------------------------
# Minimal YAML frontmatter parser (stdlib only — no PyYAML dependency)
# ---------------------------------------------------------------------------

def _strip_inline_comment(text: str) -> str:
    """
    Strip a YAML inline comment (unquoted, unbracketed `# ...`) from text.

    Rules:
    - If text is a double-quoted or single-quoted string, the `#` is part of
      the value — do not strip.
    - If text is an inline list `[...]` (bracket not yet closed), the `#`
      inside the brackets is part of a value — do not strip from within.
    - Otherwise, the first unquoted, non-bracket-interior `#` that follows
      whitespace starts a comment and is stripped along with everything after.
    """
    # If the value is a quoted scalar, return as-is.
    stripped = text.strip()
    if (stripped.startswith('"') and stripped.endswith('"')) or \
       (stripped.startswith("'") and stripped.endswith("'")):
        return text

    # Walk character by character; track quote and bracket nesting.
    in_double = False
    in_single = False
    bracket_depth = 0
    prev_was_space = False

    for idx, ch in enumerate(text):
        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '[' and not in_double and not in_single:
            bracket_depth += 1
        elif ch == ']' and not in_double and not in_single:
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == '#' and not in_double and not in_single and bracket_depth == 0:
            # A `#` that is the first char or is preceded by whitespace is a comment.
            if idx == 0 or prev_was_space:
                return text[:idx].rstrip()
        prev_was_space = ch == ' ' or ch == '\t'

    return text


def _split_inline_list(inner: str) -> list[str]:
    """
    Split a comma-separated inline list content (the part inside [...]) into items.

    Handles quoted strings: commas inside `"..."` or `'...'` are not split
    points. Explicit REJECT with ValueError if any item contains a quoted
    string that would be ambiguously split — i.e., if the raw inner contains
    mixed-quote items that cannot be cleanly handled.

    Strips surrounding quotes from each item after splitting.
    """
    items: list[str] = []
    current: list[str] = []
    in_double = False
    in_single = False

    for ch in inner:
        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
        elif ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
        elif ch == ',' and not in_double and not in_single:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    # Append last item
    last = "".join(current).strip()
    if last:
        items.append(last)

    # Strip surrounding quotes from each item
    result = []
    for item in items:
        s = item.strip()
        if (s.startswith('"') and s.endswith('"')) or \
           (s.startswith("'") and s.endswith("'")):
            result.append(s[1:-1])
        else:
            result.append(s)
    return result


def _parse_simple_yaml(text: str) -> dict:
    """
    Parse the subset of YAML used in persona frontmatter.

    Supported constructs:
      key: scalar value          (str; quoted or unquoted)
      key: [item1, item2]        (inline list of strings)
      key:                       (followed by '- item' lines — block list)

    Inline YAML comments (# ...) are stripped from unquoted scalars and
    from values after the closing bracket of inline lists.

    Raises ValueError on unsupported or malformed input.
    """
    result: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip blank lines and comments
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        if ":" not in line:
            raise ValueError(f"line {i+1}: expected 'key: value', got {line!r}")

        colon_idx = line.index(":")
        key = line[:colon_idx].strip()
        raw_val = line[colon_idx + 1:].strip()

        # Strip inline comment from the raw value (before bracket check so
        # that `[reviewer] # comment` works correctly).
        raw_val = _strip_inline_comment(raw_val)

        if raw_val.startswith("[") and raw_val.endswith("]"):
            # Inline list: [item1, item2] (quote-aware split)
            inner = raw_val[1:-1]
            if inner.strip():
                items = _split_inline_list(inner)
            else:
                items = []
            result[key] = items
            i += 1
        elif raw_val == "" and i + 1 < len(lines) and lines[i + 1].lstrip().startswith("- "):
            # Block list: next lines are '- item'
            items = []
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                item_raw = lines[i].lstrip()[2:]
                item_no_comment = _strip_inline_comment(item_raw).strip()
                item = item_no_comment.strip("'\"")
                items.append(item)
                i += 1
            result[key] = items
        else:
            # Scalar — strip optional surrounding quotes
            val = raw_val.strip("'\"")
            result[key] = val
            i += 1

    return result


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    """
    Parse a persona markdown file.

    Returns (frontmatter_dict, body_text).
    Exits 2 on parse failure or invalid name.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[personas] cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    # Expect file to start with '---\n'
    if not text.startswith("---\n"):
        print(
            f"[personas] {path}: missing YAML frontmatter — file must start with '---'",
            file=sys.stderr,
        )
        sys.exit(2)

    # Find the closing '---'
    rest = text[4:]  # strip opening '---\n'
    close_idx = rest.find("\n---\n")
    if close_idx == -1:
        # Try end-of-file closing marker
        if rest.endswith("\n---"):
            yaml_block = rest[:-4]
            body = ""
        else:
            print(
                f"[personas] {path}: unclosed YAML frontmatter — missing closing '---'",
                file=sys.stderr,
            )
            sys.exit(2)
    else:
        yaml_block = rest[:close_idx]
        body = rest[close_idx + 5:]  # skip '\n---\n'

    try:
        fm = _parse_simple_yaml(yaml_block)
    except ValueError as exc:
        print(f"[personas] {path}: YAML parse error: {exc}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(fm, dict):
        print(
            f"[personas] {path}: frontmatter must be a YAML mapping, got {type(fm).__name__}",
            file=sys.stderr,
        )
        sys.exit(2)

    # Reject unknown frontmatter keys (schema declares additionalProperties: false)
    _KNOWN_FRONTMATTER_KEYS = {"name", "description", "compatible_roles", "contract"}
    unknown_keys = set(fm.keys()) - _KNOWN_FRONTMATTER_KEYS
    if unknown_keys:
        print(
            f"[personas] {path}: unknown frontmatter key(s): "
            f"{sorted(unknown_keys)!r} — only "
            f"{sorted(_KNOWN_FRONTMATTER_KEYS)!r} are allowed. "
            "Note: 'model', 'runtime', and similar binding axes belong in TOML config, "
            "not in the persona file.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate required fields
    name = fm.get("name")
    if not isinstance(name, str) or not name:
        print(f"[personas] {path}: 'name' is required and must be a non-empty string", file=sys.stderr)
        sys.exit(2)

    if not _is_valid_persona_name(name):
        print(
            f"[personas] {path}: invalid persona name {name!r} — "
            "must match ^[a-z][a-z0-9-]*$ with no trailing hyphen "
            "(no uppercase, dots, slashes, or leading/trailing hyphens)",
            file=sys.stderr,
        )
        sys.exit(2)

    description = fm.get("description")
    if not isinstance(description, str) or not description.strip():
        print(
            f"[personas] {path}: 'description' is required and must be a non-empty string",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate optional compatible_roles
    compatible_roles = fm.get("compatible_roles")
    if compatible_roles is not None:
        if not isinstance(compatible_roles, list) or not all(
            isinstance(r, str) and r for r in compatible_roles
        ):
            print(
                f"[personas] {path}: 'compatible_roles' must be a list of non-empty strings",
                file=sys.stderr,
            )
            sys.exit(2)

    # Validate optional contract
    contract = fm.get("contract")
    valid_contracts = {"freeform", "review-verdict", "strict-json"}
    if contract is not None and contract not in valid_contracts:
        print(
            f"[personas] {path}: 'contract' must be one of "
            f"{sorted(valid_contracts)!r}, got {contract!r}",
            file=sys.stderr,
        )
        sys.exit(2)

    return fm, body


# ---------------------------------------------------------------------------
# Layer discovery
# ---------------------------------------------------------------------------

LAYER_BUILTIN = "builtin"
LAYER_USER_GLOBAL = "user-global"
LAYER_REPO = "repo"


def _discover_layers(
    repo_root_override: Optional[str] = None,
) -> list[tuple[str, Path]]:
    """
    Return a list of (layer_name, directory_path) in load order.

    Directories that don't exist are included — callers check existence before
    scanning via _scan_layer.

    Test overrides (for hermetic testing without touching real fs paths):
      Z_HARNESS_BUILTIN_PERSONAS_DIR  — override layer 1 (builtin)
      Z_HARNESS_USER_PERSONAS_DIR     — override layer 2 (user-global)
      Z_HARNESS_REPO_ROOT             — repo root for layer 3 (repo-local)
    """
    # Layer 1: builtin
    builtin_override = os.environ.get("Z_HARNESS_BUILTIN_PERSONAS_DIR", "")
    if builtin_override:
        builtin_dir = Path(builtin_override)
    else:
        script_dir = Path(__file__).parent
        harness_root = script_dir.parent
        builtin_dir = harness_root / "personas" / "builtin"

    # Layer 2: user-global
    user_override = os.environ.get("Z_HARNESS_USER_PERSONAS_DIR", "")
    if user_override:
        user_global_dir = Path(user_override)
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        user_global_dir = Path(xdg_config) / "z-harness" / "personas"

    # Layer 3: repo-local
    repo_personas_override = os.environ.get("Z_HARNESS_REPO_PERSONAS_DIR", "")
    if repo_personas_override:
        repo_local_dir = Path(repo_personas_override)
    elif repo_root_override:
        repo_local_dir = Path(repo_root_override) / ".z-harness" / "personas"
    else:
        repo_env = os.environ.get("Z_HARNESS_REPO_ROOT", "")
        if repo_env:
            repo_root = Path(repo_env)
        else:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    capture_output=True, text=True, check=True,
                )
                repo_root = Path(result.stdout.strip())
            except (subprocess.CalledProcessError, FileNotFoundError):
                repo_root = Path.cwd()
        repo_local_dir = repo_root / ".z-harness" / "personas"

    return [
        (LAYER_BUILTIN, builtin_dir),
        (LAYER_USER_GLOBAL, user_global_dir),
        (LAYER_REPO, repo_local_dir),
    ]


def _scan_layer(layer_name: str, directory: Path) -> list[dict]:
    """
    Scan a single layer directory for *.md persona files.

    Returns list of {name, source_layer, path, _fm} dicts.
    Files whose frontmatter fails name validation are skipped with a warning.
    """
    if not directory.exists() or not directory.is_dir():
        return []

    results = []
    for md_file in sorted(directory.glob("*.md")):
        fm, _body = _parse_frontmatter(md_file)
        results.append({
            "name": fm["name"],
            "source_layer": layer_name,
            "path": str(md_file),
            "_fm": fm,
        })
    return results


def _load_all_layers(
    repo_root_override: Optional[str] = None,
) -> list[dict]:
    """
    Walk all three layers in order and return every persona entry found.

    Each entry: {name, source_layer, path, _fm}.
    Entries are returned in load order (builtin first, repo last).
    """
    layers = _discover_layers(repo_root_override)
    all_entries: list[dict] = []
    for layer_name, directory in layers:
        all_entries.extend(_scan_layer(layer_name, directory))
    return all_entries


# ---------------------------------------------------------------------------
# Shared shadow detection helper
# ---------------------------------------------------------------------------

def _detect_and_emit_shadows(personas_by_name: dict[str, list[dict]]) -> None:
    """
    For each name in personas_by_name that appears in more than one layer,
    emit persona_shadowed via _emit_persona_shadowed (which is already memoized
    once-per-(process, name) so repeated calls are safe).
    """
    for name, entries in personas_by_name.items():
        if len(entries) > 1:
            layer_names = [e["source_layer"] for e in entries]
            winner = entries[-1]
            _emit_persona_shadowed(name, layer_names, winner["source_layer"])


# ---------------------------------------------------------------------------
# list-personas subcommand
# ---------------------------------------------------------------------------

def cmd_list_personas(args: list[str]) -> None:
    """
    Print JSON array of {name, source_layer, path} — one entry per name (winner only).

    The winner is the last layer in load order that defines the name.
    Emits persona_shadowed for each name that appears in more than one layer.
    """
    if args:
        print("usage: resolve-persona.py list-personas", file=sys.stderr)
        sys.exit(2)

    all_entries = _load_all_layers()

    # Collect all entries per name to detect shadowing
    by_name: dict[str, list[dict]] = {}
    for entry in all_entries:
        name = entry["name"]
        by_name.setdefault(name, []).append(entry)

    # Emit persona_shadowed for any collisions (once per process per name)
    _detect_and_emit_shadows(by_name)

    output = []
    for name, entries in sorted(by_name.items()):
        # Winner is the last entry (highest-priority layer)
        winner = entries[-1]

        output.append({
            "name": winner["name"],
            "source_layer": winner["source_layer"],
            "path": winner["path"],
        })

    print(json.dumps(output))


# ---------------------------------------------------------------------------
# where subcommand
# ---------------------------------------------------------------------------

def cmd_where(args: list[str]) -> None:
    """
    Print all layers defining <name>, one path per line, in load order.
    Exits 1 with actionable error if name not found in any layer.

    Also emits persona_shadowed (once per process per name) when the target
    persona is defined in more than one layer, so shadow detection is
    consistent regardless of which subcommand the caller uses.
    """
    if len(args) != 1:
        print("usage: resolve-persona.py where <name>", file=sys.stderr)
        sys.exit(2)

    target_name = args[0]

    all_entries = _load_all_layers()
    matches = [e for e in all_entries if e["name"] == target_name]

    if not matches:
        print(
            f"[personas] persona {target_name!r} not found in any layer.\n"
            "Run 'resolve-persona.py list-personas' to see available personas.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Emit shadow event when multiple layers define this persona
    if len(matches) > 1:
        by_name: dict[str, list[dict]] = {target_name: matches}
        _detect_and_emit_shadows(by_name)

    for entry in matches:
        print(entry["path"])


# ---------------------------------------------------------------------------
# T007 helpers: command-name normalization
# ---------------------------------------------------------------------------

def _normalize_command(command: str) -> str:
    """
    Normalize a command name to the underscore-only form used in TOML.

    Examples:
      /z-plan  → z_plan
      z-plan   → z_plan
      z_plan   → z_plan
    """
    # Strip leading slash
    if command.startswith("/"):
        command = command[1:]
    # Replace hyphens with underscores
    return command.replace("-", "_")


# ---------------------------------------------------------------------------
# T007 helpers: TOML config loading for role bindings
# ---------------------------------------------------------------------------

def _load_toml_file(path: Path) -> dict:
    """Load a TOML file. Returns {} if file does not exist."""
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError:
        return {}


def _global_toml_path() -> Path:
    """Return the global user config path."""
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(xdg) / "z-harness" / "config.toml"


def _repo_toml_path() -> Path:
    """Return the repo-local config path."""
    repo_env = os.environ.get("Z_HARNESS_REPO_CONFIG", "")
    if repo_env:
        return Path(repo_env)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        repo_root = Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        repo_root = Path.cwd()
    return repo_root / ".z-harness" / "config.toml"


def _providers_json_path() -> Path:
    """Return the repo-local providers.json path."""
    repo_env = os.environ.get("Z_HARNESS_REPO_PROVIDERS", "")
    if repo_env:
        return Path(repo_env)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        repo_root = Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        repo_root = Path.cwd()
    return repo_root / ".z-harness" / "providers.json"


def _get_role_binding_from_toml(data: dict, command_key: str, role: str) -> dict:
    """
    Extract {persona, model, runtime} from a TOML dict for [roles.<command>.<role>].

    Returns dict with only the keys present in TOML (may be empty).
    Source: the section key path roles.<command>.<role>.
    """
    roles = data.get("roles", {})
    if not isinstance(roles, dict):
        return {}
    cmd_section = roles.get(command_key, {})
    if not isinstance(cmd_section, dict):
        return {}
    role_section = cmd_section.get(role, {})
    if not isinstance(role_section, dict):
        return {}
    result = {}
    for field in ("persona", "model", "runtime"):
        if field in role_section:
            result[field] = role_section[field]
    return result


def _get_default_role_binding_from_toml(data: dict, role: str) -> dict:
    """
    Extract {persona, model, runtime} from a TOML dict for [roles.default.<role>].

    Returns dict with only the keys present in TOML (may be empty).
    """
    return _get_role_binding_from_toml(data, "default", role)


def _get_legacy_provider_role(role: str) -> Optional[str]:
    """
    Look up role in providers.json legacy roles mapping.

    Returns provider name string or None if not found.
    """
    providers_path = _providers_json_path()
    if not providers_path.exists():
        return None
    try:
        with open(providers_path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    roles = data.get("roles", {})
    return roles.get(role)


def _find_persona_path(name: str) -> Optional[str]:
    """
    Find the winning-layer path for a persona by name.

    Returns absolute path string or None if not found.
    """
    all_entries = _load_all_layers()
    # Build by-name dict; later entries win (higher layer priority)
    by_name: dict[str, dict] = {}
    for entry in all_entries:
        by_name[entry["name"]] = entry
    winner = by_name.get(name)
    return winner["path"] if winner else None


# ---------------------------------------------------------------------------
# T007 helpers: chimera event emission
# ---------------------------------------------------------------------------

# Module-level set for chimera events (once per (process, command, role))
_chimera_emitted: set[tuple[str, str]] = set()


def _emit_persona_binding_chimera(
    command: str,
    role: str,
    sources: dict[str, str],
) -> None:
    """
    Emit persona_binding_chimera once per (process, command, role) when the three
    binding axes resolve from ≥2 distinct sources.
    """
    key = (command, role)
    if key in _chimera_emitted:
        return
    _chimera_emitted.add(key)

    print(
        f"[personas] persona_binding_chimera: command={command!r} role={role!r} "
        f"sources={sources!r}",
        file=sys.stderr,
    )

    script_dir = Path(__file__).parent
    log_event = script_dir / "log-event.sh"
    if log_event.exists() and shutil.which("bash"):
        payload = json.dumps({
            "command": command,
            "role": role,
            "sources": sources,
        })
        run_id = os.environ.get("Z_HARNESS_RUN_ID", "unknown-run")
        try:
            subprocess.run(
                ["bash", str(log_event), run_id, "persona_binding_chimera", payload],
                check=False,
                capture_output=True,
            )
        except OSError:
            pass  # log-event.sh unavailable — ignore


# ---------------------------------------------------------------------------
# T007 helpers: resolution core
# ---------------------------------------------------------------------------

_SOURCE_ROLES_COMMAND = "roles_command"
_SOURCE_ROLES_DEFAULT = "roles_default"
_SOURCE_PROVIDERS_LEGACY = "providers_legacy"
_SOURCE_NONE = "none"


def _resolve_binding(command_raw: str, role: str) -> dict:
    """
    Resolve the persona/model/runtime triple for (command, role).

    Applies resolution order:
      1. [roles.<command>.<role>] in repo TOML (highest TOML priority)
      2. [roles.<command>.<role>] in global TOML
      3. [roles.default.<role>] in repo TOML
      4. [roles.default.<role>] in global TOML
      5. legacy providers.json roles[role] (sets runtime only; persona/model=null)
      6. none

    Axes are resolved per-field (chimera-aware).

    Returns dict:
      {
        persona: str|null,
        model: str|null,
        runtime: str|null,
        source: "roles_command"|"roles_default"|"providers_legacy"|"none",
        persona_body_path: str|null,
        _axis_sources: {persona: str, model: str, runtime: str},   # internal
      }
    """
    command_key = _normalize_command(command_raw)

    global_data = _load_toml_file(_global_toml_path())
    repo_data = _load_toml_file(_repo_toml_path())

    # Collect command-level bindings (repo wins over global per-field)
    cmd_global = _get_role_binding_from_toml(global_data, command_key, role)
    cmd_repo = _get_role_binding_from_toml(repo_data, command_key, role)

    # Collect default bindings (repo wins over global per-field)
    def_global = _get_default_role_binding_from_toml(global_data, role)
    def_repo = _get_default_role_binding_from_toml(repo_data, role)

    # Per-field resolution: command > default > legacy
    resolved: dict[str, Optional[str]] = {
        "persona": None,
        "model": None,
        "runtime": None,
    }
    # Track which TOML source each axis came from
    axis_sources: dict[str, str] = {
        "persona": _SOURCE_NONE,
        "model": _SOURCE_NONE,
        "runtime": _SOURCE_NONE,
    }

    # Layer order per field: cmd_repo → cmd_global → def_repo → def_global → legacy
    for field in ("persona", "model", "runtime"):
        if field in cmd_repo:
            resolved[field] = cmd_repo[field]
            axis_sources[field] = _SOURCE_ROLES_COMMAND
        elif field in cmd_global:
            resolved[field] = cmd_global[field]
            axis_sources[field] = _SOURCE_ROLES_COMMAND
        elif field in def_repo:
            resolved[field] = def_repo[field]
            axis_sources[field] = _SOURCE_ROLES_DEFAULT
        elif field in def_global:
            resolved[field] = def_global[field]
            axis_sources[field] = _SOURCE_ROLES_DEFAULT

    # Legacy fallback for runtime (and persona if still None)
    legacy_provider = _get_legacy_provider_role(role)
    if legacy_provider is not None:
        if resolved["runtime"] is None:
            resolved["runtime"] = legacy_provider
            axis_sources["runtime"] = _SOURCE_PROVIDERS_LEGACY

    # Determine overall source (highest-priority axis that resolved something)
    sources_used = set(v for v in axis_sources.values() if v != _SOURCE_NONE)
    if _SOURCE_ROLES_COMMAND in sources_used:
        overall_source = _SOURCE_ROLES_COMMAND
    elif _SOURCE_ROLES_DEFAULT in sources_used:
        overall_source = _SOURCE_ROLES_DEFAULT
    elif _SOURCE_PROVIDERS_LEGACY in sources_used:
        overall_source = _SOURCE_PROVIDERS_LEGACY
    else:
        overall_source = _SOURCE_NONE

    # Find persona body path
    persona_body_path = None
    if resolved["persona"]:
        persona_body_path = _find_persona_path(resolved["persona"])

    # Chimera check: did axes resolve from ≥2 distinct sources?
    distinct_sources = {v for v in axis_sources.values() if v != _SOURCE_NONE}
    if len(distinct_sources) >= 2:
        _emit_persona_binding_chimera(command_key, role, axis_sources)

    return {
        "persona": resolved["persona"],
        "model": resolved["model"],
        "runtime": resolved["runtime"],
        "source": overall_source,
        "persona_body_path": persona_body_path,
        "_axis_sources": axis_sources,
    }


# ---------------------------------------------------------------------------
# T007 subcommand: resolve
# ---------------------------------------------------------------------------

def cmd_resolve(args: list[str]) -> None:
    """
    resolve <command> <role>

    Normalize command name, resolve binding via TOML + legacy providers.json.
    Print JSON {persona, model, runtime, source, persona_body_path}.
    """
    if len(args) != 2:
        print("usage: resolve-persona.py resolve <command> <role>", file=sys.stderr)
        sys.exit(2)

    command_raw, role = args[0], args[1]
    result = _resolve_binding(command_raw, role)

    # Remove internal key before printing
    output = {k: v for k, v in result.items() if not k.startswith("_")}
    print(json.dumps(output))


# ---------------------------------------------------------------------------
# T007 subcommand: list-bindings
# ---------------------------------------------------------------------------

def _discover_configured_commands(global_data: dict, repo_data: dict) -> set[str]:
    """
    Return the set of all command keys (normalized, underscore form) that have
    at least one role binding in any TOML layer.

    Only includes explicit [roles.<command>.*] sections — not "default".
    """
    commands: set[str] = set()
    for data in (global_data, repo_data):
        roles_section = data.get("roles", {})
        if not isinstance(roles_section, dict):
            continue
        for cmd_key in roles_section:
            if cmd_key != "default":
                commands.add(cmd_key)
    return commands


def _discover_configured_roles(global_data: dict, repo_data: dict, command_key: str) -> set[str]:
    """
    Return all role names configured under [roles.<command>.*] and [roles.default.*]
    across both TOML layers.
    """
    roles: set[str] = set()
    for data in (global_data, repo_data):
        roles_section = data.get("roles", {})
        if not isinstance(roles_section, dict):
            continue
        # Command-specific roles
        cmd_section = roles_section.get(command_key, {})
        if isinstance(cmd_section, dict):
            roles.update(cmd_section.keys())
        # Default roles
        default_section = roles_section.get("default", {})
        if isinstance(default_section, dict):
            roles.update(default_section.keys())
    return roles


def cmd_list_bindings(args: list[str]) -> None:
    """
    list-bindings [--command <c>]

    Walk all configured commands (or just one if --command given),
    enumerate roles, call resolve() per (command, role), output JSON tree.
    """
    # Parse args
    filter_command: Optional[str] = None
    i = 0
    while i < len(args):
        if args[i] == "--command" and i + 1 < len(args):
            filter_command = args[i + 1]
            i += 2
        elif args[i].startswith("--"):
            print(f"[personas] unknown flag {args[i]!r}", file=sys.stderr)
            sys.exit(2)
        else:
            print(f"[personas] unexpected argument {args[i]!r}", file=sys.stderr)
            sys.exit(2)

    global_data = _load_toml_file(_global_toml_path())
    repo_data = _load_toml_file(_repo_toml_path())

    if filter_command is not None:
        command_key = _normalize_command(filter_command)
        commands_to_walk = {command_key}
    else:
        commands_to_walk = _discover_configured_commands(global_data, repo_data)

    output: dict = {}
    for command_key in sorted(commands_to_walk):
        roles = _discover_configured_roles(global_data, repo_data, command_key)
        command_bindings: dict = {}
        for role in sorted(roles):
            result = _resolve_binding(command_key, role)
            # Remove internal key
            command_bindings[role] = {k: v for k, v in result.items() if not k.startswith("_")}
        output[command_key] = command_bindings

    print(json.dumps(output))


# ---------------------------------------------------------------------------
# T007 subcommand: validate
# ---------------------------------------------------------------------------

def cmd_validate(args: list[str]) -> None:
    """
    validate

    Sanity-check all personas + TOML bindings:
    - Each persona's compatible_roles (if declared) maps to known role names.
    - All default bindings reference existing personas.
    - TODO(T009): contract enforcement against role expected_contract.

    Exit non-zero if any violation found.
    """
    if args:
        print("usage: resolve-persona.py validate", file=sys.stderr)
        sys.exit(2)

    # TODO(T009): When role registry is added, enforce contract matching here.
    # For now, validate persona names + compatible_roles only.

    errors: list[str] = []

    # Known roles: from providers.json legacy + default TOML bindings
    # For T007 scope, treat these three as the known roles.
    known_roles = {"consultant_primary", "consultant_secondary", "reviewer"}

    # Load all personas
    all_entries = _load_all_layers()
    # Build winning persona set (by name)
    by_name: dict[str, dict] = {}
    for entry in all_entries:
        by_name[entry["name"]] = entry

    # 1. For each persona, check compatible_roles references known roles
    for name, entry in by_name.items():
        fm = entry.get("_fm", {})
        compatible_roles = fm.get("compatible_roles")
        if compatible_roles is not None:
            for cr in compatible_roles:
                if cr not in known_roles:
                    errors.append(
                        f"persona {name!r}: compatible_roles lists {cr!r} which is not a known role "
                        f"(known: {sorted(known_roles)})"
                    )

    # 2. Check that all default TOML bindings reference existing personas
    global_data = _load_toml_file(_global_toml_path())
    repo_data = _load_toml_file(_repo_toml_path())

    for data, label in ((global_data, "global"), (repo_data, "repo")):
        roles_section = data.get("roles", {})
        if not isinstance(roles_section, dict):
            continue
        for cmd_key, cmd_section in roles_section.items():
            if not isinstance(cmd_section, dict):
                continue
            for role_key, role_fields in cmd_section.items():
                if not isinstance(role_fields, dict):
                    continue
                persona_name = role_fields.get("persona")
                if persona_name and isinstance(persona_name, str):
                    if persona_name not in by_name:
                        errors.append(
                            f"[{label} TOML] roles.{cmd_key}.{role_key}.persona = {persona_name!r} "
                            f"references a persona that does not exist in any layer. "
                            f"Run 'resolve-persona.py list-personas' to see available personas."
                        )

    if errors:
        for err in errors:
            print(f"[personas] VALIDATION ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"status": "ok", "checked_personas": len(by_name)}))


# ---------------------------------------------------------------------------
# T007 subcommand: read
# ---------------------------------------------------------------------------

def cmd_read(args: list[str]) -> None:
    """
    read <name>

    Print frontmatter + body of the winning persona file.
    Exits non-zero with actionable error if name doesn't exist.
    """
    if len(args) != 1:
        print("usage: resolve-persona.py read <name>", file=sys.stderr)
        sys.exit(2)

    target_name = args[0]

    all_entries = _load_all_layers()

    # Find the winning entry (last one in load order for this name)
    winner: Optional[dict] = None
    for entry in all_entries:
        if entry["name"] == target_name:
            winner = entry

    if winner is None:
        print(
            f"[personas] persona {target_name!r} not found in any layer.\n"
            "Run 'resolve-persona.py list-personas' to see available personas.\n"
            "Run 'resolve-persona.py where <name>' to check which layers define a name.",
            file=sys.stderr,
        )
        sys.exit(1)

    path = Path(winner["path"])
    fm, body = _parse_frontmatter(path)

    # Print frontmatter as JSON, then the body
    output = {
        "name": fm.get("name"),
        "source_layer": winner["source_layer"],
        "path": winner["path"],
        "frontmatter": fm,
        "body": body,
    }
    print(json.dumps(output))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SUBCOMMANDS = {
    "list-personas": cmd_list_personas,
    "where": cmd_where,
    "resolve": cmd_resolve,
    "list-bindings": cmd_list_bindings,
    "validate": cmd_validate,
    "read": cmd_read,
}


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: resolve-persona.py <subcommand> [args]\n"
            f"subcommands: {', '.join(sorted(SUBCOMMANDS))}",
            file=sys.stderr,
        )
        sys.exit(2)

    subcommand = sys.argv[1]
    remaining = sys.argv[2:]

    handler = SUBCOMMANDS.get(subcommand)
    if handler is None:
        print(
            f"[personas] unknown subcommand {subcommand!r}\n"
            f"subcommands: {', '.join(sorted(SUBCOMMANDS))}",
            file=sys.stderr,
        )
        sys.exit(2)

    handler(remaining)


if __name__ == "__main__":
    main()
