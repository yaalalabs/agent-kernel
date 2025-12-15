---
sidebar_position: 7
---

# Configuration

Configure Agent Kernel via environment variables or configuration files. This sub module class 'AKConfig' is exported as 'Config'. Its unlikely that you will directly use this class in your code (i.e. need for Advanced usage).

## Configuration File

Agent Kernel supports YAML and JSON configuration files. By default, it looks for `config.yaml` in the current working directory.

### Basic Configuration File

Create `config.yaml`:

```yaml
# Core settings
debug: true
library_version: "0.1.0"

# Session management
session:
  type: redis  # or 'in_memory' or 'dynamodb'
  redis:
    url: redis://localhost:6379
    ttl: 604800  # 7 days in seconds
    prefix: "ak:sessions:"
  dynamodb:
    table_name: agent-kernel-sessions
    ttl: 604800  # 7 days in seconds

# API server
api:
  host: 0.0.0.0
  port: 8000
  custom_router_prefix: /custom
  enabled_routes:
    agents: true

# Agent-to-Agent communication
a2a:
  enabled: true
  url: http://localhost:8000/a2a
  agents:
    - "*"  # Enable for all agents
  task_store_type: redis

# Model Context Protocol
mcp:
  enabled: true
  expose_agents: true
  url: http://localhost:8000/mcp
  agents:
    - "*"  # Expose all agents as MCP tools
```

### JSON Configuration

Alternatively, use `config.json`:

```json
{
  "debug": true,
  "session": {
    "type": "redis",
    "redis": {
      "url": "redis://localhost:6379",
      "ttl": 604800,
      "prefix": "ak:sessions:"
    },
    "dynamodb": {
      "table_name": "agent-kernel-sessions",
      "ttl": 604800
    }
  },
  "api": {
    "host": "0.0.0.0",
    "port": 8000,
    "custom_router_prefix": "/custom",
    "enabled_routes": {
      "agents": true
    }
  },
  "a2a": {
    "enabled": true,
    "url": "http://localhost:8000/a2a",
    "agents": ["*"],
    "task_store_type": "redis"
  },
  "mcp": {
    "enabled": true,
    "expose_agents": true,
    "url": "http://localhost:8000/mcp",
    "agents": ["*"]
  }
}
```

### Custom Configuration File Path

Override the default configuration file path:

```bash
export AK_CONFIG_PATH_OVERRIDE=custom-config.yaml
# or
export AK_CONFIG_PATH_OVERRIDE=conf/agent-kernel.json
```

## Environment Variables

All configuration parameters can be set using environment variables with the `AK_` prefix. Use double underscores ('__') to separate nested configuration levels.
A name can have single underscores ('_') in its body.

### Core Configuration

```bash
# Enable debug mode
export AK_DEBUG=true  # default: false

# Library version (auto-detected from package metadata)
export AK_LIBRARY_VERSION=0.1.0
```

### Session Storage

```bash
# Session storage type
export AK_SESSION__TYPE=redis  # Options: 'in_memory', 'redis', 'dynamodb' (default: 'in_memory')

# Redis configuration
export AK_SESSION__REDIS__URL=redis://localhost:6379  # default: redis://localhost:6379
export AK_SESSION__REDIS__TTL=604800  # TTL in seconds (default: 604800 = 7 days)
export AK_SESSION__REDIS__PREFIX=ak:sessions:  # Key prefix (default: ak:sessions:)

# DynamoDB configuration
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-kernel-sessions  # DynamoDB table name (required)
export AK_SESSION__DYNAMODB__TTL=604800  # TTL in seconds (default: 604800 = 7 days, 0 to disable)
```

### API Server

```bash
# API server configuration
export AK_API__HOST=0.0.0.0  # default: 0.0.0.0
export AK_API__PORT=8000  # default: 8000

# API route configuration
export AK_API__ENABLED_ROUTES__AGENTS=true  # Enable agent routes (default: true)
```

### Agent-to-Agent (A2A) Server

```bash
# Enable A2A functionality
export AK_A2A__ENABLED=true  # default: false
export AK_A2A__URL=http://localhost:8000/a2a  # default: http://localhost:8000/a2a
export AK_A2A__AGENTS="agent1,agent2"  # Comma-separated list (default: ["*"])
export AK_A2A__TASK_STORE_TYPE=redis  # Options: 'in_memory', 'redis' (default: 'in_memory')
```

### Model Context Protocol (MCP) Server

```bash
# Enable MCP functionality
export AK_MCP__ENABLED=true  # default: false
export AK_MCP__EXPOSE_AGENTS=true  # Expose agents as MCP tools (default: false)
export AK_MCP__URL=http://localhost:8000/mcp  # default: http://localhost:8000/mcp
export AK_MCP__AGENTS="agent1,agent2"  # Comma-separated list (default: ["*"])
```

### Trace / Observability

```bash
# Enable tracing functionality
export AK_TRACE__ENABLED=true  # default: false
export AK_TRACE__TYPE=langfuse  # Options: 'langfuse', 'openllmetry' (default: 'langfuse')

# Langfuse-specific configuration (required when using Langfuse)
export LANGFUSE_PUBLIC_KEY=pk-lf-...  # Your Langfuse public key
export LANGFUSE_SECRET_KEY=sk-lf-...  # Your Langfuse secret key
export LANGFUSE_HOST=https://cloud.langfuse.com  # Langfuse host (or self-hosted instance)

# OpenLLMetry (Traceloop) configuration (required when using OpenLLMetry)
export TRACELOOP_API_KEY=your-api-key  # Your Traceloop API key
export TRACELOOP_BASE_URL=https://api.traceloop.com  # Optional: Traceloop base URL (for self-hosted)
```



## Configuration Schema

### Complete Configuration Reference

```yaml
# Core configuration
debug: false                    # Enable debug mode
library_version: "0.1.0"       # Library version (auto-detected)

# Session storage configuration
session:
  type: "in_memory"             # Storage type: 'in_memory', 'redis', or 'dynamodb'
  redis:                        # Redis-specific settings
    url: "redis://localhost:6379"  # Redis connection URL (supports rediss:// for SSL)
    ttl: 604800                 # Session TTL in seconds (7 days)
    prefix: "ak:sessions:"      # Redis key prefix
  dynamodb:                     # DynamoDB-specific settings
    table_name: "agent-kernel-sessions"  # DynamoDB table name (required)
    ttl: 604800                 # Item TTL in seconds (7 days, 0 to disable)

# API server configuration
api:
  host: "0.0.0.0"              # API server host
  port: 8000                    # API server port
  custom_router_prefix: "/custom" # API path prefix for custom routes
  enabled_routes:               # Route configuration
    agents: true                # Enable agent interaction routes

# Agent-to-Agent communication
a2a:
  enabled: false                # Enable A2A functionality
  url: "http://localhost:8000/a2a"  # A2A endpoint URL
  agents:                       # List of agents to enable for A2A
    - "*"                       # "*" enables all agents
  task_store_type: "in_memory"  # Task storage: 'in_memory' or 'redis'

# Model Context Protocol
mcp:
  enabled: false                # Enable MCP functionality
  expose_agents: false          # Expose agents as MCP tools
  url: "http://localhost:8000/mcp"  # MCP endpoint URL
  agents:                       # List of agents to expose as MCP tools
    - "*"                       # "*" exposes all agents

# Trace / Observability
trace:
  enabled: false                # Enable tracing
  type: "langfuse"              # Trace provider: 'langfuse' or 'openllmetry'
```

## Configuration Precedence

Configuration values are resolved in the following order (highest to lowest priority):

1. **Environment variables** (with `AK_` prefix)
2. **Configuration file** (YAML/JSON)
3. **Default values** (defined in the schema)

## Loading Configuration

```python
from agentkernel.core import Config

# Get the current configuration instance
config = Config.get() # or config = Config()

# Access configuration values
print(f"Debug mode: {config.debug}")
print(f"API port: {config.api.port}")
print(f"Session storage: {config.session.type}")
print(f"Redis URL: {config.session.redis.url}")
```
### Dynamically reloading config
You can reload the configs from scratch by calling __init__(). However, this might not change the behaviour of the core modules, if its not refering to the AKConfig instance again.

```python
from agentkernel import Config
import os

os.environ["AK_DEBUG"] = "True"  # default is False. Setting to True
config.__init__()
print(f"Debug mode: {config.debug}") # will show True
```

## Your Application configs
You can include your application configs to the same config.yaml file. Derive a class from AKConfig and setup your modules.
Please note that these should be instantiated by you.

```python
from agentkernel import Config
from pydantic import Field

class ApplicationConfig(Config):
  monogdb_url: str = Field(default="mongo://localhost:27017", description="MongoDB URL")

# Get the current configuration instance
config = ApplicationConfig()

# Access configuration values
print(config.model_dump())
```


## Environment Configuration Examples

### Development Setup

```bash
# Enable debug mode with in-memory storage
export AK_DEBUG=true
export AK_SESSION__TYPE=in_memory
export AK_API__PORT=8000
```

### Production Setup

```bash
# Production configuration with Redis
export AK_DEBUG=false
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://prod-redis:6379
export AK_SESSION__REDIS__TTL=86400  # 1 day
export AK_API__HOST=0.0.0.0
export AK_API__PORT=8000
```

### Production Setup with DynamoDB (AWS Serverless)

```bash
# Production configuration with DynamoDB
export AK_DEBUG=false
export AK_SESSION__TYPE=dynamodb
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-kernel-sessions-prod
export AK_SESSION__DYNAMODB__TTL=86400  # 1 day
export AK_API__HOST=0.0.0.0
export AK_API__PORT=8000
```

### A2A Enabled Setup

```bash
# Enable Agent-to-Agent communication with Redis
export AK_A2A__ENABLED=true
export AK_A2A__TASK_STORE_TYPE=redis
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://localhost:6379
```

### A2A Enabled Setup with DynamoDB (AWS)

```bash
# Enable Agent-to-Agent communication with DynamoDB
export AK_A2A__ENABLED=true
export AK_A2A__TASK_STORE_TYPE=redis  # A2A tasks still use Redis or in-memory
export AK_SESSION__TYPE=dynamodb
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-kernel-sessions
```

### MCP Enabled Setup

```bash
# Enable Model Context Protocol
export AK_MCP__ENABLED=true
export AK_MCP__EXPOSE_AGENTS=true
export AK_MCP__AGENTS="my-agent,another-agent"  # Specific agents
```

### Observability / Tracing Setup

**Langfuse:**

```bash
# Enable Langfuse tracing
export AK_TRACE__ENABLED=true
export AK_TRACE__TYPE=langfuse

# Langfuse credentials
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://cloud.langfuse.com
```

Install the langfuse extra:

```bash
pip install agentkernel[langfuse]
```

**OpenLLMetry (Traceloop):**

```bash
# Enable OpenLLMetry tracing
export AK_TRACE__ENABLED=true
export AK_TRACE__TYPE=openllmetry

# Traceloop credentials
export TRACELOOP_API_KEY=your-api-key
# Optional: for self-hosted
export TRACELOOP_BASE_URL=https://api.traceloop.com
```

Install the openllmetry extra:

```bash
pip install agentkernel[openllmetry]
```

## Validation and Error Handling

Agent Kernel validates all configuration values at startup:

- **Invalid session storage types** will raise validation errors
- **Invalid port numbers** will be rejected
- **Malformed Redis URLs** will cause connection failures
- **Invalid boolean values** will be rejected

Example validation errors:

```bash
# These will cause validation errors:
export AK_SESSION__TYPE=invalid_storage  # Must be 'in_memory', 'redis', or 'dynamodb'
export AK_A2A__TASK_STORE_TYPE=invalid   # Must be 'in_memory' or 'redis'
export AK_TRACE__TYPE=invalid_tracer     # Must be 'langfuse' or 'openllmetry'
```

## Best Practices

1. **Use environment variables for secrets** (Redis passwords, API keys, AWS credentials)
2. **Use configuration files for static settings** (ports, URLs, feature flags)
3. **Set appropriate TTL values** for your use case
4. **Use Redis or DynamoDB for production** session storage
   - Use **DynamoDB** for non-performance-critical deployments
   - Use **Redis** for performance-critical deployments
5. **Enable debug mode only in development**
6. **Use specific agent lists** instead of "*" in production for security
7. **Ensure DynamoDB table has correct schema** (partition key: 'session_id', sort key: 'key')

## Summary

- Configure via environment variables (with `AK_` prefix) or YAML/JSON files
- Environment variables take precedence over file configuration
- Support for nested configuration using underscore delimiter
- Built-in validation ensures configuration integrity
- Flexible session storage options (in-memory, Redis, or DynamoDB)
- Optional A2A and MCP functionality with granular control
- DynamoDB recommended for non-performance-critical deployments
