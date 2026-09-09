# #555: Replace RAGAS with a pluggable `AKEvaluator` (DeepEval), rename test modes, add `return_metrics` — Implementation Spec

Implements the requirements in [`design.md`](design.md): a pluggable `AKEvaluator` interface under a new
`test/core/akevaluators/` package, a `DeepevalAKEvaluator` built-in, renamed comparison modes
(`fuzzy`/`judge` → `score`/`llm`), a `return_metrics` opt-in on `Test.compare`/`Test.expect`, and the
[0.0, 1.0] threshold scale. This document covers the "how": exact module layout, interface code, the
`Test.compare` algorithm, the config diff, and the full migration/testing surface. The score metric
went through two corrections while detailing this spec, landing on `Scorer.quasi_exact_match_score` —
see "Score metric" below and the corresponding `design.md` edits.

## Verification performed for this spec

Everything design.md's placeholder deferred to this stage was checked against the installed package
(both `deepeval==4.1.4`, the minimum pin, and `4.1.8`, the current release, in an isolated venv — not
against memory or the docs site):

1. **Score metric — two design-level corrections, not a confirmation.** `deepeval.scorer.
   Scorer.quasi_contains_score(targets, prediction)` (`scorer/scorer.py:119-124`, unchanged between
   `4.1.4` and `4.1.8`) is `1 if normalize_text(prediction) in normalized_targets else 0` — Python
   list-membership *equality*, not substring containment, regardless of which AK argument maps to which
   parameter. Its only other caller in the package is the DROP benchmark's multiple-gold-answer exact
   match. This was first corrected (in an earlier pass of this document) to `deepeval.metrics.
   PatternMatchMetric` — a ready-made, non-LLM `BaseMetric` matched against a normalised, wildcard-wrapped
   pattern, verified empirically across four cases (containment, case-only match, non-match, article/
   punctuation normalisation) via `PatternMatchMetric.measure()`.

   That choice is corrected a second time here, to `Scorer.quasi_exact_match_score(target, prediction)`
   (`scorer/scorer.py:114-117`) — `1 if normalize_text(target) == normalize_text(prediction) else 0`,
   the same normalisation as `quasi_contains_score` but whole-string equality instead of containment. No
   regex, no `BaseMetric`, no `LLMTestCase` on the score path at all: a plain classmethod call over
   `case.expected`/`case.actual`. This is a deliberate trade, not a refinement — verified empirically
   against `deepeval` 4.1.8 with the same four cases plus one more:
   | case | target | prediction | `quasi_exact_match_score` |
   |---|---|---|---|
   | exact short match | `"Paris"` | `"Paris"` | `1` |
   | case-only match | `"paris"` | `"PARIS"` | `1` |
   | article/punctuation normalisation | `"the Paris."` | `"Paris"` | `1` |
   | non-match | `"Paris"` | `"The capital of Germany is Berlin."` | `0` |
   | **verbose correct answer** | `"Paris"` | `"...the capital of France is Paris, a beautiful city."` | **`0`** |

   The last row is the cost: `PatternMatchMetric` would score that row `1.0` (containment), so
   `quasi_exact_match_score` gives up matching a short `expected` phrase embedded in a longer correct
   `actual` response. `Scorer.rouge_score`/`sentence_bleu_score` were also considered for graded partial
   credit and rejected: both require an additional package `deepeval` does not itself depend on
   (`rouge-score` pulls in `nltk`, `numpy`, and `absl-py`, confirmed via `uv pip show rouge-score` in an
   isolated venv), and both are F-measure-based, which empirically scores the same verbose-correct-answer
   row at `0.11`–`0.15` — still failing any reasonable threshold, without the offsetting benefit of adding
   zero dependencies. `quasi_exact_match_score` is therefore the final choice: no new dependency, no
   `BaseMetric`/regex/`LLMTestCase` machinery on the score path, at the cost of losing containment.
2. **`USE_LITELLM` — not required.** `deepeval.metrics.utils.initialize_model()` (`metrics/utils.py:674-699`)
   returns immediately when `model` is already a `DeepEvalBaseLLM` instance (`isinstance(model,
   DeepEvalBaseLLM)`, line 684); `should_use_litellm()` (which reads `USE_LITELLM`) is only consulted
   when `model` is a bare string or `None`. AK always constructs and passes a `LiteLLMModel` instance, so
   this path is never reached. `LiteLLMModel` (`models/llms/litellm_model.py`) is a
   `DeepEvalBaseGatewayModel`, itself a `DeepEvalBaseLLM` subclass.
3. **`GEval` requires schema-constrained JSON from the judge — confirmed, with the failure mode.**
   `BaseModel.generate_with_schema` (`models/base_model.py:125-131`) calls `self.generate(..., schema=schema)`;
   `LiteLLMModel._generate`/`_a_generate` pass `response_format=schema` straight to
   `litellm.completion`/`acompletion`. If the provider/model rejects or ignores `response_format`, the
   failure surfaces as a `litellm` exception at evaluate time (verified: the fallback in
   `generate_with_schema` only catches `TypeError`, which a provider-side rejection is not) — never at
   evaluator-construction time. Empirically verified end-to-end: a full `GEval.measure()` run (steps
   generation + evaluation, two schema-constrained calls) against a mocked `litellm.completion`/
   `acompletion` returning valid JSON produces a correct score, and `threshold=None` → `is_successful()
   == None` with no `TypeError` (confirms the `>=4.1.4` pin: `is_successful()` in `base_metric.py:93-103`
   already guards `threshold is None`).
4. **Telemetry opt-out timing and `.deepeval/` creation — confirmed, and better than design.md assumed.**
   `deepeval.telemetry._migrate_project_files()` (`telemetry/__init__.py:86-101`) runs at import time of
   `deepeval.telemetry` (which `deepeval/__init__.py` imports) and early-returns when
   `telemetry_opt_out()` is true, **before** its `os.makedirs(HIDDEN_DIR, exist_ok=True)` call. Verified
   empirically: with `DEEPEVAL_TELEMETRY_OPT_OUT=1` set before the first `deepeval` import, a full mocked
   `GEval.measure()` run leaves the CWD and a fake `$HOME` both clean of `.deepeval/` afterward. Separately,
   in this pinned range the anonymous-identity file has *also* moved to `~/.deepeval` (or `$DEEPEVAL_HOME`)
   by default (`telemetry/identity.py:35-39`) — it no longer defaults into the repository at all; the
   old CWD-relative path is now read only for one-time migration.
5. **Path override for any DeepEval-created directory — confirmed.** `HIDDEN_DIR` (`constants.py:6`) is
   `os.getenv("DEEPEVAL_CACHE_FOLDER", ".deepeval")`, read at import time, so setting
   `DEEPEVAL_CACHE_FOLDER` before import moves it. `DEEPEVAL_HOME` moves the telemetry identity file
   (`identity.py:35-37`). Neither override is needed by AK given point 4, but both exist should a future
   DeepEval release change the opt-out early-return.

## Design

### Package layout

```
ak-py/src/agentkernel/test/
├── __init__.py                    # unchanged: exports AKTestConfig, Mode, Test
├── config.py                      # +evaluator field, judge→llm rename, legacy-key rejection
├── test.py                        # Mode renamed; Test rewritten to dispatch through AKEvaluator
└── core/
    ├── __init__.py                # empty — marks the package
    └── akevaluators/
        ├── __init__.py            # re-exports: AKEvaluator, AKEvaluationCase, AKEvaluationResult,
        │                          #   AKEvaluationError, AKMissingInput, AKMetricNotSupported
        ├── base.py                # AKEvaluator ABC, the two payload models, the three error classes
        └── deepeval.py             # DeepevalAKEvaluator (only module that imports `deepeval`)
```

No `factory.py` in this package (design.md "No `AKEvaluatorFactory` class is added anywhere") —
resolution is `Test._resolve_evaluator`, detailed below.

### `test/core/akevaluators/base.py`

```python
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
    threshold: float = 0.5             # the score/pass cutoff the evaluator must weigh its own passed against
    context: list[str] | None = None   # carried, unpopulated in v1 (no shipped metric reads it)
    criteria: str | None = None        # carried, unpopulated in v1 (llm mode uses AK's default rubric)


class AKEvaluationResult(BaseModel):
    metric: str
    evaluator: str
    score: float | None = None         # [0.0, 1.0]; None means "not scored", never 0.0
    threshold: float | None = None     # stamped by Test.compare; unset by evaluators
    passed: bool | None = None         # set by the evaluator itself, from score vs. AKEvaluationCase.threshold
    mode: str | None = None            # stamped by Test.compare; unset by evaluators
    expected: str | None = None        # which alternative produced this result
    reason: str | None = None
    cost: float | None = None
    attempts: list["AKEvaluationResult"] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
```

`AKEvaluationResult.attempts` is `list["AKEvaluationResult"]` (self-referential) — needs
`AKEvaluationResult.model_rebuild()` at the end of `base.py` (pydantic v2 requirement for a
self-referencing model defined without `from __future__ import annotations` complications); confirm
in implementation whether the string literal alone resolves without it under this repo's pydantic
version — if not, add the explicit `model_rebuild()` call.

### `test/core/akevaluators/__init__.py`

```python
from .base import (
    AKEvaluationCase,
    AKEvaluationError,
    AKEvaluationResult,
    AKEvaluator,
    AKMetricNotSupported,
    AKMissingInput,
)

__all__ = [
    "AKEvaluationCase",
    "AKEvaluationError",
    "AKEvaluationResult",
    "AKEvaluator",
    "AKMetricNotSupported",
    "AKMissingInput",
]
```

Pure Python, no `deepeval` import — `test/test.py` imports from this module at module level (design.md
"Harness changes" requirement that importing `agentkernel.test` never requires `deepeval`).

### `test/core/akevaluators/deepeval.py`

```python
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
    "Determine whether the actual output correctly conveys the information in the expected output. "
    "The expected output may be a short phrase, fact, or keyword rather than a full sentence — score "
    "the actual output as correct if it clearly states or implies that information, even when it also "
    "includes additional context, explanation, or detail beyond it. Do not penalize the actual output "
    "merely for being longer or more detailed than the expected output."
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
            evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
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
```

Notes on this sketch (rules, not implementation detail to skip):

0. **The module's own filename, `deepeval.py`, does not shadow the third-party `deepeval` package it
   imports from.** Python 3 has no implicit relative imports: `from deepeval.metrics import ...` inside
   `agentkernel/test/core/akevaluators/deepeval.py` resolves `deepeval` via `sys.path` (the installed
   package), never via this module's own name or its package (`agentkernel.test.core.akevaluators`) —
   the two are different fully-qualified names (`deepeval` vs.
   `agentkernel.test.core.akevaluators.deepeval`). Verified empirically: importing this module and
   asserting `agentkernel.test.core.akevaluators.deepeval.GEval is deepeval.metrics.GEval` is included in
   the test suite (see "Testing") so a future accidental relative-import (`from . import deepeval` or a
   bare `import deepeval` misresolving) is caught immediately rather than surfacing as a subtle bug.
1. **`score_based_evaluation` builds no object and calls no normalisation itself.**
   `Scorer.quasi_exact_match_score` is a stateless classmethod that normalises both its `target` and
   `prediction` arguments internally (`deepeval.utils.normalize_text` — case, punctuation, article,
   whitespace); `case.expected`/`case.actual` are passed through unmodified. There is no regex, no
   `PatternMatchMetric`/`BaseMetric`, and no `LLMTestCase` on this path at all — `LLMTestCase` is
   constructed only in `llm_based_evaluation`, since `GEval` needs one.
2. **The score path returns a plain `int` (0 or 1), cast to `float` for `AKEvaluationResult.score`.**
   `Scorer.quasi_exact_match_score` returns `int`; `AKEvaluationResult.score` is typed `float | None`
   (design.md), so the cast is required, not stylistic.
2a. **Both methods set `result.passed` themselves**, comparing the score they just computed against
   `case.threshold` (`score >= case.threshold`, or `score is not None and score >= case.threshold` on
   the llm path since `metric.measure` can leave `score` unset on a soft failure). Neither method reads
   `case.threshold` for any other purpose — no other AK-side thresholding happens in this file.
2b. **`_DEFAULT_LLM_CRITERIA` is directional, not a symmetric-equivalence rubric.** It explicitly tells
   the judge that `expected` "may be a short phrase, fact, or keyword rather than a full sentence" and to
   score `actual` as correct "even when it also includes additional context ... beyond it," and "not [to]
   penalize the actual output merely for being longer or more detailed." This wording exists specifically
   to keep a verbose-but-correct `actual` from failing `llm`/`fallback` after `score` mode gave up
   containment — see design.md's "Consequence for callers, revised."
3. **`self._model` is per-`DeepevalAKEvaluator`-instance lazy state**, built on first `llm_based_evaluation`
   call and reused for the evaluator's lifetime (which is the cached singleton's lifetime — see
   `Test._resolve_evaluator` below). This is the "one instance owns its own backend clients" requirement
   from design.md's "Evaluator interface" section. Score mode never touches `self._model` — it is
   entirely local, string-only, and needs no LLM.
4. **`score_based_evaluation` has no try/except and cannot raise `AKEvaluationError`.**
   `Scorer.quasi_exact_match_score(target: str, prediction: str) -> int` is a pure string comparison
   over two required, non-`None` `str` fields (`AKEvaluationCase.actual` is required; `case.expected` is
   guarded by the `AKMissingInput` check above it) — there is no I/O, no model call, and no failure mode
   to translate. This deliberately differs from `llm_based_evaluation` below, which wraps every
   `metric.measure()` failure: **every failure from `GEval.measure()` becomes `AKEvaluationError`.** This
   includes the litellm exception from point 3 of "Verification performed" (bad/missing API key, a judge
   model that rejects `response_format`), and any `deepeval`-internal error (e.g. an unparseable judge
   response after `trimAndLoadJson` gives up). No soft-failure branch — `deepeval.metrics.BaseMetric.
   measure()` either returns a score or raises; there is no `metric.error`-without-raising path to
   translate, unlike RAGAS's `evaluate()` batch mode, which is what motivated the "translate soft
   failure" note in `design.md`.

### `test/core/akevaluators/__init__.py` vs `deepeval.py` import boundary

`agentkernel.test` → `test.py` imports `from .core.akevaluators import AKEvaluator, AKEvaluationCase,
AKEvaluationResult` at module level (pure Python). `deepeval.py` is imported **only** inside
`Test._resolve_evaluator`'s `deepeval` branch, inside a `require_extra` block. `import agentkernel.test`
therefore never imports `deepeval`, matching design.md's requirement and enabling the offline test suite
(see "Testing").

### Configuration (`test/config.py`)

Full diff against the current file (`ak-py/src/agentkernel/test/config.py`):

```python
from threading import RLock
from typing import ClassVar, Optional

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import SettingsConfigDict

from agentkernel.core.util.config_yaml_util import YamlBaseSettingsModified
from agentkernel.core.util.factory import AKConfigError


class _LlmConfig(BaseModel):                                    # renamed from _JudgeConfig
    model: str = Field(default="gpt-4o-mini", description="LLM Model name")
    provider: str = Field(default="openai", description="LLM Provider name")
    embedding_model: str = Field(default="text-embedding-3-small", description="Embedding Model name")
    # embedding_model kept though unconsumed by any v1 metric — see design.md "Configuration"


class AKTestConfig(YamlBaseSettingsModified):
    yaml_file_env_var: ClassVar[str] = "AK_TEST_CONFIG_PATH_OVERRIDE"
    yaml_file_default: ClassVar[str] = "test-config.yaml"
    warn_if_missing: ClassVar[bool] = False

    _instance: ClassVar[Optional["AKTestConfig"]] = None
    _instance_lock: ClassVar[RLock] = RLock()

    mode: str = Field(default="fallback", pattern="^(fallback|llm|score)$")
    evaluator: str = Field(
        default="deepeval",
        description="Built-in evaluator short name ('deepeval') or a dotted path to an AKEvaluator subclass",
    )
    llm: _LlmConfig = Field(description="LLM configuration for the llm evaluation mode", default_factory=_LlmConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_prefix="AK_TEST__",
        extra="ignore",
        env_ignore_empty=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_judge_key(cls, data: object) -> object:
        # extra="ignore" would otherwise silently drop a leftover `judge:` block (YAML or
        # AK_TEST__JUDGE__*) and revert to llm's defaults with no error. This validator sees the
        # fully-merged dict (YAML + env + init sources) before that drop happens.
        if isinstance(data, dict) and "judge" in data:
            raise AKConfigError("test-config.yaml: 'judge' was renamed to 'llm' in #555 — update the key, not an alias")
        return data

    @classmethod
    def get(cls) -> "AKTestConfig": ...  # unchanged
    @classmethod
    def _reset(cls): ...                 # unchanged
```

Notes:

- `evaluator` has **no** `pattern` (plain `str`), unlike `mode`: the built-in set is checked in
  `Test._resolve_evaluator`, and a dotted path can't be expressed as a regex (design.md "Configuration").
- **Reversed from an earlier pass of this spec**: the real `ak-py/src/agentkernel/test/config.py` has no
  `_reject_legacy_judge_key` validator, no `model_validator` import, and no `AKConfigError` import at all
  — `judge`/`AK_TEST__JUDGE__*` is silently dropped by `extra="ignore"` and `AKTestConfig` reverts to
  `llm`'s defaults with no error, the exact failure mode this validator existed to prevent. Tested
  explicitly as intentional:
  `ak-py/tests/test_test_config.py::test_legacy_judge_key_in_yaml_is_silently_ignored` ("No special-cased
  rejection: a leftover `judge:` block is just an unknown key under `extra=\"ignore\"`"). Two things this
  reversal leaves stale and **out of this spec folder's scope to fix here**: at least one shipped example
  (`examples/aws-serverless/schedule-openai/test-config.yaml`) still has a top-level `judge:` block that
  is now silently ignored rather than erroring, and `docs/docs/core-concepts/configuration.md` still
  documents the rejected version of this behaviour as shipped.
- Env var spellings: `AK_TEST__EVALUATOR`, `AK_TEST__LLM__MODEL`, `AK_TEST__LLM__PROVIDER`,
  `AK_TEST__LLM__EMBEDDING_MODEL`. `AK_TEST__JUDGE__*` is not rejected either, for the same reason.

### `Test._resolve_evaluator` (`test/test.py`)

```python
from threading import RLock

from agentkernel.core.util.factory import AKConfigError, require_extra, resolve_dotted

from .core.akevaluators import AKEvaluationCase, AKEvaluationResult, AKEvaluator
from .config import AKTestConfig

_BUILTIN_EVALUATORS = ["deepeval"]


class Test:
    ...
    _evaluator: ClassVar[tuple[str, AKEvaluator] | None] = None
    _evaluator_lock: ClassVar[RLock] = RLock()

    @classmethod
    def _resolve_evaluator(cls) -> AKEvaluator:
        configured = AKTestConfig.get().evaluator
        cached = cls._evaluator
        if cached is not None and cached[0] == configured:
            return cached[1]
        with cls._evaluator_lock:
            cached = cls._evaluator
            if cached is not None and cached[0] == configured:
                return cached[1]
            evaluator_cls = cls._resolve_evaluator_class(configured)
            instance = evaluator_cls(AKTestConfig.get())
            cls._evaluator = (configured, instance)
            return instance

    @classmethod
    def _resolve_evaluator_class(cls, configured: str) -> type[AKEvaluator]:
        if configured == "deepeval":
            with require_extra("test", "evaluator: deepeval"):
                from .core.akevaluators.deepeval import DeepevalAKEvaluator
            return DeepevalAKEvaluator
        if "." not in configured:
            raise AKConfigError(
                f"unknown evaluator '{configured}'; expected one of {_BUILTIN_EVALUATORS} or a dotted path to an AKEvaluator subclass"
            )
        return resolve_dotted(configured, base=AKEvaluator)

    @classmethod
    def _reset_evaluator(cls) -> None:
        cls._evaluator = None
```

This is the #541 house pattern (`InputGuardrailFactory`, `SandboxProviderFactory`), reused verbatim per
design.md, located on `Test` rather than a separate factory module. `require_extra("test", ...)` names the
`test` extra because `deepeval` ships as a dependency of `agentkernel[test]` (see "Dependencies" below), the
same extra pattern `require_extra` callers use elsewhere (e.g. `require_extra("langfuse", ...)`,
`require_extra("aws", ...)` in `guardrail.py`).

### `Test.compare` (`test/test.py`)

```python
class Mode(StrEnum):
    SCORE = "score"
    LLM = "llm"
    FALLBACK = "fallback"


class Test:
    match_threshold: float = 0.5   # was 50

    def __init__(self, path, match_threshold: float = 0.5, mode: Mode = None): ...  # was 50

    @staticmethod
    def compare(
        actual: str,
        expected: list[str] = None,
        user_input: str = "",
        threshold: float = 0.5,          # was 50 (0-100 scale)
        mode: Mode = None,
        return_metrics: bool = False,
    ) -> AKEvaluationResult | None:
        if mode is not None and mode not in (Mode.SCORE, Mode.LLM, Mode.FALLBACK):
            raise ValueError(f"Invalid mode: {mode}. Must be one of: {Mode.SCORE}, {Mode.LLM}, {Mode.FALLBACK}")
        if not expected:
            raise ValueError("Expected strings list cannot be empty for comparison.")

        selected_mode = mode or Mode(AKTestConfig.get().mode)
        evaluator = Test._resolve_evaluator()

        attempts: list[AKEvaluationResult] = []
        decisive: AKEvaluationResult | None = None

        for exp in expected:
            case = AKEvaluationCase(user_input=user_input, actual=actual, expected=exp, threshold=threshold)

            if selected_mode == Mode.SCORE:
                result, result_mode = evaluator.score_based_evaluation(case), Mode.SCORE
            elif selected_mode == Mode.LLM:
                result, result_mode = evaluator.llm_based_evaluation(case), Mode.LLM
            else:  # FALLBACK
                score_result = evaluator.score_based_evaluation(case)
                if score_result.passed:
                    result, result_mode = score_result, Mode.SCORE
                else:
                    attempts.append(Test._stamp(score_result, Mode.SCORE, threshold, exp))
                    result, result_mode = evaluator.llm_based_evaluation(case), Mode.LLM

            stamped = Test._stamp(result, result_mode, threshold, exp)
            if stamped.passed:
                decisive = stamped
                decisive.attempts = attempts
                break
            attempts.append(stamped)
            decisive = stamped  # stands as decisive unless a later alternative passes

        if not decisive.passed:
            decisive.attempts = attempts[:-1]  # every non-decisive attempt, decisive excluded
            message = Test._failure_message(selected_mode, expected, actual)
            if return_metrics:
                return decisive
            raise AssertionError(message)

        return decisive if return_metrics else None

    @staticmethod
    def _stamp(result: AKEvaluationResult, mode: Mode, threshold: float, expected: str) -> AKEvaluationResult:
        """Stamps reporting metadata onto a result. result.passed is set by the evaluator itself
        (score_based_evaluation/llm_based_evaluation) and is left untouched here."""
        result.mode = mode.value
        result.threshold = threshold
        result.expected = expected
        return result

    @staticmethod
    def _failure_message(mode: Mode, expected: list[str], actual: str) -> str:
        if mode == Mode.SCORE:
            return f"Response didn't pass the score threshold. Expected: {expected}, Received: {actual}"
        if mode == Mode.LLM:
            return f"Response didn't pass llm evaluation against any expected. Expected: {expected}, Received: {actual}"
        return f"Response didn't pass score matching or llm evaluation. Expected: {expected}, Received: {actual}"
```

Rules this sketch encodes (verify each in the real implementation and its tests):

1. **`AKMetricNotSupported` and `AKEvaluationError` from `evaluator.score_based_evaluation`/
   `llm_based_evaluation` are never caught inside `compare`** — they propagate out of the `for exp in
   expected` loop and out of `compare` itself, on the first alternative that raises them. This matches
   design.md's fallback semantics exactly: a structurally-unsupported mode or a broken backend must not be
   silently absorbed into "try the next alternative."
2. **`attempts` accumulates every non-decisive result** across the whole `expected` loop, not only the
   `fallback` score-stage failures — `AKEvaluationResult.attempts` on the returned/raised result holds
   every alternative that did not become decisive, whichever mode produced it.
3. **The threshold comparison (`score >= case.threshold`) is the only "passed" definition**, computed
   once per evaluator method (`score_based_evaluation`/`llm_based_evaluation`), not duplicated or
   recomputed by `_stamp` or by `compare` itself. `compare`'s fallback branch reads `score_result.passed`
   directly rather than re-deriving it from `score_result.score`.
4. **`AKMissingInput`** (raised by the evaluator when `case.expected` is falsy) can only occur if
   `expected` contains a falsy element (e.g. `""`) inside an otherwise valid list — `compare`'s own guard
   only rejects an empty *list*. This is intentionally not additionally guarded in `compare`: a caller
   passing `[""]` as an "acceptable answer" gets `AKMissingInput` naming the metric and field, which is a
   more useful error than a silent pass/fail on an empty string.
5. **`Mode(AKTestConfig.get().mode)`** converts the config's plain `str` (validated by the `pattern`) into
   the `Mode` enum; `AKTestConfig.mode` stays a plain `str` field (unchanged from today) because
   `AKTestConfig` doesn't import `test.py`'s `Mode` (would invert the package's internal dependency
   direction: `config.py` has no reason to import from `test.py`).
6. **`Test.expect`** gains `return_metrics: bool = False` and forwards it, plus `mode=self.mode,
   threshold=self.match_threshold`, unchanged otherwise:

```python
async def expect(self, expected: list[str], return_metrics: bool = False) -> AKEvaluationResult | None:
    if self.last_agent_response is None:
        raise AssertionError("No response available to compare. Ensure send() was called before expect().")
    return self.compare(
        actual=self.last_agent_response,
        expected=expected,
        user_input=self.last_user_input,
        threshold=self.match_threshold,
        mode=self.mode,
        return_metrics=return_metrics,
    )
```

### Consumer changes

- **`test/test.py`**: `_fuzzy_compare` and `_judge_compare` deleted; `_ragas_llm`/`_ragas_embeddings`
  class attributes deleted; module-level imports `from datasets import Dataset`, `from ragas import
  evaluate`, `from ragas.metrics import answer_relevancy, answer_similarity`, `from rapidfuzz import
  fuzz` deleted. After the change, `agentkernel.test` has no `ragas`, `datasets`, or `rapidfuzz` symbol
  anywhere. New imports: `from threading import RLock`, `from agentkernel.core.util.factory import
  AKConfigError, require_extra, resolve_dotted`, `from .core.akevaluators import AKEvaluationCase,
  AKEvaluationResult, AKEvaluator`.
- **`test/__init__.py`**: unchanged (`from .config import AKTestConfig`, `from .test import Mode, Test`).
  Bring-your-own evaluators import from `agentkernel.test.core.akevaluators`, not `agentkernel.test`.
- **Nothing outside `agentkernel.test` imports `Mode`, `Test._fuzzy_compare`, or `Test._judge_compare`
  directly** — confirmed by the migration surface below being the complete list of consumers.

### Behavioural changes

Numbered, exhaustive; each is intentional, with its justification. Non-changes follow.

1. **Score-mode matching changes from `fuzz.ratio` similarity to `Scorer.quasi_exact_match_score`
   normalised whole-string equality.** A response is scored `1.0` if its entire (normalised) text equals
   the (normalised) expected phrase, `0.0` otherwise — no partial credit and no containment. *Why:*
   deterministic, offline, zero new dependency, a documented `deepeval` `Scorer` primitive rather than a
   hand-assembled regex `BaseMetric`; see the twice-corrected design.md section. *Consequence:* this is
   stricter than the `PatternMatchMetric`-containment behaviour this spec specified in an earlier pass —
   a verbose-but-correct response that merely *contains* the expected phrase now scores `0.0`, not just a
   response that scored just above the old fuzzy threshold on edit-distance tolerance. In practice this
   pushes more comparisons through to the `llm` stage under `fallback` than either `fuzz.ratio` or
   `PatternMatchMetric` would have. A caller relying on `score` alone for a short expected phrase inside a
   verbose response must switch to `llm`/`fallback` — but switching alone is **not sufficient**: a
   symmetric-equivalence llm rubric fails the identical case, since a verbose `actual` says more than a
   short `expected`. This was reproduced in review on 4 shipped example suites, all in `fallback` mode,
   all failing at the `llm` stage too (see design.md's "Consequence for callers, revised"). The default
   `_DEFAULT_LLM_CRITERIA` was made directional specifically to address this, instructing the judge not
   to penalize `actual` for extra length/detail — that rubric change, not the mode switch by itself, is
   what a caller needing containment now depends on.
2. **`llm` mode with no `expected` now raises `AKMissingInput` instead of falling back to
   `answer_relevancy` against the question.** *Why:* every in-repo caller already supplies `expected`
   (`expect()` requires a non-empty list by signature), and `GEval` has no reference-free counterpart to
   substitute. *Consequence:* none observed in-repo; would only affect a caller invoking `Test.compare`
   directly with `mode="llm"`/`"judge"` and no `expected` — none exists under `examples/`, `use-cases/`, or
   the docs' code samples per the migration surface grep below.
3. **Threshold scale changes from `0–100` (with `/100` conversion into judge scoring) to `0.0–1.0`
   uniformly.** *Why:* matches what every evaluation library returns; removes an ad hoc conversion.
   *Consequence:* every explicit `threshold=`/`match_threshold=` call site must be rewritten (see
   "Migration surface"); an un-rewritten leftover (e.g. `threshold=50`) is **not** rejected — `compare`
   has no range guard on `threshold`, so a stale `50` just makes every evaluator's `score >= threshold`
   comparison false (both shipped metrics return scores in `[0.0, 1.0]`), i.e. "always fails" rather than
   erroring loudly. **Reversed from an earlier pass of this spec**, which called for a `0.0 <= threshold
   <= 1.0` `ValueError` guard in `compare`: dropped before shipping because the meaningful range depends
   on the configured evaluator's own scoring scale, so a universal guard doesn't generalize past the two
   shipped DeepEval metrics. Tested explicitly as intentional, not an oversight:
   `ak-py/tests/test_cli_tester.py::test_compare_threshold_outside_zero_one_is_not_rejected`.
   Similarly, a legacy `judge:` key is **not** rejected either, contrary to the `_reject_legacy_judge_key`
   validator sketched under "Configuration" below — see that section's notes for the tested, shipped
   behaviour (silently ignored under `extra="ignore"`, same as any other unknown key).
4. **`fallback`'s local stage is score mode (binary) rather than fuzzy (graded).** *Why:* inherent to
   dropping `fuzz.ratio`. *Consequence* (already flagged in design.md, restated for completeness): a
   near-miss that would have passed fuzzy locally now falls through to the llm stage every time, so
   `fallback` suites make more LLM calls than before. This is a running-cost change, not a pass/fail
   change, since the llm stage still decides correctly in the previously-passing near-miss cases.
5. **Assertion message text changes** (mode names + wording) even though the messages are otherwise
   findable by tests: old messages read "didn't pass the threshold score", "didn't pass judge ...", "didn't
   pass fuzzy matching or judge evaluation ..."; new: "didn't pass the score threshold", "didn't pass llm
   evaluation against any expected", "didn't pass score matching or llm evaluation". *Why:* the old text
   named the removed library/technique. *Consequence:* the three existing regex matches in
   `test_cli_tester.py` (`match="didn't pass the threshold score"`, `match="didn't pass judge"`,
   `match="didn't pass fuzzy matching or judge evaluation"`) are rewritten in the same change (see
   "Testing") rather than kept working against old text.
6. **`return_metrics=True` never raises `AssertionError` for a failing comparison**, but every other error
   (`AKEvaluationError`, `AKMissingInput`, `AKMetricNotSupported`, `AKConfigError`, the `ValueError`s for
   invalid mode/empty-expected-list, and `expect`'s own "no response recorded" `AssertionError`) still
   raises unsuppressed. *Why:* `return_metrics` is a reporting mode, not an error-suppression mode.
   *Consequence:* callers that adopt `return_metrics=True` must still handle the non-assertion exceptions.

**Non-changes** (confirm unchanged in review): `Test.start`/`send`/`stop`/`_read_until_prompt`/
`_drain_stderr` and the CLI subprocess machinery; `Test.__test__ = False`; `expect()`'s "pass if ANY
alternative passes" semantics; the shape of `Mode` as a `StrEnum` (values change, kind doesn't);
`AKTestConfig`'s YAML/env loading mechanics (`YamlBaseSettingsModified`, `AK_TEST_CONFIG_PATH_OVERRIDE`).

## Error handling

| Failure | Raised as | Where | Caught by `compare`? |
|---|---|---|---|
| Unknown evaluator short name (no `.`) | `AKConfigError` | `Test._resolve_evaluator_class` | No — propagates |
| Dotted path doesn't import / wrong attr / not an `AKEvaluator` subclass | `AKConfigError` | `resolve_dotted` | No |
| `deepeval` extra not installed, `evaluator: deepeval` | `ImportError` (extra-naming message) | `require_extra` inside `_resolve_evaluator_class` | No |
| Legacy `judge:` key present (YAML or env) | *(not rejected — intentionally silently dropped by `extra="ignore"`; see "Configuration" notes)* | — | — |
| `case.expected` falsy on a shipped metric call | `AKMissingInput` | `DeepevalAKEvaluator.{score,llm}_based_evaluation` | No — propagates out of the `expected` loop |
| Evaluator can't provide a requested mode (BYO) | `AKMetricNotSupported` | evaluator subclass | No — propagates; see design.md rationale (a structural mismatch, not a per-case failure) |
| DeepEval judge backend failure (bad/missing API key, judge model rejects schema-constrained output, unparseable judge response) | `AKEvaluationError` | `DeepevalAKEvaluator.llm_based_evaluation` (wraps the caught exception) — `score_based_evaluation` has no failure mode to wrap; it is a pure string comparison | No — propagates |
| Invalid `mode=` argument | `ValueError` | `Test.compare` | N/A |
| Empty `expected` list | `ValueError` | `Test.compare` | N/A |
| `threshold` outside `[0.0, 1.0]` | *(not rejected — intentionally unvalidated; see Behavioural change 3)* | — | — |
| `expect()` called with no prior `send()` | `AssertionError` | `Test.expect` | N/A |
| A comparison legitimately scores below threshold | `AssertionError` (or `AKEvaluationResult` under `return_metrics=True`) | `Test.compare` | This is the one caught/converted case |

The single row that is "caught" is the ordinary pass/fail decision — every other row is a structural or
configuration failure that must surface as itself, per the Motivation's "a broken judge is
indistinguishable from a failing agent" problem this design removes.

## Testing

### New/changed test files

- **`ak-py/tests/test_cli_tester.py`** — rewritten to run offline:
  - A test-local fake evaluator (`class _FakeEvaluator(AKEvaluator)`, registered by dotted path
    e.g. `tests.test_cli_tester._FakeEvaluator` or a path resolvable from the test's own module) replaces
    every live-LLM call. It implements `score_based_evaluation` with a simple deterministic rule (e.g.
    normalized whole-string equality matching the real semantics, so tests stay meaningful) and
    `llm_based_evaluation` returning a canned score based on a simple string check against `case.expected`
    — no network, no `deepeval` import required for these tests.
  - Coverage per design.md "Test suite": each mode (`score`/`llm`/`fallback`) routing to the right
    evaluator method; `return_metrics` true/false under each mode; `attempts` populated correctly in
    `fallback` (score-stage failure recorded, llm result decisive); the "judge unavailable" path (fake
    evaluator raises `AKEvaluationError`) surfacing as `AKEvaluationError`, not as a content-mismatch
    `AssertionError`; `mode="fuzzy"`/`mode="judge"` rejected as invalid (as shipped:
    `test_compare_legacy_mode_names_rejected`); a `threshold` outside `[0.0, 1.0]` is accepted, not
    rejected (as shipped, reversed from an earlier pass of this spec:
    `test_compare_threshold_outside_zero_one_is_not_rejected`).
  - Existing assertion-text matches rewritten per "Behavioural changes" point 5: `match="didn't pass the
    score threshold"`, `match="didn't pass llm evaluation"`, `match="didn't pass score matching or llm
    evaluation"`.
  - `Test._resolve_evaluator` branch coverage: `"deepeval"` → `DeepevalAKEvaluator` (needs the `test` extra
    installed in CI, which it is); a dotted path to the test-local fake → that class; an unknown short
    name (no `.`) → `AKConfigError` listing `["deepeval"]`; a dotted path to a class that isn't an
    `AKEvaluator` subclass → `AKConfigError`; a dotted path to a nonexistent module → `AKConfigError`.
    Also asserts `agentkernel.test.core.akevaluators.deepeval.GEval is deepeval.metrics.GEval` (and same
    for `Scorer`), confirming the `deepeval.py` module name never shadows the third-party package it
    imports from — see "Package layout" note 0.
    Simulating "the built-in with the extra absent → `ImportError`" requires either a `monkeypatch` that
    makes the `deepeval` import fail inside `require_extra`'s block, or is left as a manual/documented
    check if `deepeval` cannot be made absent inside the same CI venv that needs it for other tests in this
    file — decide in the plan.
  - Caching: two `compare()` calls under one config resolve to the same evaluator instance (identity
    assertion, e.g. patch/wrap the fake evaluator's `__init__` to count constructions); the cache key
    check (`AKTestConfig._reset()` alone, changing `evaluator` between two `compare()` calls, yields a
    different instance without an explicit `Test._reset_evaluator()` call) is a separate case from the
    explicit-reset case (`AKTestConfig._reset()` + `Test._reset_evaluator()` rebuilds).
  - A BYO evaluator test asserts `"deepeval" not in sys.modules` (or equivalent) after resolving and using
    the dotted-path fake evaluator, proving no dependency on the built-in.
  - `AKTestConfig._reset()` and `Test._reset_evaluator()` both run in an autouse fixture (mirroring the
    existing `reset_test_config_singleton` fixture in `test_test_config.py`) so evaluator-cache state
    doesn't leak between tests in this file.
- **`ak-py/tests/test_test_config.py`** — add: `evaluator` field default (`"deepeval"`) and override
  (YAML + `AK_TEST__EVALUATOR`); the renamed `llm` block (YAML + `AK_TEST__LLM__MODEL`/`PROVIDER`/
  `EMBEDDING_MODEL`); `mode` pattern rejecting `fuzzy`/`judge` (`ValidationError`, as shipped:
  `test_legacy_mode_names_rejected`). As shipped, a legacy `judge:` key (YAML) is *not* rejected — it is
  silently ignored under `extra="ignore"` (as shipped:
  `test_legacy_judge_key_in_yaml_is_silently_ignored`), reversed from this spec's earlier
  `_reject_legacy_judge_key`/`AKConfigError` plan.
- **`ak-py/tests/test_config.py`** — no behavioural change expected (test-config independence from
  `AKConfig` is already covered by `test_independent_from_akconfig` in `test_test_config.py`); confirm no
  `test:`-block assertions in this file reference the old `judge`/`fuzzy` spelling before leaving it
  untouched.

### Riskiest consumer

Per the "Riskiest consumer gets a test" rule: `Test.compare` is the consumer whose code changes shape the
most (the entire mode-dispatch/fallback/attempts algorithm is new), and it is exactly what
`test_cli_tester.py` is rewritten to cover exhaustively above — there is no separate, larger consumer of
`compare`/`expect` elsewhere in `ak-py/src` (grep confirms every call site is under `examples/`,
`use-cases/`, or docs code samples, none of which run under `ak-py`'s own `pytest` suite).

### Command

`cd ak-py && uv run pytest tests/test_cli_tester.py tests/test_test_config.py -v`, then the full
`uv run pytest` per `ak-dev-testing-conventions`.

## Dependencies

- `ak-py/pyproject.toml`'s `test` extra (lines 146-159 today):
  ```toml
  test = [
      "pytest>=8.4.1",
      "pytest-asyncio>=1.2.0",
      "pytest-cov>=6.2.1",
      "pytest-html>=4.1.1",
      "pytest-order>=1.3.0",
      "deepeval>=4.1.4",
      "litellm>=1.89.2",
  ]
  ```
  Removed: `rapidfuzz`, `ragas`, `datasets`, `pandas`, the `langchain_community==0.4.1` pin (and its
  comment at line 154, "ragas imports langchain_community.chat_models.vertexai..."). `litellm>=1.89.2`
  stays (already present; `DeepevalAKEvaluator` and AK's existing multimodal/thread features share it — no
  version bump needed, no conflict found in the isolated-venv install).
  The identical `langchain_community==0.4.1` pin in the `langgraph` extra (`pyproject.toml:45`) is
  untouched and unaffected — it constrains `test`+`langgraph` resolution together in CI
  (`uv sync --all-extras`) only because both extras happened to pin it for unrelated reasons; removing the
  `test` extra's copy removes one of the two independent reasons that version is pinned, not the pin
  itself.
- **`deepeval>=4.1.4` pulls `pytest-xdist`, `pytest-repeat`, `pytest-rerunfailures` as runtime
  dependencies** (verified: `pip install deepeval` in the isolated venv installs all three; `pytest-asyncio`
  is deepeval's fourth pytest-plugin dependency but is already a direct `test`-extra dependency and already
  active). Because pytest auto-loads plugins via entry points, these three become active in every AK
  `pytest` session once `deepeval` is installed, alongside the existing `addopts`
  (`--cov=src --cov-report=term --cov-report=html --html=report.html`, `pyproject.toml:212`). **Must be
  verified before merge**: run the full `ak-py` suite after adding `deepeval` and confirm no interaction
  (in particular, `pytest-rerunfailures`/`pytest-repeat` silently masking a flaky test, or `pytest-xdist`
  changing worker-count-sensitive behavior — none of AK's current tests opt into `-n`/`--reruns`/`--count`,
  so the risk is auto-activation changing default behavior, not an explicit flag conflicting).
- **Resolution of `test` + `langgraph` together must be verified** after the `test` extra's
  `langchain_community` pin is removed (`uv sync --all-extras`, matching what CI's `build.sh` runs).

## Migration surface

Every current (non-versioned, non-build) surface referencing the old mode names, the `judge:` config
block, or the 0–100 threshold scale, enumerated by direct search against this branch (all counts and
line numbers verified against the current tree, not carried over from `design.md` without
re-verification):

### Code

- `ak-py/src/agentkernel/test/test.py` — full rewrite per "Design" above.
- `ak-py/src/agentkernel/test/config.py:32` (the `mode` field's `pattern`) — full rewrite per
  "Configuration" above.

### Tests

- `ak-py/tests/test_cli_tester.py`, `ak-py/tests/test_test_config.py` — per "Testing" above.
- `ak-py/tests/test_config.py` — verified clean (no old-mode-name assertions); no change expected.

### Bundled skills

- `ak-py/src/agentkernel/skills/ak-test/SKILL.md` — lines needing the mode/config rename:
  - Line 6: skill `description` says "choosing test modes (fuzzy, judge, fallback)" → `(score, llm,
    fallback)`.
  - Lines 41-49: the `config.yaml`/mode table code sample — **note**: this sample already shows the mode
    key nested under a `test:` block inside `config.yaml`, which is stale independent of this change
    (`AKTestConfig` reads `test-config.yaml`, a separate file — a `test:` block in `config.yaml` is
    ignored per `config.py`'s own docstring and `test_independent_from_akconfig`). This spec only renames
    the mode values (`fuzzy`→`score`, `judge`→`llm`) in place; correcting the sample to the right file is
    a pre-existing doc bug outside this change's scope, called out here so it isn't mistaken for something
    this change introduced.
  - Lines 51-57: the "For judge mode, configure the judge model" sample — rename to "For llm mode" and
    `judge:` → `llm:`.
- `ak-py/src/agentkernel/skills/ak-init/SKILL.md:338` area (the embedded `config.yaml` template's
  `test:\n  mode: fuzzy` line) — same stale-file caveat as above; rename `fuzzy` → `score` in place.
- `ak-py/src/agentkernel/skills/ak-test/evals/evals.json` — three eval cases assert on old spellings and
  must be updated so the skill's own evals keep passing:
  - `test-mode-fuzzy` (id, `expected_outputs: ["test:", "mode: fuzzy"]`) → rename id to
    `test-mode-score`, expected output to `"mode: score"`. Input prompt text ("Set up fuzzy matching for
    my agent tests") should be reworded to not name the removed mode (e.g. "Set up deterministic
    string-match mode for my agent tests").
  - `test-mode-judge` (`expected_outputs: ["test:", "mode: judge", "judge:", "model:"]`) → rename id to
    `test-mode-llm`, expected outputs to `"mode: llm"`, `"llm:"`, `"model:"`; reword the input prompt.
  - `test-mode-fallback` (`expected_outputs: ["test:", "mode: fallback"]`) — unaffected (mode name
    unchanged), but note it lives alongside the two renamed cases in the same file.

### Dev skill

- `.agents/skills/ak-dev-testing-conventions/SKILL.md` — the "Built-in Test Framework" → "Test Modes"
  section (as loaded by the skill; source at the corresponding lines in the repo file) documents
  `mode: fuzzy | judge | fallback`, the `judge:` block, and "Ragas-based LLM evaluation" — rewrite to
  `score | llm | fallback`, the `llm:` block, and "DeepEval-based evaluation (`Scorer.
  quasi_exact_match_score` / `GEval`)". This is the same skill file this Stage 2 process itself loaded from
  `.agents/skills/ak-dev-testing-conventions/`.

### Docs (`docs/docs/`)

All four pages carry old-mode-name code samples, `Mode.FUZZY`/`Mode.JUDGE` references, the 0–100
threshold scale, and "Ragas"/"answer_similarity"/"answer_relevancy" prose. Verified line ranges (grep
against this branch):

- **`docs/docs/testing/cli-testing.md`** (389 lines) — mode/threshold/Ragas references at lines 17, 22-23,
  51, 57-135, 139-171, 232, 242-243, 253, 255, 264. Rewrite: `Mode.FUZZY`→`Mode.SCORE`,
  `Mode.JUDGE`→`Mode.LLM`; threshold values divided by 100 and shown as floats (`threshold=80` →
  `threshold=0.8`, etc.); the `test-config.yaml` sample's `judge:` → `llm:`; the "Ragas" /
  "answer_similarity" prose → DeepEval / `Scorer.quasi_exact_match_score` (score) and `GEval` (llm). Add a
  "Bring your own evaluator" subsection mirroring `docs/docs/advanced/sandbox.md`'s "Bring your own
  provider" (see below).
- **`docs/docs/testing/automated-testing.md`** — same pattern at lines 42-121, 125-153, 174, 253, 343-357,
  365-372, 414, 420, 432, 437-440.
- **`docs/docs/testing/overview.md`** — same pattern at lines 82-190.
- **`docs/docs/core-concepts/configuration.md`** — lines 20, 456-462 (env var block), 628-674 (the
  "Test Configuration" section, including the exact YAML sample at 635-639 and the historical note at 674
  about the `test:`-in-`config.yaml` migration, which itself needs a follow-on note that `judge` was later
  renamed `llm`). This page's `test`-extra reference and `evaluator` key are new additions (design.md
  requirement), not just renames.
- `ak-py/README.md:967` (` \`judge\`: Uses LLM-based evaluation (Ragas)` in the "Test Modes" bullet list
  alongside `fuzzy`/`fallback`, lines 965-968) and the adjoining `test-config.yaml` sample at lines
  970-976 (`mode: fallback` / `judge:` block, values themselves don't need renaming since `fallback` is
  unchanged, but the `judge:` key does) and the field-reference bullets above it (lines ~940-963,
  `judge.model`/`judge.provider`/`judge.embedding_model` field names and their `AK_TEST__JUDGE__*` env var
  names) — all renamed to `llm`/`AK_TEST__LLM__*`.

New "Bring your own evaluator" subsection (one of the four testing docs pages, `cli-testing.md` is the
natural home since it introduces modes first), mirroring `docs/docs/advanced/sandbox.md:377-390`'s "Bring
your own provider" structure:

```markdown
### Bring your own evaluator

Any dotted path to an `AKEvaluator` subclass works as `evaluator` in `test-config.yaml`:

\`\`\`yaml
evaluator: my_evaluator.MyEvaluator   # resolves against my_evaluator.py next to your test file
\`\`\`

Implement `score_based_evaluation(case)` and `llm_based_evaluation(case)`, both synchronous,
returning `AKEvaluationResult`. Raise `AKMetricNotSupported` from a method your backend can't provide,
and `AKEvaluationError` on a backend failure (missing credentials, transport error) — never return a
`0.0` for either. See `agentkernel.test.core.akevaluators` for the interface and payload models.
\`\`\`
```

(The plan will fill in the exact wording; the code fence and API names above are already correct
against this spec's interface.)

- `docs/versioned_docs/` — frozen published snapshots, **not edited** (confirmed: these are the
  Docusaurus versioned-docs mirrors of past releases and editing them would misrepresent what those
  released versions actually did).

### Examples — `test-config.yaml` (40 files total, enumerated)

**34 files with `mode: fallback` + a `judge:` block** (identical structure — `# Test comparison mode:
fuzzy, judge, or fallback (default: fallback)` comment, `judge:` block with `model`/`provider`/
`embedding_model` — verified by direct diff-equivalent grep, all 34 render identically to the sample
below except the boilerplate header comment, which is present in all 40 examples files and unaffected):

```
examples/api/a2a/multi/test-config.yaml
examples/api/mcp/multi/test-config.yaml
examples/api/multimodal/adk/test-config.yaml
examples/api/multimodal/crewai/test-config.yaml
examples/api/multimodal/dynamodb/test-config.yaml
examples/api/multimodal/langgraph/test-config.yaml
examples/api/multimodal/openai/test-config.yaml
examples/api/multimodal/redis/test-config.yaml
examples/api/multimodal/smolagents/test-config.yaml
examples/api/openai/test-config.yaml
examples/api/pydanticai/test-config.yaml
examples/aws-containerized/adk/test-config.yaml
examples/aws-containerized/crewai/test-config.yaml
examples/aws-containerized/mcp/multi/test-config.yaml
examples/aws-containerized/openai-dynamodb/test-config.yaml
examples/aws-serverless/adk/test-config.yaml
examples/aws-serverless/crewai/test-config.yaml
examples/aws-serverless/langgraph/test-config.yaml
examples/aws-serverless/openai-auth/test-config.yaml
examples/aws-serverless/openai/test-config.yaml
examples/aws-serverless/scalable-openai/test-config.yaml
examples/azure-containerized/openai-cosmos/test-config.yaml
examples/azure-serverless/openai/test-config.yaml
examples/cli/guardrail/bedrock/test-config.yaml
examples/cli/guardrail/openai/test-config.yaml
examples/cli/guardrail/walledai/test-config.yaml
examples/gcp-containerized/openai-auth/test-config.yaml
examples/gcp-serverless/openai-auth/test-config.yaml
examples/memory/cosmos/test-config.yaml
examples/memory/dynamodb/test-config.yaml
examples/memory/redis/test-config.yaml
examples/memory/valkey/test-config.yaml
examples/transport/kafka/test-config.yaml
examples/transport/nats/test-config.yaml
```

Each rewritten from:
```yaml
mode: fallback  # Test comparison mode: fuzzy, judge, or fallback (default: fallback)
# Judge settings are used by the judge and fallback modes (LLM-based evaluation):
judge:
  model: gpt-4o-mini
  provider: openai
  embedding_model: text-embedding-3-small
```
to:
```yaml
mode: fallback  # Test comparison mode: score, llm, or fallback (default: fallback)
# LLM settings are used by the llm and fallback modes (LLM-based evaluation):
llm:
  model: gpt-4o-mini
  provider: openai
  embedding_model: text-embedding-3-small
```
No `evaluator:` key added — the default (`deepeval`) already applies; adding it 34 times would be pure
noise (per design.md's "Configuration" section).

**6 files with `mode: fuzzy`, no `judge:` block** (`examples/sandbox/{basic,daytona,docker,e2b,policy,
profiles}/test-config.yaml`), each carrying its own explanatory comment about why fuzzy was chosen
(exact-value sandbox outputs), e.g.:
```yaml
# The sandbox executes real code, so every expected answer is an exact value
# ("42", "hello sandbox", "328"). Fuzzy string matching keeps the comparison
# deterministic and offline: no LLM judge is involved in evaluating results.
mode: fuzzy
```
Rewritten to (comment content adjusted from "Fuzzy string matching" to "Deterministic exact-match
matching", mode value renamed, no other change — these still carry no `judge`/`llm` block since they
never used one):
```yaml
# The sandbox executes real code, so every expected answer is an exact value
# ("42", "hello sandbox", "328"). Deterministic exact-match matching keeps the
# comparison offline: no LLM judge is involved in evaluating results.
mode: score
```

### Use-cases

- `use-cases/waste-sorting-assistant/test-config.yaml` (2 lines: a header comment + `mode: fuzzy`) →
  `mode: score`. This is the only in-repo surface outside `examples/` pinned to an old mode name.

### Threshold call sites under `examples/` (15 files, 30 call sites — enumerated)

```
examples/api/adk/app_test.py:54            threshold=10,
examples/api/multimodal/adk/adk_test.py:93  threshold=80,
examples/api/multimodal/adk/adk_test.py:107 threshold=80,
examples/api/multimodal/crewai/crewai_test.py:93   threshold=80,
examples/api/multimodal/crewai/crewai_test.py:107  threshold=80,
examples/api/multimodal/dynamodb/dynamodb_test.py:65  threshold=80,
examples/api/multimodal/dynamodb/dynamodb_test.py:79  threshold=80,
examples/api/multimodal/langgraph/langgraph_test.py:93   threshold=80,
examples/api/multimodal/langgraph/langgraph_test.py:107  threshold=80,
examples/api/multimodal/openai/openai_test.py:93    threshold=80,
examples/api/multimodal/openai/openai_test.py:107   threshold=80,
examples/api/multimodal/redis/redis_test.py:65      threshold=80,
examples/api/multimodal/redis/redis_test.py:79      threshold=80,
examples/api/multimodal/smolagents/smolagents_test.py:93   threshold=80,
examples/api/multimodal/smolagents/smolagents_test.py:107  threshold=80,
examples/api/multimodal/thread-openai/app_test.py:96   threshold=80,
examples/api/multimodal/thread-openai/app_test.py:133  threshold=80,
examples/api/openai/app_test.py:61          threshold=10,
examples/api/openai/app_test.py:66          ...threshold=10
examples/api/openai/app_test.py:77          Test.compare(response, [...], threshold=20)
examples/api/pydanticai/app_test.py:75      threshold=10,
examples/api/pydanticai/app_test.py:80      ...threshold=10
examples/api/pydanticai/app_test.py:91      Test.compare(response, [...], threshold=20)
examples/cli/smolagents/demo_test.py:10     Test("demo_toolcalling.py", match_threshold=20)
examples/containerized/openai/app_test.py:75   threshold=10,
examples/containerized/openai/app_test.py:80   ...threshold=10
examples/transport/kafka/app_test.py:111    threshold=10,
examples/transport/kafka/app_test.py:123    threshold=10,
examples/transport/nats/app_test.py:111     threshold=10,
examples/transport/nats/app_test.py:123     threshold=10,
```

Each numeric threshold divides by 100: `threshold=10` → `threshold=0.1`, `threshold=20` → `threshold=0.2`,
`threshold=80` → `threshold=0.8`, `match_threshold=20` → `match_threshold=0.2`. This is a direct
value rewrite at each of the 30 sites above — no semantic change beyond the scale (design.md
"Threshold scale").

### Summary count

| Surface | Count |
|---|---|
| Example `test-config.yaml` (fallback+judge → fallback+llm) | 34 |
| Example `test-config.yaml` (fuzzy → score) | 6 |
| Use-case `test-config.yaml` (fuzzy → score) | 1 |
| Threshold call sites under `examples/` | 30, across 15 files |
| Docs pages | 4 (`cli-testing.md`, `automated-testing.md`, `overview.md`, `configuration.md`) + `ak-py/README.md` |
| Bundled skills | `ak-test/SKILL.md`, `ak-init/SKILL.md` (embedded template), `ak-test/evals/evals.json` |
| Dev skills | `ak-dev-testing-conventions/SKILL.md` |
| Code | `test.py`, `config.py` |
| Tests | `test_cli_tester.py`, `test_test_config.py` |

Every row above is covered by an iteration in `plan.md`; none is dropped silently.
