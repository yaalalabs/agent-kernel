import logging
import os

# Before any Opik metric is built, as AK's own Opik evaluator does: nothing is sent to Opik's cloud
os.environ.setdefault("OPIK_TRACK_DISABLE", "True")

from agentkernel.test import AKEvaluationCase, AKEvaluationResult, AKEvaluator, AKMetricNotSupported, AKTestConfig
from opik.evaluation.metrics import AgentTaskCompletionJudge, AgentToolCorrectnessJudge, AnswerRelevance, Hallucination
from opik.evaluation.metrics.base_metric import BaseMetric
from opik.evaluation.metrics.score_result import ScoreResult

from .case import TraceEvaluationCase

_log = logging.getLogger("ak.example.trace_evaluation")


class OpikTraceEvaluator(AKEvaluator):
    """Scores one reference-free metric of a production trace with an Opik LLM judge."""

    THRESHOLD = 0.5
    MAX_ATTEMPTS = 2
    METRICS = ("task_completion", "tool_correctness", "answer_relevance", "hallucination")
    _LOWER_IS_BETTER = {"hallucination"}  # 1 means hallucinated
    _JUDGE_CLASSES: dict[str, tuple[type[BaseMetric], dict]] = {
        "task_completion": (AgentTaskCompletionJudge, {}),
        "tool_correctness": (AgentToolCorrectnessJudge, {}),
        "answer_relevance": (AnswerRelevance, {"require_context": False}),
        "hallucination": (Hallucination, {}),
    }

    def __init__(self, config: AKTestConfig, metric: str):
        if metric not in self.METRICS:
            raise ValueError(f"unknown metric {metric!r}; expected one of {', '.join(self.METRICS)}")
        super().__init__(config)
        self._metric = metric
        self._judge_model = f"{config.llm.provider}/{config.llm.model}"
        self._judge: BaseMetric | None = None

    @classmethod
    def for_all_metrics(cls, config: AKTestConfig) -> list["OpikTraceEvaluator"]:
        """Builds one evaluator per metric in METRICS."""
        return [cls(config, metric) for metric in cls.METRICS]

    @property
    def metric(self) -> str:
        """The metric this evaluator scores."""
        return self._metric

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

    def evaluate_by_llm(self, case: AKEvaluationCase) -> AKEvaluationResult:
        """Judges the case, trying twice; a second failure becomes an unscored result, never an exception."""
        last_error = ""
        attempts = 0
        judge_result: ScoreResult | None = None
        while attempts < self.MAX_ATTEMPTS:
            attempts += 1
            try:
                score_result = self._run_judge(case)
            except Exception as e:  # Opik and litellm raise many unrelated types; one bad metric never fails the run
                last_error = f"{type(e).__name__}: {e}"
                _log.warning(f"{self._metric} attempt {attempts} failed: {last_error}")
                continue
            if score_result.scoring_failed or score_result.value is None:
                last_error = score_result.reason or "scoring failed"
                _log.warning(f"{self._metric} attempt {attempts} failed: {last_error}")
                continue
            judge_result = score_result
            break

        metadata = {
            "higher_is_better": self.higher_is_better,
            "opik_metric": self._JUDGE_CLASSES[self._metric][0].__name__,
            "attempts": attempts,
        }
        if judge_result is None:
            return AKEvaluationResult(
                metric=self._metric,
                evaluator="opik",
                threshold=case.threshold,
                mode="llm",
                reason=f"{self._metric} failed after {attempts} attempts: {last_error}",
                metadata=metadata,
            )
        score = float(judge_result.value)
        passed = score >= case.threshold if self.higher_is_better else score < case.threshold
        return AKEvaluationResult(
            metric=self._metric,
            evaluator="opik",
            score=score,
            threshold=case.threshold,
            passed=passed,
            mode="llm",
            reason=judge_result.reason,
            metadata=metadata,
        )

    def _build_judge(self) -> BaseMetric:
        """Builds this metric's Opik judge on first use and reuses it after."""
        if self._judge is None:
            judge_class, judge_kwargs = self._JUDGE_CLASSES[self._metric]
            self._judge = judge_class(model=self._judge_model, track=False, **judge_kwargs)
        return self._judge

    def _run_judge(self, case: TraceEvaluationCase) -> ScoreResult:
        """Calls the judge once, with the inputs its metric reads."""
        judge = self._build_judge()
        # The two agent judges take one output string, so the transcript carries the request, tools and answer
        if self._metric in ("task_completion", "tool_correctness"):
            return judge.score(output=case.transcript)
        if self._metric == "answer_relevance":
            return judge.score(input=case.user_input, output=case.actual)
        return judge.score(input=case.user_input, output=case.actual, context=case.context)
