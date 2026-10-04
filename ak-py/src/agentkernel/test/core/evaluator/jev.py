from threading import Lock

from typesafe_sdk import Noul, TypeSafeClient, TypeSafeError

from agentkernel.test.config import AKTestConfig

from .base import (
    AKEvaluationCase,
    AKEvaluationError,
    AKEvaluationResult,
    AKEvaluator,
    AKMetricNotSupported,
    AKMissingInput,
)

_QUESTION_ID = "conveys_expected"

_DEFAULT_INSTRUCTIONS = "Does actual_output correctly convey the information in expected_output, as an answer to user_input?"

_DEFAULT_CRITERIA = {
    "true": (
        "Every concrete fact expected_output asserts (entities, names, numbers, or other specific claims) is "
        "stated or clearly implied by actual_output, matching in substance regardless of wording, order, or "
        "length. Extra correct, non-contradictory detail in actual_output does not count against it."
    ),
    "false": (
        "actual_output omits one or more facts required by expected_output, contradicts expected_output, or "
        "asserts something that conflicts with it."
    ),
}


class JevAKEvaluator(AKEvaluator):
    """TypeSafe JEV judge. Supports ``mode: llm`` only; ``evaluate_by_score`` is not supported.

    Each comparison asks one Noul (yes/no) question and uses the returned probability as the score.

    Outbound data: every ``evaluate_by_llm`` call sends the user input, expected output and actual output
    to api.typesafe.ai. Use ``deepeval`` or ``opik`` (judged by your own LLM) for sensitive data.

    Requires ``TYPESAFE_API_KEY``; the SDK also reads ``TYPESAFE_DEFAULT_MODEL`` and ``TYPESAFE_BASE_URL``.
    """

    def __init__(self, config: AKTestConfig) -> None:
        super().__init__(config)
        self._client: TypeSafeClient | None = None  # lazy: the SDK constructor raises without TYPESAFE_API_KEY
        self._client_lock = Lock()

    def _get_client(self) -> TypeSafeClient:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    # A failed construction leaves _client as None so the next call retries.
                    self._client = TypeSafeClient()
        return self._client

    def evaluate_by_score(self, case: AKEvaluationCase) -> AKEvaluationResult:
        raise AKMetricNotSupported("evaluator 'jev' has no score-based metric; set mode: llm in test-config.yaml")

    def evaluate_by_llm(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("evaluate_by_llm requires AKEvaluationCase.expected")
        if not case.actual:
            return AKEvaluationResult(
                metric="noul",
                evaluator="jev",
                score=0.0,
                reason="actual output is empty; nothing to judge",
                passed=False,
            )
        if case.criteria:
            # The caller's rubric is the only rubric; AK's true/false descriptions could contradict it.
            question = Noul(instructions=case.criteria)
        else:
            question = Noul(instructions=_DEFAULT_INSTRUCTIONS, criteria=_DEFAULT_CRITERIA)
        state = {
            "user_input": case.user_input,
            "expected_output": case.expected,
            "actual_output": case.actual,
        }
        try:
            response = self._get_client().system_one(state=state, questions={_QUESTION_ID: question})
        except TypeSafeError as exc:
            raise AKEvaluationError(f"jev llm-based evaluation failed: {exc}") from exc
        answer = response.nouls.get(_QUESTION_ID)
        if answer is None:
            raise AKEvaluationError(f"jev response contained no noul answer for '{_QUESTION_ID}'")
        score = float(answer.noul)
        return AKEvaluationResult(
            metric="noul",
            evaluator="jev",
            score=score,
            passed=score >= case.threshold,
            metadata={
                "model": response.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )
