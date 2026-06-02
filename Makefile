SHELL := /usr/bin/env bash
.PHONY: test test-sh conformance conformance-live conformance-record lint lint-strict preflight bench-autonomy-check

# Full Python test suite: the unit/integration tests under tests/, the
# script-level tests under scripts/, and the runtime dispatch + driver tests
# under runtime/ (runtime/tests/ + runtime/drivers/*/tests/). This is the primary
# regression gate and is what CI (.github/workflows/tests.yml) runs.
# Requires Python 3.11+ (tomllib).
test:
	python3 -m pytest tests/ scripts/ runtime/

# Standalone shell test scripts (bash assertion harnesses, not pytest).
# Run for local verification; each script self-reports pass/fail counts.
test-sh:
	@_fail=0; \
	for t in $$(ls scripts/*test*.sh | grep -v research); do \
	  echo "==> $$t"; \
	  bash "$$t" || { echo "FAILED: $$t" >&2; _fail=1; }; \
	done; \
	exit $$_fail

conformance:
	python3 -m pytest tests/conformance/ -v

conformance-live:
	python3 -m pytest tests/conformance/ -v --tb=short

conformance-record:
	python3 tests/conformance/run_conformance.py --command z-do --mode live --record --drivers $(DRIVER)

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

preflight:
	bash scripts/preflight.sh

# Benchmark autonomy pre-run gate.
# Asserts (a) quick-build hot-path AskUserQuestion callsites are REGISTERED
# and (b) every hot-path gate is present in the frozen benchmark-autonomy.yaml policy.
# Exit 0 only if both pass; non-zero (loud) otherwise.
bench-autonomy-check:
	bash scripts/bench-autonomy-check.sh
