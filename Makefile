.PHONY: lint lint-check help

help:
	@echo "Available targets:"
	@echo "  lint        - Formats python code"
	@echo "  lint-check  - Dry run to check code formatting"
	@echo "  help        - Show this help message"

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
