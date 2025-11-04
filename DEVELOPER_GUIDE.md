# Developer Guide

This guide provides essential information for developers working on the Agent Kernel project.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Development Setup](#development-setup)
- [Makefile Commands](#makefile-commands)
- [Code Quality](#code-quality)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

## Prerequisites

Before you begin development, ensure you have the following installed:

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) - Fast Python package installer and resolver
- Git
- Make

## Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yaalalabs/agent-kernel.git
   cd agent-kernel
   ```

2. **Navigate to the Python package**
   ```bash
   cd ak-py
   ```

3. **Install development dependencies**
   ```bash
   ./build.sh
   ```

## Makefile Commands

The project includes a Makefile with several useful commands for code formatting and quality checks. All commands should be run from the root directory of the project.

### Available Commands

To see all available Makefile commands:
```bash
make help
```
## Code Quality

### Formatting Standards

Agent Kernel uses the following tools to maintain code quality:

- **[black](https://github.com/psf/black)**: Opinionated code formatter
- **[isort](https://pycqa.github.io/isort/)**: Import statement organizer

### Pre-commit Workflow

Before committing code, run:
```bash
make lint-check-all
```

This ensures your code meets the project's formatting standards without making changes. If issues are found, run:
```bash
make lint-all
```

to automatically fix formatting issues.


## Contributing

### Development Workflow

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write code following the project's conventions
   - Add tests for new functionality

3. **Verify formatting**
   ```bash
   make lint-check-all
   ```

4. **Format your code**
   ```bash
   make lint-all
   ```

5. **Run tests**
   ```bash
   cd ak-py
   uv run pytest
   ```

6. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: describe your changes"
   ```

7. **Push to your branch**
   ```bash
   git push origin feature/your-feature-name
   ```

### Commit Message Convention

Follow conventional commit format:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `chore:` - Maintenance tasks
- `refactor:` - Code refactoring
- `test:` - Test additions or modifications

### Code Review

- Ensure all formatting checks pass
- Add appropriate tests
- Ensure all CI tests pass
- Update documentation if needed
- Request review from maintainers

## Additional Resources

- [Main README](README.md) - Project overview and usage
- [Documentation Setup](docs/SETUP.md) - Setting up the documentation site
- [Examples](examples/) - Sample implementations
