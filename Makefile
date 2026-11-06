PYTHON ?= python3

.PHONY: install lint format test cov run-all serve docker-build docker-run clean

install:          ## Install the package with API and dev extras (editable)
	$(PYTHON) -m pip install -e ".[api,dev]"

lint:             ## Ruff lint + format check
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

format:           ## Auto-fix lint issues and format
	$(PYTHON) -m ruff check --fix src tests
	$(PYTHON) -m ruff format src tests

test:             ## Run the test suite
	$(PYTHON) -m pytest

cov:              ## Tests with coverage report
	$(PYTHON) -m pytest --cov=kestrel --cov-report=term-missing

run-all:          ## Adjudicate all 420 alerts and print the disposition counts
	kestrel run-all

serve:            ## API + reviewer dashboard on http://127.0.0.1:8080/ui
	kestrel serve

docker-build:
	docker build -t kestrel-sentinel .

docker-run:
	docker run --rm -p 8080:8080 kestrel-sentinel

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
