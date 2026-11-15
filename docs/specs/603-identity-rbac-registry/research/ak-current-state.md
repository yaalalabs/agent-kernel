# Agent Kernel today: identity, authorization and agent-registry surfaces

Evidence pass over `develop` (HEAD `0a33d7d9`), 2026-09-28. Every claim below was read from the
source; paths are relative to `ak-py/src/agentkernel/` unless prefixed. Supports issues #441 (auth
providers), #521 and #603 (RBAC), #658 (agent entity and registry), and relates to #243
(omnichannel identity) and the #494 sandbox permission boundary.

## 1. Headline findings

1. **There is an authentication seam but no identity layer.** `auth/` ships two ABCs
   (`AuthValidator`, `Authoriser`) and one adapter between them; no built-in JWT/OIDC, Cognito,
   API-key or static provider exists in the package (section 2).
2. **The REST chat surface validates a token and then discards who it belongs to.**
   `RESTAPI.add_auth_handlers` returns a `ValidationResult` from a FastAPI dependency that nothing
   reads; the acting user on `/api/v1/chat` is whatever `user_id` the client writes in the body
   (section 3).
3. **WebSocket surfaces authenticate one identity and act as another.** The validated `userId`
   claim keys the connection and routes the reply; the acting user is the client-controlled frame
   `user_id`, which `BaseRequest.from_payload` declares "authoritative" (section 3).
4. **No surface authorizes agent selection per user.** `AgentService.select` and
   `ensure_agent_available` check only that the name is registered; MCP, A2A and AG-UI filter by
   static config allow-lists that know nothing about the caller (section 4).
5. **The agent registry is a name-keyed dict on `Runtime`.** An `Agent` carries `name`, `runner`,
   hooks and run options, and nothing else: no id, version, owner, tags or catalog description
   (section 4).
6. **Tool sets are fixed per agent at load time.** There is no per-run or per-user tool filtering
   and no call-time interception point that AK wires; the only call-time checks live inside
   individual tools (OKF `write_kb`, the schedule tools) (section 5).
7. **Three unrelated per-agent scoping vocabularies coexist**: `agents:` allow-lists with
   `None`-means-all semantics, `["*"]` sentinels on A2A/MCP, and OKF's per-database roles
   (section 6).
8. **Two identity precedents already exist to build on**: the sandbox `SandboxPrincipal` with
   agent/user modes and a pluggable `PrincipalResolver`, and the run-scoped `ACTING_USER_CACHE_KEY`
   that the schedule tools read (section 7).

## 2. The `auth/` package

`auth/__init__.py:14-15` exports exactly five names:

```python
from .authoriser import Authoriser, AuthValidatorAuthoriser
from .handler import AuthValidator, ValidationContext, ValidationResult
```

- `ValidationContext` (`auth/handler.py:7-10`): `path`, `http_method`, `headers`, all optional.
- `ValidationResult` (`auth/handler.py:13-17`): `is_valid: bool`, `subject: Optional[str] = "user"`,
  `claims: Optional[Dict[str, Any]] = None`, `error_msg`. Note the default subject `"user"`: a valid
  result with no subject resolves to the literal user id `"user"`, which
  `ak-py/tests/test_authoriser_shared.py:54-57` pins as current behaviour.
- `AuthValidator(ABC)` (`auth/handler.py:20`): abstract
  `validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult` (:26),
  plus two protected helpers, `_validate_hmac` (:34) and `_validate_rs256_jwt(token, public_key,
  audience, issuer, options)` (:50-52), which lazily imports PyJWT (:62) and calls `jwt.decode(...,
  algorithms=["RS256"])` (:64-71). That is the entire built-in crypto surface: a static public key,
  no JWKS fetch, no discovery.
- `Authoriser(ABC)` (`auth/authoriser.py:17`): abstract `authorise(self, token: str) -> Optional[str]`
  (:26) returning a user id or `None`; the docstring (:18-23) states that with no Authoriser the
  protected routes remain open.
- `AuthValidatorAuthoriser(Authoriser)` (`auth/authoriser.py:35`, `__init__(validator)` at :42)
  returns `result.subject if result is not None and result.is_valid else None` (:56).
- A stray `auth.py` module (`from .auth import *`) is shadowed by the `auth/` package and is dead.
- Deployment adapters that wrap a caller-supplied validator, not providers of their own:
  `APIGatewayAuthorizer` (`deployment/aws/serverless/akauthorizer.py:24-101`, builds an IAM policy
  with `principalId=result.subject` and `context=claims`) and `GCPAuthorizer`
  (`deployment/gcp/akauthorizer.py:6-29`, calls `RESTAPI.add_auth_handlers([validator])`).
- The only readers of `ValidationResult.subject` in the package are `auth/authoriser.py:56` and
  `deployment/aws/serverless/akauthorizer.py:44` (grep `\.subject`).
- Extras: `auth = ["PyJWT>=2.13.0"]` (`ak-py/pyproject.toml:24-26`). No python-jose, authlib (only
  transitively via fastmcp and google-adk in `uv.lock`), casbin, openfga or cedar anywhere.

Concrete implementations in the repo are all examples or tests. Every example `AuthValidator`
decodes with `jwt.decode(token, options={"verify_signature": False})` against a hard-coded
allow-list, several with an explicit "trivially forgeable" warning (for example
`examples/aws-containerized/crewai-auth/app.py:46-62`, `examples/k8s/openai-queue-mode/app_ws_gateway.py:16-38`).
The `Authoriser` examples are static token maps (`examples/api/thread-openai/app.py:16-41`,
`examples/api/agui/app.py:59-112`). The GCP auth examples do JWT at API Gateway in Terraform
(`examples/gcp-containerized/openai-auth/deploy/main.tf:41-49`) and no in-process auth at all.

## 3. Per-surface authentication and acting-user resolution

| Surface | Token read | Acting user comes from | With nothing configured |
|---|---|---|---|
| REST, `RESTAPI.add_auth_handlers` (`api/http.py:170-198`) | `authorization` header (:184), `Bearer ` stripped (:187), `validate(token, ValidationContext(...))` (:188-190) | **Not the token.** The dependency returns `result` (:193) and no route reads it; chat `user_id` is the body field (`api/handler.py:105`) or the multipart form field (:121) | Open: `_get_router_dependencies` returns `None` (`api/http.py:32-36`). Dependencies attach to handler routers (:64) and custom routers (:166), and A2A routers are in that list (:151-155). MCP is `app.mount("/mcp", mcp_app)` (:161) and is **not** covered |
| `AuthorisedRESTRequestHandler._resolve_user` (`api/handler.py:39-73`) | header (:63), `partition(" ")` (:66), scheme must be `bearer` (:68) | `self._authoriser.authorise(token)` (:70); `None` is a 401 (:71-72) | Open: returns `None` (:61-62). Used only by the thread read routes, the schedule routes and AG-UI |
| Pipeline `IOHandler` (`pipeline/io_handler.py:38-152`) | `auth_validator` is used only to co-host the WebSocket handlers (:85, :98); otherwise warned about and ignored (:99-104) | body | ASYNC on `in_memory` without a validator raises (:194-198); REST open unless `add_auth_handlers` was called before `build_app` (:111) |
| Pipeline `RequestHandler` / `RestHandler` (`pipeline/request_handler.py:25, 220`) | none | body `user_id` (:256; multipart :342, :368). `RequestProducer.enqueue` stamps no user attribute (`pipeline/producer.py:44-50`) | open |
| Pipeline WebSocket `PipelineWebSocketHandler` (`pipeline/ws/handler.py`) | `token` query param (:177), `validate(token)` with no context (:181) | `claims["userId"]` (:185) keys the registry (:144), the store (:146) and `ATTR_USER_ID` (:230). The queued body is `BaseRequest.from_payload(payload)` (:205), so the **acting user is the frame's own `user_id`** | Refused: `ValueError` without a validator (:59-63) |
| `WebSocketGateway.run` (`pipeline/ws/gateway.py:38`) | delegates | same | Refused (:81-85); also needs `push_auth_token` (:96-99) |
| Push endpoint (`pipeline/ws/endpoint.py:40-54`) | `x-ak-push-token` header compared with `hmac.compare_digest` (`pipeline/ws/push.py:30`) | pod-to-pod, n/a | Fails closed, 403 (:48-51) |
| AWS Lambda REST (`deployment/aws/serverless/core/router/rest_lambda.py`) | none in-process; auth is the separate `APIGatewayAuthorizer.handle` Lambda (`akauthorizer.py:68-73`) | envelope via `from_payload` (:79-88), `user_id=payload.user_id` (:147). `requestContext.authorizer` is never read | open unless an API Gateway authorizer is attached |
| AWS Lambda WebSocket `$connect` (`ws_lambda.py:150-215`) | `queryStringParameters["token"]` (:158-168) | `claims.get("userId")` (:204-208) stored on the connection; messages resolve `get_user_id(connection_id)` (:75-80) for broadcast and the SQS attribute (:398-401); body again from `from_payload` (:51) | Refused: validator required when `connection_routes=True` (:445-446) |
| ECS `ECSIOHandler.run` (`deployment/aws/containerized/ecs_io_handler.py:31-86`) | WS mode `set_auth_handler` (:61); REST `AWSRestAPI.add_auth_handlers` (:66-67) | REST body; WS as next row | WS refused (:54-57); REST open |
| ECS `ECSWebSocketSystemRequestHandler` (`containerized/core/api/websocket_api.py:100-155`) | `token` query param (:138) | `claims.get("userId")` (:146) on the connection; frame body `from_payload` (:316); the runner uses the body (`akagentrunner.py:134, 141`) and the attribute falls back to `body.user_id` (:86-91) | Refused (:116-120, :500-507) |
| Azure Functions (`deployment/azure/akfunction.py:27-56`) | none | body (:42-45) | open, no hook |
| GCP Cloud Run (`deployment/gcp/akcloudrun.py:59-78`) | `CloudRun.run` calls `RESTAPI.run()`; `GCPAuthorizer.register` adds validators (`gcp/akauthorizer.py:20-29`) | same as REST (subject discarded) | open in-process |
| Threads (`integration/thread/thread_chat.py`) | read routes only: `ThreadRESTRequestHandler(AuthorisedRESTRequestHandler)` (:311), `_resolve_user` (:350, :367) | listing forced to the resolved user (:351-352); `get_thread(session_id, user_id=...)` raises `PermissionError` mapped to 403 (:369-371; `manager.py:199-200`). The **chat routes never call the authoriser** (:77-117, :268-283); `user_id` is required from the body (`recorder.py:46-47`); `get_or_create_thread` returns an existing thread without checking its owner (`manager.py:108-114`) | open reads |
| Schedules (`schedule/handler.py:70-177`) | `_resolve_user` (:98, :113, :125, :135) | listing forced (:98-99); single-task routes raise `PermissionError`, mapped to 403 by `_as_http_error` (:160-172; ownership check `schedule/manager.py:416-424`); `ScheduleManager.create` requires a `user_id` (`manager.py:135-136`); `record_trigger` checks ownership (`manager.py:267-315`) | open; `_check_ownership` is skipped when `user_id is None` (`manager.py:423`) |
| AG-UI (`integration/agui/handler.py:25-47`) | inherited `_resolve_user` (:149 list, :194 run) | `acting_user_id=user_id` (:263). The session is `run_input.thread_id` (:206) with no ownership check | Refused: `ValueError` "never served anonymously" (:41-45); a validator is wrapped via `AuthValidatorAuthoriser` (:46) |
| MCP (`api/mcp/akmcp.py:34-76`) | none | none: `service.run(prompt=prompt)` (:43) and `AgentService.run(self, prompt)` (`core/service.py:144`) has no user parameter | open; the only filter is `mcp.agents` (:66) |
| A2A (`api/a2a/a2a.py:36-63`, `api/a2a/handler.py:36-75`) | none of its own; covered by the global REST validators (`api/http.py:151-155`) | none: `service.run(prompt=prompt)` (:60-63). Cards carry no security schemes (`core/builder.py:38-48`) | open; filter is `a2a.agents` (:73) |
| CLI (`cli/cli.py:76-127`) | none | none (:119) | n/a |
| Messaging (`integration/*/adapter.py`) | platform verification only: Meta HMAC skipped when no `app_secret` (`integration/adapter/meta.py:20-40`), Telegram secret header optional (`telegram/adapter.py:118-124`), Slack via Bolt | the platform sender id becomes `InboundRequest.user_id` (`integration/adapter/base.py:59`) and then the body `user_id` (`integration/adapter/producer.py:79`, deliberately not a queue attribute, :64-66): Slack `user`, WhatsApp `from_number`, Messenger and Instagram `sender_id`, Telegram `sender_id`, Teams `activity.from_property.id`, Gmail `sender` | unsigned deliveries accepted when no secret is set |

The `from_payload` rule (`core/model.py:299-332`) strips `user_id` from an inner body and injects
the envelope's `user_id` with the comment "The envelope user_id is authoritative" (:325-328). On
every WebSocket surface the envelope is the client frame, so this makes the client authoritative
over whom the run acts for, while the connection was authenticated as `claims["userId"]`.

`BaseChatRequest` (`core/model.py:248-266`) carries `prompt`, `agent`, `session_id`, `user_id`,
`group_id`, `thread_name`, `schedule`; `BaseRunRequest` (:269-290) adds `files`, `images`,
`requests`, `scheduled_task_id`, `scheduled_time` with `extra="allow"`. `group_id` is thread-only:
fixed at thread creation (`integration/thread/manager.py:88, 94-100, 118`), a listing filter
(:219-235), indexed by the stores (`store/redis_like.py:72-74, 188`), populated by the Slack channel
and Teams group adapters. There is no group-membership check anywhere. The queue-level
`QueueMessage.group_id` (`pipeline/envelope.py:34`) is the FIFO key, a different concept.

`ChatService._attach_additional_context` excludes `user_id` and `group_id` from the context an agent
sees (`core/chat_service.py:127-143`).

## 4. The agent registry and every place that lists or selects agents

### 4.1 `Runtime` and `Module`

- `Runtime._agents = {}` (`core/runtime.py:140`), keyed by `agent.name`. `agents()` returns the live
  dict (:193-198). `register` raises a bare `Exception` on a duplicate name (:200-209); `deregister`
  deletes by name without checking identity and warns on an unknown name (:211-220). `load(module)`
  imports a module inside `with self` (:180-191). `GlobalRuntime` is a `Singleton` that builds the
  session store (:382-402). The registry is per `Runtime` instance
  (`ak-py/tests/test_module.py:164-179`).
- `Module` (`core/module.py`): `_agents = []` (:22); `load` calls `unload`, wraps each native agent
  and registers it, rolling back on failure (:59-77); `get_agent(name)` is a linear scan (:39-48);
  `_native_agent_name` defaults to `agent.name` (:147-155).
- Name derivation per adapter: OpenAI `agent.name` (`framework/openai/openai.py:467`), ADK
  `agent.name` (`framework/adk/adk.py:581`), LangGraph `agent.name`
  (`framework/langgraph/langgraph.py:722`), CrewAI `agent.role`
  (`framework/crewai/crewai.py:583-584, 601-607`), smolagents
  `getattr(agent, "name", "smolagent")` so two unnamed agents collide
  (`framework/smolagents/smolagents.py:351, 364-370`), Pydantic AI raises `ValueError` when
  `name is None` (`framework/pydanticai/pydanticai.py:585-590`).

### 4.2 What an `Agent` carries

`Agent.__init__(self, name: str, runner: Runner)` (`core/base.py:456-467`) stores `_name`,
`_runner`, `_pre_hooks`, `_post_hooks`, `_run_options`, `_run_options_factory`. Abstract methods:
`get_description()` (:582-587), `override_system_prompt` (:589), `attach_tool` (:601),
`get_a2a_card()` (:609-614). There is no id, version, owner, tags, visibility or catalog
description; grep for `version|owner|tags|metadata` in `core/base.py` finds nothing.

`get_description()` is not a catalog description: OpenAI returns the system prompt
(`openai.py:404-408`), ADK `agent.description` (`adk.py:523-527`), LangGraph the literal
`"I am a LangGraph agent."` (`langgraph.py:265-270`), CrewAI `goal or backstory`
(`crewai.py:508-512`), smolagents the system prompt falling back to `description`
(`smolagents.py:242-246`), Pydantic AI `description` falling back to instructions
(`pydanticai.py:492-503`). The AG-UI handler lists names only for exactly this reason: a
description can leak the system prompt (`integration/agui/handler.py:143-144`).

### 4.3 Listing and selection points

| Surface | Code | Filtering applied |
|---|---|---|
| REST `GET /api/v1/agents` | `AgentRESTRequestHandler.list_agents` returns `{"agents": list(Runtime.current().agents().keys())}` (`api/handler.py:102-103`); registered at :152 and by the pipeline handler (`pipeline/request_handler.py:214, 247`) | none |
| REST chat | `run` (`api/handler.py:105-114`) and `run_multipart` (:116-145) hand to `ChatService.execute*`, which call `prepare_agent_handler(req.session_id, req.agent)` (`core/chat_service.py:395, 412, 433, 461`) | registered-name check only |
| `AgentService` | `ensure_agent_available(name)` (`core/service.py:49-70`): `if (name and name not in agents) or (not name and not agents): raise ValueError("No agent available")`. `select(session_id, name)` (:72-101): dict lookup (:80); unknown name warns and leaves the selection unchanged (:84); no name picks the first registered agent in insertion order (:86-88) | none |
| `AgentHandler.initialize` | `ensure_agent_available` then `select` (`core/chat_service.py:211-224`) | none |
| AG-UI | `GET {prefix}/agents` (`integration/agui/handler.py:139-151`) resolves the user (:149) and then filters on `agent.runner.supports_streaming and self._is_exposed(name)` (:151), where `_is_exposed` is `exposed is None or agent_name in exposed` (:59-67). `_resolve_agent` 404s identically for unknown and unexposed names (:102-126) | static `agui.agents`; the user plays no part |
| MCP | `MCP._build` (`api/mcp/akmcp.py:57-76`): only when `mcp.expose_agents` (:63); `whitelisted = mcp.agents == ["*"] or name in mcp.agents` (:66); each agent becomes a FastMCP **tool** named after the agent with `description=agent.get_description()` (:71-75), so the system prompt is published as the tool description for OpenAI agents. Built once (:59, :76) | static `mcp.agents` |
| A2A | `A2A._build` (`api/a2a/a2a.py:65-79`): `whitelisted = a2a.agents == ["*"] or name in a2a.agents` (:73); `card = agent.get_a2a_card()` (:77); built once. `GET /a2a/catalog` returns every card (`api/a2a/handler.py:36-47`); public well-known card route (:67-75) | static `a2a.agents` |
| CLI | `!select` (`cli/cli.py:108-113`); the loop starts on the default agent (:78) | none |
| Pipeline runner | `AgentRunner.process` validates `BaseRunRequest` from the body (`pipeline/agent_runner.py:52`) and calls `process_chat_request(req=body, requests=body.requests)` (:59); the queue REST `run_chat` (`pipeline/request_handler.py:256-297`) does **not** precheck agent availability before enqueueing | none |
| Schedules | `ScheduleManager.create` prechecks only a *named* agent (`schedule/manager.py:145-146`, reason at :141-144) | registered-name check only |
| Messaging | `InboundRequest.agent` (`integration/adapter/base.py:58`) forwarded by the producer (`producer.py:75-82`); per-platform default `agent` fields at `core/config.py:159, 171, 188, 200, 213, 224, 242` | none |

`api.enabled_routes.agents: bool` (`core/config.py:110-111, 117`) is declared but no code reads it.

### 4.4 The A2A card, the only catalog record today

`A2ACardBuilder.build(name, description, skills)` (`core/builder.py:19-48`) emits `name`,
`description`, `url=f"{a2a.url}/{name}"`, `version=AKConfig.get().library_version` (the library
version, not an agent version), `default_input_modes=["text"]`, `default_output_modes=["json"]`,
`preferred_transport="HTTP+JSON"`, `capabilities=AgentCapabilities(streaming=False)`, `skills`. No
`security_schemes`, `security` or `provider`. Skills are one `AgentSkill(id=tool.name,
name=tool.name, description=..., tags=[])` per tool (OpenAI `openai.py:428-437`, CrewAI
`crewai.py:514-523`, LangGraph `langgraph.py:272-293` with empty descriptions, smolagents
`smolagents.py:307-319`, Pydantic AI `pydanticai.py:532-554`); ADK's `get_a2a_card` is a `TODO` that
returns `None` (`adk.py:546-551`).

### 4.5 The `skills` package is not a runtime catalog

`docs/specs/246-agent-skills/design.md:1-13` and `skills/skills.py` define `SKILL.md` guides for
coding assistants (`ak-init`, `ak-build`, ...), installed by the `ak` CLI (`cli/ak.py:48-136`).
They are unrelated to runtime agent capabilities. The only per-agent "skills" at runtime are the
A2A `AgentSkill` entries above.

## 5. Tools: binding, context and the absence of a call-time gate

- `ToolContext` (`core/tool.py:22-141`): `__init__(runtime, agent, session, requests)` (:34-47),
  `get()` raises `RuntimeError` outside a run (:89-100). **It carries no user or principal.** Set
  per run by every adapter (OpenAI `openai.py:202, 254`; CrewAI `crewai.py:338`; LangGraph
  `langgraph.py:450, 513`; smolagents `smolagents.py:139`; Pydantic AI `pydanticai.py:178, 230`;
  ADK stores the id in state and re-activates per call, `adk.py:237-241, 656-670`). ADK's native
  `user_id` is hard-coded to `"AgentKernel"` (`adk.py:234`) and reserved (:496).
- `ToolBuilder.bind(funcs)` (`core/tool.py:153-162`) has six implementations that only adapt the
  callable: `OpenAIToolBuilder` (`openai.py:479-500`), `CrewAIToolBuilder` (`crewai.py:610-631`),
  `LangGraphToolBuilder` (`langgraph.py:734-783`, which also appends `SystemToolFactory.get_all`),
  `SmolagentsToolBuilder` (`smolagents.py:373-420`), `GoogleADKToolBuilder` (`adk.py:593-698`),
  `PydanticAIToolBuilder` (`pydanticai.py:603-622`). None authorizes or intercepts.
- `SystemTool` (`core/model.py:197-200`): `name`, `description`, `func`.
- `SystemToolFactory._agent_allowed` (`core/tool.py:166-176`):

  ```python
  allowed = getattr(config, "agents", None)
  return allowed is None or agent_name is None or agent_name in allowed
  ```

  `get_all(agent_name)` (:178-230) branches on multimodal (:188-192), sandbox (:194-198), schedule
  (:200-206), OKF via `OKFToolFactory.get_tools` deliberately bypassing `_agent_allowed` (:208-215),
  `agui.state` (:217-222), `agui.client_context` (:224-228).
- **Attachment happens once, at load time.** `Agent._attach_system_tools()` (`core/base.py:626-636`)
  and `_setup_system_prompt()` (:616-624) are called from each adapter Agent's `__init__` (OpenAI
  :394-395, ADK :513-514, CrewAI :461-462, LangGraph :255-256 where `attach_tool` is a no-op and
  system tools arrive at graph build via the ToolBuilder, smolagents :232-233, Pydantic AI
  :482-483), which `Module._wrap` runs inside `Module.load` (`core/module.py:69`). The native tool
  list is mutated (`core/base.py:702-713`); name collisions only warn (:638-664).
- **No per-run or per-user tool filtering exists.** `Agent.resolve_run_options` (`core/base.py:528-552`)
  is the only per-run input to the native call and AK does not use it for tools.
- **No call-time interception AK wires.** Grepping `on_tool_start|RunHooks|AgentHooks|
  before_tool_callback|after_tool_callback|step_callbacks` across the package finds only LangGraph's
  `astream_events` kind `"on_tool_start"` mapped to a `ToolCallStart` stream event
  (`langgraph.py:610-611`). `ToolCallStart` (`core/event.py:58`) is emitted by the stream mappers
  (`openai.py:344`, `adk.py:450`, `pydanticai.py:344`, `langgraph.py:611`) after the framework has
  already produced the item; `PostHook.on_stream_event` sees it only on streamed runs
  (`core/runtime.py:341-343`), and the non-stream `run()` path has no tool event at all. For OpenAI
  the arguments arrive whole on `tool_called` (`openai.py:241-242`). The only way to install a
  native tool hook today is user-level: `Module.run_options` forwarding native kwargs such as
  OpenAI `hooks` (`core/module.py:103-105`) or ADK `plugins` (`adk.py:111-112, 244-246`).
- Call-time checks that do exist live inside individual tools: OKF `write_kb` checks
  `manager.roles.may_write(agent_name, backend)` (`knowledgebase/okf/tools.py:150-152`) with the
  agent name bound into the closure, deliberately not `ToolContext` (:147-149); the five schedule
  tools read the acting user (`schedule/tools.py:73-81`) and the manager checks ownership
  (`schedule/manager.py:416-424`).

## 6. Hooks as an enforcement point

- `PreHook.on_run(session, agent, requests) -> list[AgentRequest] | AgentReply` (`core/hooks.py:42`);
  `PostHook.on_run(session, requests, agent, agent_reply)` (:72);
  `PostHook.on_stream_event(session, requests, agent, event)` (:94-100); `StreamHalt` (:20-37). The
  module docstring (:16) notes hooks run only for the initial execution, not for agent-to-agent
  calls inside a workflow.
- System hook order: `Runtime._system_pre_hooks = [InputGuardrailFactory.get(),
  MultimodalPreHookFactory.get(), SandboxPreHookFactory.get()]` (`core/runtime.py:122`),
  `_system_post_hooks = [OutputGuardrailFactory.get()]` (:130); `pre_hooks = agent.pre_hooks +
  self._get_system_pre_hooks()` so system pre-hooks run **last** (:238), and system post-hooks run
  first (:288, stream :337). They are process-wide class attributes (:112-131), not per agent.
- A PreHook can halt a run: `_prepare_requests` returns the reply when the hook returns an
  `AgentReply` (:241-242); `run` returns it without storing the session (:279-281, store at :295);
  `stream` yields `StreamChunk(error=..., done=True)` (:329-332). Hooks run after the acting user
  is published (:275-276) and inside `agent._activate()` (:277), so a hook can read both
  `ACTING_USER_CACHE_KEY` and `Agent.current()`. Existing halting hooks: `SandboxPreHook`
  (`sandbox/hooks.py:72-75`), Bedrock (`guardrail/bedrock.py:199`), WalledAI
  (`guardrail/walledai.py:130`), and the auth-gate example `examples/sandbox/identity/identity.py:46-72`
  which returns "Unauthorized" as an `AgentReplyText` (:60-65).

A pre-hook is therefore a viable "may this user run this agent" gate today, but it fires after the
session was loaded and, on the pipeline, after the request was queued and acknowledged: too late to
answer with a 403 and too late to keep a phantom thread or a wasted queue slot from being created
(compare `AgentThreadRequestHandler`'s precheck rule, `integration/thread/thread_chat.py:209-217, 300`).

## 7. Existing identity precedents to build on

### 7.1 The acting user

- `ACTING_USER_CACHE_KEY = "ak.acting_user_id"` (`core/runtime.py:34-36`), exported from
  `core/__init__.py:45`. `Runtime.run(agent, session, requests, acting_user_id=None)` (:257) sets it
  (:275-276) and clears it with the volatile cache (:297-298); `stream` (:300-301) likewise
  (:325-326).
- Threaded from `ChatService.execute*` as `acting_user_id=req.user_id` (`core/chat_service.py:396,
  413, 437, 464`, and `_record_trigger` :521) through `AgentHandler.run_*` (:250-280) to
  `AgentService.run_multi` / `stream_multi` (`core/service.py:162, 180`). `AgentService.run(prompt)`
  (:144) has no acting user, and MCP, A2A and the CLI use it.
- **Exactly one reader**: `ScheduleToolUtil.acting_user()` (`schedule/tools.py:20, 73-81`), used by
  all five schedule tools, which return `_NO_IDENTITY` (:28) when it is absent. The sandbox does not
  read it. The design origin is `docs/specs/629-scheduled-tasks/design.md:120-137`.

### 7.2 The sandbox principal

- `SandboxPrincipal` (`sandbox/model.py:114-120`): `mode: Literal["agent", "user"] = "agent"`,
  `subject: str`, `credentials: dict`, `groups: list[str]`.
- `PrincipalResolver.resolve(session, agent) -> SandboxPrincipal` (`sandbox/principal.py:17-26`);
  `AgentPrincipalResolver` returns the agent-mode principal named after the agent (:29-39).
  Configured by the dotted-path `sandbox.principal_resolver` (`core/config.py:841-843`) and resolved
  via `resolve_dotted(..., base=PrincipalResolver)` with a default (`sandbox/manager.py:46-51`);
  resolved per operation from `Session.current()` and the `ToolContext` agent (:306-320).
- The worker fails closed: a user-mode profile against a provider without `principal_user`, or a
  resolver that returned an agent-mode principal, raises `SandboxPolicyError`
  (`sandbox/broker/worker.py:125-139`).
- Kubernetes maps a user principal to impersonation: `Impersonate-User` from
  `credentials["user"] or subject` (`sandbox/providers/kubernetes.py:229, 244`), one
  `Impersonate-Group` (:230, :245-246, more than one rejected :234-237), clients cached per
  `(user, groups)` (:238-248). EC2 SSM maps `credentials["role_arn"]` and `run_as`
  (`sandbox/providers/ec2_ssm.py:208-226`).
- **AK never hands the resolver a user.** The user-mode example seeds the identity from a PreHook
  into `nv_cache["user_identity"]` and reads it back in a custom resolver
  (`examples/sandbox/identity/identity.py:46-88`). The `#494` design named "agent-own vs
  user-assumed" identity as a first-class permission boundary
  (`docs/specs/494-sandbox-capability/design.md:104-134`).

### 7.3 OKF roles, the only role model in the repo

- `OKFRole(StrEnum)`: `consumer`, `producer`, `curator` (`knowledgebase/okf/roles.py:22-27`), with
  `writable` true for all but consumer (:29-40). `OKFAssignment(database, role)` (:43-52).
  `OKFRoleRegistry.from_config` rejects a database naming no agent (:99-104) and an agent that is
  both producer and curator of one database (:106-112); `may_write(agent_name, database)` (:157-168).
- Config: `okf.databases.<name>.consumer|producer|curator: Optional[list[str]]`
  (`core/config.py:432-440`), the block optional at :963-966.
- Resolution: `OKFCapabilityManager.builder_for(agent)` builds a `KnowledgeBuilder` over only that
  agent's databases (`knowledgebase/okf/capability.py:145-166`), so read scoping is structural;
  `OKFToolFactory.get_tools` returns nothing without a role and omits `write_kb` without a writable
  one (`okf/tools.py:34-55, 155-157`); the write check is at call time (:150-152).
- The subject is always the agent. There is no user dimension. The `#553` design states as a
  non-goal "a generic role or permission framework" and keeps the vocabulary inside
  `knowledgebase/okf/` (`docs/specs/553-okf-knowledge-bases/design.md:645-648, 927-929`).

## 8. Per-agent scoping vocabularies in config (`core/config.py`)

| Field | Lines | Type | Semantics |
|---|---|---|---|
| `a2a.agents` | 141 | `List[str]` | default `["*"]` |
| `mcp.agents` (+ `mcp.expose_agents`) | 148-149 | `List[str]` | default `["*"]` |
| `multimodal.agents` | 269-272 | `Optional[list[str]]` | `None` = all, `[]` = none |
| `schedule.agents` | 403-406 | `Optional[list[str]]` | same |
| `sandbox.agents` | 836-839 | `Optional[list[str]]` | same |
| `agui.agents`, `agui.default_agent` | 923, 925 | `Optional[list[str]]` | `None` = all streaming-capable |
| `agui.state.agents`, `agui.client_context.agents` | 906, 916 | `Optional[list[str]]` | tool scoping |
| `okf.databases.<db>.consumer|producer|curator` | 432-440 | per-role lists | per (agent, database) |
| `sandbox.principal_resolver` | 841-843 | dotted path | identity mode plumbing |
| `sandbox.<profile>.identity.mode` | 673-678, 816 | `agent` or `user` | per profile |

Every one of these is an **agent-to-capability** grant. None is a **user-to-agent** grant. There is
no end-user auth configuration at all: no validator, authoriser, issuer, JWKS or API-key setting;
all auth is code-wired through constructor arguments (`authoriser=`, `auth_validator=`).

## 9. Reusable plumbing for a registry, policy store or identity cache

- Factory shape (`core/util/factory.py`): `AKConfigError` (:18-23), `resolve_dotted(path, *, base,
  error=AKConfigError)` (:26-46), `require_extra(extra, feature)` (:49-64, re-raises as
  `ImportError`). Representative builder: `ScheduleStoreBuilder.build()`
  (`schedule/store/base.py:98-146`), `if key == "in_memory"` ... `require_extra("redis", ...)` ...
  dotted path fallback, built-in names in a list at :13.
- Config models to reuse whole or subclass: `_RedisConfig` (:22), `_ValkeyConfig` (:31),
  `_DynamoDBConfig` (:40), `_CosmosDBConfig` (:50), `_FirestoreConfig` (:59); the subclass pattern
  `_ThreadRedisConfig(_RedisConfig)` (:295), `_ScheduleStoreDynamoDBConfig(_DynamoDBConfig)` (:376).
- Drivers (`core/util/driver/`): `_RedisLikeDriver(url, prefix, ttl, decode_responses)`
  (`redis_like.py:32`) with sets, hashes and `scan_keys`; `DynamoDBDriver(table_name, partition_key,
  sort_key, region, ttl)` (`dynamodb.py:23-30`); `CosmosDBDriver`, `FirestoreDriver`, `S3Driver`.
  Representative key schema: the schedule store's `{prefix}task:{id}` document plus
  `{prefix}index:user:{user_id}` and `{prefix}index:all` sets (`schedule/store/redis_like.py:3-6`),
  and the DynamoDB single-partition-key item with denormalized `user_id` (`schedule/store/dynamodb.py:3-18`).
- The session backend already provides a second store on the same connection
  (`SessionStore.get_connection_store()`), which is the house precedent for letting an
  already-configured backend host a registry or policy store without a second `type` selector.

## 10. Test seams that already cover the area

- Auth primitives: `tests/test_auth_handler.py`, `test_authoriser_shared.py`, `test_akauthorizer.py`,
  `test_api_http.py:185-289` (`add_auth_handlers`), `test_pipeline_ws.py:350`.
- Thread authoriser: `test_thread_router.py:127-165`, `test_thread_manager.py:176`.
- AG-UI: `test_agui_handler.py:203-287, 565`.
- Schedule ownership: `test_schedule_router.py:252-315`, `test_schedule_manager.py:333-345, 444,
  478, 532`, `test_schedule_tools.py:293`.
- `_agent_allowed`: `test_sandbox.py:946-975`, `test_schedule_tools.py:156-171`, `test_agui_state.py:149`.
- OKF roles: `test_knowledgebase_okf_roles.py`, `test_knowledgebase_okf_tools.py:213, 287, 423`.
- Registry: `test_module.py:146, 164`. Hooks: `test_runtime.py:711, 728`,
  `test_runtime_stream_events.py:317-364`. Acting user: `test_chat_service_core.py:326-343`.
- MCP: `test_api_mcp.py` has three tests, none about allow-lists or auth.

## 11. What prior specs decided about identity

- `docs/specs/348-conversation-thread-support/design.md:272-293`: the authorisation flow;
  "Agent Kernel does not verify identity itself" (:275).
- `docs/specs/523-ag-ui-support/design.md:402-423`: `user_id` is derived from the bearer token,
  never from the request body; decision log D5/D6 (`research/decision-log.md:48-49`).
- `docs/specs/629-scheduled-tasks/spec.md:381-424`: relocation of `Authoriser` to `auth/`, the
  adapter, `AuthorisedRESTRequestHandler`, and the acting-user contract.
- `docs/specs/527-thread-store-deployment/design.md:162-216`: route authorization removed from
  scope; an in-process authorizer on ECS flagged as a risk (:210-211).
- `docs/specs/494-sandbox-capability/design.md:104-134` and
  `docs/specs/503-sandbox-queue-broker/spec.md:442-468`: the sandbox permission boundary and the
  chart's `sandboxWorker.rbac.impersonate` ClusterRole.
- Website docs that describe the open-by-default posture: `docs/docs/api/rest-api.md:383-411`,
  `docs/docs/advanced/threads.md:179-210`, `docs/docs/advanced/scheduling.md:236-260`,
  `docs/docs/integrations/agui.md:60-67`, `docs/docs/advanced/sandbox.md:230-262, 382`.
