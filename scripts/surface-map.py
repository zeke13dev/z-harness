#!/usr/bin/env python3
"""surface-map.py — deterministic shared surface map producer.

Produces bounded ``surface-map.json`` payloads for repo, symbol, and diff
surfaces. The helper is intentionally neutral: it emits source-shaped facts,
not prose, recommendations, or command orchestration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

MODES = {"repo", "symbol", "diff"}
CALLERS = {"z-explain", "z-learn", "z-report", "z-explore"}
STATUSES = {
    "ok",
    "partial",
    "not_found",
    "ambiguous",
    "too_broad",
    "truncated",
    "error",
}
CONFIDENCES = {"high", "medium", "low"}

DEFAULT_MAX_PRIMARY_FILES = 10
DEFAULT_MAX_REFS = 100
DEFAULT_MAX_BYTES = 200_000

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
_TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".go",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
_CONFIG_NAMES = {
    "Makefile",
    "Dockerfile",
    "compose.yaml",
    "docker-compose.yml",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "README.md",
    "LICENSE",
}

_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)
_IDENT_RE_TEMPLATE = r"\b{symbol}\b"
_DEF_RE_TEMPLATE = (
    r"\b(class|def|function|const|let|var|type|interface|struct|enum)\s+{symbol}\b"
)


@dataclass(frozen=True)
class Caps:
    max_primary_files: int = DEFAULT_MAX_PRIMARY_FILES
    max_refs: int = DEFAULT_MAX_REFS
    max_bytes: int = DEFAULT_MAX_BYTES

    def as_json(self) -> dict[str, int]:
        return {
            "max_primary_files": self.max_primary_files,
            "max_refs": self.max_refs,
            "max_bytes": self.max_bytes,
        }


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int

    @property
    def range_label(self) -> str:
        return f"{self.line_start}-{self.line_end}"

    @property
    def new_end(self) -> int:
        return self.new_start + max(self.new_count, 1) - 1

    @property
    def old_end(self) -> int:
        return self.old_start + max(self.old_count, 1) - 1

    @property
    def line_start(self) -> int:
        return self.old_start if self.new_count == 0 else self.new_start

    @property
    def line_end(self) -> int:
        return self.old_end if self.new_count == 0 else self.new_end


@dataclass
class ChangedFile:
    path: str
    old_path: str | None = None
    hunks: list[Hunk] = field(default_factory=list)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_rel(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _normalize_diff_path(raw: str) -> str | None:
    raw = raw.strip()
    if not raw or raw == "/dev/null":
        return None
    if "\t" in raw:
        raw = raw.split("\t", 1)[0]
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]
    return raw or None


def infer_target_kind(mode: str, repo_root: Path, target: str) -> str:
    if mode == "diff":
        return "diff"
    if mode == "symbol":
        return "symbol"
    raw = target.strip()
    if raw in {"", ".", "repo"}:
        return "repo"
    candidate = (repo_root / raw).resolve()
    if candidate.is_dir():
        return "directory"
    if candidate.is_file():
        return "module" if candidate.suffix in _TEXT_SUFFIXES else "free_text"
    return "free_text"


def empty_payload(mode: str, caller: str, repo_root: Path, target: str, caps: Caps) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "mode": mode,
        "caller": caller,
        "status": "ok",
        "target": {
            "raw": target,
            "repo_root": str(repo_root.resolve()),
            "inferred_kind": infer_target_kind(mode, repo_root, target),
        },
        "caps": caps.as_json(),
        "stats": {
            "files_scanned": 0,
            "candidate_files": 0,
            "refs": 0,
            "truncated": False,
        },
        "primary": [],
        "related": [],
        "clusters": [],
        "suggested_reads": [],
        "warnings": [],
        "tried_strategies": [],
    }


def validate_payload(payload: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "generated_at",
        "mode",
        "caller",
        "status",
        "target",
        "caps",
        "stats",
        "primary",
        "related",
        "clusters",
        "suggested_reads",
        "warnings",
        "tried_strategies",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"surface-map missing required fields: {', '.join(missing)}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("surface-map schema_version must be 1")
    if payload["mode"] not in MODES:
        raise ValueError(f"invalid surface-map mode: {payload['mode']}")
    if payload["caller"] not in CALLERS:
        raise ValueError(f"invalid surface-map caller: {payload['caller']}")
    if payload["status"] not in STATUSES:
        raise ValueError(f"invalid surface-map status: {payload['status']}")
    target = payload["target"]
    if not isinstance(target, dict):
        raise ValueError("surface-map target must be an object")
    for key in ("raw", "repo_root", "inferred_kind"):
        if key not in target:
            raise ValueError(f"surface-map target missing {key}")
    for key in ("max_primary_files", "max_refs", "max_bytes"):
        if key not in payload["caps"]:
            raise ValueError(f"surface-map caps missing {key}")
    for key in ("files_scanned", "candidate_files", "refs", "truncated"):
        if key not in payload["stats"]:
            raise ValueError(f"surface-map stats missing {key}")
    for key in ("primary", "related", "clusters", "suggested_reads", "warnings", "tried_strategies"):
        if not isinstance(payload[key], list):
            raise ValueError(f"surface-map {key} must be a list")
    for entry in payload["primary"]:
        confidence = entry.get("confidence")
        if confidence not in CONFIDENCES:
            raise ValueError(f"invalid primary confidence: {confidence}")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    validate_payload(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _classify_path(path: str, *, is_dir: bool = False) -> str:
    name = Path(path).name
    parts = Path(path).parts
    first = parts[0] if parts else name
    if first == "tests" or name.startswith("test_"):
        return "test"
    if first == "docs" or name.lower().endswith(('.md', '.rst')):
        return "doc"
    if name in _CONFIG_NAMES or name.startswith(".") and not is_dir:
        return "config"
    if first == "scripts" and name.endswith((".py", ".sh")):
        return "entrypoint"
    if is_dir:
        return "module"
    if name.endswith((".py", ".ts", ".tsx", ".js", ".rs", ".go")):
        return "module"
    return "artifact"


def _surface_label(path: str) -> str:
    parts = Path(path).parts
    if not parts:
        return "root"
    first = parts[0]
    labels = {
        "agents": "agent contracts",
        "docs": "documentation",
        "runtime": "runtime support",
        "scripts": "scripts and helpers",
        "skills": "command skills",
        "tests": "tests",
        "z_harness_cli": "packaging CLI",
        "_fragments": "shared command fragments",
    }
    if len(parts) == 1 and "." in first:
        return "root config"
    return labels.get(first, first)


def _cluster_id(label: str, index: int) -> str:
    return f"C{index}"


def _clusters_for_paths(paths: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for path in sorted(dict.fromkeys(paths)):
        grouped.setdefault(_surface_label(path), []).append(path)
    clusters = []
    for index, (label, members) in enumerate(sorted(grouped.items()), start=1):
        clusters.append(
            {
                "id": _cluster_id(label, index),
                "label": label,
                "paths": members,
                "summary": f"Changed or primary surface under {label}.",
            }
        )
    return clusters


def _repo_candidates(repo_root: Path) -> list[tuple[Path, bool]]:
    candidates: list[tuple[Path, bool]] = []
    if not repo_root.exists():
        return candidates
    priority_names = [
        "scripts",
        "skills",
        "agents",
        "runtime",
        "z_harness_cli",
        "tests",
        "docs",
        "_fragments",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "README.md",
    ]
    seen: set[Path] = set()
    for name in priority_names:
        path = repo_root / name
        if path.exists():
            candidates.append((path, path.is_dir()))
            seen.add(path)
    for path in sorted(repo_root.iterdir(), key=lambda p: p.name):
        if path in seen:
            continue
        if path.name in _SKIP_DIRS or (path.name.startswith(".") and path.name not in {".github"}):
            continue
        if path.is_dir() or path.name in _CONFIG_NAMES or path.suffix in {".toml", ".json", ".yml", ".yaml"}:
            candidates.append((path, path.is_dir()))
    return candidates


def build_repo_map(repo_root: Path, target: str, caller: str, caps: Caps) -> dict[str, Any]:
    payload = empty_payload("repo", caller, repo_root, target, caps)
    payload["tried_strategies"].append("top-level deterministic repository scan")

    candidates = _repo_candidates(repo_root)
    payload["stats"]["files_scanned"] = len(candidates)
    payload["stats"]["candidate_files"] = len(candidates)
    if not candidates:
        payload["status"] = "not_found"
        payload["warnings"].append("repo root has no mappable top-level surfaces")
        return payload

    limit = max(caps.max_primary_files, 0)
    shown = candidates[:limit]
    for path, is_dir in shown:
        rel = _safe_rel(path, repo_root)
        entry = {
            "path": rel,
            "kind": _classify_path(rel, is_dir=is_dir),
            "relation": "entrypoint" if _classify_path(rel, is_dir=is_dir) == "entrypoint" else "documents" if _classify_path(rel, is_dir=is_dir) == "doc" else "defines",
            "line_start": 1,
            "line_end": 1,
            "citations": [f"{rel}:1"],
            "reason": "deterministic top-level repository surface",
            "confidence": "medium",
        }
        if not is_dir:
            entry["symbol"] = path.stem
        payload["primary"].append(entry)
        payload["suggested_reads"].append(
            {"path": rel, "ranges": ["1-80"], "reason": "primary top-level surface"}
        )

    payload["clusters"] = _clusters_for_paths([_safe_rel(path, repo_root) for path, _ in shown])
    payload["stats"]["refs"] = len(payload["primary"])
    if len(candidates) > limit:
        payload["status"] = "truncated" if limit > 0 else "too_broad"
        payload["stats"]["truncated"] = True
        payload["warnings"].append(
            f"repo surfaces capped at {caps.max_primary_files} primary entries out of {len(candidates)} candidates"
        )
    return payload


def parse_unified_diff(diff_text: str) -> list[ChangedFile]:
    changed: list[ChangedFile] = []
    current: ChangedFile | None = None

    def finish_current() -> None:
        nonlocal current
        if current and current.path:
            if not changed or changed[-1] is not current:
                changed.append(current)
        current = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            finish_current()
            parts = line.split()
            old_path = _normalize_diff_path(parts[2]) if len(parts) > 2 else None
            new_path = _normalize_diff_path(parts[3]) if len(parts) > 3 else None
            current = ChangedFile(path=new_path or old_path or "", old_path=old_path)
            continue
        if line.startswith("--- "):
            old_path = _normalize_diff_path(line[4:])
            if current is None:
                current = ChangedFile(path=old_path or "", old_path=old_path)
            else:
                current.old_path = old_path
            continue
        if line.startswith("+++ "):
            new_path = _normalize_diff_path(line[4:])
            if current is None:
                current = ChangedFile(path=new_path or "", old_path=None)
            elif new_path:
                current.path = new_path
            elif current.old_path:
                current.path = current.old_path
            continue
        match = _HUNK_RE.match(line)
        if match:
            if current is None:
                current = ChangedFile(path="unknown")
            old_count = int(match.group("old_count") or "1")
            new_count = int(match.group("new_count") or "1")
            current.hunks.append(
                Hunk(
                    old_start=int(match.group("old_start")),
                    old_count=old_count,
                    new_start=int(match.group("new_start")),
                    new_count=new_count,
                )
            )
    finish_current()

    deduped: dict[str, ChangedFile] = {}
    for item in changed:
        if not item.path:
            continue
        existing = deduped.get(item.path)
        if existing is None:
            deduped[item.path] = item
        else:
            existing.hunks.extend(item.hunks)
    return [deduped[path] for path in sorted(deduped)]


def _read_diff_from_args(diff_path: str | None, base: str | None, range_spec: str | None, repo_root: Path, caps: Caps) -> tuple[str, bool]:
    if diff_path:
        path = Path(diff_path)
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(caps.max_bytes + 1)
        return text[: caps.max_bytes], len(text) > caps.max_bytes
    cmd: list[str]
    if range_spec:
        cmd = ["git", "diff", "--no-ext-diff", range_spec]
    elif base:
        cmd = ["git", "diff", "--no-ext-diff", base]
    else:
        cmd = ["git", "diff", "--no-ext-diff"]
    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git diff exited {result.returncode}")
    text = result.stdout
    return text[: caps.max_bytes], len(text) > caps.max_bytes


def build_diff_map(
    repo_root: Path,
    target: str,
    caller: str,
    caps: Caps,
    *,
    diff_path: str | None = None,
    base: str | None = None,
    range_spec: str | None = None,
) -> dict[str, Any]:
    payload = empty_payload("diff", caller, repo_root, target, caps)
    payload["tried_strategies"].append("unified diff file/hunk parse")

    diff_text, byte_truncated = _read_diff_from_args(diff_path, base, range_spec, repo_root, caps)
    changed = parse_unified_diff(diff_text)
    payload["stats"]["candidate_files"] = len(changed)
    payload["stats"]["files_scanned"] = len(changed)
    total_hunks = sum(len(item.hunks) for item in changed)

    if not changed:
        payload["status"] = "not_found"
        if byte_truncated:
            payload["status"] = "truncated"
            payload["stats"]["truncated"] = True
            payload["warnings"].append("diff input exceeded max_bytes before a changed file was parsed")
        return payload

    primary_limit = max(caps.max_primary_files, 0)
    ref_limit = max(caps.max_refs, 0)
    shown_files = changed[:primary_limit]
    refs_used = 0
    for item in shown_files:
        hunks = item.hunks or [Hunk(1, 1, 1, 1)]
        line_start = min(h.line_start for h in hunks)
        line_end = max(h.line_end for h in hunks)
        ranges = [h.range_label for h in hunks[: max(ref_limit - refs_used, 0)]]
        refs_used += len(ranges)
        payload["primary"].append(
            {
                "path": item.path,
                "kind": "changed_file",
                "relation": "changes",
                "line_start": line_start,
                "line_end": line_end,
                "citations": [f"{item.path}:{line_start}"],
                "reason": "file appears in unified diff",
                "confidence": "high",
            }
        )
        payload["suggested_reads"].append(
            {
                "path": item.path,
                "ranges": ranges or [f"{line_start}-{line_end}"],
                "reason": "changed hunks from diff",
            }
        )
        for hunk in hunks:
            if len(payload["related"]) >= ref_limit:
                break
            payload["related"].append(
                {
                    "path": item.path,
                    "kind": "changed_file",
                    "relation": "changes",
                    "line_start": hunk.line_start,
                    "line_end": hunk.line_end,
                    "citations": [f"{item.path}:{hunk.line_start}"],
                    "reason": "changed hunk from unified diff",
                    "confidence": "high",
                }
            )

    payload["clusters"] = _clusters_for_paths([item.path for item in shown_files])
    payload["stats"]["refs"] = total_hunks

    too_many_files = len(changed) > primary_limit
    too_many_refs = total_hunks > ref_limit
    if byte_truncated or too_many_refs:
        payload["status"] = "truncated"
        payload["stats"]["truncated"] = True
    if too_many_files:
        payload["status"] = "too_broad" if primary_limit == 0 else "truncated"
        payload["stats"]["truncated"] = True
    if payload["stats"]["truncated"]:
        payload["warnings"].append(
            "diff surface exceeded caps: "
            f"files={len(changed)}/{caps.max_primary_files}, hunks={total_hunks}/{caps.max_refs}, "
            f"bytes_truncated={byte_truncated}"
        )
    return payload


def _iter_text_files(repo_root: Path, caps: Caps) -> tuple[list[Path], bool]:
    files: list[Path] = []
    bytes_seen = 0
    truncated = False
    for root, dirs, names in os.walk(repo_root):
        dirs[:] = sorted(
            d for d in dirs if d not in _SKIP_DIRS and not (d.startswith(".") and d != ".github")
        )
        for name in sorted(names):
            path = Path(root) / name
            if name.startswith(".") and name not in _CONFIG_NAMES:
                continue
            if path.suffix not in _TEXT_SUFFIXES and name not in _CONFIG_NAMES:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if bytes_seen + size > caps.max_bytes:
                truncated = True
                return files, truncated
            bytes_seen += size
            files.append(path)
    return files, truncated


def _symbol_kind(line: str, path: str) -> str:
    stripped = line.strip()
    if re.search(r"\b(class|type|interface|struct|enum)\b", stripped):
        return "type"
    if re.search(r"\b(def|function)\b", stripped):
        return "function"
    return _classify_path(path)


def build_symbol_map(repo_root: Path, target: str, caller: str, caps: Caps) -> dict[str, Any]:
    payload = empty_payload("symbol", caller, repo_root, target, caps)
    payload["tried_strategies"].append("filename and identifier text scan within caps")
    symbol = target.strip()
    if not symbol or len(symbol) < 2:
        payload["status"] = "too_broad"
        payload["warnings"].append("symbol target is empty or too short for deterministic scan")
        return payload

    files, byte_truncated = _iter_text_files(repo_root, caps)
    payload["stats"]["files_scanned"] = len(files)
    ident_re = re.compile(_IDENT_RE_TEMPLATE.format(symbol=re.escape(symbol)), re.IGNORECASE)
    def_re = re.compile(_DEF_RE_TEMPLATE.format(symbol=re.escape(symbol)), re.IGNORECASE)
    matches: list[dict[str, Any]] = []
    candidate_paths: set[str] = set()

    for path in files:
        rel = _safe_rel(path, repo_root)
        name_match = symbol.lower() in path.name.lower()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        best_line = 1
        best_kind = _classify_path(rel)
        confidence = "medium" if name_match else "low"
        for idx, line in enumerate(text.splitlines(), start=1):
            if def_re.search(line):
                best_line = idx
                best_kind = _symbol_kind(line, rel)
                confidence = "high"
                break
            if ident_re.search(line) and confidence != "high":
                best_line = idx
                best_kind = _symbol_kind(line, rel)
                confidence = "medium"
        if name_match or ident_re.search(text):
            candidate_paths.add(rel)
            matches.append(
                {
                    "path": rel,
                    "symbol": symbol,
                    "kind": best_kind,
                    "relation": "defines" if confidence == "high" else "uses",
                    "line_start": best_line,
                    "line_end": best_line,
                    "citations": [f"{rel}:{best_line}"],
                    "reason": "filename or identifier text matched symbol target",
                    "confidence": confidence,
                }
            )
            if len(matches) > caps.max_refs:
                break

    matches.sort(key=lambda item: (0 if item["confidence"] == "high" else 1, item["path"], item["line_start"]))
    payload["stats"]["candidate_files"] = len(candidate_paths)
    payload["stats"]["refs"] = len(matches)

    if not matches:
        payload["status"] = "truncated" if byte_truncated else "not_found"
        payload["stats"]["truncated"] = byte_truncated
        if byte_truncated:
            payload["warnings"].append("symbol scan reached max_bytes before finding a match")
        return payload

    primary_limit = max(caps.max_primary_files, 0)
    payload["primary"] = matches[:primary_limit]
    payload["related"] = matches[primary_limit : max(caps.max_refs, primary_limit)]
    payload["clusters"] = _clusters_for_paths([entry["path"] for entry in payload["primary"]])
    for entry in payload["primary"]:
        start = entry["line_start"]
        end = min(start + 40, max(start, entry["line_end"] + 40))
        payload["suggested_reads"].append(
            {"path": entry["path"], "ranges": [f"{start}-{end}"], "reason": "symbol candidate"}
        )

    if byte_truncated or len(matches) > caps.max_refs:
        payload["status"] = "too_broad"
        payload["stats"]["truncated"] = True
        payload["warnings"].append("symbol scan exceeded max_refs or max_bytes")
    elif len(matches) > primary_limit:
        payload["status"] = "ambiguous" if primary_limit > 0 else "too_broad"
        payload["stats"]["truncated"] = True
        payload["warnings"].append(
            f"symbol matched {len(matches)} references; primary output capped at {caps.max_primary_files}"
        )
    return payload


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("caps must be non-negative integers")
    return parsed


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Produce a bounded z-harness surface-map.json")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--caller", choices=sorted(CALLERS), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--base")
    parser.add_argument("--range", dest="range_spec")
    parser.add_argument("--diff-path")
    parser.add_argument("--max-primary-files", type=positive_int, default=DEFAULT_MAX_PRIMARY_FILES)
    parser.add_argument("--max-refs", type=positive_int, default=DEFAULT_MAX_REFS)
    parser.add_argument("--max-bytes", type=positive_int, default=DEFAULT_MAX_BYTES)
    return parser.parse_args(argv)


def build_map(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    caps = Caps(args.max_primary_files, args.max_refs, args.max_bytes)
    if args.mode == "repo":
        return build_repo_map(repo_root, args.target, args.caller, caps)
    if args.mode == "symbol":
        return build_symbol_map(repo_root, args.target, args.caller, caps)
    return build_diff_map(
        repo_root,
        args.target,
        args.caller,
        caps,
        diff_path=args.diff_path,
        base=args.base,
        range_spec=args.range_spec,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        payload = build_map(args)
        atomic_write_json(Path(args.out), payload)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        try:
            repo_root = Path(args.repo_root).resolve()
            caps = Caps(args.max_primary_files, args.max_refs, args.max_bytes)
            payload = empty_payload(args.mode, args.caller, repo_root, args.target, caps)
            payload["status"] = "error"
            payload["warnings"].append(str(exc))
            atomic_write_json(Path(args.out), payload)
        except (OSError, ValueError):
            pass
        print(f"surface-map.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
