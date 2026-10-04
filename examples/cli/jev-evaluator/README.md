# Agent Kernel CLI testing with the built-in JEV evaluator

This package demos an OpenAI Agents SDK trivia agent running in Agent Kernel via the CLI, tested
with the **built-in `jev` evaluator** — the [TypeSafe](https://docs.typesafe.ai) JEV judge. Like the
[`opik-evaluator`](../opik-evaluator) example, it shows the built-in evaluator extension point: any short
name registered in [`Test._resolve_evaluator_class`](../../../ak-py/src/agentkernel/test/test.py) works as the
`evaluator` value in `test-config.yaml`.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    python demo.py

To run tests (requires `TYPESAFE_API_KEY` for the judge and `OPENAI_API_KEY` for the agent under test):

    export TYPESAFE_API_KEY=...
    export OPENAI_API_KEY=...
    uv run pytest -s

## The JEV evaluator

Wired in via [`test-config.yaml`](test-config.yaml):

```yaml
mode: llm
evaluator: jev
```

which resolves to `agentkernel.test.core.evaluator.jev.JevAKEvaluator`:

- **`evaluate_by_llm`**: asks JEV one yes/no (Noul) question, "does the actual output convey the
  information in the expected output?", and uses the returned probability as the score.
- **`evaluate_by_score`**: not supported; it raises `AKMetricNotSupported`. `jev` therefore works only with
  `mode: llm`, and `score` or `fallback` mode fails.
- **No `llm:` block**: JEV picks its own model (`jev-latest`, overridable with `TYPESAFE_DEFAULT_MODEL`).
- **Missing key**: without `TYPESAFE_API_KEY`, the test fails with `AKEvaluationError`, never with a score of 0.

**Outbound data:** every judged comparison sends the user input, expected output and actual output to
`api.typesafe.ai`. For sensitive data, use `deepeval` or `opik` (judged by your own LLM) instead.

Requires the `jev` extra (`pip install "agentkernel[jev]"`), already declared in this package's
[`pyproject.toml`](pyproject.toml).

See [`agentkernel.test.core.evaluator.jev`](../../../ak-py/src/agentkernel/test/core/evaluator/jev.py)
for the implementation, and
[`docs/docs/testing/cli-testing.md`](../../../docs/docs/testing/cli-testing.md#configuration-based-mode)
for the general test-config documentation.
