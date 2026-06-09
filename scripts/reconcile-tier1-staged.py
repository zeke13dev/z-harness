#!/usr/bin/env python3
"""
reconcile-tier1-staged.py — Tier 1 staged doc update reconciliation.

Scans $Z_HARNESS_PLAN_DIR/tier1-staged/ for concept directories, merges AUTO-START/AUTO-END
delimited sections from staged docs into the live docs/human/ and docs/llm/ files.
Updates INDEX.json last_updated and source_files. Regenerates MEMORIES-FLAT.md.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Optional


AUTO_SECTION_RE = re.compile(
    r'(\<!--\s*AUTO-START:\s*([a-zA-Z0-9_-]+)\s*--\>)(.*?)(\<!--\s*AUTO-END:\s*(\2)\s*--\>)',
    re.DOTALL,
)


def find_staged_concepts(staging_dir: str) -> list[str]:
    """List concept slugs that have staged updates."""
    if not os.path.isdir(staging_dir):
        return []
    return [
        d for d in os.listdir(staging_dir)
        if os.path.isdir(os.path.join(staging_dir, d))
    ]


def merge_human_doc(staged_path: str, live_path: str, dry_run: bool = False) -> Optional[str]:
    """Merge AUTO-START/AUTO-END sections from staged into live human doc.
    Returns the merged content, or None if live doc doesn't exist."""
    if not os.path.exists(live_path):
        return None

    with open(live_path) as f:
        live = f.read()

    with open(staged_path) as f:
        staged = f.read()

    # Extract staged sections
    staged_sections = {}
    for m in AUTO_SECTION_RE.finditer(staged):
        section_name = m.group(2)
        staged_sections[section_name] = m.group(0)

    if not staged_sections:
        return live  # No AUTO sections in staged — nothing to merge

    # Replace in live doc
    def replace_section(match):
        section_name = match.group(2)
        if section_name in staged_sections:
            return staged_sections[section_name]
        return match.group(0)

    merged = AUTO_SECTION_RE.sub(replace_section, live)

    # If live has no AUTO sections at all, we can't merge — return live unchanged
    if merged == live and not AUTO_SECTION_RE.search(live):
        return live

    if not dry_run:
        with open(live_path, "w") as f:
            f.write(merged)

    return merged


def merge_llm_json(staged_path: str, live_path: str, dry_run: bool = False) -> Optional[dict]:
    """Merge machine-truth fields from staged LLM JSON into live LLM JSON.
    Preserves: depends_on, consumed_by, summary, confidence, memories, invariants, gotchas."""
    if not os.path.exists(live_path):
        return None

    with open(live_path) as f:
        live = json.load(f)

    with open(staged_path) as f:
        staged = json.load(f)

    # Fields to update from staged
    update_fields = ["entry_points", "source_file", "source_files", "last_updated"]
    for field in update_fields:
        if field in staged:
            live[field] = staged[field]

    live["last_updated"] = staged.get("last_updated", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    if not dry_run:
        tmp = live_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(live, f, indent=2)
        os.replace(tmp, live_path)

    return live


def update_index(index_path: str, touched_concepts: list[str], dry_run: bool = False) -> None:
    """Update INDEX.json last_updated and source_files for touched concepts."""
    if not os.path.exists(index_path):
        return

    with open(index_path) as f:
        index = json.load(f)

    concepts = index.get("concepts", [])
    for concept in concepts:
        slug = concept.get("slug", "")
        if slug in touched_concepts:
            concept["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            # source_files already updated by merge_llm_json

    if not dry_run:
        tmp = index_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(index, f, indent=2)
        os.replace(tmp, index_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile Tier 1 staged doc updates into live docs/"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show diffs, don't write")
    parser.add_argument("--plan-dir", default=None,
                        help="Plan directory (default: $Z_HARNESS_PLAN_DIR)")
    args = parser.parse_args()

    plan_dir = args.plan_dir or os.environ.get("Z_HARNESS_PLAN_DIR")
    if not plan_dir:
        print("Error: --plan-dir or $Z_HARNESS_PLAN_DIR must be set", file=sys.stderr)
        sys.exit(2)

    repo_root = os.environ.get("Z_HARNESS_REPO_ROOT", os.getcwd())
    staging_dir = os.path.join(plan_dir, "tier1-staged")
    human_dir = os.path.join(repo_root, "docs", "human")
    llm_dir = os.path.join(repo_root, "docs", "llm")
    index_path = os.path.join(repo_root, "docs", "llm", "INDEX.json")
    memories_script = os.path.join(repo_root, "scripts", "regenerate-memories-flat.py")

    concepts = find_staged_concepts(staging_dir)
    if not concepts:
        print("No staged updates found.")
        return

    touched = []
    for concept in concepts:
        concept_staging = os.path.join(staging_dir, concept)
        staged_human = os.path.join(concept_staging, "human.md")
        staged_llm = os.path.join(concept_staging, "llm.json")
        live_human = os.path.join(human_dir, f"{concept}.md")
        live_llm = os.path.join(llm_dir, f"{concept}.json")

        if os.path.exists(staged_human) and os.path.exists(live_human):
            result = merge_human_doc(staged_human, live_human, args.dry_run)
            if result is not None:
                touched.append(concept)
                print(f"  Merged human doc: {concept}")
        else:
            print(f"  Skipped human doc: {concept} (staged or live missing)")

        if os.path.exists(staged_llm) and os.path.exists(live_llm):
            result = merge_llm_json(staged_llm, live_llm, args.dry_run)
            if result is not None and concept not in touched:
                touched.append(concept)
            print(f"  Merged LLM JSON: {concept}")
        else:
            print(f"  Skipped LLM JSON: {concept} (staged or live missing)")

    # Update INDEX.json
    if touched:
        update_index(index_path, touched, args.dry_run)
        print(f"Updated INDEX.json for {len(touched)} concepts")

    # Regenerate MEMORIES-FLAT.md
    if not args.dry_run and os.path.exists(memories_script):
        rc = subprocess.run(
            ["python3", memories_script, "--repo-root", repo_root],
            capture_output=True, text=True,
        )
        if rc.returncode == 0:
            print("Regenerated MEMORIES-FLAT.md")
        else:
            print(f"Warning: MEMORIES-FLAT.md regeneration failed: {rc.stderr}", file=sys.stderr)
    elif args.dry_run:
        print("[dry-run] Would regenerate MEMORIES-FLAT.md")

    print(f"\nReconciliation complete: {len(touched)} concept(s) updated.")


if __name__ == "__main__":
    main()
