# Agent Kernel CLI testing with the built-in Opik evaluator

This package demos an OpenAI Agents SDK trivia agent running in Agent Kernel via the CLI, tested
with the **built-in `opik` evaluator** — [Opik](https://www.comet.com/docs/opik/) by Comet. It
shows the built-in evaluator extension point: any short name registered in
[`Test._resolve_evaluator_class`](../../../ak-py/src/agentkernel/test/test.py) works as the
`evaluator` value in `test-config.yaml`, alongside the default `deepeval`.

Contrast this with [`examples/cli/custom-evaluator`](../custom-evaluator), which shows the
opposite extension point — a **bring-your-own** `AKEvaluator` referenced by dotted path instead
of a short name.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    python demo.py

To run tests:

    uv run pytest -s

## The Opik evaluator

Wired in via [`test-config.yaml`](test-config.yaml):

```yaml
evaluator: opik
```

which resolves to `agentkernel.test.core.evaluator.opik.OpikAKEvaluator`:

- **`evaluate_by_score`**: Opik's `LevenshteinRatio` metric — a graded, offline string-similarity
  ratio (stdlib/`rapidfuzz`, no LLM call), unlike `deepeval`'s binary whole-string
  `quasi_exact_match_score`.
- **`evaluate_by_llm`**: Opik's `GEval` LLM-as-judge metric, run against the model configured
  under `llm:` in `test-config.yaml`. Opik's trace logging to Comet Cloud is disabled by default
  (`agentkernel.test.core.evaluator.opik` sets `OPIK_TRACK_DISABLE`, and passes `track=False` to
  every metric it constructs), so no Opik Cloud account, API key, or self-hosted server is
  required — the only network calls this evaluator makes are the LLM judge calls themselves.

Requires the `opik` extra (`pip install "agentkernel[opik]"`), already declared in this package's
[`pyproject.toml`](pyproject.toml).

See [`agentkernel.test.core.evaluator.opik`](../../../ak-py/src/agentkernel/test/core/evaluator/opik.py)
for the implementation, and
[`docs/docs/testing/cli-testing.md`](../../../docs/docs/testing/cli-testing.md#configuration-based-mode)
for the general test-config documentation.
