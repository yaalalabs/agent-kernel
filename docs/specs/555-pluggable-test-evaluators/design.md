# #555: Replace RAGAS with a pluggable `AKEvaluator` (DeepEval), rename test modes, add `return_metrics`

Removes the RAGAS-specific comparison logic from `Test` — code as well as dependency — and moves all
scoring behind a pluggable `AKEvaluator` interface selected by a new `evaluator` field in
`test-config.yaml`, with `deepeval` as the only built-in. Renames the comparison modes
(`fuzzy` → `score`, `judge` → `llm`) so each mode maps one-to-one onto an `AKEvaluator` method. Adds
`return_metrics`, a per-call argument that makes `Test.compare` / `Test.expect` return an
`AKEvaluationResult` instead of raising `AssertionError`. The design idea: evaluators are pure scorers, and every policy decision —
threshold, mode, alternative-expected iteration, pass/fail — stays in the harness.

Requirements background: [`research/evaluator-framework-survey.md`](research/evaluator-framework-survey.md).

## Motivation

- The comparison logic is RAGAS-specific and cannot be swapped
  - `Test._judge_compare` imports `ragas` / `litellm` inline and builds RAGAS clients directly (`ak-py/src/agentkernel/test/test.py:152-181`)
  - The two RAGAS metrics are selected by an `if expected:` branch inside that method (`test.py:188`, `test.py:201`)
  - Judge clients are cached on **class attributes of `Test`** (`test.py:25-26`, `test.py:171-178`), so evaluator state and harness state share a lifetime
- The evaluator seam exists but is unspecified
  - `AKEvaluator` (untracked, `ak-py/src/agentkernel/test/core/akevaluators/evaluator.py`) declares `score_based_evaluation` and `llm_based_evaluation` with no parameters, no return type, and no payload model; `deepeval.py` is empty
- Mode names describe implementations, not intent
  - `Mode.FUZZY` / `Mode.JUDGE` (`test.py:16-19`) name a specific string-matching library and a specific
    RAGAS technique, so a backend that scores deterministically by another means has no accurate mode to sit under
- Scoring and asserting are fused, so scores are unobservable
  - `_fuzzy_compare` and `_judge_compare` return `None` and communicate only by raising `AssertionError` (`test.py:149`, `test.py:197-199`, `test.py:214-217`)
  - Numeric scores are computed and discarded (`test.py:194`, `test.py:212`); no caller can report or threshold them
- A broken judge is indistinguishable from a failing agent
  - `FALLBACK` catches `AssertionError` from the judge and re-raises a message naming only expected/received (`test.py:254-262`), so a missing API key surfaces as a content mismatch
- The RAGAS dependency forces a transitive pin
  - The `test` extra carries `ragas`, `datasets`, `pandas`, and `langchain_community==0.4.1` pinned solely to work around a RAGAS import (`ak-py/pyproject.toml:153-157`, comment at `:154`)
- Judge unit tests hit a live LLM
  - `test_compare_judge_mode` and `test_compare_fallback_mode` make real RAGAS calls with no skip guard or fake (`ak-py/tests/test_cli_tester.py:35-81`)

## Design

```mermaid
graph LR
    E["Test.expect()"] --> C["Test.compare()<br/>mode, threshold,<br/>expected-list loop,<br/>pass/fail or result"]
    C -->|"mode: score"| S["evaluator.score_based_evaluation()"]
    C -->|"mode: llm"| L["evaluator.llm_based_evaluation()"]
    C -->|"mode: fallback"| S -.->|"on fail"| L
    F["AKEvaluatorFactory<br/>(test-config: evaluator)"] --> DE["DeepEvalEvaluator"]
    F --> BYO["dotted-path<br/>user subclass"]
```

## Requirements

### Mode rename

- `Mode` becomes `SCORE = "score"`, `LLM = "llm"`, `FALLBACK = "fallback"`; `FUZZY` and `JUDGE` are gone
- Each mode maps to exactly one evaluator entry point
  - `score` → `AKEvaluator.score_based_evaluation`
  - `llm` → `AKEvaluator.llm_based_evaluation`
  - `fallback` → `score_based_evaluation`, then `llm_based_evaluation` only if the first did not pass
- `AKTestConfig.mode` validation pattern becomes `^(fallback|llm|score)$` (`ak-py/src/agentkernel/test/config.py:32`)
- Clean break: `fuzzy` and `judge` are not accepted as aliases, and no changelog note is produced
  (the repo has no `CHANGELOG` file)
  - `mode: fuzzy` / `mode: judge` fail loudly against the pattern, which is the intended upgrade signal
  - The 6 in-repo example configs pinned to `mode: fuzzy` are updated in the same change
    (enumerated under "Migration surface")
- `Mode` stays exported from `agentkernel.test` (`ak-py/src/agentkernel/test/__init__.py:9`)

### Evaluator interface (`test/core/akevaluators/`)

- `AKEvaluator` is an ABC whose implementations are **pure scorers**: they compute a score and never
  assert, never threshold, and never decide pass/fail
- Two abstract methods, matching the two non-fallback modes
  - `score_based_evaluation(case) -> AKEvaluationResult` — deterministic scoring, no LLM involved
  - `llm_based_evaluation(case) -> AKEvaluationResult` — LLM-as-judge scoring
- Both methods are **synchronous** (see "Synchronous evaluation") and take one argument: the
  `AKEvaluationCase` payload. Everything a backend needs arrives in that model, so adding an input
  later changes the model, never the method signatures or the harness's call sites
- Constructed with the resolved test configuration; an evaluator instance owns its own backend
  clients, so no evaluator state lives on `Test`
- **One metric per mode in v1.** The interface allows a backend to offer more, but AK ships exactly one
  score metric and one llm metric, so no metric-selection vocabulary or config key exists yet
  - A backend that cannot provide one of the two raises `AKMetricNotSupported`

### LLM model construction

- **The configuration is the common surface, not the model object.** `llm.model` and `llm.provider`
  (`config.py:11-12`) stay AK's single source of truth for every evaluator; each backend adapts them
  into whatever model class its own library expects
  - This is the repo's adapter convention — wrap the native object, do not abstract over it — and it
    preserves the provider support the RAGAS path had, which passed `provider=` into
    `LiteLLMStructuredLLM` (`test.py:177`)
- For DeepEval that adapter is its built-in `LiteLLMModel`, constructed as
  `LiteLLMModel(f"{llm.provider}/{llm.model}")`
  - AK writes **no** `DeepEvalBaseLLM` subclass and no structured-output handling: every DeepEval LLM
    metric requires schema-constrained JSON from the judge, and `LiteLLMModel` already provides it.
    Hand-rolling a shim would mean owning that schema plumbing for no gain, since `LiteLLMModel` is
    litellm underneath either way
  - `api_key` / `base_url` are left to litellm's own environment resolution
- **Only `llm` mode needs a model.** `score_based_evaluation` performs no LLM call, so score mode runs
  without a model, an API key, or a network connection

### Evaluation payload (`AKEvaluationCase`)

- Pydantic model, the single argument to both evaluator methods
  - `user_input: str` — required
  - `actual: str` — required
  - `expected: str | None` — a **single** ground truth; no library accepts alternatives (survey §2)
  - `context: list[str] | None` — retrieved/ground-truth context; **present in the model but not
    populated in v1**, since neither shipped metric consumes it
  - `criteria: str | None` — rubric for the llm metric; **present in the model but not populated in
    v1** — where a per-test rubric comes from is deferred, and the llm metric uses AK's own default
    rubric until then
- Only the fields the two shipped metrics need are populated, all of them from `Test.compare`'s
  existing arguments
  - `quasi_contains` needs `actual` and `expected`
  - `GEval` is keyed on `actual` and `expected` only — its `evaluation_params` name `ACTUAL_OUTPUT`
    and `EXPECTED_OUTPUT`, so the rubric never reads the question
  - `user_input` is still carried and passed through, because `LLMTestCase.input` is mandatory in
    DeepEval even when no metric reads it; an empty string is acceptable there
  - So `Test.compare` fills `actual` and `expected`, passes `user_input` through, and leaves
    `context` / `criteria` unset
- **No new `compare` / `expect` parameters** other than `return_metrics`: nothing about metric or
  payload configuration is passed per call
- `expected` is required by both shipped metrics; a call that reaches either without one raises
  `AKMissingInput` naming the metric and the field

### Evaluation result (`AKEvaluationResult`)

- Pydantic model returned by both evaluator methods and by `compare`/`expect` under `return_metrics`
  - `metric: str` — the metric that produced the score
  - `evaluator: str` — the configured evaluator name
  - `score: float | None` — normalised to `[0.0, 1.0]`; `None` means "not scored", never `0.0`
  - `threshold: float | None` / `passed: bool | None` — stamped by `Test.compare`, unset by evaluators
  - `mode: str | None` — the `Mode` that produced the decisive result; unset by evaluators
  - `expected: str | None` — which alternative produced the decisive score
  - `reason: str | None` — the judge's rationale where the backend supplies one
  - `cost: float | None` — evaluation cost where the backend reports it; expected to be `None` in
    practice, since DeepEval documents `evaluation_cost` as tracked when integrated with Confident AI
  - `attempts: list[AKEvaluationResult]` — non-decisive attempts (the failed score-mode result in
    `fallback`, and per-alternative scores); empty by default
  - `metadata: dict[str, Any]` — backend-specific extras (verbose logs, raw metric name); empty by default

### Configuration (`AKTestConfig`)

- One new field
  - `evaluator: str = "deepeval"` — built-in short name or a dotted path
- `return_metrics` is **not** a config field: it is decided per call, so a suite can assert on most
  comparisons and collect the result for specific ones
- The `judge` block is renamed to `llm`, matching the mode name, and keeps its three existing fields
  unchanged (`model`, `provider`, `embedding_model` — `config.py:11-13`)
  - `embedding_model` is retained though nothing consumes it any more (RAGAS `answer_similarity` was
    its only consumer; neither shipped metric uses embeddings)
- No `score` block, no metric-selection keys, and no rubric key: one metric per mode means nothing to
  select, and the llm metric's rubric is AK-owned until a per-test source is decided
- Legacy keys are rejected rather than ignored, so the clean break fails loudly
  - `AKTestConfig` sets `extra="ignore"` (`config.py:40`), so a leftover `judge:` block would otherwise
    be **silently dropped**, reverting the model/provider to defaults with no error
  - A present `judge` key (in YAML or as `AK_TEST__JUDGE__*`) raises `AKConfigError` naming the new
    `llm` spelling; this is a validation error, not a compatibility shim
- Env-var spellings for new fields follow the existing convention: `AK_TEST__EVALUATOR`,
  `AK_TEST__LLM__MODEL`

### Evaluator selection

- `AKEvaluatorFactory` follows the #541 house pattern (`ak-py/src/agentkernel/core/util/factory.py`)
  - Built-in short names resolved by `if/elif` + real imports; any other value resolved by
    `resolve_dotted(path, base=AKEvaluator)` so users can bring their own
  - Missing optional dependency reported via `require_extra` (`factory.py:50`); invalid configuration
    raises `AKConfigError` (`factory.py:18`)
- Evaluator instance lifetime
  - One instance per `Test` instance; `Test.compare`'s static path uses a lazily built singleton held
    **inside the evaluator package**, guarded by an `RLock` like `AKTestConfig` (`config.py:30`)
  - `Test` itself does not move and holds no backend client — a client cached on `Test` is exactly the
    state this change removes (`test.py:25-26`)
  - The singleton exposes a `_reset()` classmethod paired with `AKTestConfig._reset()` (`config.py:53`),
    so a test that swaps config does not keep scoring through an evaluator built from the old one
  - Instances must be safe to share across threads, since evaluators are reused across tests
- The evaluator is resolved for every mode, including `score`, because score mode runs the evaluator's
  own `score_based_evaluation`
  - `DeepEvalEvaluator` therefore needs the `deepeval` package in every mode; the import happens inside
    `require_extra` (`factory.py:50`), the repo-wide pattern for turning `ModuleNotFoundError` into an
    actionable message
  - Module-level imports in `agentkernel.test` stay free of `deepeval` so importing the harness does
    not require it

### `DeepEvalEvaluator`

- Ships as part of the `test` extra, exactly as `ragas` did — one dependency line, no new extra
- **Score metric: `quasi_contains`** via `deepeval.scorer.Scorer`, wrapped in a custom `BaseMetric` as
  DeepEval documents for statistical scoring
  - SQuAD-style normalised containment (case, punctuation, and article normalisation, then a
    containment test), so a verbose correct answer still matches a short expected phrase
  - Chosen because it is the only option that is simultaneously DeepEval-specific (Opik, RAGAS, and
    autoevals all ship ROUGE/BLEU/BERTScore/exact-match; none ship normalised containment), needs no
    extra dependency, downloads no model, and runs offline — so `agentkernel[test]` stays light and
    score mode never touches the network (survey §9)
  - It returns a binary 0/1, with two accepted consequences: `threshold` is inert on the score path
    (any value in `(0, 1]` behaves identically), and in `fallback` a near-miss reaches the llm stage
    rather than passing locally (survey §12). That cost is proportional — only failing comparisons pay
    it — and close to today's behaviour, since the length-sensitive `fuzz.ratio` already falls through
    for long responses against short expectations
  - The model-backed scorers (`faithfulness` via SummaC, `hallucination` via Vectara HHEM,
    `answer_relevancy` via a sentence-transformers cross-encoder) are **not** shipped: each pulls
    PyTorch and a first-run model download into every environment installing the `test` extra
- **Llm metric: `GEval`**
  - One AK-owned rubric, judging whether the response conveys the same information as `expected`, with
    `evaluation_params=[ACTUAL_OUTPUT, EXPECTED_OUTPUT]`
  - Required because DeepEval ships no semantic-similarity metric (survey §3), so the RAGAS
    `answer_similarity` path has no drop-in replacement other than a rubric-based judge
  - **Behavioural change**: today, `judge` mode with no expected answers falls back to RAGAS
    `answer_relevancy` against the question (`test.py:201-217`). That path is dropped — `llm` mode now
    requires `expected` and raises `AKMissingInput` without it. Every in-repo caller already passes
    expectations, and `expect()` requires them by signature (`test.py:264`)
  - AK owns the default rubric; overriding it per test is deferred (see the payload section)
  - Constructed with `threshold=None` (DeepEval's score-only mode), `include_reason=True`, and the
    `LiteLLMModel` from "LLM model construction"
- Maps `AKEvaluationCase` → `LLMTestCase(input, actual_output, expected_output)`
- Translates a soft backend failure (`metric.error`, a `None` score) into a raised `AKEvaluationError`
  rather than a low score
- **Behavioural change**: score mode no longer computes a rapidfuzz ratio, so a response that scored
  just above the old threshold may now score differently on a different scale

### No outbound data

- **Nothing about a user's tests may reach DeepEval or Confident AI.** Evaluation is local except for
  the judge call that the user's own `llm.model` / `llm.provider` configuration makes
- Telemetry is disabled by the harness, not left to the user
  - `DEEPEVAL_TELEMETRY_OPT_OUT` is set via `os.environ.setdefault(..., "1")` **before the first
    `deepeval` import**, since DeepEval initialises telemetry at import time — setting it afterwards is
    too late
  - `setdefault` rather than an unconditional write, so a user who deliberately opts in by exporting
    the variable themselves is respected
- The Confident AI cloud path is never engaged: AK does not call `deepeval.login`, does not set
  `CONFIDENT_API_KEY`, and does not use the hosted dataset/report features. Results stay in-process
- Local state files DeepEval writes into the working directory — `.deepeval/`,
  `.deepeval_telemetry.txt` — are treated as build artefacts: added to `.gitignore`, and relocated out
  of the repository root if DeepEval offers a path override
- Covered by a test asserting the environment variable is set before `deepeval` is imported, so a
  future refactor that moves the import cannot silently re-enable telemetry

### `return_metrics` mode

- A keyword argument on `Test.compare` and `Test.expect`, `return_metrics: bool = False`
  - Per-assertion, so one suite can assert on most comparisons and collect the `AKEvaluationResult`
    for the ones it wants to inspect or report
  - Defaulted, and keyword-only in practice since it is appended after the existing parameters, so
    every current call site keeps working unchanged
- When `False` (default), `compare` and `expect` behave as today: return `None` on success, raise
  `AssertionError` on failure
- When `True`
  - `compare` and `expect` return the decisive `AKEvaluationResult` with `passed`, `threshold`, and
    `mode` stamped, and non-decisive attempts in `attempts`
  - No `AssertionError` is raised for a failing comparison
  - Every other error still raises, unsuppressed: `AKEvaluationError` (judge unavailable),
    `AKMissingInput`, `AKMetricNotSupported`, `AKConfigError`, the `ValueError` for an invalid mode
    (`test.py:239-240`), the `ValueError` for an empty expected list (`test.py:143-144`), and the
    `AssertionError` from `expect` when no response has been recorded (`test.py:271`)
- In `fallback`, the decisive result is the llm result whenever score mode did not pass; the score-mode
  result is recorded in `attempts`

### Harness changes (`Test`)

- **All RAGAS code leaves `test.py`, not just the dependency**: `_fuzzy_compare` and `_judge_compare`
  are deleted, along with the `_ragas_llm` / `_ragas_embeddings` class attributes (`test.py:25-26`) and
  the module-level imports `from datasets import Dataset`, `from ragas import evaluate`,
  `from ragas.metrics import answer_relevancy, answer_similarity`, and `from rapidfuzz import fuzz`
  (`test.py:8-11`). After the change no RAGAS, `datasets`, or `rapidfuzz` symbol appears anywhere in
  `agentkernel.test`; all scoring goes through `AKEvaluator`
- `Test.compare` keeps its existing parameters and stays a synchronous `@staticmethod`; the only
  addition is `return_metrics: bool = False`, appended last, so every current call site is unaffected
  (`examples/transport/nats/app_test.py:105`, `ak-py/src/agentkernel/skills/ak-test/SKILL.md:159`)
- `Test.expect` gains the same argument and forwards it to `compare`
- `compare` retains ownership of: mode validation and selection, iteration over the `expected` list
  with "pass if ANY alternative passes", the fallback chain, and building the `AKEvaluationCase`
- Assertion messages remain recognisable to existing tests that match on them
  (`ak-py/tests/test_cli_tester.py:31`, `:48`, `:73`), with the mode names updated
- `Test.expect` stays `async` and returns whatever `compare` returns

### Threshold scale

- Thresholds become plain floats in `[0.0, 1.0]` on every path, matching what every evaluation library
  returns; the 0–100 scale and the `threshold / 100` conversion into judge scoring (`test.py:251`,
  `test.py:260`) are removed
- `Test.match_threshold` and `Test.compare(threshold=...)` default to `0.5` instead of `50`
  (`test.py:28`, `test.py:221`)
- Thresholding stays in the harness: DeepEval metrics are constructed with `threshold=None`, and
  `passed` is decided by comparing the returned score against the AK threshold
- Out-of-range values (a leftover `50`) raise `ValueError` rather than silently passing everything,
  since any score is below 50 on the new scale
- Call sites carrying explicit thresholds are updated: `examples/transport/nats/app_test.py:111,123`
  and `examples/transport/kafka/app_test.py` (`threshold=10`), plus the docs pages listed under
  Migration surface

### Synchronous evaluation

- Evaluator methods and `Test.compare` are synchronous, because `compare` is called from inside
  running event loops in shipped code — `examples/transport/nats/app_test.py:100-112` and
  `examples/aws-serverless/openai/lambda_test.py:52-56` call it inside `@pytest.mark.asyncio` bodies
  - `asyncio.run()` raises inside a running loop, and the existing `AgentHandler._run_async_sync`
    bridge (`ak-py/src/agentkernel/core/chat_service.py:207-225`) ends in `loop.run_until_complete`,
    which also raises on an already-running loop
- An adapter whose backend is async-only must run the coroutine on a dedicated worker thread with its
  own event loop; a shared helper in the evaluator package provides this so each adapter does not
  reinvent it

### Dependencies

- `deepeval` replaces `ragas` in the `test` extra as a single dependency line, the same way `ragas` was
  declared (`ak-py/pyproject.toml:153`)
- Removed from the `test` extra (`pyproject.toml:152-157`): `ragas`, `datasets`, `pandas`, the
  `langchain_community==0.4.1` pin, and `rapidfuzz` (`:152`), which loses its consumer once
  `_fuzzy_compare` is deleted
- Nothing else is added: `quasi_contains` needs no library, and `litellm` is already there
- DeepEval emits anonymous usage telemetry by default and writes local state files into the working
  directory; both are suppressed — see "No outbound data"
- Installing `deepeval` also installs four pytest plugins — `pytest-xdist`, `pytest-repeat`,
  `pytest-rerunfailures`, `pytest-asyncio` are its runtime dependencies, and pytest auto-loads plugins
  via entry points, so they become active in every AK test session alongside the existing `addopts`
  (`pyproject.toml:212`). RAGAS brought none; the interaction must be verified before merge
- The identical `langchain_community==0.4.1` pin in the `langgraph` extra (`pyproject.toml:45`) is a
  separate pin and is untouched. AK's CI installs every extra (`ak-py/build.sh` runs
  `uv sync --all-extras`, driven by `.github/workflows/test-reusable.yaml:152`), so that pin still
  constrains CI resolution after the `test` one is dropped
- Resolution of `test` + `langgraph` together must be verified after the removal

### Migration surface

The rename touches these current (non-versioned, non-build) surfaces; all must be updated in the same change:

- Code: `ak-py/src/agentkernel/test/test.py`, `ak-py/src/agentkernel/test/config.py:32`
- Tests: `ak-py/tests/test_test_config.py`, `ak-py/tests/test_cli_tester.py`, `ak-py/tests/test_config.py`
- Skills: `ak-py/src/agentkernel/skills/ak-test/SKILL.md:6,42,47-56`, and the `test-config.yaml`
  template embedded in `ak-py/src/agentkernel/skills/ak-init/SKILL.md:338` (there is no separate
  template file)
- Docs: `docs/docs/testing/cli-testing.md`, `docs/docs/testing/automated-testing.md`,
  `docs/docs/testing/overview.md`, `docs/docs/core-concepts/configuration.md`
- Examples: 40 `examples/**/test-config.yaml` files — 34 with `mode: fallback`, 6 with `mode: fuzzy`,
  and every one of them carrying a `judge:` block and a comment naming the old modes
- Versioned docs under `docs/versioned_docs/` are frozen published snapshots and are **not** edited

### Test suite

- Llm-mode unit tests must run offline: a fake `AKEvaluator` subclass registered by dotted path
  replaces the live-LLM calls currently in `ak-py/tests/test_cli_tester.py:35-81`
- Coverage required for: factory resolution (built-in, dotted path, unknown name, missing extra),
  each mode routing to its evaluator method, `return_metrics` true/false per mode, `attempts`
  population in `fallback`, the judge-unavailable path raising rather than reporting a mismatch, and
  `mode: fuzzy` / `mode: judge` and a leftover `judge:` block each failing with a clear error
- `ak-py/tests/test_test_config.py` gains assertions for the new fields, the renamed `llm` block, the
  rejected `mode` values, and the `AKConfigError` raised by a legacy `judge:` key
- Score-mode tests run against the real `quasi_contains` scorer — no model download, no network — and
  assert the new score semantics rather than the old fuzzy ratio

## Non-goals

- Any evaluator backend other than DeepEval. Opik, Braintrust, and RAGAS are not implemented here; the
  factory's dotted-path branch is the extension point until a second built-in is added
- More than one metric per mode, and any config surface for selecting metrics
- Per-call metric or payload configuration: the only argument added to `compare` / `expect` is
  `return_metrics`, and the payload's optional fields stay unpopulated in v1
- `DAGMetric`: it needs a caller-supplied graph object, which no config key can express and no call
  argument may carry under the rule above
- Trace- or trajectory-derived metrics (`TaskCompletion`, `StepEfficiency`, `PlanAdherence`): they read
  instrumentation, not arguments, and need the CLI under test to emit spans (survey §2, Finding 4)
- Tool-call metrics (`ToolCorrectness`, `ArgumentCorrectness`): they need typed `ToolCall` payloads the
  harness cannot currently capture from a CLI subprocess
- Conversational/multi-turn metrics and the turn history they need
- Multimodal metrics and image payloads
- Dataset-level batch evaluation (`deepeval.evaluate(test_cases, metrics)`)
- Editing `docs/versioned_docs/` snapshots

### Verification required in `spec.md`

- The argument direction of `quasi_contains_score(targets, prediction)`: documented as testing whether
  the normalised prediction appears in the normalised target list, which is the reverse of what this
  harness needs (the short expected phrase should be found inside the longer response). AK controls
  which value goes into which argument — confirm against the source and map accordingly
- Whether passing a `LiteLLMModel` instance to a metric is sufficient, or whether DeepEval also
  requires the `USE_LITELLM=1` environment variable its docs mention for litellm-backed judges
- That the configured judge model can actually return schema-constrained JSON: `GEval` parses
  structured verdicts, so a weak or non-JSON-capable model behind `llm.model` fails at evaluation time
  rather than at configuration time
- That opting out of telemetry does not break evaluation in the pinned DeepEval version — the project
  has a history of opt-out regressions (confident-ai/deepeval#1613), so the pin must be tested with
  `DEEPEVAL_TELEMETRY_OPT_OUT=1` set
- Whether DeepEval still creates `.deepeval/` when telemetry is opted out, and whether a path override
  exists to move it out of the user's repository

## Open questions

- None outstanding. Items needing confirmation against the DeepEval source or a pinned version are
  listed under "Verification required in `spec.md`" rather than left as design decisions.
