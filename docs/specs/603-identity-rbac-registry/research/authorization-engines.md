# Authorization engines: which ones can sit behind an `Authorizer` adapter

Survey date: 2026-09-28. Supports the RBAC part of issues #521 and #603.

The question this note answers: which embeddable or remote policy engines could a pluggable
`Authorizer` interface wrap, so that Agent Kernel ships one zero-setup built-in (the house
`in_memory`/`local` default) and lets deployments swap in an enterprise engine by config `type`.
The interface has to answer four questions:

- (a) may user U access agent A at level L (read, execute, write, admin);
- (b) may agent A invoke tool T, optionally on behalf of user U;
- (c) which agents may user U see (list-filtering, the catalog question);
- (d) who may access agent A (audit and admin UI).

Verification legend: **[V]** the cited page was fetched and read during this survey; **[U]** taken
from a search snippet or prior knowledge only. Re-verify [U] claims before designing against them.

## 1. Comparison

| Engine | Deployment model | Python SDK | In-process, no server? | RBAC / ABAC / ReBAC | (c)/(d) list queries | License | Agent-authz docs | Verdict |
|---|---|---|---|---|---|---|---|---|
| Casbin (`pycasbin`) | Embedded library, pure Python port | `pycasbin` 2.8.0, 2026-02-02, Py 3.8+, `AsyncEnforcer` [V] | Yes: model from text, File and String adapters built in [V] | RBAC with transitive hierarchy and domains; ABAC via matcher expressions; ReBAC only emulated | RBAC-grant enumeration via `get_implicit_resources_for_user` / `get_implicit_users_for_permission` [V]; ABAC needs candidate set + `batch_enforce` | Apache 2.0, ASF Incubator since 2026-02-07 [V] | "Casbin in 2025: the AI Agent era" (2025-12-11) [V] | **First built-in**: the only engine with the exact "model + swappable policy adapter, in-process" shape |
| OpenFGA | Server (Go), CNCF; Go-library embedding only [V] | `openfga-sdk` 0.10.4, 2026-06-29, async and sync clients [V] | No (memory datastore is server-side) [V] | ReBAC first-class; RBAC as role types; ABAC via conditions [V] | **Native**: `ListObjects` (also streamed), `ListUsers`, `BatchCheck` [V] | Apache 2.0, v1.21.0 2026-09-20 [V] | `/docs/modeling/agents` and `/docs/modeling/agents/mcp-authorization` [V] | **Second built-in**: ReBAC makes (c)/(d) cheap and "A may call T for U" a stored tuple |
| Cedar (`cedarpy`) | Embedded Rust library; AWS Verified Permissions is the SaaS form | `cedarpy` 4.12.1, 2026-09-24, Py 3.10-3.14, unofficial (k9security) [V] | Yes, stateless: policies and entity slice passed per call [V] | permit/forbid, `in` hierarchies, `when` ABAC; ReBAC via entity parents the caller supplies | Type-aware partial evaluation RFC 0095 still "Accepted: TBD" [V]; AVP has no list API [U] | Apache 2.0, Cedar v4.13.0 2026-09-15 [V] | AWS AgentCore Policy chose Cedar (2026-05-20) [V]; multi-agent least-privilege blog (2026-07-06) [V] | Optional in-process policy-as-code adapter; AK owns storage |
| SpiceDB (AuthZed) | Server (Go); Postgres/CockroachDB/Spanner/MySQL/memdb [V] | `authzed` 1.25.0, 2026-07-14, gRPC, auto grpc.aio in a running loop; `InsecureClient` async bug open [V] | No | ReBAC with `+ & - ->`; caveats for ABAC [V] | **Native**: `LookupResources` (fine under ~10k), `LookupSubjects`, `CheckBulkPermissions` [V] | Apache 2.0, v1.56.2 2026-09-11 [V] | `langchain-spicedb` [U] | Near-equivalent to OpenFGA; BYO |
| OPA (Rego) | PDP sidecar (Go), or Rego compiled to WASM in-process | `opa-python-client` 2.1.0, 2026-08-18 (needs server) [V]; `opa-py-wasm` 1.2.1, 2026-09-16, wasmtime, in-process [V] | WASM route yes (needs an `opa build -t wasm` step) | Anything Rego expresses; ReBAC as data | None native; Compile API partial evaluation to SQL/UCAST [V] | Apache 2.0 [U] | None first-party; Permit and Topaz build on OPA | BYO (server) or optional WASM adapter |
| Cerbos | PDP (Go), YAML + CEL; embedded WASM PDP is JS/TS only and Hub-bound [V] | `cerbos`: sync and async, HTTP and gRPC; `is_allowed`, `check_resources`, `plan_resources` [V] | No for Python [V] | RBAC with derived roles, ABAC; ReBAC emulated via attributes | `PlanResources` returns an AST (always allowed / denied / conditional) with SQLAlchemy and LangChain adapters [V] | Apache 2.0, v0.55.0 2026-08-13 [V] | "Dynamic Authorization for AI Agents" (2025-06-30) [V] | Good BYO PDP adapter |
| Permit.io | SaaS control plane + PDP sidecar (OPA/OPAL); PDP needs a Permit API key [V] | `permit`, asyncio-native [V] | No | RBAC, ABAC (container PDP only), ReBAC [V] | `filter_objects` is a bulk-check post-filter; `authorized_users`; `get_user_permissions` [V] | SDK Apache 2.0; service proprietary | MCP authorization strategies (2025-12-29) [V] | BYO only |
| Oso Cloud | SaaS; the OSS library is deprecated (support and critical fixes only) [V] | `oso-cloud` 2.6.0, 2026-03-30 [V]; async unverified [U] | No (dev server is dev/test only) [V] | Polar: RBAC, ReBAC, ABAC | `list` (~10k) and `list_local` (SQL WHERE from fact bindings) [V] | SDK Apache 2.0; service proprietary | "Best practices of authorizing AI agents" [V] | BYO only |
| Topaz (Aserto) | OSS authorizer: OPA engine + embedded Zanzibar directory; sidecar [V] | `aserto` 0.32.2, 2025-03-25, sync and async [V] | No | OPA policies + relationship directory | Directory graph queries [U] | Apache 2.0, v0.33.20 2026-09-09 [V] | None found | BYO only |
| WorkOS FGA (was Warrant) | SaaS; OSS Warrant repo not archived [V] | `workos` (`workos.authorization.*`) [U] | No | Zanzibar + policies | Query API answers both (c) and (d) [V] | Apache 2.0 (OSS) | "Agents need authorization, not just authentication" (2026-02-17) [V] | BYO only |
| Ory Keto | Server (Go), Zanzibar, OPL [V] | `ory-keto-client` 25.4.0, 2025-11-09, OpenAPI-generated [V] | No | ReBAC | List API does not expand subject sets; needs Expand or repeated calls [V] | Apache 2.0, v26.2.0 2026-03-20 [V] | None found | BYO only; weakest list support |

## 2. Per-engine notes

### Casbin (`pycasbin`)

- Two PyPI names exist: `casbin` (last release 1.43.0, 2025-05-10) and `pycasbin` (2.8.0,
  2026-02-02, Python 3.8 to 3.13) [V]. The GitHub releases page tracks 2.x, so `pycasbin` is the
  live package [V]; the import name stays `casbin` [V].
- `AsyncEnforcer` since 1.23.0; async adapters live in `casbin.persist.adapters.asyncio` [V].
  Adapters: File and String built in; SQLAlchemy, Django, pymongo, Redis, DynamoDB, Peewee, Pony,
  Tortoise, Couchbase as separate packages; async variants for SQLAlchemy, Databases, Ormar and
  SQLModel [V]. `Model.load_model_from_text(text)` exists, so the model can be embedded in the
  framework rather than shipped as a file [V].
- RBAC: `g = _, _` role inheritance is transitive with a default max depth of 10; `g = _, _, _`
  adds a domain (tenant or, for AK, the agent as a scope); `g2` gives resource roles [V]. ABAC is
  expressed in the matcher over `r.obj.attr` [V].
- Listing: `get_implicit_resources_for_user`, `get_implicit_permissions_for_user`,
  `get_implicit_users_for_permission` enumerate policy rows, which answers (c) and (d) for RBAC
  grants only; ABAC matchers need `batch_enforce` over a candidate list [V].
- Agent story: the December 2025 blog frames "can this agent, on behalf of this user, invoke this
  tool with these parameters?" as the open problem and admits there are no first-class agent
  primitives yet [V]. ASF incubation started 2026-02-07 [V].
- Sources: https://pypi.org/project/pycasbin/ , https://github.com/casbin/pycasbin/releases ,
  https://casbin.apache.org/docs/rbac , https://casbin.apache.org/docs/rbac-api ,
  https://casbin.apache.org/docs/adapters , https://casbin.apache.org/blog/casbin-2025-ai-agent-era/ ,
  https://incubator.apache.org/projects/casbin.html

### OpenFGA

- Server v1.21.0 (2026-09-20); datastores: memory (default, lost on restart), Postgres, MySQL,
  SQLite; embeddable only as a Go library [V].
- `openfga-sdk` 0.10.4 (2026-06-29, Apache 2.0, Python 3.10+): async `OpenFgaClient`, a sync
  client under `openfga_sdk.sync`, `list_objects`, `list_users`, `batch_check`, streamed list
  objects [V].
- `ListObjects` has a fixed result limit; the streamed variant is bounded only by
  `OPENFGA_LIST_OBJECTS_DEADLINE`; cost rises with `and` / `but not` [V]. `ListUsers` answers (d) [V].
- First-party agent modelling: `/docs/modeling/agents` (agents as principals, task-based
  time-limited grants, RAG and MCP patterns) and `/docs/modeling/agents/mcp-authorization` (types
  `user`, `group`, `role`, `tool`; `can_call` with `user:*`, `role#assignee`, a `temporal_grant`
  condition; `ListObjects` to filter the tool list before the model sees it) [V]. This is the
  closest published model to AK's (agent, tool, user) triple.
- Token claims as contextual tuples: OpenFGA recommends passing IdP `groups`/`roles` at check
  time instead of syncing directories, noting they stay stale until token expiry [V].
- Sources: https://pypi.org/project/openfga-sdk/ , https://github.com/openfga/openfga ,
  https://openfga.dev/docs/getting-started/setup-openfga/configure-openfga ,
  https://openfga.dev/docs/getting-started/perform-list-objects ,
  https://openfga.dev/docs/getting-started/perform-list-users ,
  https://openfga.dev/docs/modeling/agents , https://openfga.dev/docs/modeling/agents/mcp-authorization ,
  https://openfga.dev/docs/modeling/token-claims-contextual-tuples

### Cedar and Amazon Verified Permissions

- Core is Rust, Apache 2.0, v4.13.0 (2026-09-15); only a WASM (JS/TS) binding is listed
  officially [V]. `cedarpy` 4.12.1 (2026-09-24) tracks Cedar 4.12.0, supports Python 3.10 to 3.14,
  and states it is "not officially supported by AWS"; `is_authorized(request, policies, entities)`
  takes the entity slice as a JSON list of `uid`, `attrs`, `parents` [V]. `cedar-policy` on PyPI is
  a 0.0.1 stub from 2023 [V]. `cedarling-python` (Janssen/Gluu) is an embeddable stateful Cedar PDP
  with pyo3 bindings [U].
- Language: `permit`/`forbid`, `principal in Group::"x"`, `resource in Album::"y"`, `when` for
  ABAC, action groups; `forbid` overrides `permit`; default deny [V]. Entity parents are transitive
  and act as groups or roles [V].
- Listing: type-aware partial evaluation (RFC 0095) targets "list resources a principal can
  access" and "list principals for a resource" with a concrete action, but the RFC header still
  says "Accepted: TBD" [V]. AgentCore Policy uses Cedar partial evaluation to filter tools before
  the LLM sees them [V]. AVP: boto3 `is_authorized` / `batch_is_authorized` (100 entities per
  batch) and no list-resources API [U].
- Agent story: "Why Policy in Amazon Bedrock AgentCore chose Cedar" (2026-05-20) [V]; "Enforce
  least-privilege authorization in multi-agent AI chains using Cedar" (2026-07-06, a three-layer
  model over AVP) [V]; `cedar-policy/cedar-for-agents` and `cedar-policy-mcp-schema-generator`
  exist on PyPI [U].
- Sources: https://pypi.org/project/cedarpy/ , https://github.com/cedar-policy/cedar ,
  https://docs.cedarpolicy.com/policies/syntax-policy.html ,
  https://docs.cedarpolicy.com/overview/terminology.html ,
  https://github.com/cedar-policy/rfcs/blob/main/text/0095-type-aware-partial-evaluation.md ,
  https://aws.amazon.com/blogs/security/why-policy-in-amazon-bedrock-agentcore-chose-cedar-for-securing-agentic-workflows/ ,
  https://aws.amazon.com/blogs/security/enforce-least-privilege-authorization-in-multi-agent-ai-chains-using-cedar/

### SpiceDB (AuthZed)

- Server v1.56.2 (2026-09-11), Go, Apache 2.0, no library mode [V]. `authzed` 1.25.0
  (2026-07-14); `create_channel` switches automatically between grpc and grpc.aio, but
  `InsecureClient` does not (issue #246, open since 2025-02-26) [V].
- Schema: `permission view = reader + editor`, `&`, `-`, and the `->` arrow for parent
  inheritance; caveats for ABAC [V]. APIs: `CheckPermission`, `CheckBulkPermissions`,
  `LookupResources` (paginated, slows past ~10k), `LookupSubjects` (no pagination),
  `ExpandPermissionTree` [V]. "Protecting a list endpoint" prescribes `LookupResources` under ~10k
  objects, else bulk-check post-filtering, else the Materialize product [V].
- Sources: https://github.com/authzed/spicedb , https://github.com/authzed/authzed-py ,
  https://github.com/authzed/authzed-py/issues/246 ,
  https://authzed.com/docs/spicedb/concepts/querying-data ,
  https://authzed.com/docs/spicedb/modeling/protecting-a-list-endpoint ,
  https://authzed.com/docs/spicedb/concepts/schema

### OPA

- Server v1.21.0 (2026-09-24) [V]. `opa-python-client` 2.1.0 (2026-08-18, MIT) offers
  `OpaClient` and `AsyncOpaClient` and requires a running OPA [V].
- WASM: `opa-py-wasm` 1.2.1 (2026-09-16, MIT, Python 3.10+, wasmtime, thread-safe pool, no OPA
  binary at runtime) [V]. The older `opa-wasm` (wasmer) is stale at 0.3.2 from 2022 [V]. OPA's WASM
  docs: some builtins such as `http.send` must be host-provided, data is loaded into module memory,
  no partial evaluation, and Python is not among the SDKs OPA lists [V].
- Data filtering: OPA's docs say allow/deny queries cannot answer "which resources" and point at
  partial evaluation via the Compile API to emit SQL or UCAST [V].
- Sources: https://pypi.org/project/opa-python-client/ , https://github.com/intuit/opa-py-wasm ,
  https://pypi.org/project/opa-py-wasm/ , https://www.openpolicyagent.org/docs/wasm ,
  https://www.openpolicyagent.org/docs/filtering

### Cerbos

- v0.55.0 (2026-08-13) [V]. `cerbos` SDK: sync and async, HTTP and gRPC, `is_allowed`,
  `check_resources`, `plan_resources`; needs a running PDP [V]. The embedded WASM PDP is JS/TS only
  and Hub-dependent: "for other platforms (Go, Python, etc.), use service PDPs" [V].
- `PlanResources` returns `ALWAYS_ALLOWED` / `ALWAYS_DENIED` / `CONDITIONAL` with an AST, and
  adapters exist for Prisma, Drizzle, Mongoose, Convex, LangChain/ChromaDB and SQLAlchemy [V].
- Agent story: "Dynamic Authorization for AI Agents" (2025-06-30): pass the delegating user's id
  and roles, query Cerbos for all tools at connect time, enable or disable each tool [V].
- Sources: https://github.com/cerbos/cerbos-sdk-python ,
  https://docs.cerbos.dev/cerbos/latest/api/index.html ,
  https://docs.cerbos.dev/cerbos-hub/deployments-epdp-rules.html ,
  https://www.cerbos.dev/blog/dynamic-authorization-for-ai-agents-guide-to-fine-grained-permissions-mcp-servers

### Permit.io, Oso, Topaz, WorkOS FGA, Ory Keto

- **Permit.io**: the PDP repo is Apache 2.0 (OPA + OPAL), run as `permitio/pdp-v2`, needs
  `PDP_API_KEY` and syncs with the Permit cloud [V]. Cloud PDP does RBAC and ReBAC only; ABAC needs
  the container PDP [V]. The `permit` SDK is asyncio-native; advanced queries: bulk check,
  `filter_objects` (Python and Go only, backed by `POST /allowed/bulk`), `authorized_users`,
  `get_user_permissions` [V]. MCP strategies blog (2025-12-29): hybrid RBAC + ABAC + ReBAC, zero
  standing permissions [V]. Sources: https://github.com/permitio/PDP ,
  https://docs.permit.io/sdk/python/quickstart-python/ ,
  https://docs.permit.io/overview/advanced-authorization-queries/ ,
  https://www.permit.io/blog/authorization-strategies-for-model-context-protocol-mcp
- **Oso**: the OSS library README confirms deprecation with support and critical fixes only [V]
  (deprecation date 2023-12-18 [U]). `oso-cloud` 2.6.0 (2026-03-30) [V]; the dev server is "for
  development and testing only" [V]. `list` for ~10k resources; `list_local` emits SQL WHERE from a
  YAML fact-to-table binding [V]. Agent docs: "Best Practices of Authorizing AI Agents" [V].
  Sources: https://github.com/osohq/oso , https://pypi.org/project/oso-cloud/ ,
  https://www.osohq.com/docs/develop/local-dev/oso-dev-server ,
  https://www.osohq.com/docs/app-integration/integrate-authorization/filter-lists ,
  https://www.osohq.com/learn/best-practices-of-authorizing-ai-agents
- **Topaz**: v0.33.20 (2026-09-09), Apache 2.0, OPA + embedded Zanzibar directory, sidecar;
  `aserto` 0.32.2 (2025-03-25) sync and async, `AuthorizerClient.decisions()` [V].
  Sources: https://github.com/aserto-dev/topaz ,
  https://www.topaz.sh/docs/software-development-kits/python/api-client
- **WorkOS FGA**: warrant.dev now reads "Warrant, Now WorkOS FGA" [V]; the OSS repo is Apache 2.0
  and not archived [V]; the FGA Query API answers "which resources can this user access" and "who
  has access" [V]; the 2026-02-17 blog models on-behalf-of access as the intersection of the agent's
  and the user's permissions [V]. Sources: https://warrant.dev/ , https://workos.com/docs/fga/query-language ,
  https://workos.com/blog/agents-need-authorization-not-just-authentication
- **Ory Keto**: v26.2.0 (2026-03-20), Apache 2.0, OPL [V]; the List API "does not expand subject
  sets", so nested groups need Expand or repeated calls [V]. Sources: https://github.com/ory/keto ,
  https://www.ory.com/docs/keto/guides/list-api-display-objects

### Standards and gateway products (2025-2026)

- **OpenID AuthZEN Authorization API 1.0** was approved as a Final Specification on 2026-01-12
  [V]. It defines `/access/v1/evaluation`, `/evaluations`, `/search/subject`, `/search/resource`
  and `/search/action` [V]. One `authzen` HTTP adapter would therefore cover every conformant PDP
  (Cerbos, Topaz, Permit and others advertise conformance [U]). Sources:
  https://openid.net/authorization-api-1-0-final-specification-approved/ ,
  https://openid.github.io/authzen/
- **Kong AI Gateway MCP Tool ACLs** (2026-01-14): gateway-level per-tool allow/deny by consumer
  group, and unauthorized tools are hidden from `tools/list` [V].
  https://konghq.com/blog/product-releases/mcp-tool-acls-ai-gateway
- **Amazon Bedrock AgentCore Policy** (Cedar, 2026-05) [V]; **Auth0 for AI Agents** (Token Vault,
  FGA for RAG, async approval) [U, verified separately in `identity-and-delegation.md`].

## 3. The list-filtering problem (question c)

A request/response PDP takes a fully specified (subject, action, resource) and returns allow or
deny. OPA's own docs separate "Evaluation: can subject do action to resource?" from "Search: which
resources match?" and say allow/deny queries cannot answer the latter [V]. AuthZEN codifies the same
split with separate `evaluation` and `search/*` endpoints [V]. Three ways out:

1. **Candidate set + N checks.** Fetch candidates from your own store, then bulk-check. Permit's
   `filter_objects` does exactly this over `/allowed/bulk` [V]; SpiceDB recommends it via
   `CheckBulkPermissions` once `LookupResources` gets slow [V]; Casbin's `batch_enforce` is the same
   idea for ABAC matchers. Cost is O(candidates), and it cannot paginate before filtering. For an
   agent catalog of tens to hundreds of agents this is cheap; the candidate set is the registry.
2. **Partial evaluation to a residual predicate.** Treat the resource as unknown, evaluate what you
   can, and return the leftover conditions as SQL or an AST: OPA Compile API [V], Cerbos
   `PlanResources` [V], Oso `list_local` [V], Cedar TPE (not yet stabilised) [V]. This only works
   when the decision hinges on resource attributes the data layer can filter on; relationship data
   that lives only in the engine cannot be pushed down.
3. **Reverse graph walk over stored tuples.** ReBAC engines own the relationships, so they walk
   backwards from the subject: OpenFGA `ListObjects` / `ListUsers` [V], SpiceDB `LookupResources` /
   `LookupSubjects` [V], WorkOS FGA Query API [V]. Keto is the outlier: its List API is a tuple
   filter that does not expand subject sets [V].

Implication for the `Authorizer` ABC: expose `list_resources(subject, action, resource_type)` and
`list_subjects(resource, action)` as optional capabilities that adapters declare (the
`KnowledgeCapabilities` / `SandboxCapabilities` house pattern). A Casbin adapter implements both for
RBAC grants (`get_implicit_resources_for_user`, `get_implicit_users_for_permission`) [V] and falls
back to candidate + batch enforce for ABAC; OpenFGA and SpiceDB adapters implement them natively; a
Cedar adapter only has the candidate-set fallback until TPE lands. The core always has route 1
available because the agent registry is the candidate set.

## 4. Expressing access levels (read < execute < write < admin)

Two encodings exist: an ordered level per grant (check `granted >= required`) or nested permission
sets (admin's set is a superset of write's, which is a superset of read's). Ordered levels are a
special case of nested sets. Every engine below expresses the nesting, so AK can keep the level as
an enum in core while each adapter maps it:

- **Casbin**: role inheritance is transitive [V], so `g, admin, writer` and `g, writer, reader`
  plus one `p` row per role (`p, reader, agent:A, read`; `p, writer, agent:A, write`;
  `p, admin, agent:A, admin`) makes admin imply write imply read. Per-agent scoping uses the domain
  form `g = _, _, _` (`g, alice, admin, agent:A`) [V].
- **OpenFGA**: concentric relations via computed usersets, `define viewer: [user] or editor`,
  `define editor: [user] or owner` [V]. For AK: `type agent { define admin: [user]; define
  can_configure: [user] or admin; define can_chat: [user] or can_configure; define can_discover:
  [user] or can_chat }` and `type tool { define can_invoke: [agent, user] }`, mirroring the
  documented MCP model's `can_call` [V].
- **SpiceDB**: `permission read = reader + write`, `permission write = writer + admin`,
  `permission admin = admin_rel`, with `->` arrows for inheritance from a parent [V].
- **Cedar**: hierarchy through entity parents (transitive) and action groups [V]. Either make
  `Role::"admin"` a child of `Role::"writer"` which is a child of `Role::"reader"`, or group
  actions (`action in Action::"writeLevel"`). `forbid` always overrides `permit` [V].

## 5. Is there an in-process "model + adapter" shape to mirror?

- **Casbin is the only surveyed engine with that exact shape**: a model (from file or
  `load_model_from_text`) plus a swappable policy adapter, with File and String adapters built in,
  Redis / DynamoDB / SQLAlchemy adapters as extras, and an async enforcer with async adapters [V].
  That maps one-to-one onto a `type: casbin` adapter with AK's own `in_memory` default and pip
  extras per storage backend. Its policy adapters could also be bypassed entirely by an AK
  `PolicyStore` over the shared DB drivers that feeds the enforcer with `add_policy` calls.
- **`cedarpy`** is in-process but stateless: policies and the entity slice are arguments to every
  `is_authorized` call [V], so AK would own storage (tuples become entity parents) and Cedar is the
  evaluator only. A clean fit for a second in-process adapter, at the cost of native listing.
- **`opa-py-wasm`** is in-process but needs the `opa` binary at build time and loads data per
  instance [V]; reasonable as an optional extra, not as a default.
- **Everything else needs a process**: OpenFGA [V], SpiceDB [V], Cerbos (Python must use the
  service PDP) [V], Oso (dev server not licensed for production) [V], Permit PDP (needs cloud sync)
  [V], Topaz, Keto, WorkOS.

## 6. Recommendation for the design

- **Built-in default (`in_memory` / `static`)**: AK's own evaluator over an in-core policy model
  (roles, level ordering, agent and tool grants) read from config or a `PolicyStore` on the shared
  drivers. This costs no dependency and is what tests and examples run. Casbin would be the
  engine-backed twin of it: `type: casbin` behind a `casbin` extra, wrapping `AsyncEnforcer` with
  an AK-embedded model text.
- **Second built-in**: OpenFGA (`openfga-sdk`, async, Apache 2.0, first-party agent and MCP
  modelling docs, native `ListObjects` / `ListUsers`). SpiceDB is the near-equivalent alternative
  and can share a ReBAC base adapter.
- **Optional in-process alternative**: `cedarpy` for policy-as-code ABAC and alignment with AWS
  AgentCore; note it is not an AWS-supported package.
- **BYO tier**: dotted-path `Authorizer` subclasses for Cerbos, Permit, Oso Cloud, WorkOS FGA,
  Topaz, Keto, plus one generic `authzen` HTTP adapter that covers any AuthZEN 1.0 PDP.

Whatever the engine, the two questions that must stay answerable in core without any engine are
"which registered agents can this principal see" (route 1 in section 3, the registry as candidate
set) and "does this agent's tool set include this tool for this principal" (the bind-time set,
see `ak-current-state.md`), because the CLI and in-memory topology must work with no server.
