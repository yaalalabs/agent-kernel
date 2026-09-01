"""Tests for the CLI test framework (agentkernel.test).

Offline by design: every mode/fallback/return_metrics/caching/error-propagation behaviour is
exercised against test-local fake AKEvaluator subclasses (registered by dotted path, exactly the
bring-your-own extension point), never against a live LLM. The one exception is the
`_resolve_evaluator_class("deepeval")` branch test, which only checks that the built-in resolves
to the right class -- it does not call any evaluation method, so it stays offline too.
"""

import builtins
import sys
import types

import pytest

from agentkernel.core.util.factory import AKConfigError
from agentkernel.test.config import AKTestConfig
from agentkernel.test.core.akevaluators import (
    AKEvaluationCase,
    AKEvaluationError,
    AKEvaluationResult,
    AKEvaluator,
    AKMetricNotSupported,
    AKMissingInput,
)
from agentkernel.test.test import Mode
from agentkernel.test.test import Test as CliTest


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


class _FakeEvaluator(AKEvaluator):
    """Deterministic, offline stand-in for DeepevalAKEvaluator.

    score_based_evaluation: normalised whole-string equality (mirrors quasi_exact_match_score).
    llm_based_evaluation: normalised containment (a stand-in "judge" that's more lenient than score).
    """

    def score_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("score_based_evaluation requires AKEvaluationCase.expected")
        score = 1.0 if _normalize(case.actual) == _normalize(case.expected) else 0.0
        return AKEvaluationResult(metric="fake_score", evaluator="fake", score=score, passed=score >= case.threshold)

    def llm_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("llm_based_evaluation requires AKEvaluationCase.expected")
        score = 1.0 if _normalize(case.expected) in _normalize(case.actual) else 0.2
        return AKEvaluationResult(metric="fake_llm", evaluator="fake", score=score, reason="fake reason", passed=score >= case.threshold)


class _CountingFakeEvaluator(_FakeEvaluator):
    """Same behaviour as _FakeEvaluator; counts constructions for the cache tests."""

    construction_count = 0

    def __init__(self, config):
        super().__init__(config)
        type(self).construction_count += 1


class _FailingLlmEvaluator(AKEvaluator):
    """Simulates a broken judge backend: score mode works, llm mode always fails."""

    def score_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        if not case.expected:
            raise AKMissingInput("score_based_evaluation requires AKEvaluationCase.expected")
        return AKEvaluationResult(metric="fake_score", evaluator="fake", score=0.0, passed=0.0 >= case.threshold)

    def llm_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        raise AKEvaluationError("judge backend unavailable (simulated)")


class _ScoreUnsupportedEvaluator(AKEvaluator):
    """Simulates a backend that structurally cannot do score-based evaluation."""

    def score_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        raise AKMetricNotSupported("score mode not supported by this fake backend")

    def llm_based_evaluation(self, case: AKEvaluationCase) -> AKEvaluationResult:
        raise AssertionError("llm_based_evaluation must not be called when score raises AKMetricNotSupported")


class _NotAnEvaluator:
    """Not an AKEvaluator subclass -- used to test the dotted-path subclass check."""


# A fake module namespace: resolve_dotted's importlib.import_module call is monkeypatched to
# return this for a fake module name, the same pattern test_store_builders.py uses for its
# bring-your-own dotted-path tests. This decouples the tests from real import machinery for a
# `tests` package that has no __init__.py.
_FAKE_MODULE_NAME = "tests._fake_akevaluators"
_fake_module = types.ModuleType(_FAKE_MODULE_NAME)
_fake_module._FakeEvaluator = _FakeEvaluator
_fake_module._CountingFakeEvaluator = _CountingFakeEvaluator
_fake_module._FailingLlmEvaluator = _FailingLlmEvaluator
_fake_module._ScoreUnsupportedEvaluator = _ScoreUnsupportedEvaluator
_fake_module._NotAnEvaluator = _NotAnEvaluator


def _patch_import(monkeypatch):
    """Make resolve_dotted's importlib return the fake module for _FAKE_MODULE_NAME."""
    import agentkernel.core.util.factory as fac

    real = fac.importlib.import_module
    monkeypatch.setattr(
        fac.importlib,
        "import_module",
        lambda name, *a, **k: _fake_module if name == _FAKE_MODULE_NAME else real(name, *a, **k),
    )


def _use_evaluator(monkeypatch, class_name: str) -> None:
    """Point AKTestConfig.evaluator at a fake evaluator class and force a fresh resolve."""
    _patch_import(monkeypatch)
    monkeypatch.setenv("AK_TEST__EVALUATOR", f"{_FAKE_MODULE_NAME}.{class_name}")
    AKTestConfig._reset()
    CliTest._reset_evaluator()


@pytest.fixture(autouse=True)
def reset_test_state():
    AKTestConfig._reset()
    CliTest._reset_evaluator()
    yield
    AKTestConfig._reset()
    CliTest._reset_evaluator()


# --- prompt/expect plumbing (unaffected by the evaluator rewrite) ------------------------- #


@pytest.mark.asyncio
async def test_cli_tester_prompt_update_and_expect(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    t = CliTest(path="dummy.py", match_threshold=0.6, mode=Mode.SCORE)
    CliTest._update_prompt("agent")
    assert CliTest._get_prompt() == "(agent) >> "

    t.last_agent_response = "Hello World"
    await t.expect(["Hello World"])

    t.match_threshold = 0.99
    t.last_agent_response = "Something else"
    with pytest.raises(AssertionError):
        await t.expect(["Hello World"])


@pytest.mark.asyncio
async def test_expect_without_send_raises_assertion_error():
    t = CliTest(path="dummy.py")
    with pytest.raises(AssertionError, match="No response available"):
        await t.expect(["Hello"])


@pytest.mark.asyncio
async def test_expect_forwards_return_metrics(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    t = CliTest(path="dummy.py", match_threshold=0.5, mode=Mode.SCORE)
    t.last_agent_response = "Hello"
    result = await t.expect(["Goodbye"], return_metrics=True)
    assert isinstance(result, AKEvaluationResult)
    assert result.passed is False


# --- mode routing ------------------------------------------------------------------------- #


def test_compare_score_mode_routes_to_score_based_evaluation(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    CliTest.compare("Hello World", ["Hello World"], threshold=0.5, mode=Mode.SCORE)
    with pytest.raises(AssertionError, match="didn't pass the score threshold"):
        CliTest.compare("Hello World", ["Goodbye"], threshold=0.5, mode=Mode.SCORE)


def test_compare_llm_mode_routes_to_llm_based_evaluation(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    # Score would fail (not an exact match) but llm mode never calls score_based_evaluation.
    CliTest.compare("Paris is lovely", ["Paris"], threshold=0.5, mode=Mode.LLM)
    with pytest.raises(AssertionError, match="didn't pass llm evaluation"):
        CliTest.compare("Hello", ["Goodbye forever"], threshold=0.5, mode=Mode.LLM)


def test_compare_fallback_mode_tries_score_then_llm(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    # Exact match passes at the score stage.
    CliTest.compare("Hello World", ["Hello World"], threshold=0.5, mode=Mode.FALLBACK)

    # Score fails (not exact) but llm passes (containment); score attempt recorded.
    result = CliTest.compare("Paris is lovely", ["Paris"], threshold=0.5, mode=Mode.FALLBACK, return_metrics=True)
    assert result.passed
    assert result.mode == Mode.LLM.value
    assert len(result.attempts) == 1
    assert result.attempts[0].mode == Mode.SCORE.value
    assert result.attempts[0].passed is False

    # Both stages fail.
    with pytest.raises(AssertionError, match="didn't pass score matching or llm evaluation"):
        CliTest.compare("Hello", ["Goodbye completely"], threshold=0.5, mode=Mode.FALLBACK)


def test_fallback_attempts_multiple_expected_alternatives(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    result = CliTest.compare(
        "Hello there",
        ["Goodbye", "Hello there"],
        threshold=0.5,
        mode=Mode.FALLBACK,
        return_metrics=True,
    )
    assert result.passed
    assert result.expected == "Hello there"
    # "Goodbye" failed both stages (score, then llm) before "Hello there" passed at the score stage.
    assert len(result.attempts) == 2


def test_compare_invalid_mode_raises_value_error():
    with pytest.raises(ValueError, match="Invalid mode"):
        CliTest.compare("Hello", ["Hello"], mode="invalid")


@pytest.mark.parametrize("legacy_mode", ["fuzzy", "judge"])
def test_compare_legacy_mode_names_rejected(legacy_mode):
    with pytest.raises(ValueError, match="Invalid mode"):
        CliTest.compare("Hello", ["Hello"], mode=legacy_mode)


def test_compare_threshold_outside_zero_one_is_not_rejected(monkeypatch):
    # No range validation: threshold isn't restricted to [0.0, 1.0] because the meaningful range
    # depends on the configured evaluator/framework's scoring scale. An out-of-range threshold is
    # accepted as-is, it just changes whether a 0.0/1.0-scored comparison can pass.
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    with pytest.raises(AssertionError):
        CliTest.compare("Hello", ["Hello"], threshold=1.5, mode=Mode.SCORE)
    CliTest.compare("Hello", ["Goodbye"], threshold=-0.1, mode=Mode.SCORE)


def test_compare_empty_expected_list_raises_value_error():
    with pytest.raises(ValueError, match="cannot be empty"):
        CliTest.compare("Hello", [], mode=Mode.SCORE)


def test_compare_none_expected_raises_value_error():
    with pytest.raises(ValueError, match="cannot be empty"):
        CliTest.compare("Hello", None, mode=Mode.SCORE)


def test_compare_falsy_expected_element_raises_missing_input(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    with pytest.raises(AKMissingInput):
        CliTest.compare("Hello", [""], mode=Mode.SCORE)


# --- return_metrics ------------------------------------------------------------------------ #


def test_return_metrics_false_default_raises_on_failure(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    with pytest.raises(AssertionError):
        CliTest.compare("Hello", ["Goodbye"], mode=Mode.SCORE)


def test_return_metrics_true_returns_result_instead_of_raising(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    result = CliTest.compare("Hello", ["Goodbye"], mode=Mode.SCORE, return_metrics=True)
    assert isinstance(result, AKEvaluationResult)
    assert result.passed is False
    assert result.score == 0.0
    assert result.threshold == 0.5


def test_return_metrics_true_on_success_returns_passed_result(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    result = CliTest.compare("Hello", ["Hello"], mode=Mode.SCORE, return_metrics=True)
    assert result.passed is True
    assert result.score == 1.0


# --- error propagation (never absorbed into a content-mismatch AssertionError) -------------- #


def test_llm_evaluator_failure_surfaces_as_evaluation_error_not_assertion(monkeypatch):
    _use_evaluator(monkeypatch, "_FailingLlmEvaluator")
    with pytest.raises(AKEvaluationError, match="judge backend unavailable"):
        CliTest.compare("Hello", ["Goodbye"], threshold=0.5, mode=Mode.LLM)


def test_fallback_mode_propagates_llm_evaluation_error(monkeypatch):
    _use_evaluator(monkeypatch, "_FailingLlmEvaluator")
    # Score stage always scores 0.0 in this fake, so fallback proceeds to llm, which raises.
    with pytest.raises(AKEvaluationError, match="judge backend unavailable"):
        CliTest.compare("Hello", ["Goodbye"], threshold=0.5, mode=Mode.FALLBACK)


def test_fallback_propagates_metric_not_supported_without_trying_llm(monkeypatch):
    _use_evaluator(monkeypatch, "_ScoreUnsupportedEvaluator")
    with pytest.raises(AKMetricNotSupported):
        CliTest.compare("Hello", ["Hello"], mode=Mode.FALLBACK)


# --- Test._resolve_evaluator / _resolve_evaluator_class branch coverage --------------------- #


def test_resolve_evaluator_class_builtin_deepeval():
    from agentkernel.test.core.akevaluators.deepeval import DeepevalAKEvaluator

    assert CliTest._resolve_evaluator_class("deepeval") is DeepevalAKEvaluator


def test_resolve_evaluator_class_dotted_path_to_fake(monkeypatch):
    _patch_import(monkeypatch)
    resolved = CliTest._resolve_evaluator_class(f"{_FAKE_MODULE_NAME}._FakeEvaluator")
    assert resolved is _FakeEvaluator


def test_resolve_evaluator_class_unknown_short_name_raises():
    with pytest.raises(AKConfigError, match=r"\['deepeval'\]"):
        CliTest._resolve_evaluator_class("deepval")


def test_resolve_evaluator_class_dotted_path_not_a_subclass_raises(monkeypatch):
    _patch_import(monkeypatch)
    with pytest.raises(AKConfigError):
        CliTest._resolve_evaluator_class(f"{_FAKE_MODULE_NAME}._NotAnEvaluator")


def test_resolve_evaluator_class_dotted_path_missing_module_raises():
    with pytest.raises(AKConfigError):
        CliTest._resolve_evaluator_class("tests.no_such_module_xyz.Thing")


def test_resolve_evaluator_class_deepeval_missing_extra_raises_import_error(monkeypatch):
    # sys.modules["deepeval"] = None is not enough here: deepeval ships as an auto-loaded pytest
    # plugin, so deepeval.metrics/scorer/etc. are already cached submodules by the time this test
    # runs, and `from deepeval.metrics import GEval` resolves straight from that cache without
    # re-triggering a failing import of the parent. Patching __import__ for any "deepeval[.*]"
    # name is what actually forces deepeval.py's top-level imports to fail, simulating the extra
    # being absent.
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "deepeval" or name.startswith("deepeval."):
            raise ImportError(f"simulated missing dependency: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "agentkernel.test.core.akevaluators.deepeval", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match=r"agentkernel\[test\]"):
        CliTest._resolve_evaluator_class("deepeval")


def test_deepeval_module_does_not_shadow_third_party_package():
    import deepeval

    import agentkernel.test.core.akevaluators.deepeval as ak_deepeval_module

    assert ak_deepeval_module.GEval is deepeval.metrics.GEval
    assert ak_deepeval_module.Scorer is deepeval.scorer.Scorer


# --- evaluator caching -----------------------------------------------------------------------#


def test_evaluator_cached_across_resolve_calls(monkeypatch):
    _use_evaluator(monkeypatch, "_CountingFakeEvaluator")
    _CountingFakeEvaluator.construction_count = 0

    first = CliTest._resolve_evaluator()
    second = CliTest._resolve_evaluator()
    assert first is second
    assert _CountingFakeEvaluator.construction_count == 1


def test_evaluator_cache_key_rebuilds_on_config_change_without_explicit_reset(monkeypatch):
    _use_evaluator(monkeypatch, "_FakeEvaluator")
    first = CliTest._resolve_evaluator()

    # Change the configured evaluator and reset only AKTestConfig -- Test._reset_evaluator() is
    # deliberately NOT called, proving the cache key (not just first-use) drives the rebuild.
    monkeypatch.setenv("AK_TEST__EVALUATOR", f"{_FAKE_MODULE_NAME}._CountingFakeEvaluator")
    AKTestConfig._reset()
    second = CliTest._resolve_evaluator()

    assert type(first) is _FakeEvaluator
    assert type(second) is _CountingFakeEvaluator
    assert first is not second


def test_evaluator_cache_explicit_reset_rebuilds_same_config(monkeypatch):
    _use_evaluator(monkeypatch, "_CountingFakeEvaluator")
    _CountingFakeEvaluator.construction_count = 0

    first = CliTest._resolve_evaluator()
    AKTestConfig._reset()
    CliTest._reset_evaluator()
    second = CliTest._resolve_evaluator()

    assert first is not second
    assert _CountingFakeEvaluator.construction_count == 2


def test_byo_evaluator_has_no_deepeval_dependency(monkeypatch):
    # Clear any prior caching so this check is meaningful regardless of test execution order.
    monkeypatch.delitem(sys.modules, "deepeval", raising=False)
    monkeypatch.delitem(sys.modules, "agentkernel.test.core.akevaluators.deepeval", raising=False)
    _use_evaluator(monkeypatch, "_FakeEvaluator")

    result = CliTest.compare("Hello World", ["Hello World"], mode=Mode.SCORE, return_metrics=True)
    assert result.passed
    assert "deepeval" not in sys.modules
