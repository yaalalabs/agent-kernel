.PHONY: lint lint-check lint-examples lint-examples-check lint-all lint-check-all help

# List of example directories to lint
EXAMPLE_DIRS := examples/api examples/cli examples/api/a2a examples/api/mcp examples/aws-containerized examples/aws-serverless examples/containerized

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
	cd ak-py && uv run --dev isort --skip src/agentkernel/core/__init__.py --check-only ./src ./tests
	@echo "Checking ak-py code formatting with black..."
	cd ak-py && uv run --dev black --check ./src ./tests

lint-examples:
	@echo "Formatting examples..."
	@for dir in $$(find $(EXAMPLE_DIRS) -maxdepth 2 -name "pyproject.toml" -type f | sed 's|/pyproject.toml||' | sort); do \
		echo "Processing $$dir..."; \
		if [ -f "$$dir/pyproject.toml" ]; then \
			cd $$dir && \
			if [ -d ".venv" ]; then \
				uv run --dev isort --skip .venv --skip .terraform --skip dist . || true; \
				uv run --dev black --exclude '/(\.venv|\.terraform|dist)/' . || true; \
			else \
				uv run --dev isort --skip .terraform --skip dist . || true; \
				uv run --dev black --exclude '/(\.terraform|dist)/' . || true; \
			fi && \
			cd - > /dev/null; \
		fi; \
	done

lint-examples-check:
	@echo "Checking examples formatting..."
	@for dir in $$(find $(EXAMPLE_DIRS) -maxdepth 2 -name "pyproject.toml" -type f | sed 's|/pyproject.toml||' | sort); do \
		echo "Checking $$dir..."; \
		if [ -f "$$dir/pyproject.toml" ]; then \
			cd $$dir && \
			if [ -d ".venv" ]; then \
				uv run --dev isort --check-only --skip .venv --skip .terraform --skip dist . || true; \
				uv run --dev black --check --exclude '/(\.venv|\.terraform|dist)/' . || true; \
			else \
				uv run --dev isort --check-only --skip .terraform --skip dist . || true; \
				uv run --dev black --check --exclude '/(\.terraform|dist)/' . || true; \
			fi && \
			cd - > /dev/null; \
		fi; \
	done

lint-all: lint lint-examples
	@echo "All linting completed!"

lint-check-all: lint-check lint-examples-check
	@echo "All lint checks completed!"
