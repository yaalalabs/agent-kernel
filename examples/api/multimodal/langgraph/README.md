# Multimodal Example — LangGraph

Demonstrates multimodal (image/file) support with a LangGraph agent.

## Running

```bash
AK_MULTIMODAL__ENABLED=true uv run python app.py
```

## Tool Injection

LangGraph compiles a **static DAG** via `create_react_agent(tools=[...])` — tools are baked in at compile time. Agent Kernel handles this automatically through `LangGraphToolBuilder.bind()`, which injects system tools (such as `analyze_attachments`) before the graph is compiled.

Simply pass your tools through `bind()` and Agent Kernel takes care of the rest:

```python
from agentkernel.langgraph import LangGraphToolBuilder

general_agent = create_react_agent(
    name="general",
    model=model,
    tools=LangGraphToolBuilder.bind([]),  # system tools injected automatically
    prompt="...",
)
```

This is consistent with how Agent Kernel works across all frameworks (OpenAI, CrewAI, and ADK) — no manual tool imports required.
