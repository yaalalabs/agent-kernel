# ak-bench-app

The Agent Kernel app that `ak-bench` deploys and loads. One code base for every host; each host's deployment folder
under [deploy/](deploy/) packages and configures it.

- **Agent:** a mock agent (`MockAgent`) when both `AK_BENCH_MOCK_AGENT_MIN_DELAY_S` and
  `AK_BENCH_MOCK_AGENT_MAX_DELAY_S` are set (by `ak-bench deploy`, from `ak-bench.yaml` `mock_agent`): it waits a random delay in that
  range and echoes the prompt, so the benchmark measures Agent Kernel rather than a model. With neither set, a real
  OpenAI agent under the same name (`bench`) that repeats the message (needs `OPENAI_API_KEY`, resolved through
  Agent Kernel's secret capability). Setting only one of the two is an error at startup.
- **Auth:** `BenchIdentityProvider` accepts only tokens of the form `<user>.<hex HMAC-SHA256(secret, user)>`, signed
  with the deployment's secret (`AK_BENCH_AUTH_SECRET`, resolved through Agent Kernel's secret capability).
- **Config:** [config.yaml](config.yaml) sets the in-memory session, `TRACE` logging, `execution.mode: async`,
  `execution.message_type: complete` and the identity provider. Host-specific keys come from the deployment folder.
- **Entry points:** [agent.py](agent.py) only registers the agent; it starts no server. Each deployment folder has
  its own entry files, one per tier, that `import agent` and hand over to the host's entry point (Lambda:
  `handler = ServerlessAgentRunner.handle`, ...; ECS: `AgentRunner.run`, `AWSWebsocketAPI.run()`).

## Test

```bash
cd benchmarks/app
uv run pytest -q
```
