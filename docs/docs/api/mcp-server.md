---
sidebar_position: 2
---

# MCP Server

Expose agents using the Model Context Protocol (MCP).

## What is MCP?

MCP (Model Context Protocol) is a standardized protocol for AI systems to interact with external tools and data sources.

## Enabling MCP

```bash
export AK_MCP__ENABLED=true
```
or
```yaml
mcp:
  enabled: true
```

> **Endpoint**: The MCP server is always mounted at `/mcp` on the main API server. The full endpoint is `http://{api.host}:{api.port}/mcp`. Use `api.port` (or `AK_API__PORT`) to change the port.

## Starting MCP Server

```python
from agentkernel.api import RESTAPI

if __name__ == "__main__":
    RESTAPI.run()
```

## Agent as MCP Tool

Agents are automatically exposed as MCP tools if you set `mcp.expose_agents` to `true`. You can selectively expose agents as well. 

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
  expose_agents: true
  agents: ['*']
  stateless_http: false  # Set to true for stateless mode (no Mcp-Session-Id)
```

## Integration

Use agents from other AI systems:

```python
result = mcp_client.call_tool(
    "custom_tool",
    {"param": "Hello!"}
)
```

## Structured replies

A tool returns the agent's reply as text, unless that reply carries a format label — set by the
[A2UI capability](../advanced/a2ui.md) or by an application post-hook. A labelled reply arrives as
`structuredContent`, with the format in MCP's own `_meta` slot:

```json
{
  "structuredContent": {"version": "v1.0", "createSurface": {"surfaceId": "s1"}},
  "_meta": {"media_type": "application/a2ui+json"}
}
```

fastmcp emits a text block alongside it, so a client reading only text blocks keeps working. Every
unlabelled reply — text, image, or structured-but-unlabelled — returns exactly the string it always
did.

Note that `_meta` is optional in MCP: a host is free to drop it, in which case the client receives
the payload without knowing its format.
