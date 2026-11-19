# #932 research notes

Supporting facts behind `design.md`. Checked against the code on `feature/932-a2a-mcp-on-aws-lambda`
(from `develop` @ `c514f928c`). Paths are under `ak-py/src/agentkernel/` unless they say otherwise.

## 1. Existing pieces

- **Lambda adapter (#760):** `deployment/aws/serverless/core/event_translator.py` (`LambdaEventTranslator`) and `webhook_host.py`
  - builds a Starlette `Request` from an API Gateway v1 event and calls **one** endpoint; no routing, middleware or lifespan
  - `_proxy_response` raises `TypeError` for a streaming response
  - `webhook_host._run` keeps one event loop and calls `run_until_complete` per request; it never keeps a lifespan open
  - `mangum` is not in `pyproject.toml` or `uv.lock`
- **Queue path:** `RestHandler.request(body, protocol)` (`pipeline/request_handler.py:165`) enqueues with the `protocol` attribute and polls the store;
  A2A (`api/a2a/a2a.py`) and MCP (`api/mcp/akmcp.py`) already call it
- **Store sharing:** `deployment/aws/core/response_store/factory.py` only re-exports the pipeline `ResponseStoreFactory`, so the Lambda workers and the
  request Lambda read and write the same store code
- **Transport type:** `QueueTransportFactory.resolve_type()` returns `in_memory` when no `execution.queues` block exists; the queue URL does not decide it.
  `LambdaWebhookGuard._check_transport` already requires `sqs`

## 2. The Lambda worker copies (G2-G4)

| File (`deployment/aws/serverless/`) | Gap | Shared version |
|---|---|---|
| `akagentrunner.py` `ServerlessAgentRunner` | does not forward `protocol` | `pipeline/agent_runner.py:34` `_FORWARDED_ATTRIBUTES` |
| `akagentrunner.py` `ServerlessStreamAgentRunner.process_message` (`:338`) | only `integration` gets one whole reply | `pipeline/agent_runner.py:416-417` |
| `akresponsehandler.py` `process_message` (`:155`) | WebSocket modes broadcast, nothing stored | `pipeline/response_handler.py:73` |
| `akresponsehandler.py` `on_permanent_failure` (`:195`, `:212`) | same for failures | `pipeline/response_handler.py:110` |

## 3. Behaviours the design must handle

- **MCP replies are SSE by default.** `MCP.get_http_app` calls `http_app(path="/", stateless_http=...)` with FastMCP's default `json_response=False`
  (`api/mcp/akmcp.py:134`), so a tool call answers `text/event-stream`. The current translator would raise `TypeError`.
  Options: buffer the body into one response, or pass `json_response=True` (FastMCP's `http_app` has the parameter; `fastmcp/server/http.py:600`).
  `GET /mcp` (server push) would hold the connection until the gateway's 29 s limit.
- **A2A `return_immediately`.** `DefaultRequestHandler` runs the agent in the background when `configuration.return_immediately` is set
  (a2a-sdk 1.2.3, `default_request_handler.py:420`). Lambda freezes after the response, and `tasks/{id}` may land on another instance.
- **Lifespan.** FastMCP's lifespan opens a task group that must stay open between calls. Nothing in the repo does this on Lambda yet.
- **Redis task store is a placeholder** (`api/a2a/a2a.py:189`, `class RedisTaskStore(InMemoryTaskStore): pass`). `message:send` replies are plain
  messages, so no task store is needed; session continuity comes from the shared session store
- **A2A SDK is `1.2.3`** (`pyproject.toml`), not the `0.3.x` the #780 design mentions
- **Cards and tools come from the agent registry (#983).** `A2A._build` and `MCP._build` read `Runtime.current().registry.descriptors()`
  (`api/a2a/a2a.py:152`, `api/mcp/akmcp.py:154`). With the default in-memory registry the serving process must import the agents; the
  examples keep the request Lambda light (`examples/aws-serverless/openai/pyproject.toml`), so this Lambda then needs the framework
  dependencies and more than the 128 MB default (`modules/request-handler/variables.tf:89`); its timeout default is 30 s (`:80`).
  A shared registry avoids the import but has a cold-start ordering limit (spec: Deviation 12)
- **Paths.** API Gateway is `/<api_base_path>/<api_version>/<endpoint>` in a stage; the app serves `/a2a/{agent}/...` and `/mcp`.
  `a2a.url` and `mcp.url` must be the public URL: the card advertises `a2a.url/<agent>` (`core/builder.py:67`)
- **Card:** `AgentCapabilities(streaming=False)`; `message:stream` is refused (`api/a2a/handler.py`)

## 4. Authentication

- The gateway method is `CUSTOM` on every route when an authorizer exists (`modules/api-gateway/main.tf`)
- `APIGatewayAuthorizer` takes a `WebhookBypass`; it only runs with authorizer caching off (`result_ttl_in_seconds = 0`), because with a TTL
  API Gateway answers a header-less request with 401 first (`akauthorizer.py` docstring)
- The bypass helpers are webhook shaped (`WebhookRouteMatcher.for_integrations`); the authorizer is wired in user code
  (`examples/aws-serverless/slack-openai/lambda_auth.py`)
- Every FastAPI router runs `RequestAuthenticator` (`RESTAPI._get_router_dependencies`), so the app can authenticate from headers alone
- Without an `identity` block the app would not authenticate, so a bypassed route would be open

## 5. Timing

- Defaults: `retry_count` 5 × `delay` 5 s (`core/config.py:657-658`); the first read is immediate, so the real wait is `(retry_count - 1) × delay`
- API Gateway stops waiting at 29 s (raising it is a quota matter; plan for under 29 s)
- Cold start (agent import + `build_app()`) counts against the same 29 s
- An agent run plus queue time over about 29 s fails; with `tasks/{id}` out of scope there is no way around it in v1

## 6. Terraform facts

- Routes allow at most 3 path levels and no `{proxy+}` (`modules/api-gateway/main.tf:13`)
- REST API only when not `async` (`state.tf:41`); response store disabled in `async` (`state.tf:49-51`)
- `async` has no authorizer (`variables.tf:324`)

## 7. Related work

- #780 / PR #829: the queue pipeline this follows (`docs/specs/780-a2a-mcp-queue-pipeline/`)
- #760: Lambda webhook host (precedent)
- #870: same gap on ECS, may move onto the shared runner
- #894 SSE on Lambda, #895 Streamable HTTP, #933 MCP upgrade
- Open dependencies: #959 (remove direct mode). #935 will be closed; only its router commit `4a8af37e3` is used (spec: Deviation 8)
