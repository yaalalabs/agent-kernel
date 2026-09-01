import os

# Must precede the first `deepeval` import anywhere in the process: DeepEval reads this at
# import time (deepeval/telemetry/__init__.py's module-level _migrate_project_files() call).
# setdefault, not an unconditional write, so a user who explicitly opts in is respected.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")

from deepeval.metrics import GEval
from deepeval.models.llms.litellm_model import LiteLLMModel
from deepeval.scorer import Scorer
from deepeval.test_case import LLMTestCase, SingleTurnParams  # not the deprecated LLMTestCaseParams

from agentkernel.test.config import AKTestConfig

from .base import AKEvaluationCase, AKEvaluationError, AKEvaluationResult, AKEvaluator, AKMissingInput

_DEFAULT_LLM_EVALUATION_STEPS = [
    "Identify the concrete facts the expected output asserts (entities, names, numbers, or other "
    "specific claims), read together with the input question.",
    "For each of those facts, check whether the actual output states or clearly implies it — matching "
    "in substance regardless of exact wording, phrasing, synonyms, order, or sentence structure, and "
    "regardless of whether the actual output is a full sentence or a short phrase/keyword.",
    "Extra correct, non-contradictory detail or specificity in the actual output beyond what the "
    "expected output states (e.g. naming a more specific type or subcategory of the same thing) must "
    "NOT be penalized — this is not a wording-similarity or length comparison.",
    "Score low only if the actual output omits one or more of the required facts, contradicts the "
    "expected output, or asserts something that conflicts with it.",
]


class DeepevalAKEvaluator(AKEvaluator):
    def __init__(self, config: AKTestConfig) -> None:
        super().__init__(config)
        self._model: LiteLLMModel | None = None  # lazy: score mode never needs it

    def _llm_model(self) -> LiteLLMModel:
        if self._model is None:
            llm = self._config.llm
            self._model = LiteLLMModel(f"{llm.provider}/{llm.model}")
        return self._model

    def score_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("score_based_evaluation requires AKEvaluationCase.expected")
        score = float(Scorer.quasi_exact_match_score(target=case.expected, prediction=case.actual))
        return AKEvaluationResult(
            metric="quasi_exact_match",
            evaluator="deepeval",
            score=score,
            passed=score >= case.threshold,
        )

    def llm_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("llm_based_evaluation requires AKEvaluationCase.expected")
        metric = GEval(
            name="Correctness",
            criteria=case.criteria if case.criteria else None,
            evaluation_steps=None if case.criteria else _DEFAULT_LLM_EVALUATION_STEPS,
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            model=self._llm_model(),
            threshold=None,
        )
        test_case = LLMTestCase(input=case.user_input, actual_output=case.actual, expected_output=case.expected)
        try:
            score = metric.measure(test_case, _show_indicator=False)
        except Exception as exc:
            raise AKEvaluationError(f"llm-based (GEval) evaluation failed: {exc}") from exc
        return AKEvaluationResult(
            metric="g_eval",
            evaluator="deepeval",
            score=score,
            reason=metric.reason,
            passed=score is not None and score >= case.threshold,
        )
