---
sidebar_position: 7
---

# Secret Resolution

Agent Kernel can **resolve secrets (API keys, passwords, tokens) from the environment, falling back to
a managed store**. Application code asks `SecretManager` for a key by the same name the SDKs already read
from the environment — `OPENAI_API_KEY`, `NEO4J_PASSWORD` — and the configured provider supplies it. The
same code reads the key from an environment variable on a laptop, from AWS SSM Parameter Store on AWS, and from Kubernetes Secrets
mounted into the pod on Kubernetes, with only `config.yaml` changing.

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
| **Provider** | Where values live — `env` (the environment only), `aws_ssm` (AWS SSM Parameter Store) or `kubernetes` (Kubernetes Secrets mounted as files), or a dotted path to your own `SecretProvider`. |
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
  prefix: ""          # deployment scope; required by aws_ssm, ignored by env and kubernetes
  provider:
    type: env         # env | aws_ssm | kubernetes, or a dotted path to a SecretProvider subclass
    kubernetes:
      mount_path: /var/run/secrets/agentkernel   # read only by the kubernetes provider
  cache_ttl: 300      # seconds a provider hit is served from the cache; 0 disables caching
```

| Field | Environment variable | Default | Description |
| --- | --- | --- | --- |
| `secret.prefix` | `AK_SECRET__PREFIX` | `""` | Deployment scope providers namespace secrets under, e.g. `myproduct-dev-agents`. Injected by the AWS Terraform modules when `ssm_enabled = true`. |
| `secret.provider.type` | `AK_SECRET__PROVIDER__TYPE` | `env` | Backend secret values are read from. |
| `secret.provider.kubernetes.mount_path` | `AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH` | `/var/run/secrets/agentkernel` | Absolute directory the Kubernetes Secrets are mounted under, one subdirectory per Secret. Read only by the `kubernetes` provider. |
| `secret.cache_ttl` | `AK_SECRET__CACHE_TTL` | `300` | Cache lifetime in seconds (≥ 0). This is the rotation-pickup window for values read per call. |

## API

`SecretManager.current()` returns the process-wide manager, built from the `secret` block on first access.

| Call | Behaviour |
| --- | --- |
| `get(key)` | Resolve `key`; raises `SecretNotFoundError` when no layer has it. |
| `get(key, default=None)` | Resolve `key`; returns `default` on a miss. A provider **failure** still raises `SecretError` — a default never masks it. |
| `describe(key, field=None)` | Every place `key` can be set, in resolution order, for your own error messages: `field` (an `AKConfig` path) when given, the environment variable, then the provider's location — e.g. `the OPENAI_API_KEY environment variable or SSM parameter /ak/myapp-dev/openai_api_key`. |
| `invalidate(key)` | Drop the cached value for `key` so the next `get` re-resolves it. |
| `clear()` | Drop every cached value. |

Errors live in `agentkernel.secret.errors` and are re-exported from `agentkernel.secret`:

- **`SecretError`** — the backend failed (credentials, network, throttling, authorization). Never carries
  the value.
- **`SecretNotFoundError`** (subclass of `SecretError`) — no layer had the key and no `default` was
  supplied. Its `key` attribute names the missing key, and its message names where to set it:
  `secret 'OPENAI_API_KEY' not found: set the OPENAI_API_KEY environment variable or SSM parameter /ak/myapp-dev/openai_api_key`.

The framework's own consumers word their missing-credential errors the same way, so a deployment on
`aws_ssm` is told the exact parameter to create (`Incomplete WhatsApp configuration: set
whatsapp.access_token, the AK_WHATSAPP__ACCESS_TOKEN environment variable or SSM parameter
/ak/myapp-dev/ak_whatsapp__access_token.`).

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

### `kubernetes` — Kubernetes Secrets mounted into the pod

```yaml
secret:
  provider:
    type: kubernetes
```

Reads one file per key from Kubernetes Secrets that are **mounted into the pod as volumes**. It never calls
the Kubernetes API, so it needs no RBAC, no ServiceAccount and no extra (`pip install` nothing: it uses the
standard library only).

- **Layout:** each Secret is its own volume at `<mount_path>/<secret-name>/`, one file per data key —
  `/var/run/secrets/agentkernel/openai-credentials/OPENAI_API_KEY`. A key file directly under `mount_path`
  is also read.
- **Lookup:** the key `OPENAI_API_KEY` is read from the one file of that name across all mounted Secrets, so
  application code does not say which Secret holds it. The same key in **two** places raises `SecretError`
  naming both paths (never the values). An empty file is a miss. Only one directory level is searched, and
  entries starting with `.` (the kubelet's `..data` bookkeeping) are skipped.
- **Environment first:** a set, non-empty environment variable still wins, so an `OPENAI_API_KEY` injected
  with an `extraEnv` `secretKeyRef` is used and the mount is not read.
- **Symlinks** are followed, since the kubelet builds the mount from them, but a matching file that resolves
  outside `mount_path` (a symlinked directory or file pointing elsewhere) raises `SecretError` instead of being
  read. A permission error on `mount_path` or on a Secret directory is also a `SecretError`, not a miss.
- **Key compatibility:** data keys must be named exactly like the AK key, i.e. match `^[A-Z][A-Z0-9_]*$`. A
  differently named data key (for example `api-key`) is silently unreachable; there is no remapping. Create
  compatible keys with `kubectl create secret generic openai-credentials --from-literal=OPENAI_API_KEY=...`
  or `--from-env-file=.env`, or with an External Secrets Operator `target.template.data` that renames the
  remote keys.
- **Missing mount:** a `mount_path` that does not exist or is not a directory raises `SecretError` on the first
  read, **even with `default=`**. Construction does no I/O, so a pod with the provider configured but nothing
  mounted still starts as long as the environment variable supplies the key.
- **`mount_path`:** the Helm chart mounts under the default, so set it only for Secrets mounted another way —
  for example the Secrets Store CSI driver, or Docker / Compose secrets (`/run/secrets`).

#### Mounting with the Helm chart

The `ak-deployment/ak-k8s` chart's `secretStore` creates the volumes. List Secrets that already exist in the
release namespace:

```yaml
secretStore:
  enabled: true
  secrets:
    - name: openai-credentials
    - name: slack-credentials
```

Each listed Secret becomes a `secret` volume (`ak-secret-<index>`, `optional: false`) mounted read-only and
whole at `/var/run/secrets/agentkernel/<name>`. A listed Secret that does not exist leaves the pod in
`ContainerCreating` with a `FailedMount` event. To add a Secret, create it, add it to `secretStore.secrets`
and roll out; a new key in an already-listed Secret needs no values change.

- **Placement:** only the tier that executes agents gets the mounts — `agent-runner`, or `io-handler` in the
  single-process profile (`agentRunner.enabled: false` and `transport.type: in_memory`). The `ws-gateway` and
  `sandbox-worker` never mount. `secretStore.enabled` with no agent-executing tier, an empty list, a duplicate
  name or an entry without a string name fails `helm template` / `install`.
- **No subPath:** the chart never uses `items`, `subPath` or `defaultMode`. Whole-Secret mounts are what let
  new keys and rotated values reach the pod.
- **Rotation:** the kubelet refreshes mounted Secret files after a short delay. Values read per call are
  picked up once that delay and `cache_ttl` have passed, or immediately after `invalidate(key)`. Values handed
  to an SDK once at startup (`set_default_openai_key`) need `kubectl rollout restart deployment/<runner>`.

**Security:** every key of every listed Secret is readable by any code running in the agent-executing
container, including code run by a `local_subprocess` sandbox. List only the Secrets the agents need, keep
unrelated keys out of them, and use an isolated sandbox provider for untrusted code.

#### Local development

Export the key (the environment wins), or set `AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH` to a local
directory laid out as `<dir>/<secret-name>/<KEY>` or flat `<dir>/<KEY>`. A missing directory is a
`SecretError` even with `default=`, so keep `env` in a local config when neither applies.

### Custom providers

Set `secret.provider.type` to a dotted path to a `SecretProvider` subclass:

```python
from typing import Optional

from agentkernel.secret import SecretProvider
from agentkernel.secret.errors import SecretError


class VaultSecretProvider(SecretProvider):
    @classmethod
    def create(cls, config) -> "VaultSecretProvider":
        return cls(mount=config.prefix)  # receives the whole `secret` block

    def get_secret(self, key: str) -> Optional[str]:
        ...  # return the value, None on a miss, or raise SecretError on a backend failure

    def describe(self, key: str) -> Optional[str]:
        return f"Vault secret {self.mount}/{key.lower()}"  # named in "not found" errors; no I/O
```

A provider owns its own addressing, must tolerate concurrent calls, and never caches or falls back — the
manager does both. `describe` is optional: without it, errors name `the '<KEY>' entry in <ClassName>`. `agentkernel.secret.testing.SecretProviderContract` is a reusable pytest contract suite for provider
implementations.

## Framework-owned credentials

Every credential Agent Kernel itself consumes resolves through `SecretManager`, so a deployment can keep
them all in its secret provider and none in its environment. The environment still wins, so existing
deployments that inject these variables behave exactly as before.

**Keys read directly.** Each is resolved under its usual environment variable name when the component
needs it:

| Component | Key | `aws_ssm` parameter |
| --- | --- | --- |
| Walled AI guardrail | `WALLED_API_KEY` | `/ak/<prefix>/walled_api_key` |
| Slack integration (webhook verification and replies) | `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` | `/ak/<prefix>/slack_bot_token`, `/ak/<prefix>/slack_signing_secret` |
| Gmail integration | `AK_GMAIL__CLIENT_ID`, `AK_GMAIL__CLIENT_SECRET` | `/ak/<prefix>/ak_gmail__client_id`, `/ak/<prefix>/ak_gmail__client_secret` |
| Neo4j knowledge base (no `password` argument) | `NEO4J_PASSWORD` | `/ak/<prefix>/neo4j_password` |
| Starburst knowledge base (no `password` argument) | `STARBURST_PASSWORD` | `/ak/<prefix>/starburst_password` |
| E2B sandbox provider | the key named by `api_key_env` (default `E2B_API_KEY`) | `/ak/<prefix>/e2b_api_key` |
| Daytona sandbox provider | the key named by `api_key_env` (default `DAYTONA_API_KEY`) | `/ak/<prefix>/daytona_api_key` |
| OpenAI realtime runner (`execution.mode: realtime`) | `OPENAI_API_KEY` | `/ak/<prefix>/openai_api_key` |
| Google ADK realtime runner (Gemini Live) | `GOOGLE_API_KEY` | `/ak/<prefix>/google_api_key` |

**Secret-valued configuration fields.** A value set in `config.yaml` or through the field's `AK_*`
environment variable is used as-is. When the field is empty, it is resolved through `SecretManager` under
that same `AK_*` name, at the point of use (never while `AKConfig` loads, since `SecretManager` is built
from it):

| Field | Key | `aws_ssm` parameter |
| --- | --- | --- |
| `whatsapp.verify_token`, `access_token`, `app_secret` | `AK_WHATSAPP__VERIFY_TOKEN`, `AK_WHATSAPP__ACCESS_TOKEN`, `AK_WHATSAPP__APP_SECRET` | `/ak/<prefix>/ak_whatsapp__verify_token`, … |
| `messenger.verify_token`, `access_token`, `app_secret` | `AK_MESSENGER__VERIFY_TOKEN`, `AK_MESSENGER__ACCESS_TOKEN`, `AK_MESSENGER__APP_SECRET` | `/ak/<prefix>/ak_messenger__verify_token`, … |
| `instagram.verify_token`, `access_token`, `app_secret` | `AK_INSTAGRAM__VERIFY_TOKEN`, `AK_INSTAGRAM__ACCESS_TOKEN`, `AK_INSTAGRAM__APP_SECRET` | `/ak/<prefix>/ak_instagram__verify_token`, … |
| `telegram.bot_token`, `webhook_secret` | `AK_TELEGRAM__BOT_TOKEN`, `AK_TELEGRAM__WEBHOOK_SECRET` | `/ak/<prefix>/ak_telegram__bot_token`, `/ak/<prefix>/ak_telegram__webhook_secret` |
| `teams.app_password` | `AK_TEAMS__APP_PASSWORD` | `/ak/<prefix>/ak_teams__app_password` |
| `livekit.api_key`, `api_secret` | `AK_LIVEKIT__API_KEY`, `AK_LIVEKIT__API_SECRET` | `/ak/<prefix>/ak_livekit__api_key`, `/ak/<prefix>/ak_livekit__api_secret` |
| `websocket_api.push_auth_token` | `AK_WEBSOCKET_API__PUSH_AUTH_TOKEN` | `/ak/<prefix>/ak_websocket_api__push_auth_token` |

A provider failure surfaces as `SecretError` from the component that needed the value — at adapter
construction for the messaging integrations, on first use for the others — rather than as a missing
credential. Model keys your own code passes to an SDK (`OPENAI_API_KEY` for a non-realtime agent, a CrewAI
`LLM`, a LangChain chat model, LiteLLM for the multimodal and thread-naming models) are the application's
to resolve, as in the [API](#api) example. A regression test fails the build if a framework module reads a
credential straight from `os.environ`.

## Deploying on AWS

Both the serverless and containerized Terraform modules take an `ssm_enabled` flag (default `false`). When
set, it grants `ssm:GetParameter` on `/ak/<prefix>/*` and injects `AK_SECRET__PREFIX = <prefix>` into every
tier that resolves framework credentials:

| Module | `queue_mode = false` | `queue_mode = true` |
| --- | --- | --- |
| Serverless | request handler | request handler (webhook verification), agent runner, response handler (integration delivery) |
| Containerized | REST service | REST service (webhook verification and integration delivery), agent runner |

The WebSocket connection handler never receives SSM access. In queue mode the request and response tiers
need it only for messaging-integration credentials; an application without integrations reads nothing
there.

```hcl
ssm_enabled = true
```

**Terraform is only half of it.** The module never injects `secret.provider.type` — the application's
`config.yaml` declares `secret.provider.type: aws_ssm`. Terraform also does not create the parameters, so
the key never passes through Terraform state. Do not also inject the key as an environment variable, or it
wins over SSM.

**Running the same app locally.** `aws_ssm` refuses to build without `secret.prefix`, even when the
environment already holds every key. Override the provider for local runs instead of editing `config.yaml`:

```bash
export OPENAI_API_KEY=...
export AK_SECRET__PROVIDER__TYPE=env
```

### Rotation

Overwrite the parameter with `aws ssm put-parameter ... --overwrite`.

- Values read **per call** (e.g. inside a tool) are picked up once the cache entry expires — within
  `cache_ttl` seconds — or immediately after `invalidate(key)`.
- Values handed to an SDK **once at startup** (e.g. `set_default_openai_key`) are picked up on the next cold
  start: force a new ECS deployment (`aws ecs update-service ... --force-new-deployment`), or on Lambda
  update the function's configuration (for example its description) to force fresh execution environments.

## Examples

- [`examples/cli/openai-secret`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai-secret)
  — the `env` provider locally, with a required model key and an optional tool key.
- [`examples/k8s/openai-queue-mode`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/k8s/openai-queue-mode)
  — the OpenAI key read from a mounted Kubernetes Secret by the agent runner.
- [`examples/aws-serverless/openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/openai)
  — the OpenAI key read from SSM on Lambda.
- [`examples/aws-containerized/openai-dynamodb-scalable`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/openai-dynamodb-scalable)
  — the OpenAI key read from SSM by the ECS agent runner.
- [`examples/aws-serverless/slack-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/slack-openai)
  — a Slack integration on Lambda with the OpenAI key and both Slack secrets in SSM and none in any Lambda's
  environment. Every other AWS example reads its model key from SSM the same way.
