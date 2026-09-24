# Agent Kernel — resolving secrets from the environment (OpenAI Agents SDK)

This demo shows Agent Kernel's secret capability with the default `env` provider: agents read their
secrets through `SecretManager` instead of `os.environ`, so the same code later reads them from a
managed store (e.g. AWS SSM Parameter Store) by changing only `config.yaml`.

- **Model key** — `demo.py` resolves `OPENAI_API_KEY` at startup and hands it to the SDK in memory:
  ```python
  set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))
  ```
  A missing key fails at startup with `SecretNotFoundError`, not on the first model call.
- **Tool secret** — the `get_weather` tool reads an optional `WEATHER_API_KEY` with
  `get("WEATHER_API_KEY", default=None)`, and reports the service as not configured when it is unset.

`config.yaml` selects the provider explicitly (it is also the default, so the block could be omitted):

```yaml
secret:
  provider:
    type: env
  cache_ttl: 300
```

How a key resolves: a set, non-empty environment variable of that name wins; an empty one is treated
as absent. Resolved values are cached for `cache_ttl` seconds and are never written back to the
environment.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    export OPENAI_API_KEY=<OPENAI_API_KEY>
    export WEATHER_API_KEY=<any value>   # optional; unset it to see the tool degrade
    python demo.py

To run tests (the test sets `WEATHER_API_KEY` itself; `OPENAI_API_KEY` must be exported):

    uv run pytest -s
