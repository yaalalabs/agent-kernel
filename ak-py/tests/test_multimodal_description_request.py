"""The request MultimodalPreHook sends to LiteLLM when it describes a new attachment."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.multimodal.hooks import MultimodalPreHook


def _llm_response(content):
    """Build a minimal litellm.acompletion response carrying the given content."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.mark.parametrize("mime_type", ["image/png", "application/pdf"])
@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-4.1-mini", "anthropic/claude-sonnet-4-5"])
def test_description_call_sends_the_same_params_for_any_model(monkeypatch, mime_type, model):
    """No per-model branching: the capped call asks for reasoning off and lets LiteLLM drop what a model doesn't support."""
    monkeypatch.setattr(AKConfig.get().multimodal, "description_model", model)
    with patch("litellm.acompletion", new=AsyncMock(return_value=_llm_response(" A red square. "))) as acompletion:
        description = asyncio.run(MultimodalPreHook()._describe_attachment_briefly(data="aW1n", mime_type=mime_type))

    assert description == "A red square."
    kwargs = acompletion.call_args.kwargs
    assert kwargs["model"] == model
    assert kwargs["max_tokens"] == 50
    assert kwargs["reasoning_effort"] == "none"
    assert kwargs["drop_params"] is True
