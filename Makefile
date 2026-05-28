.PHONY: conformance conformance-live conformance-record lint lint-strict preflight

conformance:
	python3 -m pytest tests/conformance/ -v

conformance-live:
	python3 -m pytest tests/conformance/ -v --tb=short

conformance-record:
	python3 tests/conformance/run_conformance.py --command z-do --mode live --record --drivers $(DRIVER)

# AskUserQuestion callsite audit — documentation/audit tooling, NOT runtime enforcement.
# Unregistered callsites under Z_HARNESS_NO_ASK=halt still block until the user responds.
# 'make lint' runs non-strict (advisory warnings, exits 0).
# 'make lint-strict' exits 1 if unregistered callsites exist (for gates that enforce it).
lint:
	@echo "==> lint-askuser (advisory — unregistered callsites are warnings, not errors)"
	@bash scripts/lint-askuser.sh || true

lint-strict:
	bash scripts/lint-askuser.sh --strict

preflight:
	bash scripts/preflight.sh
