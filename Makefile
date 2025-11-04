# Makefile for Agent Kernel

.PHONY: lint lint-check lint-fix format format-check help

# Default target
help:
	@echo "Available targets:"
	@echo "  lint        - Run black formatter on ak-py code (same as lint-fix)"
	@echo "  lint-check  - Check ak-py code formatting without making changes"
	@echo "  lint-fix    - Format ak-py code with black (fixes formatting issues)"
	@echo "  help        - Show this help message"

# Lint ak-py code using uv run black (fix formatting)
lint: lint-fix

lint-fix:
	@echo "Formatting ak-py code with black..."
	cd ak-py && uv run --dev black ./src ./tests

# Check ak-py code formatting without making changes
lint-check:
	@echo "Checking ak-py code formatting with black..."
	cd ak-py && uv run --dev black --check ./src ./tests
