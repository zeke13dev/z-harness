#!/usr/bin/env python3
"""Summarize supported Codex rollout JSONL through canonical native telemetry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.telemetry.native_usage import (  # noqa: E402
    CONTRACT_VERSION,
    reduce_intervals,
    reduce_usage_observations,
    session_hash,
    summarize_sources,
    timestamp_ms,
    validate_observation,
)


VERSION = CONTRACT_VERSION


def parse_source(spec: str) -> tuple[str, Path]:
    """Parse one ``live:path`` or ``archive:path`` CLI source.

    Raises:
        argparse.ArgumentTypeError: If the source label or path is invalid.
    """
    try:
        source, raw_path = spec.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("source must be live:<jsonl-path> or archive:<jsonl-path>") from exc
    if source not in {"live", "archive"} or not raw_path:
        raise argparse.ArgumentTypeError("source must be live:<jsonl-path> or archive:<jsonl-path>")
    return source, Path(raw_path)


def summarize(sources: list[tuple[str, Path]]) -> dict[str, object]:
    """Return the compatibility summary produced by the canonical reducer."""
    return summarize_sources(sources)


def main(argv: list[str] | None = None) -> int:
    """Run the read-only normalizer CLI and return its process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=parse_source, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.source), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
