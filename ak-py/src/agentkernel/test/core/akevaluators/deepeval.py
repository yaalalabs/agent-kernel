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

_DEFAULT_LLM_CRITERIA = (
    "Given the input question, determine whether the actual output correctly conveys the information in "
    "the expected output. The actual output may be a short phrase, fact, or keyword rather than a full "
    "sentence — score it as correct if, read together with the input, it clearly states or implies the "
    "information in the expected output, even when it also includes additional context, explanation, or "
    "detail beyond it. Do not penalize the actual output merely for being shorter, longer, or more or less "
    "detailed than the expected output, as long as the information conveyed is correct. When the expected "
    "output is a list or combination of facts (e.g. multiple names, items, or entities), the actual output "
    "is correct as long as it conveys the same set of facts — the order in which they are listed, the "
    "wording used to introduce them, and the grammatical structure of the sentence do not matter."
)


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
            criteria=case.criteria or _DEFAULT_LLM_CRITERIA,
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
