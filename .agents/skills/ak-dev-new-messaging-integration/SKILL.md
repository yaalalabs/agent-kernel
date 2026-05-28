---
name: ak-dev-new-messaging-integration
description: >
  Step-by-step guide for adding a new messaging platform integration to Agent Kernel.
  Use this skill when you need to add support for a new chat platform (beyond Slack,
    WhatsApp, Messenger, Instagram, Telegram, Teams, Gmail). Covers creating the integration
  handler, webhook routes, message parsing, configuration, and examples.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Messaging Integration

This guide walks through adding a new messaging platform integration to Agent Kernel. Use the Slack integration (`ak-py/src/agentkernel/integration/slack/`) as the canonical reference.

## Architecture Overview

Messaging integrations follow a consistent pattern:

1. A **request handler** class that extends `RESTRequestHandler`
2. The handler exposes FastAPI **routes** for webhooks
3. Incoming messages are parsed into `AgentRequest` models
4. `AgentService` is used to select an agent, run the request, and get a reply
5. The reply is formatted and sent back via the platform's API
6. Configuration is added to `AKConfig` for platform-specific settings

## Step-by-Step

### 1. Create the Integration Directory

```
ak-py/src/agentkernel/integration/<platform>/
├── __init__.py
└── <platform>_chat.py
```

### 2. Implement the Request Handler

```python
# ak-py/src/agentkernel/integration/<platform>/<platform>_chat.py
import logging
from agentkernel.api.handler import RESTRequestHandler
from agentkernel.core import AgentService
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentRequestText, AgentRequestImage, AgentRequestFile
from fastapi import APIRouter, Request

logger = logging.getLogger("ak.integration.<platform>")


class Agent<Platform>RequestHandler(RESTRequestHandler):
    """Handles incoming messages from <Platform> and routes them to Agent Kernel agents."""

    def __init__(self):
        config = AKConfig.get().<platform>
        self._agent_name = config.agent if config else None
        # Initialize platform-specific client/SDK here
        # e.g., self._client = PlatformClient(token=config.bot_token)

    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/health")
        async def health():
            return {"status": "ok"}

        @router.post("/<platform>/webhook")
        async def webhook(request: Request):
            body = await request.json()
            await self._handle_message(body)
            return {"status": "ok"}

        return router

    async def _handle_message(self, body: dict):
        """Parse platform message and route to agent."""
        # 1. Extract message content from platform-specific format
        user_id = body.get("user_id", "unknown")
        text = body.get("text", "")
        attachments = body.get("attachments", [])

        # 2. Build request list
        requests = []
        if text:
            requests.append(AgentRequestText(text=text))

        for attachment in attachments:
            # Handle images
            if attachment.get("type") == "image":
                image_data = await self._download_file(attachment["url"])
                requests.append(AgentRequestImage(
                    image_data=image_data,
                    name=attachment.get("name", "image"),
                    mime_type=attachment.get("mime_type")
                ))
            # Handle files
            elif attachment.get("type") == "file":
                file_data = await self._download_file(attachment["url"])
                requests.append(AgentRequestFile(
                    file_data=file_data,
                    name=attachment.get("name", "file"),
                    mime_type=attachment.get("mime_type")
                ))

        if not requests:
            return

        # 3. Create service, select agent, run
        service = AgentService()
        service.select(session_id=user_id, name=self._agent_name)

        reply = await service.run_multi(requests)

        # 4. Send reply back via platform API
        await self._send_reply(user_id, reply.text)

    async def _download_file(self, url: str) -> str:
        """Download a file and return base64-encoded content."""
        import base64
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._auth_headers())
            return base64.b64encode(response.content).decode("utf-8")

    async def _send_reply(self, channel: str, text: str):
        """Send reply back to the messaging platform."""
        # Platform-specific API call to send message
        # e.g., self._client.send_message(channel=channel, text=text)
        pass

    def _auth_headers(self) -> dict:
        """Return auth headers for platform API calls."""
        return {}
```

### 3. Create the `__init__.py`

```python
# ak-py/src/agentkernel/integration/<platform>/__init__.py
from .<platform>_chat import Agent<Platform>RequestHandler
```

### 4. Create the Public API Alias

Create `ak-py/src/agentkernel/<platform>.py`:

```python
from .integration.<platform> import Agent<Platform>RequestHandler
```

This allows `from agentkernel.<platform> import Agent<Platform>RequestHandler`.

### 5. Add Configuration

Add a configuration section to `ak-py/src/agentkernel/core/config.py`:

```python
class _<Platform>Config(BaseModel):
    agent: str | None = None
    bot_token: str | None = None       # platform-specific fields
    webhook_secret: str | None = None  # for webhook verification
    # Add other platform-specific config fields

class AKConfig(YamlBaseSettingsModified):
    # ... existing fields ...
    <platform>: _<Platform>Config = _<Platform>Config()
```

This enables configuration via `config.yaml`:

```yaml
<platform>:
  agent: general
  bot_token: "xoxb-..."
```

Or environment variables: `AK_<PLATFORM>__AGENT=general`, `AK_<PLATFORM>__BOT_TOKEN=xoxb-...`

### 6. Add Optional Dependencies

In `ak-py/pyproject.toml`:

```toml
[project.optional-dependencies]
<platform> = [
    "httpx>=0.27.0",           # for HTTP API calls (most platforms need this)
    "platform-sdk>=x.y.z",     # platform-specific SDK if available
]
```

### 7. Webhook Verification

Most platforms require webhook verification. Implement it in the webhook route:

```python
@router.post("/<platform>/webhook")
async def webhook(request: Request):
    body = await request.json()

    # Challenge/verification handling (platform-specific)
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    # Signature verification (recommended for security)
    signature = request.headers.get("X-Platform-Signature")
    if not self._verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    await self._handle_message(body)
    return {"status": "ok"}
```

### 8. Message Chunking

If the platform has message length limits, implement a reply splitter:

```python
def _split_reply(self, text: str, max_length: int = 4000) -> list[str]:
    """Split long replies into platform-compatible chunks."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    return chunks
```

### 9. Usage Pattern

Users will use the integration like this:

```python
# server.py
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.<platform> import Agent<Platform>RequestHandler
from agents import Agent

agent = Agent(name="general", instructions="You are a helpful assistant.")
OpenAIModule([agent])

if __name__ == "__main__":
    RESTAPI.run([Agent<Platform>RequestHandler()])
```

### 10. Add Example

Create `examples/api/<platform>/` with:
- `server.py` — minimal working example
- `pyproject.toml` — with `agentkernel[api,openai,<platform>]` dependency
- `config.yaml` — platform configuration
- `server_test.py` — health check and basic functional test
- `README.md` — setup instructions (bot token, webhook URL, etc.)

### 11. Add Tests

Create `ak-py/tests/test_<platform>.py` with:
- Unit tests for message parsing
- Unit tests for reply formatting/chunking
- Mock tests for webhook handling

### 12. Add Documentation

Add `docs/docs/integrations/<platform>.md` covering:
- Platform setup (creating a bot, getting tokens)
- Configuration options
- Example code
- Webhook URL setup

## Checklist

- [ ] `ak-py/src/agentkernel/integration/<platform>/` directory
- [ ] `Agent<Platform>RequestHandler` extending `RESTRequestHandler`
- [ ] Public alias at `ak-py/src/agentkernel/<platform>.py`
- [ ] Configuration class in `config.py`
- [ ] Optional dependency group in `pyproject.toml`
- [ ] Webhook verification
- [ ] Message chunking for long replies
- [ ] Example in `examples/api/<platform>/`
- [ ] Tests in `ak-py/tests/`
- [ ] Documentation in `docs/docs/integrations/<platform>.md`
