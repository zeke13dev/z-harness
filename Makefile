SHELL := /usr/bin/env bash
.PHONY: conformance conformance-live conformance-record lint lint-strict preflight

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
