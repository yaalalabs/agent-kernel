---
name: ak-dev-new-messaging-integration
description: >
  Step-by-step guide for adding a new messaging platform integration to Agent Kernel.
  Use this skill when you need to add support for a new chat platform (beyond Slack,
    WhatsApp, Messenger, Instagram, Telegram, Teams, Gmail). Covers writing the
  inbound/outbound adapter pair, hosting it, webhook verification, attachments, configuration,
  and examples.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Messaging Integration

This guide walks through adding a new messaging platform integration to Agent Kernel. Use the WhatsApp adapter (`ak-py/src/agentkernel/integration/whatsapp/adapter.py`) as the canonical webhook reference, and Gmail (`integration/gmail/adapter.py`) as the polling one.

## Architecture Overview

**A platform integration is two pure translation functions with a queue between them** (spec #524):

1. An **`InboundAdapter`** turns one platform delivery into normalized `InboundRequest` envelopes: it verifies the delivery, extracts the text, downloads and stores attachments, and resolves `session_id` and `request_id` at the edge. It **never runs the agent**.
2. The **pipeline** carries the request: `IntegrationProducer` enqueues it, `AgentRunner` executes it platform-agnostically, and the reply travels back on the output queue with the `integration` attribute and the `reply_`-prefixed reply context.
3. An **`OutboundAdapter`** turns the agent's reply back into platform API calls, using nothing but the flat `reply_context` the inbound half resolved.

This is why the webhook answers in milliseconds: a slow agent run can no longer hold the turn open past the platform's delivery timeout and cause a redelivery.

Hosting depends on how the platform delivers events:

| Source | Host | Entry point |
|---|---|---|
| `Source.WEBHOOK` (pushed) | `WebhookRESTRequestHandler` | `IOHandler.run(handlers=[WebhookRESTRequestHandler(MyInboundAdapter())])` |
| `Source.POLLER` (pulled) | `PollerRunner` | `IOHandler.run(pollers=[PollerRunner(MyInboundAdapter())])` on `in_memory`, `PollerRunner.run(adapter)` as its own container on a broker |

**Adapters must be mounted inside the pipeline.** `WebhookRESTRequestHandler` sets `requires_pipeline = True`, so `RESTAPI.run([...])` refuses it with an `AKConfigError`: without a queue there would be no runner to drain what it enqueues, and the platform would get its 200 while the user never got a reply.

## Step-by-Step

### 1. Create the Integration Directory

```
ak-py/src/agentkernel/integration/<platform>/
├── __init__.py
└── adapter.py
```

### 2. Implement the Inbound Adapter

```python
# ak-py/src/agentkernel/integration/<platform>/adapter.py
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request

from ...core.config import AKConfig
from ...core.model import AgentReply, AgentRequest, AgentRequestImage, AgentRequestText
from ...core.multimodal.storage.offload import offload_attachments
from ..adapter.base import (
    ATTACHMENTS_DISABLED_ERROR,
    SESSION_CACHE_ERROR,
    InboundAdapter,
    InboundParseResult,
    InboundRequest,
    OutboundAdapter,
)

NAME = "<platform>"
_log = logging.getLogger("ak.integration.<platform>")


class <Platform>InboundAdapter(InboundAdapter):
    """<Platform> deliveries -> normalized requests."""

    name = NAME
    webhook_path = "/<platform>/webhook"
    challenge_path = None  # set to the same path when the platform has a GET handshake

    _log = _log

    def __init__(self):
        config = AKConfig.get()
        self._agent = config.<platform>.agent or None
        self._max_file_size = config.api.max_file_size
        self._client = <Platform>Client()   # your API wrapper

    async def verify(self, raw: Request) -> None:
        """Reject a delivery that did not come from the platform. Runs before parse."""
        if not self._client.verify(await raw.body(), raw.headers.get("x-platform-signature", "")):
            raise HTTPException(status_code=403, detail="Invalid signature")

    async def parse(self, raw: Request) -> InboundParseResult:
        """One delivery can carry several messages; return one InboundRequest per message."""
        body = await raw.json()
        requests = [r for r in [await self._to_request(m) for m in body.get("messages", [])] if r is not None]
        return InboundParseResult(requests=requests)

    async def _to_request(self, message: dict) -> Optional[InboundRequest]:
        text = message.get("text", "")
        sender = message["from"]
        if not text:
            return None   # legitimately ignored: an empty list is not an error

        requests: List[AgentRequest] = [AgentRequestText(prompt=text)]
        # ... download attachments into `requests` here (see step 5) ...

        requests, _ = offload_attachments(
            sender,
            requests,
            attachments_disabled_error=ATTACHMENTS_DISABLED_ERROR,
            session_cache_error=SESSION_CACHE_ERROR,
        )
        return InboundRequest(
            session_id=sender,             # the platform's conversation key
            request_id=message["id"],      # the platform's own id: this is what dedupes a retry
            requests=requests,
            prompt=text,
            agent=self._agent,
            user_id=sender,
            reply_context={"to": sender},  # flat, string-valued delivery coordinates
        )
```

Rules the adapter must hold to:

1. **Never execute.** No `ChatService`, `AgentService` or `Runtime` import. The only side effects allowed are platform API calls and attachment storage.
2. **Read only your own config block**, `AKConfig.get().<platform>`.
3. **`verify` before `parse`, `parse` before enqueue.** `verify` is concrete and a no-op on the base: override it only when verification is separable from parsing. (Slack and Teams verify inside their SDK's dispatch, so theirs stays the default.)
4. **`request_id` is the platform's message id** wherever one exists; that is what makes a webhook retry deduplicate instead of running the agent twice. Synthesize a stable one only when the platform gives you none (Slack: `f"slack:{channel}:{ts}"`).
5. **An ignored delivery returns an empty request list**, never an exception.

### 3. Implement the Outbound Adapter

```python
class <Platform>OutboundAdapter(OutboundAdapter):
    """Agent replies -> <Platform> messages."""

    name = NAME
    MESSAGE_LIMIT = 4096          # the platform's per-message limit; split_reply chunks to it
    MAX_CHUNKS = None             # or a cap, with TRUNCATION_NOTICE appended past it

    _log = _log

    def __init__(self):
        self._client = <Platform>Client()

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        """Edge-side feedback: a typing indicator, a read receipt, a "thinking" message.

        The returned dict is merged into reply_context, which is how Slack carries the id of
        its placeholder message through to delivery.
        """
        await self._client.typing(reply_context["to"])
        return {}

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        """Raising hands the message back for retry, then deliver_error."""
        await self._client.send(reply_context["to"], self.split_reply(str(reply)))

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        try:
            await self._client.send(reply_context["to"], [message])
        except Exception as e:
            self._log.error(f"Could not deliver the <Platform> error message: {e}")
```

- The reply always arrives as an `AgentReplyText`: the Agent Runner serializes the typed reply to its string form before the output queue.
- Outbound adapters are **cached and shared across consumer threads**, and each call runs on its own event loop. Keep no per-message state on `self`, and build loop-bound clients (an `httpx.AsyncClient`) per call.
- `deliver_error` receives `OutboundAdapter.ERROR_MESSAGE`, not the raw exception: raw error text is logged, never sent to a platform user.

### 4. Reply Context

`reply_context` is flat, string-valued delivery coordinates: everything `deliver` needs and nothing else. It travels as `reply_`-prefixed message attributes rather than body fields, because `BaseRunRequest` is `extra="allow"` and an unknown body field would reach the agent as `AgentRequestAny` context.

Budget: **8 KB serialized**, enforced in `IntegrationProducer` with a `ValueError` naming the adapter. If the platform's reply address is an object rather than strings, JSON-encode it into one value (Teams does this with its `ConversationReference`).

### 5. Attachments

Attachment bytes must **not** ride the queue: brokers cap a message far below `api.max_file_size`. Download at the edge (that is where the platform token is), then call `offload_attachments`, which stores the bytes in the `AttachmentStore` and replaces each image/file request with an `AgentRequestAttachmentRef`.

This makes `multimodal.enabled: true` a requirement for attachment-bearing messages, and rejects `multimodal.storage_type: session_cache` (it writes into a session copy the runner process never sees). Both messages are shared constants; pass them through as shown in step 2.

### 6. Create the `__init__.py` and the Public Alias

```python
# ak-py/src/agentkernel/integration/<platform>/__init__.py
from .adapter import <Platform>InboundAdapter, <Platform>OutboundAdapter
```

Create `ak-py/src/agentkernel/<platform>.py` with a wildcard import (see `ak-py/src/agentkernel/slack.py`):

```python
from .integration.<platform> import *
```

### 7. Register the Built-in with the Factory

The Response Handler holds only the `integration` attribute string, so **the outbound half is resolved by name**. Add the platform to `IntegrationAdapterFactory` (`integration/adapter/factory.py`): its short name in `_BUILTIN_NAMES`, and an `if/elif` branch in `_builtin` importing the class inside `require_extra`.

(The inbound half is never resolved by name: the application constructs it and hands it to a host, so bring-your-own inbound is just passing a different instance.)

### 8. Add Configuration

Add a config section to `ak-py/src/agentkernel/core/config.py`, following the existing idiom (`Field` with empty-string defaults). Every platform block carries an `outbound_adapter` override:

```python
class _<Platform>Config(BaseModel):
    agent: str = Field(default="", description="Agent name to handle <Platform> messages")
    bot_token: str = Field(default="", description="<Platform> bot token")
    webhook_secret: str = Field(default="", description="Webhook verification secret")
    outbound_adapter: str = Field(
        default="",
        description="Dotted path to an OutboundAdapter subclass replacing the built-in <Platform> outbound adapter",
    )


class AKConfig(YamlBaseSettingsModified):
    <platform>: _<Platform>Config = Field(description="<Platform> related configurations", default_factory=_<Platform>Config)
```

Configurable through `config.yaml` or `AK_<PLATFORM>__AGENT` / `AK_<PLATFORM>__BOT_TOKEN` environment variables.

### 9. Add Optional Dependencies

In `ak-py/pyproject.toml`:

```toml
[project.optional-dependencies]
<platform> = [
    "httpx>=0.27.0",           # for HTTP API calls (most platforms need this)
    "platform-sdk>=x.y.z",     # platform-specific SDK if available
]
```

The factory imports the built-in inside `require_extra("<platform>", ...)`, so a missing SDK reports `pip install "agentkernel[<platform>]"` rather than a bare `ModuleNotFoundError`.

### 10. Polling Platforms

A platform with no webhook subclasses `PollingInboundAdapter` instead:

```python
class <Platform>InboundAdapter(PollingInboundAdapter):
    name = NAME
    poll_interval = 30.0   # read it from your config block in __init__

    async def poll(self) -> List[Any]:
        """Return the raw events to parse this iteration. Must not run the agent."""

    def mark_handled(self, raw: Any) -> None:
        """Called after an event is enqueued, so the next poll skips it."""
```

`PollerRunner` waits on `ThreadRunner.shutdown_event` between iterations, so a 30-second interval still drains promptly on SIGTERM. Run the poller at **one replica**: `mark_handled` state is per process (see Gmail, where a message stays unread until its reply is sent).

### 11. Usage Pattern

```python
# server.py
from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import IOHandler
from agentkernel.<platform> import <Platform>InboundAdapter
from agents import Agent

agent = Agent(name="general", instructions="You are a helpful assistant.")
OpenAIModule([agent])

if __name__ == "__main__":
    IOHandler.run(handlers=[WebhookRESTRequestHandler(<Platform>InboundAdapter())])
```

### 12. Add Example

Create `examples/api/<platform>/` with:
- `server.py` — minimal working example (the pattern above)
- `pyproject.toml` — with `agentkernel[api,openai,<platform>]` dependency
- `config.yaml` — platform configuration
- `server_test.py` — health check and basic functional test
- `README.md` — setup instructions (bot token, webhook URL, etc.)

### 13. Add Tests

Two files:

1. `ak-py/tests/test_integration_adapter_contract.py` — add a `IntegrationAdapterContract` subclass for the platform. The contract covers the invariants the queue hop needs: stable identifiers, an ignorable delivery that is not an error, a flat reply context inside its budget, and a clean round trip through `IntegrationProducer`.
2. `ak-py/tests/test_<platform>_integration.py` — the platform's own parsing and formatting. Build the adapter via `object.__new__` with a stubbed API client (see `test_whatsapp_integration.py`), and cover: message parsing, ignored deliveries, rejection paths (oversized, unsupported media, download failure), verification, reply chunking and acknowledgement.

### 14. Add Documentation

Add `docs/docs/integrations/<platform>.md` covering:
- Platform setup (creating a bot, getting tokens)
- Configuration options, including `outbound_adapter`
- Example code using `IOHandler.run(handlers=[...])`
- Webhook URL setup
- The `multimodal.enabled` requirement if the platform accepts attachments

## Checklist

- [ ] `ak-py/src/agentkernel/integration/<platform>/adapter.py` with the inbound/outbound pair
- [ ] `verify` (or a documented reason it stays the base no-op) and `challenge` if the platform has a handshake
- [ ] `request_id` set from the platform's own message id
- [ ] Attachments offloaded with `offload_attachments`, never inlined
- [ ] `reply_context` flat, string-valued, inside the 8 KB budget
- [ ] `MESSAGE_LIMIT` (and `MAX_CHUNKS`) set to the platform's limits
- [ ] Package `__init__.py` and public alias at `ak-py/src/agentkernel/<platform>.py`
- [ ] Registered in `IntegrationAdapterFactory._BUILTIN_NAMES` and `_builtin`
- [ ] Configuration class in `config.py`, including `outbound_adapter`
- [ ] Optional dependency group in `pyproject.toml`
- [ ] Example in `examples/api/<platform>/` mounting through `IOHandler.run`
- [ ] `IntegrationAdapterContract` subclass plus the per-platform test file
- [ ] Documentation in `docs/docs/integrations/<platform>.md`
