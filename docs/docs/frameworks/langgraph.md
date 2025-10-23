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

## Features

- ✅ Graph-based workflows
- ✅ Conditional routing
- ✅ State management
- ✅ Checkpointing
- ✅ Human-in-the-loop

## Example

See [examples/cli/langgraph](https://github.com/yaalalabs/agent-kernel/tree/main/examples/cli/langgraph) for complete examples.
