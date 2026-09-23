---
sidebar_position: 7
---

# Secret Resolution

Agent Kernel can **resolve secrets (API keys, passwords, tokens) from a managed store, falling back from
the environment**. Application code asks `SecretManager` for a key by the same name the SDKs already read
from the environment — `OPENAI_API_KEY`, `NEO4J_PASSWORD` — and the configured provider supplies it. The
same code reads the key from an environment variable on a laptop and from AWS SSM Parameter Store in
production, with only `config.yaml` changing.

```python
from agentkernel.secret import SecretManager
from agents import set_default_openai_key

set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))
```

## Overview

| Concern | What it means |
| --- | --- |
| **Enablement** | Always available. The default `env` provider costs nothing; selecting another `secret.provider.type` is the only opt-in, so there is no `enabled` flag. |
| **Keys** | Environment-variable-style names matching `^[A-Z][A-Z0-9_]*$`. A malformed key raises `ValueError`. |
| **Resolution order** | Fixed: process environment → process cache → configured provider. First hit wins. |
| **Provider** | Where values live — `env` (the environment only) or `aws_ssm` (AWS SSM Parameter Store), or a dotted path to your own `SecretProvider`. |
| **Cache** | Provider hits are cached in-process for `cache_ttl` seconds (default `300`, `0` disables). |
| **Environment** | Never written. A resolved value is returned to the caller and held in the cache only — hand it to the SDK explicitly. |

### Resolution Order

1. **Environment** — a set, **non-empty** environment variable named by the key always wins, whatever the
   provider. An empty variable is treated as absent. Environment values are re-read on every call and never
   cached, so local overrides keep working in a deployment configured for a managed store.
2. **Cache** — a value the provider returned within the last `cache_ttl` seconds.
3. **Provider** — the configured backend. A hit is cached; a miss returns `None` to the manager.

## Configuration

```yaml
secret:
  prefix: ""          # deployment scope; required by aws_ssm, ignored by env
  provider:
    type: env         # env | aws_ssm, or a dotted path to a SecretProvider subclass
  cache_ttl: 300      # seconds a provider hit is served from the cache; 0 disables caching
```

| Field | Environment variable | Default | Description |
| --- | --- | --- | --- |
| `secret.prefix` | `AK_SECRET__PREFIX` | `""` | Deployment scope providers namespace secrets under, e.g. `myproduct-dev-agents`. Injected by the AWS Terraform modules when `ssm_enabled = true`. |
| `secret.provider.type` | `AK_SECRET__PROVIDER__TYPE` | `env` | Backend secret values are read from. |
| `secret.cache_ttl` | `AK_SECRET__CACHE_TTL` | `300` | Cache lifetime in seconds (≥ 0). This is the rotation-pickup window for values read per call. |

## API

`SecretManager.current()` returns the process-wide manager, built from the `secret` block on first access.

| Call | Behaviour |
| --- | --- |
| `get(key)` | Resolve `key`; raises `SecretNotFoundError` when no layer has it. |
| `get(key, default=None)` | Resolve `key`; returns `default` on a miss. A provider **failure** still raises `SecretError` — a default never masks it. |
| `invalidate(key)` | Drop the cached value for `key` so the next `get` re-resolves it. |
| `clear()` | Drop every cached value. |

Errors live in `agentkernel.secret.errors` and are re-exported from `agentkernel.secret`:

- **`SecretError`** — the backend failed (credentials, network, throttling, authorization). Never carries
  the value.
- **`SecretNotFoundError`** (subclass of `SecretError`) — no layer had the key and no `default` was
  supplied. Its `key` attribute names the missing key.

A required key resolved at module import time fails the process at startup rather than on the first model
call. An optional one can degrade gracefully:

```python
def get_weather(city: str) -> str:
    api_key = SecretManager.current().get("WEATHER_API_KEY", default=None)
    if api_key is None:
        return "The weather service is not configured."
    ...
```

## Providers

### `env` (default)

Reads the environment variable named by the key. Needs no settings and no extra. Because the environment is
always consulted first, the provider layer itself only ever confirms a miss.

### `aws_ssm` — AWS SSM Parameter Store

```yaml
secret:
  prefix: myproduct-dev-agents   # usually injected as AK_SECRET__PREFIX by Terraform
  provider:
    type: aws_ssm
```

- **Install:** `pip install "agentkernel[aws]"` (boto3). Region and credentials come from the standard
  boto3 environment chain.
- **Addressing:** the key is lowercased under the prefix — `OPENAI_API_KEY` →
  `/ak/<prefix>/openai_api_key`.
- **Prefix rules:** required, and must be a single path segment (leading/trailing `/` are stripped). An
  empty or nested prefix is rejected with `AKConfigError` when the manager is built (the first
  `SecretManager.current()` call).
- **Call:** one read-only `GetParameter(WithDecryption=True)`. `ParameterNotFound` is a miss; any other
  failure raises `SecretError`.
- **IAM:** `ssm:GetParameter` on `arn:aws:ssm:<region>:<account>:parameter/ak/<prefix>/*` — nothing else.

Create each parameter yourself as a `SecureString` (AWS-managed `alias/aws/ssm` key):

```bash
aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
    --type SecureString --value "$OPENAI_API_KEY" --overwrite
```

### Custom providers

Set `secret.provider.type` to a dotted path to a `SecretProvider` subclass:

```python
from typing import Optional

from agentkernel.secret import SecretProvider
from agentkernel.secret.errors import SecretError


class VaultSecretProvider(SecretProvider):
    @classmethod
    def from_config(cls, config) -> "VaultSecretProvider":
        return cls(mount=config.prefix)  # receives the whole `secret` block

    def get_secret(self, key: str) -> Optional[str]:
        ...  # return the value, None on a miss, or raise SecretError on a backend failure
```

A provider owns its own addressing, must tolerate concurrent calls, and never caches or falls back — the
manager does both. `agentkernel.secret.testing.SecretProviderContract` is a reusable pytest contract suite for provider
implementations.

## Deploying on AWS

Both the serverless and containerized Terraform modules take an `ssm_enabled` flag (default `false`). When
set, it grants every Lambda or ECS task role `ssm:GetParameter` on `/ak/<prefix>/*` and injects
`AK_SECRET__PREFIX = <prefix>`.

```hcl
ssm_enabled = true
```

**Terraform is only half of it.** The module never injects `secret.provider.type` — the application's
`config.yaml` declares `secret.provider.type: aws_ssm`. Terraform also does not create the parameters, so
the key never passes through Terraform state. Do not also inject the key as an environment variable, or it
wins over SSM.

### Rotation

Overwrite the parameter with `aws ssm put-parameter ... --overwrite`.

- Values read **per call** (e.g. inside a tool) are picked up once the cache entry expires — within
  `cache_ttl` seconds — or immediately after `invalidate(key)`.
- Values handed to an SDK **once at startup** (e.g. `set_default_openai_key`) are picked up on the next cold
  start: force a new ECS deployment (`aws ecs update-service ... --force-new-deployment`), or on Lambda
  update the function's configuration (for example its description) to force fresh execution environments.

## Examples

- [`examples/cli/openai_secret`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai_secret)
  — the `env` provider locally, with a required model key and an optional tool key.
- [`examples/aws-serverless/openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/openai)
  — the OpenAI key read from SSM on Lambda.
- [`examples/aws-containerized/openai-dynamodb-scalable`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/openai-dynamodb-scalable)
  — the OpenAI key read from SSM by the ECS agent runner.
