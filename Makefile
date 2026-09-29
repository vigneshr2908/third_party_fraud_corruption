.PHONY: help setup setup-dev install-graph install-linkage install-app check test lint format tree clean

PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

help:
	@echo ""
	@echo "  Third-Party Fraud & Corruption Network Detection  (APND-001)"
	@echo "  ------------------------------------------------------------------"
	@echo "  make setup           venv + editable install + core dependencies"
	@echo "  make setup-dev       as above plus dev tooling and pre-commit hooks"
	@echo "  make install-graph   neo4j, igraph, leidenalg        (needed at A7)"
	@echo "  make install-linkage splink                          (needed at A6)"
	@echo "  make install-app     streamlit, plotly, pyvis        (needed at A14)"
	@echo "  make check           environment and configuration health check"
	@echo "  make test            test suite with coverage"
	@echo "  make lint            ruff check"
	@echo "  make format          ruff format + autofix"
	@echo "  make tree            repository structure"
	@echo "  make clean           caches and build artefacts (data/ untouched)"
	@echo ""

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e .
	@echo "\nDone. Activate with:  source $(VENV)/bin/activate"

setup-dev: setup
	$(BIN)/pip install -e ".[dev]"
	$(BIN)/pre-commit install
	@echo "\nDev environment ready. Pre-commit hooks installed."

install-graph:
	$(BIN)/pip install -e ".[graph]"

install-linkage:
	$(BIN)/pip install -e ".[linkage]"

install-app:
	$(BIN)/pip install -e ".[app]"

check:
	$(BIN)/apnd check

test:
	$(BIN)/pytest --cov=src/apnd --cov-report=term-missing

lint:
	$(BIN)/ruff check src tests

format:
	$(BIN)/ruff format src tests
	$(BIN)/ruff check --fix src tests

tree:
	@find . -type f -not -path './.git/*' -not -path './$(VENV)/*' \
		-not -path '*/__pycache__/*' -not -path './data/*' -not -path './outputs/*' | sort

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov build dist src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned. data/ and outputs/ untouched."