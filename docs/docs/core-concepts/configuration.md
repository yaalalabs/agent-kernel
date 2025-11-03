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
  type: redis  # or 'in_memory'
  redis:
    url: redis://localhost:6379
    ttl: 604800  # 7 days in seconds
    prefix: "ak:sessions:"

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
export AK_SESSION__TYPE=redis  # Options: 'in_memory', 'redis' (default: 'in_memory')

# Redis configuration
export AK_SESSION__REDIS__URL=redis://localhost:6379  # default: redis://localhost:6379
export AK_SESSION__REDIS__TTL=604800  # TTL in seconds (default: 604800 = 7 days)
export AK_SESSION__REDIS__PREFIX=ak:sessions:  # Key prefix (default: ak:sessions:)
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



## Configuration Schema

### Complete Configuration Reference

```yaml
# Core configuration
debug: false                    # Enable debug mode
library_version: "0.1.0"       # Library version (auto-detected)

# Session storage configuration
session:
  type: "in_memory"             # Storage type: 'in_memory' or 'redis'
  redis:                        # Redis-specific settings
    url: "redis://localhost:6379"  # Redis connection URL (supports rediss:// for SSL)
    ttl: 604800                 # Session TTL in seconds (7 days)
    prefix: "ak:sessions:"      # Redis key prefix

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

os.environ["AK_DEBUG"] = "True"  # default is False. Setting to True
config.__init__()
print(f"Debug mode: {config.debug}") # will show True
```

## Your Application configs
You can include your application configs to the same config.yaml file. Derive a class from AKConfig and setup your modules.
Please note that these should be instantiated by you.

```python
from agentkernel import Config

class ApplicationConfig(Config):
  monogdb_url:str Field(default="mongo://localhost:27017", description="MongoDB URL")

# Get the current configuration instance
config = ApplicationConfig()

# Access configuration values
print(config.dump())
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

### A2A Enabled Setup

```bash
# Enable Agent-to-Agent communication
export AK_A2A__ENABLED=true
export AK_A2A__TASK_STORE_TYPE=redis
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://localhost:6379
```

### MCP Enabled Setup

```bash
# Enable Model Context Protocol
export AK_MCP__ENABLED=true
export AK_MCP__EXPOSE_AGENTS=true
export AK_MCP__AGENTS="my-agent,another-agent"  # Specific agents
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
export AK_SESSION__TYPE=invalid_storage  # Must be 'in_memory' or 'redis'
export AK_A2A__TASK_STORE_TYPE=invalid   # Must be 'in_memory' or 'redis'
```

## Best Practices

1. **Use environment variables for secrets** (Redis passwords, API keys)
2. **Use configuration files for static settings** (ports, URLs, feature flags)
3. **Set appropriate TTL values** for your use case
4. **Use Redis for production** session storage and task stores
5. **Enable debug mode only in development**
6. **Use specific agent lists** instead of "*" in production for security

## Summary

- Configure via environment variables (with `AK_` prefix) or YAML/JSON files
- Environment variables take precedence over file configuration
- Support for nested configuration using underscore delimiter
- Built-in validation ensures configuration integrity
- Flexible session storage options (in-memory or Redis)
- Optional A2A and MCP functionality with granular control
