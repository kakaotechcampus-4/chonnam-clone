.PHONY: test e2e e2e-schedule e2e-week05 e2e-week05-update e2e-week06

E2E_ARGS ?=

test:
	uv run python -m unittest discover -s tests

e2e: e2e-schedule e2e-week05 e2e-week06

e2e-schedule:
	uv run python tests/e2e/schedule/run_scenarios.py $(E2E_ARGS)

e2e-week05:
	uv run python tests/e2e/week05_mcp/run_scenarios.py $(E2E_ARGS)

e2e-week05-update:
	uv run python tests/e2e/week05_mcp/run_scenarios.py --scenarios tests/e2e/week05_mcp/schedule_update_scenarios.json $(E2E_ARGS)

e2e-week06:
	uv run python tests/e2e/week06_supervisor/run_scenarios.py $(E2E_ARGS)
