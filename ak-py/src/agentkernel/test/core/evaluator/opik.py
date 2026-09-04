import os

# Must precede the first `opik` import anywhere in the process: this stops the SDK from writing
# traces/spans to Opik Cloud (or a self-hosted instance) by default, which would otherwise require
# an OPIK_API_KEY / `opik configure` the AK test framework never asks users to set up. setdefault,
# not an unconditional write, so a user who explicitly wants tracking is respected. `track=False`
# is also passed to each metric below as a second, explicit guard.
os.environ.setdefault("OPIK_TRACK_DISABLE", "True")

from opik.evaluation.metrics import GEval, LevenshteinRatio

from agentkernel.test.config import AKTestConfig

from .base import AKEvaluationCase, AKEvaluationError, AKEvaluationResult, AKEvaluator, AKMissingInput

_DEFAULT_TASK_INTRODUCTION = (
    "You are an expert evaluator checking whether an AI system's actual output correctly answers a "
    "user's question, judged against a known-correct expected output."
)

_DEFAULT_EVALUATION_CRITERIA = (
    "Identify the concrete facts the expected output asserts (entities, names, numbers, or other "
    "specific claims), read together with the user input.\n"
    "For each of those facts, check whether the actual output states or clearly implies it — matching "
    "in substance regardless of exact wording, phrasing, synonyms, order, or sentence structure, and "
    "regardless of whether the actual output is a full sentence or a short phrase/keyword.\n"
    "Extra correct, non-contradictory detail or specificity in the actual output beyond what the "
    "expected output states (e.g. naming a more specific type or subcategory of the same thing) must "
    "NOT be penalized — this is not a wording-similarity or length comparison.\n"
    "Score low only if the actual output omits one or more of the required facts, contradicts the "
    "expected output, or asserts something that conflicts with it."
)


class OpikAKEvaluator(AKEvaluator):
    def __init__(self, config: AKTestConfig) -> None:
        super().__init__(config)
        self._model: str | None = None  # lazy: score mode never needs it

    def _llm_model(self) -> str:
        if self._model is None:
            llm = self._config.llm
            self._model = f"{llm.provider}/{llm.model}"
        return self._model

    def evaluate_by_score(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("evaluate_by_score requires AKEvaluationCase.expected")
        metric = LevenshteinRatio(track=False)
        result = metric.score(output=case.actual, reference=case.expected)
        score = float(result.value)
        return AKEvaluationResult(
            metric="levenshtein_ratio",
            evaluator="opik",
            score=score,
            passed=score >= case.threshold,
        )

    def evaluate_by_llm(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("evaluate_by_llm requires AKEvaluationCase.expected")
        if not case.actual:
            # An empty reply can never satisfy a non-empty expected: report the scored failure so
            # Test.compare raises its normal AssertionError instead of paying for a judge call.
            return AKEvaluationResult(
                metric="g_eval",
                evaluator="opik",
                score=0.0,
                reason="actual output is empty; nothing to judge",
                passed=False,
            )
        metric = GEval(
            task_introduction=_DEFAULT_TASK_INTRODUCTION,
            evaluation_criteria=case.criteria if case.criteria else _DEFAULT_EVALUATION_CRITERIA,
            model=self._llm_model(),
            track=False,
        )
        # Opik's GEval.score() takes a single `output` string (unlike deepeval's LLMTestCase) — the
        # input/expected/actual all have to be packed into it for the judge to have anything to compare.
        formatted_output = f"User input: {case.user_input}\n\nExpected output: {case.expected}\n\nActual output: {case.actual}"
        try:
            result = metric.score(output=formatted_output)
        except Exception as exc:
            raise AKEvaluationError(f"opik g_eval llm-based evaluation failed: {exc}") from exc
        score = float(result.value) if result.value is not None else None
        return AKEvaluationResult(
            metric="g_eval",
            evaluator="opik",
            score=score,
            reason=result.reason,
            passed=score is not None and score >= case.threshold,
        )
