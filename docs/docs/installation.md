---
sidebar_position: 2
---

# Installation

Get started with Agent Kernel in just a few minutes.

## Prerequisites

Before installing Agent Kernel, ensure you have:

- **Python 3.12 or higher** installed on your system
- **pip** or **uv** package manager
- (Optional) **Virtual environment** tool like `venv` or `conda`

## Basic Installation

Install Agent Kernel using pip:

```bash
pip install agentkernel
```

This installs the core Agent Kernel library with minimal dependencies.

## Framework-Specific Installation

Agent Kernel supports multiple AI agent frameworks. Install the extras for the framework(s) you plan to use:

### OpenAI Agents

```bash
pip install agentkernel[openai]
```

### CrewAI

```bash
pip install agentkernel[crewai]
```

### LangGraph

```bash
pip install agentkernel[langgraph]
```

### Google ADK

```bash
pip install agentkernel[adk]
```

### Multiple Frameworks

You can install support for multiple frameworks at once:

```bash
pip install agentkernel[openai,crewai,langgraph]
```

## Additional Components

### REST API Server

For running agents with REST API endpoints:

```bash
pip install agentkernel[api]
```

### AWS Deployment

For deploying to AWS Lambda or ECS:

```bash
pip install agentkernel[aws]
```

### CLI Testing

For interactive command-line testing (included by default):

```bash
pip install agentkernel[cli]
```

### All Features

Install everything:

```bash
pip install agentkernel[openai,crewai,langgraph,adk,api,aws,cli]
```

## Using UV Package Manager

[UV](https://github.com/astral-sh/uv) is a fast Python package installer. If you're using UV:

```bash
uv pip install agentkernel[openai,crewai,langgraph,api]
```

## Virtual Environment Setup

We recommend using a virtual environment to avoid dependency conflicts:

### Using venv

```bash
# Create virtual environment
python -m venv ak-env

# Activate (Linux/macOS)
source ak-env/bin/activate

# Activate (Windows)
ak-env\Scripts\activate

# Install Agent Kernel
pip install agentkernel[openai,api]
```

### Using conda

```bash
# Create conda environment
conda create -n ak-env python=3.12

# Activate
conda activate ak-env

# Install Agent Kernel
pip install agentkernel[openai,api]
```

## Verify Installation

After installation, verify that Agent Kernel is installed correctly:

```bash
python -c "import agentkernel; print(agentkernel.__version__)"
```

You should see the version number printed (e.g., `0.1.2b17`).

## Development Installation

If you want to contribute to Agent Kernel or modify the source code:

```bash
# Clone the repository
git clone https://github.com/yaalalabs/agent-kernel.git
cd agent-kernel/ak-py

# Install in development mode
pip install -e ".[openai,crewai,langgraph,adk,api,aws,cli,test]"
```

## Configuration

Agent Kernel can be configured using environment variables or a configuration file. See the [Configuration Guide](./deployment/configuration) for details.

### Basic Environment Variables

```bash
# Set log level
export AK_LOG_LEVEL=INFO

# Set session storage
export AK_SESSION_STORAGE=redis
export AK_REDIS_URL=redis://localhost:6379
```

## Troubleshooting

### Python Version Issues

Agent Kernel requires Python 3.12+. Check your Python version:

```bash
python --version
```

If you have multiple Python versions, use `python3.12` explicitly:

```bash
python3.12 -m pip install agentkernel
```

### Dependency Conflicts

If you encounter dependency conflicts, try creating a fresh virtual environment:

```bash
python -m venv fresh-env
source fresh-env/bin/activate  # or fresh-env\Scripts\activate on Windows
pip install --upgrade pip
pip install agentkernel[your-extras]
```

### Import Errors

If you get import errors after installation, ensure you've installed the appropriate extras:

```bash
# If using OpenAI Agents
pip install agentkernel[openai]

# If using CrewAI
pip install agentkernel[crewai]
```

## Next Steps

Now that you have Agent Kernel installed, proceed to the [Quick Start Guide](./quick-start) to build your first agent!

## Version Information

- **Current Version**: 0.1.2b17 (Beta)
- **Python Requirements**: 3.12+
- **License**: MIT

## Support

If you encounter installation issues:

1. Check the [GitHub Issues](https://github.com/yaalalabs/agent-kernel/issues)
2. Search for existing solutions
3. Open a new issue with your error details

---

**Ready to build?** Continue to the [Quick Start Guide](./quick-start) →
