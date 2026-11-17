# #954: Pluggable cost management: gateway-backed usage, attribution and user budgets

Every supported LLM call goes through one configured external LLM gateway, carrying attribution headers built from trusted
run context. Agent Kernel reads usage and cost back from that gateway when asked, through an adapter that normalises
them, and enforces per-user budgets: natively where the gateway can, and with a pre-run check against gateway spend
where it cannot. The gateway owns request execution, usage capture and persistent records. Agent Kernel owns
attribution, pricing normalisation, budget configuration and orchestration, and reporting.

## Motivation

- #954 makes the gateway the **source of truth** for usage. Agent Kernel keeps no persistent usage store; it caches
  per-user spend aggregates (the spend ledger) only for a gateway that cannot compute them itself.
- Agent Kernel builds no model client. Every adapter wraps a native agent the user built, for example
  `OpenAIModule` at `framework/openai/openai.py:908` and `LangGraphAgent` at `framework/langgraph/langgraph.py:326`. So
  only a client the user configures can reach the gateway.
- Agent Kernel's own LLM calls go straight to the provider through LiteLLM:
  - multimodal: `core/multimodal/hooks.py:73`, `:94`; `core/multimodal/tools.py:78`
  - thread naming: `integration/thread/naming.py:120`
- `Runtime` has no request id: `Runtime.run` (`core/runtime.py:410`) and `Runtime.stream` (`:466`) take only agent,
  session, requests and principal. The id exists only on the envelope (`core/model.py:764`) and is dropped before the
  run (`core/chat_service.py:151`).
- The user identity Agent Kernel can trust is the published principal: `ak.principal` (`core/base.py:32`), which
  application code cannot write.
- `ErrorCategory` (`core/util/error_util.py:1-7`) has no budget category. A gateway's budget refusal would surface as
  `AUTH` or `RATE_LIMIT`.
- Gateway capabilities differ sharply. Only LiteLLM enforces per-user budgets before the request is sent; Agentgateway
  has no HTTP usage API (usage lives in its request-log database); Langfuse has no budgets (`research/gateways.md`).

## Requirements

### Activation and configuration

- A `cost` block in `AKConfig` enables the capability by being present. It is `_CostConfig | None = None`, the
  `thread` / `schedule` / `identity` pattern (`core/config.py:1529`, `:1535`, `:1549`). There is no `enabled` flag.
- With no `cost` block, behaviour is unchanged: no headers, no budget check, the usage route returns 404.
- An invalid or incomplete block raises `AKConfigError` at startup. So does any of the following:
  - a `cost.gateway` without `type` or `base_url`
  - a capability the configured gateway does not declare, needed by the config (for example a `budgets` block on a
    gateway with none of `native_user_budget`, `windowed_spend` or `usage_retrieval`)
  - a budget currency the gateway does not report
  - an Agentgateway gateway without `database`
  - a malformed `budgets.users` key (see Attribution), or the reserved key `ak-system`

```yaml
cost:
  gateway:
    type: litellm                 # litellm | agentgateway | langfuse | dotted path to an LLMGateway
    base_url: http://litellm:4000 # model endpoint the gateway client sends calls to (or AK_COST__GATEWAY__BASE_URL)
    api_key: ""                   # empty -> SecretManager.get(api_key_key)
    api_key_key: LITELLM_API_KEY
    admin_key: ""                 # optional: usage reads and budget sync, where the gateway separates them
    admin_key_key: LITELLM_MASTER_KEY
    database: {url: "", url_key: AGW_DB_URL}  # agentgateway only: its request-log DB (Postgres or SQLite), read-only
    litellm:                      # litellm only
      api: end_user               # end_user | customer_management
      customer_org_alias: ""      # customer_management only: the org every member belongs to
  attribution:
    type: default                 # default | dotted path to an Attributor
  view:
    type: default                 # default | dotted path to a UsageView
  pricing:
    type: passthrough             # passthrough | static | dotted path to a PricingSource
  budgets:
    on_error: block               # block | allow: what a failed budget check does
    default: {amount: 100, currency: USD, period: monthly, action: block}
    users:                        # keys are the attributed user id: the principal's subject
      "user-123": {amount: 20, currency: USD, period: monthly, action: block}
      "user-456": {amount: 50, currency: USD, period: monthly, action: warn}
    ledger:                       # used only when the gateway lacks windowed_spend (see Spend ledger)
      type: redis                 # in_memory | redis | valkey | dynamodb | cosmosdb | firestore | dotted path to a SpendLedger
      redis: {url: "redis://redis:6379", prefix: "ak:cost:ledger:"}
```

- New fields, and why none can be derived from existing config:
  - `gateway.type`, `gateway.base_url`: which gateway sits in front of the models is deployment knowledge, and no
    existing block holds a model endpoint (no `base_url` anywhere in `AKConfig`)
  - `gateway.api_key` / `admin_key` / `database.url` with their `*_key` siblings: the house secret-field shape. The
    value field falls back to `SecretManager.get(<*_key>)` when empty, at the point of use, never inside `AKConfig`.
    The request's `${VAR}` YAML form is not supported: AK config has no `${}` interpolation (only `<file:...>`,
    `core/util/config_yaml_util.py:39`); environment values arrive through `AK_COST__*` variables
  - `gateway.litellm.api`: LiteLLM has two incompatible per-user APIs (see LLM gateway); which one the proxy runs
    is deployment knowledge
  - `gateway.litellm.customer_org_alias`: Customer Management scopes members to an organization; nothing in config
    names it
  - `attribution.type`, `pricing.type`, `view.type`: name the bring-your-own (BYO) class
  - `pricing.static`: per-model rates; nothing in config holds a price
  - `budgets.*`: budget amounts are new data
  - `budgets.on_error`: the explicit failure policy the requirements demand (§10)
  - `budgets.ledger`: where budget spend aggregates live when the gateway cannot aggregate them. It mirrors
    `_ThreadStoreConfig` (`core/config.py:489`): `type` (default `in_memory`) plus per-backend blocks reusing
    `_RedisConfig`, `_ValkeyConfig`, `_DynamoDBConfig`, `_CosmosDBConfig`, `_FirestoreConfig` (`core/config.py:23-60`).
    Ignored with a warning on a gateway with `windowed_spend`; missing where needed means `in_memory` with a warning
- Dotted-path classes receive their sub-block (`extra="allow"`, the identity-provider pattern).

### LLM gateway (`LLMGateway`)

- An ABC in `agentkernel/cost/gateway/`. It is the only place a gateway is named. `Runtime`, `CostManager`, the
  budget policy and the usage route all talk to the ABC.
- `capabilities: GatewayCapabilities` is a class-level declaration (the `SandboxCapabilities` pattern). Every
  consumer reads it before calling an optional operation. The flags:
  - `usage_retrieval`
  - `cost_retrieval`
  - `user_aggregation`
  - `windowed_spend`: per-model sums for one user over an arbitrary UTC window, in one aggregate read
  - `agent_aggregation`
  - `session_filter`
  - `custom_metadata`
  - `native_user_budget`
  - `request_level_budget_check` (strict pre-request reservation)
  - `streaming_usage`
  - `currencies`
  - `filters`: the subset of user, agent, session, time range, model and provider it can filter on
- Operations:
  - `attribution_headers(attribution) -> dict[str, str]`, required. Returns the attribution in the gateway's own
    header vocabulary.
  - `fetch_usage(query) -> UsageResult`, needs `usage_retrieval`. Returns records normalised to `ModelUsage`, paging
    through the gateway's API.
    - A filter outside `capabilities.filters` raises `UnsupportedCapabilityError`.
    - Any failure raises `UsageRetrievalError`. It never returns an empty result in place of an error.
    - Hitting a gateway cap raises `UsageTruncatedError`. It never returns a partial total.
  - `total_spend(user_id, window) -> SpendTotal`, needs `windowed_spend`. The aggregate the budget check reads,
    so a user's row count never affects enforcement. It must equal `SpendTotal.from_rows` over the same rows,
    including cached tokens and the unpriced count. A gateway that cannot report one of these raises, rather than
    report it as 0 (asserted by `LLMGatewayContract`).
    - `SpendTotal` holds per-model sums: requests, each token kind, `provider_cost`, and the count of unpriced
      requests. That is enough for a `PricingSource` to bill the aggregate (`bill_total`) without rows.
    - A gateway whose own spend figure is lifetime, reset on the gateway's schedule, or not per model does not
      declare `windowed_spend`.
  - `fetch_usage_since(user_id, cursor, until) -> (rows, next_cursor, caught_up)`, needs `usage_retrieval`. The
    incremental read the spend ledger uses.
    - It returns **one batch**: at most one page of rows strictly after `cursor` and up to `until`, in timestamp
      order, so no row is skipped or repeated. `caught_up` says whether rows remain.
    - The cursor is the last timestamp plus the row ids seen at that timestamp, because LiteLLM sorts on `startTime`
      alone.
    - The bounds are exact even where the gateway filters more coarsely: LiteLLM's `/spend/logs/v2` takes
      second-resolution, inclusive dates, so the adapter filters on the client.
  - The fallback budget check uses `total_spend` when `windowed_spend` is declared, otherwise the spend ledger.
  - `sync_budget_definitions(limits)` and `sync_budgets(budgets)`, need `native_user_budget`. The first writes the
    distinct budget definitions, and the second writes each user's budget assignment into the gateway.
  - `is_budget_refusal(error) -> bool`, required. Matches the gateway's error type or code, never the HTTP status
    alone.
- Built-ins, behind the `cost` extra (gateway SDK-free: `httpx` plus `litellm`):

  | | `litellm` (`api: end_user`) | `litellm` (`api: customer_management`) | `agentgateway` 1.7.x | `langfuse` |
  |---|---|---|---|---|
  | User header | `x-litellm-customer-id` (first in its end-user resolution order) | `x-litellm-customer-org-alias` + `x-litellm-customer-member-id` | `x-ak-user-id` | `langfuse-user-id` |
  | Agent / session / request | `x-litellm-tags` (agent); session and request id in `x-litellm-spend-logs-metadata` | as `end_user` | `x-ak-agent-id`, `x-ak-session-id`, `x-ak-request-id` | `langfuse-tags` (agent), `langfuse-session-id`, `langfuse-metadata` (`request_id:<id>`) |
  | `fetch_usage` | `/spend/logs/v2` filtered on `end_user` (never `user_id`, LiteLLM's internal user); agent and session grouped or filtered client-side from `request_tags` and `metadata` | daily totals only (`/management/v1/customer_members/daily/activity`); per-member row retrieval **not available** | read-only SQL on `request_logs` | `/api/public/v2/observations` filtered by `userId` / `sessionId` |
  | `total_spend` (`windowed_spend`) | no: `/customer/info` `spend` is lifetime (or LiteLLM's reset period when a budget is attached) and not per model | no: member `spend` has the same limits | yes: SQL `SUM ... GROUP BY model` over the window | yes: v2 metrics filtered by `userId`, grouped by model (never top-N user grouping) |
  | Fallback budget source | spend ledger, fed by `fetch_usage_since` over `/spend/logs/v2` filtered on `end_user`, ordered by `startTime`; cursor = last settled `startTime` + `request_id` | not available: no per-member rows, so no ledger and no other fallback; a fallback budget raises `AKConfigError`; native budgets unaffected | `total_spend` | `total_spend` |
  | `native_user_budget` | yes: `/customer/new` / `/customer/update` with a `budget_id` | yes: `/management/v1/customer_members/upsert` with a budget | no: budgets are per API key only | no |
  | Default budget | upserted onto each user lazily, on their first run in each process (`max_end_user_budget_id` cannot be set through the admin API at 1.95.1) | the org's default budget template (`/customer_organizations/{id}/default_budgets`) | fallback | fallback |
  | `request_level_budget_check` | yes: reservation (on by default) | yes | n/a | n/a |
  | Refusal signature | `error.type` / `litellm_error_type` = `budget_exceeded` (422 by default on current releases; 429 on 1.95.x); never matched by status | as `end_user` | `budget_exceeded` (429) | n/a |
  | Setup the operator owns | DB-backed proxy; `always_include_stream_usage`; `timezone` unset or `UTC` (not verifiable through the admin API, see Budgets) | as `end_user`, plus the organization | CEL `standardAttributes` over the `x-ak-*` headers (below); a request-log database | a **service-account** key, without which `langfuse-user-id` is ignored (documented) |

  - Per-gateway mode notes, operator config and schema pins are in spec.md §5. The requirement-level points:
    - LiteLLM `end_user` is the default (open source, every stable release). `customer_management` needs LiteLLM
      1.111+, which is checked at startup. Without Enterprise it is capped at 5 orgs × 5 teams × 5 members, and it
      supports native budgets only. Documented.
    - Agentgateway 1.7.x: the adapter pins the request-log schema at startup and refuses unknown migrations. It reads
      the database read-only (SQLite through stdlib; Postgres behind the `cost-agentgateway` extra). It needs the
      documented `standardAttributes` mapping of the `x-ak-*` headers. An uncatalogued model is priced at $0, which
      looks like free spend. Documented.
    - Langfuse 4.75.0+ (or Cloud), gateway beta: a compatibility suite pins its contract. The adapter derives the
      OpenAI or Anthropic base from the model's provider. It refuses attribution headers over Langfuse's 1 KiB per
      value and 8 KiB total limits, rather than have them silently dropped.
- `LLMGatewayFactory` follows the `core/util/factory.py` shape: `if/elif` built-ins, `require_extra`, `resolve_dotted`
  for BYO, `AKConfigError` otherwise.
- `LLMGatewayContract` (`cost/testing.py`) checks every built-in against its declaration:
  - an undeclared operation raises `UnsupportedCapabilityError`
  - a failed fetch raises, and never comes back as zero
  - pages are concatenated in order
  - headers overwrite a caller's value for the same key

### Gateway client and request coverage

- `GatewayLiteLLM` (class, `cost/client.py`) is Agent Kernel's gateway-bound LiteLLM client. `completion` and
  `acompletion` call LiteLLM with:
  - `api_base` set to the gateway (Langfuse: the base for the model's provider)
  - `api_key` resolved through `SecretManager`
  - `extra_headers` = the caller's headers with the current run's attribution headers merged on top, so Agent
    Kernel's keys win
  - `stream_options.include_usage` set for OpenAI-format streams
- Headers are computed **per call** from the current context: `Session.current()`, its published principal,
  `Agent.current()` and the run's request id. Never from a global: `litellm.headers` is a module-level setting shared
  by concurrent runs, so Agent Kernel never sets it.
- A call outside any run (thread naming in `ThreadRecorder.pre_run`, which runs before `Runtime`) sends the
  attribution the caller passes explicitly (`GatewayLiteLLM.completion(..., attribution=...)`). Thread naming passes
  the attributed user id (the configured `Attributor` applied to the principal) and the session id it already
  holds. With no principal it sends `user_id=ak-system` and no agent. Naming runs before the budget check, so an
  over-budget user still pays for one naming call per new thread (the one documented exception). A refusal falls back to the prompt-prefix name.
  - `ak-system` is used only at named system call sites. Any other call with no run context and no explicit
    attribution logs a warning and is sent unattributed. `AnalyzeAttachmentsTool` reads the current run's
    attribution at call time. System tools are built once per agent,
    so a capture when the tool is bound would charge the first run's user for every later call. Under CrewAI's sync
    tool executor, which drops context, the call is sent unattributed with the warning. This is a documented gap.
  - `ak-system` is never refused: native budget sync always upserts it with no budget, and the fallback check skips it.
  - `ak-system` is reserved: a `budgets.users` key equal to it raises `AKConfigError`, and a principal whose subject
    is `ak-system` is denied.
- Framework bindings: thin per-framework classes over each framework's own model seam, so headers are added on
  every call from the current context. Verified at the `uv.lock` versions (`research/framework-bindings.md`):
  - Each lives in `framework/<fw>/cost.py` and is exported from the framework's public module (`agentkernel.<fw>`,
    e.g. `from agentkernel.openai import GatewayLitellmModel`), next to its `*Module`.
  - Dependency direction: `framework/` imports `cost/client.py`; `cost/` never imports `framework/`. The import is
    lazy, so a framework module without the `cost` extra still loads.
  - The user builds the binding in place of the framework's own model class. It takes the model name and reads
    `base_url` and the key from `cost.gateway`. Constructing one without a `cost` block raises `AKConfigError`.

  | Framework | Class the user builds | Granularity |
  |---|---|---|
  | openai-agents 0.20.0 | `GatewayLitellmModel` (a `LitellmModel` subclass) | per call |
  | google-adk 2.8.0 | `GatewayLiteLLMClient`, passed as `LiteLlm(llm_client=...)` | per call |
  | smolagents 1.26.0 | `GatewayLiteLLMModel` (a `LiteLLMModel` subclass) | per call |
  | crewai 1.15.18 | `GatewayCrewLLM` (an `LLM` subclass) | per call |
  | agent-framework-core 1.24.0 (MAF) | `GatewayChatClient` (a `BaseChatClient` over `GatewayLiteLLM`) | per call |
  | LangChain / LangGraph | `GatewayChatLiteLLM` (from `langchain-litellm`, added to the `langgraph` extra) | per call |
  | claude-agent-sdk 0.2.179 | none: automatic in `ClaudeModule` when `cost` is configured | per run (one CLI process per run) |
  | Pydantic AI | none: `CostRunOptions.wrap` (no LiteLLM-SDK seam) | per run |

  - The seams overridden, how context reaches each call, and the CrewAI caveats are in spec.md §6–§7, verified at the
    `uv.lock` versions. Each binding's context test pins its seam.
  - CrewAI sync tools drop context, so a tool's own LLM call there must pass attribution explicitly. Documented.
  - Claude Agent SDK: gateway routing supports **API-key authentication only**. With `cost` configured and no API
    key, the Claude adapter raises `AKConfigError` on the agent's first run (the key is resolved per run, so
    rotation is picked up). Documented.
- Users who bring their own client have two per-run routes. `default_headers` fixed when a client is built cannot
  carry per-run values, so neither uses them:
  - a #758 `run_options` factory that returns `CostManager.attribution_headers()` into the framework's native per-run
    field: OpenAI `ModelSettings.extra_headers`, Pydantic AI `model_settings.extra_headers`, ADK
    `RunConfig.http_options`. Agent Kernel ships `CostRunOptions.wrap(user_factory=None)` for these three: an agent holds
    one factory, so it wraps the user's own and deep-merges the headers into the native field.
  - a tool's own client calls `CostManager.attribution_headers()` and passes them per request.
  
  `attribution_headers()` returns the current run's headers and raises `RuntimeError` outside a run.
- **Coverage rule**: when cost management is on, every LLM call must either use `GatewayLiteLLM` (directly or through a
  framework binding) or send `attribution_headers()` to the gateway itself.
  - This goes into the user docs (`docs/docs/`), into the bundled agent-creation skills
    (`ak-py/src/agentkernel/skills/ak-build`, `ak-add-capabilities`), and into each example that uses cost management.
  - A call that bypasses the gateway is not in its records. A call that reaches the gateway without headers is
    recorded unattributed. Both are documented as outside the tracked path.
- Agent Kernel's own LiteLLM calls (multimodal description and analysis, thread naming) use `GatewayLiteLLM` when
  `cost` is configured, and unchanged `litellm` otherwise.
- OpenAI guardrails are routed too: `GuardrailsOpenAI` takes a base URL and key at construction and forwards
  `extra_headers` per call (verified in spec.md). Their library-internal check calls may reach the gateway
  unattributed. Documented.
- Outside the tracked path, documented:
  - Bedrock and Walled AI guardrails (their own SDKs)
  - realtime sessions (native SDK websockets)
  - Claude Agent SDK runs authenticated by subscription or OAuth instead of an API key
  - test evaluators

### Attribution

- `Attributor` ABC: `resolve(ctx) -> Attribution(user_id, agent_id, session_id, request_id)`.
- Default `Attributor`:
  - `user_id` comes **only** from the run's published principal.
    - Default form: `principal.subject`. The same subject under two issuers is one user; a deployment with several
      issuers uses a BYO `Attributor` (for example, provider-qualified). Documented.
    - This form is the `budgets.users` key. Keys are validated at startup (non-empty, not `ak-system`); a malformed
      key raises `AKConfigError`. The usage API returns the caller's `user_id`. Documented.
    - Anonymous runs map to `anonymous`, so a budget on it caps all anonymous traffic together. Documented.
    - Messaging and realtime principals carry the platform sender id as subject, so they are budgeted per sender.
      Documented.
  - `agent_id` is `agent.name`, `session_id` is the session id, `request_id` is the run's request id.
- Spoofing protection:
  - Nothing in a client request body or user run options can set or override `user_id` or `agent_id`. `request_id`
    is a correlation id: a client or pipeline id is kept, and minted when absent.
  - `GatewayLiteLLM` and the bindings write Agent Kernel's header keys last.
  - `user_id` in a chat body is already a 400 (identity rule, #603).
- Request id plumbing:
  - `Runtime.run` and `Runtime.stream` gain `request_id: str | None = None`.
  - It is threaded along the path the principal takes: `ChatService.execute*` → `AgentHandler.run*` →
    `AgentService.run_multi` / `stream_multi` (`core/service.py:177`).
  - The pipeline passes the id it resolves per message (`pipeline/agent_runner.py:73`).
  - A run arriving without one gets a `uuid4().hex`.
  - It is published under a reserved `ak.` key and read through `session.get_request_id()`.
- BYO `Attributor` via dotted path, for example a tenant-scoped user id taken from a claim.
- `AttributorContract`:
  - stable output for the same context
  - `user_id` never taken from anything but the principal
  - context left unmodified

### Usage model, pricing and currency

- `ModelUsage` (Pydantic) is the normalised record:
  - `user_id`, `agent_id`, `session_id`, `request_id`: each `str | None` (unattributed rows exist)
  - `provider`, `model`
  - `input_tokens`, `output_tokens`, `cached_input_tokens`: `int | None`, so a missing count is `None`, never 0 and
    never estimated
  - `provider_cost`, `billed_cost`: `Decimal | None`
  - `currency`, `timestamp`
- Adapters fill only what the gateway reports. A missing cost stays `None` and is counted in
  `UsageReport.unpriced_requests`.
- `PricingSource` ABC: `bill(usage) -> Decimal | None` gives a record's `billed_cost`, `bill_total(spend_total) ->
  Decimal` bills an aggregate per model, and `bills_at_cost: bool` says whether billed equals provider cost.
  - `provider_cost` always comes from the gateway and is never recomputed.
  - Built-in `passthrough` (the default): billed equals provider, `bills_at_cost = True`.
  - Built-in `static`: per-model rates in USD per 1M tokens for input, output and cached input, plus an optional
    `markup` multiplier. An unknown key in the block raises `AKConfigError`. `bills_at_cost` is false whenever a
    rate or markup is set. Cached input is priced at the cached rate, falling back to the input rate, and is never
    charged twice.
  - BYO via dotted path, for example credits or free tiers.
  - `PricingSourceContract`: `None` in gives `None` out; cached tokens are not double-charged.
- Currency: Agent Kernel does not convert.
  - A budget currency outside `gateway.capabilities.currencies` (USD for all three built-ins) raises `AKConfigError`
    at startup.
  - A record arriving in another currency raises `UsageRetrievalError`. It is never summed.

### Usage retrieval and aggregation

- `UsageView` ABC (§9.5): `report(query, principal) -> UsageReport`. It applies authorization (which queries this
  principal may run, compared against the principal's attributed user id), aggregates and shapes the result. Built-in `default`, BYO via dotted path, `UsageViewContract`.
  The default does the following:
  - `UsageQuery` fields: `user_id`, `agent_id`, `session_id`, `start`, `end`, `model`, `provider`.
  - The view calls `gateway.fetch_usage` and aggregates the pages **in memory, per request**. Nothing is persisted:
    no `UsageStore`, no usage rows held by Agent Kernel (the spend ledger holds budget aggregates only).
  - The whole window is fetched first. Only a window that hits the gateway's row cap (LiteLLM 10k) is split, into
    days and then hours. A cap that is still hit is a `UsageTruncatedError`, never a partial total.
- `UsageReport` has one shape whatever the gateway:
  - `user_id`, `currency`, `window`
  - `total_cost` (billed) and `total_provider_cost`
  - `total_input_tokens`, `total_output_tokens`, `total_cached_input_tokens`
  - `unpriced_requests`
  - `agents`: per-agent cost and tokens
  - `sessions`, only when the query is scoped to one agent or session
- User × agent and user × session are answered by filtering on one dimension and grouping on the other client-side.
  A query the gateway cannot filter becomes a client-side filter over a filterable query (time range plus user).
  Only when even that is impossible is it `UnsupportedCapabilityError`.
- A BYO `UsageView` may change authorization or add fields, but must return the `UsageReport` envelope keys, so
  clients rely on one format. The contract suite asserts the envelope.

### Budgets

- `BudgetPolicy` ABC: `check(ctx, attribution) -> BudgetDecision`, one of `allow`, `warn(message)` or
  `deny(message)`.
  - Built-ins: `static` (the `budgets` block) and `none`, used when there is no `budgets` block.
  - BYO via dotted path.
  - `BudgetPolicyContract`.
- Budget model, `BudgetLimit`:
  - `amount` (> 0), `currency`
  - `period`: `daily` | `weekly` | `monthly`
  - `action`: `block` | `warn`
  - optional `message`
- Resolution: `budgets.users[<user key>]` overrides `budgets.default`. No entry means no budget.
- Periods are calendar-aligned in UTC: the day starts at 00:00, the week on Monday, the month on the 1st. The current
  period's spend is everything timestamped since its start. Documented.
- Compared figure: `pricing.bill_total(total_spend)` against `amount`. With `passthrough` that equals the gateway's
  provider cost.
  - A request with no cost counts as zero toward the amount. `SpendTotal.unpriced_requests` exposes it, a warning is
    logged once per model, and docs say a budget cannot see unpriced spend (the Agentgateway $0 case included).
- **Native enforcement** (preferred):
  - At startup `CostManager` calls `gateway.sync_budget_definitions` and `gateway.sync_budgets` for each per-user budget the gateway can express **exactly**:
    - `native_user_budget`
    - `action: block`
    - `pricing.bills_at_cost` (a gateway enforces on its own cost, not `billed_cost`)
    - a period the gateway represents faithfully
  - LiteLLM periods map exactly: `daily` → `1d`, `weekly` → `7d` (resets Monday), `monthly` → `1mo` (resets on the
    1st). At 1.95.1 these are calendar-aligned by `get_next_standardized_reset_time`, against
    `litellm_settings.timezone` (default UTC); a `w` unit is not aligned there.
  - The proxy must run with `timezone` unset or `UTC`. No admin route returns it at 1.95.1, so this is a documented
    operator requirement that Agent Kernel cannot verify; startup logs that once. Agent Kernel never writes proxy-wide
    settings. Admin routes are pinned in spec.md §5.1.
  - Sync is idempotent (an upsert per user) because every process runs it at startup. A user removed from config is
    not deleted from the gateway: Agent Kernel does not track what it created, and deletion is documented as manual.
  - Startup with the gateway down. Config errors fail fast; availability errors do not:
    - an auth failure (401/403) or a gateway that rejects the budget shape raises `AKConfigError`: the deployment is
      misconfigured, and retrying will not fix it
    - an unreachable gateway or a 5xx logs an error and does not stop startup. The sync retries in the background
      with capped exponential backoff until it succeeds, so a gateway outage never blocks a rollout
    - startup waits only on the calls that can expose a config error: one budget definition per distinct budget,
      plus the `ak-system` upsert. Per-user rows are written in the background, and a user is checked by the
      fallback until their row is written. Startup cost therefore does not grow with the number of users
    - until a retried sync succeeds, the gateway keeps the budgets from the last successful sync (LiteLLM stores them
      in its database); a budget new in this config is enforced by the fallback check meanwhile
    - startup probes that need the gateway (the LiteLLM `customer_management` version check, the Agentgateway
      migration check) follow the same rule: deferred when unreachable, fatal when they read a wrong answer. Until
      a probe succeeds, usage reads return 502 and budget checks apply `budgets.on_error`
  - Deliberate trade-off, documented: with the default `on_error: block`, a gateway outage denies every run of a user
    with a fallback budget. Model calls would fail in the same outage anyway, since they go through the gateway.
  - A natively synced budget is not checked again by Agent Kernel. Its enforcement and strictness are the gateway's
    (LiteLLM: pre-request reservation).
  - The default budget covers users unknown at startup:
    - `end_user`: on a user's first run in each process, Agent Kernel upserts the default budget onto that customer
      (`/customer/new` or `/customer/update` with the default budget's `budget_id`), cached per process: one or two
      admin calls on that user's first run. A failed upsert falls back to the fallback check for that run. `max_end_user_budget_id` is not used: at 1.95.1 a value
      written through `/config/update` is never applied by the proxy.
    - `customer_management`: written as the organization's default budget template.
    - Other gateways: enforced by the fallback check.
- **Fallback enforcement** (every other budget):
  - `Runtime` calls `RunMeter.check(ctx)` **before any pre-hook**, at `core/runtime.py:433` (run) and `:494` (stream).
    An over-budget user spends nothing, not even on guardrail or multimodal calls.
  - `check` reads the current period's `SpendTotal`, from `gateway.total_spend(user, current period)` or from the
    spend ledger (see LLM gateway), and compares it with the budget.
  - `deny`: no model call is made. Non-streamed runs return an `AgentReplyText` with the message, the pre-hook halt
    shape (`core/runtime.py:434-438`). Streamed runs yield one `StreamChunk(error=<message>, done=True)` (`:499`).
  - `warn`: the run proceeds. Agent Kernel logs a warning naming the user, the budget, the period and the spend.
    Nothing is added to the reply or the stream.
  - Default message: "Your usage budget for this period has been reached."
  - A resume is checked like any run. A `deny` (or an `on_error: block` denial) on a resume:
    - leaves the paused run untouched, so it can be answered again once the period resets or the budget changes
    - logs the existing resume-halted warning (`Runtime._warn_resume_halted`, `core/runtime.py:394`), as a pre-hook
      halt does (`:437`, `:498`)
    - returns the same deny shape as a fresh run
- Gateway refusals mid-run: `ErrorUtil` asks the already-built `RunMeter` (never constructing one in the error path)
  `is_budget_refusal(error)` first and maps a match to the new
  `ErrorCategory.BUDGET`, whose user-facing message is "Error: The usage budget for this request has been reached." (the sibling categories' prefix) Without
  a `cost` block nothing matches, and categories are unchanged.
  - Frameworks re-raise their own exceptions around LiteLLM's (openai-agents, CrewAI, LangChain). The check walks the
    `__cause__` / `__context__` chain, cycle-safe, and matches on any link. Each adapter's `is_budget_refusal`
    still inspects only one exception; the walk lives once in `RunMeter`.
- Consistency, declared rather than claimed:
  - Strict only when the gateway reserves before the request (`request_level_budget_check`: LiteLLM native).
  - The fallback is best-effort and documented as such:
    - concurrent runs can all pass before any spend is recorded
    - gateway writes lag (LiteLLM batches spend writes; Langfuse records best-effort)
    - in-flight runs are not counted
    - a run that starts under budget completes
  - Docs name the gateway and setting needed for strict enforcement.
- Cost on the hot path, per run of a user with a fallback budget:
  - `windowed_spend` gateways: one aggregate read (one SQL `SUM`, one metrics query), whatever the user's row count.
  - ledger gateways, in steady state:
    - two gateway reads: the settled rows since the cursor (usually none) and the unsettled range of at most
      `settle_lag`
    - three ledger reads
    - at most one ledger write
    - A cold start adds one read and one write per batch, bounded by the catch-up budget (see Spend ledger).
- Failure policy: `budgets.on_error` applies when any of these happens:
  - `total_spend`, `fetch_usage_since` or the ledger fails
  - the gateway is unreachable
  - the ledger is still catching up when the catch-up budget runs out
  - `block` (default) denies the run with a distinct "budget could not be verified" message.
  - `allow` runs it and logs at warning level.
  - A retrieval failure is never read as zero spend.
- Budgets come from config only. There is no write API (see Non-goals).

### Spend ledger (`SpendLedger`)

- Per-user, per-period, per-model spend aggregates for a gateway without `windowed_spend`. A **derived cache**:
  filled only from gateway rows, rebuildable from the gateway, never the source of truth, and never holding rows.
- One document per user, so every update is a single-document compare-and-set:
  - the cursor: the last settled gateway timestamp and the row ids applied at that timestamp
  - aggregates keyed `(period, period_start, model)`: `requests`, `input_tokens`, `output_tokens`,
    `cached_input_tokens`, `provider_cost`, `unpriced_requests`
- `SpendLedger` ABC (`cost/ledger/`):
  - `cursor(user_id)`
  - `add(user_id, rows, expected_cursor, next_cursor)`: adds the rows' deltas and advances the cursor
    **atomically**, compare-and-set on `expected_cursor`. A stale cursor adds nothing, so two processes pulling the
    same rows never double-count.
  - `read(user_id, period, period_start) -> SpendTotal`
- Check flow: `cursor` → repeat (`gateway.fetch_usage_since` → `add`) until caught up → `read` → `pricing.bill_total`.
  - Catch-up is bounded and keeps its progress:
    - each batch is committed with `add` as soon as it is read
    - a fixed catch-up budget of 5 seconds (documented, not a config field) sits inside the check's time bound
    - a check still behind when the budget runs out applies `budgets.on_error`, and never sums a partial total
    - the next check continues from the committed cursor, so a heavy user's cold start (or an `in_memory` restart)
      is denied for a bounded number of runs, never indefinitely. Documented
  - Late rows: a fixed `settle_lag` of 10 minutes (documented, not a config field) covers LiteLLM's batched spend
    writes. The settle line is `now − settle_lag`.
    - rows before the settle line are **settled**: `add` stores them, and the cursor never moves past the settle line
    - rows after it are **unsettled**: re-read on every check, added to that check's total only, never stored. A row
      written late but inside the lag is still counted
    - a row older than the settle line that arrives after the cursor has passed it is missed; documented as
      best-effort, like the rest of the fallback
    - the unsettled read always starts at the settle line, never at an old cursor, so each check re-reads at most
      the last 10 minutes of the user's rows. Hitting the row cap there applies `budgets.on_error`
  - A user with no cursor starts at the start of the longest configured period, so the first check sees the whole
    current period.
  - A compare-and-set conflict re-reads the cursor and retries once, then applies `budgets.on_error`.
- Each row is bucketed by its timestamp into every period kind (`daily`, `weekly`, `monthly`) used by a budget.
- Retention: an aggregate expires one period after its period ends (native TTL where the backend has one).
- Failure: a ledger read or write failure is a budget-check failure (`budgets.on_error`), never read as zero.
- Backends, each over the shared driver in `core/util/driver/`, the way the thread store uses them
  (`integration/thread/store/`):
  - `in_memory`: single process only, documented as dev and test use
  - `redis`, `valkey`: one base over `_RedisLikeDriver` (`core/util/driver/redis_like.py`)
  - `dynamodb`, `cosmosdb`, `firestore`
  - BYO via dotted path
- `SpendLedgerFactory` follows the `core/util/factory.py` shape; `SpendLedgerContract` lives in `cost/testing.py`.

### Streaming

- Agent Kernel never reads usage from a model response, so streamed and non-streamed calls are counted the same way:
  by the gateway's own record.
- Per gateway:
  - LiteLLM records stream usage when `always_include_stream_usage` is set (documented setup).
  - Agentgateway and Langfuse record stream usage per their docs. `GatewayLiteLLM` requesting `include_usage` (below)
    covers the case where they do not inject it themselves.
  - `GatewayLiteLLM` always requests `include_usage` on OpenAI-format streams.
- `capabilities.streaming_usage` is declared per adapter, and docs state the gaps.

### Usage REST API

- `UsageRESTRequestHandler` (extends `AuthorisedRESTRequestHandler`, `api/handler.py:44`, so it requires an
  `identity` block) serves
  `GET /api/v1/usage?agent_id=&session_id=&start=&end=&model=&provider=` and returns a `UsageReport`.
- Window:
  - `start` and `end` are ISO 8601 timestamps; one without a timezone is read as UTC.
  - Defaults: `end` = now, `start` = the start of the current UTC calendar month.
  - The window may span at most 93 days (a quarter), a fixed limit and not a config field: it bounds how many
    gateway calls one request can fan out to when windows are split under row caps.
  - `start` after `end`, or a window over the limit: 400, naming the parameter.
- It always reports the caller's own usage: the caller's attributed `user_id` (the configured `Attributor` applied to
  the principal), so a BYO attributor keys the route the same way as the headers and budgets.
  - A `user_id` parameter naming someone else is a 403 until #603's authorization phase.
  - Anonymous callers get the inherited 401.
- Statuses:
  - unsupported filter, bad timestamp, inverted or over-long window: 400, naming the parameter
  - truncation: 422
  - gateway or retrieval failure: 502
  - no `cost` block: 404
  
  None of these is ever a 200 with zero totals.
- Mounted by the application, the schedule/thread convention:
  `RESTAPI.run(handlers=[AgentRESTRequestHandler(), UsageRESTRequestHandler()])`.
- Exported lazily from `agentkernel.cost`. It is the package's only FastAPI-importing module, so runner processes
  never load it.

### Wiring

- `CostManager`, a process-wide singleton:
  - `get()` returns `None` without a `cost` block; `reset()` for tests.
  - It owns the gateway, attributor, pricing source, budget policy and `UsageView`.
  - It syncs native budgets at startup.
  - It implements `RunMeter`.
- `RunMeter` is an ABC in `core/` with two calls: `check(ctx) -> BudgetDecision` and `is_budget_refusal(error) ->
  bool`.
  - `RunMeterFactory` returns `CostManager` (imported lazily inside the enabled-check) or a no-op meter.
  - Core never imports `cost/` at module scope.
  - No BYO branch: it is not a backend seam.
- Package: `agentkernel/cost/` holding `gateway/` (ABC, factory, built-ins), `ledger/` (ABC, factory, backends), `attribution.py`, `pricing.py`,
  `budget.py`, `view.py`, `client.py`, `manager.py`, `handler.py` and `testing.py`. Contract suites are not
  re-exported (the `secret/testing.py` rule).

| ABC | Factory | Built-ins | Contract suite |
|---|---|---|---|
| `LLMGateway` | `LLMGatewayFactory` | `litellm`, `agentgateway`, `langfuse` | `LLMGatewayContract` |
| `Attributor` | `AttributorFactory` | `default` | `AttributorContract` |
| `PricingSource` | `PricingSourceFactory` | `passthrough`, `static` | `PricingSourceContract` |
| `BudgetPolicy` | `BudgetPolicyFactory` | `none`, `static` | `BudgetPolicyContract` |
| `UsageView` | `UsageViewFactory` | `default` | `UsageViewContract` |
| `SpendLedger` | `SpendLedgerFactory` | `in_memory`, `redis`, `valkey`, `dynamodb`, `cosmosdb`, `firestore` | `SpendLedgerContract` |

```mermaid
graph LR
  FW[Framework LiteLLM bindings / AK own calls] --> CL[GatewayLiteLLM]
  BYO[User's own client] -.->|attribution_headers| GWY
  CL -->|calls + attribution headers| GWY[(LLM gateway)]
  RT[Runtime] -->|check before pre-hooks| CM[CostManager : RunMeter]
  CM --> AT[Attributor]
  CM --> BP[BudgetPolicy]
  CM --> PR[PricingSource]
  CM --> UV[UsageView]
  CM --> GW[LLMGateway adapter]
  UV --> GW
  BP -->|total_spend| GW
  BP -->|no windowed_spend| SL[SpendLedger]
  SL -->|fetch_usage_since| GW
  GW -->|usage APIs / DB read| GWY
  R[GET /api/v1/usage] --> UV
```

### Error handling

| Condition | Behaviour |
|---|---|
| Gateway unreachable on a model call | The framework error surfaces as today (`ErrorUtil`); no retry added |
| Gateway auth failure (bad key) | Model calls: as above. Usage reads: `UsageRetrievalError` → 502. At startup: native budget sync fails with `AKConfigError` |
| Gateway unreachable at startup | Logged; native sync and startup probes retry in the background with backoff; startup continues |
| Budget refusal from the gateway | `ErrorCategory.BUDGET` with its user-facing message |
| Budget check fails (`total_spend`, `fetch_usage_since` or ledger error, or the ledger still catching up) | `budgets.on_error`: `block` denies with a distinct message, `allow` runs and warns; never read as zero |
| Ledger cursor conflict | Re-read and retry once, then `budgets.on_error` |
| Usage retrieval fails | `UsageRetrievalError` → 502; never an empty report |
| Missing records / unattributed rows | Excluded from user-scoped queries; counted only in unscoped admin views (none in #954) |
| Missing cost on a record | `provider_cost` / `billed_cost` stay `None`; `unpriced_requests` incremented |
| Unsupported capability or filter | Startup `AKConfigError` when config needs it; run time `UnsupportedCapabilityError` → 400 |
| Invalid pricing config | `AKConfigError` at startup |
| Currency mismatch | `AKConfigError` at startup; `UsageRetrievalError` at run time |
| Incomplete streaming usage | The gateway's record is used as-is; tokens `None` where not reported |

### Deployment (AWS Terraform)

- In scope: `ak-deployment/ak-aws/` serverless and containerized. GCP, Azure and the `ak-k8s` Helm chart are the next
  stage.
- `create_dynamodb_cost_ledger_table` (default `false`) in both stacks. It creates the spend-ledger table: partition
  `user_id`, TTL on `expiry_time`.
  - It is wired like the conversation-thread table: request handler (direct mode) or agent runner (queue mode) on
    serverless, and rest service plus agent runner on containerized. These are the tiers where `Runtime` runs the
    budget check.
  - Least-privilege IAM: `DescribeTable`, `GetItem`, `PutItem` on that table only.
  - It injects `AK_COST__BUDGETS__LEDGER__DYNAMODB__TABLE_NAME` and outputs the table name and ARN.
- Terraform never sets a `cost` type or any other `cost` field. The application's `config.yaml` does, as with
  `thread.type`.
- No Terraform change for gateway credentials: the existing `ssm_enabled` grant covers them through `SecretManager`.
  The READMEs name the parameters.
- The gateway and its databases are operator infrastructure. The agent tiers reach them over the existing VPC.
  Documented.

### Security

- Attribution comes only from the published principal and run context (see Attribution). Clients cannot spoof it.
- Gateway credentials are resolved through `SecretManager` by key name, never held as values in config.
  - They never appear in logs, exceptions or API responses: the adapters log the endpoint path only.
- The admin key is used only for usage reads and native budget sync. Model calls use `api_key`.
- The Agentgateway DB connection is read-only, documented with a read-only database role.
- Users read only their own usage; no cross-user reads until #603.
- Budgets are set in config only; there is no runtime path that modifies them.

### Testing

Test files, fixtures and patch targets are in spec.md (Testing). At design level, the requirements are:

- Every built-in subclasses its contract suite: `LLMGatewayContract` (both LiteLLM modes), `SpendLedgerContract`
  (each backend), and the attributor, pricing, budget-policy and view suites.
- Gateways:
  - headers, normalisation, paging, failures (unreachable, 401, 5xx, malformed) and truncation
  - `total_spend` equal to the same rows' totals
  - The pinned external contracts (LiteLLM's `/spend/logs/v2` order, row ids and settle timing; the Agentgateway
    1.7.x schema; Langfuse's headers, limits and v2 shapes) each have a compatibility or fixture test.
- Client and bindings:
  - headers per call from context, never shared between concurrent runs, with Agent Kernel keys winning
  - `include_usage` on streams
  - context reaching each binding's call, including inside `asyncio.to_thread`
- Attribution:
  - only the principal sets the user, and spoofing is rejected or overwritten
  - anonymous runs
  - a BYO attributor used by the route, the view and thread naming
- Budgets:
  - resolution, UTC period edges, and the deny and warn shapes for run and stream
  - native sync eligibility, plus startup behaviour: auth failure is fatal, an outage is retried in the background,
    and per-user rows are written in the background
  - `on_error` for every failure kind
  - `ak-system` never refused, and reserved keys rejected
- Spend ledger:
  - stale cursors and concurrent adds never double-count
  - the settle lag and second-resolution dates handled
  - catch-up committed batch by batch, never summed partially
  - expiry
- API: the 400 / 401 / 403 / 404 / 422 / 502 statuses, the window rules, and one response format across all three
  gateways.
- `Runtime`:
  - the check runs before pre-hooks and is skipped without `cost`
  - `request_id` is threaded and minted
  - a denied resume stays answerable
  - `BUDGET` mapping through wrapped framework exceptions, with no `CostManager` built in the error path

## Non-goals

- Building an LLM gateway or proxy.
- Any persistent usage record store in Agent Kernel: no `UsageStore`, no per-request usage rows, no in-process usage
  capture from adapters or responses. The only Agent Kernel-held data is the spend ledger's per-period aggregates,
  used only for gateways without `windowed_spend`, and rebuildable from the gateway.
- Budgets on dimensions other than the user.
- Billing or invoicing.
- Strict enforcement on gateways without pre-request reservation.
- A budget management endpoint or runtime budget writes (a follow-up issue).
- Reading another user's usage, and agent-wide totals across users ("how much has agent X spent?"), over the API.
  Both wait on #603 authorization. Until then, agent-wide totals are a `UsageView.report` call from application code,
  or the gateway's own UI.
- Currency conversion.

## Open questions

- Delivery split. Proposed:
  1. `request_id` plumbing and the `RunMeter` seam
  2. `cost/` core, LiteLLM adapter, client and usage route
  3. budgets and the spend ledger
  4. Agentgateway and Langfuse adapters
  5. docs, skills and examples
