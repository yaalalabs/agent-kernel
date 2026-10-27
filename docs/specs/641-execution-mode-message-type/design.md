# #641: Split `execution.mode` into an invocation mode and a reply `message_type`

`ExecutionMode` mixes two settings in one enum. `rest_sync`, `rest_async` and `async` say how a
request is invoked, `stream` says how the reply is delivered, and `realtime` says both. This change
keeps `execution.mode` for invocation only (`rest_sync | rest_async | async | realtime`) and adds
`execution.message_type` (`complete | delta`) for reply delivery. Each mode names one transport:
SSE is `rest_sync + delta` and `async` is always WebSocket only. The legacy `stream` value, which
served both routes, is retired.

## Motivation

- **One enum, two questions.** `ExecutionMode` (`ak-py/src/agentkernel/core/model.py:314-332`) holds
  `rest_sync`, `rest_async`, `stream`, `async`, `realtime`. Its own docstring describes `stream` by
  delivery ("token streaming"), and the others mostly by transport.
- **`stream` has no fixed transport.** In one process it serves both routes:
  - REST: `POST /api/v1/chat` returns SSE (`api/handler.py:106`, `:137`; pipeline
    `pipeline/request_handler.py:272`; threads `integration/thread/thread_chat.py:78`, `:109`).
  - WebSocket: the same chunks are pushed over `/ws`. `pipeline/response_handler.py:72-80` picks
    the route per message by whether `ATTR_USER_ID` is set.
  - `async`, in contrast, rejects the REST route (`pipeline/request_handler.py:299`).
- **Delivery is checked as if it were a mode.** `ExecutionMode.STREAM` appears 29 times across 16 files in
  `ak-py/src` (pipeline, REST API, threads, AWS serverless and containerized, WS gateway). Most of
  these checks mean "emit chunks", not "use this transport". Examples: `StreamAgentRunner` selection at
  `pipeline/io_handler.py:142`, and the ECS runner dispatch at
  `deployment/aws/containerized/akagentrunner.py:172`.
- **"Is this WebSocket?" is spelled `mode in (ASYNC, STREAM)`** in seven places (`io_handler.py:85`, `:94`,
  `:227`; `ws/gateway.py:91`; `aws/serverless/aklambda.py:37`; `aws/containerized/ecs_io_handler.py:50`;
  `aws/serverless/akagentrunner.py:82`). Every new delivery variant would have to be added to each one.
- **`realtime` hides its delivery.** It always streams (`io_handler.py:145`,
  `pipeline/agent_runner.py:104`), but nothing in the config says so.
- **`rest_lambda.py:73` is dead.** `Lambda._is_websocket_mode` sends `STREAM` to the WebSocket router
  (`aklambda.py:37`), so the REST router's `STREAM` branch and its "SSE not supported" 400
  (`rest_lambda.py:299-315`) are never reached.

## Requirements

### Configuration

- `execution.mode`: `Optional[ExecutionMode]` with values `rest_sync | rest_async | async | realtime`.
  - The default stays `None`, read as `rest_sync` exactly as today (`request_handler.py:247`).
  - The field description drops `stream`.
- New field `execution.message_type: Optional[ReplyMessageType]` with values `complete | delta`, on
  `_ExecutionConfig` (`core/config.py:690`).
  - Default `None`, resolved to `delta` for `realtime` and to `complete` for every other mode.
  - Env var `AK_EXECUTION__MESSAGE_TYPE`, through the usual `AK_*` nesting.
  - Why a new field and not a derived value: `async + complete` and `async + delta` differ only in
    this field, so no existing config can express the choice.
- `ReplyMessageType(str, Enum)` lives in `core/model.py` next to `ExecutionMode`.
  - It is not named `MessageType`, so it doesn't clash with the nested `WebSocketHandlerABC.MessageType`
    (`pipeline/ws/base.py:68`). Modules such as `pipeline/response_handler.py` import both.
  - The config field keeps the issue's name, `message_type`.
- No other new configuration. There is no `enabled` flag, and `realtime` pacing stays in
  `execution.realtime`.

### Valid combinations

A combination outside this table fails at config load with `AKConfigError` that names both fields
and the valid alternatives.

| `mode` | `complete` | `delta` |
| --- | --- | --- |
| `rest_sync` (or unset) | JSON reply | SSE on the REST route; WebSocket routes not served |
| `rest_async` | submit + poll | ❌ (polling returns one stored reply) |
| `async` | WebSocket, whole reply; REST chat route rejected | WebSocket chunks; REST chat route rejected |
| `realtime` | ❌ | integration gateway, chunks (unchanged; `delta` may be set explicitly or left unset) |

- **One mode, one transport.** `async` means WebSocket only for both message types.
  - Under `async + delta`, the REST chat route returns the existing `async` 400 "connect to /ws instead"
    (`request_handler.py:299`). The `ATTR_USER_ID` route split in `response_handler.py:72-80` goes away,
    because every `async + delta` reply goes to WebSocket.
  - `async + delta` on the `in_memory` transport needs an `auth_validator`, the same as `async` does today
    (`io_handler.py:220`).
  - Intentional behaviour change: no single config serves SSE and WebSocket together any more, which
    today's `stream` does in one process.
- `rest_sync + delta` is the only SSE configuration. It serves SSE only, and no WebSocket is co-hosted or required.
  - On the bare `RESTAPI.run()` and direct paths it behaves like today's `stream` without an `auth_validator`.
  - `IOHandler.run(auth_validator=...)` logs the existing "auth_validator ignored" warning
    (`io_handler.py:108-113`) instead of co-hosting `/ws`.
  - On a broker transport (`sqs`, `kafka`, `nats`) it needs a shared response store that can hold
    chunks: Redis or Valkey once #755 merges. DynamoDB cannot (`response_store/base.py:54`).
    - Otherwise `IOHandler` and `ECSIOHandler` fail at startup with `AKConfigError`, naming
      `async + delta`. Today this is a 400 on every request (`request_handler.py:304`).
- `rest_sync + delta` on AWS Lambda fails at router init, naming `async + delta` or a Function URL
  streaming entry point. API Gateway REST cannot stream (`rest_lambda.py:299-315`).
- Messaging webhooks (`LambdaWebhookHost`, `webhook_host.py:92`) keep requiring a REST mode, and
  also require `message_type: complete`. Platform adapters deliver whole messages.

### Legacy `stream`

- `ExecutionMode.STREAM` is removed.
- No single replacement covers what `stream` does today, so a silent alias would break some
  deployments:
  - SSE deployments need `rest_sync + delta`. These are the bare `RESTAPI.run()` path, direct REST,
    and single-container deployments: ECS Simple REST (one container running `RESTAPI`), Azure
    Container Apps or Cloud Run. ECS queue mode runs `stream` as WebSocket today, so it is not one.
  - WebSocket deployments need `async + delta`. These are AWS Lambda WS, ECS WS and the Helm `wsGateway`.
  - Mapped to `async + delta`, an SSE deployment on `in_memory` with no `auth_validator` would fail at
    startup (`io_handler.py:220`).
- **Hard fail, no alias.** `execution.mode: stream` fails at config load with `AKConfigError`. This
  applies whether it comes from YAML, `AK_EXECUTION__MODE` or Helm `--set`.
  - A `model_validator(mode="before")` on `_ExecutionConfig` catches it before enum parsing. Without
    that, the user would get Pydantic's generic "not a valid enum member" error.
  - The message names both replacements: `rest_sync` + `message_type: delta` for SSE, and `async` +
    `message_type: delta` for WebSocket.
  - The release notes list it as a breaking config change, with the same two-line migration.

### Code that branches on the mode

- Every check that means "emit chunks" reads `message_type == ReplyMessageType.DELTA` and
  `mode != REALTIME` instead of `mode == STREAM`.
  - `realtime` is always `delta` but has its own runner. A bare `delta` check would send voice turns
    to `StreamAgentRunner`, because `io_handler.py:142` and ECS `akagentrunner.py:172` test `STREAM`
    before `REALTIME`.
  - This covers runner selection, output-consumer and response-handler delivery, the REST SSE branch,
    the threads SSE branch, the WS direct-stream branch, and the A2UI warning (`a2ui/hook.py:115`, which
    today compares to the string `"stream"`).
- Every check that means "WebSocket" reads `mode == ASYNC` through one shared predicate on
  `ExecutionConfig`, not seven copies of a tuple.
  - The predicates live as methods or properties on `_ExecutionConfig`, e.g. `is_websocket`,
    `is_delta`, `resolved_message_type`. They are not module-level functions.
- `_validate_topology` (`io_handler.py:217-245`) and `WebSocketGateway` validation (`ws/gateway.py:91`) are
  rewritten against the matrix. The errors they raise today for `rest_sync`, `rest_async`, `async` and
  `realtime` stay the same.
- `rest_lambda.py:73` (the dead `STREAM` branch) is removed. `rest_sync + delta` is rejected at
  router init instead.

### Deployment

- Terraform (AWS serverless and containerized) gets a `message_type` variable (default `null`),
  injected as `AK_EXECUTION__MESSAGE_TYPE` wherever `AK_EXECUTION__MODE` is injected today
  (`containerized/modules/agent-runner/main.tf:39`, `modules/rest-service/main.tf:43`,
  `serverless/state.tf:633`, `:649`, `:738`).
  - `execution_mode` validation (`serverless/variables.tf:61`, `containerized/variables.tf:267`)
    drops `stream`. Its `error_message` names the same two replacements, so `terraform plan` fails
    before anything is deployed.
  - The WebSocket conditions `contains(["async","stream"], …)` (`containerized/state.tf:25`,
    `variables.tf:66-307`) become `execution_mode == "async"` once `stream` is gone.
  - The new combination rules are validated in Python only, not duplicated in HCL.
- The Helm chart passes `execution.message_type` through like `execution.mode`. The chart CI
  (`.github/workflows/chart-test.yaml:78`, `:116`) gets one render using `async + delta`.
- Azure and GCP modules inject no execution mode and need no change. Verify this during the spec.

### Docs and skills

- Every `stream` reference is updated to the new pair. This covers about 30 files in
  `docs/docs/`, `ak-py/README.md`, the bundled skills (`ak-add-capabilities`, `ak-cloud-deploy`),
  `.agents/skills/ak-dev-architecture`, `ak-deployment/ak-k8s/README.md` and the AWS module READMEs.
- `docs/versioned_docs/` and existing `docs/specs/` are left as written.

### Tests

- Config: every cell of the matrix, the defaults (`None` resolves to `complete`, or `delta` for
  `realtime`), and `stream` from YAML and from env failing with the migration message
  (asserting both replacements appear in it).
- Each rewritten branch keeps its current test coverage. The 13 test files that reference
  `ExecutionMode` and their roughly 33 `STREAM` / `"stream"` hits move to the new pair.
- One new test per newly reachable combination: `rest_sync + delta` serves SSE with no WS co-host
  (pipeline and direct), `async + delta` rejects the REST chat route, and `rest_sync + delta` on the
  Lambda REST router is rejected at init.

## Non-goals

- No new transport (for example, SSE on Lambda through a Function URL) and no per-request choice
  of delivery. Both settings stay process-level, as `execution.mode` is today
  (`model.py:317-318`).
- No change to the chunk format (`StreamChunk`), SSE framing, the WS message types, or the
  response-store chunk API.
- No change to `realtime` behaviour. It only gains an explicit (forced) `message_type`.

## Open questions

- None. All design questions are resolved: the enum is named `ReplyMessageType`, `async` is
  WebSocket only, SSE is `rest_sync + delta`, and `stream` is a hard fail.
