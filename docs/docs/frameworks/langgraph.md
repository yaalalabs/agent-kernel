---
sidebar_position: 4
---

# LangGraph

Integrate LangGraph's graph-based orchestration with Agent Kernel.

## Installation

```bash
pip install agentkernel[langgraph]
```

## Basic Usage

```python
from typing import TypedDict
from langgraph.graph import StateGraph, END
from agentkernel.cli import CLI
from agentkernel.langgraph import LangGraphModule

class State(TypedDict):
    messages: list

def agent_node(state: State):
    # Your logic
    return {"messages": state["messages"] + ["response"]}

# Build graph
workflow = StateGraph(State)
workflow.add_node("agent", agent_node)
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)

# Compile
graph = workflow.compile()
graph.name = "assistant"

LangGraphModule([graph])

if __name__ == "__main__":
    CLI.main()
```

## Complex Graph

```python
from langgraph.graph import StateGraph, END

# Multi-node graph with conditional routing
workflow = StateGraph(State)
workflow.add_node("analyzer", analyze_node)
workflow.add_node("responder", respond_node)
workflow.add_node("validator", validate_node)

workflow.set_entry_point("analyzer")
workflow.add_conditional_edges(
    "analyzer",
    router_func,
    {
        "respond": "responder",
        "validate": "validator"
    }
)
workflow.add_edge("responder", END)
workflow.add_edge("validator", "responder")

graph = workflow.compile()
graph.name = "complex_agent"
```

## Configuration

```bash
export OPENAI_API_KEY=sk-...
```

## Tool Binding

Use `LangGraphToolBuilder` to bind plain Python functions as tools to your LangGraph agents:

```python
from langgraph.prebuilt import create_react_agent
from agentkernel.langgraph import LangGraphModule, LangGraphToolBuilder

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25°C"

weather_agent = create_react_agent(
    name="weather",
    tools=LangGraphToolBuilder.bind([get_weather]),
    model=model,
    prompt="Use the get_weather tool for weather-related questions.",
)

LangGraphModule([weather_agent])
```

Both sync and async functions are supported. Async functions are automatically passed as coroutines.

See [Tools](../core-concepts/tools) for the full guide on writing and binding tools.

## Structured Output

Build the agent with LangGraph's `response_format` parameter (e.g., `create_react_agent`). The result then contains a `structured_response` alongside the messages; Agent Kernel detects it and returns an `AgentReplyAny` whose `content` is the result as a dict:

```python
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel
from agentkernel.core.model import AgentReplyAny
from agentkernel.langgraph import LangGraphModule

class WeatherResponse(BaseModel):
    city: str
    conditions: str

graph = create_react_agent(
    model="openai:gpt-4o",
    tools=[get_weather],
    response_format=WeatherResponse,
)
graph.name = "weather"

LangGraphModule([graph])

# When running the agent:
reply = await service.run_multi(requests)
if isinstance(reply, AgentReplyAny):
    weather = reply.content        # {"city": ..., "conditions": ...}
```

Pydantic results are converted via `model_dump()`; graphs without `response_format` continue to return `AgentReplyText` from the last message. `str(reply)` on an `AgentReplyAny` returns the JSON-serialized content, so text-based consumers work unchanged. Post-execution hooks receive the `AgentReplyAny` object with the dict content — see [Execution Hooks](../integrations/hooks#structured-replies-in-hooks).

:::info Streaming limitation
Structured output applies to non-streaming execution only. Streamed runs emit token-by-token text deltas.
:::

## Features

- ✅ Graph-based workflows
- ✅ Conditional routing
- ✅ State management
- ✅ Checkpointing
- ✅ Framework-agnostic tool binding
- ✅ Structured output (`response_format` → `AgentReplyAny`)

## Example

See [examples/cli/langgraph](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/langgraph) for complete examples.
