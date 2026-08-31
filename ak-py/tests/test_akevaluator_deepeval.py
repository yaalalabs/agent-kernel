"""Dedicated behavior tests for the built-in DeepevalAKEvaluator adapter.

score_based_evaluation is exercised against the real (offline, no-network) `Scorer` — it's pure
string normalization. llm_based_evaluation mocks `GEval` in place (no real LLM/network call) since
that's the one path that would otherwise hit a live provider.
"""

from typing import ClassVar

import pytest
from agentkernel.test.config import AKTestConfig
from agentkernel.test.core.akevaluators import (
    AKEvaluationCase,
    AKEvaluationError,
    AKMissingInput,
)
from agentkernel.test.core.akevaluators.deepeval import (
    _DEFAULT_LLM_CRITERIA,
    DeepevalAKEvaluator,
)


@pytest.fixture
def evaluator():
    return DeepevalAKEvaluator(AKTestConfig())


# --- score_based_evaluation --------------------------------------------------------------------#


def test_score_based_evaluation_exact_match(evaluator):
    case = AKEvaluationCase(
        user_input="capital of France?", actual="Paris", expected="Paris"
    )
    result = evaluator.score_based_evaluation(case)
    assert result.score == 1.0
    assert result.metric == "quasi_exact_match"
    assert result.evaluator == "deepeval"
    assert result.passed is True


def test_score_based_evaluation_mismatch(evaluator):
    case = AKEvaluationCase(
        user_input="capital of France?", actual="London", expected="Paris"
    )
    result = evaluator.score_based_evaluation(case)
    assert result.score == 0.0
    assert result.passed is False


def test_score_based_evaluation_passed_uses_case_threshold(evaluator):
    case = AKEvaluationCase(
        user_input="capital of France?", actual="London", expected="Paris", threshold=0.0
    )
    result = evaluator.score_based_evaluation(case)
    assert result.score == 0.0
    assert result.passed is True  # 0.0 >= the case's own threshold of 0.0


def test_score_based_evaluation_normalizes_whitespace_and_case(evaluator):
    case = AKEvaluationCase(user_input="q", actual="  PARIS  ", expected="paris")
    result = evaluator.score_based_evaluation(case)
    assert result.score == 1.0


def test_score_based_evaluation_missing_expected_raises(evaluator):
    case = AKEvaluationCase(user_input="q", actual="Paris", expected=None)
    with pytest.raises(AKMissingInput):
        evaluator.score_based_evaluation(case)


# --- llm_based_evaluation -----------------------------------------------------------------------#


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
    import agentkernel.test.core.akevaluators.deepeval as ak_deepeval_module

    _FakeGEval.instances = []
    _FakeGEval.measure_score = 1.0
    _FakeGEval.measure_reason = "looks correct"
    _FakeGEval.measure_error = None
    monkeypatch.setattr(ak_deepeval_module, "GEval", _FakeGEval)


def test_llm_based_evaluation_missing_expected_raises(evaluator):
    case = AKEvaluationCase(user_input="q", actual="Paris", expected=None)
    with pytest.raises(AKMissingInput):
        evaluator.llm_based_evaluation(case)
    assert _FakeGEval.instances == []  # never got as far as constructing GEval


def test_llm_based_evaluation_success(evaluator):
    _FakeGEval.measure_score = 0.9
    _FakeGEval.measure_reason = "matches expected answer"
    case = AKEvaluationCase(
        user_input="capital of France?", actual="It's Paris.", expected="Paris"
    )

    result = evaluator.llm_based_evaluation(case)

    assert result.metric == "g_eval"
    assert result.evaluator == "deepeval"
    assert result.score == 0.9
    assert result.reason == "matches expected answer"
    assert result.passed is True
    (fake,) = _FakeGEval.instances
    assert fake.kwargs["criteria"] == _DEFAULT_LLM_CRITERIA
    assert fake.test_case.input == "capital of France?"
    assert fake.test_case.actual_output == "It's Paris."
    assert fake.test_case.expected_output == "Paris"
    assert fake._show_indicator is False


def test_llm_based_evaluation_uses_case_criteria_override(evaluator):
    case = AKEvaluationCase(
        user_input="q",
        actual="a",
        expected="e",
        criteria="Score 1 only if it mentions cats.",
    )
    evaluator.llm_based_evaluation(case)
    (fake,) = _FakeGEval.instances
    assert fake.kwargs["criteria"] == "Score 1 only if it mentions cats."


def test_llm_based_evaluation_passed_false_below_case_threshold(evaluator):
    _FakeGEval.measure_score = 0.4
    case = AKEvaluationCase(user_input="q", actual="a", expected="e", threshold=0.5)
    result = evaluator.llm_based_evaluation(case)
    assert result.score == 0.4
    assert result.passed is False


def test_llm_based_evaluation_wraps_measure_exception(evaluator):
    boom = RuntimeError("provider unreachable")
    _FakeGEval.measure_error = boom
    case = AKEvaluationCase(user_input="q", actual="a", expected="e")

    with pytest.raises(AKEvaluationError) as exc_info:
        evaluator.llm_based_evaluation(case)
    assert exc_info.value.__cause__ is boom


def test_llm_model_is_lazily_created_and_cached(monkeypatch, evaluator):
    import agentkernel.test.core.akevaluators.deepeval as ak_deepeval_module

    created = []

    class _FakeLiteLLMModel:
        def __init__(self, model_name):
            self.model_name = model_name
            created.append(model_name)

    monkeypatch.setattr(ak_deepeval_module, "LiteLLMModel", _FakeLiteLLMModel)
    assert created == []  # never constructed by __init__

    case = AKEvaluationCase(user_input="q", actual="a", expected="e")
    evaluator.llm_based_evaluation(case)
    evaluator.llm_based_evaluation(case)

    assert created == ["openai/gpt-4o-mini"]  # constructed once, then cached
