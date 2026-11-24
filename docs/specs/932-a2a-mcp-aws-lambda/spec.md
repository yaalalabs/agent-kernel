# #932: A2A and MCP on AWS Lambda through the queue pipeline — Implementation Spec

This spec details how `design.md` is built: a new request-Lambda host, `LambdaProtocolHost`, runs the existing
`RESTAPI.build_app()` through AK's own `LambdaEventTranslator`. The Lambda queue workers are not changed. Scope is as in
`design.md`: queue mode only, REST modes only (`rest_sync`, `rest_async`), no streaming, direct mode untouched. Supporting facts are in `research/findings.md`.

Evidence was gathered on `feature/932-a2a-mcp-on-aws-lambda` (from `develop` @ `c514f928c`). Paths are under
`ak-py/src/agentkernel/` unless they say otherwise. Facts proven by a throwaway experiment are marked **(spiked)**; claims about
AWS behaviour that were not run are marked **(unverified)** and become a check in plan Iteration 1.

## Deviations from `design.md` (decision needed before implementation)

`design.md` is unchanged. The evidence pass found points where the code disagrees with it. Each needs a decision at design
review; the rest of this spec is written as proposed here.

1. **A2A is open to anonymous callers (security gap).** With an `identity` block configured, an A2A call with no token runs as
   the anonymous principal: the identity dependency returns `Principal.anonymous()` when there is no `Authorization` header
   (`identity/provider/request.py:72-73`), and `tests/test_api_a2a_auth.py:200` (`test_no_token_runs_anonymous`) pins it.
   MCP is safe: FastMCP answers 401 itself (`tests/test_api_mcp_auth.py`).
   - **Decided: ECS parity.** ECS has no API Gateway authorizer (`ak-deployment/ak-aws/containerized/*.tf`): the app authenticates
     the bearer token through the `identity` block, so a call with no token is the anonymous principal and a bad token is a 401.
     The Lambda protocol routes work the same way: `authorization = "NONE"`, no authorizer and no bypass. A token-less A2A call
     therefore runs as anonymous (it was a 401 at API Gateway under the earlier design). Requiring a token on every A2A call is
     a generic feature for ECS and Lambda alike, a follow-up. The request handler's `config.yaml` must carry the `identity`
     block, or every caller is anonymous.
2. **`return_immediately` cannot stall our executor (spiked).** a2a-sdk 1.2.3 binds `DefaultRequestHandler` to
   `DefaultRequestHandlerV2` (`a2a/server/request_handlers/__init__.py:46`), not the file `research/findings.md` cites. In V2,
   `return_immediately` stops waiting only on a `Task` event (`default_request_handler_v2.py:421`). `A2A.Executor` enqueues one
   `Message` only (`api/a2a/a2a.py:93`), so the call still waits for the reply. Experiment: a fake queue client answering after
   1.5 s; `returnImmediately: true` and `{}` both returned the same 200 reply message in 1.51 s.
   - Proposed: no refusal code in the host. A regression test pins the behaviour so an SDK upgrade that changes it fails loudly.
3. **The worker changes are no-ops in the in-scope modes.** In REST modes the Lambda response handler already stores every
   reply and every permanent failure (`serverless/akresponsehandler.py:158-161`, `:235-239`). The stream runner is never
   reached, because `rest_sync` + `delta` is refused at router init (`core/router/rest_lambda.py:49`) and `rest_async` +
   `delta` is refused by config. So the `protocol` fixes would change nothing observable for #932.
   - **Decided: removed from #932 and moved to #985**, where `async` needs them. `design.md` is updated. A round-trip test
     proves the unchanged workers already serve A2A and MCP in REST modes.
4. **`GET /mcp` already answers 405 (spiked).** In stateless mode FastMCP returns 405 for GET with no code from us. The
   stateless guard makes this hold, so the host adds no GET handling; a test pins it.
5. **No authorizer on the protocol routes.** The first design put a route bypass in front of the API Gateway authorizer. The routes now carry
   no authorizer, as on ECS (Deviation 1), so nothing has to express the A2A paths.
6. **MCP OAuth discovery does not work on a default API Gateway URL (spiked, Iteration 1).** For an OpenID provider the MCP 401 points at
   `<scheme>://<netloc of mcp.url>/.well-known/oauth-protected-resource/mcp/` (`api/mcp/auth.py`, `AKMCPAuthProvider.from_config`),
   the origin root. A default `execute-api` URL carries a stage prefix, so a root path is not served by the REST API. **(spiked)**
   Both `<host>/.well-known/oauth-protected-resource/mcp/` (403 `Forbidden`) and `<host>/<stage>/.well-known/...` (403
   `Missing Authentication Token`) are refused on a default URL.
   Bearer-only providers (`static`) are unaffected.
   - Proposed: document the limit (use a custom domain mapped at root, or a bearer provider). A custom domain was not tested.
7. **The Lambda timeout cannot be checked at cold start.** Lambda sets no environment variable holding its timeout, and the
   context object exists only per invocation. The cold-start guard checks the 29 s API Gateway limit; the host checks
   `context.get_remaining_time_in_millis()` against the wait budget per invocation and logs a warning.
8. **#935 will be closed, not merged.** Its author is refactoring `LambdaHost`, `LambdaHostGuard` and `core/integration/`, so
   #932 does not depend on them. Only #935's first commit, `4a8af37e3` ("path parameter support for lambda"), survives: the
   router's resource-template lookup (`_resolve_route_path` in `core/router/rest_lambda.py`, about 15 lines).
   - Decided: #932 is based on `develop`. It cherry-picks only the router change of `4a8af37e3` (`rest_lambda.py` and its
     `tests/test_lambda_router.py` cases), agreed with that commit's author so it lands once.
   - The host and guard follow `develop`'s own pattern, `LambdaWebhookHost` and `LambdaWebhookGuard`
     (`deployment/aws/serverless/core/webhook_host.py`), with no shared base class. When the refactor adds one, moving onto it
     is a small follow-up.
   - The translator stays at `develop`'s path, `deployment/aws/serverless/core/event_translator.py`.
9. **Stripping the prefix breaks the `/mcp` to `/mcp/` redirect (spiked, Iteration 1).** Starlette builds the redirect `Location`
   from `scope["path"]` only and ignores `root_path`. With the prefix stripped the client is sent to `https://<host>/mcp/`, a URL
   the gateway does not serve. Passing the full event path with `root_path=/<base>/<version>` still drops the stage
   (`https://<host>/<base>/<version>/mcp/`). Only a path that includes the stage gives a correct `Location`.
   - Proposed: after stripping, the host rewrites the exact path `/mcp` to `/mcp/` before calling the app, so no redirect is ever
     built and the result does not depend on the stage or a custom domain. Direct calls to `/mcp/` answer normally. Spiked: a
     valid `initialize` sent to `/mcp/` returned 200 with no redirect.
   - Residual: any other route called with the wrong trailing slash would get the same wrong `Location`; the docs tell clients to
     use the exact URLs from the agent card.
   - Precedent: ECS already does the same rewrite; its MCP gateway route sets `overwrite_path = "/mcp/"`
     (`ak-deployment/ak-aws/containerized/state.tf:58-65`).
10. **Routing uses `Lambda.register`, like Slack and threads (consistency).** The first draft added a new
    `Lambda.set_protocol_host` hook and a path check in `Lambda.handler`. The router change cherry-picked from `4a8af37e3`
    (Deviation 8) resolves a route by the API Gateway resource template first, with the base path removed (`_resolve_route_path`),
    and `_normalize_path` keeps `{proxy+}` as is. So `/api/v1/a2a/{proxy+}` resolves to the registered key `/a2a/{proxy+}`.
    - Decided: the application registers the host's routes with `Lambda.register`, as `slack-openai` does for
      `LambdaWebhookHost`. `aklambda.py` is not changed. **(unverified)** A unit test in Iteration 4 proves a `{proxy+}` event
      dispatches before the rest is built on it.
11. **Terraform flag names match ECS (consistency).** ECS names its flag `enable_mcp_server`
    (`ak-deployment/ak-aws/containerized/variables.tf:244`). Lambda uses `enable_mcp_server` and `enable_a2a_server`, not
    `enable_*_route`.
12. **Cards and MCP tools come from the agent registry (#983).** `design.md` assumed they come from the agents this process hosts.
    Since #983 they come from `Runtime.current().registry.descriptors()`, built when the routes are mounted. Two set-ups follow:
    - **In-memory registry (default, used by the example):** the request Lambda imports the agent modules, as every other
      surface does today. It needs the agents' framework dependencies and more memory.
    - **Shared registry (`registry.type: dynamodb`, `redis` or `valkey`):** the request Lambda need not import the agents, so it
      stays light. But it builds its routes from whatever the registry holds at its cold start: on a fresh deployment, before the
      agent-runner Lambda has registered anything, it serves no agent until it is recycled (#983's own note). The serverless
      Terraform has no registry table or permissions today.
    - Decided for #932: the in-memory set-up, with no new code; the shared set-up works with no host change and is documented with
      its limit. A registry table in Terraform and a fix for the cold-start ordering are out of scope.
13. **`ProtocolPaths` lives in `deployment/aws/serverless/core/`**, beside the host that reads it: A2A and MCP are not messaging
    integrations, so it is not in `integration/adapter/`.
14. **One API Gateway method per verb, not `ANY`.** The Lambda router looks a route up by the resource template and the request's
    verb (`rest_lambda.py`), and `ProtocolPaths.ROUTES` registers `GET`, `POST` and `DELETE` for each template. The module creates
    exactly those methods; a test pins it. An unlisted verb (`PUT`, `PATCH`) is answered by API Gateway itself with 403 "Missing
    Authentication Token", instead of reaching the Lambda and failing at the router.
15. **The request Lambda builds a session store at import (real AWS, Iteration 6).** Registering an agent (`OpenAIModule(...)`)
    makes the runtime build its session store. In queue mode the Terraform module gives the request handler no session table
    (`state.tf:602-606`: `var.queue_mode ? null`), because the agent runner owns the sessions. With `session.type: dynamodb`
    in the shared `config.yaml` the request Lambda failed at cold start (`AKConfig.session.dynamodb.table_name must be set`) and
    every route that reaches it answered 502.
    - Decided for #932: no new code. The example sets `AK_SESSION__TYPE=in_memory` on the request handler, which holds no
      session. The docs say so. A request Lambda that needs no session store at all would be a runtime change, out of scope.
    - Not caught by the guard: the cold-start failure is the runtime's, not one of the guard checks.

## Design

### `LambdaProtocolHost` (new class, `deployment/aws/serverless/core/protocol_host.py`)

A standalone class beside `LambdaWebhookHost` (`core/webhook_host.py`), following its pattern (Deviation 8): a class-level
event loop reused across warm invocations and a `_run` classmethod that drives a coroutine on it, as `LambdaWebhookHost._run`
does (`webhook_host.py:84-88`). It serves every `/a2a` and `/mcp` event in the request Lambda by running the whole FastAPI app,
not one endpoint.

```python
class LambdaProtocolHost:
    def __init__(self, translator: LambdaEventTranslator | None = None):
        # 1. LambdaProtocolGuard().check()                       (cold-start checks, raises AKConfigError)
        # 2. app = RESTAPI.build_app(handlers=[])                 (once per cold start)
        # 3. self._lifespan = AppLifespan(app); self._run(self._lifespan.start())
    def handle(self, event: dict[str, Any], context: Any) -> dict[str, Any]: ...
```

The application registers the routes (Deviation 10), in its request-handler file, as `slack-openai` does:

```python
protocol = LambdaProtocolHost()
for path, method in ProtocolPaths.ROUTES:
    Lambda.register(path, method=method)(protocol.handle)
handler = Lambda.handler
```

- `RESTAPI.build_app(handlers=[])`: an empty list, not `None`, so the direct chat routes (`AgentRESTRequestHandler`, which runs
  agents in the process) are not built in the request Lambda. `build_app` still mounts A2A and MCP (`api/http.py:194-204`).
  The app's `/health` and `/openapi.json` are unreachable: only the `/a2a` and `/mcp` routes are registered.
- Cards and MCP tools come from the agent registry (#983, in `develop`): `A2A._build` and `MCP._build` read
  `Runtime.current().registry.descriptors()` (`api/a2a/a2a.py:152`, `api/mcp/akmcp.py:154`), when the routes are built at cold
  start. So the registry must know the agents before the host is constructed (Deviation 12). With the default in-memory registry,
  the application imports its agent module first; docs and example show the order.
- Lambda runs one invocation at a time per environment, so the host needs no locking. Failures never escape `handle`: every
  exception becomes a proxy response through `LambdaEventTranslator.error_to_proxy_response`, as for the webhook host.
- Per invocation, `handle` compares the wait budget `(retry_count - 1) * delay` with `context.get_remaining_time_in_millis()`
  and logs one WARNING when the budget is longer (Deviation 7).
- `handle` strips `/<API_BASE_PATH>/<API_VERSION>` (`BaseLambdaRouter._get_base_paths_from_env`,
  `core/router/common.py:48`) from the event path so app routes stay `/a2a/...` and `/mcp`. **(spiked S2, see Deviation 9)** Starlette
  redirects `/mcp` to `/mcp/` and builds a wrong `Location` once the prefix is stripped, so `handle` also rewrites the exact path
  `/mcp` to `/mcp/`. The API Gateway event `path` carries no stage; `requestContext.path` does **(spiked S1)**.
- Exported lazily from `agentkernel.aws` (`deployment/aws/__init__.py`, `_LAZY_EXPORTS`), like `LambdaWebhookHost`.

### `LambdaProtocolGuard` (new class, same module)

Modelled on `develop`'s `LambdaWebhookGuard` (`core/webhook_host.py:91-170`): same method names and message style, no shared
base class (Deviation 8). Runs in the host's constructor. Order: `_check_mode` (`rest_sync` or `rest_async`; the message names #985 for `async`; a `delta` reply is already refused by the REST router at init), `_check_base_path_env` (`API_BASE_PATH`, `API_VERSION`, `AGENT_ENDPOINT`, as the webhook guard),
then, only when A2A or agent MCP runs agents (`RESTAPI.agent_protocol_surfaces()`; an MCP serving only the application's own tools enqueues nothing and waits for nothing), the checks below.
`_check_stateless_mcp` runs whenever `mcp.enabled` (tool-only MCP included): `mcp.stateless_http` defaults to false and a call can land on any Lambda instance, whereas ECS keeps one replica's session. Not checked, because ECS does not check them either: that A2A or MCP is enabled, and the public `a2a.url` / `mcp.url` (documented requirements; shared checks are a follow-up). Each raises `AKConfigError` naming the setting and the fix.

| # | Check | Rule |
|---|---|---|
| 1 | Transport | `QueueTransportFactory.resolve_type() == "sqs"` (`in_memory` when no `execution.queues` block, so calls would time out) |
| 2 | Shared topology | `IOHandler._validate_topology("sqs", config)` and `_warn_if_no_agents(config)`, the ECS checks: a shared response store, and a warning when the registry knows no agents. Only when A2A or agent MCP runs agents |
| 3 | Wait budget | `(retry_count - 1) * delay <= 29` (`API_GATEWAY_TIMEOUT_SECONDS`); the first read is immediate (`pipeline/request_handler.py:148-163`) |

Check 2 uses the config model alone; it does not build the store. A missing input queue is #959's check, not repeated.

### `LambdaEventTranslator` — extended (`deployment/aws/serverless/core/event_translator.py`, not moved)

The class stays stateless. Two additions, no change to existing method behaviour:

```python
async def call_app(self, app: ASGIApp, event: Mapping[str, Any], app_path: str) -> dict[str, Any]: ...
    # builds the ASGI scope (shared with to_request), drives `await app(scope, receive, send)`, buffers every
    # http.response.body chunk (an SSE answer is buffered whole: design.md's "the adapter buffers the body")
@staticmethod
def proxy_response_from_parts(status: int, raw_headers: Sequence[tuple[bytes, bytes]], body: bytes) -> dict[str, Any]: ...
    # the one place a proxy response is built; _proxy_response delegates to it
```

- Scope building is factored out of `to_request` into one private method, so a Starlette `Request` and an app call see the same
  headers, query string, client and body bytes. `receive` returns the body once, then `http.disconnect` after the response ends.
- The default MCP answer is `text/event-stream` (`api/mcp/akmcp.py:134` passes no `json_response`). **(spiked)** A tool call
  through a bare ASGI driver returned one complete SSE event with status 200; buffering it gives a valid whole response. MCP is
  not changed to `json_response=True`, because `MCP.get_http_app` is shared with every other deployment.
- `_proxy_response` keeps raising `TypeError` for a streaming `Response` (#894 swaps the adapter).

### `AppLifespan` (new class, `core/protocol_host.py`)

Holds an app's lifespan open for the life of the execution environment. FastMCP raises `RuntimeError` ("task group was not
initialized") on any request before its lifespan runs **(spiked)**.

```python
class AppLifespan:
    def __init__(self, app: ASGIApp): ...
    async def start(self) -> None   # creates one task on the running loop that enters app.router.lifespan_context(app),
                                    # sets a ready event, then parks on a stop event; start() returns once ready
```

- **(spiked)** Started once on one loop that is never made current, then three separate `run_until_complete` calls each served a
  tool call. The task is parked between calls, never closed (Lambda freezes the environment; shutdown needs no work).
- A startup failure is re-raised from `start()`, so a broken app fails Lambda init, not the first request.
- One lifespan per host, so the loop is `LambdaProtocolHost`'s class-level loop.

### `ProtocolPaths` (new, FastAPI-free)

`ProtocolPaths` (`deployment/aws/serverless/core/protocol_paths.py`) is the one definition of the hosted prefixes, as
`BUILTIN_WEBHOOK_ROUTES` is for webhooks: `PREFIXES = ("/a2a", "/mcp")`, `matches(app_path)` (the prefix itself or the prefix
followed by `/`), and `ROUTES`: the `(path, method)` pairs the application registers, matching the Terraform resource templates:
`/a2a`, `/a2a/{proxy+}`, `/mcp`, `/mcp/{proxy+}`, each for `GET`, `POST` and `DELETE`. Read by the application and `LambdaProtocolHost`.

### Consumer changes

**`Lambda` (`serverless/aklambda.py`): no change (Deviation 10).** The routes go through `Lambda.register` and the
cherry-picked resource-template lookup, as `LambdaWebhookHost` does.

**`RESTLambdaRouter` (`core/router/rest_lambda.py`)**: only the cherry-picked `_resolve_route_path` change from `4a8af37e3`
(Deviation 8); nothing else. The chat route, `RESTLambdaRouter` and
`WSLambdaRouter` are untouched.

**Queue workers: no change (Deviation 3).** `ServerlessAgentRunner`, `ServerlessStreamAgentRunner` and the Lambda
`ResponseHandler` are untouched. In REST modes the response handler stores every reply and permanent failure
(`serverless/akresponsehandler.py:158-161`, `:235-239`), which is what `RestHandler.request` reads. The `protocol` fixes move to #985.

Verified unchanged: the three workers, integration delivery, `LambdaWebhookHost`, `LambdaWebhookGuard`.

### Config changes

No config changes. Reused as is: `a2a.enabled`, `mcp.enabled`, `mcp.expose_agents`, `mcp.stateless_http` (`core/config.py:156`),
`a2a.url` (`:144`), `mcp.url` (`:152`), `execution.response_store.retry_count` / `delay` (`:657-658`, defaults 5 x 5 s). Existing
YAML and `AK_*` variables are valid unchanged. `a2a.url` and `mcp.url` must be the public URL including stage and base path;
their defaults (`localhost`) now fail the guard when the host is built (check 7).

### Terraform (`ak-deployment/ak-aws/serverless`)

New optional inputs, both off by default; with both off the plan is empty for an existing deployment.

- Root `variables.tf`: `enable_a2a_server` and `enable_mcp_server` (bool, default `false`; the MCP name matches ECS's
  `enable_mcp_server`, `containerized/variables.tf:244`, Deviation 11). Validation: both must be `false` when
  `execution_mode == "async"` (matches `gateway_endpoints`, `variables.tf:302-305`).
- `state.tf:249` passes `proxy_routes = concat(var.enable_a2a_server ? ["a2a"] : [], var.enable_mcp_server ? ["mcp"] : [])` to the
  `api_gateway` module.
- The resource templates it creates (`/a2a`, `/a2a/{proxy+}`, `/mcp`, `/mcp/{proxy+}`, under the base path) are exactly the keys
  in `ProtocolPaths.ROUTES`, which the application registers (Deviation 10). The two lists must stay in step; a test pins it.
- `modules/api-gateway`: new variable `proxy_routes` (`list(string)`, default `[]`). For each name: an
  `aws_api_gateway_resource` `<name>` under the version resource, a child resource `{proxy+}`, and on each of the two a
  method per verb in `GET`, `POST`, `DELETE` (**not `ANY`**, Deviation 14) with an `AWS_PROXY` integration to the request Lambda
  (as `modules/api-gateway/main.tf:106-117`). The verbs are `ProtocolPaths.ROUTES`'s; a test pins them. Methods carry
  `authorization = "NONE"` whether or not an authorizer exists: the app authenticates (Deviation 1). The new resources, methods and integrations are
  added to the deployment `triggers` hash (`main.tf:131-141`) **only when `proxy_routes` is not empty** (`concat(<the existing
  list>, <the proxy ids or []>)`), so the hash of a deployment that sets none is unchanged and its plan stays empty; evaluating
  the old and new forms gives the same SHA-1 **(verified, Iteration 5)**. The existing three-level `endpoints` code is not
  touched. A name that is also a first path segment in `gateway_endpoints` would create the same resource twice.
- Request-Lambda memory is not changed: the default stays 128 MB (`variables.tf:355`, module default `modules/request-handler/variables.tf:89`)
  so existing plans are empty. With the in-memory registry the request Lambda imports the agents (Deviation 12), so the example
  sets a higher value and the docs say 128 MB is too small in that case.
- The request handler role already has what the protocol host needs in queue mode. **(verified, Iteration 5)** The response-store
  statement (`modules/request-handler/main.tf:124-149`, passed from `state.tf:574`) grants `dynamodb:GetItem` and
  `dynamodb:DeleteItem`, among others, on the response-store table and its indexes, which covers `RestHandler.request`'s
  delete-on-read (`pipeline/request_handler.py:157`); the SQS statement (`main.tf:192`) grants `sqs:SendMessage` on the input queue.
  No IAM change is needed.
- **(spiked S1)** `{proxy+}` plus a separate `/mcp` method serves `/mcp`, `/mcp/` and `/a2a/<agent>/tasks/<id>:cancel`. Run on a
  real REST API (stage `agents`, `authorization = NONE`): `/mcp` and `/mcp/` both reach the `/mcp` method (`event.path` keeps the
  trailing slash, `pathParameters` null); every `/a2a/...` path reaches `{proxy+}` with the rest of the path in
  `pathParameters.proxy`, including `triage/tasks/123:cancel` and `triage/message:send` (the colon arrives whole). Not run: a custom domain.

### Authentication (docs and example)

The protocol routes have no authorizer. The request-handler Lambda authenticates the bearer token through the `identity` block of
the `config.yaml` it carries, exactly as the ECS REST service does: A2A reads the principal from the identity dependency, FastMCP
refuses a missing or bad token. An authorizer on the same API protects the chat route only, and its cache can stay on. The docs say
that the request handler's `config.yaml` must carry the `identity` block, and that a token-less A2A call runs as anonymous.

## Behavioural changes

All intentional.

1. With the protocol routes registered, `/a2a/*` and `/mcp*` events are served by the app instead of failing at the router.
   Today they raise `ValueError` from `RESTLambdaRouter.dispatch` (`rest_lambda.py:430-432`) and `Lambda.handler` answers 500.
2. An A2A request with no token runs as the anonymous principal, as on ECS (Deviation 1); one with a bad token is a 401 from the app.
3. Cold start fails with `AKConfigError` for the guard conditions above, only when the host is constructed.

**Non-changes:** the chat route and its wire format; `RESTLambdaRouter`, `WSLambdaRouter`; the three Lambda queue workers; direct mode; ECS and the pipeline
`IOHandler`; the `MCP.get_http_app` call and any other deployment's MCP answer (still SSE); the SQS wire format; response-store
data layout; public exports other than the two new lazy names; untagged traffic in every mode; every `AKConfig` field.

## Error handling

- Cold start: `AKConfigError` from the guard (table above), from `build_app` (e.g. no agents for a card), or re-raised from
  `AppLifespan.start()`. Lambda init fails and the deployment is visibly broken, instead of requests failing later.
- Per request: an app exception, a translator error or a buffering error becomes a proxy response (500 plain text, details in the
  log only) through `error_to_proxy_response`; the exception text never reaches the caller.
- Reply failures: `ReplyTimeoutError` and runner failures already reach callers as A2A `InternalError` / MCP `ToolError` with
  fixed messages (`api/a2a/a2a.py:77-90`, `api/mcp/akmcp.py:100-103`); tested here on the Lambda path.
- Limits to document: an agent run plus queue time over about 29 s fails with the executor's timeout error in v1; cold start
  (agent import, `build_app`, lifespan) counts toward the 29 s of the first request only if init was not already done; `tasks/{id}`
  across instances is out of scope.
- Missing optional dependencies: the host imports FastAPI, Starlette and the `a2a`/`mcp` extras; a missing extra surfaces as the
  import error at module scope of the request Lambda (same as `LambdaWebhookHost`), so the example's `pyproject.toml` lists them.

## Testing

Run: `cd ak-py && uv run pytest tests/<file>`; then the full `uv run pytest`.

New files:
- `tests/test_lambda_protocol_host.py`: the host end to end over a fake queue client on `A2A._client` / `MCP._client`:
  A2A `message:send`, MCP `tools/call` (SSE body buffered, status 200), the public card with no token, A2A with `returnImmediately: true` returns the same reply after the wait (Deviation 2 pin), `GET /mcp` is 405 (Deviation 4
  pin), `/mcp` and `/mcp/` both served with no redirect (Deviation 9), base-path stripping, lifespan started once and reused across three calls, a lifespan start
  failure raising at construction, error mapping to proxy responses (the riskiest consumer: the whole app behind a translator).
- `tests/test_lambda_protocol_guard.py`: each check passing and failing, with the message naming the setting;
  `async` mode refused naming #985.
- `tests/test_lambda_protocol_roundtrip.py`: proves the **unchanged** workers serve A2A and MCP in `rest_sync` and `rest_async`
  (Deviation 3): an input record with `protocol` through `ServerlessAgentRunner.process_message` then
  `ResponseHandler.process_message` into an `InMemoryResponseStore`, read by `RestHandler.request`; success, permanent failure
  (500 record) and a timeout.

Changed files (patch targets and assertions):
- `tests/test_lambda_event_translator.py`: `call_app` buffering, `proxy_response_from_parts`, and that `to_request` and the app
  scope agree on headers and body; existing cases unchanged (the delegation must not change `_proxy_response` output).
- `tests/test_aws_lazy_exports.py`: `LambdaProtocolHost` and `ProtocolPaths` resolve lazily; importing `agentkernel.aws` and
  touching `Lambda` loads neither FastAPI nor the host.
- `tests/test_lambda_router.py`: with `ProtocolPaths.ROUTES` registered, a `{proxy+}` event (`resource` `/api/v1/a2a/{proxy+}`,
  `path` `/api/v1/a2a/triage/message:send`) and an `/mcp` event dispatch to the registered handler for `GET`, `POST` and
  `DELETE`; the chat route still dispatches as today (Deviation 10). This is the first test written in Iteration 4.
- `tests/test_pipeline_protocol_routing.py` is unchanged (it covers the pipeline copies; the Lambda copies are covered above).

Terraform: `terraform validate` and a plan with both flags off showing no changes, and one with both on showing the new resources.

Integration test: a weekly entry for the new example (`.github/integration-test-config.yaml`, after `schedule-openai` at `:83`);
the test sends one A2A `message:send` and one MCP tool call, twice each on one session, plus an A2A `message:send` with no token
expecting 200 (anonymous, as on ECS), one with a wrong token expecting 401, and a card fetch with no token expecting 200.

## Docs and skills touched

`docs/docs/api/a2a-server.md:56` and `docs/docs/api/mcp-server.md:48` (add Lambda rows), `docs/docs/deployment/aws-serverless.md`,
`.agents/skills/ak-dev-architecture/SKILL.md` (and its `.claude/skills` copy; the `LambdaWebhookHost` paragraph around `:626` and
`:899`), `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`, and `.agents/skills/ak-dev-testing-conventions/SKILL.md` (new
test rows). Details are in `plan.md`.
