---
sidebar_position: 2
---

# MCP Server

Expose agents using the Model Context Protocol (MCP).

## What is MCP?

MCP (Model Context Protocol) is a standardized protocol for AI systems to interact with external tools and data sources.

## Enabling MCP

```bash
export AK_MCP_ENABLED=true
export AK_MCP_PORT=8001
```
or
```yaml
mcp
  enabled: true
```

## Starting MCP Server

```python
from agentkernel.api import RESTAPI

if __name__ == "__main__":
    RESTAPI.run()
```

## Agent as MCP Tool

Agents are automatically exposed as MCP tools if you set `mcp.expose_agents` to `true`. You can selectively expose agents as well. 

```

## Custom Tools

Expose custom tools via MCP:

```python
from agentkernel.mcp import MCP
from agentkernel.api import RESTAPI

mcp = MCP.get()

@mcp.tool
def custom_tool(param: str) -> str:
    return f"Processed: {param}"

RESTAPI.run()
```

## Configuration

```yaml
mcp:
  enabled: true
  port: 8000
  expose_agents: true
  agents: ['*']
```

## Integration

Use agents from other AI systems:

```python
result = mcp_client.call_tool(
    "custom_tool",
    {"message": "Hello!"}
)
```
