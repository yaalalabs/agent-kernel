# Models that only run in thinking mode: LiteLLM maps reasoning_effort="none" to thinkingBudget=0 for them,
# which the provider rejects instead of ignoring (https://ai.google.dev/gemini-api/docs/thinking).
_CANNOT_DISABLE_REASONING = ("gemini-2.5-pro",)


def reasoning_off_params(model: str) -> dict[str, str]:
    """
    LiteLLM params that turn reasoning off for a capped or deterministic call, where the model can.
    Reasoning models get reasoning_effort="none" (LiteLLM maps it per provider). Models without reasoning,
    and reasoning models that cannot turn it off, get nothing, so the call is sent as if the setting didn't exist.
    A model counts as unable to turn it off when it is listed in _CANNOT_DISABLE_REASONING or when LiteLLM's
    model info marks supports_none_reasoning_effort as false (e.g. gpt-5 and gpt-5-mini, which reject "none").
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
    try:
        none_supported = litellm.get_model_info(model=model).get("supports_none_reasoning_effort")
    except Exception:
        none_supported = None  # no model info: leave it to the reasoning check above
    if none_supported is False:
        return {}
    return {"reasoning_effort": "none"}
