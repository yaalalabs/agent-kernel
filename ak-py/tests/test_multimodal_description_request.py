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
@pytest.mark.parametrize(
    "model, reasoning_effort",
    [("gpt-6-luna", "none"), ("anthropic/claude-sonnet-4-5", "none"), ("gpt-4.1-mini", None), ("gemini/gemini-2.5-pro", None)],
)
def test_description_call_turns_reasoning_off_where_the_model_can(monkeypatch, mime_type, model, reasoning_effort):
    """The capped call asks for reasoning off only from reasoning models that can turn it off."""
    monkeypatch.setattr(AKConfig.get().multimodal, "description_model", model)
    with patch("litellm.acompletion", new=AsyncMock(return_value=_llm_response(" A red square. "))) as acompletion:
        description = asyncio.run(MultimodalPreHook()._describe_attachment_briefly(data="aW1n", mime_type=mime_type))

    assert description == "A red square."
    kwargs = acompletion.call_args.kwargs
    assert kwargs["model"] == model
    assert kwargs["max_tokens"] == 50
    assert kwargs.get("reasoning_effort") == reasoning_effort
    assert kwargs["drop_params"] is True
