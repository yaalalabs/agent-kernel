"""Dedicated behavior tests for the built-in OpikAKEvaluator adapter.

evaluate_by_score is exercised against the real (offline, no-network) `LevenshteinRatio` metric.
evaluate_by_llm mocks `GEval` in place (no real LLM/network call) since that's the one path that
would otherwise hit a live provider. The top_logprobs tests run the real judge model (and the real
`GEval`) against a fake `litellm.completion`, so they stay offline too.
"""

import asyncio
import math
from typing import ClassVar

import pytest
from opik.evaluation.metrics import GEval

from agentkernel.test import (
    AKEvaluationCase,
    AKEvaluationError,
    AKMissingInput,
)
from agentkernel.test.config import AKTestConfig
from agentkernel.test.core.evaluator.opik import (
    _DEFAULT_EVALUATION_CRITERIA,
    OpikAKEvaluator,
)


@pytest.fixture
def evaluator():
    return OpikAKEvaluator(AKTestConfig())


# --- evaluate_by_score --------------------------------------------------------------------#


def test_evaluate_by_score_exact_match(evaluator):
    case = AKEvaluationCase(user_input="capital of France?", actual="Paris", expected="Paris")
    result = evaluator.evaluate_by_score(case)
    assert result.score == 1.0
    assert result.metric == "levenshtein_ratio"
    assert result.evaluator == "opik"
    assert result.passed is True


def test_evaluate_by_score_mismatch(evaluator):
    case = AKEvaluationCase(user_input="capital of France?", actual="London", expected="Paris")
    result = evaluator.evaluate_by_score(case)
    assert result.score == 0.0
    assert result.passed is False


def test_evaluate_by_score_passed_uses_case_threshold(evaluator):
    case = AKEvaluationCase(user_input="capital of France?", actual="London", expected="Paris", threshold=0.0)
    result = evaluator.evaluate_by_score(case)
    assert result.score == 0.0
    assert result.passed is True  # 0.0 >= the case's own threshold of 0.0


def test_evaluate_by_score_is_case_insensitive(evaluator):
    case = AKEvaluationCase(user_input="q", actual="PARIS", expected="paris")
    result = evaluator.evaluate_by_score(case)
    assert result.score == 1.0


def test_evaluate_by_score_missing_expected_raises(evaluator):
    case = AKEvaluationCase(user_input="q", actual="Paris", expected=None)
    with pytest.raises(AKMissingInput):
        evaluator.evaluate_by_score(case)


# --- evaluate_by_llm -----------------------------------------------------------------------#


class _FakeScoreResult:
    def __init__(self, value, reason):
        self.value = value
        self.reason = reason


class _FakeGEval:
    """Stand-in for opik.evaluation.metrics.GEval that never calls a real model."""

    instances: ClassVar[list["_FakeGEval"]] = []
    score_value = 1.0
    score_reason = "looks correct"
    score_error: Exception | None = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeGEval.instances.append(self)

    def score(self, output, **ignored_kwargs):
        self.output = output
        if _FakeGEval.score_error is not None:
            raise _FakeGEval.score_error
        return _FakeScoreResult(_FakeGEval.score_value, _FakeGEval.score_reason)


@pytest.fixture(autouse=True)
def _reset_fake_geval(monkeypatch):
    import agentkernel.test.core.evaluator.opik as ak_opik_module

    _FakeGEval.instances = []
    _FakeGEval.score_value = 1.0
    _FakeGEval.score_reason = "looks correct"
    _FakeGEval.score_error = None
    monkeypatch.setattr(ak_opik_module, "GEval", _FakeGEval)


def test_evaluate_by_llm_missing_expected_raises(evaluator):
    case = AKEvaluationCase(user_input="q", actual="Paris", expected=None)
    with pytest.raises(AKMissingInput):
        evaluator.evaluate_by_llm(case)
    assert _FakeGEval.instances == []  # never got as far as constructing GEval


def test_evaluate_by_llm_empty_actual_fails_without_judging(evaluator):
    case = AKEvaluationCase(user_input="q", actual="", expected="Paris")
    result = evaluator.evaluate_by_llm(case)
    assert result.passed is False
    assert result.score == 0.0
    assert result.metric == "g_eval"
    assert "empty" in result.reason
    assert _FakeGEval.instances == []  # no judge call was attempted


def test_evaluate_by_llm_success(evaluator):
    _FakeGEval.score_value = 0.9
    _FakeGEval.score_reason = "matches expected answer"
    case = AKEvaluationCase(user_input="capital of France?", actual="It's Paris.", expected="Paris")

    result = evaluator.evaluate_by_llm(case)

    assert result.metric == "g_eval"
    assert result.evaluator == "opik"
    assert result.score == 0.9
    assert result.reason == "matches expected answer"
    assert result.passed is True
    (fake,) = _FakeGEval.instances
    assert fake.kwargs["evaluation_criteria"] == _DEFAULT_EVALUATION_CRITERIA
    assert fake.kwargs["track"] is False
    assert fake.kwargs["model"] is evaluator._model
    assert evaluator._model.model_name == "openai/gpt-6-luna"
    # Regression: the judge must see the question and expected output packed into `output`, since
    # opik's GEval.score() takes only that one string.
    assert "capital of France?" in fake.output
    assert "Paris" in fake.output
    assert "It's Paris." in fake.output


def test_evaluate_by_llm_uses_case_criteria_override(evaluator):
    case = AKEvaluationCase(
        user_input="q",
        actual="a",
        expected="e",
        criteria="Score 1 only if it mentions cats.",
    )
    evaluator.evaluate_by_llm(case)
    (fake,) = _FakeGEval.instances
    assert fake.kwargs["evaluation_criteria"] == "Score 1 only if it mentions cats."


def test_evaluate_by_llm_passed_false_below_case_threshold(evaluator):
    _FakeGEval.score_value = 0.4
    case = AKEvaluationCase(user_input="q", actual="a", expected="e", threshold=0.5)
    result = evaluator.evaluate_by_llm(case)
    assert result.score == 0.4
    assert result.passed is False


def test_evaluate_by_llm_wraps_score_exception(evaluator):
    boom = RuntimeError("provider unreachable")
    _FakeGEval.score_error = boom
    case = AKEvaluationCase(user_input="q", actual="a", expected="e")

    with pytest.raises(AKEvaluationError) as exc_info:
        evaluator.evaluate_by_llm(case)
    assert exc_info.value.__cause__ is boom


def test_llm_model_is_lazily_created_and_cached(evaluator):
    """Repeated LLM evaluations must reuse the same configured judge instance."""
    assert evaluator._model is None  # never built by __init__

    case = AKEvaluationCase(user_input="q", actual="a", expected="e")
    evaluator.evaluate_by_llm(case)
    evaluator.evaluate_by_llm(case)

    assert evaluator._model.model_name == "openai/gpt-6-luna"
    assert all(f.kwargs["model"] is evaluator._model for f in _FakeGEval.instances)


@pytest.mark.parametrize(
    "provider, model",
    [("openai", "gpt-6-luna"), ("openai", "gpt-4.1-mini"), ("anthropic", "claude-sonnet-4-5"), ("gemini", "gemini-2.5-flash")],
)
def test_llm_model_sends_the_same_reasoning_params_for_any_model(monkeypatch, provider, model):
    """No per-model branching: every judge is the same LiteLLM model with plain LiteLLM params, which LiteLLM maps or drops per provider."""
    import agentkernel.test.core.evaluator.opik as ak_opik_module

    calls = []

    def _fake_model(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(ak_opik_module, "_TopLogprobsCappedModel", _fake_model)
    config = AKTestConfig()
    config.llm.provider = provider
    config.llm.model = model

    OpikAKEvaluator(config).evaluate_by_llm(AKEvaluationCase(user_input="q", actual="a", expected="e"))

    assert calls == [{"model_name": f"{provider}/{model}", "track": False, "temperature": 0.0, "reasoning_effort": "none", "drop_params": True}]


# --- GEval's top_logprobs ------------------------------------------------------------------#


def _judge_response(content, logprobs=None):
    import litellm

    choice = {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
    if logprobs is not None:
        choice["logprobs"] = logprobs
    return litellm.ModelResponse(model="gpt-6-luna", choices=[choice])


def _score_logprobs():
    """Logprobs for '{"score":8,...}' whose score token puts 0.7 on 8, 0.2 on 9 and 0.1 on 7: GEval weighs that to 0.81."""
    candidates = [{"token": digit, "logprob": math.log(p)} for digit, p in (("8", 0.7), ("9", 0.2), ("7", 0.1))]
    tokens = ['{"', "score", '":', "8", ',"', "reason", '":"', "names the same city", '"}']
    return {
        "content": [
            {"token": token, "logprob": math.log(0.7) if token == "8" else 0.0, "top_logprobs": candidates if token == "8" else []}
            for token in tokens
        ]
    }


def test_default_judge_scores_without_asking_for_more_top_logprobs_than_it_accepts(monkeypatch):
    """Regression: opik's GEval asks for top_logprobs=20 and gpt-6-luna (the default judge) rejects more than 5, so with
    opik up to 2.2.138 every llm-mode evaluation failed. Later versions drop logprobs for gpt-6 models themselves."""
    import litellm

    import agentkernel.test.core.evaluator.opik as ak_opik_module

    monkeypatch.setattr(ak_opik_module, "GEval", GEval)  # the real metric, not the autouse fake
    requests = []

    def _gpt_6_luna(**kwargs):
        requests.append(kwargs)
        if "response_format" not in kwargs:  # GEval's chain-of-thought call
            return _judge_response("1. List the facts the expected output asserts. 2. Check the actual output states each one.")
        if kwargs.get("top_logprobs", 0) > 5:
            raise litellm.BadRequestError(
                message="Invalid 'top_logprobs': must be less than or equal to 5", model=kwargs["model"], llm_provider="openai"
            )
        return _judge_response('{"score":8,"reason":"names the same city"}', logprobs=_score_logprobs() if kwargs.get("logprobs") else None)

    monkeypatch.setattr(litellm, "completion", _gpt_6_luna)  # read by the judge model when it is built

    result = OpikAKEvaluator(AKTestConfig()).evaluate_by_llm(
        AKEvaluationCase(user_input="capital of France?", actual="It's Paris.", expected="Paris")
    )

    (scoring,) = [r for r in requests if "response_format" in r]  # accepted the first time, so never retried
    assert scoring["model"] == "openai/gpt-6-luna"
    assert scoring.get("top_logprobs", 0) <= 5
    # Weighed over the logprobs where opik asks for them (0.81), the text score where it drops them for gpt-6 (0.8).
    assert result.score == pytest.approx(0.81 if scoring.get("logprobs") else 0.8)
    assert result.passed is True


@pytest.mark.parametrize("sent, expected", [(20, 5), (5, 5), (3, 3), (None, None)])
def test_judge_caps_top_logprobs_on_sync_and_async_calls(monkeypatch, sent, expected):
    """The cap is in the judge model, so it holds for any model; gpt-4.1-mini here, whose logprobs no opik version drops."""
    import litellm

    received = []

    def _completion(**kwargs):
        received.append(kwargs.get("top_logprobs"))
        return _judge_response("ok")

    async def _acompletion(**kwargs):
        return _completion(**kwargs)

    monkeypatch.setattr(litellm, "completion", _completion)
    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    config = AKTestConfig()
    config.llm.model = "gpt-4.1-mini"
    judge = OpikAKEvaluator(config)._llm_model()
    kwargs = {} if sent is None else {"logprobs": True, "top_logprobs": sent}
    messages = [{"role": "user", "content": "q"}]

    judge.generate_provider_response(messages, **kwargs)
    asyncio.run(judge.agenerate_provider_response(messages, **kwargs))

    assert received == [expected, expected]
