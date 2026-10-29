# Claude Agent SDK REST API example

This example serves Claude Agent SDK agents through Agent Kernel's REST API. The `triage` agent
delegates math, general and weather questions to Claude subagents, each declared once as a native
`AgentDefinition` (only `triage` is registered with Agent Kernel). The weather subagent calls a local
Python function bound to `triage` through `ClaudeToolBuilder`.

## Setup

Claude needs an Anthropic API key or configured Bedrock, Vertex AI, or Foundry credentials. For
example:

```bash
export ANTHROPIC_API_KEY=...
./build.sh local
uv run app.py
```

`./build.sh local` installs the branch-built `agentkernel` wheel from `ak-py/dist`; build that wheel
first. After a release containing the Claude adapter is published, `./build.sh` uses PyPI.

## Chat

```bash
curl -s http://localhost:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"agent":"triage","session_id":"example-1","prompt":"What is the weather in Tokyo?"}'
```

Use the same `session_id` for another turn in the conversation. The default session store is
in-memory, so it lasts only while this API process runs. Configure a shared Agent Kernel session
store to continue conversations across processes or replicas.

The example allows only its declared tools: `tools=[]` disables Claude Code's built-in file and
shell tools, and `setting_sources=[]` avoids loading local settings. `permission_mode="dontAsk"`
denies unapproved calls; Agent Kernel approves the bound weather tool and the subagent `Agent`
tool. `strict_mcp_config=True` and `verbatim_prompts=True` keep local MCP configuration and
`@path` expansion out of API requests, and `max_turns=8` bounds a runaway run. The `options()`
helper in `app.py` applies these to every agent.

Each request starts a Claude Code subprocess. Set API request timeouts and process memory for the
number of concurrent requests you expect. To stream token events over SSE, run with
`AK_EXECUTION__MODE=stream uv run app.py`; the same `/api/v1/chat` endpoint then returns an SSE stream.

The credentialed API smoke test can be run with `uv run pytest app_test.py -q`.
