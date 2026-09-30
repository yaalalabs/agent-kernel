# #773: Add a built-in `jev` test evaluator (TypeSafe JEV) and a CLI example run in CI

Adds `jev` as a third built-in `AKEvaluator` (beside `deepeval` and `opik`), backed by TypeSafe's JEV judge
model through the `typesafe-sdk` Python SDK. Ships an `examples/cli/jev-evaluator/` example that uses it, run in CI with
the API key supplied from a GitHub secret. The design idea: JEV is an API-only judge, so it implements only
`evaluate_by_llm` (one Noul yes/no question whose probability is the score) and rejects `evaluate_by_score`.

JEV reference: [quickstart](https://docs.typesafe.ai/introduction/quickstart),
[Noul](https://docs.typesafe.ai/primitives/noul.md), [Python SDK](https://docs.typesafe.ai/sdk/python/usage.md).
Contract background: [`../555-pluggable-test-evaluators/design.md`](../555-pluggable-test-evaluators/design.md).

## Motivation

- The evaluator seam already exists and is meant to be extended
  - `AKEvaluator` has two abstract methods, `evaluate_by_score` / `evaluate_by_llm`, and an error contract (`ak-py/src/agentkernel/test/core/evaluator/base.py:49-66`)
  - Built-ins are registered by a short-name `if` branch (`ak-py/src/agentkernel/test/test.py:148-158`) and listed in `_BUILTIN_EVALUATORS` (`test.py:14`)
- Only two built-ins exist, both self-hosted libraries that judge with the user's own `llm:` model
  - `OpikAKEvaluator` (`core/evaluator/opik.py`) and `DeepevalAKEvaluator` (`core/evaluator/deepeval.py`)
- JEV is a hosted judge with a calibrated probability output, not a general LLM prompt
  - Noul returns a single 0–1 probability of "yes" (docs: Noul); that maps directly onto `AKEvaluationResult.score` in `[0.0, 1.0]` (`base.py:35`)
- A hosted evaluator needs a secret in CI, and the CI secret plumbing is per-secret and explicit
  - `OPENAI_API_KEY` / `WALLED_API_KEY` are declared in `.github/workflows/test-reusable.yaml:26-28`, exported to the e2e step at `:241-242`, and forwarded by callers (`test.yaml:96-97`, `test-trusted-pr.yaml:45`)

## Requirements

### Evaluator class (`JevAKEvaluator`)

- New file `ak-py/src/agentkernel/test/core/evaluator/jev.py`; SDK imports stay in this file only (the `evaluator/__init__.py` stays SDK-free, per `ak-dev-new-evaluator-provider`)
- Subclasses `AKEvaluator`, constructor `__init__(self, config: AKTestConfig)` unchanged (`base.py:56-57`)
- `evaluate_by_score` always raises `AKMetricNotSupported`
  - JEV has no deterministic/offline scorer; faking one would be feature-forcing (AGENTS.md, "No feature-forcing")
- `evaluate_by_llm(case)`
  - Raises `AKMissingInput` when `case.expected` is empty (same as `opik.py:60-61`)
  - Empty `case.actual` returns a scored `0.0` / `passed=False` with no API call (same as `opik.py:62-71`)
  - Otherwise asks **one Noul question** ("does the actual output convey the information in the expected output?")
    - Rubric is directional: extra correct, non-contradictory detail in `actual` must not be penalised (mirrors `opik.py:21-32`); `case.criteria` replaces the default rubric when set (`base.py:29`)
    - `state` packs user input, expected output and actual output, as `opik.py:80` does for its single-string metric
  - `score = answer.noul`; `passed = score >= case.threshold`
  - Result: `metric="noul"`, `evaluator="jev"`, `cost=None`; SDK token usage (`input_tokens`, `output_tokens`) and the model id go in `metadata`
- Failure mapping
  - Any `TypeSafeError` (auth, rate limit, timeout, connection, response validation) is wrapped as `AKEvaluationError`, chained with `from exc`
  - A missing/invalid `TYPESAFE_API_KEY` is an `AKEvaluationError`, never a `0.0` (base contract, `base.py:10-12`)
- Client lifecycle
  - Sync `TypeSafeClient`, built lazily on the first `evaluate_by_llm` call and reused; the SDK constructor raises when the key is missing, so eager construction would break `score` mode and construction-time resolution
  - Sync client matches the synchronous evaluator methods (no event-loop bridge)
  - Instance safe to share across threads (one evaluator instance is cached per run, `test.py:130-146`)
- Input size: the 64k-token request budget (32k for state plus the longest question) is documented, not enforced; an over-budget request surfaces as an `AKEvaluationError`

### Usability constraint: `mode: llm` only

- `AKTestConfig.mode` defaults to `fallback` (`config.py:32`); `Test.compare` runs `evaluate_by_score` first and does not catch `AKMetricNotSupported` (`test.py:214`)
  - #555 rejected catching it on purpose (permanent, structural mismatch should surface once)
- Therefore `evaluator: jev` is usable only with `mode: llm`
  - The example's `test-config.yaml` sets `mode: llm`; docs state the constraint next to the built-in's description
  - This design does **not** change `Test.compare` fallback semantics

### Factory and packaging

- Add `"jev"` to `_BUILTIN_EVALUATORS` (`test.py:14`) and a branch in `Test._resolve_evaluator_class` (`test.py:148-158`) using `require_extra("jev", "evaluator: jev")` around the import of `JevAKEvaluator`
- Dotted-path bring-your-own branch and the unknown-name `AKConfigError` message are unchanged
- New optional extra in `ak-py/pyproject.toml` beside `opik` (`:191-193`): `jev = ["typesafe-sdk>=0.7.2"]`
  - Separate extra, not folded into `test` (which stays DeepEval's); latest PyPI release checked is 0.7.2; SDK needs Python >=3.10, ak-py requires `>=3.12,<3.14` (`pyproject.toml:10`)

### Configuration

- **No new configuration fields.** Reason each candidate was rejected:
  - Model: JEV must not read `llm.model` / `llm.provider` — they default to `gpt-4o-mini` / `openai` (`config.py:11-12`) and are not JEV model ids. The SDK's own default `jev-latest` applies, overridable with the SDK-native `TYPESAFE_DEFAULT_MODEL` env var
  - API key: read by the SDK from `TYPESAFE_API_KEY`; AK adds no key field
- Only the `evaluator` field's `description` string is edited to list `'jev'` (`config.py:35`); the field stays a free-form `str`
- Existing YAML and `AK_*` env vars stay valid

### Example (`examples/cli/jev-evaluator/`)

- Mirrors `examples/cli/opik-evaluator/`: `demo.py`, `demo_test.py`, `test-config.yaml`, `pyproject.toml`, `build.sh`, `README.md`
- `test-config.yaml`: `evaluator: jev`, `mode: llm`
- `pyproject.toml` dev dependency group installs `agentkernel[test,jev]`
- `demo_test.py` asserts through `Test.expect`, so a JEV verdict decides pass/fail
- README documents: `TYPESAFE_API_KEY` requirement, `mode: llm` requirement, and that test text is sent to JEV (see "Outbound data")
- Registered in `.github/test-config.yaml` next to the Opik entry (`:66`)
- The agent under test still needs `OPENAI_API_KEY`; JEV only does the judging

### CI secret (`TYPESAFE_API_KEY`)

- The GitHub secret is named `TYPESAFE_API_KEY`, the SDK's native variable, so no renaming glue is needed
- Every hop, in order
  - `.github/workflows/test-reusable.yaml`: declare under `workflow_call.secrets` with `required: false` (`:21-33`), and export in the e2e step `env:` (`:240-244`)
  - `.github/workflows/test.yaml`: forward in the `secrets:` block (`:94-99`)
  - `.github/workflows/test-trusted-pr.yaml`: forward in the `secrets:` block (`:42-47`)
    - Note this caller already omits `WALLED_API_KEY`, so it is not a complete mirror of `test.yaml`; add `TYPESAFE_API_KEY` deliberately, not by copy
  - `test-reusable.yaml` has exactly two callers (`test.yaml:87`, `test-trusted-pr.yaml:36`)
- Prerequisite outside the PR: a repository admin creates the `TYPESAFE_API_KEY` repository secret; until then the example fails with `AKEvaluationError` in CI
- Fork PRs receive no secrets and skip e2e (`test.yaml:91-92`); labelled-safe fork PRs run via `test-trusted-pr.yaml` and get the secret
- The key is never written to the repo, `test-config.yaml`, or logs

### Outbound data

- Unlike the DeepEval path (#555, "No outbound data"), every `evaluate_by_llm` call sends the user input, expected output and actual output to `api.typesafe.ai`
  - Stated in the class docstring, the example README, and the docs section for the built-in
  - Users testing agents on sensitive data should choose `deepeval`/`opik` (judge on their own LLM) or bring their own evaluator

### Tests

- `ak-py/tests/test_evaluator_jev.py`, following `test_evaluator_deepeval.py`, all offline with the SDK client mocked
  - `evaluate_by_score` raises `AKMetricNotSupported`
  - `evaluate_by_llm`: pass, fail, threshold boundary (`score == threshold` passes), `AKMissingInput` without `expected`, empty `actual` makes no client call
  - `TypeSafeError` (including missing key) becomes `AKEvaluationError`, never a `0.0`
  - Token usage lands in `metadata`; `case.criteria` overrides the default rubric
  - Client constructed lazily and once
  - Factory: `Test._resolve_evaluator_class("jev")` resolves to `JevAKEvaluator`; missing SDK raises `ImportError` naming `agentkernel[jev]` (pattern: `test_resolve_evaluator_class_deepeval_missing_extra_raises_import_error` in `ak-py/tests/test_cli_tester.py`)
- The example is the live end-to-end check, run in the CI e2e matrix

### Documentation and skills

- Follow the doc checklist in `ak-dev-new-evaluator-provider` (step 7); every surface that enumerates the built-ins by name is updated, including
  - `docs/docs/core-concepts/configuration.md` (~`:730`), `docs/docs/testing/{cli-testing,automated-testing,overview}.md`, `docs/docs/agent-skills.md`
  - `ak-py/README.md` (evaluator field ~`:1181`, mode descriptions ~`:1203-1204`, env example ~`:1566`, walkthrough ~`:1836`)
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md` (~`:375`), `.agents/skills/ak-dev-new-evaluator-provider/SKILL.md` ("Existing Providers" table)
  - `ak-py/src/agentkernel/skills/ak-test/SKILL.md` (~`:48-78`) and its `evals/evals.json`
  - `docs/src/pages/features.tsx` / `index.tsx`: checked, updated only if they list evaluators
- The docs state the `mode: llm` constraint and the outbound-data note for `jev`
- `docs/versioned_docs/` is never edited

## Non-goals

- Score or Choice question types; multi-question rubrics; using JEV confidence/probabilities beyond the Noul value
- Emulating `score` mode (local string match) inside the JEV evaluator
- Changing `fallback` so it tolerates `AKMetricNotSupported`
- A `jev:` config block, a JEV model field, or an API-key field
- The async SDK client; custom retry policy beyond the SDK's own `RetryPolicy` defaults
- JEV as the agent under test, or as a tracing/guardrail provider
- Editing `docs/versioned_docs/`

## Open questions

- Short name: `jev` (as requested) vs `typesafe` (vendor/SDK name). Chosen `jev`; confirm
- Noul (chosen; score is the yes-probability) vs a Score question with an ordered rubric that adds a confidence signal
- Should `fallback` support judge-only evaluators in a follow-up, so `jev` is not restricted to `mode: llm`? Out of scope here; conflicts with #555's rationale
- The JEV docs publish no rate limits or pricing; is the SDK's default retry policy acceptable for CI, or should the example pin a timeout?
- `typesafe-sdk` is 0.x; is `>=0.7.2` (unbounded) acceptable or should it carry an upper bound?
- Repo admin must create the `TYPESAFE_API_KEY` secret before merge; who owns that
