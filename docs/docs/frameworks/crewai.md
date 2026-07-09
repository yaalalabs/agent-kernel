---
sidebar_position: 3
---

# CrewAI

Integrate CrewAI's role-based agent framework with Agent Kernel.

## Installation

```bash
pip install agentkernel[crewai]
```

## Basic Usage

```python
from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

agent = CrewAgent(
    role="assistant",
    goal="Help users with their questions",
    backstory="You are a helpful AI assistant",
    verbose=False,
)

CrewAIModule([agent])

if __name__ == "__main__":
    CLI.main()
```

## Multi-Agent Crew

```python
from crewai import Agent as CrewAgent, Task, Crew
from agentkernel.crewai import CrewAIModule

researcher = CrewAgent(
    role="researcher",
    goal="Research topics thoroughly",
    backstory="You are an expert researcher",
    verbose=False,
)

writer = CrewAgent(
    role="writer",
    goal="Write clear content",
    backstory="You are a skilled writer",
    verbose=False,
)

CrewAIModule([researcher, writer])
```

## Configuration

```bash
export OPENAI_API_KEY=sk-...  # CrewAI uses OpenAI by default
```

## Tool Binding

Use `CrewAIToolBuilder` to bind plain Python functions as tools to your CrewAI agents:

```python
from crewai import Agent as CrewAgent
from agentkernel.crewai import CrewAIModule, CrewAIToolBuilder

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25°C"

agent = CrewAgent(
    role="weather",
    goal="You provide weather information",
    backstory="Use the get_weather tool for weather-related questions.",
    tools=CrewAIToolBuilder.bind([get_weather]),
)

CrewAIModule([agent])
```

See [Tools](../core-concepts/tools) for the full guide on writing and binding tools.

## Structured Output

CrewAI configures structured output on the `Task` (`output_pydantic` / `output_json`). Since Agent Kernel's runner builds the task per run, set the model class on the wrapped agent after loading the module — the runner forwards it into the task it creates:

```python
from crewai import Agent as CrewAgent
from pydantic import BaseModel
from agentkernel.core.model import AgentReplyAny
from agentkernel.crewai import CrewAIModule

class ResearchReport(BaseModel):
    topic: str
    score: int

agent = CrewAgent(
    role="Researcher",
    goal="Research topics and score their relevance",
    backstory="You are a meticulous researcher",
    verbose=False,
)

module = CrewAIModule([agent])
module.get_agent("Researcher").output_pydantic = ResearchReport
# or: module.get_agent("Researcher").output_json = ResearchReport

# When running the agent:
reply = await service.run_multi(requests)
if isinstance(reply, AgentReplyAny):
    report = reply.content         # {"topic": ..., "score": ...}
```

With `output_pydantic`, the `CrewOutput.pydantic` result is converted via `model_dump()`; with `output_json`, `CrewOutput.json_dict` is used directly. Plain-text crews continue to return `AgentReplyText` from `CrewOutput.raw`. `str(reply)` on an `AgentReplyAny` returns the JSON-serialized content, so text-based consumers work unchanged. Post-execution hooks receive the `AgentReplyAny` object with the dict content — see [Execution Hooks](../integrations/hooks#structured-replies-in-hooks).

:::info Streaming limitation
Structured output applies to non-streaming execution only. (CrewAI does not support streaming in Agent Kernel.)
:::

## Features

- ✅ Role-based agents
- ✅ Task delegation
- ✅ Sequential execution
- ✅ Hierarchical teams
- ✅ Framework-agnostic tool binding
- ✅ Structured output (`output_pydantic` / `output_json` → `AgentReplyAny`)

## Example

See [examples/cli/crewai](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/crewai) for complete examples.
