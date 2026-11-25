# Contributing to Open Agent Kernel

Thank you for your interest in contributing to Open Agent Kernel (OAK)! We welcome contributions from the community and are excited to have you here.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Developer Guide](#developer-guide)
- [Pull Request Process](#pull-request-process)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Community](#community)

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## How to Contribute

There are many ways to contribute to OAK:

- **OAK core contributions**: Bug fixes, new features, performance improvements
- **OAK integrations**: New integrations to OAK (Eg: A messaging platform integration)
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

4. **Add a changelog fragment** if users of OAK would notice the change. See
   [Changelog entries](#changelog-entries) below.

5. **Write clear commit messages** following conventional commit format:
   ```
   type: brief description
   
   Optional longer description explaining the change
   ```

   An optional scope narrows the type: `type(scope): brief description`, for example
   `fix(ws): reconnect gateway after broker restart` or `chore(auto): sync skills/docs`.
   
   **Commit Types:**
   - `feat`: New feature
   - `fix`: Bug fix
   - `docs`: Documentation only changes
   - `style`: Code style/formatting changes
   - `refactor`: Code refactoring
   - `test`: Adding or updating tests
   - `chore`: Maintenance tasks
   - `ci`: CI configuration and workflow changes
   - `build`: Build system, packaging, and dependency changes
   - `perf`: Performance improvements

   **Examples:**
   ```
   feat: add support for streaming responses
   
   fix: resolve session initialization bug
   
   docs: update installation instructions
   ```

### Changelog entries

[CHANGELOG.md](CHANGELOG.md) is built from small fragment files, one per change, so pull requests
never conflict on it. Add the fragment in the same PR as the change; never edit `CHANGELOG.md`
itself. When a release is published, the Publish workflow compiles the fragments into a new version
section with [towncrier](https://towncrier.readthedocs.io/) and deletes them.

**When you need one.** Add a fragment for anything a user of the `agentkernel` package, the Helm
chart, the Terraform modules, the bundled skills or the deployment templates would notice:

- an added or removed capability, framework, provider or deployment target
- an added, renamed or removed config key, API field or CLI flag, or a changed default
- a behaviour change, a bug fix a user could have hit, or a security fix
- a dependency bound change that affects installs

Tests, CI, internal refactors with no behaviour change, docs-only changes and blog posts need none.

**File name.** `changelog.d/<issue>.<type>.md`, where `<issue>` is the GitHub issue the PR fixes,
for example `changelog.d/664.added.md`. A second entry for the same issue and type adds a counter
(`664.added.1.md`); in a stack of PRs for one issue, each PR uses its own counter. A PR with no
issue uses `+<short-slug>.<type>.md`, which is rendered without a link.

| Type | Use it for |
| --- | --- |
| `breaking` | Anything that makes existing code, config or deployments stop working |
| `added` | New capability, framework, provider, deployment target, config key, API field or CLI flag |
| `changed` | Changed behaviour or default that keeps working without changes |
| `deprecated` | Something still works but will be removed |
| `removed` | Something removed that nobody should still depend on (otherwise `breaking`) |
| `fixed` | A bug a user could have hit |
| `security` | A security fix |

**Content.** One to three sentences of Markdown, written for someone using OAK:

- say what changed in their terms (config key, API field, CLI flag, deployment target), not how
  it was built
- link the docs page when there is one (`https://kernel.yaala.ai/docs/...`)
- in a `breaking` fragment, say what to change, starting "To migrate, ..."
- name the surface when it is not the Python package: "Helm chart: ...", "Terraform: ..."
- the issue link is added for you

**The check.** The **Changelog Check** workflow fails a `feat`, `fix`, `perf`, `refactor`,
`build` or `chore` PR that neither adds a fragment nor updates a pending one, a PR whose title has
`!` but adds no `breaking` fragment, and any PR that adds or edits a fragment with an invalid name.
`docs`, `test`, `ci` and `style` PRs need no fragment. A fix to a change that has not been released
yet corrects that change's pending fragment instead of adding a `fixed` one. If your PR changes
nothing users would notice, ask a maintainer to add the `no-changelog` label.

**Versioning.** Before 1.0, any release may contain breaking changes; they are always listed under
Breaking changes. While a `breaking` fragment is pending, the Publish workflow refuses a version
that does not raise the minor version over the last release in `CHANGELOG.md`, so a breaking change
ships in at least a minor release.

Preview what the next release will say with
`uvx towncrier@26.9.0 build --draft --version next`.

### Submitting Your PR

If you have followed the guidelines in [Developer Guide](DEVELOPER_GUIDE.md) to fork the repository, refer below.


1. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Create a Pull Request** on GitHub with:
   - **Conventional title**: Use the same `type: description` or `type(scope): description`
     format as commit messages, with one of the types listed above (for example
     `feat: add telegram messaging integration`). The **PR Title Check** workflow fails the PR
     otherwise. `develop` only accepts squash merges, so the title becomes the commit subject.
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

### Review Workflow

- **Copilot review**: A GitHub Copilot code review is requested only when a maintainer adds the
  `Request Copilot` label to a PR, since each review is billed to a maintainer's license. You
  cannot apply labels yourself; ask a maintainer if you would like one.
- **`Reviewed` label**: Maintainers add the `Reviewed` label once they have gone through a PR.
  Pushing new commits removes the label automatically so the PR shows up again in the review
  queue (`is:pr is:open -label:Reviewed`). Do not add or remove the label yourself.

## Reporting Bugs

When reporting bugs, please include:

1. **Description**: Clear and concise description of the bug
2. **Steps to reproduce**: Detailed steps to reproduce the issue
3. **Expected behavior**: What you expected to happen
4. **Actual behavior**: What actually happened
5. **Environment**:
   - OAK version
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
- **[AGENTS.md](AGENTS.md)**: Guidance for AI coding agents contributing to this repo
- **[README](README.md)**: Project overview and getting started
- **[Documentation](docs/)**: Full documentation and examples

## Questions?

If you have questions about contributing:
- Open a discussion on GitHub
- Review existing issues and PRs
- Check the [Developer Guide](DEVELOPER_GUIDE.md) for technical details
- Reach out to us via our [Discord Server](https://discord.gg/snrPzb46uu)

Thank you for contributing to OAK! 🎉
