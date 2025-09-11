# Agent Kernel Configuration Guide

This document describes how to configure Agent Kernel (ak) using environment variables and/or a config file

## Overview
- Values are loaded from (highest precedence first):
  1) Environment variables (including variables loaded from a .env file)
  2) A YAML or JSON config file (defaults to config.yaml in the current working directory)
  3) Built-in defaults in the model
- Environment variable prefix: `AK_`
- Nested fields delimiter for env vars (Examples shown below): _ (underscore) 
- Extra/unknown fields are ignored.

## Choosing a config file
- By default, AK looks for `./config.yaml`
- Override the file path by setting the environment variable `AK_CONFIG_PATH_OVERRIDE` to a filename or path (relative to the current working directory), e.g.:
  - `AK_CONFIG_PATH_OVERRIDE=config.json`
  - `AK_CONFIG_PATH_OVERRIDE=conf/agent-kernel.yaml`
- Supported formats: YAML (`.yaml`, `.yml`) and JSON (`.json`)

## Top-level settings
- debug: bool (default: false)
  - Enables debug mode across the library.

## Session store settings
- type: str (default: in_memory) — one of: in_memory, redis
- redis: object (only used when type=redis)
  - url: str (default: redis://localhost:6379)
    - Use rediss:// for SSL.
  - ttl: int (default: 604800) — TTL in seconds (7 days)
  - prefix: str (default: ak:sessions:) — Key prefix for session storage

## Environment variables
Use the AK_ prefix and underscores to set nested fields. Examples:
- `AK_DEBUG=true`
- `AK_SESSION_TYPE=redis`
- `AK_SESSION_REDIS_URL=redis://localhost:6379`
- `AK_SESSION_REDIS_TTL=604800`
- `AK_SESSION_REDIS_PREFIX=ak:sessions:`

### Example `.env` file
Place a `.env` file in your working directory to be auto-loaded:

```
AK_DEBUG=false
AK_SESSION_TYPE=redis
AK_SESSION_REDIS_URL=rediss://my-redis:6379
AK_SESSION_REDIS_TTL=1209600
AK_SESSION_REDIS_PREFIX=ak:prod:sessions:
```

### Example `config.yaml`
You can also supply values via YAML. Environment variables still override these.
```
debug: false
session:
  type: redis
  redis:
    url: redis://localhost:6379
    ttl: 604800
    prefix: ak:sessions:
```

### Example `config.json`
```
{
  "debug": false,
  "session": {
    "type": "redis",
    "redis": {
      "url": "redis://localhost:6379",
      "ttl": 604800,
      "prefix": "ak:sessions:"
    }
  }
}
```


## Notes and tips
- Empty environment variables are ignored.
- Unknown fields in files or env vars are ignored.
- If a non-YAML/JSON file is provided via `AK_CONFIG_PATH_OVERRIDE`, a ValueError is raised.
- For Redis sessions, ensure your redis URL is reachable by your runtime/container.
