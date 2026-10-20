.PHONY: dev-setup lint lint-check lint-examples lint-examples-check lint-all lint-check-all deploy-inject deploy-revert help

EXAMPLE_DIRS := examples

# Example linters run standalone via uvx (isolated, no project env): black/isort only
# format .py text and must never resolve an example's agentkernel dependency — some example
# locks legitimately pin agentkernel to a local ../../../ak-py/dist source (an unreleased
# extra), which a project-env sync would fail to resolve during lint. Pin black to match
# the version examples pin in their dev groups so formatting is identical.
BLACK_VERSION := 26.5.1

# Ruff enforces only the pyupgrade typing rules (PEP 585/604 annotations, collections.abc imports).
# ak-py reads them from [tool.ruff] in ak-py/pyproject.toml; examples run ruff via uvx in --isolated
# mode (same reason as black above), so keep these and the version in sync with ak-py.
RUFF_VERSION := 0.17.1
RUFF_RULES := UP006,UP007,UP035,UP045
RUFF_EXAMPLES := uvx ruff@$(RUFF_VERSION) check --isolated --target-version py312 --select $(RUFF_RULES) \
	--extend-exclude '.terraform,dist*,__pycache__'

# Ensure venv uses pyenv-managed Python when available
define ENSURE_PYENV_VENV
if command -v pyenv >/dev/null 2>&1; then \
	uv venv --python "$$(pyenv which python)" --allow-existing; \
else \
	uv venv --allow-existing; \
fi
endef

help:
	@echo "Available targets:"
	@echo "  dev-setup           - Installs prerequisites (pyenv, Python, uv) and syncs ak-py"
	@echo "  lint                - Formats python code and modernizes type annotations in ak-py"
	@echo "  lint-check          - Dry run to check code formatting and type annotations in ak-py"
	@echo "  lint-examples       - Formats python code and modernizes type annotations in examples"
	@echo "  lint-examples-check - Dry run to check code formatting and type annotations in examples"
	@echo "  lint-all            - Formats python code in both ak-py and examples"
	@echo "  lint-check-all      - Dry run to check code formatting in both ak-py and examples"
	@echo "  deploy-inject       - Injects local module sources/backend.tf into deployment examples"
	@echo "  deploy-revert       - Reverts deployment examples back to registry module sources"
	@echo "  help                - Show this help message"

dev-setup:
	@./scripts/dev-setup.sh

lint: lint-fix

lint-fix:
	@cd ak-py && $(ENSURE_PYENV_VENV)
	@echo "Modernizing type annotations with ruff..."
	cd ak-py && uv run --dev ruff check --fix --exit-zero ./src ./tests
	@echo "Sorting imports with isort..."
	cd ak-py && uv run --dev isort --skip src/agentkernel/core/__init__.py ./src ./tests
	@echo "Formatting ak-py code with black..."
	cd ak-py && uv run --dev black ./src ./tests

lint-check:
	@cd ak-py && $(ENSURE_PYENV_VENV)
	@echo "Checking import sorting with isort..."
	@EXIT_CODE=0; \
	(cd ak-py && uv run --dev isort --skip src/agentkernel/core/__init__.py --check-only ./src ./tests) || EXIT_CODE=$$?; \
	echo "Checking ak-py code formatting with black..."; \
	(cd ak-py && uv run --dev black --check ./src ./tests) || EXIT_CODE=$$?; \
	echo "Checking ak-py type annotations with ruff..."; \
	(cd ak-py && uv run --dev ruff check ./src ./tests) || EXIT_CODE=$$?; \
	if [ $$EXIT_CODE -ne 0 ]; then \
		echo "❌ Linting errors found in ak-py!"; \
	fi; \
	exit $$EXIT_CODE

lint-examples:
	@echo "Modernizing example type annotations with ruff..."
	@$(RUFF_EXAMPLES) --fix --exit-zero $(EXAMPLE_DIRS)
	@echo "Formatting examples..."
	@for dir in $$(find $(EXAMPLE_DIRS) -maxdepth 4 -name "pyproject.toml" -type f | sed 's|/pyproject.toml||' | sort); do \
		echo "Processing $$dir..."; \
		if [ -f "$$dir/pyproject.toml" ]; then \
			cd $$dir && \
			uvx isort --skip .venv --skip .terraform --skip-glob "dist*" --skip __pycache__ . || true; \
			uvx black@$(BLACK_VERSION) --exclude '/\.venv/|/\.terraform/|/dist[^/]*/|/__pycache__/' . || true; \
			cd - > /dev/null; \
		fi; \
	done

lint-examples-check:
	@echo "Checking examples formatting..."
	@EXIT_CODE=0; \
	for dir in $$(find $(EXAMPLE_DIRS) -maxdepth 4 -name "pyproject.toml" -type f | sed 's|/pyproject.toml||' | sort); do \
		echo "Checking $$dir..."; \
		if [ -f "$$dir/pyproject.toml" ]; then \
			cd $$dir && \
			uvx isort --check-only --skip .venv --skip .terraform --skip-glob "dist*" --skip __pycache__ . || EXIT_CODE=1; \
			uvx black@$(BLACK_VERSION) --check --exclude '/\.venv/|/\.terraform/|/dist[^/]*/|/__pycache__/' . || EXIT_CODE=1; \
			cd - > /dev/null; \
		fi; \
	done; \
	echo "Checking example type annotations with ruff..."; \
	$(RUFF_EXAMPLES) $(EXAMPLE_DIRS) || EXIT_CODE=1; \
	if [ $$EXIT_CODE -ne 0 ]; then \
		echo "❌ Linting errors found in examples!"; \
	fi; \
	exit $$EXIT_CODE

lint-all: lint lint-examples
	@echo "All linting completed!"

lint-check-all: lint-check lint-examples-check
	@echo "All lint checks completed!"

deploy-inject:
	@python3 scripts/deploy/inject_dependencies.py

deploy-revert:
	@python3 scripts/deploy/inject_dependencies.py --revert
