---
sidebar_position: 5
---

# Configuration

Configure Agent Kernel via environment variables or configuration files.

## Environment Variables

### Core Configuration

```bash
# Logging
export AK_LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR

# Library version (auto-detected)
export AK_VERSION=0.1.2b17
```

### Session Storage

```bash
# Storage type
export AK_SESSION_STORAGE=redis  # or 'in-memory'

# Redis configuration
export AK_REDIS_URL=redis://localhost:6379
export AK_REDIS_DB=0
export AK_REDIS_PASSWORD=your-password
export AK_SESSION_TTL=3600  # seconds
```

### API Server

```bash
# API mode
export AK_MODE=api
export AK_API_PORT=8000
export AK_API_HOST=0.0.0.0
```

### MCP Server

```bash
# Enable MCP
export AK_MCP_ENABLED=true
export AK_MCP_PORT=8001
```

### A2A Server

```bash
# Enable A2A
export AK_A2A_ENABLED=true
export AK_A2A_URL=https://your-domain.com/a2a
export AK_A2A_PORT=8002
```

### Framework-Specific

```bash
# OpenAI
export OPENAI_API_KEY=sk-...
export OPENAI_MODEL=gpt-4

# Google ADK
export GOOGLE_API_KEY=...
export GEMINI_MODEL=gemini-2.0-flash-exp
```

## Configuration File

Create `ak-config.yaml`:

```yaml
# Core settings
log_level: INFO
version: 0.1.2b17

# Session management
session:
  storage: redis
  redis:
    url: redis://localhost:6379
    db: 0
    password: ${REDIS_PASSWORD}
  ttl: 3600

# API server
api:
  enabled: true
  host: 0.0.0.0
  port: 8000

# MCP server
mcp:
  enabled: true
  port: 8001

# A2A server
a2a:
  enabled: true
  url: https://your-domain.com/a2a
  port: 8002

# Deployment
deployment:
  profile: serverless  # or 'containerized'
  region: us-east-1
  lambda:
    memory: 512
    timeout: 30
  ecs:
    cpu: 512
    memory: 1024
    desired_count: 2
```

Load configuration:

```python
from agentkernel.core import AKConfig

config = AKConfig.from_file("ak-config.yaml")
```

## Configuration Precedence

1. Environment variables (highest priority)
2. Configuration file
3. Default values (lowest priority)

## Best Practices

### Development

```bash
export AK_LOG_LEVEL=DEBUG
export AK_SESSION_STORAGE=in_memory
```

### Production

```bash
export AK_LOG_LEVEL=INFO
export AK_SESSION_STORAGE=redis
export AK_REDIS_URL=redis://elasticache-endpoint:6379
```

### Security

- Never commit API keys to version control
- Use environment variables or secrets manager
- Use IAM roles in AWS instead of keys when possible

```bash
# Use secrets
export OPENAI_API_KEY=$(aws secretsmanager get-secret-value --secret-id openai-key --query SecretString --output text)
```

## Accessing Configuration

```python
from agentkernel.core import AKConfig

config = AKConfig.get()

print(config.log_level)
print(config.session_storage)
print(config.redis_url)
```

## Validation

Agent Kernel validates configuration on startup:

```python
# Invalid configuration will raise error
export AK_SESSION_STORAGE=invalid  # Error!
export AK_LOG_LEVEL=INVALID  # Error!
```

## Summary

- Configure via environment variables or YAML
- Environment variables override file configuration
- Validate configuration before deployment
- Use secrets management for sensitive data
