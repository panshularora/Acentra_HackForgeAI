# Common development tasks. Run `make help` for the list.

PYTHON  ?= python3
VENV    := backend/.venv
BIN     := $(VENV)/bin
RATE    ?= 40

.DEFAULT_GOAL := help
.PHONY: help install dev test lint format typecheck check loggen incident-db incident-auth replay moto feed sns-tail demo clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Create the backend virtualenv and install dependencies
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e "backend[dev]"

dev: ## Run the API with auto-reload on :8000
	$(BIN)/uvicorn app.main:app --app-dir backend --reload --port 8000

test: ## Run the backend test suite
	cd backend && .venv/bin/pytest

lint: ## Lint and check formatting
	cd backend && .venv/bin/ruff check . ../tools && .venv/bin/ruff format --check . ../tools

format: ## Apply formatting and safe lint fixes
	cd backend && .venv/bin/ruff check --fix . ../tools && .venv/bin/ruff format . ../tools

typecheck: ## Static type check
	cd backend && .venv/bin/mypy app ../tools

check: lint typecheck test ## Everything CI runs

loggen: ## Write normal claims traffic to logs/app.log (RATE=40)
	$(BIN)/python tools/loggen.py --rate $(RATE)

incident-db: ## Inject a 45 s claim-adjudication database outage
	$(BIN)/python tools/loggen.py --incident db-outage --duration 45

incident-auth: ## Inject a 30 s credential-stuffing burst against member-auth
	$(BIN)/python tools/loggen.py --incident cred-stuffing --duration 30

replay: ## Replay a known scenario and print detection latency and false alarms
	PYTHONPATH=backend $(BIN)/python tools/replay.py

moto: ## Run the local AWS emulator (SNS, CloudWatch Logs, SQS) on :5000
	$(BIN)/moto_server -p 5000

feed: ## Print the live WebSocket feed in the terminal
	$(BIN)/python tools/watch_feed.py

sns-tail: ## Print alerts as delivered through SNS (via an SQS subscription)
	$(BIN)/python tools/sns_tail.py

clean: ## Remove caches and local state
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache claimswatch.db logs
