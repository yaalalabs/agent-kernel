# #603: Identity layer, RBAC and agent registry: Implementation Plan

Builds `spec.md` in 28 iterations grouped into seven phases. Every iteration is one theme a
reviewer can read as a single diff and is expected to leave the branch green; within a phase only
the suites an iteration's Verify names are run, and the full suite (`cd ak-py && uv run --no-sync
pytest`) runs once at the end of each phase. The phase order is set by two dependencies: nothing above the
identity fix is worth building on a forgeable subject, and the omnichannel work (#243) needs the
identity interfaces frozen early and live principals on every surface soon after. Phase A freezes
the interfaces; phase B is the point after which every surface carries a real `Principal`.

## Parallel work: omnichannel

Omnichannel (#243, "Omnichannel: Functional Requirements") consumes identity and nothing else in
this change. Two branch points:

- **After iteration 3** (end of phase A, interfaces frozen) omnichannel can start its models,
  mapping store and tools against: `Principal` (`subject`, `provider`, `namespace`, `claims`), the
  `provider` prefix convention (`messaging:<platform>`, `realtime:<gateway>`, anything else is the
  shared direct channel), `BaseChatRequest.principal` as the body field every queue message
  carries, `InboundRequest.namespace` and `claims`, `Session.get_principal()` and
  `ToolContext.principal`, `SessionOwner`, and `ScheduledTask.principal`. These do not change in
  later iterations.
- **After iteration 12** (end of phase B, every surface establishes the principal) omnichannel
  can run end to end: its identity-sessions recording, link operations and fact tools see live
  principals on REST, AG-UI, WebSocket and every messaging integration.

Phases C to F (registry, authorization, tool gates, credentials) touch nothing omnichannel reads.
The one shared file after phase B is `core/tool.py` (`ToolContext.access_level` goes live in
iteration 18 and `credentials` lands in iteration 25, both additive).

## Reading the iterations

- Each iteration has a **Goal** (what is true of the branch once it lands), **Files** (every
  source file the diff touches, so the reviewer knows the diff's extent before opening it),
  **Steps** (in commit order, with the spec section each one implements) and **Verify** (the
  suites to run after the iteration; new files and changed files by name).
- Test cadence: after an iteration, run only the suites its Verify names. The full `ak-py` suite
  runs once at the end of each phase (after iterations 3, 12, 16, 20, 23, 25 and 28) and
  `make lint-check` with it; that phase-end run is what confirms the branch is green.
- Size rule: an iteration touches at most about ten source files beside its tests and has one
  kind of change. Phases C, D, E and F split along the component boundary: contract and config
  first, backends second, consumers third, so each diff is either new code with no caller or
  call-site changes against code already reviewed.
- Four transient states are deliberate and called out where they occur: iteration 1 adds types
  nothing reads yet; `BaseChatRequest.user_id` survives beside `principal` through iteration 2
  and leaves in 3; from iteration 2 every run is anonymous until its surface sets a principal in
  iterations 6 to 11 (threads and schedules answer 403 to every caller in that window, and a
  principal a client puts in a body is overwritten by the surface); the
  example suites that send `user_id` are red from iteration 3, and those importing
  `agentkernel.auth` from iteration 11, until iteration 12 migrates them. The branch-green
  criterion is the `ak-py` suite, which does not run the examples.
- Test stubs: the `FakeCfg` objects in `tests/test_module.py:80-84`, `tests/test_runtime.py:79-155`,
  `tests/test_agui_handler.py:122-134`, `tests/test_pipeline_ws.py:54-74`,
  `tests/test_schedule_tools.py:92` and `tests/test_ecs_websocket_routes.py:19-27` gain
  `identity = None` in iteration 4, `registry = None` in 15 and `authorization = None` in 17, each
  with the iteration that adds the config read.

## Phase A: Identity contract (iterations 1 to 3)

### Iteration 1: Identity models

- **Goal:** the types every later iteration and omnichannel build on exist, exported from
  `agentkernel.core`, with no consumer; behaviour is unchanged.
- **Files:** `core/model.py`, `core/__init__.py`, `core/chat_service.py`,
  `integration/adapter/base.py`.
- **Steps:**
  1. `AccessLevel`, `Principal` (`anonymous()`, `is_anonymous`, `with_actor`,
     `with_credential_ref`), `SessionOwner`, `ToolFilter` (`allows`, `reason`),
     `AgentSkillDescriptor`, `AgentIdentitySpec`, `AgentDescriptor` (`exposed_on`);
     `SystemTool.tier` with its default (spec 2). The declared tiers on the system tools come
     with the gate in iteration 18.
  2. `BaseChatRequest.principal: Optional[Principal] = None` beside `user_id`, which stays until
     iteration 3 (spec 2); `RequestBuilder._attach_additional_context` adds `"principal"` to
     `known_fields` in the same step, since the builder turns every unknown field into an
     `AgentRequestAny` (spec 8.1).
  3. `InboundRequest.namespace` and `claims` with their defaults; the adapters fill them in
     iteration 9 (spec 8.4).
  4. Exports.
- **Verify:** new `tests/test_identity_models.py` (including the principal never reaching the
  agent as context); `test_model`, `test_hitl_chat_service`, `test_thread_pipeline_recording`
  (the suites that exercise the request builder).

### Iteration 2: The principal replaces the acting user

- **Goal:** `Runtime` publishes the principal into the session and records the owner, and
  everything that read the acting-user cache key reads `Session.get_principal()`;
  `ACTING_USER_CACHE_KEY` is gone. No surface sets a principal yet, so every run is anonymous
  and the schedule tools refuse.
- **Files:** `core/util/key_value_cache.py`, `core/base.py`, `core/paused_run.py`,
  `core/runtime.py`, `core/tool.py`, `core/service.py`, `core/chat_service.py`,
  `core/__init__.py`, `core/model.py` (`Principal.is_shared_channel`, the prefix rule's one
  home), `integration/agui/handler.py`, `pipeline/agent_runner.py`, `schedule/tools.py`.
- **Steps:**
  1. `KeyValueCache`: `RESERVED_PREFIX = "ak."`, `_set_reserved`, `_delete_reserved`,
     `_clear_all`; `clear()` keeps reserved entries (spec 3).
  2. `Session.Keys.OWNER`; `get_principal()`, `get_tool_filter()` (always `None` until
     iteration 18), `get_owner()`; `_publish_run`, `_unpublish_run`, `_record_owner`; the two
     private cache-key constants (spec 3).
  3. `PausedRun` gains `subject`, `provider`, `namespace`; `PausedRunState` writes through the
     reserved path and records them from `get_principal()` (spec 2, 3).
  4. `Runtime.run`/`stream`: `acting_user_id` becomes `principal=`; publish before the pre-hooks,
     record the owner (prefix rule), the actor chain (the agent subject is `agent.name` until the
     descriptor lands in 13), the eighth resume check (`PermissionError`);
     `ACTING_USER_CACHE_KEY` deleted with its export. The gate steps are left as no-ops until
     iteration 18 (spec 3).
  5. `ToolContext.principal` and `access_level` (reads `get_tool_filter`, so `None` for now)
     (spec 3).
  6. `AgentService.run_multi`/`stream_multi`, `AgentHandler.run_*` and `ChatService.execute*`
     pass `req.principal`; the AG-UI handler and `AgentRunner._process_agui` call sites renamed
     (spec 8.1, 8.3, 8.5).
  7. `ScheduleToolUtil.acting_user()` returns the principal's subject; `_NO_IDENTITY` reads
     "scheduling requires an authenticated principal" (spec 8.11).
- **Verify:** `grep -rn "acting_user_id\|ACTING_USER_CACHE_KEY" ak-py/src/agentkernel` returns
  nothing; new `tests/test_session_identity.py` and `tests/test_runtime_principal.py`
  (publication, owner, resume check; the gate cases come in 18); changed `test_runtime`,
  `test_runtime_resume` and `test_paused_run_state` (tests that seed `ak.paused_runs` write it
  through `_set_reserved`; the "clearing discards decisions" pin flips), `test_chat_service_core`,
  `test_chat_service_streaming`, `test_schedule_tools`, `test_agui_queue_handler`,
  `test_agui_handler` (the authoriser-to-acting-user test is removed; iteration 7 adds the
  principal one), `test_agui_resume`, `test_hitl_*`, `test_tool`, `test_session`, `test_key_value_cache` (the `clear()` log line).

### Iteration 3: `user_id` leaves the request models

- **Goal:** no request body carries a user id, a body or envelope with one is refused, and
  threads and schedules key on `req.principal`.
- **Files:** `core/model.py`, `core/chat_service.py`, `schedule/model.py`, `schedule/manager.py`,
  `schedule/tools.py`, `integration/thread/recorder.py`, `integration/thread/thread_chat.py`
  (its own multipart form field, the 403 mapping and the chat routes), the chat routes in
  `api/handler.py` and `pipeline/request_handler.py`, the three queue runners whose routing
  attribute falls back to the body (`pipeline/agent_runner.py`,
  `deployment/aws/{containerized,serverless}/akagentrunner.py`), `integration/agui/handler.py`,
  and the six constructor sites that pass `user_id=` today: `api/handler.py:130`,
  `pipeline/request_handler.py:508`, `thread_chat.py:98`, `integration/adapter/producer.py:79`,
  `integration/agui/queue_handler.py:143`, `deployment/aws/serverless/core/router/rest_lambda.py:151`.
  (`pipeline/realtime_pool.py:545` is the dispatch parameter, not a body field; it moves in 9.)
- **Steps:**
  1. Remove `BaseChatRequest.user_id`; `from_payload` drops the envelope propagation, raises
     `ValueError` on a `user_id` key and drops a `principal` key from a client payload (spec 2).
  2. `ChatService.reject_unprocessable` (the public name of `_reject_ambiguous`) rejects the
     `user_id` extra ahead of scheduling and trigger recording, and the thread and pipeline
     edges run it before their first write or enqueue; `known_fields` drops `user_id`;
     `_record_trigger` forwards `req.principal`; the presentation wrappers map `PermissionError`
     to 403 (pulled forward from 19, so a schedule block without a principal is a 403 and not a
     500 in the meantime) (spec 8.1).
  3. `ScheduledTask.principal`; `ScheduleManager.create(principal, ...)` with the anonymous
     `PermissionError`, storing the owner without the creating run's actor or credential handle;
     `create_from_request`; `_build_trigger_body` carrying `principal`;
     `record_trigger(task_id, principal, ...)` and `_owns_occurrence` comparing the frozen owner's
     namespace and subject; `update` refusing a task created before principal ownership; the
     `create_schedule` tool passes the principal object (spec 8.11). The `error=` keyword and the
     store's `last_error` come with the fire-time skip in iteration 19.
  4. `ThreadRecorder.pre_run` reads `req.principal` and raises `PermissionError` when it is
     missing or anonymous; the thread handlers map it to 403 (pulled forward from 10, so an
     anonymous thread request is a 403 and not a 500 in the meantime) (spec 8.10).
  5. The chat routes that bind a client body (`AgentRESTRequestHandler.run`, pipeline
     `RequestHandler.run_chat` and `RestHandler.enqueue_and_wait`, the thread handlers' overrides,
     and the multipart routes for symmetry) take `request: Request` and assign `body.principal`
     from `request.state` (`None` until the identity dependency of 6 sets it), so a principal a
     client sends is overwritten (spec 8.2, 8.3); the REST route maps `PermissionError` to 403
     on its SSE branch; the Lambda REST router maps `ValueError` to 400; the AG-UI `_events`
     loses its unused `user_id` parameter.
  6. The six constructor sites stop passing `user_id=` (the multipart form fields go with it,
     and a form still carrying one is a 400 through `_reject_user_id_form`); each gets its
     principal in phase B. `Runtime` records a shared-channel principal as the owner too (Q17
     refined); `Session.clear()` keeps the run publication. The three queue runners' body fallback for the routing
     attribute reads `Principal.subject_of(body.principal)` (spec 8.3).
- **Verify:** `grep -rn "\.user_id\|\"user_id\"" ak-py/src/agentkernel` shows only
  `InboundRequest.user_id`, `Thread.user_id`, `ScheduledTask.user_id`, the WebSocket routing
  attribute (`ATTR_USER_ID`, the connection stores, `response_handler.py`) and ADK's native
  session `user_id`; changed `test_chat_service_core` (refusal of `user_id`),
  `test_serverless_request_handle` (`from_payload` refusals), `test_api_multipart_fields`,
  `test_chat_service_schedule`, `test_schedule_manager`, `test_schedule_tools`,
  `test_schedule_router`, `test_schedule_model`, `test_thread_integration` and
  `test_thread_pipeline_recording` (a test-side handler subclass sets `request.state.principal`
  the way the identity dependency will in 6; a principal in the body is a 403 like an anonymous
  request), `test_pipeline_request_handler` and `test_api_multipart_fields` (a client-sent
  principal never reaches the queue or the service), `test_integration_producer`,
  `test_agui_queue_handler`, the three `*_agent_runner_schedule` suites, `test_ws_lambda_stream`,
  `test_serverless_status_propagation` (a `user_id` body is a 400 on the Lambda REST router),
  `test_pipeline_ws` (a frame carrying `user_id` is a `FAILED` frame; one carrying `principal` is
  enqueued without it).

## Phase B: Providers and surfaces (iterations 4 to 12)

### Iteration 4: Identity config, provider contract, static provider and role mapper

- **Goal:** an `identity.provider` block parses, a `static` provider authenticates a token and
  the role mapper produces `Principal.roles`; no surface calls it yet.
- **Files:** `core/config.py`, `identity/__init__.py`, `identity/errors.py`,
  `identity/provider/base.py`, `identity/provider/factory.py`, `identity/provider/static.py`,
  `identity/provider/roles.py`, `identity/provider/testing.py`.
- **Steps:**
  1. `_ClaimPathsConfig`, the provider blocks, `_IdentityProviderConfig`, `_RoleMapperConfig`,
     `_IdentityConfig` with its validator; `AKConfig.identity: Optional = None` (spec Config
     changes). The `credentials` block comes in iteration 24.
  2. `identity/errors.py`; `RequestContext`; the `IdentityProvider` ABC (`authenticate`,
     `security_scheme()`, `close()`); `IdentityProviderFactory` with the `static` branch and the
     dotted-path branch; the OIDC-family names arrive with their classes in 5 (spec 4).
  3. `StaticIdentityProvider`: secret-resolved credentials, `hmac.compare_digest`, namespace
     `"static"` (spec 4).
  4. `RoleMapper`, `MappingRoleMapper` (`pass_through`), `RoleMapperFactory`,
     `MappedIdentityProvider` (spec 4).
  5. `IdentityProviderContract` and `RoleMapperContract`.
- **Verify:** new `tests/test_identity_providers.py` (static contract, mapper contract, factory
  built-in, dotted and unknown); `test_config` identity cases; the `FakeCfg` stubs gain
  `identity = None`.

### Iteration 5: OIDC provider family

- **Goal:** bearer JWTs from any OIDC issuer, Cognito, Entra and Firebase authenticate.
- **Files:** `identity/provider/oidc.py`, `identity/provider/cognito.py`,
  `identity/provider/entra.py`, `identity/provider/firebase.py`, `identity/provider/factory.py`,
  `ak-py/pyproject.toml`.
- **Steps:**
  1. The `auth` extra: PyJWT, `cryptography>=42.0`, `httpx>=0.27.0`; `require_extra` around the
     imports in the factory branches (spec Config changes).
  2. `JWKSCache` over `PyJWKClient` in `asyncio.to_thread`, one refresh on an unknown `kid` with
     a 30 s cooldown, discovery through httpx (spec 4).
  3. `OIDCIdentityProvider` (namespace = `iss`, claim paths read as one claim name first and then
     dotted, a trailing slash on the issuer tolerated either way, so Auth0 is an `oidc`
     configuration) and the Cognito, Entra and Firebase subclasses (Firebase groups claim path
     defaults to `roles`) (spec 4).
  4. The four factory branches.
- **Verify:** `IdentityProviderContract` subclasses for the four providers over RSA and EC keys
  and a local JWKS on `httpx.MockTransport`; discovery cached; unknown `kid` refreshed once;
  cooldown; the missing-extra error.

### Iteration 6: REST and the pipeline chat route

- **Goal:** a request on the REST surface or the pipeline chat route carries the authenticated
  principal.
- **Files:** `identity/provider/request.py`, `api/http.py`, `api/handler.py`,
  `pipeline/request_handler.py`.
- **Steps:**
  1. `RequestAuthenticator`: `from_config`, `authenticate_bearer`, `authenticate_token`,
     `dependency()`, the `current()` contextvar, `release()` (a no-op until iteration 25)
     (spec 4).
  2. `RESTAPI._get_router_dependencies` appends the identity dependency after the legacy
     validators; `add_auth_handlers` and `_auth_token_validators` stay until 11, which removes
     them with `agentkernel.auth` and their last callers (`ecs_io_handler.py:78`,
     `gcp/akauthorizer.py:29`); the `request.state.principal` read that
     `AgentRESTRequestHandler.run`/`run_multipart` have carried since 3 now finds the dependency's
     principal (spec 8.2). `AuthorisedRESTRequestHandler` changes in 10 together with the thread
     and schedule routers that subclass it.
  3. Likewise pipeline `RequestHandler.run_chat` and `RestHandler.enqueue_and_wait`;
     `RestHandler.request` requires the caller's principal; the precheck slot before
     `_enqueue_request` is filled in 19 (spec 8.3).
- **Verify:** the authenticator cases in `test_identity_providers` (bearer parsing, anonymous
  rules, 401 details, contextvar); changed `test_api_http` (dependency assertions replace the
  validator ones), `test_api_multipart_fields`, `test_pipeline_request_handler`.

### Iteration 7: WebSocket, AG-UI and CLI

- **Goal:** the WebSocket gateway keys connections by the authenticated subject, AG-UI carries
  the principal, and the CLI sends a token.
- **Files:** `pipeline/ws/handler.py`, `pipeline/ws/gateway.py`, `pipeline/io_handler.py`,
  `integration/agui/handler.py`, `integration/agui/queue_handler.py`, `cli/cli.py`.
- **Steps:**
  1. `PipelineWebSocketHandler` loses `auth_validator`, authenticates through
     `authenticate_token`, registers by `principal.subject`, sets `body.principal`, refuses a
     `user_id` frame with the `FAILED` frame, passes `{"message", "principal"}` to custom routes,
     acks with `subject` (spec 8.3).
  2. `WebSocketGateway.run()` takes no arguments; `IOHandler.run()` loses `auth_validator`;
     both require the identity block with the spec's `AKConfigError` messages (spec 8.3).
  3. AG-UI handlers lose `authoriser`/`auth_validator`, require the identity block at
     construction and carry the principal; until 10 moves `AuthorisedRESTRequestHandler` to the
     provider, `AGUIRequestHandler._resolve_principal(request)` reads the dependency's
     `request.state.principal` and answers 401 for the anonymous principal (spec 8.5).
  4. CLI `--token` / `AK_CLI_TOKEN` (spec 8.8).
- **Verify:** changed `test_pipeline_ws`, `test_pipeline_io_handler`, `test_agui_handler`,
  `test_agui_queue_handler`, `test_agui_resume`; new `tests/test_cli_token.py`.

### Iteration 8: MCP and A2A

- **Goal:** both protocol surfaces authenticate and put the principal on the executor's body.
- **Files:** `api/mcp/akmcp.py`, `api/mcp/auth.py` (new: `AKAccessToken`, `AKTokenVerifier`,
  `AKMCPAuthProvider`), `api/a2a/a2a.py`, `api/a2a/handler.py` (`AKCallContextBuilder`).
- **Steps:**
  1. MCP: `AKTokenVerifier`, `AKAccessToken` (`principal`), `AKMCPAuthProvider.from_config`
     (`RemoteAuthProvider` for OIDC), `auth=` on `FastMCP`, the principal from
     `get_access_token()` on the executor's body (spec 8.6). The per-tool `AuthCheck` comes in
     20.
  2. A2A: `AKCallContextBuilder` on `create_rest_routes`, the principal on the executor's body
     (spec 8.7). The card's security schemes come in 14.
- **Verify:** new `tests/test_api_mcp_auth.py` and `tests/test_api_a2a_auth.py`; changed
  `test_api_mcp`, `test_api_a2a`, `test_cross_surface_parity`,
  `test_protocol_pipeline_roundtrip`.

### Iteration 9: Messaging and realtime principals

- **Goal:** every messaging delivery and LiveKit participant runs as a `messaging:` or
  `realtime:` principal with the platform's namespace.
- **Files:** `integration/adapter/producer.py`, the seven `integration/<platform>/adapter.py`,
  `integration/livekit/adapter.py`, `integration/adapter/base.py` (`StatefulEdgeAdapter._enqueue`),
  `pipeline/realtime_pool.py`.
- **Steps:**
  1. `IntegrationProducer.enqueue` builds the principal from the adapter's `Source` prefix, or
     anonymous when the delivery has no sender (spec 8.4, design refinement 3).
  2. Each adapter fills `namespace` (Slack team id, Teams tenant, Gmail inbox, WhatsApp
     `phone_number_id`, Messenger and Instagram page id, Telegram bot id); Gmail records the
     `Authentication-Results` claim (spec 8.4).
  3. LiveKit passes the participant identity and the API key id as namespace (spec 8.4).
  4. `RealtimeConnectionPool.dispatch` takes `body.principal` and the connection stores it;
     `_execute_tool_and_reply` publishes it around `execute_tool` (the tool check comes in 23)
     (spec 8.4).
- **Verify:** new `tests/test_principal_messaging.py`; changed `test_integration_producer`, the
  per-platform adapter suites (namespace), `test_integration_adapter_contract`, the realtime
  pool tests.

### Iteration 10: Threads, schedules and the sandbox resolver

- **Goal:** the thread and schedule routes authenticate through the principal and enforce
  ownership on it; the default sandbox resolver reads the run principal.
- **Files:** `api/handler.py`, `integration/thread/manager.py`,
  `integration/thread/thread_chat.py`, `schedule/handler.py`, `sandbox/principal.py`.
- **Steps:**
  1. `AuthorisedRESTRequestHandler` loses `authoriser`, requires the identity block and
     resolves `_resolve_user -> Principal` (absorbing `AGUIRequestHandler._resolve_principal`
     from 7); `ThreadRESTRequestHandler` and `ScheduleRESTRequestHandler` follow, keeping their
     403 and 404 rules on the principal's subject (spec 8.2, 8.10, 8.11).
  2. `ConversationThreadManager.get_or_create_thread` raises `PermissionError` on a foreign
     thread (spec 8.10).
  3. `AgentThreadRequestHandler` and `ThreadRequestHandler` lose `authoriser`, require the
     identity block and map an anonymous principal to 401 (the 403 mapping landed in 3) (spec 8.10).
  4. The schedule handler passes `principal.subject` to `get_task`, `list_tasks`, `update`,
     `cancel` (spec 8.11).
  5. `AgentPrincipalResolver.resolve` returns the user-mode principal for a non-anonymous run
     (spec 8.12).
- **Verify:** changed `test_thread_pipeline_recording`, `test_thread_integration`,
  `test_thread_router`, `test_schedule_router`, the three `*_agent_runner_schedule` suites; new
  `tests/test_schedule_principal.py` (ownership; the fire-time skip is added in 19); the sandbox
  resolver cases.

### Iteration 11: Deployment adapters; delete `agentkernel.auth`

- **Goal:** the ECS, Lambda, GCP and Azure entry points authenticate through the configured
  provider; the last importers of the auth package have moved and the package is deleted.
- **Files:** `deployment/aws/containerized/ecs_io_handler.py`,
  `deployment/aws/containerized/core/api/websocket_api.py`,
  `deployment/aws/core/websocket_service.py`,
  `deployment/aws/serverless/core/router/ws_lambda.py`,
  `deployment/aws/serverless/core/router/rest_lambda.py`,
  `deployment/aws/serverless/akauthorizer.py`, `deployment/aws/serverless/akwsconnectionhandler.py`,
  `deployment/gcp/akauthorizer.py` (delete), `deployment/azure/akfunction.py`, `auth/` (delete),
  `auth.py` (delete).
- **Steps:**
  1. ECS: `ECSIOHandler.run(handlers=None)`; `set_auth_handler` and `_ws_auth_validator` go;
     `$connect` authenticates through `authenticate_token`; the AWS `WebSocketConnectionStore`
     gains the `principal` attribute and `get_principal`; `_handle_chat` sets `body.principal`
     from it (spec 8.9).
  2. Lambda: `ConnectionRoutesHandler` and `WebsocketConnectionHandler` the same way;
     `APIGatewayAuthorizer(bypass=None)` returns `principalId` and the `principal` context
     string; the REST router rebuilds the principal from the authorizer context (spec 8.9).
  3. `GCPAuthorizer` deleted; `AzureFunctions.handler` runs `authenticate_bearer` and answers
     401 (spec 8.9).
  4. Delete the `auth` package and the `auth.py` shadow module, and with them
     `RESTAPI.add_auth_handlers` and `_auth_token_validators` (kept since 6 for the adapters
     above).
- **Verify:** new `tests/test_deployment_identity.py`; changed `test_ecs_*`,
  `test_ws_lambda_stream`, `test_akauthorizer`, `test_authorizer_webhook_bypass`; deleted
  `test_auth_handler.py` and `test_authoriser_shared.py`;
  `python -c "import agentkernel.auth"` fails with `ModuleNotFoundError`;
  `grep -rn "AuthValidator\|Authoriser\b" ak-py/src` returns nothing.

### Iteration 12: Examples

- **Goal:** every example runs on `identity.provider`; this is the omnichannel branch point for
  live principals.
- **Files:** the examples listed in the spec's "Documentation, skills and examples" section
  except the three configs naming `mcp.agents`/`a2a.agents`, which move in 16.
- **Steps:**
  1. `identity.provider.static` blocks with credential values through the `secret` capability.
  2. Bodies, tests, READMEs and the a2ui frontend (`App.tsx`) and the k8s `ws_client.py` without
     `user_id`; the `auth`-based examples (`crewai-auth`, `openai-auth`, the WebSocket
     connection handlers, `slack-openai`) on the provider.
  3. `examples/sandbox/identity` keeps its resolver and gains the note.
  4. Auth0 appears as a supported provider (decided 2026-11-10): one of the `auth`-based
     examples carries an Auth0 configuration in its README beside the static one, as an
     `identity.provider` block of `type: oidc` with the tenant issuer (trailing slash included),
     the API identifier as `audience` and the namespaced roles claim as `claims.groups`, with the
     token acquired through the tenant's `/oauth/token` endpoint in its `app_test.py` notes.
- **Verify:** `examples/api/agui`, `examples/api/thread-openai`,
  `examples/api/multimodal/thread-openai`, `examples/api/schedule-openai`,
  `examples/api/a2ui-openai` and `examples/aws-containerized/openai-websocket` `app_test.py`
  pass against a `static` provider; `grep -rn "user_id\|AuthValidator" examples` returns only
  `examples/sandbox/identity` and the Gmail API's `userId="me"`.

## Phase C: Agent entity and registry (iterations 13 to 16)

### Iteration 13: Registry contract and in-memory backend

- **Goal:** `Runtime` keeps its agents in an `AgentRegistry`; every agent has a descriptor;
  behaviour is unchanged.
- **Files:** `core/registry.py` (new), `core/runtime.py`, `core/base.py`, `core/module.py`,
  `core/__init__.py`.
- **Steps:**
  1. `AgentRegistry` ABC, `InMemoryAgentRegistry`, `AgentRegistryFactory` (in-memory branch
     only, no config read), `AgentDescriptorPage`, `AgentRegistrationError` (spec 6).
  2. `Runtime` delegates `register`, `deregister` and `agents()` (spec 6).
  3. `Agent.descriptor`; the default `get_tool_names()` and `ungated_tool_names()` (`[]`);
     `Module.describe` with the descriptor sources and later-wins (spec 6, 9).
- **Verify:** new `tests/test_agent_registry.py` (in-memory cases); changed `test_runtime`,
  `test_module`.

### Iteration 14: Adapter descriptors and A2A cards

- **Goal:** each adapter reports its tool names and its card is built from the descriptor with
  the provider's security scheme.
- **Files:** the eight `framework/<name>/<name>.py`, `api/a2a/a2a.py`.
- **Steps:**
  1. `get_tool_names()` per adapter from the spec 9 table (the LangGraph `ToolNode` walk
     replaces the `node_data.tools` read that always produced empty skills) (spec 9).
  2. `A2ACardBuilder.build(descriptor)` with security schemes from `security_scheme()`;
     `get_a2a_card` goes through it (spec 6, design refinement 5).
- **Verify:** the descriptor cases in the eight `test_tool_<adapter>` suites; the card
  assertions in `test_api_a2a_surface` and `test_api_a2a_auth`.

### Iteration 15: Registry config and store backends

- **Goal:** the registry is pluggable and store-backed; an instance reads descriptors another
  instance registered.
- **Files:** `core/config.py`, `core/registry.py` (the factory reads the block and applies the
  overlay), `identity/registry/redis_like.py`, `identity/registry/redis.py`,
  `identity/registry/valkey.py`, `identity/registry/dynamodb.py`, `identity/registry/testing.py`.
- **Steps:**
  1. `_RegistryConfig`, the defaults-only `_Registry*Config` subclasses,
     `_RegistryAgentOverlayConfig`; `AKConfig.registry: Optional = None` (spec Config changes).
  2. `_RedisLikeAgentRegistry`, the Redis, Valkey and DynamoDB backends,
     `AgentRegistryContract` (spec 6).
  3. The factory's store branches, the dotted-path branch and the overlay.
- **Verify:** `test_agent_registry` (all backends over fake drivers, factory, overlay,
  cross-instance read); `test_config` registry cases; the `FakeCfg` stubs gain `registry = None`.

### Iteration 16: Catalog and exposure

- **Goal:** the catalog route serves descriptors, the protocol surfaces expose agents from
  `descriptor.exposed_on`, and the three removed config lists fail loudly.
- **Files:** `core/config.py` (the `mode="before"` validators on `_A2AConfig`, `_MCPConfig`,
  `_AGUIConfig`), `core/service.py`, `api/handler.py`, `api/mcp/akmcp.py`, `api/a2a/a2a.py`,
  `api/a2a/handler.py`, `integration/agui/handler.py`; the example configs
  `aws-containerized/mcp/multi` and `k8s/openai-queue-mode/config.{kafka,nats}.yaml`.
- **Steps:**
  1. `ensure_agent_available` resolves through the registry (`LookupError` for an unknown
     agent) (spec 6).
  2. `GET /api/v1/agents?cursor=&limit=&tags=` (spec 6); filtering by caller is added in 19.
  3. MCP tool registration, A2A cards and AG-UI exposure read `exposed_on`; the removed-list
     validators; the example configs move to `registry.agents.<id>.surfaces` (spec 8.5 to 8.7,
     Config changes).
- **Verify:** new `tests/test_api_catalog.py`; `test_config` cases for the removed lists;
  changed `test_api_mcp`, `test_api_a2a_surface`, `test_agui_handler`.

## Phase D: Authorization (iterations 17 to 20)

### Iteration 17: Authorizer

- **Goal:** an `authorization` block parses and the static authorizer answers every decision;
  nothing consults it yet.
- **Files:** `core/config.py`, `identity/authz/base.py`, `identity/authz/factory.py`,
  `identity/authz/static.py`, `identity/authz/testing.py`.
- **Steps:**
  1. `_AuthorizationConfig`, `_GrantConfig`, `_ToolPolicyConfig`;
     `AKConfig.authorization: Optional = None` (spec Config changes).
  2. `Decision`, `AuthorizerCapabilities`, the `Authorizer` ABC (spec 7).
  3. `StaticAuthorizer` with `GrantTable` and `SubjectMatcher` (the six subject forms,
     `tag:<name>`, `tiers`/`allow`/`deny`), the reason strings (spec 7).
  4. `AuthorizerFactory` with the reserved engine names raising `AKConfigError`;
     `AuthorizerContract` (spec 7).
- **Verify:** new `tests/test_authorizer_static.py`; `test_config` authorization cases; the
  `FakeCfg` stubs gain `authorization = None`.

### Iteration 18: Access gate and Runtime enforcement

- **Goal:** a configured `authorization` block gates every run: agent level, session ownership,
  resume identity and the published tool filter; `ToolContext.access_level` is live.
- **Files:** `identity/authz/gate.py`, `core/runtime.py`, `core/module.py`, `core/service.py`.
- **Steps:**
  1. `AccessGate` with its sync and async twins: `authorize_agent` (`PermissionError`,
     `LookupError`), `visible`, `visible_agents`, `tool_filter`, `authorize_session`,
     `validate_configuration` (the Q12 check reads `ungated_tool_names`, empty until phase E)
     (spec 7).
  2. `Runtime` gate sequence before the pre-hooks, the tool filter publication,
     `authorize_session` on the recorded owner, the resume identity check against the gate
     (spec 3).
  3. `Module.load` calls `validate_configuration`; `ensure_agent_available(name, principal)`
     gains the principal and the gate (spec 6, 7).
  4. The declared tiers on the system tools: sandbox and schedule tools, `write_kb` and
     `update_agui_state` at `WRITE`, the rest at the `READ` default (spec 2).
- **Verify:** new `tests/test_access_gate.py`; the gate cases in `test_runtime_principal`;
  changed `test_module`, `test_schedule_tools`, `test_sandbox_tools`.

### Iteration 19: Service, pipeline and schedule enforcement

- **Goal:** an unauthorized request is a 403 or 404 before anything is enqueued or run, the
  catalog shows only visible agents, and a scheduled task whose owner lost access is skipped
  and recorded.
- **Files:** `core/chat_service.py`, `pipeline/request_handler.py`, `api/handler.py`,
  `schedule/manager.py`, `schedule/store/*`.
- **Steps:**
  1. `ChatService` maps `LookupError` to 404 (the `PermissionError` to 403 branch landed in 3)
     (spec 8.1).
  2. The scheduled-trigger skip: `record_trigger(..., error=)`, the store's `last_error`, the
     403 reply and the warning (spec 8.1, 8.11).
  3. The pipeline precheck before `_enqueue_request` and in `RestHandler.request` (spec 8.3).
  4. The catalog filtered by `visible_agents`; `get_router()` calls `validate_configuration`
     (spec 6, 7).
- **Verify:** 403/404 cases in `test_api_http`; `test_pipeline_request_handler` (the riskiest
  consumer: the precheck on a store-backed registry with no local agents); the fire-time skip
  in `test_schedule_principal`; visibility in `test_api_catalog`.

### Iteration 20: Protocol surface enforcement

- **Goal:** MCP, A2A, AG-UI and the realtime pool enforce agent access for the caller.
- **Files:** `api/mcp/akmcp.py`, `api/a2a/a2a.py`, `api/a2a/handler.py`,
  `integration/agui/handler.py`, `pipeline/realtime_pool.py`.
- **Steps:**
  1. MCP per-tool `AuthCheck` and list filtering (spec 8.6).
  2. A2A `get_cards(principal)` filtering and the 403 (spec 8.7).
  3. AG-UI `/agents` narrowed by `visible_agents` and the 403 (spec 8.5).
  4. `RealtimeConnectionPool.dispatch` runs `ensure_agent_available(body.agent, body.principal)`
     on first connect (spec 8.4).
- **Verify:** list filtering and `AuthCheck` in `test_api_mcp_auth`; card filtering in
  `test_api_a2a_auth`; the 403 in `test_agui_handler`; the realtime pool tests.

## Phase E: Framework tool gates (iterations 21 to 23)

Each adapter gate is one file plus one `tests/test_tool_gates_<adapter>.py`, grouped by
mechanism. Every suite asserts the native call keyword-for-keyword unchanged with no
`authorization` block.

### Iteration 21: `ToolGate`, OpenAI, Pydantic AI, MAF and Claude

- **Goal:** the four adapters with a per-run hook hide denied tools at list time and refuse
  them at call time.
- **Files:** `core/tool.py` (`ToolGate`), `framework/openai/openai.py`,
  `framework/pydanticai/pydanticai.py`, `framework/maf/maf.py`, `framework/claude/claude.py`.
- **Steps:**
  1. `ToolGate.current(session)` and `deny_result(name, filter)` (spec 9).
  2. OpenAI: `is_enabled` as an AND with the AK check and the `ak_tool_gate` input guardrail at
     wrap time (spec 9, design refinement 4).
  3. Pydantic AI: `AKToolGateCapability` per run (`prepare_tools`, `before_tool_execute`)
     (spec 9, design refinement 2).
  4. MAF: `AKToolGateMiddleware` first in the per-run middleware list inside
     `_prepare_session` (spec 9).
  5. Claude: in `_native_options`, a denied `mcp__ak__<name>` leaves `allowed_tools` for
     `disallowed_tools`, and the HITL `PreToolUse` hook answers `deny` with the reason ahead of
     its approval branch (spec 9).
- **Verify:** `test_tool_gates_openai.py`, `test_tool_gates_pydanticai.py`,
  `test_tool_gates_maf.py`, `test_tool_gates_claude.py`.

### Iteration 22: ADK and CrewAI

- **Goal:** the two callback-driven adapters refuse denied tools through their native hook.
- **Files:** `framework/adk/adk.py`, `framework/crewai/crewai.py`.
- **Steps:**
  1. ADK: `before_tool_callback` AK-first on every reachable `LlmAgent`, returning
     `{"error": reason}` (spec 9).
  2. CrewAI: the process-wide `register_before_tool_call_hook` registered on first module load,
     returning `False` for a denied tool (spec 9).
- **Verify:** `test_tool_gates_adk.py`, `test_tool_gates_crewai.py`.

### Iteration 23: LangGraph, smolagents and realtime; Q12 live

- **Goal:** the two wrap-time adapters gate the tools AK binds, report the ones it cannot, and
  refuse to start under `authorization` when any tool is ungated; the realtime pool checks the
  filter before `execute_tool`.
- **Files:** `framework/langgraph/langgraph.py`, `framework/smolagents/smolagents.py`,
  `pipeline/realtime_pool.py`.
- **Steps:**
  1. LangGraph: the bind-time wrapper with `metadata={"ak_gated": True}`;
     `ungated_tool_names` over unmarked `tools_by_name` entries (spec 9).
  2. smolagents: `forward` wrapped at wrap time with `__ak_gated__`; `ungated_tool_names` over
     unmarked tools (spec 9, design refinement 4).
  3. `_execute_tool_and_reply` checks `ToolFilter.allows(name)` before `adapter.execute_tool`
     (spec 8.4, 9).
- **Verify:** `test_tool_gates_langgraph.py`, `test_tool_gates_smolagents.py`, the realtime
  gate cases; the Q12 refusal cases in `test_access_gate`; `test_cross_surface_parity`
  unchanged.

## Phase F: Credentials (iterations 24 to 25)

### Iteration 24: Credential store

- **Goal:** an encrypted `CredentialStore` with four backends exists behind a factory; nothing
  writes to it yet.
- **Files:** `core/config.py`, `identity/credential/store.py`, `identity/credential/in_memory.py`,
  `identity/credential/redis_like.py`, `identity/credential/redis.py`,
  `identity/credential/valkey.py`, `identity/credential/dynamodb.py`,
  `identity/credential/testing.py`.
- **Steps:**
  1. `_CredentialsConfig`, its store models and `_ExchangerConfig`;
     `AKConfig.identity.credentials` (spec Config changes).
  2. `CredentialStore` ABC, `CredentialCipher` (AES-GCM, key through the `secret` capability),
     the four backends, `CredentialStoreFactory`, `CredentialStoreContract` (spec 5).
- **Verify:** the store and cipher cases of new `tests/test_identity_credentials.py` (contract
  over in-memory and the redis-like and DynamoDB backends through fake drivers, cipher round
  trip, TTL).

### Iteration 25: Exchange, broker and retention

- **Goal:** the inbound credential is retained by reference for the run and read through
  `ToolContext.credentials`; `passthrough` is the only exchanger.
- **Files:** `identity/credential/exchange.py`, `identity/credential/broker.py`,
  `identity/provider/request.py`, `core/runtime.py`, `core/tool.py`, `pipeline/agent_runner.py`,
  `deployment/aws/containerized/akagentrunner.py`, `deployment/aws/serverless/akagentrunner.py`.
- **Steps:**
  1. `TokenExchanger`, `IssuedToken`, `PassthroughTokenExchanger`, `TokenExchangerFactory` with
     the reserved names raising; `TokenExchangerContract` (spec 5).
  2. `CredentialBroker` with its cache key (spec 5).
  3. `RequestAuthenticator` mints and stores `credential_ref` with `min(exp, inbound_ttl)`;
     `release` deletes it; `Runtime.run`/`stream` and every runner call `release` in `finally`;
     `ToolContext.credentials` returns the live broker (spec 3, 4, 8.3).
- **Verify:** the remaining `test_identity_credentials` cases (broker, no token in a queue body
  or log line, deletion on both paths, reserved exchanger names).

## Phase G: Tests, docs and skills (iterations 26 to 28)

### Iteration 26: Test walk

- **Goal:** the spec's Testing section is fully covered and the whole suite and lint are clean.
- **Files:** any test file the walk finds short.
- **Steps:** walk the spec's Testing section file by file; confirm every new file exists, every
  listed patch target resolves and every deleted file is gone; run the full suite and
  `make lint-check-all`.
- **Verify:** `cd ak-py && uv run pytest` green; `make lint-check-all` clean.

### Iteration 27: Docs site and READMEs

- **Goal:** the docs site and the package READMEs describe the implementation.
- **Files:** `docs/docs/advanced/identity-and-access.md` (new) and the sixteen existing pages
  listed in the spec's "Documentation, skills and examples" section; `ak-py/README.md`,
  `README.md`; the `ak-deployment` READMEs and chart comments listed there.
- **Steps:**
  1. Run `ak-dev-sync-docs-from-branch` over the branch; write the new advanced page from spec
     sections 2 to 8 and the design's worked example, including the operator note that scheduled
     tasks and threads from before the change are recreated or migrated outside the system. Its
     supported-providers table lists Auth0 as a supported provider served by the `oidc` type,
     with the configuration block spelled out (tenant issuer, API identifier audience, namespaced
     roles claim), beside Cognito, Entra, Firebase, the static provider and any other OIDC issuer
     (decided 2026-11-10); `configuration.md` says the same where it lists the provider types.
  2. Confirm the Terraform resources need no change (the connections table keeps its `user_id`
     hash key; the authorizer Lambda keeps its `handler_path` contract).
- **Verify:** `grep -rn "AuthValidator\|Authoriser\|acting_user_id\|mcp.agents\|a2a.agents\|
  agui.agents\|userId" docs/docs ak-py/README.md README.md ak-deployment` returns only the
  frozen `docs/versioned_docs/` snapshots and the Gmail API's `userId="me"`; the docs site
  builds (`NODE_ENV=production`, 6 GB heap).

### Iteration 28: Skills

- **Goal:** the dev and user skills match the implementation.
- **Files:** `.agents/skills/ak-dev-architecture/SKILL.md`,
  `.agents/skills/ak-dev-testing-conventions/SKILL.md`,
  `.agents/skills/ak-dev-new-messaging-integration/SKILL.md`, new
  `.agents/skills/ak-dev-new-identity-provider/SKILL.md` and
  `.agents/skills/ak-dev-new-authorizer/SKILL.md`; `ak-py/src/agentkernel/skills/ak-cloud-deploy/`,
  `ak-add-capabilities/`, `ak-add-integration/` with their `evals/evals.json`.
- **Steps:**
  1. Run `ak-dev-sync-skills-from-branch` over the branch; write the two new dev skills from
     spec sections 4 and 7 and their contract suites.
  2. Verify no update is needed for `ak-dev-write-spec`, `ak-dev-review-pr`, the other
     `ak-dev-new-*` skills, `ak-build`, `ak-init` and `ak-test`.
  3. Wherever `ak-add-capabilities` and `ak-cloud-deploy` list the identity providers, Auth0 is
     named as a supported provider with its `oidc` block (decided 2026-11-10), and the
     `ak-dev-new-identity-provider` skill says a new OIDC issuer is a configuration before it is a
     subclass.
- **Verify:** the iteration 27 grep extended to `.agents/skills` and
  `ak-py/src/agentkernel/skills` returns nothing new; the `ak-dev-testing-conventions` table
  names every file the spec's Testing section adds, changes or deletes.
