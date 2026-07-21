"""Standalone strict release-conformance evidence validator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from z_harness_cli.release_host_evidence import (  # noqa: E402
    derive_release_claims,
    evidence_set_digest,
    validate_release_evidence,
)

SAMPLE_CANDIDATE_SHA = "1" * 40
SAMPLE_FIXTURE_DIGEST = "db3a27d1ef0a62d67ab27719f7ea19aea1dc16c5e0ef61e2dcd5147408dc12d1"
Z_FIX_FIXTURE_ROOT = _HERE / "fixtures" / "z-fix"


def evaluate_release_evidence(
    evidence_root: Path,
    candidate_sha: str,
    *,
    test_fixture_mode: bool = False,
) -> list[str]:
    """Programmatic runner seam; shares the pytest validator verbatim."""

    return validate_release_evidence(
        evidence_root,
        candidate_sha,
        allow_test_fixtures=test_fixture_mode,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate blocking z-fix evidence for the exact C1 release claims."
    )
    parser.add_argument(
        "--candidate-sha",
        required=True,
        help="Exact lowercase 40-hex candidate SHA",
    )
    parser.add_argument(
        "--evidence-root",
        required=True,
        type=Path,
        help="Explicit z-fix evidence directory",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Forbidden compatibility flag; claimed-host evidence can never be advisory.",
    )
    parser.add_argument(
        "--test-fixture-mode",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    if args.allow_missing:
        print(
            "conformance-strict: FAILED: --allow-missing cannot relax blocking C1 release claims",
            file=sys.stderr,
        )
        return 1

    if args.test_fixture_mode:
        try:
            exact_fixture_root = args.evidence_root.resolve() == Z_FIX_FIXTURE_ROOT.resolve()
        except OSError:
            exact_fixture_root = False
        try:
            exact_fixture_digest = (
                evidence_set_digest(args.evidence_root) == SAMPLE_FIXTURE_DIGEST
            )
        except OSError:
            exact_fixture_digest = False
        if (
            not exact_fixture_root
            or not exact_fixture_digest
            or args.candidate_sha != SAMPLE_CANDIDATE_SHA
        ):
            print(
                "conformance-strict: FAILED: fixture mode is bound to the checked-in "
                "z-fix samples, exact digest, and synthetic candidate",
                file=sys.stderr,
            )
            return 1

    errors = evaluate_release_evidence(
        args.evidence_root,
        args.candidate_sha,
        test_fixture_mode=args.test_fixture_mode,
    )
    if errors:
        print(f"conformance-strict: FAILED with {len(errors)} issue(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    claims, claim_errors = derive_release_claims()
    if claim_errors or not claims:
        print("conformance-strict: FAILED: zero C1 release claims exercised", file=sys.stderr)
        return 1
    mode = "TEST FIXTURE SCHEMA" if args.test_fixture_mode else "LIVE RELEASE EVIDENCE"
    print(
        f"conformance-strict: PASSED ({mode}) — {len(claims)}/{len(claims)} "
        f"blocking C1 claims, command 'z-fix', candidate {args.candidate_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
