# #603: Identity layer, RBAC and agent registry: Implementation Plan

Builds `spec.md` in nine iterations, each leaving the branch green under `cd ak-py && uv run
pytest`. The order is set by two dependencies: nothing above the identity fix is worth building on
a forgeable subject, and the omnichannel work (#243) needs the identity interfaces frozen early and
live principals on every surface soon after. Iteration 1 freezes the interfaces; iteration 3 is the
point after which every surface carries a real `Principal`.

## Parallel work: omnichannel

Omnichannel (#243, "Omnichannel: Functional Requirements") consumes identity and nothing else in
this change. Two branch points:

- **After iteration 1** (interfaces frozen) omnichannel can start its models, mapping store and
  tools against: `Principal` (`subject`, `provider`, `namespace`, `claims`), the `provider` prefix
  convention (`messaging:<platform>`, `realtime:<gateway>`, anything else is the shared direct
  channel), `BaseChatRequest.principal` as the body field every queue message carries,
  `InboundRequest.namespace` and `claims`, `Session.get_principal()` and `ToolContext.principal`,
  `SessionOwner`, and `ScheduledTask.principal`. These do not change in later iterations.
- **After iteration 3** (every surface establishes the principal) omnichannel can run end to end:
  its identity-sessions recording, link operations and fact tools see live principals on REST,
  AG-UI, WebSocket and every messaging integration.

Iterations 4 to 7 (registry, authorization, tool gates, credentials) touch nothing omnichannel
reads. The one shared file after iteration 3 is `core/tool.py` (`ToolContext.access_level` and
`credentials` land there in 6 and 7, additive).

## Iteration 1: Identity contract

- **Goal:** the models, accessors and publication every later iteration and omnichannel build on,
  with `user_id` and the acting-user seam gone; every surface still works and acts as the
  anonymous principal.
- **Files:** `core/model.py`, `core/registry.py` (new), `core/base.py`, `core/tool.py`,
  `core/util/key_value_cache.py`, `core/paused_run.py`, `core/runtime.py`, `core/service.py`,
  `core/chat_service.py`, `core/module.py`, `core/__init__.py`, `integration/adapter/base.py`,
  `integration/agui/handler.py`, `pipeline/agent_runner.py`, `schedule/tools.py`,
  `schedule/manager.py`, `schedule/model.py`, `integration/thread/recorder.py`.
- **Steps:**
  1. Add `AccessLevel`, `Principal`, `SessionOwner`, `ToolFilter`, `AgentSkillDescriptor`,
     `AgentIdentitySpec`, `AgentDescriptor`; `SystemTool.tier`; `BaseChatRequest.principal`;
     remove `user_id` and the `from_payload` propagation (spec 2).
  2. `core/registry.py`: `AgentRegistry`, `InMemoryAgentRegistry`, `AgentRegistryFactory`
     (in-memory branch only, no config read yet), `AgentDescriptorPage`,
     `AgentRegistrationError`; `Runtime` delegates `register`/`deregister`/`agents()` (spec 6).
  3. `KeyValueCache` reserved prefix and `_clear_all`; `Session.Keys.OWNER`, the three accessors,
     `_publish_run`/`_unpublish_run`/`_record_owner`; `PausedRunState` writes through the
     reserved path and `PausedRun` gains subject/provider/namespace (spec 3).
  4. `Runtime.run`/`stream` take `principal=`, publish, record the owner (prefix rule), actor
     chain, the eighth resume check; gate calls are left as a `None` gate (spec 3).
  5. `ToolContext.principal` and `access_level` (reads `get_tool_filter`, `None` for now);
     `Agent.descriptor`, `get_tool_names()` and `ungated_tool_names()` defaults;
     `Module.describe` (spec 6).
  6. `AgentService`, `AgentHandler`, `ChatService`: the `principal=` rename, `req.principal`
     hand-off, `_validate` rejection of `user_id`, `known_fields` swap; AG-UI handler and
     `AgentRunner` renamed call sites; delete `ACTING_USER_CACHE_KEY` (spec 8.1, 8.3).
  7. `InboundRequest.namespace`/`claims`; `ScheduledTask.principal`, `ScheduleManager.create(
     principal)`, the trigger body `principal`, `record_trigger(principal, error=)`, schedule
     tools reading `Session.get_principal()`; `ThreadRecorder.pre_run` reading the principal
     (spec 8.4, 8.10, 8.11). No surface sets a principal yet, so threads and schedules refuse
     anonymous callers from here on.
- **Verify:** `grep -rn "acting_user_id\|ACTING_USER_CACHE_KEY\|\.user_id" ak-py/src/agentkernel`
  shows only `InboundRequest.user_id`, `Thread.user_id` and `ScheduledTask.user_id`; new
  `tests/test_identity_models.py`, `tests/test_session_identity.py`,
  `tests/test_runtime_principal.py`, `tests/test_agent_registry.py` (in-memory cases); the changed
  suites in spec Testing for `core/` (`test_chat_service_*`, `test_schedule_tools`,
  `test_thread_integration`, `test_serverless_request_handle`, `test_module`, `test_runtime`).

## Iteration 2: Providers and the direct surfaces

- **Goal:** `identity.provider` configured once authenticates REST, the pipeline chat route, the
  WebSocket surfaces, AG-UI and the CLI; `agentkernel.auth` is gone.
- **Files:** `identity/__init__.py`, `identity/errors.py`, `identity/provider/*` (new),
  `core/config.py`, `api/http.py`, `api/handler.py`, `pipeline/request_handler.py`,
  `pipeline/ws/handler.py`, `pipeline/ws/gateway.py`, `pipeline/io_handler.py`,
  `integration/agui/handler.py`, `integration/agui/queue_handler.py`, `cli/cli.py`,
  `ak-py/pyproject.toml`; delete `auth/` and `auth.py`.
- **Steps:**
  1. `_IdentityConfig` and its provider, claim-path and static models with the validator;
     `AKConfig.identity`; the `auth` extra gains `cryptography` and `httpx` (spec Config changes).
  2. `IdentityProvider`, `RequestContext`, `IdentityProviderFactory`, `OIDCIdentityProvider` with
     `JWKSCache`, the Cognito, Entra and Firebase subclasses, `StaticIdentityProvider`,
     `RoleMapper`, `MappingRoleMapper`, `RoleMapperFactory`, `MappedIdentityProvider`, the two
     contracts (spec 4). `credential_ref` minting stays a no-op until iteration 7.
  3. `RequestAuthenticator` with the FastAPI dependency and the contextvar; `RESTAPI`
     dependencies; `AgentRESTRequestHandler.run`/`run_multipart` assign `body.principal`;
     `AuthorisedRESTRequestHandler` identity requirement and `_resolve_user -> Principal`
     (spec 8.2).
  4. Pipeline `RequestHandler`/`RestHandler` assign the principal and precheck;
     `PipelineWebSocketHandler`, `WebSocketGateway.run()`, `IOHandler.run()` lose
     `auth_validator`, key by subject, require the identity block (spec 8.3).
  5. AG-UI handlers lose `authoriser`/`auth_validator`, carry the principal (spec 8.5); CLI
     `--token` / `AK_CLI_TOKEN` (spec 8.8).
  6. Delete the `auth` package and the `auth.py` shadow module; delete
     `tests/test_auth_handler.py` and `tests/test_authoriser_shared.py`.
- **Verify:** `tests/test_identity_providers.py` (contracts over the local JWKS fixture, static,
  factory, authenticator); the changed `test_api_http`, `test_pipeline_ws`,
  `test_pipeline_io_handler`, `test_agui_*`, `test_thread_router`, `test_schedule_router`,
  `test_api_multipart_fields`, new `test_cli_token.py`; `python -c "import agentkernel.auth"`
  fails with `ModuleNotFoundError`.

## Iteration 3: Protocol surfaces, edges and deployments

- **Goal:** MCP, A2A, the seven messaging integrations, LiveKit, HITL resume, the AWS, GCP and
  Azure adapters and the sandbox resolver all carry the principal; the examples run on
  `identity.provider`. This is the omnichannel branch point for live principals.
- **Files:** `api/mcp/akmcp.py`, `api/a2a/a2a.py`, `api/a2a/handler.py`,
  `integration/adapter/producer.py`, `integration/adapter/base.py`, the seven
  `integration/<platform>/adapter.py`, `integration/livekit/adapter.py`,
  `pipeline/realtime_pool.py`, `pipeline/agent_runner.py`, `deployment/aws/containerized/
  ecs_io_handler.py`, `deployment/aws/containerized/core/api/websocket_api.py`,
  `deployment/aws/core/websocket_service.py`, `deployment/aws/serverless/core/router/
  ws_lambda.py`, `deployment/aws/serverless/core/router/rest_lambda.py`,
  `deployment/aws/serverless/akauthorizer.py`, `deployment/aws/serverless/
  akwsconnectionhandler.py`, `deployment/gcp/akauthorizer.py` (delete),
  `deployment/azure/akfunction.py`, `integration/thread/manager.py`,
  `integration/thread/thread_chat.py`, `schedule/handler.py`, `sandbox/principal.py`,
  the examples listed in spec "Documentation, skills and examples".
- **Steps:**
  1. MCP: `AKTokenVerifier`, `AKAccessToken`, `AKMCPAuthProvider.from_config`, `auth=` on
     `FastMCP`, the principal on the executor's body (spec 8.6; the per-tool `AuthCheck` comes
     with iteration 5).
  2. A2A: `AKCallContextBuilder` on `create_rest_routes`, the principal on the executor's body
     (spec 8.7).
  3. `IntegrationProducer.enqueue` builds the `messaging:`/`realtime:` principal; each adapter
     fills `namespace` (and Gmail `claims`); LiveKit passes the participant identity;
     `RealtimeConnectionPool.dispatch` takes `body.principal` and `_execute_tool_and_reply`
     publishes it (spec 8.4).
  4. Deployment adapters per spec 8.9, including the AWS connection store's `principal`
     attribute and the authorizer context.
  5. Thread ownership `PermissionError` and the 401/403 mapping; schedule handler on the
     principal's subject; `AgentPrincipalResolver` reads the run principal (spec 8.10 to 8.12).
  6. Migrate the examples: `identity.provider.static` blocks with secret-resolved credentials,
     bodies and tests without `user_id`, READMEs.
- **Verify:** new `tests/test_api_mcp_auth.py`, `tests/test_api_a2a_auth.py`,
  `tests/test_principal_messaging.py`, `tests/test_schedule_principal.py`,
  `tests/test_deployment_identity.py`; changed `test_ecs_*`, `test_ws_lambda_stream`,
  `test_akauthorizer`, `test_authorizer_webhook_bypass`, `test_integration_producer`,
  `test_thread_pipeline_recording`, the three `*_agent_runner_schedule` suites,
  `test_cross_surface_parity`, `test_protocol_pipeline_roundtrip`; `examples/api/agui`,
  `examples/api/thread-openai` and `examples/aws-containerized/openai-websocket` `app_test.py`
  pass against a `static` provider.

## Iteration 4: Agent entity and registry

- **Goal:** every agent has a descriptor, the registry is pluggable and store-backed, the catalog
  and the protocol surfaces read descriptors, and the three removed config lists fail loudly.
- **Files:** `core/registry.py`, `identity/registry/*` (new), `core/config.py`, `core/builder.py`,
  `api/handler.py`, `api/mcp/akmcp.py`, `api/a2a/a2a.py`, `api/a2a/handler.py`,
  `integration/agui/handler.py`, the seven `framework/<name>/*.py`.
- **Steps:**
  1. `_RegistryConfig` and the overlay model; `AKConfig.registry`; the `agents`-removal
     validators on `_A2AConfig`, `_MCPConfig`, `_AGUIConfig` (spec Config changes).
  2. `_RedisLikeAgentRegistry`, Redis, Valkey and DynamoDB backends, `AgentRegistryContract`;
     `AgentRegistryFactory` reads the block and applies the overlay (spec 6).
  3. Adapter `get_tool_names()` per the spec 9 table (the LangGraph `ToolNode` walk included) and
     `get_a2a_card` through `A2ACardBuilder.build(descriptor)` with security schemes (spec 6).
  4. `ensure_agent_available` on `registry.descriptor`; the catalog route; MCP tool
     registration, A2A cards and AG-UI exposure from `descriptor.exposed_on` (spec 6, 8.5 to 8.7).
- **Verify:** `tests/test_agent_registry.py` (all backends, factory, overlay, cross-instance
  read), `tests/test_api_catalog.py`, the A2A card assertions in `test_api_a2a_auth.py` and
  `test_api_a2a_surface.py`, `test_config.py` cases for the removed lists; the k8s and
  `mcp/multi` example configs moved to `registry.agents.<id>.surfaces`.

## Iteration 5: Authorization

- **Goal:** an `authorization` block enforces agent levels, visibility, session ownership, resume
  identity and the fire-time re-check; tool filters are published for the adapters.
- **Files:** `identity/authz/*` (new), `core/config.py`, `core/runtime.py`, `core/service.py`,
  `core/chat_service.py`, `core/module.py`, `api/handler.py`, `api/mcp/akmcp.py`,
  `api/a2a/*`, `integration/agui/handler.py`, `pipeline/request_handler.py`,
  `pipeline/realtime_pool.py`, `schedule/manager.py`, `schedule/store/*`.
- **Steps:**
  1. `_AuthorizationConfig`, `_GrantConfig`, `_ToolPolicyConfig`; `AKConfig.authorization`.
  2. `Authorizer`, `Decision`, `AuthorizerCapabilities`, `StaticAuthorizer` with `GrantTable` and
     `SubjectMatcher`, `AuthorizerFactory` with the reserved engine names, `AuthorizerContract`
     (spec 7).
  3. `AccessGate` with its sync and async twins; `validate_configuration` called from
     `Module.load` and the handlers' `get_router()` (the Q12 check reads the default empty
     `ungated_tool_names` until iteration 6).
  4. Enforcement: `ensure_agent_available(name, principal)`; `Runtime` gate sequence and
     `authorize_session`; `ChatService` 403/404 mapping and the scheduled-trigger skip with
     `last_error`; the catalog, MCP per-tool `AuthCheck`, A2A card filtering and AG-UI 403; the
     realtime pool check before `execute_tool` (spec 7, 8.1, 8.4 to 8.7).
- **Verify:** `tests/test_authorizer_static.py`, `tests/test_access_gate.py`, the gate cases in
  `test_runtime_principal.py`, 403/404 cases in `test_api_http`, `test_pipeline_request_handler`
  (the riskiest consumer: precheck on a store-backed registry with no local agents), MCP list
  filtering in `test_api_mcp_auth.py`, the fire-time skip in `test_schedule_principal.py`.

## Iteration 6: Framework tool gates

- **Goal:** every adapter hides and refuses denied tools per the spec 9 table; `ToolContext.
  access_level` is live; LangGraph and smolagents refuse ungated tools under `authorization`.
- **Files:** `core/tool.py` (`ToolGate`), `framework/openai/openai.py`,
  `framework/pydanticai/pydanticai.py`, `framework/adk/adk.py`, `framework/crewai/crewai.py`,
  `framework/langgraph/langgraph.py`, `framework/smolagents/smolagents.py`,
  `framework/maf/maf.py`, `pipeline/realtime_pool.py`.
- **Steps:** one adapter per step in the table's order (OpenAI, Pydantic AI, ADK, CrewAI,
  LangGraph, smolagents, MAF), each adding its gate, `ungated_tool_names` where the table names
  one, and its `tests/test_tool_gates_<adapter>.py`; then the realtime check.
- **Verify:** the eight gate suites, including the keyword-for-keyword assertion on each mocked
  native call with no `authorization` block; the Q12 refusal cases in `test_access_gate.py`;
  `test_cross_surface_parity.py` unchanged.

## Iteration 7: Credentials

- **Goal:** the inbound credential is retained by reference and read through
  `ToolContext.credentials`; `passthrough` is the only exchanger.
- **Files:** `identity/credential/*` (new), `core/config.py`, `core/tool.py`,
  `identity/provider/request.py`, `core/runtime.py`, `pipeline/agent_runner.py`,
  `deployment/aws/{containerized,serverless}/akagentrunner.py`.
- **Steps:**
  1. `_CredentialsConfig` and its store models; `AKConfig.identity.credentials`.
  2. `CredentialStore`, `CredentialCipher`, the four backends, `CredentialStoreFactory`;
     `TokenExchanger`, `IssuedToken`, `PassthroughTokenExchanger`, `TokenExchangerFactory` with
     the reserved names; `CredentialBroker`; the two contracts (spec 5).
  3. `RequestAuthenticator` mints and stores `credential_ref` and `release` deletes it;
     `Runtime.run`/`stream` and every runner call `release` in `finally`;
     `ToolContext.credentials` returns the live broker (spec 3, 4, 8.3).
- **Verify:** `tests/test_identity_credentials.py` (contracts, cipher, broker, no token in a
  queue body or log, deletion on both paths, reserved exchanger names).

## Iteration 8: Tests

- **Goal:** the cross-cutting suites the per-iteration files do not own are green and the
  spec's Testing section is fully covered.
- **Files:** `tests/test_cross_surface_parity.py`, `tests/test_protocol_pipeline_roundtrip.py`,
  `tests/test_pipeline_request_handler.py`, the `FakeCfg` stubs in `tests/test_module.py:80-84`,
  `tests/test_runtime.py:79-155`, `tests/test_agui_handler.py:122-134`,
  `tests/test_pipeline_ws.py:54-74`, `tests/test_schedule_tools.py:92`,
  `tests/test_ecs_websocket_routes.py:19-27` (gaining `identity = authorization = registry =
  None`).
- **Steps:** walk the spec's Testing section file by file; confirm every new file exists and every
  listed patch target resolves; run the full suite and `make lint-check-all`.
- **Verify:** `cd ak-py && uv run pytest` green; `make lint-check-all` clean.

## Iteration 9: Sync docs and skills

- **Goal:** every surface in the spec's "Documentation, skills and examples" section matches the
  implementation.
- **Files:** `docs/docs/advanced/identity-and-access.md` (new) and the sixteen existing pages
  listed there; `ak-py/README.md`, `README.md`; `.agents/skills/ak-dev-architecture/SKILL.md`,
  `.agents/skills/ak-dev-testing-conventions/SKILL.md`,
  `.agents/skills/ak-dev-new-messaging-integration/SKILL.md`, new
  `.agents/skills/ak-dev-new-identity-provider/SKILL.md` and
  `.agents/skills/ak-dev-new-authorizer/SKILL.md`; `ak-py/src/agentkernel/skills/ak-cloud-deploy/`,
  `ak-add-capabilities/`, `ak-add-integration/` with their `evals/evals.json`; the
  `ak-deployment` READMEs and chart comments listed in the spec.
- **Steps:**
  1. Run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` over the branch;
     write the new advanced page from spec sections 2 to 8 and the design's worked example.
  2. Verify no update is needed for `ak-dev-write-spec`, `ak-dev-review-pr`, `ak-dev-new-*`
     skills other than the messaging one, `ak-build`, `ak-init`, `ak-test`, and the Terraform
     resources (the connections table keeps its `user_id` key; the authorizer Lambda keeps its
     `handler_path` contract).
- **Verify:** `grep -rn "AuthValidator\|Authoriser\|acting_user_id\|mcp.agents\|a2a.agents\|
  agui.agents\|userId" docs/docs .agents/skills ak-py/src/agentkernel/skills ak-py/README.md
  README.md ak-deployment` returns only the frozen `docs/versioned_docs/` snapshots and the
  Gmail API's `userId="me"`; the docs site builds (`NODE_ENV=production`, 6 GB heap).
