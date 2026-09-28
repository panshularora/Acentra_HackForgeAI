# Common development tasks. Run `make help` for the list.

PYTHON  ?= python3
VENV    := backend/.venv
BIN     := $(VENV)/bin
RATE    ?= 40

.DEFAULT_GOAL := help
.PHONY: help install dev test lint format typecheck check loggen incident-db incident-auth incident-new incident-silence incident-flow replay moto feed sns-tail sns-check dashboard demo clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Create the backend virtualenv and install dependencies
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e "backend[dev]"

dev: ## Run the API with auto-reload on :8000
	$(BIN)/uvicorn app.main:app --app-dir backend --reload --port 8000

dashboard: ## Run the dashboard dev server on :5173 (proxies to :8000)
	cd frontend && npm install && npm run dev

demo: ## Run the whole stack (moto, backend, loggen, dashboard) with Docker
	docker compose up --build

test: ## Run the backend test suite
	cd backend && .venv/bin/pytest

lint: ## Lint and check formatting
	cd backend && .venv/bin/ruff check . ../tools && .venv/bin/ruff format --check . ../tools

format: ## Apply formatting and safe lint fixes
	cd backend && .venv/bin/ruff check --fix . ../tools && .venv/bin/ruff format . ../tools

typecheck: ## Static type check
	cd backend && .venv/bin/mypy app ../tools

check: lint typecheck test ## Everything CI runs

loggen: ## Write normal traffic, heartbeats and claim flows to logs/app.log (RATE=40)
	$(BIN)/python tools/loggen.py --rate $(RATE)

incident-db: ## Inject a 45 s claim-adjudication database outage
	$(BIN)/python tools/loggen.py --incident db-outage --duration 45

incident-auth: ## Inject a 30 s credential-stuffing burst against member-auth
	$(BIN)/python tools/loggen.py --incident cred-stuffing --duration 30

incident-new: ## Inject 45 s of a never-seen TLS error calling the payer gateway
	$(BIN)/python tools/loggen.py --incident new-error --duration 45

incident-silence: ## Silence eligibility-sync heartbeats for 60 s (needs `make loggen`)
	$(BIN)/python tools/loggen.py --incident heartbeat-stop --duration 60

incident-flow: ## Stop adjudicating validated claims for 60 s (needs `make loggen`)
	$(BIN)/python tools/loggen.py --incident flow-break --duration 60

replay: ## Replay a known scenario and print detection latency and false alarms
	PYTHONPATH=backend $(BIN)/python tools/replay.py

moto: ## Run the local AWS emulator (SNS, CloudWatch Logs, SQS) on :5000
	$(BIN)/moto_server -p 5000

feed: ## Print the live WebSocket feed in the terminal
	$(BIN)/python tools/watch_feed.py

sns-tail: ## Print alerts as delivered through SNS (via an SQS subscription)
	$(BIN)/python tools/sns_tail.py

sns-check: ## Send one test alert through the configured SNS topic
	PYTHONPATH=backend $(BIN)/python tools/sns_check.py

clean: ## Remove caches and local state
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache claimswatch.db logs
