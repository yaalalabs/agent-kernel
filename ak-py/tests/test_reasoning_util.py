"""reasoning_off_params: which LiteLLM models are asked to turn reasoning off."""

import builtins

import pytest

from agentkernel.core.util.reasoning import reasoning_off_params


@pytest.mark.parametrize("model", ["gpt-6-luna", "openai/gpt-6-luna", "anthropic/claude-sonnet-4-5", "gemini/gemini-2.5-flash"])
def test_reasoning_model_that_can_turn_reasoning_off_gets_none(model):
    assert reasoning_off_params(model) == {"reasoning_effort": "none"}


@pytest.mark.parametrize("model", ["gemini/gemini-2.5-pro", "vertex_ai/gemini-2.5-pro", "gemini-2.5-pro"])
def test_reasoning_model_that_cannot_turn_reasoning_off_gets_nothing(model):
    """LiteLLM would send thinkingBudget=0, which Gemini 2.5 Pro rejects."""
    assert reasoning_off_params(model) == {}


@pytest.mark.parametrize("model", ["gpt-4.1-mini", "openai/gpt-4o-mini"])
def test_non_reasoning_model_gets_nothing(model):
    assert reasoning_off_params(model) == {}


def test_without_litellm_gets_nothing(monkeypatch):
    real_import = builtins.__import__

    def _no_litellm(name, *args, **kwargs):
        if name == "litellm":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_litellm)
    assert reasoning_off_params("gpt-6-luna") == {}
