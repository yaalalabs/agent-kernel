import logging
from datetime import timedelta

from agentkernel.test import AKTestConfig
from agentkernel.trace import Trace

from .case import TraceCase
from .opik_evaluator import OpikTraceEvaluator
from .store import EvaluationStore

_log = logging.getLogger("ak.example.trace_evaluation")


class SessionGrader:
    """Fetches a session's traces, judges each one and stores one row per trace."""

    FETCH_WINDOW = timedelta(hours=1)

    def __init__(self):
        self._store = EvaluationStore()
        config = AKTestConfig.get()  # the judge model, from AK_TEST__LLM__*
        self._evaluators = [OpikTraceEvaluator(config, metric) for metric in OpikTraceEvaluator.METRICS]

    def grade_session(self, session_id: str) -> int:
        """Grades every trace of the session and returns how many were stored."""
        traces = Trace.get().fetch_traces(session_id=session_id, last=self.FETCH_WINDOW)
        graded = 0
        for trace in traces:
            if trace.root is None:
                _log.warning(f"trace {trace.trace_id} has no root span; skipped")
                continue
            case = TraceCase.from_trace(trace)
            evaluation_case = case.to_evaluation_case(OpikTraceEvaluator.THRESHOLD)
            results = [
                evaluator.evaluate_by_llm(evaluation_case)
                for evaluator in self._evaluators
                if evaluator.applies_to(evaluation_case)
            ]
            self._store.save_results(case, results)
            graded += 1
        _log.info(f"session {session_id}: graded {graded} of {len(traces)} traces")
        return graded
