import os

# Before any Opik metric is built, as AK's own Opik evaluator does: nothing is sent to Opik's cloud
os.environ.setdefault("OPIK_TRACK_DISABLE", "True")

from agentkernel.test import AKEvaluationCase, AKEvaluationResult, AKEvaluator, AKMetricNotSupported, AKTestConfig
from opik.evaluation.metrics import AgentTaskCompletionJudge, AgentToolCorrectnessJudge, AnswerRelevance, Hallucination
from opik.evaluation.metrics.base_metric import BaseMetric
from opik.evaluation.metrics.score_result import ScoreResult

from .case import TraceEvaluationCase


class OpikTraceEvaluator(AKEvaluator):
    """Scores one reference-free metric of a production trace with an Opik LLM judge."""

    THRESHOLD = 0.5
    METRICS = ("task_completion", "tool_correctness", "answer_relevance", "hallucination")
    _LOWER_IS_BETTER = {"hallucination"}  # 1 means hallucinated
    _JUDGE_CLASSES: dict[str, tuple[type[BaseMetric], dict]] = {
        "task_completion": (AgentTaskCompletionJudge, {}),
        "tool_correctness": (AgentToolCorrectnessJudge, {}),
        "answer_relevance": (AnswerRelevance, {"require_context": False}),
        "hallucination": (Hallucination, {}),
    }

    def __init__(self, config: AKTestConfig, metric: str):
        super().__init__(config)
        self._metric = metric
        judge_class, judge_kwargs = self._JUDGE_CLASSES[metric]
        self._judge = judge_class(model=f"{config.llm.provider}/{config.llm.model}", track=False, **judge_kwargs)

    @property
    def higher_is_better(self) -> bool:
        """False for hallucination, where a high score is bad."""
        return self._metric not in self._LOWER_IS_BETTER

    def applies_to(self, case: TraceEvaluationCase) -> bool:
        """Whether the metric makes sense for the case: tool correctness needs at least one tool call."""
        return self._metric != "tool_correctness" or case.tool_call_count > 0

    def evaluate_by_score(self, case: AKEvaluationCase) -> AKEvaluationResult:
        """Not supported: every metric here is an LLM judge."""
        raise AKMetricNotSupported(f"{self._metric} is an LLM judge; it has no score mode")

    def evaluate_by_llm(self, case: TraceEvaluationCase) -> AKEvaluationResult:
        """Judges the case once and returns its score and verdict."""
        judge_result = self._run_judge(case)
        if judge_result.scoring_failed or judge_result.value is None:
            raise RuntimeError(f"{self._metric} judge failed: {judge_result.reason}")
        score = float(judge_result.value)
        return AKEvaluationResult(
            metric=self._metric,
            evaluator="opik",
            score=score,
            threshold=case.threshold,
            passed=score >= case.threshold if self.higher_is_better else score < case.threshold,
            mode="llm",
            reason=judge_result.reason,
            metadata={"higher_is_better": self.higher_is_better},
        )

    def _run_judge(self, case: TraceEvaluationCase) -> ScoreResult:
        """Calls the judge with the inputs its metric reads."""
        # The two agent judges take one output string, so the transcript carries the request, tools and answer
        if self._metric in ("task_completion", "tool_correctness"):
            return self._judge.score(output=case.transcript)
        if self._metric == "answer_relevance":
            return self._judge.score(input=case.user_input, output=case.actual)
        return self._judge.score(input=case.user_input, output=case.actual, context=case.context)
