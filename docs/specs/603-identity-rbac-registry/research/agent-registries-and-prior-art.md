# Agent registries, catalogs and framework-level access control: prior art

Survey date: 2026-09-28. Supports issue #658 (agent entity and registry) and the enforcement-point
and access-level questions of #603.

Verification legend: **[V]** primary page fetched and read; **[U]** search snippet, secondary source
or inference. Re-verify [U] claims before designing against them.

## A. What an agent record looks like elsewhere

### A.1 A2A Agent Card and discovery

- Latest released spec is **v1.0.0** [V]. https://a2a-protocol.org/latest/specification/
- v1.0.0 `AgentCard` fields: `name`*, `description`*, `supportedInterfaces[]`* (`url`,
  `protocolBinding`, `protocolVersion`, optional `tenant`), `provider`, `iconUrl`, `version`,
  `documentationUrl`, `capabilities`* (`streaming`, `pushNotifications`, `stateTransitionHistory`,
  `extensions[]`, `extendedAgentCard`), `securitySchemes` (map), `security[]`, `defaultInputModes`*,
  `defaultOutputModes`*, `skills[]`, `extensions[]`, `signatures[]` (* required) [V].
- `AgentSkill`: `id`*, `name`*, `description`, `tags[]`, `examples[]`, `inputModes`*, `outputModes`*,
  and a **per-skill `security[]`** [V].
- v0.3.0 differences: `url`, `preferredTransport`, `additionalInterfaces` collapsed into
  `supportedInterfaces`; `supportsAuthenticatedExtendedCard` became `capabilities.extendedAgentCard`
  with a `GetExtendedAgentCard` operation available only after authenticating with a scheme from the
  public card [V]. https://a2a-protocol.org/v0.3.0/specification/ AK's `A2ACardBuilder` emits the
  0.3-era `url` and `preferred_transport` (`core/builder.py:38-48`); the pyproject floor is
  `a2a-sdk[http-server]>=0.3.6` (`ak-py/pyproject.toml:167-168`) while the lock resolves 1.1.2
  (`ak-py/uv.lock:18-19`). Whether 1.x still accepts those names was not checked here.
- Discovery [V]: (1) the well-known URI `/.well-known/agent-card.json` (RFC 8615); (2) curated
  registries, where "the current A2A specification does not prescribe a standard API for curated
  registries"; (3) direct configuration. Guidance recommends authenticated extended cards for
  sensitive detail and HTTP-level access control on the card endpoint.
  https://a2a-protocol.org/latest/topics/agent-discovery/
- What the card lacks: owner, visibility, roles, tool list. Access requirements are only
  `securitySchemes` / `security` (card and per-skill) plus the extended-card mechanism [V].
- The A2A repo's registry discussion (#741, opened 2025-06-10, active into May 2026, no closure)
  converges on a three-layer model: the *Agent Card*, a *Publication Record* (namespace, owner,
  visibility, lifecycle state, version) and a separate *Authorization Overlay* (entitlements not
  embedded in the card); endpoints evolved toward `GET /agents` and `GET /agents/{id}` with
  filters; proposed roles Administrator, Catalog Manager, User, Viewer; auth-aware filtering of
  listings by caller identity [V]. https://github.com/a2aproject/A2A/discussions/741

### A.2 The official MCP Registry (the tool-catalog model)

- Launched preview 2025-09-08; still "in preview" with possible breaking changes before GA [V].
  https://modelcontextprotocol.io/registry/about README states an API freeze at v0.1 [V].
  https://github.com/modelcontextprotocol/registry
- `server.json`: required `name` (reverse-DNS, `io.github.user/server`), `description`, `version`
  (semver); at least one of `packages[]` (npm, PyPI, NuGet, Cargo, OCI, MCPB) or `remotes[]`
  (streamable-http, SSE); optional `title`, `repository`, `websiteUrl`, `status`, `_meta` under
  `io.modelcontextprotocol.registry/publisher-provided` [V].
  https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/generic-server-json.md
- Namespaces are verified via GitHub OAuth/OIDC (`io.github.*`) or DNS/HTTP challenge; the official
  registry is deliberately unopinionated metadata; private servers are explicitly out of scope and
  the codebase is "not designed for self-hosting"; sub-registries implement the same OpenAPI [V].
- No access policy in `server.json`; authorization lives in the private sub-registry and at the
  server [V by absence].

### A.3 Cisco AGNTCY (Linux Foundation)

- OASF record: `name`, `version`, `schema_version`, `description`, `authors[]`, `created_at`,
  `skills[]` and `domains[]` (taxonomy entries with numeric ids from schema.oasf.outshift.com),
  `locators[]`, `modules[]`, `signature`, `previous_record_cid`; content-addressed and signable. No
  owner, visibility or tool-ACL fields [V]. https://docs.agntcy.org/oasf/agent-record-guide/
- Agent Directory Service: federated, DHT-based, Store / Routing / Search, OIDC auth as an
  extension, an MCP server exposing the directory; no RBAC model documented [V].
  https://dir.agntcy.org/latest/
- Identity: "Agent Badge" as an enveloped W3C Verifiable Credential; SPIFFE SVIDs via SPIRE [V].
  https://spec.identity.agntcy.org/docs/vc/intro/

### A.4 Other open efforts

- **NANDA (MIT)**: `AgentAddr` (Ed25519-signed, at most 120 bytes) mapping an agent id to a
  `FactsURL`, optional `PrivateFactsURL`, `AdaptiveRouterURL`; `AgentFacts` carries identity, name,
  capabilities, endpoints, certification, skills, evaluations, telemetry, TTL [V].
  https://arxiv.org/abs/2507.14263
- **OWASP ANS v1.0**: DNS-inspired naming, PKI certificates, registry + CA + RA, adapters for A2A /
  MCP / ACP; IETF draft `draft-narajala-ans-00` [U].
- **agents.json (Wildcard)**: OpenAPI + Arazzo flows at `/.well-known/agents.json` [U].

### A.5 Vendor catalogs

**AWS Agent Registry (AgentCore)**, the closest analogue to what #658 asks for:

- Preview 2026-04-09 [V], GA 2026-08-31 with its own `agent-registry` service namespace; the older
  `bedrock-agentcore` registry APIs retire 2026-10-30 [V docs, U for the exact GA date].
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry.html
- A registry has a name, description, inbound authorization config (IAM or JWT from a corporate
  IdP) and an approval config (manual or auto) [V].
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-concepts.html
- A record: `name`, `displayName`, `description`, `recordVersion`, `recordType` (`AGENT` | `MCP` |
  `SKILL` | `CUSTOM`), `tags`, and one primary descriptor: `a2aAgentCard` (validated against the
  A2A 0.3 schema), `mcpServer` (server.json plus MCP tool schema), `agentSkillsDefinition`
  (SKILL.md), or `custom`. `name` + `recordVersion` is the uniqueness key [V].
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-supported-record-types.html
- Lifecycle: `DRAFT` to `PENDING_APPROVAL` to `APPROVED` | `REJECTED`, `DEPRECATED` terminal;
  editing an approved record creates a new draft revision while the approved one stays
  discoverable; discovery APIs return only approved revisions [V].
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-record-lifecycle.html
- Personas: Administrator, Publisher, Curator/Approver, Consumer; discovery via hybrid search,
  paginated browse, or the registry's own MCP endpoint; records can sync from a live MCP/A2A
  endpoint; tags usable in IAM conditions [V]. **No per-record ACL**: access is registry-level auth
  plus approval state.

**Microsoft**: the Agent 365 Agent Registry in the M365 admin center lists agent types (Microsoft,
partner, "Published by your org", "Shared by creator"); exported fields include Name, Status,
Channel, Publisher, Version, Owner, Description, Platform, Instructions; actions: upload manifest,
publish to users or groups, deploy, pin, block, ownerless-agent triage [V].
https://learn.microsoft.com/en-us/microsoft-365/admin/manage/agent-registry Copilot Studio agents
auto-register with name, description, publisher, agent type, Agent ID, connectors used, DLP status,
version [V]. https://learn.microsoft.com/en-us/microsoft-agent-365/builder/agent-registry Entra
Agent ID: an *agent identity* (service principal) created from an *agent identity blueprint*
(class of agent, publisher, roles, Graph scopes); Foundry uses a shared project identity for
unpublished agents and a distinct identity per published agent [V].
https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-identity

**Google**: Gemini Enterprise Agent Gallery shares agents with users, groups, workforce pools or
all, with a role per share: "Agent User" (`agentUser`: query/run, no edit) versus
`roles/discoveryengine.agentspaceAdmin`; ownership transfer demotes the previous owner to
`agentUser` [V]. https://docs.cloud.google.com/gemini/enterprise/docs/share-custom-agents Agent
Engine: sharing an agent is granting `aiplatform.reasoningEngines.query` on the specific
`reasoningEngine` resource; the docs state "Agent Runtime only provides coarse access control to the
agent interface" [V]. https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/share-agent

**Databricks**: *Agent Services in Unity Catalog* (beta): an agent is a UC object
`agent-services/<catalog>.<schema>.<name>` with `comment`, `config`, `agent_service_type`,
`created_by`; privileges `EXECUTE`, `READ METADATA`, `MANAGE`, `ALL PRIVILEGES` [V]; tools are
governed as UC `FUNCTION` (`EXECUTE`, `MANAGE`, `READ METADATA`) and `CONNECTION` [V].
https://docs.databricks.com/aws/en/ai-gateway/agent-services

**Snowflake**: `AGENT` is a schema-level object: `CREATE AGENT` on the schema, `USAGE` to query,
`MODIFY` to update, `MONITOR` for threads, logs and traces, `OWNERSHIP`; each tool's underlying
objects need their own privileges and a missing tool privilege defaults to a warning [V].
https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-setup

**ServiceNow**: per-agent "who can discover and use" by roles or user criteria; run-as "Dynamic
user" (inherits the invoker's roles) or a dedicated "AI user"; role masking narrows the effective
role set; skills and tools require approved roles [V community article].
https://www.servicenow.com/community/now-assist-articles/latest-access-control-security-enhancements-for-ai-agents-and/ta-p/3374036

**IBM watsonx Orchestrate**: a catalog of Agents, MCP servers, Tools and Apps with name,
description, publisher, category tags, status labels, capabilities and dependencies; tenant-level
usability control is all-or-nothing [V]. https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=discovering-catalog

**Salesforce Agentforce**: access per permission set ("Agent Access" lists active agents to move
into "Enabled Agents") [V]; builder permissions "Manage AI Agents" [U].

### A.6 Kubernetes-native

- **kagent**: `kind: Agent` (`kagent.dev/v1alpha2`), `spec.type: Declarative|BYO`,
  `spec.declarative.{modelConfig, systemMessage, stream, tools[]}` where a tool is
  `{type: McpServer, mcpServer: {apiGroup, kind, name}, toolNames: [...]}`; a static per-agent
  allow-list; access control is Kubernetes RBAC on the CRDs [V via a mirror; kagent.dev returned
  HTTP 500 repeatedly].
- **agentgateway**: `AgentgatewayPolicy` with `spec.backend.mcp.authorization: {action: Allow|Deny,
  policy.matchExpressions: ['jwt.sub == "alice" && mcp.tool.name == "get_me"']}` (CEL); unauthorised
  tools are **removed from `tools/list`**, not only rejected on call [V].
  https://agentgateway.dev/docs/kubernetes/latest/mcp/tool-access/

### A.7 Takeaways for an AK agent entity

Every mature catalog separates (a) the protocol-native descriptor (A2A card, `server.json`) from
(b) registry metadata (owner, version, tags, lifecycle status, visibility) and (c) an authorization
overlay held outside the card. Versioning is semver on the record with name + version uniqueness
(AWS, MCP registry, OASF). Approval state is the dominant visibility primitive at AWS; per-principal
grants are the primitive at Google, Databricks, Snowflake and Copilot Studio.

## B. Framework-level authorization prior art

### B.1 LangGraph Platform / LangSmith Deployment

- `@auth.authenticate` returns a dict with `identity` (required), `is_authenticated`,
  `permissions[]` and arbitrary custom fields; `@auth.on` handlers at global, resource
  (`@auth.on.threads`, `.assistants`, `.crons`, `.store`) and action level (`.create`, `.read`,
  `.update`, `.delete`, `.search`, `.create_run`); the most specific handler wins [V].
  https://docs.langchain.com/langsmith/auth , https://reference.langchain.com/python/langgraph-sdk/auth/Auth
- Returning `None` or `True` allows, `False` or raising is a 403, and **a dict is a metadata filter
  applied to the query** (default `$eq`, `$contains` for list membership, multiple keys AND).
  "Owner" is a convention: the create handler stamps `value["metadata"]["owner"] =
  ctx.user.identity` and returns `{"owner": ...}`, and reads and searches are filtered at the
  database layer [V]. `AuthContext(user, resource, action, permissions)`.
- *Assistants* (graph + config + runtime context, auto-versioned, searchable) combined with
  `assistants.search` filters form a per-user-visible agent catalog [V].
  https://docs.langchain.com/langsmith/assistants
- Enforcement point: server-side, before the run, with list filtering; user identity available;
  dynamic code, not config.

### B.2 Google ADK and Vertex AI Agent Engine

- `before_tool_callback(tool, args, tool_context)`: returning a dict **skips execution and that
  dict becomes the tool result sent to the LLM**; `None` proceeds [V].
  https://adk.dev/callbacks/types-of-callbacks/ `ToolContext` inherits `ReadonlyContext` exposing
  `user_id`, `session`, `state`, `agent_name`, `invocation_id`, `run_config`, `custom_metadata`
  [V]. Tool auth via `AuthCredential` and `tool_context.request_credential(...)`. There is no
  tool-list filter hook; gating is call-time.
- Agent Engine per-agent access is an IAM binding of `aiplatform.reasoningEngines.query` on the
  resource [V]; predefined roles `roles/aiplatform.admin|user|viewer|expressUser` exist [V].
- AK today hard-codes ADK's `user_id` to `"AgentKernel"` (`framework/adk/adk.py:234`), so
  `tool_context.user_id` would be useless for an AK deployment until the acting user is threaded in.

### B.3 OpenAI Agents SDK

- `FunctionTool.is_enabled: bool | Callable[[RunContextWrapper, AgentBase], MaybeAwaitable[bool]]`;
  disabled tools are "completely hidden from the LLM at runtime", re-evaluated before invocation;
  the docs warn it "controls visibility only, it does not replace authorization checks based on tool
  arguments or accessed resources" [V]. https://openai.github.io/openai-agents-python/tools/
- `tool_input_guardrails` / `tool_output_guardrails` (`@tool_input_guardrail`) run on every
  invocation; outcomes `allow()`, `reject_content(message)` (blocks and sends the message to the
  model) or a tripwire exception; `data.context` is the `RunContextWrapper` [V]. Not applicable to
  hosted tools or handoffs.
- MCP: `create_static_tool_filter(allowed_tool_names, blocked_tool_names)` or a dynamic
  `(ToolFilterContext{run_context, agent, server_name}, tool) -> bool` applied at list time [V].
- `needs_approval` (bool or callable, fail-closed on malformed args) pauses the run;
  `state.reject(...)` returns a rejection message to the model [V].
- `RunHooks.on_tool_start(context, agent, tool) -> None` is observational only [V]. No registry
  concept in the SDK. The hosted Agent Builder shuts down 2026-11-30 [V].
  https://developers.openai.com/api/docs/guides/agent-builder
- AK relevance: `RunContextWrapper.context` is exactly what AK's `framework_context` is injected as
  (`ak-dev-architecture`, Runner), so a user principal placed in the framework context would be
  reachable from `is_enabled` and tool guardrails without new plumbing.

### B.4 CrewAI

- `@before_tool_call` receives `ToolCallHookContext{tool_name, tool_input (mutable), agent, task,
  crew, tool}`; returning `False` blocks and the agent sees `"Tool execution blocked by hook. Tool:
  <name>"`; `@after_tool_call` can rewrite `tool_result`; hooks are global (filterable by `tools=`
  and `agents=`) or crew-scoped [V]. https://docs.crewai.com/en/learn/tool-hooks Added in 1.9.1 [V
  for the release line, U for the date]. No user identity in the hook context; close over it.
  Enterprise (AMP): SSO with Entra, Okta, Auth0 [V]; RBAC with custom roles [U].

### B.5 Pydantic AI

- Per-tool `prepare: (ctx: RunContext[Deps], tool_def: ToolDefinition) -> ToolDefinition | None`
  (`None` omits the tool that step); agent-wide `prepare_tools`; `toolset.filtered((ctx, tool_def)
  -> bool)` and `toolset.prepared(...)` evaluated ahead of each step; per-run `toolsets=` on
  `agent.run`; `requires_approval=True` [V].
  https://pydantic.dev/docs/ai/tools-toolsets/tools-advanced/ User identity via `ctx.deps`, which is
  where AK injects its framework context (`deps=`).

### B.6 smolagents

- Only `step_callbacks` (post-step) and `final_answer_checks`; no pre-tool hook [V]. Feature request
  #2654 (2026-08-18) asks for `before_tool_call` / `before_code_execution` hooks; no maintainer
  response yet [V]. https://github.com/huggingface/smolagents/issues/2654 Gating must wrap
  `Tool.forward` or filter the `tools` list before construction.

### B.7 Microsoft Agent Framework

- Python function middleware `process(context: FunctionInvocationContext, call_next)`: block by
  setting `context.result` and not calling `call_next()`, or raise `MiddlewareTermination`;
  agent-level or run-level registration; `function_invocation_kwargs` forwards tenant and user
  values to tools [V]. https://learn.microsoft.com/en-us/agent-framework/agents/middleware/
- **Agent Hooks** (Python, experimental, September 2026): interception points `pre_tool_call`,
  `post_tool_call`, `pre_model_call`; fail-closed; a policy deny at the tool seam "returns a control
  error containing the policy reason to the model" so the loop continues; hosted tools cannot be
  blocked [V]. https://learn.microsoft.com/en-us/agent-framework/agents/agent-hooks
- Foundry: Entra Agent ID blueprint and identity, OBO versus app-only flows, **agent-scope role
  assignments** (`.../projects/<p>/agents/<name>`) for endpoint access [V].
  https://learn.microsoft.com/en-us/azure/foundry/concepts/rbac-foundry

### B.8 Gateways with per-tool RBAC

- agentgateway (CEL on `jwt.*` and `mcp.tool.name`, hides from `tools/list`) [V]; Kong AI Gateway
  3.13 MCP Tool ACLs (`default_acl` plus per-tool `acl.allow/deny` by Consumer or Consumer Group,
  filters `tools/list`) [V] https://konghq.com/blog/product-releases/mcp-tool-acls-ai-gateway ;
  Microsoft MCP Gateway (Kubernetes reverse proxy, Entra ID, adapters with `requiredRoles`) [V]
  https://microsoft.github.io/mcp-gateway/ ; LiteLLM `tool_permission` guardrail (regex allow/deny,
  pre-call strips tools, post-call validates calls, "block" or "rewrite" modes) [V]
  https://docs.litellm.ai/docs/proxy/guardrails/tool_permission
- AWS AgentCore: a valid JWT alone grants every tool behind a gateway, so tool-level control comes
  from **AgentCore Policy (Cedar)**, evaluated on both `tools/list` and `tools/call`, for example
  `permit(principal, action == AgentCore::Action::"DeployCI___invoke", resource) when {
  principal.getTag("groups").contains(...) && context.input.environment == "staging" }` [V].
  https://aws.amazon.com/blogs/machine-learning/govern-ai-agent-tool-access-with-amazon-bedrock-agentcore-gateway/
  Resource-based policies with actions `InvokeAgentRuntime`, `InvokeAgentRuntimeForUser`,
  `GetAgentCard`, `InvokeGateway` [V].
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html
  Classic Bedrock Agents: `bedrock:InvokeAgent` on `agent-alias/*`, `GetAgent` / `UpdateAgent` /
  `PrepareAgent` on `agent/*` [V].

### B.9 Summary matrix

| Framework | Enforcement point | User identity at that point | Policy nature |
|---|---|---|---|
| LangGraph Platform | server handlers + DB filter, before the run | yes (`ctx.user`) | dynamic code |
| Google ADK | `before_tool_callback` (call time) | yes (`tool_context.user_id`) | dynamic |
| OpenAI Agents SDK | `is_enabled` (list time) + tool guardrails (call time) + MCP filter | via `RunContextWrapper.context` | dynamic |
| CrewAI | `@before_tool_call` (call time) | not in context; closure only | dynamic |
| Pydantic AI | `prepare` / `FilteredToolset` (per step, list time) | `ctx.deps` | dynamic |
| smolagents | none built in | n/a | n/a |
| Microsoft Agent Framework | function middleware / Agent Hooks (call time) | via kwargs or session | dynamic, fail-closed |
| Gateways (agentgateway, Kong, AgentCore Policy) | proxy, `tools/list` and `tools/call` | JWT claims or consumer | static config (CEL, ACL, Cedar) |

AK's six adapters map onto this as follows: OpenAI (`is_enabled`, tool guardrails), Pydantic AI
(`prepare`, `filtered`), ADK (`before_tool_callback`) and CrewAI (`@before_tool_call`) each expose
a native gate AK could wire from one core policy; LangGraph has no per-tool gate in the graph
itself (the Platform's auth is a server feature) so AK would filter at `LangGraphToolBuilder.bind`
or wrap the `StructuredTool`; smolagents has nothing, so AK would wrap `Tool.forward`. None of this
exists in AK today (`ak-current-state.md`, section 5).

## C. Agent-to-tool access: the four patterns

1. **Static bind-time tool set per agent** (kagent `toolNames`, CrewAI/ADK/OpenAI `tools=[...]`,
   Databricks function grants, Snowflake tool privileges, and AK's `SystemToolFactory` today).
   Auditable, cache-friendly (the MCP spec recommends deterministic tool ordering for prompt-cache
   hits [V]), simplest mental model. Cannot vary by user; one agent per audience.
2. **Dynamic per-run filtering by principal** (OpenAI `is_enabled`, MCP dynamic tool filters,
   Pydantic `prepare` / `filtered`, LiteLLM pre-call). The MCP 2026-07-28 spec permits it: the
   `tools/list` set "MUST NOT vary per-connection [but] MAY vary by the authorization presented on
   the request, for example, returning only the tools the caller's granted scopes permit" [V].
   https://modelcontextprotocol.io/specification/2026-07-28/server/tools Least-privilege prompt, no
   wasted tokens. But hidden tools are not a security boundary: OpenAI's docs say `is_enabled` "does
   not replace authorization checks" [V], and Answer.AI shows models can hallucinate and
   successfully invoke functions that exist in the namespace but were not offered, so every call
   must be validated against the offered set [V]. https://www.answer.ai/posts/2026-01-20-toolcalling.html
3. **Call-time deny with a message back to the model** (ADK dict return, CrewAI "blocked by hook"
   string, OpenAI `reject_content`, MAF Agent Hooks control error, LiteLLM rewrite). MCP guidance:
   tool execution errors (`isError: true`) "SHOULD" be given to the model to enable
   self-correction [V]; Anthropic's tool-design guidance recommends error responses that "clearly
   communicate specific and actionable improvements, rather than opaque error codes" [V].
   https://www.anthropic.com/engineering/writing-tools-for-agents Catches argument-level (ABAC)
   denials that visibility cannot express. Leaks tool existence, wastes turns, must be fail-closed
   (MAF treats interceptor failure as deny). This is also AK's established tool-boundary behaviour:
   OKF `write_kb` returns an actionable string rather than raising
   (`knowledgebase/okf/tools.py:150-152`).
4. **Gateway enforcement** (agentgateway CEL, Kong ACLs, AgentCore Policy, Microsoft MCP Gateway).
   Framework-agnostic, one policy language, filters both list and call. Requires the user identity
   to reach the gateway (OBO or token exchange) and cannot see in-process function tools.

Who does what: ADK 3 only; OpenAI 2 + 3 (+ approval); Pydantic 2; CrewAI 3; MAF 3 (fail-closed);
LangGraph Platform resource-level (agent, thread) rather than tool-level; agentgateway, Kong and
AgentCore 2 + 3 at the gateway; Databricks, Snowflake and ServiceNow check data-platform privileges
at call time under the invoking user's role. Published guidance converges on **filter visibility for
UX and token economy, but authorize every call** (MCP spec, OpenAI docs, Answer.AI, Oso academy
[V] https://www.osohq.com/academy/authorization-in-llm-applications). A denied call should produce
an `isError`-style tool result naming the policy reason, not an exception that kills the run,
unless the failure is in the enforcement layer itself.

## D. Access-level vocabularies across products

| Vendor | Level names | What each allows | Tag |
|---|---|---|---|
| Copilot Studio | Owner; Editor (collaborative author); User ("can use the agent"); Analytics viewer; Agent viewer | Owner: everything incl. share and delete. Editor: view, edit, configure, share, publish, not delete. User: chat only (users, security groups, everyone). Analytics viewer: read analytics. Agent viewer: view and run evaluations | [V] https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-share-bots |
| Microsoft Foundry | Foundry Agent Consumer; Foundry User; Foundry Project Manager; Foundry Account Owner; Foundry Owner | Consumer: interact with agent endpoints only (assignable at agent scope). User: build and develop plus interact. Project Manager: publish agents, assign Foundry User. Owner: all | [V] rbac-foundry |
| Google Gemini Enterprise / Agent Engine | Agent User (`agentUser`) vs `agentspaceAdmin`; Agent Engine `aiplatform.reasoningEngines.query`; predefined `aiplatform.viewer` / `user` / `admin` | agentUser: query and run, no edit; admin: configure, share, transfer ownership; `reasoningEngines.query`: execute one agent | [V] roles, [U] per-role tables |
| Salesforce Agentforce | permission set "Agent Access > Enabled Agents"; "Manage AI Agents" | enabled: chat; Manage: build and edit | [V]/[U] |
| LangSmith workspace | Viewer, Editor, Admin (+ org roles); custom roles from `resource:action` permissions | Viewer: read-only; Editor: all but delete runs and member management; Admin: full. Per-user agent visibility is separate, via custom-auth metadata filters | [V] https://docs.langchain.com/langsmith/rbac |
| Databricks Unity Catalog | READ METADATA, EXECUTE, MANAGE, ALL PRIVILEGES, ownership | READ METADATA: see and discover; EXECUTE: invoke; MANAGE: grant, revoke, transfer, delete | [V] |
| Snowflake Cortex Agent | USAGE, MODIFY, MONITOR, OWNERSHIP (+ CREATE AGENT on schema) | USAGE: run; MODIFY: update; MONITOR: view threads, logs, traces; OWNERSHIP: full | [V] |
| AWS Bedrock Agents / AgentCore | IAM `bedrock:GetAgent`, `InvokeAgent` (alias), `UpdateAgent`, `PrepareAgent`; AgentCore `InvokeAgentRuntime`, `InvokeAgentRuntimeForUser`, `GetAgentCard`; registry personas Administrator / Publisher / Curator / Consumer | Get: read; Invoke: execute; Update, Prepare: write; Consumer: browse approved only | [V] |
| ServiceNow | `sn_aia_user` / `sn_aia_developer` / `sn_aia.admin`; per-agent discover-and-use roles | user: interact; developer: build; admin: manage and deploy | [U] |
| A2A registry proposal (#741) | Administrator, Catalog Manager, User, Viewer | Viewer: see listings; User: entitled use; Catalog Manager: publish and curate | [V] |

**Naming takeaway.** A four-step scale of **read** (see the record or card: Databricks READ
METADATA, Copilot Agent viewer), **execute** (invoke: Databricks EXECUTE, Snowflake USAGE, Foundry
Agent Consumer, `reasoningEngines.query`, `bedrock:InvokeAgent`), **write** (edit, publish,
version: Copilot Editor, Snowflake MODIFY, `bedrock:UpdateAgent`) and **admin** (grant, transfer,
delete: Databricks MANAGE, Snowflake OWNERSHIP, Copilot Owner) maps onto every product surveyed.
Only Snowflake's MONITOR and Copilot's Analytics viewer add an observability level between read and
write, worth keeping as an optional fifth level if AK exposes traces or threads per agent. For
agent-to-tool the surveyed systems use a single boolean grant (tool allowed or not), optionally with
argument-level conditions (Cedar), so no level scale is needed there. The user's brief names the
scale "read, write, admin"; the survey argues for splitting "execute" out of "write", because every
product treats "may chat with the agent" and "may change the agent" as different grants.
