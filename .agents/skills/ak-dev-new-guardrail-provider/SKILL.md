---
name: ak-dev-new-guardrail-provider
description: >
  Step-by-step guide for adding a new guardrail provider to Agent Kernel.
  Use this skill when you need to integrate a new content safety or guardrail
  service (beyond OpenAI Guardrails, AWS Bedrock Guardrails, and Walled AI). Covers implementing
  input/output guardrails, factory registration, configuration, and testing.
license: apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Guardrail Provider

This guide walks through adding a new guardrail provider to Agent Kernel. Use the existing OpenAI (`ak-py/src/agentkernel/guardrail/openai.py`), Bedrock (`ak-py/src/agentkernel/guardrail/bedrock.py`), and Walled AI (`ak-py/src/agentkernel/guardrail/walledai.py`) implementations as reference.

## Existing Providers

| Provider | Type value | Features | Extra |
|---|---|---|---|
| OpenAI | `openai` | Content moderation, jailbreak detection, PII detection (via config JSON) | `agentkernel[openai]` |
| AWS Bedrock | `bedrock` | AWS-managed guardrails (ID + version) | `agentkernel[aws]` |
| Walled AI | `walledai` | Content safety + PII redaction/unmasking (via `pii` flag) | `agentkernel[walledai]` |

## Architecture Overview

Agent Kernel's guardrail system uses the hook mechanism:

- **Input guardrails** are `PreHook` implementations — they inspect incoming requests and can halt execution by returning an `AgentReply` instead of passing through
- **Output guardrails** are `PostHook` implementations — they inspect agent replies and can modify or replace the response
- **Factories** in `guardrail.py` select the appropriate provider based on `AKConfig.guardrail` configuration
- Guardrails are registered as **system hooks** in `Runtime`, meaning they apply to all agents automatically

## Step-by-Step

### 1. Create the Guardrail Provider File

Create `ak-py/src/agentkernel/guardrail/<provider>.py`.

### 2. Implement the Base Provider Class

```python
# ak-py/src/agentkernel/guardrail/<provider>.py
import logging
from abc import ABC
from agentkernel.core.config import AKConfig

logger = logging.getLogger("ak.guardrail.<provider>")


class Base<Provider>Guardrail(ABC):
    """Base class for <Provider> guardrail implementations."""

    def __init__(self):
        config = AKConfig.get().guardrail
        # Initialize the guardrail client/SDK
        # e.g., self._client = ProviderClient(api_key=config.api_key)
        logger.info("<Provider> guardrail initialized")
```

### 3. Implement the Input Guardrail

If you are modifying an input request with the guardrail, then you should make sure to return the modified request and all the other unmodified requests. For example, if you have 3 requests and the guardrail modifies the first one, then you should return a list of 3 requests with the first one modified and the other two unmodified.

```python
from agentkernel.core.base import Agent, Session
from agentkernel.core.hooks import PreHook
from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest
from agentkernel.guardrail.guardrail import BaseGuardrailUtil


class <Provider>InputGuardrail(Base<Provider>Guardrail, PreHook):
    """Validates input requests using <Provider> guardrail service."""

    async def on_run(
        self, session: Session, agent: Agent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        # 1. Extract text content from requests
        text = BaseGuardrailUtil._extract_text_from_requests(requests)
        if not text:
            return requests  # No text to validate, pass through

        # 2. Call the guardrail service
        try:
            result = await self._validate(text)
        except Exception as e:
            logger.error(f"Guardrail validation error: {e}")
            return requests  # Fail open (or fail closed based on policy)

        # 3. If content is flagged, return an AgentReply to halt execution
        if result.is_flagged:
            message = self._build_intervention_message(result)
            logger.warning(f"Input guardrail triggered: {message}")
            return AgentReplyText(
                text=message,
                prompt=text
            )

        # 4. Content is safe, pass through
        return requests

    async def _validate(self, text: str):
        """Call the guardrail provider's API to validate text."""
        # Provider-specific validation logic
        # return self._client.validate(text=text, source="INPUT")
        pass

    def _build_intervention_message(self, result) -> str:
        """Build a user-friendly message when content is blocked."""
        return "I apologize, but I'm unable to process this request as it may violate content safety guidelines."

    def name(self) -> str:
        return "<provider>_input_guardrail"
```


### 4. Implement the Output Guardrail

```python
class <Provider>OutputGuardrail(Base<Provider>Guardrail, PostHook):
    """Validates agent output using <Provider> guardrail service."""

    async def on_run(
        self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply
    ) -> AgentReply:
        # 1. Extract text from the reply
        text = BaseGuardrailUtil._extract_text_from_reply(agent_reply)
        if not text:
            return agent_reply  # No text to validate

        # 2. Call the guardrail service
        try:
            result = await self._validate(text)
        except Exception as e:
            logger.error(f"Output guardrail validation error: {e}")
            return agent_reply  # Fail open

        # 3. If content is flagged, modify the reply
        if result.is_flagged:
            message = self._build_intervention_message(result)
            logger.warning(f"Output guardrail triggered: {message}")
            agent_reply.text = message
            return agent_reply

        # 4. Content is safe, return unchanged
        return agent_reply

    async def _validate(self, text: str):
        """Call the guardrail provider's API to validate text."""
        pass

    def _build_intervention_message(self, result) -> str:
        return "The generated response was flagged by content safety filters and has been blocked."

    def name(self) -> str:
        return "<provider>_output_guardrail"
```

### 5. Register with the Factory

Update `ak-py/src/agentkernel/guardrail/guardrail.py` to add the new provider to both factories:

```python
# In InputGuardrailFactory.get():
class InputGuardrailFactory:
    @staticmethod
    def get() -> PreHook:
        config = AKConfig.get().guardrail
        if config and config.input and config.input.enabled:
            if config.input.type == "openai":
                from .openai import OpenAIInputGuardrail
                return OpenAIInputGuardrail()
            elif config.input.type == "bedrock":
                from .bedrock import BedrockInputGuardrail
                return BedrockInputGuardrail()
            elif config.input.type == "walledai":
                from .walledai import WalledAIInputGuardrail
                return WalledAIInputGuardrail()
            elif config.input.type == "<provider>":          # ADD THIS
                from .<provider> import <Provider>InputGuardrail
                return <Provider>InputGuardrail()
        return InputGuardrail()  # no-op default

# Same pattern for OutputGuardrailFactory.get()
```

### 6. Add Configuration

Update the guardrail config in `ak-py/src/agentkernel/core/config.py`:

The existing `_GuardrailParamConfig` already supports a `type` field with pattern `^(openai|bedrock|walledai)$`. To add your provider, update the pattern regex and add any provider-specific config fields if needed:

```yaml
# config.yaml
guardrail:
  input:
    enabled: true
    type: <provider>
    # provider-specific fields
    api_key: "..."
    config_path: guardrails_input.json
  output:
    enabled: true
    type: <provider>
    config_path: guardrails_output.json
```

### 7. Add Optional Dependencies

If the provider requires additional packages, add them to `ak-py/pyproject.toml` either under an existing group or a new one:

```toml
[project.optional-dependencies]
# Option A: Add to existing openai group if it's an OpenAI-based provider
# Option B: Create a new group
<provider>-guardrail = [
    "provider-sdk>=x.y.z",
]
```

### 8. Add Tests

Create `ak-py/tests/test_guardrail_<provider>.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from agentkernel.core.model import AgentRequestText, AgentReplyText
from agentkernel.guardrail.<provider> import (
    <Provider>InputGuardrail,
    <Provider>OutputGuardrail
)

@pytest.mark.asyncio
async def test_input_guardrail_passes_safe_content():
    guardrail = <Provider>InputGuardrail()
    # Mock the validation to return safe
    guardrail._validate = AsyncMock(return_value=MockResult(is_flagged=False))
    requests = [AgentRequestText(text="What is 2+2?")]
    result = await guardrail.on_run(session, agent, requests)
    assert isinstance(result, list)  # passed through

@pytest.mark.asyncio
async def test_input_guardrail_blocks_unsafe_content():
    guardrail = <Provider>InputGuardrail()
    guardrail._validate = AsyncMock(return_value=MockResult(is_flagged=True))
    requests = [AgentRequestText(text="unsafe content")]
    result = await guardrail.on_run(session, agent, requests)
    assert isinstance(result, AgentReplyText)  # halted
```

### 9. Add Example

Create `examples/cli/guardrail/<provider>/` with:
- `demo.py` — agent with guardrails enabled
- `config.yaml` — guardrail configuration
- `pyproject.toml` — dependencies
- `demo_test.py` — tests verifying guardrail triggers

### 10. Add Documentation

Add guardrail provider docs to `docs/docs/advanced/guardrails.md` or create `docs/docs/advanced/guardrails-<provider>.md`.

## Checklist

- [ ] `ak-py/src/agentkernel/guardrail/<provider>.py` with base, input, and output classes
- [ ] Factory registration in `guardrail.py` for both input and output
- [ ] Configuration support via `type: "<provider>"` in `config.yaml`
- [ ] Optional dependencies in `pyproject.toml` (if needed)
- [ ] Unit tests in `ak-py/tests/test_guardrail_<provider>.py`
- [ ] Example in `examples/cli/guardrail/<provider>/`
- [ ] Documentation
