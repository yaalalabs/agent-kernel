---
name: ak-dev-new-guardrail-provider
description: >
  Step-by-step guide for adding a new guardrail provider to Agent Kernel.
  Use this skill when you need to integrate a new content safety or guardrail
  service (beyond OpenAI Guardrails, AWS Bedrock Guardrails, and Walled AI). Covers implementing
  input/output guardrails, factory registration, configuration, and testing.
license: Apache-2.0
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

- **Input guardrails** subclass the no-op `InputGuardrail` class in `guardrail/guardrail.py` (itself a `PreHook`) — they inspect incoming requests and can halt execution by returning an `AgentReply` instead of passing through
- **Output guardrails** subclass the no-op `OutputGuardrail` class (itself a `PostHook`) — they inspect agent replies and can modify or replace the response
- **`BaseGuardrailUtil`** (also in `guardrail/guardrail.py`) provides shared text-extraction helpers and is mixed into concrete guardrail classes
- **Factories** in `guardrail.py` select the appropriate provider based on `AKConfig.guardrail` configuration; unknown types raise an exception, and the no-op classes are returned only when guardrails are disabled
- Guardrails are registered as **system hooks** in `Runtime`, meaning they apply to all agents automatically

## Step-by-Step

### 1. Create the Guardrail Provider File

Create `ak-py/src/agentkernel/guardrail/<provider>.py`.

### 2. Implement the Base Provider Class

The base class is a plain provider-specific class that holds shared client/config setup. The concrete input/output classes (steps 3 and 4) combine it with the no-op `InputGuardrail`/`OutputGuardrail` hooks and the `BaseGuardrailUtil` mixin. Real examples: `class OpenAIInputGuardrail(BaseGuardrailUtil, BaseOpenAIGuardrail, InputGuardrail)` in `openai.py`, `class BedrockInputGuardrail(BaseGuardrailUtil, BaseBedrockGuardrail, InputGuardrail)` in `bedrock.py`, and `class WalledAIInputGuardrail(InputGuardrail, WalledAIGuardrailBase)` in `walledai.py`.

```python
# ak-py/src/agentkernel/guardrail/<provider>.py
import logging
import os
from abc import ABC
from agentkernel.core.config import AKConfig

logger = logging.getLogger("ak.guardrail.<provider>")


class Base<Provider>Guardrail(ABC):
    """Base class for <Provider> guardrail implementations."""

    def __init__(self):
        config = AKConfig.get().guardrail
        # Initialize the guardrail client/SDK. Secrets come from environment
        # variables, not config (e.g., Walled AI reads WALLED_API_KEY).
        # e.g., self._client = ProviderClient(api_key=os.getenv("<PROVIDER>_API_KEY"))
        logger.info("<Provider> guardrail initialized")
```

### 3. Implement the Input Guardrail

If you are modifying an input request with the guardrail, then you should make sure to return the modified request and all the other unmodified requests. For example, if you have 3 requests and the guardrail modifies the first one, then you should return a list of 3 requests with the first one modified and the other two unmodified.

```python
from typing import Any
from agentkernel.core.base import Agent
from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest
from agentkernel.guardrail.guardrail import BaseGuardrailUtil, InputGuardrail, OutputGuardrail


class <Provider>InputGuardrail(BaseGuardrailUtil, Base<Provider>Guardrail, InputGuardrail):
    """Validates input requests using <Provider> guardrail service."""

    async def on_run(
        self, session: Any | None, agent: Agent, requests: list[AgentRequest]
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
class <Provider>OutputGuardrail(BaseGuardrailUtil, Base<Provider>Guardrail, OutputGuardrail):
    """Validates agent output using <Provider> guardrail service."""

    async def on_run(
        self, session: Any | None, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply
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
            agent_reply.response = message
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

Both factories in `ak-py/src/agentkernel/guardrail/guardrail.py` share the house pluggable-backend
shape from `core/util/factory.py` (`resolve_dotted`, `require_extra`, `AKConfigError` — the same
pattern used by the trace, session/thread/multimodal store, and sandbox provider factories): a
short-circuit for disabled, `if`-per-built-in with the SDK import wrapped in `require_extra` (so a
missing optional dependency raises an actionable `ImportError` naming the pip extra), then a
dotted-path "bring your own" fallback for anything else:

```python
_BUILTIN_GUARDRAILS = ["openai", "bedrock", "walledai"]

class InputGuardrailFactory:
    @staticmethod
    def get() -> PreHook:
        config = AKConfig.get().guardrail.input
        if not config.enabled:
            return InputGuardrail()  # OFF: pass-through hook
        gtype = config.type
        if gtype == "openai":
            with require_extra("openai", "guardrail.input.type: openai"):
                from .openai import OpenAIInputGuardrail
            return OpenAIInputGuardrail()
        if gtype == "bedrock":
            with require_extra("aws", "guardrail.input.type: bedrock"):
                from .bedrock import BedrockInputGuardrail
            return BedrockInputGuardrail()
        if gtype == "walledai":
            with require_extra("walledai", "guardrail.input.type: walledai"):
                from .walledai import WalledAIInputGuardrail
            return WalledAIInputGuardrail()
        if gtype == "<provider>":                                         # ADD THIS
            with require_extra("<provider>", "guardrail.input.type: <provider>"):
                from .<provider> import <Provider>InputGuardrail
            return <Provider>InputGuardrail()
        if "." not in gtype:
            raise AKConfigError(
                f"unknown guardrail type '{gtype}'; expected one of {_BUILTIN_GUARDRAILS} or a dotted path to an InputGuardrail subclass"
            )
        return resolve_dotted(gtype, base=InputGuardrail)()  # bring-your-own

# Same pattern for OutputGuardrailFactory.get()
```

A dotted `type` (e.g. `myorg.guardrails.CustomInputGuardrail`) resolves via `resolve_dotted`
without any factory edit at all — only add an `if` branch here for a first-party, in-repo
provider you want addressable by a short name.

### 6. Add Configuration

Update the guardrail config in `ak-py/src/agentkernel/core/config.py`:

The existing `_GuardrailParamConfig.type` is a free-form string (no regex pattern) described as
"a built-in short name (openai, bedrock, walledai) or a dotted path to an InputGuardrail/OutputGuardrail
subclass" — do not add a `pattern=` constraint back, since that would break the bring-your-own path.
Its only fields are `enabled`, `type`, `pii`, `config_path`, `model`, `id`, and `version` — there is
no `api_key` field. Secrets come from environment variables (e.g., Walled AI reads `WALLED_API_KEY`).
If your provider needs new config fields, add them to `_GuardrailParamConfig` in `core/config.py`:

```yaml
# config.yaml
guardrail:
  input:
    enabled: true
    type: <provider>
    # provider-specific fields (must exist on _GuardrailParamConfig)
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

Add tests to the existing consolidated `ak-py/tests/test_guardrail.py`, which covers the no-op hooks, the factories (including `test_get_raises_exception_for_unknown_type`), and the OpenAI provider:

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
    requests = [AgentRequestText(prompt="What is 2+2?")]
    result = await guardrail.on_run(session, agent, requests)
    assert isinstance(result, list)  # passed through

@pytest.mark.asyncio
async def test_input_guardrail_blocks_unsafe_content():
    guardrail = <Provider>InputGuardrail()
    guardrail._validate = AsyncMock(return_value=MockResult(is_flagged=True))
    requests = [AgentRequestText(prompt="unsafe content")]
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
- [ ] Unit tests added to `ak-py/tests/test_guardrail.py`
- [ ] Example in `examples/cli/guardrail/<provider>/`
- [ ] Documentation
