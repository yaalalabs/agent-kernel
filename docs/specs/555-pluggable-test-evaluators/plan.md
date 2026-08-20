# #555: Replace RAGAS with a pluggable `AKEvaluator` (DeepEval), rename test modes, add `return_metrics` — Implementation Plan

Builds [`spec.md`](spec.md) in order: the evaluator package first (importable and unit-testable with no
dependency on `Test`), then config, then the harness rewrite that wires them together, then the dependency
swap, then the full migration surface, then tests, then the docs/skills sync.

## Iteration 1: Evaluator interface package

- **Goal:** `agentkernel.test.core.akevaluators` exists, is pure Python (no `deepeval` import at module
  level), and exports the full interface. Nothing consumes it yet.
- **Files:** `ak-py/src/agentkernel/test/core/__init__.py` (new, empty),
  `ak-py/src/agentkernel/test/core/akevaluators/__init__.py` (new),
  `ak-py/src/agentkernel/test/core/akevaluators/base.py` (new)
- **Steps:**
  1. Create `base.py` per spec.md "`test/core/akevaluators/base.py`": the three error classes
     (`AKEvaluationError`, `AKMissingInput`, `AKMetricNotSupported`), `AKEvaluationCase`,
     `AKEvaluationResult` (confirm whether `model_rebuild()` is needed for the self-referential
     `attempts` field, per the note under that section), and the `AKEvaluator` ABC.
  2. Create `__init__.py` re-exporting all six names per spec.md.
- **Verify:** `uv run python -c "from agentkernel.test.core.akevaluators import AKEvaluator, AKEvaluationCase, AKEvaluationResult, AKEvaluationError, AKMissingInput, AKMetricNotSupported"`
  succeeds, and `sys.modules` contains no `deepeval` afterward.

## Iteration 2: `DeepevalAKEvaluator`

- **Goal:** The built-in evaluator works standalone (importable and callable directly), still with no
  wiring into `Test`.
- **Files:** `ak-py/src/agentkernel/test/core/akevaluators/deepeval.py` (new)
- **Steps:**
  1. Implement per spec.md "`test/core/akevaluators/deepeval.py`": the `DEEPEVAL_TELEMETRY_OPT_OUT`
     `setdefault` before any `deepeval` import, `DeepevalAKEvaluator.__init__` with lazy `_model`,
     `score_based_evaluation` (`Scorer.quasi_exact_match_score`, `AKMissingInput` guard, `float` cast),
     `llm_based_evaluation` (`GEval` with `threshold=None`, `SingleTurnParams`, the `AKEvaluationError`
     wrap around `metric.measure()`).
  2. Add the shadowing check from spec.md note 0 (`agentkernel.test.core.akevaluators.deepeval.GEval is
     deepeval.metrics.GEval`, same for `Scorer`) as a quick standalone script or the first test written in
     Iteration 7 — whichever lands first; do not skip it.
- **Verify:** manually construct `DeepevalAKEvaluator(config)` with a real `AKTestConfig` default and call
  `score_based_evaluation` on a matching/non-matching pair; confirm `1.0`/`0.0`. `llm_based_evaluation`
  needs a real or mocked LLM credential — smoke-test with a real key if available, otherwise defer full
  coverage to Iteration 7's fake-evaluator tests and mocked `litellm` call.

## Iteration 3: Configuration (`test/config.py`)

- **Goal:** `AKTestConfig` has `evaluator`, the renamed `llm` block, the new `mode` pattern, and rejects a
  legacy `judge` key — independently loadable and testable before `Test` changes.
- **Files:** `ak-py/src/agentkernel/test/config.py`
- **Steps:** Apply the full diff in spec.md "Configuration (`test/config.py`)": rename `_JudgeConfig` →
  `_LlmConfig`, rename the `judge` field → `llm`, add `evaluator: str = "deepeval"` (no pattern), change
  `mode`'s pattern to `^(fallback|llm|score)$`, add the `_reject_legacy_judge_key` `model_validator`
  importing `AKConfigError` from `agentkernel.core.util.factory`.
- **Verify:** confirm `AKConfigError` (not a wrapped `pydantic.ValidationError`) propagates from
  `AKTestConfig()` when a `judge:` key or `AK_TEST__JUDGE__*` env var is present (spec.md's config.py note
  flags this as unconfirmed pydantic-version behavior — check it here, before Iteration 7's tests assert
  on it). `AKTestConfig()` still constructs with defaults when no `test-config.yaml` exists.

## Iteration 4: Harness rewrite (`test/test.py`)

- **Goal:** `Test.compare`/`Test.expect` dispatch through `AKEvaluator` end to end; all RAGAS code is gone;
  `Mode` is renamed. This is the iteration where the feature becomes real.
- **Files:** `ak-py/src/agentkernel/test/test.py`
- **Steps:**
  1. Delete `_fuzzy_compare`, `_judge_compare`, the `_ragas_llm`/`_ragas_embeddings` class attributes, and
     the four RAGAS/rapidfuzz module-level imports.
  2. Add imports: `from threading import RLock`; `from agentkernel.core.util.factory import AKConfigError,
     require_extra, resolve_dotted`; `from .core.akevaluators import AKEvaluationCase, AKEvaluationResult,
     AKEvaluator`.
  3. Rename `Mode.FUZZY`/`Mode.JUDGE` → `Mode.SCORE = "score"` / `Mode.LLM = "llm"`; keep `Mode.FALLBACK`.
  4. Add `_evaluator`, `_evaluator_lock`, `_resolve_evaluator`, `_resolve_evaluator_class`,
     `_reset_evaluator` per spec.md "`Test._resolve_evaluator`" — the double-checked cache, `_BUILTIN_EVALUATORS`.
  5. Rewrite `Test.compare` per spec.md "`Test.compare`": `0.0`–`1.0` threshold defaults and validation,
     `return_metrics` parameter, the `_stamp`/`_failure_message` helpers, the mode-dispatch and `fallback`
     algorithm with `attempts` accumulation, propagation (not catching) of `AKMetricNotSupported` /
     `AKEvaluationError`.
  6. Update `Test.__init__`'s `match_threshold` default `50` → `0.5`.
  7. Add `return_metrics` to `Test.expect` and forward it, per spec.md's `expect` sketch.
- **Verify:** `agentkernel.test` module imports with no `deepeval`/`ragas`/`datasets`/`rapidfuzz` symbol
  present (`uv run python -c "import agentkernel.test, sys; assert 'deepeval' not in sys.modules"`). Full
  test suite for this file is written in Iteration 7, but do a manual `Test.compare` smoke call here
  (`mode="score"`) against a running CLI example to confirm the dispatch path works before moving on.

## Iteration 5: Dependencies (`pyproject.toml`)

- **Goal:** `deepeval` replaces `ragas` in the `test` extra; the environment installs and resolves cleanly.
- **Files:** `ak-py/pyproject.toml`
- **Steps:**
  1. Replace the `test` extra block per spec.md "Dependencies": remove `rapidfuzz`, `ragas`, `datasets`,
     `pandas`, the `langchain_community==0.4.1` pin and its comment; add `deepeval>=4.1.4`; keep
     `litellm>=1.89.2` and the existing pytest packages.
  2. Leave the `langgraph` extra's separate `langchain_community==0.4.1` pin untouched.
- **Verify:** `cd ak-py && uv sync --all-extras` succeeds (matching CI's `build.sh`); confirm `deepeval`,
  `pytest-xdist`, `pytest-repeat`, `pytest-rerunfailures` are installed; confirm `ragas`/`datasets`/`pandas`
  are gone from the resolved environment for the `test` extra alone (`uv sync --extra test` in a scratch
  venv) if `--all-extras` makes this hard to see directly.

## Iteration 6: Threshold call-site migration (`examples/`)

- **Goal:** Every explicit threshold value across `examples/` is on the `0.0`–`1.0` scale; nothing left on
  the old `0`–`100` scale (which would now raise `ValueError`).
- **Files:** the 15 files / 30 call sites enumerated in spec.md "Threshold call sites under `examples/`"
- **Steps:** Divide each `threshold=`/`match_threshold=` value by 100 in place (`threshold=10` →
  `threshold=0.1`, `threshold=20` → `threshold=0.2`, `threshold=80` → `threshold=0.8`,
  `match_threshold=20` → `match_threshold=0.2`) at every site in the spec.md table — no other change.
- **Verify:** `git grep -nE "(match_)?threshold *= *[0-9]" examples/` shows only values in `(0, 1]`.

## Iteration 7: `test-config.yaml` migration (`examples/`, `use-cases/`)

- **Goal:** Every example and use-case config uses the renamed modes/`llm` block; no example carries a
  stale `judge:` key or `mode: fuzzy`/`mode: judge` (which would now raise at config load).
- **Files:** the 34 `mode: fallback` + `judge:` files, the 6 `mode: fuzzy` sandbox files (all enumerated in
  spec.md "Examples — `test-config.yaml`"), and `use-cases/waste-sorting-assistant/test-config.yaml`
- **Steps:**
  1. For each of the 34 fallback files: rewrite the mode comment (`fuzzy, judge, or fallback` →
     `score, llm, or fallback`), rename the `judge:` block header comment and key to `llm:`, keep the three
     sub-fields unchanged.
  2. For the 6 sandbox files: `mode: fuzzy` → `mode: score`, and reword each file's explanatory comment
     ("Fuzzy string matching" → "Deterministic exact-match matching") per spec.md's before/after sample.
  3. `use-cases/waste-sorting-assistant/test-config.yaml`: `mode: fuzzy` → `mode: score`.
  4. Do not add an `evaluator:` key to any of these — the default covers it (spec.md explicit non-goal).
- **Verify:** `git grep -n "mode: fuzzy\|mode: judge\|^judge:" examples/ use-cases/` returns nothing.

## Iteration 8: Tests

- **Goal:** The renamed/rewritten harness has full offline coverage; CI is green with no live-LLM calls in
  unit tests.
- **Files:** `ak-py/tests/test_cli_tester.py` (rewrite), `ak-py/tests/test_test_config.py` (additions),
  `ak-py/tests/test_config.py` (verify-only, per spec.md "no behavioural change expected")
- **Steps:** Per spec.md "Testing" in full:
  1. Write the test-local `_FakeEvaluator(AKEvaluator)` in `test_cli_tester.py`, registered by dotted path.
  2. Cover: each mode routing to the right evaluator method; `return_metrics` true/false per mode;
     `attempts` population in `fallback`; the judge-unavailable path raising `AKEvaluationError` (not a
     content-mismatch `AssertionError`); `mode="fuzzy"`/`mode="judge"` rejected; a leftover `judge:` key
     raising `AKConfigError`.
  3. Rewrite the three existing assertion-text `match=` regexes per spec.md "Behavioural changes" point 5.
  4. Cover every `_resolve_evaluator`/`_resolve_evaluator_class` branch listed in spec.md "New/changed test
     files", including the `deepeval.py` shadowing check from Iteration 2 step 2 if not already added
     there, and decide (per spec.md's open note) whether the extra-absent → `ImportError` branch is
     monkeypatched or left as a documented manual check.
  5. Cover caching: same-config identity across two `compare()` calls; cache-key change via
     `AKTestConfig._reset()` alone; explicit rebuild via `_reset()` + `Test._reset_evaluator()`.
  6. Cover the BYO-no-`deepeval`-dependency assertion (`sys.modules` check).
  7. Add the autouse fixture resetting `AKTestConfig`/`Test._reset_evaluator()` between tests in this file.
  8. In `test_test_config.py`: add `evaluator` default/override, renamed `llm` block, `mode` pattern
     rejection, and the legacy `judge:` key/env-var `AKConfigError` cases.
  9. In `test_config.py`: confirm no old-spelling assertions exist; leave the file otherwise unchanged.
- **Verify:** `cd ak-py && uv run pytest tests/test_cli_tester.py tests/test_test_config.py -v`, then the
  full `uv run pytest` per `ak-dev-testing-conventions` — confirm no `pytest-xdist`/`pytest-repeat`/
  `pytest-rerunfailures` auto-activation regressions (spec.md "Dependencies").

## Iteration 9: Sync docs and skills

- **Goal:** Every non-code surface spec.md's "Migration surface" enumerates is updated; nothing referencing
  `fuzzy`/`judge`/RAGAS/the 0–100 scale survives outside `docs/versioned_docs/`.
- **Files/surfaces**, each from spec.md "Migration surface":
  - **Bundled skills:** `ak-py/src/agentkernel/skills/ak-test/SKILL.md` (description line, mode table,
    "For judge mode" sample → "For llm mode"); `ak-py/src/agentkernel/skills/ak-init/SKILL.md`'s embedded
    `config.yaml` template (`mode: fuzzy` → `mode: score`); `ak-py/src/agentkernel/skills/ak-test/evals/evals.json`
    (`test-mode-fuzzy` → `test-mode-score`, `test-mode-judge` → `test-mode-llm`, reworded prompts, updated
    `expected_outputs`).
  - **Dev skill:** `.agents/skills/ak-dev-testing-conventions/SKILL.md`'s "Test Modes" section — rewrite to
    `score | llm | fallback`, the `llm:` block, DeepEval-based evaluation.
  - **Docs:** `docs/docs/testing/cli-testing.md` (plus the new "Bring your own evaluator" subsection per
    spec.md's draft), `docs/docs/testing/automated-testing.md`, `docs/docs/testing/overview.md`,
    `docs/docs/core-concepts/configuration.md` (env var block, "Test Configuration" section, `evaluator`
    key as a new addition), `ak-py/README.md:940-976` (Test Modes bullets, field reference, config sample).
  - Do **not** edit `docs/versioned_docs/`.
- **Steps:**
  1. Update each surface above per spec.md's exact before/after text.
  2. Run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` against the accumulated diff to
     catch anything spec.md's enumeration missed (new commits since spec.md was written, e.g. from
     Iterations 1-8).
- **Verify:** `git grep -rn "ragas\|RAGAS\|mode: fuzzy\|mode: judge\|Mode.FUZZY\|Mode.JUDGE" -- ':!docs/versioned_docs'`
  returns nothing; the `ak-test` skill's own evals pass (`evals.json` cases render against the renamed
  modes); `evaluator-framework-survey.md` in `research/` is left as-is (historical record, not a doc
  surface).
