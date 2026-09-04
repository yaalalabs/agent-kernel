---
name: ak-dev-new-evaluator-provider
description: >
  Step-by-step guide for adding a new built-in test evaluator provider to Agent Kernel
  (beyond DeepEval). Use this skill when you need to give the test framework's pluggable
  AKEvaluator interface a new first-party scoring/judge backend addressable by a short
  config name (e.g. "ragas"), not a one-off bring-your-own evaluator. Covers implementing
  score-based and LLM-as-judge evaluation, factory registration, configuration, optional
  dependencies, and testing.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Test Evaluator Provider

This guide walks through adding a new **built-in** evaluator provider to Agent Kernel's test
framework. Use the existing DeepEval implementation
(`ak-py/src/agentkernel/test/core/evaluator/deepeval.py`) as reference.

Before starting, check whether you actually need this skill: if the evaluator only needs to exist
for *your own* project (not addressable by every AK user via a short built-in name), you don't
need any of the steps below — just subclass `AKEvaluator` anywhere importable and point
`test-config.yaml`'s `evaluator:` at its dotted path. That's the "bring your own evaluator"
path described in the user-facing `ak-test` skill and
[`docs/docs/testing/cli-testing.md`](../../../docs/docs/testing/cli-testing.md#bring-your-own-evaluator);
`examples/cli/custom-evaluator/` is a complete worked example of it. This skill is only for adding
a **first-party, in-repo** provider that ships with AK and gets its own short `type` name.

## Existing Providers

| Provider | Short name | Scoring mode | LLM-judge mode | Extra |
|---|---|---|---|---|
| DeepEval | `deepeval` | `Scorer.quasi_exact_match_score` (whole-string, normalised) | `GEval` LLM-as-judge metric | `agentkernel[test]` |
| Opik | `opik` | `LevenshteinRatio` (fuzzy string similarity) | `GEval` LLM-as-judge metric | `agentkernel[opik]` |

## Architecture Overview

- **`AKEvaluator`** (`ak-py/src/agentkernel/test/core/evaluator/base.py`) is the abstract base
  every evaluator — built-in or bring-your-own — implements. It has exactly two abstract methods:
  - `evaluate_by_score(case: AKEvaluationCase) -> AKEvaluationResult` — deterministic scoring,
    no LLM call
  - `evaluate_by_llm(case: AKEvaluationCase) -> AKEvaluationResult` — LLM-as-judge scoring
- **`AKEvaluationCase`** carries the comparison inputs (`user_input`, `actual`, `expected`,
  `threshold`, `context`, `criteria`); **`AKEvaluationResult`** carries the outcome (`score`,
  `passed`, `metric`, `evaluator`, `reason`, `cost`, `attempts`, `metadata`).
- **Error contract** (every evaluator must honor this, not just DeepEval):
  - Raise `AKMissingInput` when a field the requested metric needs (e.g. `case.expected`) wasn't
    supplied.
  - Raise `AKMetricNotSupported` from whichever of the two methods your backend structurally
    cannot implement (e.g. a pure LLM-judge service has no offline scoring mode).
  - Raise `AKEvaluationError` when a configured backend fails to produce a score (missing
    credentials, transport error, unparseable judge output). Never raise `AssertionError` and
    never silently return a `0.0` to stand in for a failure — `0.0` must only ever mean "scored
    zero", not "couldn't be scored". `Test.compare` is the only place that decides pass/fail
    fatality; evaluators only ever set `result.passed`.
- **`Test._resolve_evaluator_class`** in `ak-py/src/agentkernel/test/test.py` is the factory. It
  shares the same pluggable-backend shape as guardrails, sandbox providers, and trace backends
  (`core/util/factory.py`'s `resolve_dotted`/`require_extra`/`AKConfigError`): an `if`-per-built-in
  branch with the SDK import wrapped in `require_extra` (actionable `ImportError` naming the pip
  extra if missing), then a dotted-path bring-your-own fallback for anything else.
- Evaluator instances are cached per-process on `Test._evaluator` (keyed by the configured value),
  guarded by `Test._evaluator_lock` — construction happens once per distinct `evaluator:` config
  value, not once per `Test.compare` call.

## Step-by-Step

### 1. Create the Evaluator Provider File

Create `ak-py/src/agentkernel/test/core/evaluator/<provider>.py`. Keep the provider's SDK imports
inside this file only — `test/core/evaluator/__init__.py` and `base.py` stay pure Python with no
optional-dependency imports at module level, so importing the `AKEvaluator` interface never
requires your provider's SDK to be installed.

```python
# ak-py/src/agentkernel/test/core/evaluator/<provider>.py
from agentkernel.test.config import AKTestConfig

from .base import AKEvaluationCase, AKEvaluationError, AKEvaluationResult, AKEvaluator, AKMissingInput


class <Provider>AKEvaluator(AKEvaluator):
    def __init__(self, config: AKTestConfig) -> None:
        super().__init__(config)
        # Lazy-init any client/model here only if evaluate_by_score never needs it
        # (mirrors DeepevalAKEvaluator's lazy LiteLLMModel, built only on first evaluate_by_llm call).

    def evaluate_by_score(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("evaluate_by_score requires AKEvaluationCase.expected")
        # Deterministic, offline scoring logic here.
        score = ...  # float
        return AKEvaluationResult(
            metric="<metric_name>",
            evaluator="<provider>",
            score=score,
            passed=score >= case.threshold,
        )

    def evaluate_by_llm(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("evaluate_by_llm requires AKEvaluationCase.expected")
        try:
            score = ...  # call the judge
        except Exception as exc:
            raise AKEvaluationError(f"<provider> llm-based evaluation failed: {exc}") from exc
        return AKEvaluationResult(
            metric="<metric_name>",
            evaluator="<provider>",
            score=score,
            reason=...,  # judge's explanation, if the backend provides one
            passed=score is not None and score >= case.threshold,
        )
```

If a mode genuinely doesn't apply to your backend (e.g. a provider that is LLM-judge-only), raise
`AKMetricNotSupported` from that method instead of faking a result — `Test.compare`'s `fallback`
mode relies on this to skip straight to the other mode rather than treating an unsupported metric
as a failed score.

### 2. Register with the Factory

Add the short name to `_BUILTIN_EVALUATORS` and a branch in `Test._resolve_evaluator_class`, both
in `ak-py/src/agentkernel/test/test.py`:

```python
_BUILTIN_EVALUATORS = ["deepeval", "<provider>"]          # ADD THIS

class Test:
    ...
    @classmethod
    def _resolve_evaluator_class(cls, configured: str) -> type[AKEvaluator]:
        if configured == "deepeval":
            with require_extra("test", "evaluator: deepeval"):
                from .core.evaluator.deepeval import DeepevalAKEvaluator
            return DeepevalAKEvaluator
        if configured == "<provider>":                                        # ADD THIS
            with require_extra("<provider>", "evaluator: <provider>"):
                from .core.evaluator.<provider> import <Provider>AKEvaluator
            return <Provider>AKEvaluator
        if "." not in configured:
            raise AKConfigError(
                f"unknown evaluator '{configured}'; expected one of {_BUILTIN_EVALUATORS} or a dotted path to an AKEvaluator subclass"
            )
        return resolve_dotted(configured, base=AKEvaluator)
```

A dotted `evaluator:` value (e.g. `myorg.evaluators.CustomEvaluator`) resolves via `resolve_dotted`
without any factory edit at all — only add an `if` branch here for a first-party, in-repo provider
you want addressable by a short name.

### 3. Add Optional Dependencies

Add a new extras group to `ak-py/pyproject.toml` for the provider's SDK — don't fold it into the
existing `test` extra (that one stays DeepEval's, since it's the only built-in today and every test
user already needs it for the framework itself):

```toml
[project.optional-dependencies]
<provider> = [
    "provider-sdk>=x.y.z",
]
```

### 4. Add Configuration Docs

`evaluator:` in `test-config.yaml` is already a free-form string on `AKTestConfig` (built-in short
name or dotted path) — no config schema change is needed for a new built-in, since it's just a new
value the same field accepts:

```yaml
mode: fallback
evaluator: <provider>
```

If your provider needs extra config fields (e.g. an API key env var name, a judge model override),
read them from `AKTestConfig` the same way `DeepevalAKEvaluator` reads `self._config.llm` — don't
invent a parallel config path.

### 5. Add Tests

Add `ak-py/tests/test_evaluator_<provider>.py`, following the shape of
`ak-py/tests/test_evaluator_deepeval.py`: exercise `evaluate_by_score` for real (offline, no
network) where possible, and mock the judge call in `evaluate_by_llm` so the suite stays
network-free. At minimum cover:

- `evaluate_by_score`: exact/mismatch cases, threshold boundary, `AKMissingInput` when `expected`
  is absent
- `evaluate_by_llm`: success, failure wrapped as `AKEvaluationError`, `AKMissingInput` when
  `expected` is absent
- The factory branch: `Test._resolve_evaluator_class("<provider>")` resolves to your class, and
  (if the SDK is optional) the `require_extra` `ImportError` path when it's missing — see
  `test_resolve_evaluator_class_deepeval_missing_extra_raises_import_error` in
  `ak-py/tests/test_cli_tester.py` for the pattern (patching `builtins.__import__`, since a
  cached submodule import can otherwise mask the missing dependency).

### 6. Add Documentation

Add the provider to the evaluator backend table in
[`docs/docs/core-concepts/configuration.md`](../../../docs/docs/core-concepts/configuration.md)
and [`docs/docs/testing/cli-testing.md`](../../../docs/docs/testing/cli-testing.md).

## Checklist

- [ ] `ak-py/src/agentkernel/test/core/evaluator/<provider>.py` implementing `AKEvaluator`
- [ ] Factory registration in `Test._resolve_evaluator_class` (`ak-py/src/agentkernel/test/test.py`)
      and `_BUILTIN_EVALUATORS`
- [ ] Optional dependency extra in `ak-py/pyproject.toml`
- [ ] Unit tests in `ak-py/tests/test_evaluator_<provider>.py`
- [ ] Documentation updated
