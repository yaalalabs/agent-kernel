# Agent Kernel Python Distribution

This directory contains Agent Kernel's code. This follows a [uv](https://docs.astral.sh/uv/) based monorepo structure.

## Monorepo Structure

The monorepo consists of three main components:

1. **common** - Common library used by other components
   - Provides utility functions and shared functionality
   - Located in `ak-common/`

2. **core** - Agent core wrapper functions
   - Exposes functionality for agent logic developers
   - Depends on the common library
   - Located in `ak-core/`

3. **agents** - Agent logic implementation
   - Contains agent logic code written using common and core
   - Depends on both common and core libraries
   - Located in `ak-agents/`

## Development Setup

### Requirements

- Python 3.12 or higher
- uv package manager 0.8.0 or higher

#### To set up the development environment:

```bash
./build.sh
```
#### To run tests

```bash
uv run pytest
```

### Notes

1. Use root level `pyproject.toml` only to maintain common `dev` dependencies
2. Module level dependencies should be maintained individually, and the conflicts should either be managed manually (recommended) or overridden on root `pyproject.toml` with caution. 