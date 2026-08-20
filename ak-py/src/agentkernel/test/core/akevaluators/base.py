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
    context: list[str] | None = None  # carried, unpopulated in v1 (no shipped metric reads it)
    criteria: str | None = None  # carried, unpopulated in v1 (llm mode uses AK's default rubric)


class AKEvaluationResult(BaseModel):
    metric: str
    evaluator: str
    score: float | None = None  # [0.0, 1.0]; None means "not scored", never 0.0
    threshold: float | None = None  # stamped by Test.compare; unset by evaluators
    passed: bool | None = None  # stamped by Test.compare; unset by evaluators
    mode: str | None = None  # stamped by Test.compare; unset by evaluators
    expected: str | None = None  # which alternative produced this result
    reason: str | None = None
    cost: float | None = None
    attempts: list["AKEvaluationResult"] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


AKEvaluationResult.model_rebuild()


class AKEvaluator(ABC):
    """Pure scorer: computes a score, never asserts, thresholds, or decides pass/fail."""

    def __init__(self, config: "AKTestConfig") -> None:
        self._config = config

    @abstractmethod
    def score_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        """Deterministic scoring — no LLM call. Raise AKMetricNotSupported if unavailable."""

    @abstractmethod
    def llm_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        """LLM-as-judge scoring. Raise AKMetricNotSupported if unavailable."""
