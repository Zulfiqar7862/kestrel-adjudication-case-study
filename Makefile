.PHONY: install test lint run-ingest run-all demo api clean

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

test:
	$(PY) -m pytest tests prototype/tests -q

lint:
	$(VENV)/bin/ruff check src tests || true

run-ingest:
	$(PY) -m kestrel_sentinel.cli ingest --reload

run-all:
	$(PY) -m kestrel_sentinel.cli adjudicate --out examples/adjudication_results.csv

demo:
	$(PY) -m kestrel_sentinel.cli adjudicate --event EXC-107133
	$(PY) -m kestrel_sentinel.cli basis --event EXC-107133 --tenant T-KAVERI --out examples/basis_EXC-107133.json
	$(PY) -m kestrel_sentinel.cli shadow-bulletin --out examples/shadow_bulletin_diff.json
	$(PY) scripts/collect_demo_outputs.py

api:
	$(PY) -m kestrel_sentinel.cli serve --host 127.0.0.1 --port 8080

clean:
	rm -rf .data .pytest_cache **/__pycache__
