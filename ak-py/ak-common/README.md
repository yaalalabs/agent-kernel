# Agent Kernel Common Library

This package provides common utilities and functionality used by other components in the Agent Kernel monorepo.

## Features

- Configuration management utilities
- Logging functionality
- Common helper functions

## Installation

### From Source

```bash
cd ak-py/common
uv pip install -e .
```

### As a Dependency

In your pyproject.toml:

```toml
dependencies = [
    "ak_common==0.1.0",
]
```

## Usage

```python
from ak_common.utils import Logger, validate_config, merge_configs

# Create a logger
logger = Logger("MyComponent")
logger.info("This is an info message")
logger.error("This is an error message")
logger.debug("This is a debug message")

# Validate a configuration
config = {"key": "value"}
is_valid = validate_config(config)
print(f"Config is valid: {is_valid}")

# Merge configurations
base_config = {"key1": "value1", "key2": "value2"}
override_config = {"key2": "new_value", "key3": "value3"}
merged_config = merge_configs(base_config, override_config)
print(merged_config)
# Output: {'key1': 'value1', 'key2': 'new_value', 'key3': 'value3'}
```

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