# Changelog

All notable user-visible changes to Open Agent Kernel (OAK), newest release first. It covers
everything that ships under one `vX.Y.Z` tag: the `agentkernel` Python package, the Helm chart, the
Terraform modules and the bundled agent skills.

Before 1.0, any release may contain breaking changes; they are always listed under **Breaking
changes**, with what to change to migrate. Each entry links to its issue or pull request. The
[GitHub releases](https://github.com/yaalalabs/agent-kernel/releases) list every merged pull request
and hold the history before 0.9.0.

Each pull request adds its entry as a fragment under `changelog.d/`, and the sections below are
compiled from those fragments when a release is published. See
[Changelog entries](CONTRIBUTING.md#changelog-entries) in CONTRIBUTING.md; do not edit the sections
below by hand.

<!-- towncrier release notes start -->

## [0.10.2](https://github.com/yaalalabs/agent-kernel/releases/tag/v0.10.2) - 2026-11-20

### Breaking changes

- Remove Azure Functions support: the `AzureFunctions` handler and the `agentkernel.azure` module are gone, and the `azure` extra no longer installs `azure-functions`. To migrate, deploy on [Azure Container Apps](https://kernel.yaala.ai/docs/deployment/azure-containerized), which runs on the in-memory queue or as an edge and an agent runner over Service Bus. ([#984](https://github.com/yaalalabs/agent-kernel/issues/984))
- Replace the per-surface agent lists `a2a.agents`, `mcp.agents` and `agui.agents` with `registry.agents.<id>.surfaces` (a config that still sets one fails at startup), return descriptors from `GET /api/v1/agents` as `{"agents": [...], "next_cursor": ...}` instead of a list of names, and remove `Agent.get_a2a_card()` from the framework adapters. A2A card and MCP tool descriptions now come from the agent's declared description, never from its instructions. To migrate, move each list to `registry.agents.<id>.surfaces`, declare descriptions with `Module.describe(...)` or `registry.agents.<id>.description`, and have custom adapters report tools through `get_tool_names()`; see [Agent Registry](https://kernel.yaala.ai/docs/core-concepts/configuration#agent-registry). ([#983](https://github.com/yaalalabs/agent-kernel/issues/983))
- LiveKit: remove `IOHandler.run(gateways=...)` and the `GatewayRunner` export, rename `LiveKitEdgeGateway` to `LiveKitEdgeAdapter`, and move the realtime runner contract from `agentkernel.core.realtime` to `agentkernel.realtime`. To migrate, mount `IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())])`, point the LiveKit project's webhook at `/livekit/webhook`, and import `RealtimeRunner`, `PCM16Resampler` and `EDGE_SAMPLE_RATE` from `agentkernel.realtime`; see [Migrating from v0.9.5](https://kernel.yaala.ai/docs/integrations/livekit#migrating-from-v095). ([#941](https://github.com/yaalalabs/agent-kernel/issues/941))

### Added

- Add an agent registry: every agent has one descriptor (name, version, description, owner, tags, surfaces, skills and tools), set with `Module.describe(...)` or `registry.agents.<id>`, which feeds the agent catalog at `GET /api/v1/agents`, A2A cards, MCP agent tools and the AG-UI listing. Set `registry.type` to `redis`, `valkey` or `dynamodb` to share it across processes. See [Agent Registry](https://kernel.yaala.ai/docs/core-concepts/configuration#agent-registry). ([#983](https://github.com/yaalalabs/agent-kernel/issues/983))
- Approve or deny a paused run from Slack or Telegram with buttons on the message, including a review form (Slack) or a grouped submit (Telegram) when several decisions are needed together; other messaging platforms show the pause as text. See [Human in the Loop](https://kernel.yaala.ai/docs/advanced/human-in-the-loop#from-a-messaging-platform). ([#860](https://github.com/yaalalabs/agent-kernel/issues/860))
- Accept file uploads on broker queue transports (SQS, Kafka, NATS, Pub/Sub, Service Bus): the REST edge saves each file to the multimodal attachment store and queues only its ID, and `POST /api/v1/chat-multipart` is served on every transport. This needs `multimodal.enabled: true` with a shared store; see [Files on a queue transport](https://kernel.yaala.ai/docs/api/rest-api#files-on-a-queue-transport). ([#979](https://github.com/yaalalabs/agent-kernel/issues/979))
- LiveKit: host one edge and one session per room, started and ended by LiveKit's signed room webhooks; override `should_start` on `LiveKitLifecycleAdapter` to choose which rooms get an agent. See [LiveKit](https://kernel.yaala.ai/docs/integrations/livekit). ([#941](https://github.com/yaalalabs/agent-kernel/issues/941))
- AWS Lambda: routes registered with `Lambda.register` can use API Gateway path parameters such as `/schedules/{task_id}`, read from `event["pathParameters"]`. See [Path and query parameters](https://kernel.yaala.ai/docs/deployment/aws-serverless#path-and-query-parameters). ([#935](https://github.com/yaalalabs/agent-kernel/issues/935))

### Changed

- Change the default model for attachment description and analysis, thread naming, the OpenAI guardrail and the DeepEval and Opik test judges from `gpt-4o` and `gpt-4o-mini` to `gpt-6-luna`, ahead of OpenAI retiring the older models on 2027-01-14; set a model explicitly to keep another one. The minimum `litellm` rises to 1.100.3 (below 1.106 in the `langgraph` and `adk` extras) and the minimum `opik` to 1.10.0. ([#929](https://github.com/yaalalabs/agent-kernel/issues/929))

### Fixed

- Google ADK realtime: ending a call no longer closes the agent's shared toolsets and plugins. ([#941](https://github.com/yaalalabs/agent-kernel/issues/941))

## [0.10.1](https://github.com/yaalalabs/agent-kernel/releases/tag/v0.10.1) - 2026-11-16

### Breaking changes

- Terraform (GCP and Azure): providers are pinned to exact versions (`google` and `google-beta` 8.8.1, `azurerm` 5.11.0), the Terraform CLI must be between 1.9.5 and 1.16.7, and the Azure modules move from azurerm 4.x to 5.x, which an existing stack cannot undo. To migrate, use a Terraform CLI in that range, align your root module's provider constraints with the pins, and plan the azurerm 5.x upgrade before applying it to an Azure stack. ([#938](https://github.com/yaalalabs/agent-kernel/issues/938))
- Terraform (GCP): `queue_mode` now defaults to `true` in the serverless and containerized modules, so an existing deployment switches to the Pub/Sub queue topology on upgrade. To migrate, set `queue_mode = false` to keep the single-service deployment. ([#923](https://github.com/yaalalabs/agent-kernel/issues/923))

### Added

- Add queue mode on GCP: the new `pubsub` queue transport (`pubsub` extra, `execution.queues.pubsub` block) connects a Cloud Run edge service to a push-driven agent-runner service (`CloudRunAgentRunner`), with Memorystore Redis for replies, and the Terraform modules provision the topics, subscriptions, dead-letter topics and runner service. See [Queue Mode](https://kernel.yaala.ai/docs/deployment/gcp-serverless#queue-mode). ([#923](https://github.com/yaalalabs/agent-kernel/issues/923))
- Add queue mode on Azure Container Apps: the new `servicebus` queue transport (in the `azure` extra) connects an edge app to an agent-runner app scaled by KEDA, with Redis for replies; set `queue_mode = true` in the `ak-azure/containerized` Terraform module. See [Queue Mode (Service Bus)](https://kernel.yaala.ai/docs/deployment/azure-containerized#queue-mode-service-bus). ([#955](https://github.com/yaalalabs/agent-kernel/issues/955))

### Changed

- Kafka transport: when sessions are not on Redis or Valkey, delivery bookkeeping now uses a configured Redis or Valkey response store, so it survives a restart, before falling back to process memory. ([#923](https://github.com/yaalalabs/agent-kernel/issues/923))

## [0.10.0](https://github.com/yaalalabs/agent-kernel/releases/tag/v0.10.0) - 2026-11-13

### Breaking changes

- Remove `execution.mode: stream`: how a reply is delivered is now set separately with `execution.message_type` (`complete` or `delta`), and `stream` fails at startup with a migration message. To migrate, use `execution.mode: rest_sync` with `message_type: delta` for SSE over REST, or `execution.mode: async` with `message_type: delta` for chunks over WebSocket (Terraform: `execution_mode = "async"` and `message_type = "delta"`; Helm chart: `execution.messageType=delta`). See [Queue Mode Guide](https://kernel.yaala.ai/docs/advanced/queue-mode-guide). ([#854](https://github.com/yaalalabs/agent-kernel/issues/854))
- Remove the `agentkernel.auth` package (`AuthValidator`, `Authoriser`, the JWT validators), `RESTAPI.add_auth_handlers`, and the `auth_validator` and `authoriser` arguments of the API, gateway, thread, schedule and AG-UI handlers. Chat requests that carry `user_id` are rejected with 400, and threads and scheduled tasks belong to the authenticated principal. To migrate, configure an `identity` block, drop `user_id` from request bodies, and recreate threads and scheduled tasks created before the upgrade; see [Migrating from `agentkernel.auth`](https://kernel.yaala.ai/docs/advanced/identity-and-access#migrating-from-agentkernelauth). ([#918](https://github.com/yaalalabs/agent-kernel/issues/918))
- A2A and agent-exposing MCP (`a2a.enabled`, or `mcp.enabled` with `mcp.expose_agents`) now run requests through the queue pipeline instead of inside the web process, so `RESTAPI.run(handlers=[...])`, `RESTAPI.run()` on a broker transport, `AWSRestAPI`, `AWSWebsocketAPI` and `ECSIOHandler` refuse to start with them enabled. On a broker transport they also need a shared response store (`redis`, `valkey` or `dynamodb`). To migrate, start the app with `RESTAPI.run()` on the in-memory transport or with `IOHandler.run(...)`, and load the agent modules in the IO process as well as the agent runner. ([#829](https://github.com/yaalalabs/agent-kernel/issues/829))
- A2A: the surface moves to a2a-sdk 1.x and serves A2A 1.0 only; the 0.3 routes (`/a2a/{agent}/v1/...`) return 404 and agent cards drop the 0.3 `url` and `preferredTransport` keys. To migrate, call agents with an a2a-sdk 1.x client and port any code that imports a2a 0.3 types; see [Migrating from A2A 0.3](https://kernel.yaala.ai/docs/api/a2a-server#migrating-from-a2a-03). ([#842](https://github.com/yaalalabs/agent-kernel/issues/842))
- Google ADK: the `adk` extra now requires google-adk 2.7.0 or later, so ADK 1.x is no longer supported. To migrate, upgrade your ADK agents to google-adk 2.7 or later; see [Google ADK](https://kernel.yaala.ai/docs/frameworks/google-adk). ([#808](https://github.com/yaalalabs/agent-kernel/issues/808), [#845](https://github.com/yaalalabs/agent-kernel/issues/845))
- Sandbox: package installs are denied unless the profile declares `policy.package_install`; before, an install request ran without a permission check. To migrate, add `package_install: {ecosystems: [python]}` to each profile that installs packages and, with the queue broker, upgrade the workers before the agent pods; see [Permissions: languages and package installs](https://kernel.yaala.ai/docs/advanced/sandbox#permissions-languages-and-package-installs). ([#813](https://github.com/yaalalabs/agent-kernel/issues/813))

### Added

- Add identity and access: an `identity` block selects one provider (`oidc` for Auth0, Keycloak, Okta and other OpenID Connect issuers, `cognito`, `entra`, `firebase`, `static`, or your own class) that authenticates every surface, and tools and hooks read the caller as a `Principal` (`ToolContext.get().principal`, `Session.get_principal()`). The token providers need the new `auth` extra. See [Identity and Access](https://kernel.yaala.ai/docs/advanced/identity-and-access). ([#918](https://github.com/yaalalabs/agent-kernel/issues/918))
- Add Microsoft Agent Framework support (`maf` extra, `MAFModule`), with streaming, sessions, structured output, native run options, human-in-the-loop approvals and tracing on all four tracing backends. See [Microsoft Agent Framework](https://kernel.yaala.ai/docs/frameworks/microsoft-agents). ([#789](https://github.com/yaalalabs/agent-kernel/issues/789))
- Add Claude Agent SDK support (`claude` extra, `ClaudeModule`): agents run on Anthropic's Claude Code harness with its built-in tools and subagents, with streaming, session persistence, multimodal input, structured output, human-in-the-loop approvals (`needs_approval=True` on `ClaudeToolBuilder.bind()`) and tracing. See [Claude Agent SDK](https://kernel.yaala.ai/docs/frameworks/claude-agent-sdk). ([#833](https://github.com/yaalalabs/agent-kernel/issues/833))
- Add A2UI support: with `a2ui.enabled: true`, a JSON reply from an agent listed in `a2ui.agents` reaches the client labelled `application/a2ui+json` over REST, MCP, AG-UI and A2A (as a data part), and conversation threads keep the structured reply. See [A2UI](https://kernel.yaala.ai/docs/advanced/a2ui). ([#719](https://github.com/yaalalabs/agent-kernel/issues/719), [#817](https://github.com/yaalalabs/agent-kernel/issues/817), [#842](https://github.com/yaalalabs/agent-kernel/issues/842))
- AG-UI: mount `AGUIPipelineRequestHandler` with `IOHandler.run(...)` to run AG-UI agents on the queue pipeline with the same routes and events; Redis and Valkey response stores share the streamed replies across processes. See [Running the agent off the web tier](https://kernel.yaala.ai/docs/integrations/agui#running-the-agent-off-the-web-tier). ([#755](https://github.com/yaalalabs/agent-kernel/issues/755))
- Realtime voice: a call can hand off between agents with the OpenAI Agents SDK's handoffs or Google ADK's transfers, and in LiveKit each agent joins the room as its own participant. LiveKit edges also gain transcript, agent-change and error hooks, live captions, and an overridable `opening_prompt`. See [Multi-agent handoffs](https://kernel.yaala.ai/docs/integrations/livekit#multi-agent-handoffs). ([#808](https://github.com/yaalalabs/agent-kernel/issues/808), [#845](https://github.com/yaalalabs/agent-kernel/issues/845))
- Read agent, LLM and tool spans back from Langfuse, Logfire, OpenLLMetry or CloudWatch with `Trace.fetch_spans()` and `Trace.fetch_traces()`, using one provider-neutral filter and including token usage, to evaluate production traffic. See [Fetching Spans Back](https://kernel.yaala.ai/docs/advanced/traceability#fetching-spans-back). ([#812](https://github.com/yaalalabs/agent-kernel/issues/812))
- Add a `kubernetes` secret provider (`secret.provider.type: kubernetes`) that reads keys from Kubernetes Secrets mounted into the pod and picks up rotated values without a restart. Helm chart: the new `secretStore.enabled` and `secretStore.secrets[]` values mount the listed Secrets into the tier that runs the agents. See [Secret Resolution](https://kernel.yaala.ai/docs/advanced/secrets). ([#781](https://github.com/yaalalabs/agent-kernel/issues/781))
- Credentials OAK reads itself (Slack, Gmail, WhatsApp, Messenger, Instagram, Telegram, Teams, LiveKit, Walled AI, Neo4j, Starburst, E2B, Daytona, and the OpenAI and Google keys of the realtime runners) now resolve through `SecretManager`, so they can live in SSM Parameter Store or Kubernetes Secrets; a set environment variable still wins. Terraform: in queue mode, `ssm_enabled` also grants read access to the AWS request handler, response handler and REST service. See [Framework-owned credentials](https://kernel.yaala.ai/docs/advanced/secrets#framework-owned-credentials). ([#873](https://github.com/yaalalabs/agent-kernel/issues/873))
- Sandbox: a profile's `policy` can restrict `run_code` languages (`languages`) and allow package installs per ecosystem (`package_install`), agents get an `install_packages` tool when a profile allows installs, and `docker`, `kubernetes`, `ec2_ssm` and `daytona` run languages other than Python through `language_runtimes` (`e2b` through `languages`). See [Language runtimes](https://kernel.yaala.ai/docs/advanced/sandbox#language-runtimes). ([#813](https://github.com/yaalalabs/agent-kernel/issues/813))
- Conversation threads record human-in-the-loop pauses and the decisions that resumed them as structured messages, on direct, streaming and queued runs. See [In conversation threads](https://kernel.yaala.ai/docs/advanced/human-in-the-loop#in-conversation-threads). ([#827](https://github.com/yaalalabs/agent-kernel/issues/827))

### Changed

- Every dependency and extra now has an upper version bound, and several minimums rise to patched or required releases, including litellm 1.95.0, langgraph 1.2.14, PyJWT 2.15.0, aiohttp 3.14.4, fastmcp 3.4.10, logfire 4.31.0 and smolagents 1.26.0. The unused `deprecated` dependency is removed. ([#919](https://github.com/yaalalabs/agent-kernel/issues/919), [#943](https://github.com/yaalalabs/agent-kernel/issues/943), [#825](https://github.com/yaalalabs/agent-kernel/issues/825), [#833](https://github.com/yaalalabs/agent-kernel/issues/833))
- Errors about a missing optional extra now suggest `uv add "agentkernel[<extra>]"` instead of `pip install`. ([#904](https://github.com/yaalalabs/agent-kernel/issues/904))

### Deprecated

- Sandbox: a custom `Sandbox.install_packages` override without the new `ecosystem` and `timeout` parameters keeps working for one more minor release through a shim that logs a deprecation warning. Update overrides to `install_packages(packages, ecosystem="python", timeout=None)`. ([#813](https://github.com/yaalalabs/agent-kernel/issues/813))

### Fixed

- Cap openai-agents below 0.21 in the `openai` extra to avoid event-loop-closed errors. ([#822](https://github.com/yaalalabs/agent-kernel/issues/822))
- Session debug logging no longer writes the whole cache on every access; cache operations log only the key they touch. ([#815](https://github.com/yaalalabs/agent-kernel/issues/815))
- A chat request that carries only a `resume` decision, with no prompt, is accepted on the queue pipeline's chat routes, including the thread chat route. ([#883](https://github.com/yaalalabs/agent-kernel/issues/883))
- Langfuse: traces are flushed after every run on AWS Lambda, including failed runs, so spans are not lost when the function freezes. ([#812](https://github.com/yaalalabs/agent-kernel/issues/812))
- Sandbox: the `e2b` provider's `template` defaults to `code-interpreter-v1` (the old `base` default could not run code), timed-out or cancelled work on `docker` and `kubernetes` is killed with its child processes, and `e2b` and `daytona` installs have a timeout. ([#813](https://github.com/yaalalabs/agent-kernel/issues/813))
- Terraform (AWS): pin the AWS provider to 6.70.0, because 6.69.0 cannot create a Lambda from a local zip package. ([#821](https://github.com/yaalalabs/agent-kernel/issues/821))
- Helm chart: `Chart.yaml` carries each release's `version` and `appVersion`, so an install from a repository checkout gets the right version labels. ([#855](https://github.com/yaalalabs/agent-kernel/issues/855))

### Security

- Public chat routes reject client-supplied `requests`, `scheduled_task_id` and `scheduled_time` fields, which only the queue and the scheduler may set. ([#926](https://github.com/yaalalabs/agent-kernel/issues/926))

## [0.9.5](https://github.com/yaalalabs/agent-kernel/releases/tag/v0.9.5) - 2026-10-09

### Added

- Add a LiveKit realtime voice integration: `LiveKitEdgeGateway` joins a LiveKit room and connects OpenAI Agents SDK and Google ADK realtime agents to it through the new `realtime` execution mode, with barge-in and function tools, on every queue transport. Install it with the `livekit` extra; the AWS containerized Terraform module accepts `execution_mode = "realtime"`. See [LiveKit](https://kernel.yaala.ai/docs/integrations/livekit). ([#761](https://github.com/yaalalabs/agent-kernel/issues/761))

### Fixed

- Require openai-agents 0.20.0 or later in the `openai` extra, so it resolves together with openai 2.54. ([#806](https://github.com/yaalalabs/agent-kernel/issues/806))

## [0.9.4](https://github.com/yaalalabs/agent-kernel/releases/tag/v0.9.4) - 2026-10-08

### Added

- Add human in the loop: a run can pause for a person's approval or answer and resume from the decision minutes or hours later, on any replica. A paused chat returns HTTP 202 with `status: "PAUSED"` and its interruptions, and the client answers by sending a `resume` block instead of a prompt; this works on the OpenAI Agents SDK, LangGraph, Pydantic AI and Google ADK, over REST, streaming and AG-UI. See [Human in the Loop](https://kernel.yaala.ai/docs/advanced/human-in-the-loop). ([#765](https://github.com/yaalalabs/agent-kernel/issues/765), [#774](https://github.com/yaalalabs/agent-kernel/issues/774))
- Add secret resolution: `SecretManager.current().get("OPENAI_API_KEY")` reads a key from the environment first, then from the configured `secret.provider` (`env`, `aws_ssm` for SSM Parameter Store, or your own class), with an in-process cache. Terraform: the AWS modules gain `ssm_enabled`, which grants the agent tier read access to `/ak/<prefix>/*` and injects `AK_SECRET__PREFIX`. See [Secret Resolution](https://kernel.yaala.ai/docs/advanced/secrets). ([#750](https://github.com/yaalalabs/agent-kernel/issues/750))
- `Module.run_options` accepts a factory that computes an agent's framework-native run options on every run from the session and requests, merged over the static options. See [Native run options](https://kernel.yaala.ai/docs/core-concepts/runner#native-run-options). ([#759](https://github.com/yaalalabs/agent-kernel/issues/759))
- AWS Lambda: run the Slack, Teams, WhatsApp, Messenger, Instagram and Telegram integrations on Lambda, with webhooks received by the request handler and replies delivered by the response handler; the Lambda authorizer lets the signed webhook routes through. See [Messaging integrations](https://kernel.yaala.ai/docs/deployment/aws-serverless#messaging-integrations). ([#768](https://github.com/yaalalabs/agent-kernel/issues/768))
- Add AWS CloudWatch tracing (`trace.type: cloudwatch`, `cloudwatch` extra): spans are sent over OTLP to the regional X-Ray endpoint, signed with SigV4 and with no collector, and appear in CloudWatch Transaction Search and GenAI Observability. See [Traceability](https://kernel.yaala.ai/docs/advanced/traceability). ([#794](https://github.com/yaalalabs/agent-kernel/issues/794))
- Add the `jev` test evaluator, which grades `llm` mode tests with TypeSafe's hosted JEV judge (`jev` extra, `TYPESAFE_API_KEY`). See [CLI Testing](https://kernel.yaala.ai/docs/testing/cli-testing). ([#775](https://github.com/yaalalabs/agent-kernel/issues/775))

### Changed

- Google ADK: every run now enables ADK resumability, which pausing needs, so in multi-agent ADK apps a turn that follows a function response goes back to the sub-agent that made the call, and ADK sessions grow. Single-agent apps are unaffected; see [Google ADK](https://kernel.yaala.ai/docs/frameworks/google-adk). ([#774](https://github.com/yaalalabs/agent-kernel/issues/774))

### Fixed

- LangGraph: `interrupt()` can now be resumed (a resume used to re-run the interrupting node from the start), and LangGraph sessions can be stored on shared backends such as Redis, Valkey and DynamoDB, where pickling them used to fail. ([#774](https://github.com/yaalalabs/agent-kernel/issues/774))

## [0.9.3](https://github.com/yaalalabs/agent-kernel/releases/tag/v0.9.3) - 2026-09-25

### Breaking changes

- Knowledge bases: `KnowledgeBase.read()` is removed and a backend declares the operations it supports with `KnowledgeCapabilities`; the `read_kb` tool routes to `search()` or `query()` itself. The bundled backends are unchanged. To migrate a custom `KnowledgeBase` subclass, pass `capabilities=KnowledgeCapabilities(...)` to `super().__init__()` and rename `read()` to `search()` (or implement `query()` for a query language); see [Custom KnowledgeBase Adapters](https://kernel.yaala.ai/docs/advanced/knowledge-bases#custom-knowledgebase-adapters). ([#687](https://github.com/yaalalabs/agent-kernel/issues/687), [#714](https://github.com/yaalalabs/agent-kernel/issues/714))

### Added

- Add Open Knowledge Format (OKF) knowledge bases: `OKFManager` serves a bundle of markdown documents with YAML frontmatter from a local directory or an S3 prefix, with no database to run, and agents get `search_kb`, `fetch_kb` and `browse_kb` tools where a backend supports them. An `okf` block in `config.yaml` can name consumer, producer and curator agents per bundle, so no `KnowledgeBuilder` code is needed. See [Knowledge Bases](https://kernel.yaala.ai/docs/advanced/knowledge-bases). ([#707](https://github.com/yaalalabs/agent-kernel/issues/707), [#713](https://github.com/yaalalabs/agent-kernel/issues/713), [#714](https://github.com/yaalalabs/agent-kernel/issues/714))
- Pass each framework's own run options to an agent with `Module.run_options(agent, ...)`, for example OpenAI `hooks`, `run_config` and `max_turns`, LangGraph `config`, ADK `plugins`, Pydantic AI `usage_limits`, CrewAI `step_callback` and smolagents `max_steps`; keys OAK manages itself are rejected. See [Native run options](https://kernel.yaala.ai/docs/core-concepts/runner#native-run-options). ([#756](https://github.com/yaalalabs/agent-kernel/issues/756))

### Changed

- Knowledge bases: `search_kb` is offered whenever a registered backend supports search, so a Chroma setup now gives the model five tools instead of four. ([#714](https://github.com/yaalalabs/agent-kernel/issues/714))

### Fixed

- OpenAI Agents SDK: `OpenAISession.get_items(limit)` returns the latest items instead of the oldest, so agents using `SessionSettings(limit=N)` see recent history. ([#748](https://github.com/yaalalabs/agent-kernel/issues/748))

## [0.9.2](https://github.com/yaalalabs/agent-kernel/releases/tag/v0.9.2) - 2026-09-22

### Breaking changes

- Messaging integrations (Slack, WhatsApp, Messenger, Instagram, Telegram, Teams, Gmail) now run on the queue pipeline as inbound and outbound adapter pairs, so a slow agent no longer exceeds a platform's delivery timeout, and the `Agent<Platform>RequestHandler` classes are removed. To migrate, mount `IOHandler.run(handlers=[WebhookRESTRequestHandler(SlackInboundAdapter())])` (likewise for the other webhook platforms), run Gmail with `PollerRunner.run(GmailInboundAdapter())`, and set `multimodal.enabled: true` with a shared store if messages carry attachments; see [Integrations](https://kernel.yaala.ai/docs/integrations/overview). ([#680](https://github.com/yaalalabs/agent-kernel/issues/680))
- Terraform: the `product_alias`, `env_alias` and `module_name` variables are replaced by one required `prefix` in every AWS, Azure and GCP module. To migrate, set `prefix` to the old `<product>-<env>-<module>` value (for example `myapp-dev-chat`) to keep resource names; some AWS serverless per-handler names (IAM roles, Lambda packages, ECR repositories) drop the repeated handler name, so Terraform replaces those resources. ([#742](https://github.com/yaalalabs/agent-kernel/issues/742))

### Added

- Conversation threads in queue mode: mount `IOHandler.run(request_handler=ThreadRequestHandler())`, and give the agent-runner process the same `thread` configuration so it can record replies. See [Conversation Threads](https://kernel.yaala.ai/docs/advanced/threads). ([#680](https://github.com/yaalalabs/agent-kernel/issues/680))
- Messaging integrations: replace a platform's reply delivery by setting its `outbound_adapter` to the dotted path of your own `OutboundAdapter` subclass, or its parsing by passing your own `InboundAdapter` subclass to the handler. ([#680](https://github.com/yaalalabs/agent-kernel/issues/680))
- Terraform (AWS): the serverless and containerized modules accept existing security group IDs instead of always creating new security groups. ([#715](https://github.com/yaalalabs/agent-kernel/issues/715))

### Fixed

- Streamed replies on the queue pipeline and on AWS Lambda and ECS reach the client as the agent produces them, instead of all at once when the run ends. ([#745](https://github.com/yaalalabs/agent-kernel/issues/745))

## [0.9.1](https://github.com/yaalalabs/agent-kernel/releases/tag/v0.9.1) - 2026-09-16

### Breaking changes

- Post-hooks: `on_stream_chunk(..., delta)` is replaced by `on_stream_event(..., event)`, and a hook that still defines `on_stream_chunk` is never called, without an error. To migrate, rename the method, take the `event` argument, return `event` to pass it on (or `event.model_copy(update={"content": new_text})` to rewrite its text) and `None` to drop it; see [Hooks](https://kernel.yaala.ai/docs/integrations/hooks). ([#678](https://github.com/yaalalabs/agent-kernel/issues/678))

### Added

- Streaming post-hooks see every stream event, including reasoning and tool call names, arguments and results, can return a list to emit several events in place of one, and can raise `StreamHalt` to end a streamed run with an error the client receives. ([#678](https://github.com/yaalalabs/agent-kernel/issues/678))
- Add the `opik` test evaluator (`evaluator: opik`, `opik` extra) alongside DeepEval. See [CLI Testing](https://kernel.yaala.ai/docs/testing/cli-testing). ([#717](https://github.com/yaalalabs/agent-kernel/issues/717))

### Fixed

- Helm chart: the chart is published to `oci://ghcr.io/yaalalabs/charts/agent-kernel` with every release, versioned to match, and the docs and the `ak-cloud-deploy` skill install that pinned chart instead of a repository checkout. ([#729](https://github.com/yaalalabs/agent-kernel/issues/729))
- AWS ECS: `ECSIOHandler.run(auth_validator=...)` now protects the REST routes in queue mode; it used to apply only to WebSocket connections. ([#735](https://github.com/yaalalabs/agent-kernel/issues/735))

## [0.9.0](https://github.com/yaalalabs/agent-kernel/releases/tag/v0.9.0) - 2026-09-02

### Breaking changes

- Conversation threads are enabled by mounting `AgentThreadRequestHandler` instead of by the presence of a `thread` block, the in-memory store type is renamed from `memory` to `in_memory`, and thread classes move to `agentkernel.thread` (`Authoriser` to `agentkernel.auth`). Only the thread handler records threads and requires `user_id`; the plain REST handler and the AWS Lambda, ECS and Azure adapters no longer record them. To migrate, run `RESTAPI.run(handlers=[AgentThreadRequestHandler()])`, change `thread.type: memory` to `in_memory`, and update imports; see [Conversation Threads](https://kernel.yaala.ai/docs/advanced/threads). ([#613](https://github.com/yaalalabs/agent-kernel/issues/613), [#614](https://github.com/yaalalabs/agent-kernel/issues/614), [#632](https://github.com/yaalalabs/agent-kernel/issues/632))
- `execution.queues.type` is required whenever queue settings are present, including when a deployment injects `AK_EXECUTION__QUEUES__*` environment variables, as the AWS Terraform modules do with `queue_mode = true`; it is no longer inferred from a queue URL. To migrate, add `execution.queues.type: sqs` (or the transport you use) to `config.yaml`; see [Queue Mode Guide](https://kernel.yaala.ai/docs/advanced/queue-mode-guide). ([#646](https://github.com/yaalalabs/agent-kernel/issues/646))
- Streaming (`execution.mode: stream`) now sends typed events: frames carry an `event` object, `delta` appears only on text frames, and the stream ends with a separate `{"done": true}` frame. A custom `Runner.stream()` must yield `StreamEvent` objects from `agentkernel.core.event` instead of strings. To migrate, have clients check for the `delta` key instead of expecting it in every frame, and update custom runners; see [Streaming](https://kernel.yaala.ai/docs/api/rest-api#streaming). ([#642](https://github.com/yaalalabs/agent-kernel/issues/642), [#650](https://github.com/yaalalabs/agent-kernel/issues/650), [#655](https://github.com/yaalalabs/agent-kernel/issues/655), [#656](https://github.com/yaalalabs/agent-kernel/issues/656))
- Test framework: DeepEval replaces Ragas, the modes are renamed (`fuzzy` to `score`, `judge` to `llm`, and `Mode.FUZZY` and `Mode.JUDGE` to `Mode.SCORE` and `Mode.LLM`), the `judge:` block and `AK_TEST__JUDGE__*` variables become `llm:` and `AK_TEST__LLM__*`, and thresholds move from 0-100 to 0.0-1.0. A leftover `judge:` block is ignored without an error, and `score` mode is an exact match with no partial credit. To migrate, rename the modes, the block and the variables and rescale thresholds; see [Testing](https://kernel.yaala.ai/docs/testing/overview). ([#644](https://github.com/yaalalabs/agent-kernel/issues/644))
- Remove the `QueueHandler` base class, move `QueueConsumer` to `agentkernel.deployment.aws.core.raw_queue_consumer` as `RawQueueConsumer`, and rename `ResponseDBHandler` to `ResponseStoreFactory`. To migrate, use the `agentkernel.pipeline.transport` API for queue access; `SQSHandler` callers and `ECSSQSConsumer` and `LambdaSQSConsumer` subclasses are unaffected. ([#630](https://github.com/yaalalabs/agent-kernel/issues/630))
- Chat requests: `schedule`, `scheduled_task_id` and `scheduled_time` are now reserved fields instead of free-form context passed to the agent. To migrate, rename any context fields your clients send under those names. ([#638](https://github.com/yaalalabs/agent-kernel/issues/638))
- AWS ECS queue mode: `rest_sync` and `rest_async` error replies return their HTTP 4xx or 5xx status instead of 200 with an error body, matching the other deployment modes. To migrate, handle error status codes in clients that read errors from the body of a 200 response. ([#632](https://github.com/yaalalabs/agent-kernel/issues/632))

### Added

- Add a queue execution pipeline with pluggable transports, chosen by `execution.queues.type`: `in_memory` (a bare `RESTAPI.run()` now runs the whole pipeline in one process), `sqs`, `kafka` (`kafka` extra) and `nats` for NATS JetStream (`nats` extra), each with per-session ordering, bounded retries and deduplication. `execution.response_store.type` also accepts a dotted path to your own store. See [Queue Mode Guide](https://kernel.yaala.ai/docs/advanced/queue-mode-guide). ([#621](https://github.com/yaalalabs/agent-kernel/issues/621), [#630](https://github.com/yaalalabs/agent-kernel/issues/630), [#633](https://github.com/yaalalabs/agent-kernel/issues/633))
- Helm chart: add the `agent-kernel` chart for Kubernetes, which runs the queue pipeline as io-handler, agent-runner and WebSocket gateway tiers over NATS, Kafka or SQS, with KEDA autoscaling, dev, bare-metal and EKS value profiles, and air-gapped installs. WebSocket replies reach clients through the new `WebSocketGateway` tier, which follows reconnects across pods. See [On-Prem Kubernetes](https://kernel.yaala.ai/docs/deployment/onprem-kubernetes). ([#651](https://github.com/yaalalabs/agent-kernel/issues/651))
- Sandbox: add the `queue` broker flavor, which runs sandbox work on separate workers (`QueueBrokerWorker`) over any queue transport, and the `kubernetes` provider, with one pod per sandbox and optional per-user RBAC impersonation. Helm chart: new `sandboxWorker` tier. See [Sandbox](https://kernel.yaala.ai/docs/advanced/sandbox). ([#699](https://github.com/yaalalabs/agent-kernel/issues/699))
- Add an AG-UI surface: mount `AGUIRequestHandler` to stream an agent's answer, reasoning, tool calls and shared state to an AG-UI frontend, with attachments, for OpenAI Agents SDK, LangGraph, Google ADK and Pydantic AI agents (`agui` extra). See [AG-UI](https://kernel.yaala.ai/docs/integrations/agui). ([#637](https://github.com/yaalalabs/agent-kernel/issues/637), [#642](https://github.com/yaalalabs/agent-kernel/issues/642), [#648](https://github.com/yaalalabs/agent-kernel/issues/648), [#649](https://github.com/yaalalabs/agent-kernel/issues/649), [#650](https://github.com/yaalalabs/agent-kernel/issues/650), [#653](https://github.com/yaalalabs/agent-kernel/issues/653), [#655](https://github.com/yaalalabs/agent-kernel/issues/655), [#656](https://github.com/yaalalabs/agent-kernel/issues/656), [#657](https://github.com/yaalalabs/agent-kernel/issues/657), [#660](https://github.com/yaalalabs/agent-kernel/issues/660))
- Add scheduled and recurring chats: a chat request with a `schedule` block (`at` or `cron`) returns HTTP 202 and runs later, with a management API (`ScheduleRESTRequestHandler`), agent scheduling tools, `local` and `eventbridge` providers, and `in_memory`, `redis`, `valkey` and `dynamodb` stores (`cron` extra). Terraform: the AWS modules gain `enable_scheduling` and `create_dynamodb_schedule_table`. See [Scheduling](https://kernel.yaala.ai/docs/advanced/scheduling). ([#632](https://github.com/yaalalabs/agent-kernel/issues/632), [#638](https://github.com/yaalalabs/agent-kernel/issues/638), [#646](https://github.com/yaalalabs/agent-kernel/issues/646))
- AWS ECS: add a WebSocket mode (`execution_mode = "async"` or `"stream"` in Terraform, `AWSWebsocketAPI` in code) behind a WebSocket API Gateway, in the direct or queue topology, with token streaming and custom routes registered with `AWSWebsocketAPI.register`. See [WebSocket Mode](https://kernel.yaala.ai/docs/deployment/aws-containerized#websocket-mode). ([#567](https://github.com/yaalalabs/agent-kernel/issues/567), [#585](https://github.com/yaalalabs/agent-kernel/issues/585))
- Add a `valkey` thread store, and Terraform flags that provision thread storage: `create_dynamodb_thread_table` on AWS and `create_firestore_thread_collection` on GCP. See [Deploying the Thread Store](https://kernel.yaala.ai/docs/advanced/threads#deploying-the-thread-store). ([#559](https://github.com/yaalalabs/agent-kernel/issues/559))
- `Agent.current()` returns the agent running in the current context, and `Session.get_framework_session()` returns that agent's native framework session from inside a hook or tool, for example to trim conversation history. See [Session](https://kernel.yaala.ai/docs/core-concepts/session#framework-session-access). ([#622](https://github.com/yaalalabs/agent-kernel/issues/622))

### Changed

- The `openai` extra requires openai-agents 0.7.0 or later. ([#679](https://github.com/yaalalabs/agent-kernel/issues/679))

### Fixed

- Microsoft Teams: add the `teams` configuration block (`agent`, `app_id`, `app_password`, `tenant_id`, or `AK_TEAMS__*`), without which the Teams handler failed with `AttributeError`. The agent now runs outside the webhook turn, so slow replies are no longer delivered twice, and a failed token check returns 401 instead of 500. ([#645](https://github.com/yaalalabs/agent-kernel/issues/645))
- Conversation threads: attachments sent as URLs (`http`, `https`, `s3`) or as non-base64 `data:` URIs are no longer stored corrupted; they are recorded by address and passed to the framework adapter, as with threads off. ([#679](https://github.com/yaalalabs/agent-kernel/issues/679))
- Sandbox: the `ec2_ssm` provider waits out SSM's short delay before a command's result is readable, instead of returning an `InvocationDoesNotExist` error to the agent. ([#681](https://github.com/yaalalabs/agent-kernel/issues/681))
- Terraform (AWS): the serverless WebSocket API Gateway no longer fails with an `attempt to get attribute from null value` error when `enable_api_gateway_logs` is `false`. ([#625](https://github.com/yaalalabs/agent-kernel/issues/625))

### Security

- Raise the `mcp` extra to fastmcp 3.2.0 or later, and the `langgraph` extra to langchain 1.3.10 and langgraph 1.2.10 (with langgraph-prebuilt 1.1), to pick up fixes for published advisories, including a critical one in fastmcp 2.x. ([#688](https://github.com/yaalalabs/agent-kernel/issues/688), [#674](https://github.com/yaalalabs/agent-kernel/issues/674))
