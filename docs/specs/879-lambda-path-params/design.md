# #879: Path-parameter routing and conversation threads on Lambda

`RESTLambdaRouter` matches only the concrete request path, so a route registered with a path
parameter (`Lambda.register("/threads/{session_id}", ...)`) can never dispatch. Phase 1 makes it
dispatch by looking the route up under the resource template API Gateway already matched
(`event["resource"]`), so the router itself never matches paths. Phase 2 (conversation
threads as a Lambda integration, below) builds on this.

## Phase 1: Path-parameter routing in the Lambda REST router

### Motivation

- `dispatch()` keys the route lookup on the concrete path only:
  - `event_path = event.get("path") or event.get("resource") or "/"`
    (`ak-py/src/agentkernel/deployment/aws/serverless/core/router/rest_lambda.py:377` on `develop`).
  - The key is `event_path.removeprefix(env_base_path)` (`rest_lambda.py:386` on `develop`), so
    `GET /api/v1/threads/abc123` looks up `/threads/abc123` and never finds `/threads/{session_id}`.
- `register()` already stores templates verbatim: `_normalize_path` only fixes the leading and
  trailing slashes (`router/common.py:22`), so `{...}` survives into `_routes` (`rest_lambda.py:351`
  on `develop`).
- API Gateway REST v1 already does the matching: the Lambda proxy event carries the matched template
  in `resource` and the values in `pathParameters`.
- The Terraform module already accepts template paths: `gateway_endpoints` paths are split on `/`
  into up to three `path_part`s (`ak-deployment/ak-aws/serverless/modules/api-gateway/main.tf:5-13`),
  the integration is `AWS_PROXY` (`:115`), and the Lambda permission covers `execution_arn/*/*` (`:124`).
- The gap already shapes code: `examples/aws-serverless/schedule-openai` used `/schedules/get`,
  `/schedules/amend` and `/schedules/cancel` with the task id in the query or body, documented as
  "no `{task_id}` path parameters".
- #527 found the gap and drafted a fix, then dropped it from scope
  (`docs/specs/527-thread-store-deployment/design.md`, Non-goals).

### Requirements

#### Route resolution (`RESTLambdaRouter`)

- A route registered as `Lambda.register("/foo/{id}", method=...)` dispatches when API Gateway
  matched that template.
  - Lookup key: `event["resource"]` with the `/<api_base_path>/<api_version>` prefix stripped.
  - Handlers read the values from `event["pathParameters"]`; the router does not parse them.
- The router does no path matching of its own: when templates overlap, API Gateway's precedence
  decides (a static segment beats a `{parameter}` at the same level).
- Fallback to the concrete path (`event["path"]`) when the resource is not registered for the method.
  - Needed only for a catch-all `{proxy+}` resource in front of the Lambda (see the note below).
  - The router supports API Gateway REST (v1) events only, where `path` and `resource` are always
    both present. Hand-built unit-test events without `resource` also fall through to `path`.
- Unchanged paths:
  - The chat endpoint check (`event_path == env_agent_endpoint`) still compares the concrete path.
  - The no-env-vars branch still sends everything to the default chat handler.
  - The no-match error still names the concrete path.
  - Static routes resolve as before (`resource == path` for them).

#### Note: why the fallback to `event["path"]` is needed

- **The rule: the router uses `path` when `resource` is not a registered route.** Not when `resource`
  is missing: under API Gateway REST it is always present.
- What each key holds:

  | Key | Holds | Example (`GET /api/v1/schedules/t1`, our Terraform) |
  |---|---|---|
  | `resource` | the gateway resource that matched, as declared, braces included (never filled in) | `/api/v1/schedules/{task_id}` |
  | `pathParameters` | the values for its `{...}` placeholders | `{"task_id": "t1"}` |
  | `path` | the actual request path | `/api/v1/schedules/t1` |

- So `resource` is a usable route key only when the gateway declares each route as its own
  resource, as our Terraform module does. Behind a catch-all `{proxy+}` resource it is present but
  is always `/api/v1/{proxy+}`, which is not one of our routes.
- `{proxy+}` is API Gateway's catch-all resource: a greedy path parameter whose value is the whole
  rest of the path, one or more segments. `{task_id}` captures exactly one segment; `{proxy+}`
  captures everything after it, so its value can be a route, or a route plus its values:

  | Resource `/api/v1/{proxy+}`, request | `pathParameters` |
  |---|---|
  | `GET /api/v1/schedules` | `{"proxy": "schedules"}` |
  | `GET /api/v1/schedules/t1` | `{"proxy": "schedules/t1"}` |
  | `GET /api/v1/schedules/t1/history` | `{"proxy": "schedules/t1/history"}` |

  A deployer who fronts our Lambda with their own gateway may use it, so they never have
  to redeploy the gateway when a route is added in code. Behind it, `resource` is the same
  `/api/v1/{proxy+}` for every request, so it never names the route that was hit. The only place
  the route is still visible is `path`.
- Complete example. The application registers:

  ```python
  @Lambda.register("/schedules", method="GET")
  def list_schedules(event, context): ...

  @Lambda.register("/schedules/{task_id}", method="GET")
  def get_schedule(event, context): ...
  ```

  `_routes` holds the keys `/schedules` and `/schedules/{task_id}`.

  - **Our Terraform module** (`gateway_endpoints` declares `schedules` and `schedules/{task_id}`, one
    resource each):

    | Request | `path` | `resource` | Key from `resource` | Key from `path` | Handler |
    |---|---|---|---|---|---|
    | `GET /api/v1/schedules` | `/api/v1/schedules` | `/api/v1/schedules` | `/schedules` ✅ | not tried | `list_schedules` |
    | `GET /api/v1/schedules/t1` | `/api/v1/schedules/t1` | `/api/v1/schedules/{task_id}` | `/schedules/{task_id}` ✅ | not tried | `get_schedule`, `pathParameters = {"task_id": "t1"}` |

    `resource` always gives the answer, so the fallback never changes the outcome here.

  - **A deployer's own gateway with one `/api/v1/{proxy+}` resource**:

    | Request | `path` | `resource` | Key from `resource` | Key from `path` | Handler |
    |---|---|---|---|---|---|
    | `GET /api/v1/schedules` | `/api/v1/schedules` | `/api/v1/{proxy+}` | `/{proxy+}` ❌ not registered | `/schedules` ✅ | `list_schedules` |
    | `GET /api/v1/schedules/t1` | `/api/v1/schedules/t1` | `/api/v1/{proxy+}` | `/{proxy+}` ❌ not registered | `/schedules/t1` ❌ not registered | none: "No registered route" → 500 |

    The full event for the first row:

    ```json
    {
      "httpMethod": "GET",
      "path": "/api/v1/schedules",
      "resource": "/api/v1/{proxy+}",
      "pathParameters": {"proxy": "schedules"}
    }
    ```

- Without the fallback, the first `{proxy+}` row returns 500 instead of `list_schedules`. Static
  routes behind `{proxy+}` work on `develop` today, because the router looked up `path` only, so
  removing the fallback would break a working setup.
- The fallback cannot make template routes work behind `{proxy+}` (second `{proxy+}` row). The
  gateway never reports the matched template there, and the router does not match templates itself
  (Non-goals). Template routes need each route declared as its own resource, as our Terraform module does.

#### Configuration and Terraform

- No new configuration, no new `AKConfig` fields, no Terraform module change.
  - Deployers declare templates in `gateway_endpoints` (`{ path = "orders/{order_id}", method = "GET" }`),
    with the same `{name}` as the registered route.

#### Example: `examples/aws-serverless/schedule-openai`

- Management routes use the containerized paths:
  `GET /schedules`, `GET` / `PUT` / `DELETE /schedules/{task_id}`.
  - Task id comes from the path only, never the query or body.
  - `?user_id=` stays as the demo's stand-in for an authorizer.
- `deploy/main.tf`, `lambda_test.py` and `README.md` follow the new routes.

#### Docs and skills

- `docs/docs/deployment/aws-serverless.md`: a "Path and query parameters" section (usage,
  `gateway_endpoints`, the precedence rule, the overlap warning, API Gateway REST only) and the
  scheduling management routes on Lambda.
- `docs/docs/advanced/scheduling.md`: how management routes are served on Lambda.
- `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`: the serverless schedule routes.
- `Lambda.register` and `RESTLambdaRouter` docstrings mention path parameters.

### Non-goals

- Route authorization on any cloud.
- Our own template matcher, or `{proxy+}`-to-route mapping inside the router.
- Any invoker other than API Gateway REST (v1): ALB targets, Function URLs, HTTP API payload 2.0,
  direct invokes. Their events use other shapes and keys, and the router does not support them,
  before or after this change.
- Path-parameter routes behind a `{proxy+}` resource (see the fallback note).
- Moving the chat endpoint check onto `resource` (it would change custom-domain behaviour; out of scope).
- GCP and Azure.

### Open questions

- None. Settled during implementation:
  - Resource first with path fallback, rather than swapping `event_path` to prefer `resource`:
    the swap would break chat and every custom route behind a `{proxy+}` resource.

## Phase 2: Conversation threads as a Lambda integration

Host the thread integration on AWS Lambda the way the messaging integrations are hosted: a
`LambdaThreadHost` wraps the same `ThreadRequestHandler` the queue pipeline mounts, and creating it
turns threads on. It takes over the built-in chat route (the one Terraform already creates), so that
route records the user message and marks the queued request. The agent-runner Lambda records the
reply. The application registers the read routes with `Lambda.register`, as the Slack example
registers its webhook. Queue mode only, `rest_sync` and `rest_async`.

### Motivation

- Threads are an integration: mounting a handler turns them on, and the `thread` block only
  parameterizes the store (`ak-py/src/agentkernel/integration/thread/thread_chat.py:1-15`).
  - On the queue pipeline, `ThreadRequestHandler` records the user message and stamps `ATTR_THREAD`
    before enqueueing (`thread_chat.py:220-300`).
  - `AgentRunner._record_thread_reply` records the reply, with its `media_type`, when it sees the
    marker (`ak-py/src/agentkernel/pipeline/agent_runner.py:79-82`, `:213-256`).
- Lambda hosts integrations through `LambdaWebhookHost`, in queue mode only.
  - It wraps the pipeline's own handler and copies none of it
    (`webhook_host.py:16-32` in `ak-py/src/agentkernel/deployment/aws/serverless/core/` on `develop`).
  - It accepts `rest_sync` and `rest_async` only (`webhook_host.py:93`).
  - The app wires it with `@Lambda.register` functions that delegate to the host
    (`examples/aws-serverless/slack-openai/lambda_request_handler.py`).
- Lambda has no thread surface, so it records nothing and serves no read routes.
  - The chat route enqueues without `ATTR_THREAD`
    (`ak-py/src/agentkernel/deployment/aws/serverless/core/router/rest_lambda.py:146-151`).
  - `ServerlessAgentRunner.process_message` never records
    (`ak-py/src/agentkernel/deployment/aws/serverless/akagentrunner.py:166-183`).
  - The read routes are closures inside `ThreadRESTRequestHandler.get_router()` (`thread_chat.py:339`,
    `:362`), so nothing outside FastAPI can call them.
- How Lambda lost it: Lambda recorded threads through `ChatService` until #612 moved recording into
  the integration package. #612 accepted the loss for every deployment adapter and named
  "thread-aware deployment variants reusing `ThreadRecorder`" as the follow-up
  (`docs/specs/612-chatservice-refactor/design.md:201-205`). Lambda's first integration host came
  later (#768).
- An application cannot change the built-in chat route today.
  - Its handlers sit under an internal key, `"default_chat_path"` (`rest_lambda.py:24-29`, `:43-81`),
    and `dispatch()` maps the Terraform chat path to that key (`rest_lambda.py:395-401`).
  - `register()` skips a key that already exists (`rest_lambda.py:356-363`).
- Authorization on Lambda is one API Gateway authorizer on every route.
  - `APIGatewayAuthorizer` wraps the app's `AuthValidator`, which receives the request path and method
    (`ak-py/src/agentkernel/deployment/aws/serverless/akauthorizer.py:54-60`).
  - Terraform puts that one authorizer on every method
    (`ak-deployment/ak-aws/serverless/modules/api-gateway/main.tf:94-95`).
  - Nothing in the request-handler Lambda reads the user the authorizer approved (`principalId`).
- Attachments arrive as base64 `files` / `images` in the JSON chat body. `ThreadRecorder.pre_run`
  stores them in the multimodal attachment store and passes references on
  (`ak-py/src/agentkernel/integration/thread/manager.py:147-188`).
- Store provisioning exists: `create_dynamodb_thread_table`
  (`ak-deployment/ak-aws/serverless/variables.tf:179`) wires the table into the agent-runner Lambda
  (`ak-deployment/ak-aws/serverless/modules/agent-runner/main.tf:83-111`, `:341-342`). It reaches the
  request-handler Lambda in non-queue mode only (`ak-deployment/ak-aws/serverless/state.tf:608-610`).

### Requirements

#### Turning threads on

- Creating `LambdaThreadHost` is the switch, as mounting the handler is on FastAPI and the pipeline.
  - A `thread` block alone turns nothing on: without the host, chat, the queue messages and the
    agent runner behave exactly as today.
  - The host without a `thread` block fails at cold start.
- Application code, request-handler Lambda:

  ```python
  threads = LambdaThreadHost(ThreadRequestHandler())   # takes over the Terraform chat route

  @Lambda.register("/threads", method="GET")
  def list_threads(event, context):
      return threads.list_threads(event, context)

  @Lambda.register("/threads/{session_id}", method="GET")
  def get_thread(event, context):
      return threads.get_thread(event, context)

  handler = Lambda.handler
  ```

- The user never registers a chat route. The agent-runner and response-handler Lambdas need no
  code change; the agent runner needs the same `thread` block, to know which store to write to.
- The request-handler Lambda loads the agents (imports the module that builds them), as the
  pipeline's IO process does under `ThreadRequestHandler`: the chat route checks the agent exists
  before it writes a thread.

#### Supported modes

- Queue mode, `execution.mode` `rest_sync` or `rest_async`.
- Anything else fails at cold start: non-queue, WebSocket (`async`), realtime.

#### Chat route

- One chat endpoint: the built-in chat route Terraform creates (`agent_endpoint`). The host takes
  it over; the router gains the means to let it.
- Its client contract does not change: same request body shapes, same responses and status codes.
  - Exception: `user_id` becomes required. Without it → 400, and no thread is written.
  - Exception: a missing prompt, an unknown agent and rejected attachments, which the agent runner
    used to answer, are answered by the chat route before any thread write. Same 400, but in
    `rest_async` it comes back from the submit instead of the poll.
- The `rest_async` poll route is unchanged.
- Before enqueueing, the chat route records the user message (thread created or loaded) and marks
  the queued request with `ATTR_THREAD`.
  - Every rejection happens before any thread write.
  - A request with a `schedule` block records nothing and carries no marker.

#### Attachments

- Base64 `files` / `images` in the JSON chat body are recorded with the user message, as on the
  pipeline, and travel through the queue as references, not bytes.
- The attachment store must be reachable by both Lambdas: the host fails at cold start with a
  multimodal store the agent runner cannot reach (`in_memory`, `session_cache`).

#### Thread store

- The thread store must be reachable by both Lambdas: the request handler records the user message
  and serves the read routes, the agent runner records the reply. The host fails at cold start with
  `thread.type: in_memory` (the default), which keeps each Lambda's threads in its own process.

#### Reply recording (`ServerlessAgentRunner`)

- After sending the reply to the output queue, the agent-runner Lambda records the assistant message
  when the input message carries `ATTR_THREAD`, the status is below 400 and the reply is not empty.
  - The recorded reply keeps its `media_type` label.
- The recording logic in `AgentRunner._record_thread_reply` moves to one shared home in the thread
  package, used by the pipeline runner and `ServerlessAgentRunner`; it is not copied. Its rules
  carry over:
  - no `thread` block → warning, nothing recorded
  - a recording failure is logged and never fails the message
- Messages from any other producer (messaging integrations, schedule occurrences) carry no marker
  and record nothing.

#### Read routes

- `GET /threads` and `GET /threads/{session_id}`, registered by the app and delegated to the host.
- Responses, statuses and error bodies match the FastAPI thread routes.
- `session_id` from `event["pathParameters"]` (phase 1); `user_id`, `group_id`, `limit`, `cursor`
  from `queryStringParameters`; a non-integer `limit` → 400.

#### Authorization on the read routes

- Uses the existing API Gateway authorizer (`APIGatewayAuthorizer` + the app's `AuthValidator`).
  No second authorizer and no Terraform authorizer change.
  - The app applies its own rules to the thread routes inside its `AuthValidator`, using the request
    path and method it already receives.
- When the gateway authorizer approved the request, the read routes are limited to the approved
  user (`principalId`): a listing is forced to that user, and another user's thread → 403.
- With no gateway authorizer, the read routes are open, as on FastAPI with no `Authoriser`.
- A `ThreadRequestHandler` built with an `Authoriser` fails at cold start: Lambda authorizes at the
  gateway, and an `Authoriser` the host silently ignored would look like protection.

#### Reuse

- The thread handler, the recorder and the existing Lambda hosting pieces (`LambdaEventTranslator`,
  the `LambdaWebhookGuard` checks) are shared with the other surfaces, not copied.
- The Lambda hosts live in `deployment/aws/serverless/core/integration/`, mirroring
  `agentkernel/integration/`: one shared host base, `LambdaEventTranslator`, `LambdaWebhookHost`
  and `LambdaThreadHost`. The webhook host and the translator move there from `serverless/core/`.
- `LambdaThreadHost` is exported lazily from `agentkernel.aws`, like `LambdaWebhookHost`
  (`ak-py/src/agentkernel/deployment/aws/__init__.py:25` on `develop`), so `from agentkernel.aws import Lambda`
  stays FastAPI-free.

#### Configuration and Terraform

- No new configuration: no `AKConfig` field, env var or Terraform variable.
  - The existing `thread` block selects the store; `create_dynamodb_thread_table` provisions it.
- The request-handler Lambda gets the thread table in queue mode, because it now writes the user
  message: drop the `queue_mode` exclusion on the three thread inputs (`state.tf:608-610`).
- Deployers declare both read routes in `gateway_endpoints`:
  `{ path = "/threads", method = "GET" }` and `{ path = "/threads/{session_id}", method = "GET" }`.

#### Example

- `examples/aws-serverless/thread-openai` (the example #527 deferred), shaped like `slack-openai`:
  queue mode, a `thread` block, `create_dynamodb_thread_table = true`, the read routes declared,
  the request handler above, and a test that chats with `user_id`, then reads the thread back.

#### Tests

- Unit tests for everything above: chat recording and the marker, rejections with no thread written,
  `schedule` requests, the unchanged chat contract and poll route, attachments, reply recording,
  the read routes and their authorization, and every cold-start failure.
- The existing pipeline `AgentRunner`, `ThreadRequestHandler`, `ThreadRESTRequestHandler`,
  `LambdaWebhookHost` and Lambda router tests pass unchanged; the webhook host and translator
  tests change only their import paths, for the move into `serverless/core/integration/`.

#### Docs and skills

- `docs/docs/advanced/threads.md`: threads on Lambda.
- `docs/docs/deployment/aws-serverless.md`: a threads section beside "Messaging integrations".
- `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`: serverless threads.
- `.agents/skills/ak-dev-architecture`: `LambdaThreadHost` beside `LambdaWebhookHost`.

### Non-goals

- Non-queue mode on Lambda: no Lambda integration supports it, and it is planned for removal.
- WebSocket mode on Lambda.
- ECS queue mode: same gap (`ECSQueueRequestHandler`, `ECSAgentRunner`), separate deployment.
- A second API Gateway authorizer, or any Terraform authorizer change.
- Thread write routes (rename and others): FastAPI has none either.
- Multipart chat: Lambda has no multipart route; attachments come as base64 in JSON.
- GCP and Azure.

### Open questions

- None. Settled:
  - Recording is in scope, although #879 asks for the read routes only: since #612, Lambda writes
    no threads, so without recording the read routes would never return anything.
  - The name is `LambdaThreadHost`, not the issue's `ThreadLambdaHandler`: it follows
    `LambdaWebhookHost`, the pattern the other Lambda integrations use.
