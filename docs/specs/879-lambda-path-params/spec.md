# #879 (phase 1): Path-parameter routing in the Lambda REST router — Implementation Spec

`RESTLambdaRouter.dispatch()` resolves a non-chat request's route key from the resource template
API Gateway matched, falling back to the concrete path. Requirements source: [design.md](design.md).

## Design

### `RESTLambdaRouter._resolve_route_path` (new private method)

`ak-py/src/agentkernel/deployment/aws/serverless/core/router/rest_lambda.py`

```python
def _resolve_route_path(self, event: dict[str, Any], event_path: str, base_path: str, method: str) -> str:
    # candidates in priority order: the matched template, then the concrete path; a missing resource is skipped
    candidates = [p.removeprefix(base_path) for p in (event.get("resource"), event_path) if p]
    # first candidate registered for the method; else the concrete path, so the no-match error is unchanged
    return next((p for p in candidates if method in self._routes.get(p, {})), candidates[-1])
```

Rules:

1. **The router never matches paths.** It looks keys up in `_routes`; API Gateway chose the template.
2. **Resource before path.** When both are registered (a template and a concrete path that equals the
   request), the gateway's choice wins, so code and gateway cannot disagree.
3. **Path is the fallback and the default.** An unregistered `resource` (`/{proxy+}`) or a missing one
   falls through to the concrete path, which is the pre-change key.
4. **Method-aware.** A template registered for `GET` only does not capture a `DELETE`; the `DELETE`
   falls through to the path and fails as before.

`event_path` is never empty (`dispatch()` defaults it to `"/"`), so `candidates` always has at least
one entry and `candidates[-1]` is safe.

### `RESTLambdaRouter.dispatch` (changed)

- The non-chat branch calls `self._resolve_route_path(event, event_path, env_base_path, method)` in
  place of `event_path.removeprefix(env_base_path)`.
- Everything else is unchanged: method normalization, `event_path` derivation, the chat endpoint
  check, the no-env-vars branch, the lookup, the error message and the handler call.

### Docstrings

- `RESTLambdaRouter` class docstring: routes may carry path parameters, looked up by the resource
  template; values in `event["pathParameters"]`.
- `Lambda.register` (`aklambda.py`): the `route` param may carry path parameters.

### Example: `examples/aws-serverless/schedule-openai`

| File | Change |
|---|---|
| `lambda_request_handler.py` | `get_schedule` / `amend_schedule` / `cancel_schedule` registered on `/schedules/{task_id}` for `GET` / `PUT` / `DELETE`; read `event["pathParameters"]["task_id"]`; PUT body is the amendment only; `user_id` from `?user_id=` via `_user_id()` |
| `deploy/main.tf` | `gateway_endpoints`: `schedules` GET, `schedules/{task_id}` GET / PUT / DELETE |
| `lambda_test.py` | client uses `GET` / `PUT` / `DELETE {schedules_url}/{task_id}` with `params={"user_id": ...}` |
| `README.md` | diagram, route table (now identical to containerized), curl examples, ownership note |

### Config changes

No config changes. No `AKConfig` field, env var or Terraform variable is added or changed.

### Behavioural changes

1. **Template routes dispatch** (intentional, the feature). Before: `ValueError` → 500.
2. **The gateway's template beats a registered concrete path** when both exist (intentional, rule 2).
   Before: the concrete path won. Only reachable when a route is registered in code but absent from
   `gateway_endpoints`.
3. **Example routes change** (intentional): `/schedules/get`, `/schedules/amend`, `/schedules/cancel`
   are removed in favour of `/schedules/{task_id}`. Clients of the example must update.

**Non-changes:** `register()` signature and normalization; `_routes` shape; chat and poll routing;
the no-env-vars fallback; the no-match error text; `Lambda._wrap_response`; the Terraform module;
`APIGatewayAuthorizer` and `WebhookRouteMatcher` (they match on method and path, untouched);
`LambdaWebhookHost` routes (static paths).

## Error handling

- No registered template or path for the method → the existing `ValueError("No registered route found
  for API Gateway path -> '<concrete path>' and method '<method>'")`, turned into a 500 by
  `Lambda.handler`.
- A handler reading `event["pathParameters"]` on a template route always finds the key: API Gateway
  only sets that `resource` when it matched the template, and so filled the parameters.

## Testing

`ak-py/tests/test_lambda_router.py`:

- `make_event_with_env_vars` takes `**extra` so tests can add `resource` / `pathParameters`; existing
  callers are unchanged.
- New tests:
  - `test_dispatch_routes_path_parameter_route_by_resource_template`: template dispatches; handler
    reads `pathParameters`.
  - `test_dispatch_follows_the_resource_api_gateway_selected_over_a_matching_concrete_path`: rule 2.
  - `test_dispatch_routes_static_route_when_resource_equals_path`: static beats template.
  - `test_dispatch_falls_back_to_concrete_path_when_resource_is_not_registered`: `{proxy+}`.
  - `test_dispatch_raises_when_template_route_lacks_the_method`: rule 4, error names the concrete path.
  - `test_dispatch_routes_agent_endpoint_to_default_when_resource_is_present`: chat unchanged.
- Existing tests (events without `resource`) pass unchanged.

Run: `cd ak-py && uv run pytest tests/test_lambda_router.py tests/test_authorizer_webhook_bypass.py`.

The example's `lambda_test.py` is an integration test against a deployed stack (weekly matrix); it
is not run locally.

---

# #879 (phase 2): Conversation threads as a Lambda integration — Implementation Spec

`LambdaThreadHost` hosts the pipeline's `ThreadRequestHandler` on the request-handler Lambda, the
way `LambdaWebhookHost` hosts `WebhookRESTRequestHandler`. It hooks the built-in chat route so the
user message is recorded and the queued request marked before it is enqueued, and it serves the two
read routes the app registers. `ServerlessAgentRunner` records the reply through the same shared
method the pipeline `AgentRunner` uses. Requirements source: [design.md](design.md), Phase 2.

## Design

### Component map

| Component | File | Kind |
|---|---|---|
| `ChatEnqueueHook`, `LambdaChatRejection` | `deployment/aws/serverless/core/router/rest_lambda.py` | type alias, exception |
| `DefaultEndpointsHandler.set_enqueue_hook`, `RESTLambdaRouter.set_chat_enqueue_hook`, `Lambda.set_chat_enqueue_hook` | `rest_lambda.py`, `aklambda.py` | new methods |
| `integration` package | `deployment/aws/serverless/core/integration/__init__.py` (new) | package docstring, imports nothing |
| `LambdaHost`, `LambdaHostGuard` | `deployment/aws/serverless/core/integration/base.py` (new) | bases lifted from `webhook_host.py` |
| `LambdaEventTranslator` | `deployment/aws/serverless/core/integration/event_translator.py` | moved from `serverless/core/`, unchanged |
| `LambdaWebhookHost`, `LambdaWebhookGuard` | `deployment/aws/serverless/core/integration/webhook.py` | moved from `webhook_host.py` beside `router/`, rebased, behaviour unchanged |
| `LambdaThreadHost`, `LambdaThreadGuard` | `deployment/aws/serverless/core/integration/thread.py` (new) | new |
| `ThreadRequestHandler` (`_validate_chat`, `prepare_for_queue`, `_queue_attributes`, `read_handler`) | `integration/thread/thread_chat.py` | methods lifted out of `run_chat` / `_enqueue_request` |
| `ThreadRESTRequestHandler` (`list_threads`, `get_thread`) | `integration/thread/thread_chat.py` | route closures lifted into named methods |
| `AuthorisedRESTRequestHandler.authoriser` | `api/handler.py` | read-only property |
| `ThreadRecorder.record_queued_reply` | `integration/thread/recorder.py` | the shared reply-recording home |
| `AgentRunner._record_thread_reply`, `ServerlessAgentRunner._record_thread_reply` | `pipeline/agent_runner.py`, `deployment/aws/serverless/akagentrunner.py` | thin lazy-import wrappers |

All paths below are relative to `ak-py/src/agentkernel/` unless they start with `ak-deployment/`,
`examples/` or `docs/`.

### Chat route takeover (`rest_lambda.py`, `aklambda.py`)

The built-in chat handlers stay where they are (`DefaultEndpointsHandler`, `rest_lambda.py:16`). The
host does not replace them; it plugs a hook into the one place every queued chat request passes
through, `_send_to_queue` (`rest_lambda.py:129-153`), which serves both `rest_sync`
(`_handle_rest_sync`, `:187`) and the `rest_async` submit (`_handle_async_submit`, `:222`). The poll
(`_handle_async_poll`, `:243`) never calls it, so it is unchanged by construction.

```python
# rest_lambda.py
# Given the parsed chat envelope, may rewrite payload.body in place; returns extra SQS attributes.
type ChatEnqueueHook = Callable[[BaseRequest], dict[str, str]]

class LambdaChatRejection(Exception):
    """A hook's refusal: answered as (status_code, body), never as the generic 500."""
    def __init__(self, status_code: int, body: dict[str, Any]): ...

class DefaultEndpointsHandler:
    def set_enqueue_hook(self, hook: ChatEnqueueHook) -> None:
        # AKConfigError when SQSHandler.get_input_queue_url() is empty (non-queue: chat never enqueues)
        # ValueError when a hook is already set (two hosts would each think they own the chat route)

class RESTLambdaRouter:
    def set_chat_enqueue_hook(self, hook: ChatEnqueueHook) -> None:  # delegates to _endpoints_handler

# aklambda.py
class Lambda:
    @classmethod
    def set_chat_enqueue_hook(cls, hook: ChatEnqueueHook) -> None:
        # AKConfigError when _get_router() is not a RESTLambdaRouter (WebSocket mode)
```

Changes inside `DefaultEndpointsHandler`:

1. `__init__` sets `self._enqueue_hook: ChatEnqueueHook | None = None`.
2. `_send_to_queue`: after its three existing checks (`body`, `request_id`, `session_id`), and
   before `SQSHandler.send_message_to_input_queue`, call the hook when set. Its result becomes
   `custom_message_attributes` (`SQSHandler.CustomAttribute(name, value, STRING)` per entry). The
   body is dumped **after** the hook, so a rewritten body (`requests` set, `files` / `images`
   cleared) is what is enqueued.
3. `_handle_request` (`:110-127`): `except LambdaChatRejection as r: return (r.status_code, r.body)`
   ahead of the existing `except Exception` (500).

Rules:

1. **The route stays the router's.** Path, methods, the `default_chat_path` key, the env-path match
   (`:397-402`) and every response shape are untouched; only the enqueue gains a step.
2. **Hooks run after the envelope checks the route already makes.** A missing `body`, `request_id`
   or `session_id` still raises `ValueError` → 500, as today, and the hook never runs for it.
3. **One hook.** A second `set_enqueue_hook` is a programming error, not a merge.

`ChatEnqueueHook` is a type alias, the precedent being `WebhookBypass` in
`deployment/aws/serverless/akauthorizer.py:26`: one caller, nothing to select between, so no ABC.

### The `integration/` package

The Lambda hosts get their own package beside `router/`, mirroring `agentkernel/integration/`
(webhooks from `integration/adapter`, threads from `integration/thread`):

| Module | Holds | Origin |
|---|---|---|
| `__init__.py` | the package docstring only | new |
| `base.py` | `LambdaHost`, `LambdaHostGuard` | new, lifted from `webhook_host.py` |
| `event_translator.py` | `LambdaEventTranslator` | moved from beside `router/` |
| `webhook.py` | `LambdaWebhookHost`, `LambdaWebhookGuard` | `webhook_host.py` beside `router/`, moved and rebased |
| `thread.py` | `LambdaThreadHost`, `LambdaThreadGuard` | new |

- Moved, not copied: class names, public signatures and error messages stay; the old modules are
  deleted with no re-export shims (users import from `agentkernel.aws`). Relative imports gain one
  package level.
- Every module imports FastAPI and Starlette, so `__init__.py` imports nothing and
  `serverless/core/__init__.py` does not import the package (see Exports).
- The package docstring explains, without the specs, what a host is (an object that runs a
  FastAPI-style handler inside the request-handler Lambda, not a server), why it is needed, how an
  app builds and registers one, and that hosts never run in the agent runner.

### `LambdaHost` and `LambdaHostGuard` (new `core/integration/base.py`)

Lifted from `webhook_host.py` so both hosts share one copy (the "classes, not scripts" rule for
shared logic). Line references in this section are into `develop`'s `webhook_host.py`. Imports
Starlette like the rest of the package, so it is reached only through the lazy exports.

```python
class LambdaHost:
    _loop: ClassVar[asyncio.AbstractEventLoop | None] = None   # moved from LambdaWebhookHost (webhook_host.py:37)
    def __init__(self, translator: LambdaEventTranslator | None = None): ...
    async def _respond(self, endpoint, event) -> dict[str, Any]: ...   # moved verbatim (webhook_host.py:69-80)
    @classmethod
    def _run(cls, coro: Coroutine) -> Any: ...                         # moved verbatim (webhook_host.py:82-87)

class LambdaHostGuard:
    HOST_NAME: ClassVar[str]        # "LambdaWebhookHost" / "LambdaThreadHost", used in messages
    SUBJECT: ClassVar[str]          # "webhooks" / "threads", used in messages
    COMPLETE_ONLY_REASON: ClassVar[str]  # host-specific tail of the message_type error
    REST_MODES = (ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC)
    BASE_PATH_ENV = ("API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT")
    def _check_deployment(self, handler: RESTRequestHandler) -> None:
        # _check_mode, _check_transport(handler), _check_base_path_env: moved from webhook_host.py:117-150
```

- `_run` keeps `cls._loop`, so each host class holds its own loop (one per class per execution
  environment, never made the thread's current loop). Moving `_loop` to a shared base attribute
  read through `LambdaHost._loop` would break the `LambdaWebhookHost._loop` patch target
  `tests/test_lambda_webhook_host.py:160-167` and `:273-283` use.
- Message text is built from `HOST_NAME` and `SUBJECT`, so `LambdaWebhookGuard`'s messages stay
  byte-identical (`tests/test_lambda_webhook_host.py:297`, `:310`, `:319` match on them).

- `LambdaHost`'s docstring says what the base does for every host (event to request, the endpoint
  on the class's own loop, answer or exception back, so a failure never reaches `Lambda.handler`'s
  generic 500) and how to add a host: subclass `LambdaHost`, add a `LambdaHostGuard` subclass with
  its cold-start checks, add a lazy export.
- `LambdaHostGuard`'s docstring names the shared checks and why they run at cold start: a broken
  deployment fails the Lambda's init loudly instead of failing requests later.

`LambdaWebhookHost(LambdaHost)` and `LambdaWebhookGuard(LambdaHostGuard)` keep their public
signatures, check order (type, mode, transport, base-path env, verification settings) and behaviour.

### `ThreadRequestHandler` and `ThreadRESTRequestHandler` (`integration/thread/thread_chat.py`)

Lifted, not copied, so the host drives the exact code the pipeline route runs.

```python
class ThreadRequestHandler(RequestHandler):
    @property
    def read_handler(self) -> "ThreadRESTRequestHandler": ...          # the composed read handler (:249)
    def _validate_chat(self, body: BaseRunRequest) -> None: ...          # the two 400s, lifted from run_chat (:276-279)
    @staticmethod
    def _queue_attributes(body: BaseRunRequest) -> dict[str, str]: ...   # {} for a schedule block, else {ATTR_THREAD: "1"} (:265)
    async def prepare_for_queue(self, body: BaseRunRequest) -> dict[str, str]:
        # _validate_chat; _record_user_message unless schedule; return _queue_attributes(body)

class ThreadRESTRequestHandler(AuthorisedRESTRequestHandler):
    def list_threads(self, resolve_user: Callable[[], str | None], user_id, group_id, limit, cursor) -> dict: ...
    def get_thread(self, resolve_user: Callable[[], str | None], session_id, limit, cursor) -> dict: ...

class AuthorisedRESTRequestHandler:   # api/handler.py
    @property
    def authoriser(self) -> Authoriser | None: ...
```

- `run_chat` becomes `_validate_chat` → `_reject_unroutable` → `_record_user_message` (unless
  `schedule`) → `super().run_chat`; `_enqueue_request` uses `_queue_attributes`. Same order, same
  errors.
- `_record_user_message` (`:285-308`) keeps its name and body: `tests/test_thread_integration.py:511`
  patches it, and `prepare_for_queue` calls it through `self`, so that patch reaches both paths.
- `prepare_for_queue` is the pipeline route's edge work minus `_reject_unroutable`, whose mode and
  SSE-store checks are the pipeline's; on Lambda the guard checks the mode at cold start and the
  router refuses SSE (`rest_lambda.py:49-53`).
- The read methods hold the closure bodies (`:347-360`, `:364-381`) verbatim. `resolve_user` is a
  callable, not a value, so the manager-`None` 404 still comes **before** the 401 the FastAPI
  resolver can raise, exactly as today. The closures in `get_router()` pass
  `lambda: self._resolve_user(request)`; the Lambda host passes the gateway principal.

### `LambdaThreadHost` and `LambdaThreadGuard` (new `core/integration/thread.py`)

```python
class LambdaThreadHost(LambdaHost):
    def __init__(self, handler: ThreadRequestHandler, translator: LambdaEventTranslator | None = None):
        # LambdaThreadGuard().check(handler); then Lambda.set_chat_enqueue_hook(self._before_enqueue)
    def list_threads(self, event: dict[str, Any], context: Any) -> dict[str, Any]: ...  # GET /threads
    def get_thread(self, event: dict[str, Any], context: Any) -> dict[str, Any]: ...    # GET /threads/{session_id}
    def _before_enqueue(self, payload: BaseRequest) -> dict[str, str]: ...             # the ChatEnqueueHook
    @staticmethod
    def _principal(event: Mapping[str, Any]) -> str | None: ...  # requestContext.authorizer.principalId, "" -> None
    @staticmethod
    def _limit(value: str | None) -> int | None: ...             # int(); ValueError -> HTTPException(400)

class LambdaThreadGuard(LambdaHostGuard):
    HOST_NAME = "LambdaThreadHost"; SUBJECT = "threads"
    def check(self, handler: Any) -> ThreadRequestHandler: ...
```

`_before_enqueue(payload)`:

1. `return self._run(handler.prepare_for_queue(payload.body))`: validation, then (unless the body
   carries a `schedule` block) the agent precheck, `RequestBuilder`, `ThreadRecorder.pre_run` and
   the body rewrite; the result is `{ATTR_THREAD: "1"}`, or `{}` for a `schedule` block.
2. `HTTPException` → `LambdaChatRejection(e.status_code, e.detail)`. The detail is already the
   `{"error", "session_id"}` dict the pipeline answers with (`thread_chat.py:277-279`, `:305`), the
   same shape the runner's 400 record had.

Read routes:

- `list_threads`: `self._run(self._respond(endpoint, event))`. `endpoint` reads `user_id`,
  `group_id`, `limit`, `cursor` from `request.query_params` (the translator already builds the query
  string from `queryStringParameters`, `event_translator.py:145-154`) and calls
  `handler.read_handler.list_threads(lambda: principal, ...)`.
- `get_thread`: the same, with `session_id = event["pathParameters"]["session_id"]` (phase 1).
- Return values and `HTTPException`s go through `LambdaEventTranslator`, so status, headers and
  `{"detail": ...}` bodies are the ones FastAPI sends (`event_translator.py:69-98`).
- `principal` comes from the event, not from the handler's `Authoriser` (the guard requires none).
  When an authorizer approved the request, the listing is forced to that user and another user's
  thread → 403 (`PermissionError` from `ConversationThreadManager.get_thread`). With no authorizer,
  `principal` is `None` and the routes are open.

`LambdaThreadGuard.check(handler)`, in this order:

| # | Check | Failure |
|---|---|---|
| 1 | `isinstance(handler, ThreadRequestHandler)` | `TypeError` |
| 2 | `_check_deployment`: mode `rest_sync` / `rest_async`, message type `complete`, transport `sqs`, base-path env | `AKConfigError` (shared messages) |
| 3 | `handler.read_handler.authoriser is None` | `AKConfigError`: "Lambda authorizes at the API Gateway authorizer; build ThreadRequestHandler() without an Authoriser" |
| 4 | `multimodal.enabled` ⇒ `AttachmentStorageManager.store_is_shared()` (`core/multimodal/storage/storage_manager.py:112`) | `AKConfigError` naming `multimodal.storage_type` (the `AGUIPipelineRequestHandler` check, `integration/agui/queue_handler.py:104-110`) |
| 5 | `thread.type` is not `in_memory` (case-insensitive; a dotted `ThreadStore` path is trusted) | `AKConfigError` naming `thread.type` and the shared backends (the `AGUIPipelineRequestHandler` `session.type` check, `integration/agui/queue_handler.py:99-103`) |

Two more cold-start failures come from the pieces the host composes, not from the guard:

- No `thread` block: `ThreadRequestHandler()` raises `ValueError` before the host exists
  (`thread_chat.py:245-247`).
- Non-queue mode (no input queue URL): `Lambda.set_chat_enqueue_hook` raises `AKConfigError`.

### Reply recording (`recorder.py`, `agent_runner.py`, `akagentrunner.py`)

```python
class ThreadRecorder:
    @classmethod
    def record_queued_reply(cls, attributes: Mapping[str, Any], req: BaseChatRequest, status_code: int, response: Any) -> None:
        """Never raises. Records the assistant message for a request the edge recorded."""
```

- Holds the body of `AgentRunner._record_thread_reply` (`agent_runner.py:213-256`): the marker,
  status and empty-reply gate, the no-`thread`-block warning, the `ThreadRecorder(manager).post_run`
  call and the catch-all log. Warning and error texts are kept verbatim
  (`tests/test_thread_pipeline_recording.py:344`, `:368` match on them).
- `response` is what the runner holds: a response dict, whose `result` and `media_type` it reads
  (moved from `agent_runner.py:79-81`), or the reply itself (`StreamAgentRunner`'s joined deltas,
  `:345`).
- Each runner keeps a `_record_thread_reply` that checks `ATTR_THREAD` and only then imports
  `integration.thread.recorder` and delegates, so a runner with no marked traffic never imports the
  thread package (coupling rule 2 of the pipeline). The import sits inside the wrapper's own
  `try` / `except Exception`, so an import failure is logged, not raised.
  - `AgentRunner._record_thread_reply(message, body, status_code, response)`; both call sites pass
    the response, and the three extraction lines in `_process_run` are deleted.
  - `ServerlessAgentRunner._record_thread_reply(record, body, status_code, response)`: attributes
    from `SQSHandler.get_message_custom_attributes(record)`. Called from `process_message` **after**
    `_send_to_output_queue` (`akagentrunner.py:181`), for the reason the pipeline gives
    (`agent_runner.py:225-229`).
- `ServerlessStreamAgentRunner` and `on_permanent_failure` record nothing: the host rejects `async`
  mode, so no marked message reaches the stream runner, and a permanent failure has no reply.

### Exports

- `deployment/aws/__init__.py`: `"LambdaThreadHost": ".serverless.core.integration.thread"` in
  `_LAZY_EXPORTS`, and `LambdaWebhookHost` repointed to `".serverless.core.integration.webhook"`,
  plus the `TYPE_CHECKING` mirror. `from agentkernel.aws import Lambda` stays FastAPI-free.
- `deployment/aws/serverless/core/integration/__init__.py` imports nothing, and
  `deployment/aws/serverless/core/__init__.py` does not import the `integration` package.

### Consumer changes

| Consumer | Change |
|---|---|
| `DefaultEndpointsHandler` | hook slot, `_send_to_queue` call, `_handle_request` rejection branch |
| `RESTLambdaRouter`, `Lambda` | `set_chat_enqueue_hook` delegates |
| `LambdaWebhookHost` / `LambdaWebhookGuard` | moved to `integration/webhook.py`, rebased on `LambdaHost` / `LambdaHostGuard`; no behaviour change |
| `ThreadRequestHandler` | `run_chat` / `_enqueue_request` call the lifted methods; new `prepare_for_queue`; `_record_user_message` unchanged |
| `ThreadRESTRequestHandler` | closures delegate to `list_threads` / `get_thread` |
| `AgentRunner`, `StreamAgentRunner` | wrapper delegates to `ThreadRecorder.record_queued_reply` |
| `ServerlessAgentRunner` | gains `_record_thread_reply`, called after the output send |

### Terraform (`ak-deployment/ak-aws/serverless/state.tf`)

- `:608-610`: pass `create_dynamodb_thread_table`, `dynamodb_thread_table_arn` and
  `dynamodb_thread_table_name` to the request-handler module unconditionally (drop the `queue_mode`
  ternaries). The table itself is created once at the root (`state.tf:357-370`). The module's flag
  only gates the IAM policy (`modules/request-handler/main.tf:93-118`) and the
  `AK_THREAD__DYNAMODB__TABLE_NAME` env var (`:390`).
- Comments at `:603-604` and `:611-613` that contrast with "the thread wiring" are reworded.
- No new variable. In queue mode with `create_dynamodb_thread_table = false`, nothing changes.

### Example: `examples/aws-serverless/thread-openai` (new)

Copied from `examples/aws-serverless/slack-openai`, minus Slack:

| File | Content |
|---|---|
| `agents.py` | the OpenAI agent, imported by both Lambdas (the request handler needs it for the agent precheck) |
| `lambda_request_handler.py` | the design's snippet plus `import agents` |
| `lambda_agent_runner.py`, `lambda_response_handler.py` | as in `slack-openai` |
| `lambda_auth.py` | demo `AuthValidator` whose subject is the user named by the token, so the read routes show principal scoping |
| `config.yaml` | `execution.mode: rest_sync`, `execution.queues.type: sqs`, `thread.type: dynamodb`, `session.type: dynamodb` |
| `deploy/main.tf` (+ `variables.tf`, `outputs.tf`, `providers.tf`, `terraform.tfvars`, `deploy.sh`, `Dockerfile.agent_runner`) | `queue_mode = true`, `create_dynamodb_thread_table = true`, `gateway_endpoints` with `threads` GET and `threads/{session_id}` GET |
| `lambda_test.py` | chat twice with `user_id`, then `GET /threads?user_id=` and `GET /threads/{session_id}`: two user and two assistant messages in order; a chat without `user_id` → 400 |
| `build.sh`, `pyproject.toml`, `README.md` | as in `slack-openai`, adapted |

### Config changes

No config changes: no `AKConfig` field, no env var, no Terraform variable. The `thread` block
selects the store, `create_dynamodb_thread_table` provisions it, and creating `LambdaThreadHost` is
the enablement (the integration rule: mounting is the switch).

### Behavioural changes

All only when `LambdaThreadHost` is created. Without it, every path below is byte-for-byte today's.

1. **Chat requires `user_id`** (intentional, design): missing → 400, nothing written or enqueued.
2. **Edge rejections** (intentional, design): missing prompt, unknown agent and attachments the
   multimodal config rejects → 400 from the chat route, before any thread write. In `rest_async` the
   400 now comes from the submit, not from the poll. In `rest_sync` the status and body shape are
   the same as the runner's record.
3. **User message written before enqueue; reply recorded after the output send** (intentional,
   pipeline parity). If the SQS send fails after recording, the thread holds an unanswered user
   message and the client gets the existing 500. A client retry with the same `request_id` records
   the user message again; FIFO dedup still runs the agent once. The pipeline route behaves the same.
4. **Attachments travel as references**: `files` / `images` are cleared from the queued body and
   `requests` carries `AgentRequestAttachmentRef`s. The SQS body shrinks; the runner already honours
   `requests` (`akagentrunner.py:178`).
5. **Thread naming runs in the request-handler Lambda.** It needs `litellm` and the model's key
   there; without them `ThreadNamingStrategy` falls back to the prompt prefix (unchanged fallback).
6. **Read routes answer a non-integer `limit` with 400** (design). FastAPI answers 422 there; this is
   the one status that differs from the FastAPI routes.
7. **Request-handler Lambda gets the thread table in queue mode** (Terraform, intentional).
8. **Pipeline recording code moves** (refactor): same behaviour, same log texts; the log records
   now come from the `ak.integration.thread.recorder` logger instead of `ak.pipeline.agent_runner`.
9. **Each Lambda host class has its own event loop** (refactor): `LambdaWebhookHost` keeps its loop;
   `LambdaThreadHost` gets its own. Neither is made current.

**Non-changes:** the chat route's path, methods and success bodies; the `rest_async` poll; the
no-env-vars branch; `Lambda.register` / `_wrap_response`; `APIGatewayAuthorizer`; the API Gateway
Terraform module; `LambdaWebhookHost`'s public API and messages; `ThreadRequestHandler` and
`ThreadRESTRequestHandler` routes and responses; the thread data layout (both sides write through
`ThreadRecorder`, as the pipeline does); the SQS wire format of unmarked messages.

## Error handling

| Failure | Where | Surfaces as |
|---|---|---|
| no `thread` block | `ThreadRequestHandler()` | `ValueError` at cold start |
| wrong handler type | guard | `TypeError` at cold start |
| non-REST mode, `delta`, non-`sqs` transport, missing base-path env | guard | `AKConfigError` at cold start |
| `ThreadRequestHandler` with an `Authoriser` | guard | `AKConfigError` at cold start |
| unshared attachment store with multimodal on | guard | `AKConfigError` at cold start |
| `thread.type: in_memory` | guard | `AKConfigError` at cold start |
| no input queue URL (non-queue) | `Lambda.set_chat_enqueue_hook` | `AKConfigError` at cold start |
| second hook | `DefaultEndpointsHandler.set_enqueue_hook` | `ValueError` at cold start |
| missing body / `request_id` / `session_id` | `_send_to_queue`, before the hook | 500, as today |
| missing prompt or `user_id`, unknown agent, rejected attachments | hook | 400 `{"error", "session_id"}`, nothing written |
| thread store failure while recording the user message | hook (`pre_run` raises a non-`ValueError`) | 500 via `_handle_request`'s catch-all; nothing enqueued |
| SQS send failure after recording | `_send_to_queue` | 500, as today; the user message stays recorded |
| agent-runner Lambda without a `thread` block | `record_queued_reply` | warning, reply not recorded, message succeeds |
| thread store failure while recording the reply | `record_queued_reply` | logged, message succeeds (no retry, the reply is already delivered) |
| read route: thread support off / not found / not owned / bad `limit` or cursor | `ThreadRESTRequestHandler` methods, host | 404 / 404 / 403 / 400, FastAPI-shaped `{"detail": ...}` |
| any other read-route exception | `LambdaHost._respond` | plain-text 500, never the exception text |

Concurrency: a Lambda execution environment serves one invocation at a time, and the stores the
hook writes through are the shared, lock-guarded `ConversationThreadManager` singleton. Hot-path
cost: one thread-store read and two writes per chat request (get-or-create plus append), and one
append per reply, only with the host created.

## Testing

New test files:

- `ak-py/tests/test_lambda_thread_host.py` (pattern: `test_lambda_webhook_host.py`, env and config
  via `monkeypatch`, `InMemoryThreadStore`, `SQSHandler.send_message_to_input_queue` patched):
  - chat `rest_sync` and `rest_async`: user message recorded, `thread` attribute on the send,
    response unchanged
  - missing `user_id` / prompt, unknown agent, attachments with multimodal off: 400, no thread, no send
  - missing `session_id`: still 500, hook not called
  - `schedule` block: no thread, no `thread` attribute
  - base64 `images`: body sent with `requests` refs and no `images`; attachment in the store
  - `rest_async` poll: unchanged
  - read routes: list and get with and without `principalId` (forced user, 403, open), 404s, bad
    `limit` → 400, cursor paging, `pathParameters` read
  - every cold-start failure in the error table
  - `LambdaWebhookHost` and `LambdaThreadHost` in one process: each serves its routes
- `ak-py/tests/test_serverless_agent_runner_thread.py`: marked record → assistant message with its
  `media_type`; unmarked, status ≥ 400, empty reply → nothing; no `thread` block → warning; store
  failure → logged, `process_message` returns normally; recording happens after the output send.

Existing files:

- `tests/test_lambda_router.py`: add hook tests (attributes added, body rewritten before dump,
  `LambdaChatRejection` → its status, second hook → `ValueError`, non-queue → `AKConfigError`,
  WebSocket mode → `AKConfigError`). Existing tests unchanged.
- `tests/test_aws_lazy_exports.py`: picks `LambdaThreadHost` up through `__all__`; add an assertion
  that touching `Lambda` does not import `integration.thread`.
- Import paths only (the move into `integration/`), test logic unchanged:
  `test_lambda_webhook_host.py`, `test_lambda_webhook_parity.py`, `test_lambda_event_translator.py`,
  `test_serverless_integration_delivery.py`, and the webhook module names in
  `test_aws_lazy_exports.py`. The file names keep `webhook_host` / `event_translator`.
- Must pass untouched: `test_thread_pipeline_recording.py`, `test_thread_router.py`,
  `test_thread_integration.py`, `test_pipeline_agent_runner.py`,
  `test_serverless_status_propagation.py`, `test_serverless_request_handle.py`.

Run:

```bash
cd ak-py && uv run pytest tests/test_lambda_thread_host.py tests/test_serverless_agent_runner_thread.py \
  tests/test_lambda_router.py tests/test_lambda_webhook_host.py tests/test_lambda_webhook_parity.py \
  tests/test_lambda_event_translator.py tests/test_serverless_integration_delivery.py \
  tests/test_aws_lazy_exports.py tests/test_thread_pipeline_recording.py tests/test_thread_router.py \
  tests/test_pipeline_agent_runner.py tests/test_serverless_status_propagation.py
```

`examples/aws-serverless/thread-openai/lambda_test.py` runs against a deployed stack (weekly
matrix), like the other serverless examples.
