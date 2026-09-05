"""Dedicated behavior tests for the built-in DeepevalAKEvaluator adapter.

evaluate_by_score is exercised against the real (offline, no-network) `Scorer` — it's pure
string normalization. evaluate_by_llm mocks `GEval` in place (no real LLM/network call) since
that's the one path that would otherwise hit a live provider.
"""

from typing import ClassVar

import pytest
from deepeval.test_case import SingleTurnParams

from agentkernel.test.config import AKTestConfig
from agentkernel.test.core.evaluator import (
    AKEvaluationCase,
    AKEvaluationError,
    AKMissingInput,
)
from agentkernel.test.core.evaluator.deepeval import (
    _DEFAULT_LLM_EVALUATION_STEPS,
    DeepevalAKEvaluator,
)


@pytest.fixture
def evaluator():
    return DeepevalAKEvaluator(AKTestConfig())


# --- evaluate_by_score --------------------------------------------------------------------#


def test_evaluate_by_score_exact_match(evaluator):
    case = AKEvaluationCase(user_input="capital of France?", actual="Paris", expected="Paris")
    result = evaluator.evaluate_by_score(case)
    assert result.score == 1.0
    assert result.metric == "quasi_exact_match"
    assert result.evaluator == "deepeval"
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


def test_evaluate_by_score_normalizes_whitespace_and_case(evaluator):
    case = AKEvaluationCase(user_input="q", actual="  PARIS  ", expected="paris")
    result = evaluator.evaluate_by_score(case)
    assert result.score == 1.0


def test_evaluate_by_score_missing_expected_raises(evaluator):
    case = AKEvaluationCase(user_input="q", actual="Paris", expected=None)
    with pytest.raises(AKMissingInput):
        evaluator.evaluate_by_score(case)


# --- evaluate_by_llm -----------------------------------------------------------------------#


class _FakeGEval:
    """Stand-in for deepeval.metrics.GEval that never calls a real model."""

    instances: ClassVar[list["_FakeGEval"]] = []
    measure_score = 1.0
    measure_reason = "looks correct"
    measure_error: Exception | None = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.reason = None
        _FakeGEval.instances.append(self)

    def measure(self, test_case, _show_indicator=True):
        self.test_case = test_case
        self._show_indicator = _show_indicator
        if _FakeGEval.measure_error is not None:
            raise _FakeGEval.measure_error
        self.reason = _FakeGEval.measure_reason
        return _FakeGEval.measure_score


@pytest.fixture(autouse=True)
def _reset_fake_geval(monkeypatch):
    import agentkernel.test.core.evaluator.deepeval as ak_deepeval_module

    _FakeGEval.instances = []
    _FakeGEval.measure_score = 1.0
    _FakeGEval.measure_reason = "looks correct"
    _FakeGEval.measure_error = None
    monkeypatch.setattr(ak_deepeval_module, "GEval", _FakeGEval)


def test_evaluate_by_llm_missing_expected_raises(evaluator):
    case = AKEvaluationCase(user_input="q", actual="Paris", expected=None)
    with pytest.raises(AKMissingInput):
        evaluator.evaluate_by_llm(case)
    assert _FakeGEval.instances == []  # never got as far as constructing GEval


def test_evaluate_by_llm_empty_actual_fails_without_judging(evaluator):
    # GEval hard-rejects an empty actual_output; an empty reply must come back as a scored
    # failure (so Test.compare raises its normal AssertionError), not an AKEvaluationError.
    case = AKEvaluationCase(user_input="q", actual="", expected="Paris")
    result = evaluator.evaluate_by_llm(case)
    assert result.passed is False
    assert result.score == 0.0
    assert result.metric == "g_eval"
    assert "empty" in result.reason
    assert _FakeGEval.instances == []  # no judge call was attempted


def test_evaluate_by_llm_success(evaluator):
    _FakeGEval.measure_score = 0.9
    _FakeGEval.measure_reason = "matches expected answer"
    case = AKEvaluationCase(user_input="capital of France?", actual="It's Paris.", expected="Paris")

    result = evaluator.evaluate_by_llm(case)

    assert result.metric == "g_eval"
    assert result.evaluator == "deepeval"
    assert result.score == 0.9
    assert result.reason == "matches expected answer"
    assert result.passed is True
    (fake,) = _FakeGEval.instances
    assert fake.kwargs["criteria"] is None
    assert fake.kwargs["evaluation_steps"] == _DEFAULT_LLM_EVALUATION_STEPS
    assert fake.test_case.input == "capital of France?"
    assert fake.test_case.actual_output == "It's Paris."
    assert fake.test_case.expected_output == "Paris"
    assert fake._show_indicator is False
    # Regression: the judge must see the question, or a terse-but-correct actual output
    # (e.g. "Paris" for "It's Paris.") can't be checked against the expected output in context.
    assert fake.kwargs["evaluation_params"] == [
        SingleTurnParams.INPUT,
        SingleTurnParams.ACTUAL_OUTPUT,
        SingleTurnParams.EXPECTED_OUTPUT,
    ]


def test_evaluate_by_llm_uses_case_criteria_override(evaluator):
    case = AKEvaluationCase(
        user_input="q",
        actual="a",
        expected="e",
        criteria="Score 1 only if it mentions cats.",
    )
    evaluator.evaluate_by_llm(case)
    (fake,) = _FakeGEval.instances
    assert fake.kwargs["criteria"] == "Score 1 only if it mentions cats."
    assert fake.kwargs["evaluation_steps"] is None


def test_evaluate_by_llm_passed_false_below_case_threshold(evaluator):
    _FakeGEval.measure_score = 0.4
    case = AKEvaluationCase(user_input="q", actual="a", expected="e", threshold=0.5)
    result = evaluator.evaluate_by_llm(case)
    assert result.score == 0.4
    assert result.passed is False


def test_evaluate_by_llm_wraps_measure_exception(evaluator):
    boom = RuntimeError("provider unreachable")
    _FakeGEval.measure_error = boom
    case = AKEvaluationCase(user_input="q", actual="a", expected="e")

    with pytest.raises(AKEvaluationError) as exc_info:
        evaluator.evaluate_by_llm(case)
    assert exc_info.value.__cause__ is boom


def test_llm_model_is_lazily_created_and_cached(monkeypatch, evaluator):
    import agentkernel.test.core.evaluator.deepeval as ak_deepeval_module

    created = []

    class _FakeLiteLLMModel:
        def __init__(self, model_name):
            self.model_name = model_name
            created.append(model_name)

    monkeypatch.setattr(ak_deepeval_module, "LiteLLMModel", _FakeLiteLLMModel)
    assert created == []  # never constructed by __init__

    case = AKEvaluationCase(user_input="q", actual="a", expected="e")
    evaluator.evaluate_by_llm(case)
    evaluator.evaluate_by_llm(case)

    assert created == ["openai/gpt-4o-mini"]  # constructed once, then cached
