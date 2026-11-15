# Models that only run in thinking mode: LiteLLM maps reasoning_effort="none" to thinkingBudget=0 for them,
# which the provider rejects instead of ignoring (https://ai.google.dev/gemini-api/docs/thinking).
_CANNOT_DISABLE_REASONING = ("gemini-2.5-pro",)


def reasoning_off_params(model: str) -> dict[str, str]:
    """
    LiteLLM params that turn reasoning off for a capped or deterministic call, where the model can.
    Reasoning models get reasoning_effort="none" (LiteLLM maps it per provider). Models without reasoning,
    and reasoning models that cannot turn it off, get nothing, so the call is sent as if the setting didn't exist.
    :param model: LiteLLM model name, e.g. "gpt-6-luna" or "gemini/gemini-2.5-flash".
    :return: Keyword arguments to merge into the LiteLLM call.
    """
    try:
        import litellm  # optional dependency — without it there's no LiteLLM call to tune
    except ImportError:
        return {}
    if not litellm.supports_reasoning(model=model):
        return {}
    if any(name in model.lower() for name in _CANNOT_DISABLE_REASONING):
        return {}
    return {"reasoning_effort": "none"}
