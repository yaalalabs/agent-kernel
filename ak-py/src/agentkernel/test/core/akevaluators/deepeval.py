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

_DEFAULT_LLM_CRITERIA = "Determine whether the actual output conveys the same information as the expected output."


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
        score = Scorer.quasi_exact_match_score(target=case.expected, prediction=case.actual)
        return AKEvaluationResult(metric="quasi_exact_match", evaluator="deepeval", score=float(score))

    def llm_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("llm_based_evaluation requires AKEvaluationCase.expected")
        metric = GEval(
            name="Correctness",
            criteria=case.criteria or _DEFAULT_LLM_CRITERIA,
            evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
            model=self._llm_model(),
            threshold=None,
        )
        test_case = LLMTestCase(input=case.user_input, actual_output=case.actual, expected_output=case.expected)
        try:
            score = metric.measure(test_case, _show_indicator=False)
        except Exception as exc:
            raise AKEvaluationError(f"llm-based (GEval) evaluation failed: {exc}") from exc
        return AKEvaluationResult(metric="g_eval", evaluator="deepeval", score=score, reason=metric.reason)
