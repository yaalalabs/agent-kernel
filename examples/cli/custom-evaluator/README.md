# Agent Kernel CLI testing with a custom (bring-your-own) evaluator

This package demos an OpenAI Agents SDK trivia agent running in Agent Kernel via the CLI, tested
with a **custom `AKEvaluator`** instead of the built-in `deepeval` one. It shows the pluggable
evaluator extension point described in
[`docs/specs/555-pluggable-test-evaluators`](../../../docs/specs/555-pluggable-test-evaluators):
any dotted path to an `AKEvaluator` subclass works as the `evaluator` value in
`test-config.yaml`, resolved the same way sandbox providers and session stores resolve their own
bring-your-own backends.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    python demo.py

To run tests:

    uv run pytest -s

## The custom evaluator

[`custom_evaluator.py`](custom_evaluator.py) implements `TokenOverlapEvaluator(AKEvaluator)` from
scratch — no DeepEval, no RAGAS:

- **`score_based_evaluation`**: a deterministic, offline Jaccard token-overlap ratio between the
  actual and expected text (stdlib `re` only). This is *graded* partial credit, unlike the
  built-in `deepeval` evaluator's binary whole-string `quasi_exact_match_score`.
- **`llm_based_evaluation`**: a single raw `litellm.completion()` call carrying its own rubric
  prompt, parsed for a bare `0.0`-`1.0` score — no `GEval`, no schema-constrained JSON, no
  DeepEval dependency at all.

Both methods raise `AKMissingInput` if `expected` is missing, and `llm_based_evaluation` raises
`AKEvaluationError` if the judge call fails or returns an unparseable response — the same error
contract every evaluator (built-in or custom) must honor so a broken judge is never mistaken for
a failing agent.

It is wired in via [`test-config.yaml`](test-config.yaml):

```yaml
evaluator: custom_evaluator.TokenOverlapEvaluator
```

which resolves against `custom_evaluator.py` next to this README, because pytest's default import
mode puts the test file's own directory on `sys.path`. No AK extra beyond `test` (for `litellm`)
is required for a custom evaluator — the `deepeval` import lives entirely inside the built-in's
own resolution branch.

See [`agentkernel.test.core.akevaluators`](../../../ak-py/src/agentkernel/test/core/akevaluators)
for the full `AKEvaluator` interface and payload models, and
[`docs/docs/testing/cli-testing.md`](../../../docs/docs/testing/cli-testing.md#bring-your-own-evaluator)
for the general "bring your own evaluator" documentation.
