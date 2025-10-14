# Agent Kernel (Python)

Agent Kernel is a lightweight runtime and adapter layer that lets you build and run AI agents across multiple frameworks with a unified API. This package brings a common set of abstractions (Agent, Runner, Session, Module, Runtime) and integrations for:

- OpenAI Agents SDK
- CrewAI
- LangGraph

It also provides a simple interactive CLI and an AWS Lambda handler to deploy your agents as serverless endpoints.


## Why Agent Kernel?

- Unified model: Write agent logic once, run it under different frameworks via thin adapters.
- Pluggable: Bring your own framework-specific agents and register them using a small shim.
- Session-aware: Built-in session abstraction to maintain conversational or task state across runs.
- Ready to use: CLI for local interaction, AWS Lambda handler for quick cloud deployment.


## Installation

This repository uses the uv toolchain. You can work from source easily.

Prerequisites:
- Python 3.12+
- uv 0.8.0+

From source (editable):

```bash
# Clone the repo and cd into ak-py
uv sync  # install dependencies
```

Or using pip (if you package/publish it):

```bash
pip install ak-py
```


## Quick Start

Below is the minimal mental model:

- Agent: your framework-specific agent (e.g., a CrewAI Agent or a LangGraph CompiledStateGraph) wrapped by an Agent Kernel adapter.
- Runner: framework-specific execution strategy.
- Session: shared state across turns.
- Module: a container that registers agents with the global Runtime on import/instantiation.
- Runtime: a registry and orchestrator for agents.

### Example: Define and register agents

You typically create a Python module that constructs your framework agents and registers them with Agent Kernel by creating an agent module. Importing this module will register agents in the Runtime.

CrewAI example (pseudo/minimal):

```python
# demo.py
from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

researcher = CrewAgent(role="researcher", goal="Find facts")
writer = CrewAgent(role="writer", goal="Summarize findings")

# Register both under Agent Kernel. The module maps each Crew agent to a CrewAIAgent
# and registers them with the global Runtime.
module = CrewAIModule([researcher, writer])
if __name__ == "__main__":
    CLI.main()
```

LangGraph example (pseudo/minimal):

```python
# demo.py
from langgraph.graph import StateGraph
from agentkernel.cli import CLI
from agentkernel.langgraph import LangGraphModule

# Build your graph and compile it to CompiledStateGraph with a `.name`
sg = StateGraph(...)
compiled = sg.compile()
compiled.name = "assistant"  # ensure a name is set

module = LangGraphModule([compiled])
if __name__ == "__main__":
    CLI.main()
```

OpenAI Agents SDK example (pseudo/minimal):

```python
# demo.py
from openai import OpenAI
from agents import Agent as OpenAIAgent  # from openai-agents SDK
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

client = OpenAI()
assistant = OpenAIAgent(name="assistant", client=client)  # add any required params for your SDK version

module = OpenAIModule([assistant])
if __name__ == "__main__":
    CLI.main()
```


## Using the CLI

Agent Kernel ships with a simple interactive CLI that lets you:
- Load an agent module (which registers agents)
- List/select an agent
- Send prompts and view responses

Run one of the above examples from the project:

```bash
uv run demo.py
```

Once inside, available commands:
- !h, !help — Show help
- !ld, !load <module_name> — Import a Python module that instantiates an agent module (e.g., my_crewai_agents)
- !ls, !list — List registered agents
- !s, !select <agent_name> — Select an agent by name
- !n, !new — Start a new session
- !q, !quit — Exit

Tip: If your agent module registers at import time, you can simply run:

```text
(assistant) >> !load my_crewai_agents
```


## AWS Lambda Deployment

A ready-to-use handler is provided at:

- ak.aws:Lambda.handler

OpenAI Agents SDK lambda example (pseudo/minimal):

```python
# demo.py
from openai import OpenAI
from agents import Agent as OpenAIAgent  # from openai-agents SDK
from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule

client = OpenAI()
assistant = OpenAIAgent(name="assistant", client=client)  # add any required params for your SDK version

module = OpenAIModule([assistant])
handler = Lambda.handler
```

It expects an API Gateway-style event with a JSON body like:

```json
{
  "prompt": "Hello agent",
  "agent": "writer"  
}
```

Response shape:
- 200 with { "result": <string> }
- 400 if no agent is available
- 500 on unexpected errors

Notes:
- If no agent name is provided, the handler selects the first registered agent.
- Make sure your deployment package (Lambda layer or container) includes your agent module and dependencies. Importing your agent module should register agents before the first request.

## Development

Requirements:
- Python 3.12+
- uv 0.8.0+

Setup:

```bash
./build.sh  # installs dev dependencies and sets up environment
```

Run tests:

```bash
uv run pytest
```

Formatting and static checks (configured in pyproject.toml):
- black
- isort
- mypy


## Configuration and Extensibility

- Configuration: See [CONFIG.md](CONFIG.md) for full details on environment variables and config file options.
- Sessions: Use ak.ak.Session to keep per-conversation or per-job state across runs. Framework adapters manage their own session storage within that Session via namespaced keys (e.g., "crewai", "langgraph", "openai").
- Adapters: See ak/crewai, ak/langgraph, ak/openai for reference implementations. To add a new framework, implement a Runner and an Agent wrapper, then a Module that registers them with Runtime.
- Runtime: Agents are registered globally; Runtime.load(module_name) imports a module, which should instantiate an agent module to register its agents.