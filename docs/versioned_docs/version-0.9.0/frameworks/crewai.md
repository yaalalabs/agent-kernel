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

CrewAI configures structured output on the `Task` (`output_pydantic` / `output_json`), not on the agent, and Agent Kernel builds the task internally per run. Pass the model class to the module constructor, keyed by agent role; the runner forwards it into the task it creates:

```python
from crewai import Agent as CrewAgent
from pydantic import BaseModel
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

CrewAIModule([agent], output_pydantic={"Researcher": ResearchReport})
# or: CrewAIModule([agent], output_json={"Researcher": ResearchReport})
```

To change the schema after the module is loaded, set it on the wrapped agent instead: `module.get_agent("Researcher").output_pydantic = ResearchReport`.

With `output_pydantic`, the `CrewOutput.pydantic` result is converted via `model_dump()`; with `output_json`, `CrewOutput.json_dict` is used directly. Plain-text crews continue to return `AgentReplyText` from `CrewOutput.raw`. `str(reply)` on an `AgentReplyAny` returns the JSON-serialized content, so text-based consumers work unchanged. See [Reply Types](../core-concepts/runner#structured-replies) for how structured replies are surfaced, and [Execution Hooks](../integrations/hooks#structured-replies-in-hooks) for how hooks receive them.

:::info Streaming limitation
Structured output applies to non-streaming execution only. Agent Kernel's CrewAI adapter does not
implement `Runner.stream()` yet (CrewAI itself supports streaming).
:::

## Per-run context/state

CrewAI **does not support** per-run caller context/state. Its `kickoff(inputs=...)` are `.format()` template-interpolation variables, not a state object, so there is no safe slot for a caller dict. If the reserved [`framework_context`](../core-concepts/session.md#framework-context--per-run-state) session key is set to a non-empty value, the CrewAI runner logs a single warning and **ignores it** (no injection, no write-back); the stored key is left untouched. A tool that still needs the dict can reach it directly via `ToolContext.get().session`.

## Features

- ✅ Role-based agents
- ✅ Task delegation
- ✅ Sequential execution
- ✅ Hierarchical teams
- ✅ Framework-agnostic tool binding
- ✅ Structured output (`output_pydantic` / `output_json` → `AgentReplyAny`)

## Example

See [examples/cli/crewai](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/crewai) for complete examples.
