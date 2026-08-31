from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agentkernel.test.config import AKTestConfig


class AKEvaluationError(Exception):
    """A configured evaluator backend failed to produce a score (missing credentials,
    transport error, unparseable judge output, ...). Never raised for a low-but-valid score."""


class AKMissingInput(Exception):
    """A field a requested metric needs was not supplied on the AKEvaluationCase."""


class AKMetricNotSupported(Exception):
    """The configured evaluator does not implement the requested evaluation method."""


class AKEvaluationCase(BaseModel):
    user_input: str
    actual: str
    expected: str | None = None
    threshold: float = 0.5  # the score/pass cutoff the evaluator must weigh its own passed against
    context: list[str] | None = None  # carried, unpopulated in v1 (no shipped metric reads it)
    criteria: str | None = None  # carried, unpopulated in v1 (llm mode uses AK's default rubric)


class AKEvaluationResult(BaseModel):
    metric: str
    evaluator: str
    score: float | None = None  # [0.0, 1.0]; None means "not scored", never 0.0
    threshold: float | None = None  # stamped by Test.compare; unset by evaluators
    passed: bool | None = None  # set by the evaluator itself, from score vs. AKEvaluationCase.threshold
    mode: str | None = None  # stamped by Test.compare; unset by evaluators
    expected: str | None = None  # which alternative produced this result
    reason: str | None = None
    cost: float | None = None
    attempts: list["AKEvaluationResult"] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


AKEvaluationResult.model_rebuild()


class AKEvaluator(ABC):
    """Computes a score and decides result.passed against AKEvaluationCase.threshold.

    Never raises AssertionError or decides whether a failure is fatal — that's Test.compare's job,
    based on the result.passed each method here returns.
    """

    def __init__(self, config: "AKTestConfig") -> None:
        self._config = config

    @abstractmethod
    def score_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        """Deterministic scoring — no LLM call. Must set result.passed. Raise AKMetricNotSupported
        if unavailable."""

    @abstractmethod
    def llm_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        """LLM-as-judge scoring. Must set result.passed. Raise AKMetricNotSupported if unavailable."""
