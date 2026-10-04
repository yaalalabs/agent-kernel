"""Dedicated behavior tests for the built-in JevAKEvaluator adapter.

Fully offline: `TypeSafeClient` is replaced by a fake that records calls and returns a configurable
SystemOneResponse-shaped object. SDK exceptions are the real `typesafe_sdk` classes so the
`except TypeSafeError` scope is exercised for real. The one exception is the missing-key test, which
uses the real SDK constructor -- it raises before any request is made, so it stays offline too.
"""

from types import SimpleNamespace
from typing import Any, ClassVar

import httpx2
import pytest
from typesafe_sdk import TypeSafeAuthenticationError, TypeSafeError

from agentkernel.test.config import AKTestConfig
from agentkernel.test.core.evaluator import (
    AKEvaluationCase,
    AKEvaluationError,
    AKMetricNotSupported,
    AKMissingInput,
)
from agentkernel.test.core.evaluator.jev import (
    _DEFAULT_CRITERIA,
    _DEFAULT_INSTRUCTIONS,
    _QUESTION_ID,
    JevAKEvaluator,
)


def _response(noul: float | None = 0.9) -> Any:
    nouls = {} if noul is None else {_QUESTION_ID: SimpleNamespace(noul=noul)}
    return SimpleNamespace(
        model="jev-latest",
        usage=SimpleNamespace(input_tokens=12, output_tokens=3),
        nouls=nouls,
    )


class _FakeTypeSafeClient:
    """Stand-in for typesafe_sdk.TypeSafeClient that never touches the network."""

    instances: ClassVar[list["_FakeTypeSafeClient"]] = []
    calls: ClassVar[list[dict[str, Any]]] = []
    response: ClassVar[Any] = None
    system_one_error: ClassVar[Exception | None] = None
    init_errors: ClassVar[list[Exception]] = []  # popped one per construction attempt
    init_attempts: ClassVar[int] = 0

    def __init__(self, **kwargs):
        _FakeTypeSafeClient.init_attempts += 1
        if _FakeTypeSafeClient.init_errors:
            raise _FakeTypeSafeClient.init_errors.pop(0)
        self.kwargs = kwargs
        _FakeTypeSafeClient.instances.append(self)

    def system_one(self, state, questions, **kwargs):
        _FakeTypeSafeClient.calls.append({"state": state, "questions": questions, **kwargs})
        if _FakeTypeSafeClient.system_one_error is not None:
            raise _FakeTypeSafeClient.system_one_error
        return _FakeTypeSafeClient.response


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch):
    import agentkernel.test.core.evaluator.jev as ak_jev_module

    _FakeTypeSafeClient.instances = []
    _FakeTypeSafeClient.calls = []
    _FakeTypeSafeClient.response = _response()
    _FakeTypeSafeClient.system_one_error = None
    _FakeTypeSafeClient.init_errors = []
    _FakeTypeSafeClient.init_attempts = 0
    monkeypatch.setattr(ak_jev_module, "TypeSafeClient", _FakeTypeSafeClient)


@pytest.fixture
def evaluator():
    return JevAKEvaluator(AKTestConfig())


def _case(**overrides) -> AKEvaluationCase:
    fields = {"user_input": "capital of France?", "actual": "It's Paris.", "expected": "Paris"}
    fields.update(overrides)
    return AKEvaluationCase(**fields)


# --- evaluate_by_score --------------------------------------------------------------------#


def test_evaluate_by_score_not_supported(evaluator):
    with pytest.raises(AKMetricNotSupported, match="mode: llm"):
        evaluator.evaluate_by_score(_case())


# --- evaluate_by_llm ----------------------------------------------------------------------#


def test_evaluate_by_llm_success(evaluator):
    result = evaluator.evaluate_by_llm(_case(threshold=0.5))
    assert result.score == 0.9
    assert result.passed is True
    assert result.metric == "noul"
    assert result.evaluator == "jev"
    assert result.reason is None
    assert result.cost is None


def test_evaluate_by_llm_below_threshold_is_scored_failure(evaluator):
    _FakeTypeSafeClient.response = _response(0.2)
    result = evaluator.evaluate_by_llm(_case(threshold=0.5))
    assert result.score == 0.2
    assert result.passed is False


def test_evaluate_by_llm_score_equal_to_threshold_passes(evaluator):
    _FakeTypeSafeClient.response = _response(0.5)
    assert evaluator.evaluate_by_llm(_case(threshold=0.5)).passed is True


def test_evaluate_by_llm_metadata(evaluator):
    result = evaluator.evaluate_by_llm(_case())
    assert result.metadata == {"model": "jev-latest", "input_tokens": 12, "output_tokens": 3}


def test_evaluate_by_llm_state_and_default_question(evaluator):
    evaluator.evaluate_by_llm(_case())
    (call,) = _FakeTypeSafeClient.calls
    assert call["state"] == {
        "user_input": "capital of France?",
        "expected_output": "Paris",
        "actual_output": "It's Paris.",
    }
    assert list(call["questions"]) == [_QUESTION_ID]
    question = call["questions"][_QUESTION_ID]
    assert question.instructions == _DEFAULT_INSTRUCTIONS
    assert question.criteria == _DEFAULT_CRITERIA


def test_evaluate_by_llm_case_criteria_overrides_default_rubric(evaluator):
    evaluator.evaluate_by_llm(_case(criteria="Is the answer polite?"))
    question = _FakeTypeSafeClient.calls[0]["questions"][_QUESTION_ID]
    assert question.instructions == "Is the answer polite?"
    assert question.criteria is None


@pytest.mark.parametrize("expected", [None, ""])
def test_evaluate_by_llm_missing_expected_raises(evaluator, expected):
    with pytest.raises(AKMissingInput):
        evaluator.evaluate_by_llm(_case(expected=expected))
    assert _FakeTypeSafeClient.init_attempts == 0


def test_evaluate_by_llm_empty_actual_fails_without_judging(evaluator):
    result = evaluator.evaluate_by_llm(_case(actual=""))
    assert result.score == 0.0
    assert result.passed is False
    assert "empty" in result.reason
    assert _FakeTypeSafeClient.init_attempts == 0
    assert _FakeTypeSafeClient.calls == []


# --- error mapping ------------------------------------------------------------------------#


def test_sdk_api_error_becomes_evaluation_error(evaluator):
    error = TypeSafeAuthenticationError(401, {"error": "bad key"}, httpx2.Headers())
    _FakeTypeSafeClient.system_one_error = error
    with pytest.raises(AKEvaluationError) as excinfo:
        evaluator.evaluate_by_llm(_case())
    assert excinfo.value.__cause__ is error


def test_client_construction_error_becomes_evaluation_error_and_is_not_cached(evaluator):
    _FakeTypeSafeClient.init_errors = [TypeSafeError("No API key was provided.")]
    with pytest.raises(AKEvaluationError, match="No API key"):
        evaluator.evaluate_by_llm(_case())
    # the failure was not cached: the next call constructs again and succeeds
    assert evaluator.evaluate_by_llm(_case()).score == 0.9
    assert _FakeTypeSafeClient.init_attempts == 2


def test_non_sdk_error_propagates_unwrapped(evaluator):
    _FakeTypeSafeClient.system_one_error = RuntimeError("bug in AK")
    with pytest.raises(RuntimeError, match="bug in AK"):
        evaluator.evaluate_by_llm(_case())


def test_response_without_noul_answer_raises(evaluator):
    _FakeTypeSafeClient.response = _response(None)
    with pytest.raises(AKEvaluationError, match=_QUESTION_ID):
        evaluator.evaluate_by_llm(_case())


# --- client lifecycle ---------------------------------------------------------------------#


def test_client_not_constructed_in_init():
    JevAKEvaluator(AKTestConfig())
    assert _FakeTypeSafeClient.init_attempts == 0


def test_client_constructed_once_and_with_no_arguments(evaluator):
    evaluator.evaluate_by_llm(_case())
    evaluator.evaluate_by_llm(_case())
    (client,) = _FakeTypeSafeClient.instances
    assert client.kwargs == {}
    assert len(_FakeTypeSafeClient.calls) == 2


# --- real SDK -----------------------------------------------------------------------------#


def test_missing_api_key_with_real_sdk_raises_evaluation_error(monkeypatch):
    from typesafe_sdk import TypeSafeClient

    import agentkernel.test.core.evaluator.jev as ak_jev_module

    monkeypatch.setattr(ak_jev_module, "TypeSafeClient", TypeSafeClient)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(AKEvaluationError, match="No API key"):
        JevAKEvaluator(AKTestConfig()).evaluate_by_llm(_case())
