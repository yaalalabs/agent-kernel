# #773: Add a built-in `jev` test evaluator (TypeSafe JEV) and a CLI example run in CI — Implementation Plan

This plan builds [`spec.md`](spec.md) in order: packaging first, then the evaluator on its own, then factory wiring,
then the example, then the CI secret, then tests, then the docs/skills sync. Each iteration leaves the branch
importable and lint-clean.

## Iteration 1: Packaging

- **Goal:** `pip install "agentkernel[jev]"` pulls in `typesafe-sdk`, and the lock resolves.
- **Files:** `ak-py/pyproject.toml`, `ak-py/uv.lock`
- **Steps:**
  1. Add the `jev` extra after `opik`, per spec.md "Packaging".
  2. Run `uv lock` in `ak-py/`.
- **Verify:** `cd ak-py && uv lock && ./build.sh && uv run python -c "import typesafe_sdk"` succeeds.

## Iteration 2: `JevAKEvaluator`

- **Goal:** The evaluator works when called directly. It isn't wired into `Test` yet.
- **Files:** `ak-py/src/agentkernel/test/core/evaluator/jev.py` (new)
- **Steps:**
  1. Add the module constants (`_QUESTION_ID`, `_DEFAULT_INSTRUCTIONS`, `_DEFAULT_CRITERIA`) and the class skeleton, per spec.md "`test/core/evaluator/jev.py`".
  2. Add `_get_client`: lazy, double-checked lock, a failed construction is not cached, no constructor arguments (Rules 2–3).
  3. Make `evaluate_by_score` raise `AKMetricNotSupported` with the `mode: llm` hint.
  4. Implement `evaluate_by_llm` steps 1–8 from spec.md "`evaluate_by_llm` algorithm", with only `TypeSafeError` wrapped in `AKEvaluationError`.
  5. Write the class docstring, including the outbound-data note.
- **Verify:** `uv run python -c "from agentkernel.test.config import AKTestConfig; from agentkernel.test.core.evaluator.jev import JevAKEvaluator; JevAKEvaluator(AKTestConfig())"` succeeds with `TYPESAFE_API_KEY` unset. With a real key, calling `evaluate_by_llm` on a matching pair returns a high score, and on a mismatched pair a low one.

## Iteration 3: Factory registration and config description

- **Goal:** `evaluator: jev` resolves through `Test`.
- **Files:** `ak-py/src/agentkernel/test/test.py`, `ak-py/src/agentkernel/test/config.py`
- **Steps:**
  1. Add `"jev"` to `_BUILTIN_EVALUATORS`, and add the `require_extra("jev", …)` branch after the Opik one, per spec.md "Factory registration".
  2. Update the `evaluator` field description, per spec.md "Config changes".
- **Verify:** `Test._resolve_evaluator_class("jev") is JevAKEvaluator`, and an unknown name's `AKConfigError` message lists `jev`.

## Iteration 4: Example

- **Goal:** `examples/cli/jev-evaluator/` passes locally with real keys.
- **Files:** `examples/cli/jev-evaluator/{demo.py,demo_test.py,test-config.yaml,pyproject.toml,build.sh,uv.lock,README.md}` (new), `.github/test-config.yaml`
- **Steps:**
  1. Copy the Opik example's files and adapt them, per the spec.md "Example" table (`mode: llm`, `evaluator: jev`, no `llm:` block, dev group `agentkernel[test,jev]`).
  2. Build ak-py (`ak-py/build.sh`), then run `./build.sh local` and `uv lock` in the example.
  3. Write the README: requires `TYPESAFE_API_KEY` and `OPENAI_API_KEY`, `mode: llm` only, and the outbound-data note.
  4. Register the example in `.github/test-config.yaml` after the `opik-evaluator` entry.
- **Verify:** `cd examples/cli/jev-evaluator && TYPESAFE_API_KEY=… OPENAI_API_KEY=… uv run pytest -s` passes both tests. With `TYPESAFE_API_KEY` unset, it fails with `AKEvaluationError`, not a content mismatch.

## Iteration 5: CI secret wiring

- **Goal:** The e2e step for the example receives `TYPESAFE_API_KEY` on every path that has secrets.
- **Files:** `.github/workflows/test-reusable.yaml`, `.github/workflows/test.yaml`, `.github/workflows/test-trusted-pr.yaml`
- **Steps:**
  1. Apply the four rows of the spec.md "CI secret wiring" table.
  2. Leave the ak-py unit-test step `env:` unchanged.
- **Verify:** `grep -n TYPESAFE_API_KEY .github/workflows/*.yaml` shows four lines: two in `test-reusable.yaml` (the `workflow_call.secrets` key and the step `env:` entry) and one in each of the two callers. Also confirm the workflows parse, for example with `actionlint` if it's available.
- **Manual, outside the PR:** a repository admin creates the `TYPESAFE_API_KEY` repository secret before merge. Call this out in the PR description.

## Iteration 6: Tests

- **Goal:** Offline coverage of every path in spec.md "Testing".
- **Files:** `ak-py/tests/test_evaluator_jev.py` (new), `ak-py/tests/test_cli_tester.py`
- **Steps:**
  1. Add the `_FakeTypeSafeClient` autouse fixture that patches `agentkernel.test.core.evaluator.jev.TypeSafeClient`.
  2. Write the `test_evaluator_jev.py` cases listed under spec.md "New: …", including the missing-key test that uses the real SDK.
  3. Add the three `test_cli_tester.py` tests from spec.md "Changed: …", following the pattern at `:363-386`.
- **Verify:** `cd ak-py && uv run pytest tests/test_evaluator_jev.py tests/test_cli_tester.py -v` passes with no network, then `make lint-check-all` from the repo root.

## Iteration 7: Sync docs and skills

- **Goal:** Every surface that lists the built-in evaluators names `jev`, along with its `mode: llm` constraint and the outbound-data note.
- **Files:** everything in spec.md "Migration surface":
  - `docs/docs/core-concepts/configuration.md` (~`:730`)
  - `docs/docs/testing/cli-testing.md` (`:162`, `:176-181`)
  - `docs/docs/testing/automated-testing.md` (`:47-49`, `:72-78`)
  - `docs/docs/testing/overview.md` (`:85`, `:103-106`, `:154`)
  - `docs/docs/agent-skills.md:132`
  - `ak-py/README.md` (~`:1181`, `:1203-1204`, `:1566`, `:1836`)
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md` (~`:375`)
  - `.agents/skills/ak-dev-new-evaluator-provider/SKILL.md` (description, Existing Providers table, step-2 snippet)
  - `ak-py/src/agentkernel/skills/ak-test/SKILL.md` (`:48`, `:61-78`)
  - `docs/src/pages/features.tsx:1508-1520`, `docs/src/pages/index.tsx:587`
- **Steps:**
  1. Edit each surface. Re-check line numbers first, because they drift.
  2. Check `ak-py/src/agentkernel/skills/ak-test/evals/evals.json`. It needs no change unless step 1 added a claim about choosing an evaluator that an eval should cover. Record the outcome in the PR.
  3. Don't touch `docs/versioned_docs/`.
  4. Run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows to confirm nothing else drifted.
- **Verify:** `grep -rn "'deepeval' or 'opik'\|deepeval.*opik" docs/docs ak-py/README.md ak-py/src/agentkernel/skills .agents/skills` finds no enumeration that leaves out `jev`. `cd docs && npm run build` succeeds.
