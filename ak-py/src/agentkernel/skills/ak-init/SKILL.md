---
name: ak-init
description: >
  Scaffold a new Agent Kernel project from scratch. This skill guides you through
  choosing an agent framework, defining tools, selecting a deployment target, and
  generating a complete project with all necessary files. Designed for users who
  want to build a new AI agent using the Agent Kernel library.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: user
---

# Scaffold an Agent Kernel Project

Use this skill to create a new AI agent project powered by Agent Kernel.

## Instructions for the Agent

When the user wants to create a new agent project, follow this interactive workflow:

### Step 1: Gather Requirements

Ask the user the following questions (adapt based on context):

1. **Agent framework**: Which agent framework would you like to use?
   - **OpenAI Agents SDK** (recommended for most use cases — best tool support, handoffs between agents)
   - **CrewAI** (multi-agent collaboration with roles and tasks)
   - **LangGraph** (complex workflow graphs with state management)
   - **Google ADK** (Google's Agent Development Kit)
   - **Smolagents** (lightweight agent framework with managed-agent routing)

2. **Agent purpose**: What should your agent(s) do? (e.g., "customer support bot", "code review assistant", "data analysis agent")

3. **Tools**: Does your agent need any custom tools? (e.g., "fetch weather data", "query a database", "search the web")

4. **Multi-agent**: Do you need multiple specialized agents with a triage/routing agent?

5. **Deployment mode**: How will you run the agent?
   - **CLI** (interactive terminal — great for development and testing)
   - **REST API** (FastAPI server — for web apps, webhooks, integrations)
   - **AWS Lambda** (serverless on AWS)
   - **AWS ECS/Fargate** (containerized on AWS)
   - **Azure Functions** (serverless on Azure)
   - **Azure Container Apps** (containerized on Azure)
   - **GCP Cloud Run Serverless** (scale-to-zero on GCP)
   - **GCP Cloud Run Containerized** (always-on on GCP)
   - **Docker** (generic container, runs anywhere)

6. **Session persistence**: How should conversation state be stored?
   - **In-memory** (default, no persistence — fine for CLI and development)
   - **Redis** (recommended for production — works with all deployment targets)
   - **DynamoDB** (AWS-native, recommended for AWS serverless)
   - **Cosmos DB** (Azure-native, recommended for Azure serverless)
   - **Firestore** (GCP-native, recommended for GCP Cloud Run)

### Step 2: Generate the Project

Based on the answers, generate the following project structure:

```
<project-name>/
├── pyproject.toml         # Dependencies and project metadata
├── build.sh               # Build script
├── config.yaml            # Agent Kernel configuration
├── <main-file>.py         # Agent definition (demo.py, app.py, or lambda.py)
├── tool.py                # Custom tool functions (if needed)
├── <main-file>_test.py    # Test file
├── README.md              # Project documentation
└── deploy/                # Deployment files (if cloud deployment selected)
    ├── main.tf
    ├── variables.tf
    ├── outputs.tf
    ├── terraform.tfvars
    ├── deploy.sh
    ├── Dockerfile          # For containerized deployments
    └── backend.tf
```

### Step 3: Generate File Contents

#### pyproject.toml

```toml
[project]
name = "<project-name>"
version = "0.1.0"
description = "<description>"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "agentkernel[<extras>]>=0.5.1",
]

[dependency-groups]
dev = [
    "agentkernel[test]>=0.5.1",
    "black>=23.0.0",
    "isort>=5.0.0",
    "mypy>=1.0.0",
]

[tool.uv]
package = false

[tool.isort]
profile = "black"
line_length = 120

[tool.black]
line-length = 120
target-version = ["py312"]
```

**Extras selection**:
- CLI mode: `agentkernel[cli,<framework>]`
- API mode: `agentkernel[<framework>,api]`
- Smolagents framework extra: `smolagents`
- With messaging: add `slack`, `whatsapp`, etc.
- With session store: add `redis`, `aws` (for DynamoDB), `azure` (for Cosmos DB)
- With tracing: add `langfuse` or `openllmetry`

#### Agent definition file

**For OpenAI framework (CLI mode)**:

```python
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent

# Import custom tools if needed
# from tool import my_tool

# Define specialized agents
<agent_name> = Agent(
    name="<name>",
    instructions="<instructions for this agent>",
    # tools=OpenAIToolBuilder.bind([my_tool]),  # if tools needed
)

# Define triage agent (if multi-agent)
triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    handoffs=[<agent_name>],
)

# Register with Agent Kernel
OpenAIModule([triage_agent, <agent_name>])

if __name__ == "__main__":
    CLI.main()
```

**For OpenAI framework (API mode)**:

```python
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

<agent_name> = Agent(
    name="<name>",
    instructions="<instructions>",
)

OpenAIModule([<agent_name>])

if __name__ == "__main__":
    RESTAPI.run()
```

**For OpenAI framework (AWS Lambda)**:

```python
from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule
from agents import Agent

<agent_name> = Agent(
    name="<name>",
    instructions="<instructions>",
)

OpenAIModule([<agent_name>])

handler = Lambda.handler
```

**For LangGraph framework**:

```python
from agentkernel.cli import CLI  # or RESTAPI, Lambda
from agentkernel.langgraph import LangGraphModule
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)

<agent_name> = create_react_agent(
    name="<name>",
    tools=[],
    model=model,
    prompt="<instructions>",
)

LangGraphModule([<agent_name>])

if __name__ == "__main__":
    CLI.main()
```

**For CrewAI framework**:

```python
from agentkernel.cli import CLI  # or RESTAPI, Lambda
from agentkernel.crewai import CrewAIModule
from crewai import Agent, Crew, Task

<agent_name> = Agent(
    role="<role>",
    goal="<goal>",
    backstory="<backstory>",
)

# CrewAI requires a Crew wrapping agents
crew = Crew(
    agents=[<agent_name>],
    tasks=[Task(description="<task>", agent=<agent_name>)],
)

CrewAIModule([crew])

if __name__ == "__main__":
    CLI.main()
```

**For Google ADK framework**:

```python
from agentkernel.cli import CLI  # or RESTAPI, Lambda
from agentkernel.adk import GoogleADKModule
from google.adk.agents import Agent

<agent_name> = Agent(
    name="<name>",
    model="gemini-2.0-flash",
    instruction="<instructions>",
)

GoogleADKModule([<agent_name>])

if __name__ == "__main__":
    CLI.main()
```

**For Smolagents framework**:

```python
from agentkernel.cli import CLI  # or RESTAPI, Lambda
from agentkernel.smolagents import SmolagentsModule, SmolagentsToolBuilder
from smolagents import LiteLLMModel, ToolCallingAgent

model = LiteLLMModel(model_id="openai/gpt-4o")

<agent_name> = ToolCallingAgent(
    tools=SmolagentsToolBuilder.bind([]),
    model=model,
    name="<name>",
    description="<instructions>",
)

SmolagentsModule([<agent_name>])

if __name__ == "__main__":
    CLI.main()
```

#### Custom tools (tool.py)

```python
from agentkernel.core import ToolContext


def <tool_name>(<params>) -> str:
    """<Tool description — this becomes the tool's description for the LLM>"""
    # Access session context if needed:
    # context = ToolContext.get()
    # session = context.session

    # Tool implementation
    return "<result>"
```

For OpenAI framework, bind tools using: `tools=OpenAIToolBuilder.bind([<tool_name>])`
For other frameworks, use their native tool binding mechanism.

#### config.yaml

```yaml
# Session configuration (if not in-memory)
session:
  type: redis          # redis | dynamodb | cosmosdb
  cache: 256           # LRU cache size (optional)
  redis:
    prefix: "ak:<project>:"
    url: "redis://localhost:6379"

# Tracing (optional)
# trace:
#   enabled: true
#   type: langfuse     # langfuse | openllmetry

# Testing
test:
  mode: fuzzy          # fuzzy | judge | fallback
```

#### build.sh

```bash
#!/bin/bash
uv venv && uv sync
```

#### Test file

```python
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("<main-file>.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()

@pytest.mark.order(1)
async def test_basic_response(test_client):
    await test_client.send("<sample question>")
    await test_client.expect(["<expected answer pattern>"])
```

### Step 4: Provide Setup Instructions

After generating the project, tell the user:

1. Set the required API key as environment variable:
   - OpenAI: `export OPENAI_API_KEY=sk-...`
   - Google: `export GOOGLE_API_KEY=...`
2. Run `chmod +x build.sh && ./build.sh` to set up the environment
3. Activate: `source .venv/bin/activate`
4. Run: `python <main-file>.py`
5. For tests: `uv run pytest`

---

### What to Do Next

Your project is scaffolded and running. Here's the natural progression:

- **Add tools & agents** → Use the `ak-build` skill to add new tools, specialist agents, and handoffs to your project. This is the skill you'll use most often as you iterate.
- **Add guardrails or tracing** → Use the `ak-add-capabilities` skill to add input/output guardrails, observability tracing, session persistence, MCP, A2A, hooks, or multimodal support.
- **Connect a messaging platform** → Use the `ak-add-integration` skill to add Slack, WhatsApp, Telegram, or other messaging channels.
- **Deploy to cloud** → Use the `ak-cloud-deploy` skill to deploy to AWS or Azure with Terraform.
- **Set up testing** → Use the `ak-test` skill to configure test modes and write agent tests.
