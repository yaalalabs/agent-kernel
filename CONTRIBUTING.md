# Contributing to Agent Kernel

Thank you for your interest in contributing to Agent Kernel! We welcome contributions from the community and are excited to have you here.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Getting Started](#getting-started)
- [Pull Request Process](#pull-request-process)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Community](#community)

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## How to Contribute

There are many ways to contribute to Agent Kernel:

- **Agent Kernel core contributions**: Bug fixes, new features, performance improvements
- **Agent Kernel integrations**: New integrations to Agent Kernel (Eg: A messaging platform integration)
- **Documentation**: Improve existing docs, add examples, write tutorials
- **Testing**: Write tests, report bugs, verify fixes
- **Community support**: Help others in discussions and issues

## Developer Guide

See the [Developer Guide](DEVELOPER_GUIDE.md) for detailed setup instructions.

## Pull Request Process

### Before Submitting

1. **Ensure code quality**:
   - Run formatting checks: `make lint-check-all`
   - Fix any issues: `make lint-all`
   - See the [Developer Guide](DEVELOPER_GUIDE.md) for details

2. **Run tests**:
   ```bash
   cd ak-py
   uv run pytest
   ```

3. **Update documentation** if your changes affect:
   - Public APIs
   - Configuration options
   - User-facing behavior

4. **Write clear commit messages** following conventional commit format:
   ```
   type: brief description
   
   Optional longer description explaining the change
   ```
   
   **Commit Types:**
   - `feat`: New feature
   - `fix`: Bug fix
   - `docs`: Documentation only changes
   - `style`: Code style/formatting changes
   - `refactor`: Code refactoring
   - `test`: Adding or updating tests
   - `chore`: Maintenance tasks

   **Examples:**
   ```
   feat: add support for streaming responses
   
   fix: resolve session initialization bug
   
   docs: update installation instructions
   ```

### Submitting Your PR

If you have followed the guidelines in [Developer Guide](DEVELOPER_GUIDE.md) to fork the repository, refer below.


1. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Create a Pull Request** on GitHub with:
   - **Clear title**: Summarize the change in one line
   - **Description**: Explain what, why, and how
   - **Related issues**: Reference using `Fixes #123` or `Related to #456`
   - **Screenshots**: If UI changes are involved
   - **Testing notes**: How reviewers can test your changes

### PR Guidelines

- **Keep PRs focused**: One feature or fix per PR
- **Write clear descriptions**: Help reviewers understand your changes
- **Add tests**: Cover new functionality and edge cases
- **Update docs**: Keep documentation in sync with code
- **Respond to feedback**: Address review comments promptly
- **Keep history clean**: Squash or rebase if needed before merging
- **Ensure CI passes**: All automated checks must pass

## Reporting Bugs

When reporting bugs, please include:

1. **Description**: Clear and concise description of the bug
2. **Steps to reproduce**: Detailed steps to reproduce the issue
3. **Expected behavior**: What you expected to happen
4. **Actual behavior**: What actually happened
5. **Environment**:
   - Agent Kernel version
   - Python version
   - Operating system
   - Framework being used (Langraph, OpenAI Agents, etc.)
6. **Code sample**: Minimal reproducible example if possible
7. **Logs/Screenshots**: Any relevant error messages or screenshots

## Suggesting Features

We love feature suggestions! When proposing a new feature:

1. **Check existing issues**: See if it's already been suggested
2. **Describe the problem**: What problem does this feature solve?
3. **Propose a solution**: How do you envision this working?
4. **Consider alternatives**: What other solutions have you considered?
5. **Additional context**: Any other relevant information

## Community

- **GitHub Issues**: For bug reports and feature requests
- **Discussions**: For questions and general discussions
- **Pull Requests**: For code contributions

## Development Resources

- **[Developer Guide](DEVELOPER_GUIDE.md)**: Technical setup, tools, and development workflow
- **[README](README.md)**: Project overview and getting started
- **[Documentation](docs/)**: Full documentation and examples

## Questions?

If you have questions about contributing:
- Open a discussion on GitHub
- Review existing issues and PRs
- Check the [Developer Guide](DEVELOPER_GUIDE.md) for technical details
- Reach out to us via our [Discord Server](https://discord.gg/snrPzb46uu)

Thank you for contributing to Agent Kernel! 🎉
