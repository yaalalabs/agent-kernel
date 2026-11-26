# #894: SSE (`rest_sync` + `delta`) on AWS Lambda — Implementation Spec

> [!TIP]
> **TL;DR:** how [`design.md`](design.md) is built. Four Python pieces:
> 1. `IOHandler.check_deployment` (shared startup checks)
> 2. `LambdaPaths` (shared chat-path rule)
> 3. `LambdaStreamGuard` + `LambdaStreamServer` + `LambdaChatPathMiddleware` (the Lambda host)
> 4. two queue-worker fixes.
>
> Then Terraform (two module inputs, three validations), one example, the docs and skills. No `AKConfig`
> change and no new root Terraform variable.

`design.md` is the requirements source. Evidence is cited against `develop` at `93885bf1b`. The AWS facts
are in [`research/aws-response-streaming.md`](research/aws-response-streaming.md).

## Design

### 1. `IOHandler.check_deployment` (shared startup checks)

File: `ak-py/src/agentkernel/pipeline/io_handler.py`.

```python
@classmethod
def check_deployment(cls, transport_type: str, config, pod_push: bool = True) -> None:
    """The startup checks every entry point that serves the pipeline runs: topology fail-fasts, then the
    no-agents warning. Public so a host with its own server process runs the same checks as ``run``."""
    cls._validate_topology(transport_type, config, pod_push=pod_push)
    cls._warn_if_no_agents(config)
```

- **Same name, signature and docstring as PR #989** (#932) adds. Whichever PR merges second drops its
  copy in the rebase.
- `IOHandler.run` calls `check_deployment` where it calls the two methods today. No behaviour change.
- The guard (section 3) calls it with `pod_push=False`. SSE mode is not a WebSocket mode, so the push-token
  branch never runs. Passing `False` states that the host pushes nothing.

### 2. `LambdaPaths` (shared chat-path rule)

New file `ak-py/src/agentkernel/deployment/aws/serverless/core/paths.py`. It imports neither FastAPI nor
Starlette, so the router can use it.

```python
class LambdaPaths:
    """The API prefix and chat path the ak-serverless module gives the request-handler Lambda (#894)."""

    ENV = ("API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT")

    def __init__(self, base_path: str, chat_path: str): ...  # "/api/v1", "/api/v1/chat"

    @classmethod
    def from_env(cls) -> "LambdaPaths | None":
        """None when any of ENV is unset or empty (today's _get_base_paths_from_env rule)."""

    @classmethod
    def missing_env(cls) -> list[str]:
        """The names in ENV that are unset or empty, for a cold-start error."""

    @property
    def base_path(self) -> str: ...
    @property
    def chat_path(self) -> str: ...
```

- `BaseLambdaRouter._get_base_paths_from_env` (`core/router/common.py:48-61`) becomes a thin delegate:
  `paths = LambdaPaths.from_env()`, returning `(paths.base_path, paths.chat_path)` or `(None, None)`.
  - Its return value is unchanged, so `RESTLambdaRouter.dispatch` (`core/router/rest_lambda.py:432-438`)
    and the WebSocket router are untouched.
- `LambdaWebhookGuard.BASE_PATH_ENV` (`core/webhook_host.py:95`) becomes `LambdaPaths.ENV`. Its
  `_check_base_path_env` uses `LambdaPaths.missing_env()`, and its message is unchanged.
- **Not touched:** `WebhookRouteMatcher._base_path_from_env` (`integration/adapter/route_matcher.py:67`).
  `integration/` may not import `deployment/` (architecture rule 6). It derives only the prefix, and it
  runs in the authorizer Lambda.

### 3. `LambdaStreamGuard` (cold-start checks)

New file `ak-py/src/agentkernel/deployment/aws/serverless/core/stream_server.py`, with the server
(section 4). It is the sibling of `LambdaWebhookGuard` (`core/webhook_host.py:91`).

```python
class LambdaStreamGuard:
    """The cold-start checks LambdaStreamServer runs (#894): fail at init, not on the first request."""

    def check(self, config: AKConfig) -> LambdaPaths:
        """Run every check, in this order; return the chat-path rule.
        :raises AKConfigError: mode, transport, base-path environment, then IOHandler.check_deployment's."""
        self._check_mode(config)            # execution.is_sse, else AKConfigError
        self._check_transport()             # QueueTransportFactory.resolve_type() == "sqs"
        paths = self._check_base_path_env() # LambdaPaths.from_env(), else AKConfigError naming missing_env()
        IOHandler.check_deployment("sqs", config, pod_push=False)
        return paths
```

| Check | Error text (gist) |
|---|---|
| `_check_mode` | `LambdaStreamServer serves execution.mode rest_sync with message_type delta (SSE) only; got <mode> + <type>. Other modes use Lambda.handler` |
| `_check_transport` | The `LambdaWebhookGuard._check_transport` sentence with `LambdaStreamServer` as the subject (`webhook_host.py:137-143`) |
| `_check_base_path_env` | `LambdaStreamServer needs <names> in the environment to map the chat path. The ak-serverless module sets them on the request-handler Lambda` |
| `check_deployment` | Its own errors, unchanged: an in-memory or missing store (`io_handler.py:226-235`), a store that cannot stream chunks (`:238-243`), A2A/MCP without a shared store (`:244-255`) |

- The order goes from cheap to expensive. `check_deployment` builds the response store last, which does
  not connect (`io_handler.py:236-237`).

### 4. `LambdaStreamServer` and `LambdaChatPathMiddleware` (the host)

Same file as section 3. It imports FastAPI, Starlette and uvicorn at module scope, like `webhook_host.py`.

```python
class LambdaChatPathMiddleware:
    """ASGI middleware: the configured chat path reaches RequestHandler.CHAT_PATH; other paths pass unchanged.
    The Lambda counterpart of ECS's gateway overwrite_path (ak-aws/containerized/state.tf:30-34)."""

    def __init__(self, app: ASGIApp, paths: LambdaPaths): ...

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # http scopes whose path == paths.chat_path (trailing "/" ignored): copy the scope with
        # path = RequestHandler.CHAT_PATH and raw_path = its bytes. Everything else passes as is.


class LambdaStreamServer:
    """Serves the pipeline's REST app from the request-handler Lambda through the Lambda Web Adapter (#894).

    The REST half of IOHandler.run: RESTAPI.build_app with the pipeline RequestHandler, served by uvicorn.
    No response-handler thread and no agent runner: on Lambda they are their own functions."""

    _log = logging.getLogger("ak.aws.lambda.stream")

    @classmethod
    def build_app(cls, handlers: list[RESTRequestHandler] | None = None) -> ASGIApp:
        """Run LambdaStreamGuard, then return the wrapped app (separate from run so tests drive it)."""
        config = AKConfig.get()
        paths = LambdaStreamGuard().check(config)
        app = RESTAPI.build_app(handlers=[RequestHandler(), *(handlers or [])])
        return LambdaChatPathMiddleware(app, paths)

    @classmethod
    def run(cls, handlers: list[RESTRequestHandler] | None = None) -> None:
        """Build the app and serve it on api.host:api.port until LWA stops the process."""
        config = AKConfig.get()
        uvicorn.Server(uvicorn.Config(app=cls.build_app(handlers), host=config.api.host, port=config.api.port)).run()
```

**Rules**

1. **No copied pipeline logic.** The SSE path, the precheck before the queue, the attachment rules and
   the store check are `RequestHandler`'s (`pipeline/request_handler.py:490-669`).
2. **uvicorn runs on the main thread.** It installs its own SIGTERM/SIGINT handlers, so LWA's shutdown
   stops it. `IOHandler`'s handlers exist only because its uvicorn runs on a worker thread
   (`io_handler.py:110-116`).
3. **`handlers` join `RequestHandler()`, never replace it**, as in `IOHandler.run`
   (`io_handler.py:103`). There is no `request_handler=` parameter (see Non-changes).
4. **Middleware, not a second route.** Mounting `RequestHandler` at the configured path would need a
   second instance. Rewriting the path keeps one chat route, as ECS does.
5. **The guard runs in `build_app`,** so `run` cannot serve an app whose checks were skipped.

### 5. Queue workers (Lambda-only fixes)

**5a. `ServerlessStreamAgentRunner._get_record_attributes`** (`serverless/akagentrunner.py:248-287`)

- It requires `endpoint_url` only when `AKConfig.get().execution.is_websocket`. The error text is unchanged.
- It puts `endpoint_url` in `record_attributes` only when present. `_send_chunk_to_output_queue`
  (`:300-327`) adds the `endpoint_url` custom attribute only when it is in `record_attributes`. That is
  the `ServerlessAgentRunner` shape (`:80`, `:98-99`, `:131-133`).
- `on_permanent_failure` (`:359-388`) needs no change. Once the attributes resolve, it sends its error
  chunk to the output queue in SSE mode too.

**5b. Serverless `ResponseHandler`** (`serverless/akresponsehandler.py`)

- `process_message` (`:155-161`) gets a branch between the WebSocket branch and the store branch:

  ```python
  elif execution.is_sse:
      cls._store_chunk(record)
  ```

- New `_store_chunk(record)`. It is the shared `ResponseHandler._store_chunk` (`pipeline/response_handler.py:257-267`)
  for a raw SQS record:
  - `request_id` comes from the custom attributes. Missing → `ValueError`, so the record is retried.
  - the store must support chunk streaming, else `AKConfigError` with the shared handler's message, word
    for word
  - `store.add_chunk(request_id, cls._decode_body(record["body"]))`.
- `on_permanent_failure` (`:235-238`) gets the same branch before the REST-store `else`. When `is_sse`, it
  calls `add_chunk(request_id, {"error": <message>, "done": True, "session_id": session_id})`, built
  like the WebSocket error chunk at `:218-223`. A missing `request_id` is logged and dropped (the method
  never raises, `:240-241`).
- **Order is unchanged:** integration first, then WebSocket, then SSE, then REST store.

### 6. The router's refusal message

`rest_lambda.py:48-52` keeps raising `AKConfigError`. The new text:

> `execution.mode rest_sync with message_type delta (SSE) is not served by Lambda.handler: it returns one finished response. Serve it with LambdaStreamServer behind the Lambda Web Adapter (see the AWS serverless deployment docs), or use execution.mode async with message_type delta (WebSocket)`

The test at `tests/test_lambda_router.py:190-193` keeps passing: it matches `rest_sync with message_type delta`.

### 7. Exports

- `deployment/aws/__init__.py` `_LAZY_EXPORTS` gains `"LambdaStreamServer": ".serverless.core.stream_server"`,
  with the matching `TYPE_CHECKING` import. `agentkernel/aws.py` re-exports it automatically.
- `LambdaStreamGuard`, `LambdaChatPathMiddleware` and `LambdaPaths` are not exported (`LambdaWebhookGuard`
  is not either).

### 8. Terraform (`ak-deployment/ak-aws/serverless`)

**8a. Root `state.tf`**

```hcl
# rest_sync + delta: the request handler streams SSE through the Lambda Web Adapter (#894)
is_sse_mode = var.execution_mode == "rest_sync" && var.message_type == "delta"
```

- `module "request_handler"` gets `response_streaming = local.is_sse_mode`.
- `module "api_gateway"` gets `response_streaming = local.is_sse_mode` and
  `lambda_function_arn = module.request_handler[0].lambda_function_arn`.

**8b. Root `variables.tf`: three validations on `message_type`** (cross-variable, Terraform ≥ 1.9; the
module needs `>= 1.9.5`, `main.tf:14`)

| Condition | Error message (gist) |
|---|---|
| `!(sse) \|\| var.queue_mode` | `rest_sync with message_type delta (SSE) needs queue_mode = true` |
| `!(sse) \|\| !var.create_dynamodb_response_store` | `... needs a response store that can stream chunks (Redis or Valkey); DynamoDB cannot` |
| `!(sse) \|\| var.authorizer == null` | `... is authenticated inside the app through the identity block in config.yaml; remove authorizer` |

- Each spells `sse` out as `var.execution_mode == "rest_sync" && var.message_type == "delta"`, since a
  validation cannot read `local`.
- The `message_type` description (`variables.tf:72`) drops the claim that delta is WebSocket-only.

**8c. `modules/request-handler`**

- New input `response_streaming` (`bool`, default `false`, `nullable = false`).
- When `true`, merged into `environment_variables` (`main.tf:372-421`):

  | Variable | Value | Why |
  |---|---|---|
  | `AWS_LWA_INVOKE_MODE` | `response_stream` | Streaming mode (research: LWA) |
  | `AWS_LWA_PORT` | `"8000"` | Port LWA forwards to |
  | `AK_API__PORT` | `"8000"` | Pins `api.port` to the same value, so `config.yaml` cannot drift from it |
  | `AWS_LWA_READINESS_CHECK_PATH` | `/health` | `RESTAPI.build_app`'s health route (`api/http.py:63`) |
  | `AWS_LAMBDA_EXEC_WRAPPER` | `/opt/bootstrap` | Zip only (`var.package_type != "Image"`). An image runs LWA as an extension |

- `handler_path` stays the user's. For zip it names the start script (`run.sh`).

**8d. `modules/api-gateway`**

- New inputs: `response_streaming` (`bool`, default `false`, `nullable = false`) and
  `lambda_function_arn` (`string`, default `null`).
- `aws_api_gateway_integration.endpoint` (`main.tf:99-116`):
  - `uri` = when streaming,
    `"arn:aws:apigateway:${var.region}:lambda:path/2021-11-15/functions/${var.lambda_function_arn}/response-streaming-invocations"`,
    else `var.lambda_function_invoke_arn` (unchanged)
  - `response_transfer_mode` = `"STREAM"` when streaming, else `null`. A `null` keeps the provider's
    default, so existing stacks plan no change. This is checked in iteration 4 of the plan.
  - `timeout_milliseconds` is not set (the doc conflict in the research note: the spike decides).
- `aws_api_gateway_method.endpoint` (`:94-95`) is unchanged. `create_authorizer` is false in SSE mode
  (8b), so every method is `NONE`.
- `aws_lambda_permission.endpoint` (`:119-124`) is unchanged: `lambda:InvokeFunction` (the spike confirms
  it covers streaming invocations).
- The redeployment trigger (`:128-139`) already hashes the integration ids. A changed `uri` or mode
  replaces the integration, so the stage redeploys.

### 9. Example: `examples/aws-serverless/sse-openai`

Modelled on `examples/aws-serverless/scalable-openai` (queue mode, `S3Zip` request handler, image runner).

| File | Content |
|---|---|
| `app_stream_server.py` | `LambdaStreamServer.run()`. No agent module: the request handler runs no agent, and the precheck leaves an empty registry to the runner (`request_handler.py` "The precheck before the queue") |
| `run.sh` | Starts the server for LWA (`exec python app_stream_server.py`, with `PATH`/`PYTHONPATH` set the way the LWA zip examples do) |
| `lambda_agent_runner.py` | The OpenAI agent module + `ServerlessStreamAgentRunner.handle` |
| `lambda_response_handler.py` | `ResponseHandler.handle` |
| `config.yaml` | `execution: {mode: rest_sync, message_type: delta, queues: {type: sqs}, response_store: {type: redis}}`, a `static` `identity` block |
| `deploy/main.tf` | `execution_mode = "rest_sync"`, `message_type = "delta"`, `queue_mode = true`, `create_redis_response_store = true`, `request_handler.handler_path = "run.sh"`, `request_handler.layers = [<pinned LWA layer ARN for var.region>]`, `timeout = 300` |
| `pyproject.toml` | `agentkernel[api,aws,openai,redis]` |
| `lambda_test.py` | Streams `POST <invoke-url>/api/v1/chat` with `httpx`; asserts several `data:` frames, the last `done: true`, and at least two frames received before the run ends |
| `README.md` | Deploy, `curl -N`, the limits from design section 7 |

- `deploy/variables.tf` and `main.tf` take the three `*_security_group_id` inputs, as weekly
  `scalable-openai` does (testing skill, "reuse the base's SGs").
- `.github/integration-test-config.yaml` gains the entry, beside `scalable-openai` (`:76-78`).

## Consumer changes

| Consumer | Change |
|---|---|
| `IOHandler.run` | Calls `check_deployment`. Same checks, same order |
| `BaseLambdaRouter._get_base_paths_from_env` | Delegates to `LambdaPaths`. Same return values |
| `LambdaWebhookGuard._check_base_path_env` | Uses `LambdaPaths.ENV` / `missing_env()`. Same message |
| `ServerlessStreamAgentRunner` | `endpoint_url` required only in WebSocket mode |
| Serverless `ResponseHandler` | New SSE branch in `process_message` and `on_permanent_failure` |
| `DefaultEndpointsHandler.get_routes` | New refusal text |
| `ak-aws/serverless` root, `request-handler`, `api-gateway` | Section 8 |
| **Verified unchanged** | `RequestHandler`, `RESTAPI.build_app`, `ResponseStoreFactory` and the Redis/Valkey stores, the pipeline `ResponseHandler`, `WSLambdaRouter`, `LambdaWebhookHost`, `WebhookRouteMatcher`, `APIGatewayAuthorizer` |

## Config changes

- **`AKConfig`:** none. `execution.mode`, `execution.message_type`, `execution.queues`,
  `execution.response_store` and `api.port` already say everything the feature needs.
- **Terraform root:** no new variable. Three validations on `message_type` (8b).
- **Terraform modules:** two internal inputs, `response_streaming` and `lambda_function_arn`, both
  defaulted, so a caller of the modules that sets neither plans no change.
- **Existing YAML and `AK_*` env vars:** unaffected. A deployment in SSE mode could not start before
  (`rest_lambda.py:48-52`), so no working config changes meaning.

## Behavioural changes

1. **Intentional:** `rest_sync` + `delta` on Lambda now works with `LambdaStreamServer`. Before, every
   route of the function failed at cold start.
2. **Intentional:** `terraform plan` fails for SSE mode without `queue_mode`, with
   `create_dynamodb_response_store`, or with an `authorizer`. Before, such a plan applied and the
   function failed at cold start.
3. **Intentional:** `ServerlessStreamAgentRunner` in a non-WebSocket mode no longer raises
   `endpoint_url is required for async + delta`. Before, an SSE message was retried until permanent failure.
4. **Intentional:** the serverless `ResponseHandler` in SSE mode writes chunks and error chunks with
   `add_chunk`. Before, it stored each chunk as a whole reply (`add_message`), which nothing read.
5. **Intentional:** the router's refusal text names `LambdaStreamServer`.

**Non-changes**

- Every other mode, WebSocket included: same code paths and same Terraform plan.
- `RequestHandler`'s SSE wire format (`data: {...}\n\n` frames, error frames), so #895 needs no Lambda change.
- `LambdaStreamServer.run` takes no `request_handler=`. Thread recording on Lambda is out of scope.
  `IOHandler.run(request_handler=...)` is unchanged.
- `Lambda.register` routes are not served in SSE mode (design non-goal).
- Data: chunk keys and records in the response store are written by the shared store methods, so their
  layout is the one ECS writes.

## Error handling

| Failure | Where | What the caller or operator sees |
|---|---|---|
| Wrong mode, transport, base-path env, or store | `LambdaStreamGuard` at init | `AKConfigError`. LWA's readiness check never passes, so the invocation fails, and the error is in the function log |
| Plan-time misconfiguration | Terraform validation | `terraform plan` fails with the 8b message |
| Request refused before the queue (unknown agent, bad body, store cannot stream) | `RequestHandler` | The same 4xx JSON as on ECS, before the stream opens |
| Runner fails one attempt | SQS retry | Nothing yet; chunks continue on the retry (dedup suffix carries the receive count, `akagentrunner.py:345-355`) |
| Runner exhausts retries | `ServerlessStreamAgentRunner.on_permanent_failure` | An error chunk `{"error", "done": true}` reaches the stream |
| Response handler exhausts retries on a chunk | Serverless `ResponseHandler.on_permanent_failure` | An error chunk reaches the stream; the stream ends |
| No chunk within the store's wait | `_sse_stream` (`request_handler.py:680-687`) | `data: {"error": "Stream timed out", "done": true, ...}` |
| Store driver error mid-stream | `_sse_stream` (`:688-692`) | `data: {"error": "Stream delivery failed", ...}`; the detail goes only to the log |
| Client disconnects | — | The stream's `finally` closes the store stream (`:693-701`). The agent run and the function continue and are billed (design section 7) |
| Missing `redis` / `api` extra | Import at cold start | `ImportError` naming the package; the example's `pyproject.toml` lists both extras |

## Testing

**New file `ak-py/tests/test_lambda_stream_server.py`**

- `TestLambdaStreamGuard` (with a real `_ExecutionConfig`, per the testing skill):
  - each refusal: wrong mode (complete, `async` + delta, `rest_async`), a non-`sqs` transport, each missing
    env name, an in-memory store, a DynamoDB store (from `check_deployment`)
  - the happy path returns `LambdaPaths` with the expected chat path
  - the order: with two problems, the mode error wins.
- `TestLambdaChatPathMiddleware` (a one-route Starlette app that echoes `scope["path"]`):
  - the default chat path, a non-default `agent_endpoint` (`/v2/api/talk` → `/api/v1/chat`), a trailing
    slash, `/api/v1/agents` unchanged, `/health` unchanged, a websocket or lifespan scope unchanged.
- `TestLambdaStreamServerApp` (over `httpx.ASGITransport` and `LambdaStreamServer.build_app`):
  - SSE end to end through the configured chat path. The guard is patched to pass, because it requires
    `sqs`. The app runs over the `in_memory` transport and store, with a thread that drains the input
    queue the way `test_protocol_pipeline_roundtrip.py` does. Asserts `text/event-stream`, frames in order,
    and the terminal frame.
  - `handlers` are mounted beside `RequestHandler`.
  - the guard runs before `RESTAPI.build_app` (patched to fail if reached).

**Extended files**

| File | New cases |
|---|---|
| `tests/test_pipeline_io_handler.py` | `check_deployment` calls `_validate_topology` with `pod_push`, then `_warn_if_no_agents`; `run` goes through it |
| `tests/test_akagentrunner_stream.py` | No `endpoint_url` in `rest_sync` + delta → attributes without it, chunks sent without the attribute; `async` + delta still raises (the existing `test_get_record_attributes_raises_when_endpoint_url_missing` runs under an `async` config) |
| `tests/test_akresponsehandler.py` | SSE: a chunk record → `add_chunk(request_id, body)`, no `add_message`, no broadcast; missing `request_id` → `ValueError`; a store without chunk streaming → `AKConfigError`; permanent failure → one error chunk; integration records still delivered first |
| `tests/test_lambda_router.py` | The refusal text names `LambdaStreamServer`; `_get_base_paths_from_env` returns the same values through `LambdaPaths` |
| `tests/test_lambda_webhook_host.py` | Unchanged; it guards the `LambdaPaths.ENV` move |
| `tests/test_aws_lazy_exports.py` | `LambdaStreamServer` resolves; importing `Lambda` loads neither `uvicorn` nor `...core.stream_server` |

**Patch targets that move:** none. `_get_base_paths_from_env` stays on the router, and `IOHandler._validate_topology`
keeps its name.

**Terraform:** `terraform validate` in `ak-aws/serverless`; `terraform plan` of `examples/aws-serverless/scalable-openai`
shows no change; a plan of `sse-openai` shows `STREAM` integrations; each 8b validation fails a plan.

**Run:** `cd ak-py && uv run pytest tests/test_lambda_stream_server.py tests/test_akresponsehandler.py tests/test_akagentrunner_stream.py tests/test_lambda_router.py tests/test_lambda_webhook_host.py tests/test_pipeline_io_handler.py tests/test_aws_lazy_exports.py`, then the full `uv run pytest` and `make lint-check-all`.
