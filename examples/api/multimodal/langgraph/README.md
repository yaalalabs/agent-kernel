# Multimodal Example — LangGraph

Demonstrates multimodal (image/file) support with a LangGraph agent.

## Running

```bash
AK_MULTIMODAL__ENABLED=true uv run python app.py
```

## LangGraph Limitation

Unlike OpenAI, CrewAI, and ADK — where agents hold a **mutable tools list** that Agent Kernel can append to at startup — LangGraph compiles a **static DAG** via `create_react_agent(tools=[...])`. The tool list is baked in at compile time; there is no official post-compile API to add tools.

As a result, Agent Kernel **cannot automatically inject** the `analyze_attachments` system tool into LangGraph agents the way it does for other frameworks.

**You must pass it explicitly before compile:**

```python
from agentkernel.core.multimodal import analyze_attachments
from agentkernel.langgraph import LangGraphToolBuilder

general_agent = create_react_agent(
    name="general",
    model=model,
    tools=LangGraphToolBuilder.bind([analyze_attachments]),   # <-- required
    prompt="...",
)
```

If you omit this, the agent will receive image descriptions in the conversation but will not be able to call `analyze_attachments` for follow-up questions about attachments.

## Other Frameworks

For OpenAI, CrewAI, and ADK, no changes to `app.py` are needed — Agent Kernel injects `analyze_attachments` automatically when `AK_MULTIMODAL__ENABLED=true`.
