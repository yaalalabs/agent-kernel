import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .config import AKTestConfig
from .core.evaluator import (
    AKEvaluationCase,
    AKEvaluationError,
    AKEvaluationResult,
    AKEvaluator,
    AKMetricNotSupported,
    AKMissingInput,
)
from .test import Mode, Test
