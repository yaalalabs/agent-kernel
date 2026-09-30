# #773: Add a built-in `jev` test evaluator (TypeSafe JEV) and a CLI example run in CI — Implementation Spec

Implements the requirements in [`design.md`](design.md). It adds a `JevAKEvaluator` in
`ak-py/src/agentkernel/test/core/evaluator/jev.py`, registers it under the short name `jev`, ships it behind a
new `jev` extra (`typesafe-sdk`), and adds `examples/cli/jev-evaluator/` to the CI e2e matrix. The example
gets the API key from the `TYPESAFE_API_KEY` GitHub secret. The idea: JEV is an API-only judge. The
evaluator asks one Noul (yes/no) question per comparison, and the returned probability is the score.
`evaluate_by_score` is rejected with `AKMetricNotSupported`.

## Verification performed for this spec

Each item below was checked against `develop` at `d51d7426` or against the installed `typesafe-sdk==0.7.2`
wheel, not taken from the docs alone.

- SDK public surface (`dir(typesafe_sdk)`): `TypeSafeClient`, `Noul`, `NoulCriteria`, `SystemOneResponse`,
  `NoulAnswer`, `Usage`, `RetryPolicy`, `TypeSafeError`, `TypeSafeAPIError`, `TypeSafeAuthenticationError`,
  `TypeSafeRateLimitError`, `TypeSafeAPIConnectionError`, `TypeSafeAPITimeoutError`,
  `TypeSafeAPIResponseValidationError` (among others)
- `TypeSafeClient.__init__(self, *, api_key=None, model=None, retry=None, timeout=None, headers=None, transport=None, http_client=None, base_url=None)`
- `TypeSafeClient.system_one(self, state: JSONContent, questions: Mapping[str, Noul | Choice | Score | ...], *, model=None, retry=None, timeout=None, extra_headers=None, extra_body=None, response_model=None) -> SystemOneResponse`
- `Noul(*, type='noul', instructions: JSONContent | None = None, criteria: NoulCriteria | None = None)`
  - `NoulCriteria` is a `TypedDict` with optional keys `true` / `false` (`_core/question_types.py:14-22`), so it is passed as a plain dict
- Missing key, empirically checked: `TypeSafeClient()` with `TYPESAFE_API_KEY` unset raises
  `TypeSafeError("No API key was provided. Pass api_key or set the TYPESAFE_API_KEY environment variable.")` at **construction**
- Invalid key, empirically checked: `system_one(...)` with `api_key="bad"` raises `TypeSafeAuthenticationError`
  (MRO: `TypeSafeAuthenticationError → TypeSafeAPIError → TypeSafeError → Exception`)
- Every SDK error subclasses `TypeSafeError`, so one `except TypeSafeError` covers construction, transport, HTTP-status and response-validation failures
- `SystemOneResponse` fields: `model: str`, `usage: Usage`, `answers: dict[str, Answer]`, plus a `nouls` property holding `dict[str, NoulAnswer]` (`_core/response_types.py:99-116`)
- `NoulAnswer.noul: float`, described as "Probability of a yes answer … from 0 to 1" (`_schemas/models.py:73-80`)
- `Usage.input_tokens: int | None`, `Usage.output_tokens: int | None` (`_core/response_types.py:65-73`)
- Defaults (`typesafe_sdk/constants.py`): `DEFAULT_MODEL = "jev-latest"`, `DEFAULT_MODEL_ENV = "TYPESAFE_DEFAULT_MODEL"`,
  `DEFAULT_TIMEOUT = 10.0`, `API_KEY_ENV = "TYPESAFE_API_KEY"`, `BASE_URL_ENV = "TYPESAFE_BASE_URL"`
- Default `RetryPolicy` (`_core/retry.py:37-80`): `max_retries=2`, exponential backoff from 0.5 s up to a 5 s cap, and retries on
  `{408, 429, 5xx}`, connection errors and timeouts, honouring `Retry-After`
- Package metadata: `Requires-Python: >=3.10`. Runtime deps: `httpx2>=2.0.0`, `pydantic>=2.12.0`,
  `pydantic-core>=2.41.1`, `tenacity>=9.0.0`, `typing-extensions>=4.13.0`
  - ak-py declares `pydantic>=2.11.7` (`ak-py/pyproject.toml:17`), and `ak-py/uv.lock` already resolves `2.12.5` / `2.13.5`, so there's no conflict. `httpx2` is a separate distribution from `httpx` and doesn't collide with the `httpx>=0.27.0` pins (`pyproject.toml:124-137`)
- ak-py's CI unit-test job runs `ak-py/build.sh`, which does `uv sync --all-extras --no-extra crewai` (`ak-py/build.sh:13`). The new `jev` extra is therefore installed for `ak-py/tests`, the same way `opik` is today

## Design

### Package layout

```
ak-py/src/agentkernel/test/core/evaluator/
├── __init__.py      # unchanged — stays SDK-free
├── base.py          # unchanged
├── deepeval.py      # unchanged
├── opik.py          # unchanged
└── jev.py           # NEW — JevAKEvaluator; the only module importing typesafe_sdk
```

The module is named `jev.py`, not `typesafe.py`. The SDK's import name is `typesafe_sdk`, so no name can shadow it.
That's unlike `opik.py`, which needs `test_opik_module_does_not_shadow_third_party_package`.

### `test/core/evaluator/jev.py`

```python
from threading import Lock

from typesafe_sdk import Noul, TypeSafeClient, TypeSafeError

from agentkernel.test.config import AKTestConfig

from .base import AKEvaluationCase, AKEvaluationError, AKEvaluationResult, AKEvaluator, AKMetricNotSupported, AKMissingInput

_QUESTION_ID = "conveys_expected"

_DEFAULT_INSTRUCTIONS = (...)   # "Does actual_output correctly convey the information in expected_output, as an answer to user_input?"
_DEFAULT_CRITERIA = {           # NoulCriteria TypedDict
    "true": (...),              # every concrete fact in expected_output is stated or clearly implied; extra correct,
                                # non-contradictory detail and different wording/length do NOT count against it
    "false": (...),             # a required fact is missing, contradicted, or conflicts with expected_output
}


class JevAKEvaluator(AKEvaluator):
    """TypeSafe JEV judge. llm mode only. Sends user_input/expected/actual to api.typesafe.ai."""

    def __init__(self, config: AKTestConfig) -> None:
        super().__init__(config)
        self._client: TypeSafeClient | None = None   # lazy: the SDK constructor raises without TYPESAFE_API_KEY
        self._client_lock = Lock()

    def _get_client(self) -> TypeSafeClient: ...     # double-checked lazy init under _client_lock

    def evaluate_by_score(self, case: AKEvaluationCase) -> AKEvaluationResult:
        raise AKMetricNotSupported("evaluator 'jev' has no score-based metric; set mode: llm in test-config.yaml")

    def evaluate_by_llm(self, case: AKEvaluationCase) -> AKEvaluationResult: ...
```

Rules:

1. **SDK imports are top-level in `jev.py` only.** `Test._resolve_evaluator_class` imports the module inside
   `require_extra`, so a missing SDK surfaces as the actionable `ImportError`. This is the same shape as `opik.py:10`.
2. **The client is built lazily and at most once.** The first `evaluate_by_llm` call that reaches the API builds it.
   - It isn't built in `__init__`: `Test._resolve_evaluator` constructs the evaluator on every `compare` path
     (`test.py:130-146`), and the SDK constructor raises without a key. Eager construction would turn a missing
     key into a failure at resolution time, outside the `AKEvaluationError` mapping below.
   - `_get_client` is a double-checked lock (`if self._client is None: with self._client_lock: if self._client is None: …`).
     One evaluator instance is shared per process (`test.py:27-28`, `:130-146`), so the check-then-act has to be race-free even though pytest normally drives it from one thread.
   - A construction failure is not cached. `self._client` stays `None`, so the next call retries. That keeps a
     key exported mid-session from staying stuck on the first error.
   - It's constructed as `TypeSafeClient()` with **no arguments**. The key comes from `TYPESAFE_API_KEY`, the model from
     `TYPESAFE_DEFAULT_MODEL` (default `jev-latest`), the base URL from `TYPESAFE_BASE_URL`, and retry/timeout use the SDK
     defaults listed above. AK passes nothing, so the SDK's defaults apply unchanged (AGENTS.md, "No hidden defaults").
   - The client is never closed explicitly. It lives for the process, the same lifetime as the cached evaluator,
     and there's no teardown hook on `AKEvaluator`.
3. **The evaluator never reads `self._config.llm`.** `_LlmConfig` defaults to `gpt-4o-mini` / `openai`
   (`config.py:11-12`), which aren't JEV model ids.

### `evaluate_by_llm` algorithm

1. If `not case.expected`, raise `AKMissingInput("evaluate_by_llm requires AKEvaluationCase.expected")` (same message as `opik.py:61`).
2. If `not case.actual`, return `AKEvaluationResult(metric="noul", evaluator="jev", score=0.0, passed=False, reason="actual output is empty; nothing to judge")` without building the client or calling the API (mirrors `opik.py:62-71`).
3. Build the question:
   - Default: `Noul(instructions=_DEFAULT_INSTRUCTIONS, criteria=_DEFAULT_CRITERIA)`
   - With `case.criteria` set: `Noul(instructions=case.criteria)`, with **no** `criteria`. The caller's rubric is then the only
     rubric. Keeping AK's true/false descriptions could contradict it.
4. Build `state` as a JSON object, not a packed string: `{"user_input": case.user_input, "expected_output": case.expected, "actual_output": case.actual}`.
   - `state` accepts `JSONContent` (verified signature). A keyed object keeps the three fields apart without a prose
     template. This meets design.md's "state packs user input, expected output and actual output".
     `opik.py:80` packs into one string only because Opik's `GEval.score()` takes a single `output` string.
5. Inside one `try` block, call `self._get_client().system_one(state=state, questions={_QUESTION_ID: question})`.
   - `except TypeSafeError as exc: raise AKEvaluationError(f"jev llm-based evaluation failed: {exc}") from exc`
   - Only `TypeSafeError` is caught. Anything else (a bug in AK) propagates unchanged, the same scope as the
     SDK's own error hierarchy. Opik catches bare `Exception` (`opik.py:83`), but that's because Opik's SDK
     has no common base class. The narrower scope here is deliberate.
6. Read `answer = response.nouls.get(_QUESTION_ID)`. If it's `None`, raise
   `AKEvaluationError("jev response contained no noul answer for '<id>'")`. Never substitute `0.0`.
7. `score = float(answer.noul)`, not clamped. The SDK schema documents it as 0–1, and `AKEvaluationResult.score` is `[0.0, 1.0]` (`base.py:35`).
8. Return:
   ```python
   AKEvaluationResult(
       metric="noul",
       evaluator="jev",
       score=score,
       passed=score >= case.threshold,
       reason=None,          # a Noul returns a probability only, no rationale
       cost=None,            # the API reports tokens, not currency
       metadata={"model": response.model, "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
   )
   ```
   `threshold`, `mode`, `expected` and `attempts` are left unset. `Test._stamp` owns them (`test.py:238-245`).

### Factory registration (`test/test.py`)

```python
_BUILTIN_EVALUATORS = ["deepeval", "opik", "jev"]                  # test.py:14

        if configured == "jev":                                      # after the opik branch (test.py:153-156), before the "." check
            with require_extra("jev", "evaluator: jev"):
                from .core.evaluator.jev import JevAKEvaluator
            return JevAKEvaluator
```

- `require_extra` comes from `core/util/factory.py:50-65` and is already imported (`test.py:9`)
- Missing SDK: `ImportError("evaluator: jev requires the 'jev' extra: pip install \"agentkernel[jev]\"")`
- The unknown-name `AKConfigError` message (`test.py:158-160`) picks up `jev` automatically through `_BUILTIN_EVALUATORS`
- The dotted-path branch, caching (`_evaluator`, `_evaluator_lock`) and `Test.compare` are unchanged

### Packaging (`ak-py/pyproject.toml`)

```toml
jev = [
    "typesafe-sdk>=0.7.2,<0.8",
]
```

- Goes directly after `opik` (`pyproject.toml:191-193`)
- The design left "`typesafe-sdk` is 0.x; upper bound?" open. This spec proposes `<0.8`: in 0.x, minor bumps may break
  the API, and this adapter depends on `nouls`, `NoulCriteria` and the error hierarchy. It stays open for the reviewer (see Open items)
- It's not added to the `test` extra, and there's no `[tool.uv.conflicts]` entry. No known conflict exists, but `uv lock` must succeed (see Testing)
- `ak-py/uv.lock` is regenerated

### Example (`examples/cli/jev-evaluator/`)

Copied from `examples/cli/opik-evaluator/` file by file:

| File | Content |
|---|---|
| `demo.py` | Identical to `opik-evaluator/demo.py` (OpenAI Agents trivia agent, `CLI.main()`) |
| `demo_test.py` | Identical to `opik-evaluator/demo_test.py`: session-scoped `Test("demo.py")` fixture, two ordered `send` / `expect` tests |
| `test-config.yaml` | `mode: llm`, `evaluator: jev`, no `llm:` block. A comment explains that `jev` rejects `score` / `fallback` and reads `TYPESAFE_API_KEY` |
| `pyproject.toml` | `name = "cli-jev-evaluator"`. `dependencies = ["agentkernel[cli,openai]>=<next release>"]`. Dev group `agentkernel[test,jev]>=<next release>` plus the same tool pins as the Opik example |
| `build.sh` | Identical to `opik-evaluator/build.sh` |
| `uv.lock` | Generated with `uv lock` against the local build |
| `README.md` | Opik README structure: what `jev` does, `mode: llm` only, required `TYPESAFE_API_KEY` **and** `OPENAI_API_KEY` (the agent under test), and the outbound-data note |

- `test-config.yaml` has no `llm:` block because `jev` doesn't read it. Including one would suggest otherwise.
- Registered in `.github/test-config.yaml` directly after the Opik entry (`:65-66`):
  ```yaml
      - type: cli
        path: examples/cli/jev-evaluator
  ```
  `run_single_test.py` runs it as a simple test: `./build.sh local`, then `uv run pytest -s` (`.github/scripts/run_single_test.py:87-110`)

### CI secret wiring

Secret name: `TYPESAFE_API_KEY`, the SDK's native variable (`constants.API_KEY_ENV`).

| File | Location | Change |
|---|---|---|
| `.github/workflows/test-reusable.yaml` | `on.workflow_call.secrets` (`:21-33`) | add `TYPESAFE_API_KEY: { required: false }` in the same block style as `WALLED_API_KEY` (`:28-29`) |
| `.github/workflows/test-reusable.yaml` | e2e step `Run test - ${{ matrix.path }}` `env:` (`:240-244`) | add `TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}` |
| `.github/workflows/test.yaml` | `e2e-tests.secrets` (`:93-99`) | add `TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}` |
| `.github/workflows/test-trusted-pr.yaml` | `secrets` (`:42-47`) | add `TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}` |

- `test-reusable.yaml` has exactly two callers, `test.yaml:87` and `test-trusted-pr.yaml:36` (verified with `grep -rn "test-reusable.yaml" .github/workflows`)
- The key is **not** added to the ak-py unit-test step `env:` (`test-reusable.yaml:152-153`). The unit tests mock the SDK and need no key
- `test-trusted-pr.yaml` already lacks `WALLED_API_KEY` (`:42-47` vs `test.yaml:96-97`). This change doesn't fix that pre-existing gap. It's out of scope and noted here so the omission isn't read as a pattern
- Manual prerequisite: a repository admin adds `TYPESAFE_API_KEY` under repository **Settings → Secrets and variables → Actions**. The PR can't do this
- Unset or empty secret: GitHub passes an empty string. The SDK treats that as missing and raises `TypeSafeError` when the client is constructed, which surfaces as `AKEvaluationError` from `Test.compare`. The e2e job for `examples/cli/jev-evaluator` fails loudly and never reports a content mismatch
- Fork PRs: `run_e2e_tests` is false (`test.yaml:91-92`), so the example doesn't run. Labelled `safe-to-test` fork PRs run it with the secret (`test-trusted-pr.yaml:20-21`)

### Consumer changes

- `Test._resolve_evaluator_class`: one new branch. The other branches are verified unchanged
- `Test.compare` / `Test.expect`: unchanged. Under `mode: fallback` or `mode: score` with `evaluator: jev`, the
  `AKMetricNotSupported` from `evaluate_by_score` propagates out of `compare` (`test.py:210`, `:214`), as #555 specifies.
  The exception message tells the user to set `mode: llm`
- `agentkernel.test.core.evaluator.__init__`: unchanged. `JevAKEvaluator` isn't exported from it, the same as `OpikAKEvaluator`

### Config changes

- No new fields, models or env vars in `AKTestConfig`
- `AKTestConfig.evaluator.description` (`config.py:35`) becomes
  `"Built-in evaluator short name ('deepeval', 'opik' or 'jev') or a dotted path to an AKEvaluator subclass"`.
  No test asserts on this string (verified with grep over `ak-py/tests`)
- Env vars the SDK reads on its own, documented but not declared by AK: `TYPESAFE_API_KEY` (required),
  `TYPESAFE_DEFAULT_MODEL`, `TYPESAFE_BASE_URL`, `TYPESAFE_LOG_LEVEL`
- Existing YAML and `AK_TEST__*` env vars are unaffected. `AK_TEST__EVALUATOR=jev` works through the existing field

### Behavioural changes

1. `evaluator: jev` becomes a valid value. Before this change it raised `AKConfigError("unknown evaluator 'jev' …")`. Intentional, the feature.
2. The unknown-evaluator `AKConfigError` message now lists `['deepeval', 'opik', 'jev']`. Intentional, a side effect of rule 1.
3. With `evaluator: jev`, comparison text leaves the process for `api.typesafe.ai`. Intentional and documented (design.md, "Outbound data").

**Non-changes:** `AKEvaluator` / `AKEvaluationCase` / `AKEvaluationResult` signatures and fields; `Test.compare`
fallback semantics; the default `evaluator` (`deepeval`) and default `mode` (`fallback`); the `test` extra's contents;
`agentkernel.test.core.evaluator` exports; every existing example config.

## Error handling

| Condition | Where | Surfaces as |
|---|---|---|
| `typesafe-sdk` not installed | `Test._resolve_evaluator_class("jev")` | `ImportError` naming `agentkernel[jev]` |
| `mode: score` or `mode: fallback` | `JevAKEvaluator.evaluate_by_score` | `AKMetricNotSupported` ("set mode: llm"), propagated by `compare` |
| `expected` missing | `evaluate_by_llm` step 1 | `AKMissingInput` |
| `actual` empty | `evaluate_by_llm` step 2 | scored result `0.0`, `passed=False`, which becomes `AssertionError` from `compare` unless `return_metrics` is set; no network call |
| `TYPESAFE_API_KEY` unset or empty | `_get_client` → `TypeSafeClient()` | `TypeSafeError` → `AKEvaluationError`; client not cached |
| Invalid key (401), permission (403), bad request / over the 64k/32k token budget (400/422) | `system_one` | `TypeSafe*Error` → `AKEvaluationError` |
| Rate limit (429), 5xx, timeout, connection error | `system_one` after the SDK's own 2 retries | `TypeSafe*Error` → `AKEvaluationError` |
| Malformed body | SDK response decoding | `TypeSafeAPIResponseValidationError` → `AKEvaluationError` |
| Response has no Noul answer under `_QUESTION_ID` | `evaluate_by_llm` step 6 | `AKEvaluationError` |

In no case does a failure produce `score=0.0`. `0.0` only ever comes from step 2 or from a real Noul value (base contract, `base.py:10-12`).

## Testing

### New: `ak-py/tests/test_evaluator_jev.py`

Offline. `agentkernel.test.core.evaluator.jev.TypeSafeClient` is monkeypatched with a `_FakeTypeSafeClient`
that records `instances` and `system_one` calls. It returns a configurable `SystemOneResponse`-shaped object
(`.model`, `.usage.input_tokens/.output_tokens`, `.nouls`) or raises a configured error. The shape follows the
`_FakeGEval` autouse fixture in `test_evaluator_opik.py:96-103`. SDK exceptions are constructed as the real classes
from `typesafe_sdk`, so the `except TypeSafeError` scope is exercised for real.

- `evaluate_by_score` raises `AKMetricNotSupported`, and the message contains `mode: llm`
- `evaluate_by_llm`
  - success: `noul=0.9`, `threshold=0.5` gives `score == 0.9`, `passed is True`, `metric == "noul"`, `evaluator == "jev"`, `reason is None`, `cost is None`
  - fail: `noul=0.2` gives `passed is False`, and it's a scored result, not an exception
  - boundary: `noul == threshold` gives `passed is True`
  - `metadata == {"model": …, "input_tokens": …, "output_tokens": …}` from the fake response
  - state and question: the recorded call's `state` equals the three-key dict, the question id is `"conveys_expected"`, and the question carries the default instructions and criteria
  - `case.criteria` override: the question's `instructions == case.criteria`, and `criteria` is absent
  - `AKMissingInput` when `expected` is `None` or `""`, and no client is constructed
  - empty `actual`: scored `0.0` / `passed is False`, `"empty" in reason`, no client constructed, no call
  - `TypeSafeAuthenticationError` from `system_one` becomes `AKEvaluationError`, with `__cause__` set
  - `TypeSafeError` from the constructor (missing key) becomes `AKEvaluationError`. A second call constructs again, so the failure isn't cached
  - a non-`TypeSafeError` exception (`RuntimeError`) from `system_one` propagates unwrapped
  - a response with no Noul answer raises `AKEvaluationError`
- Client lifecycle: the constructor isn't called in `JevAKEvaluator.__init__`, and two successful `evaluate_by_llm` calls construct exactly one client
- Missing key, end to end with the **real** SDK: monkeypatch `TYPESAFE_API_KEY` away, don't patch `TypeSafeClient`, and assert `AKEvaluationError` matching `"No API key"`. No network is reached, because the SDK raises before any request

### Changed: `ak-py/tests/test_cli_tester.py`

Following `test_resolve_evaluator_class_builtin_opik` / `..._opik_missing_extra_raises_import_error` (`:363-386`):

- `test_resolve_evaluator_class_builtin_jev`: `CliTest._resolve_evaluator_class("jev") is JevAKEvaluator`
- `test_resolve_evaluator_class_jev_missing_extra_raises_import_error`: patch `builtins.__import__` to fail for `typesafe_sdk` / `typesafe_sdk.*`, `delitem` `agentkernel.test.core.evaluator.jev` from `sys.modules`, and assert an `ImportError` matching `agentkernel\[jev\]`
- `test_compare_jev_under_fallback_raises_metric_not_supported`: set `evaluator: jev` and `mode: fallback` through the config-reset pattern the caching tests use, then `Test.compare(...)` raises `AKMetricNotSupported` before any client is built. This is the riskiest consumer path: the default mode combined with a judge-only built-in

### Live check

`examples/cli/jev-evaluator` in the CI e2e matrix, with `TYPESAFE_API_KEY` and `OPENAI_API_KEY` from secrets.

### Commands

```bash
cd ak-py && uv lock && ./build.sh && uv run pytest tests/test_evaluator_jev.py tests/test_cli_tester.py -v
make lint-check-all
cd examples/cli/jev-evaluator && ./build.sh local && TYPESAFE_API_KEY=… OPENAI_API_KEY=… uv run pytest -s
```

## Migration surface (docs and skills)

Per `ak-dev-new-evaluator-provider` step 7. Each surface lists the built-ins by name and gains `jev`, with its `mode: llm`
constraint and the outbound-data note where the surface describes behaviour:

- `ak-py/src/agentkernel/test/config.py:35`: field description (see Config changes)
- `docs/docs/core-concepts/configuration.md` (~`:730`, "Evaluator backend")
- `docs/docs/testing/cli-testing.md` (`:162` YAML comment, `:176-181` "Built-in evaluators" paragraph and example links)
- `docs/docs/testing/automated-testing.md` (`:47-49`, `:72-78` score/llm prose)
- `docs/docs/testing/overview.md` (`:85`, `:103-106`, `:154`)
- `docs/docs/agent-skills.md:132`: `ak-dev-new-evaluator-provider` row ("beyond DeepEval and Opik" becomes "… Opik and JEV")
- `ak-py/README.md` (~`:1181`, `:1203-1204`, `:1566`, `:1836`)
- `.agents/skills/ak-dev-testing-conventions/SKILL.md` (~`:375`)
- `.agents/skills/ak-dev-new-evaluator-provider/SKILL.md`: `description` ("beyond DeepEval and Opik"), and a new
  "Existing Providers" row: `JEV | jev | — (AKMetricNotSupported) | TypeSafe Noul | agentkernel[jev]`. Also the step-2 snippet's
  `_BUILTIN_EVALUATORS` list
- `ak-py/src/agentkernel/skills/ak-test/SKILL.md` (`:48`, `:61-78`)
- `ak-py/src/agentkernel/skills/ak-test/evals/evals.json`: checked. The mode evals (`:33-53`) don't enumerate
  evaluators, so there's **no change** unless the SKILL.md edit adds an evaluator-selection claim an eval should cover
- `docs/src/pages/features.tsx:1508-1520` ("Pluggable Evaluators" card) and `docs/src/pages/index.tsx:587`: both say
  "DeepEval built in" and already omit Opik. Updated to name DeepEval, Opik and JEV, which also fixes the existing Opik gap
- `docs/versioned_docs/`: not edited

## Open items for review

- `typesafe-sdk` upper bound `<0.8` (proposed here; design.md left it open)
- `case.criteria` override drops AK's true/false criteria entirely (Rule, step 3), rather than merging with them
- The design's open questions on the short name (`jev`) and on Noul vs Score still stand. This spec implements `jev` + Noul
- The SDK's default retry policy is used unchanged (2 retries, 10 s timeout). No example-level override is proposed
