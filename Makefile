.PHONY: lint lint-check lint-examples lint-examples-check lint-all lint-check-all help

EXAMPLE_DIRS := examples

help:
	@echo "Available targets:"
	@echo "  lint                - Formats python code in ak-py"
	@echo "  lint-check          - Dry run to check code formatting in ak-py"
	@echo "  lint-examples       - Formats python code in examples directory"
	@echo "  lint-examples-check - Dry run to check code formatting in examples"
	@echo "  lint-all            - Formats python code in both ak-py and examples"
	@echo "  lint-check-all      - Dry run to check code formatting in both ak-py and examples"
	@echo "  help                - Show this help message"

lint: lint-fix

lint-fix:
	@echo "Sorting imports with isort..."
	cd ak-py && uv run --dev isort --skip src/agentkernel/core/__init__.py ./src ./tests
	@echo "Formatting ak-py code with black..."
	cd ak-py && uv run --dev black ./src ./tests

lint-check:
	@echo "Checking import sorting with isort..."
	@EXIT_CODE=0; \
	(cd ak-py && uv run --dev isort --skip src/agentkernel/core/__init__.py --check-only ./src ./tests) || EXIT_CODE=$$?; \
	echo "Checking ak-py code formatting with black..."; \
	(cd ak-py && uv run --dev black --check ./src ./tests) || EXIT_CODE=$$?; \
	if [ $$EXIT_CODE -ne 0 ]; then \
		echo "❌ Linting errors found in ak-py!"; \
	fi; \
	exit $$EXIT_CODE

lint-examples:
	@echo "Building ak-py to ensure dependencies are installed..."
	cd ak-py && ./build.sh
	@echo "Formatting examples..."
	@for dir in $$(find $(EXAMPLE_DIRS) -maxdepth 4 -name "pyproject.toml" -type f | sed 's|/pyproject.toml||' | sort); do \
		echo "Processing $$dir..."; \
		if [ -f "$$dir/pyproject.toml" ]; then \
			cd $$dir && \
			uv run --dev isort --skip .venv --skip .terraform --skip dist --skip __pycache__ . || true; \
			uv run --dev black --exclude '/\.venv/|/\.terraform/|/dist/|/__pycache__/' . || true; \
			cd - > /dev/null; \
		fi; \
	done

lint-examples-check:
	@echo "Building ak-py to ensure dependencies are installed..."
	cd ak-py && ./build.sh
	@echo "Checking examples formatting..."
	@EXIT_CODE=0; \
	for dir in $$(find $(EXAMPLE_DIRS) -maxdepth 4 -name "pyproject.toml" -type f | sed 's|/pyproject.toml||' | sort); do \
		echo "Checking $$dir..."; \
		if [ -f "$$dir/pyproject.toml" ]; then \
			cd $$dir && \
			uv run --dev isort --check-only --skip .venv --skip .terraform --skip dist --skip __pycache__ . || EXIT_CODE=1; \
			uv run --dev black --check --exclude '/\.venv/|/\.terraform/|/dist/|/__pycache__/' . || EXIT_CODE=1; \
			cd - > /dev/null; \
		fi; \
	done; \
	if [ $$EXIT_CODE -ne 0 ]; then \
		echo "❌ Linting errors found in examples!"; \
	fi; \
	exit $$EXIT_CODE

lint-all: lint lint-examples
	@echo "All linting completed!"

lint-check-all: lint-check lint-examples-check
	@echo "All lint checks completed!"
