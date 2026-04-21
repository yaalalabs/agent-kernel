---
name: ak-dev-code-quality
description: >
  Code quality standards, formatting, commit conventions, and PR workflow for
  Agent Kernel development. Use this skill when making contributions, formatting
  code, writing commit messages, or preparing pull requests.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Code Quality & Contribution Conventions

## Code Formatting

Agent Kernel uses `black` for formatting and `isort` for import sorting.

### Auto-format

```bash
# Format ak-py source and tests
make lint

# Format examples too
make lint-all
```

### Check only (CI mode, no changes)

```bash
make lint-check       # ak-py only
make lint-check-all   # ak-py + examples
```

### Configuration

In `ak-py/pyproject.toml`:

```toml
[tool.black]
line-length = 150
target-version = ["py312"]

[tool.isort]
profile = "black"
line_length = 150
```

In example projects, line length is 120:

```toml
[tool.black]
line-length = 120
target-version = ["py312"]
```

### Type Checking

```bash
cd ak-py
uv run mypy src/
```

Configuration:
```toml
[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
```

## Commit Convention

Use **Conventional Commits** format:

```
<type>: <short description>
```

### Types

| Type | When to Use |
|------|------------|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `docs:` | Documentation changes only |
| `chore:` | Maintenance, dependencies, config |
| `refactor:` | Code restructuring without behavior change |
| `test:` | Adding or modifying tests |

### Examples

```
feat: add telegram messaging integration
fix: handle empty session in Redis store
docs: update deployment guide for Azure containerized
chore: bump openai-agents dependency to 0.6.5
refactor: extract common guardrail logic to base class
test: add unit tests for CosmosDB session store
```

### Rules

- Use lowercase for commit type and description
- Keep the description under 72 characters
- Use imperative mood ("add feature" not "added feature")
- No period at the end
- Reference issue numbers when applicable: `feat: add telegram integration (#123)`

## Pull Request Process

### Before Submitting

1. **Run tests**: `cd ak-py && uv run pytest`
2. **Run linting**: `make lint-check-all`
<!-- 3. **Run type checks**: `cd ak-py && uv run mypy src/` Enable after all mypy checks are passing -->
4. **Ensure no regressions** — all existing tests must pass

### PR Guidelines

- **One feature/fix per PR** — keep PRs focused
- **Include tests** — new features must have tests
- **Update docs** — if the change affects user-facing behavior
- **Add examples** — for new features, add or update examples
- **Fill in the PR template** — description, type of change, testing done

### PR Types

- **Core changes**: Modifications to `ak-py/src/agentkernel/core/`
- **Integration additions**: New messaging platforms, framework adapters
- **Documentation**: Updates to `docs/`, README files
- **Testing**: New or improved tests
- **Community support**: Bug reports, feature suggestions

## Version Management

### Version Bumping

Handled by publish.yaml workflow. This updates:

This updates:
- `ak-py/pyproject.toml` version field
- Terraform module versions
- Example dependency versions

### Version Locations

The version appears in:
- `ak-py/pyproject.toml` → `version = "x.y.z"`
- Terraform modules `version` fields in examples
- `agentkernel` dependency version constraints in example `pyproject.toml` files

## Development Setup

### Prerequisites

- Python 3.12–3.13.x
- `uv` package manager
- Git
- Make

### Setup

```bash
git clone https://github.com/yaalalabs/agent-kernel.git
cd agent-kernel/ak-py
./build.sh                    # Creates venv, installs deps
```

### Running Examples

```bash
cd examples/cli/openai
./build.sh
uv run demo.py
```

### Running Tests

```bash
cd examples/cli/openai
./build.sh
uv run pytest -s
```

## File Organization Conventions

- **Source**: `ak-py/src/agentkernel/` — all package source code
- **Tests**: `ak-py/tests/` — unit tests
- **Examples**: `examples/<mode>/<framework>/` — self-contained demo projects
- **Docs**: `docs/docs/` — Docusaurus documentation
- **Scripts**: `scripts/` — CI/CD and maintenance scripts
- **Terraform**: `ak-deployment/` — Terraform modules

## Python Style Guidelines

- Python 3.12+ features are encouraged (type unions with `|`, `match` statements)
- Use type hints for all function signatures
- Use `logging.getLogger("ak.<module>")` for logger names
- Use async/await for all I/O operations
- Prefer `BaseModel` (Pydantic) for data models
- Use `ABC` and `@abstractmethod` for interfaces
- Keep line length under 150 characters (120 for examples)

## Logging

### Logger Hierarchy

- **AK Logger** (`"ak"`): Parent logger for all Agent Kernel components
  - Child loggers like `"ak.api"`, `"ak.runtime"`, etc. inherit from this
  - Propagation is disabled at the AK level to prevent logs from bubbling to the root
  - Use `logging.getLogger("ak.<module>")` for Agent Kernel components

### Log Levels

The following log levels are supported (in order of verbosity):

- **DEBUG**: Detailed information for diagnosing problems
- **INFO**: General information about program execution
- **WARNING**: Something unexpected happened (default)
- **ERROR**: Due to a more serious problem, the software has not been able to perform some function
- **CRITICAL**: A serious error, indicating that the program itself may be unable to continue running
