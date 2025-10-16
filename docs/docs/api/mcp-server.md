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

## Starting MCP Server

```python
from agentkernel.mcp import MCPServer

if __name__ == "__main__":
    server = MCPServer()
    server.run()
```

## Agent as MCP Tool

Agents are automatically exposed as MCP tools:

```json
{
  "tools": [
    {
      "name": "assistant",
      "description": "General assistant agent",
      "parameters": {
        "message": "string",
        "session_id": "string"
      }
    }
  ]
}
```

## Custom Tools

Expose custom tools via MCP:

```python
from agentkernel.mcp import MCPServer, register_tool

@register_tool
def custom_tool(param: str) -> str:
    return f"Processed: {param}"

server = MCPServer()
server.run()
```

## Configuration

```yaml
mcp:
  enabled: true
  port: 8001
  auth:
    enabled: true
    token: ${MCP_TOKEN}
```

## Integration

Use agents from other AI systems:

```python
# From Claude, GPT, etc.
result = mcp_client.call_tool(
    "assistant",
    {"message": "Hello!", "session_id": "user-123"}
)
```

## Best Practices

- Enable authentication in production
- Document tool capabilities
- Handle errors gracefully
- Monitor tool usage
