SHELL := /usr/bin/env bash
.PHONY: test test-sh conformance conformance-live conformance-record conformance-strict lint lint-strict lint-frontmatter lint-halt preflight bench-autonomy-check test-ecc-lessons export release-dry-run release-verify version-sync version-check

# Full Python test suite: the unit/integration tests under tests/, the
# script-level tests under scripts/, and the runtime dispatch + driver tests
# under runtime/ (runtime/tests/ + runtime/drivers/*/tests/). This is the primary
# regression gate and is what CI (.github/workflows/tests.yml) runs.
# Requires Python 3.11+ (tomllib).
test: version-check
	python3 -m pytest tests/ scripts/ runtime/

# Standalone shell test scripts (bash assertion harnesses, not pytest).
# Each script self-reports pass/fail counts. Gated in CI (tests.yml).
# The *test*.sh scripts run with no args; overnight-preflight.sh and
# normalize-task-state.sh expose their tests behind a --self-test subcommand.
test-sh:
	@_fail=0; \
	for t in $$(ls scripts/*test*.sh | grep -v research); do \
	  echo "==> $$t"; \
	  bash "$$t" || { echo "FAILED: $$t" >&2; _fail=1; }; \
	done; \
	for t in scripts/overnight-preflight.sh scripts/normalize-task-state.sh; do \
	  echo "==> $$t --self-test"; \
	  bash "$$t" --self-test || { echo "FAILED: $$t" >&2; _fail=1; }; \
	done; \
	exit $$_fail

conformance:
	python3 -m pytest tests/conformance/ -v

conformance-live:
	python3 -m pytest tests/conformance/ -v --tb=short

conformance-record:
	python3 tests/conformance/run_conformance.py --command z-do --mode live --record --drivers $(DRIVER)

# Strict, fail-loud conformance gate (MF2 / audit-finding F7). A REAL
# integration check — NOT a placeholder:
#   - select_driver(host) must return a LIVE HostDriver for each of
#     claude/cursor/codex/antigravity (a missing host FAILS unless
#     ALLOW_MISSING=1 sets --allow-missing);
#   - select_driver("unknown") must raise DriverNotFoundError with a clear msg;
#   - each driver .init() with unset auth must not crash (clear config error);
#   - FAIL on zero actual driver coverage and on placeholder/missing fixtures.
# Both the standalone runner AND the pytest module (run with
# Z_HARNESS_CONFORMANCE_STRICT=1 so the fail-loud fixture check is enabled
# rather than skipped) must pass.
# This target is EXPECTED to fail until real fixtures are recorded
# (run_conformance.py --mode live --record) — that is the point of the gate.
conformance-strict:
	python3 tests/conformance/run_strict.py --command z-do $(if $(ALLOW_MISSING),--allow-missing,)
	Z_HARNESS_CONFORMANCE_STRICT=1 python3 -m pytest tests/conformance/test_strict.py -v

# AskUserQuestion callsite audit — documentation/audit tooling, NOT runtime enforcement.
# Unregistered callsites under Z_HARNESS_NO_ASK=halt still block until the user responds.
# 'make lint' runs --strict but treats exit 1 (unregistered callsites) as advisory.
# Exit 2 (usage error) or 3+ (hard error) propagate as failures.
# 'make lint-strict' exits 1 if unregistered callsites exist (for gates that enforce it).
lint:
	@echo "==> lint-askuser (unregistered callsites are advisory warnings, hard errors are fatal)"
	@bash scripts/lint-askuser.sh --strict; _ec=$$?; \
	  if [[ $$_ec -eq 1 ]]; then \
	    echo "WARNING: unregistered callsites found (advisory, not blocking)." >&2; \
	  elif [[ $$_ec -ne 0 ]]; then \
	    exit $$_ec; \
	  fi

lint-strict:
	bash scripts/lint-askuser.sh --strict

# Frontmatter YAML lint — validates all .md frontmatter with a strict YAML parser.
# Catches unquoted colons in descriptions (file:line, tasks: [...]) that the
# custom regex frontmatter parser silently accepts. Requires PyYAML.
lint-frontmatter:
	bash scripts/lint-frontmatter.sh

# Halt-category lint — validates that every ask_user RUNTIME-GATE in skills/*/SKILL.md
# carries a valid category= token from the halt_category enum
# {decision, risk, shortcut, archiving, mechanical_proceed}.
# Exit 0 = all gates tagged; exit 1 = missing or invalid category tokens.
# Wired into CI (lint-askuser.yml lint-halt-categories job).
lint-halt:
	bash scripts/lint-halt-categories.sh --strict --skills-dir skills

preflight:
	bash scripts/preflight.sh

# Version propagation. PATCH is auto-derived from the git commit count; the
# human-controlled MAJOR.MINOR lives in ./VERSION. `version-sync` rewrites the
# plugin manifests; `version-check` fails loudly on drift (wired into `test` so
# CI catches a commit whose manifests weren't stamped by the pre-commit hook).
version-sync:
	bash scripts/sync-version.sh sync

version-check:
	bash scripts/sync-version.sh --check

# Benchmark autonomy pre-run gate.
# Asserts (a) quick-build hot-path AskUserQuestion callsites are REGISTERED
# and (b) every hot-path gate is present in the frozen benchmark-autonomy.yaml policy.
# Exit 0 only if both pass; non-zero (loud) otherwise.
bench-autonomy-check:
	bash scripts/bench-autonomy-check.sh

# ECC lessons port — regression tests for new scripts (T017).
# Runs pytest on: test_cost_summary.py, test_context_budget.py, test_evaluate_session.py
test-ecc-lessons:
	python3 -m pytest scripts/test_cost_summary.py scripts/test_context_budget.py scripts/test_evaluate_session.py -v

# On-demand export generation — regenerates cursor, codex, and antigravity exports
# to temp/exports/ via runtime drivers (NOT the deprecated scripts/export-*.py).
# Runs fully offline; exits 0 only when all three hosts emit zero validation warnings.
# Wired into CI (tests.yml generate-exports job).  The temp/exports/ directory is
# .gitignored; exports are never committed.
export:
	python3 scripts/generate-exports.py

# Full release-publishing gate set for a single checked-out SHA. The release
# workflow runs this before creating any tag assets; each prerequisite must pass
# in this same worktree so a skipped/failing gate blocks publication.
release-verify: test test-sh
	python3 -m pytest tests/test_install_sh_integrity.py -v
	bash scripts/release-dry-run.sh

release-dry-run:
	bash scripts/release-dry-run.sh
