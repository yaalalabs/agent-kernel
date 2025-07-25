# Agent Kernel Common Library

This package provides common utilities and functionality used by other components in the Agent Kernel monorepo.

## Features

- Configuration management utilities
- Logging functionality
- Common helper functions

## Development

To set up the development environment:

```bash
# Install development dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Format code
black .
isort .

# Type check
mypy .
```