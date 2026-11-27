---
name: ak-dev-new-authorizer
description: >
  Step-by-step guide for adding a new built-in authorizer to Open Agent Kernel's authorization layer
  (beyond static). Use this skill when a policy engine (Casbin, OpenFGA, Cedar, an AuthZEN service)
  needs a short `authorization.type` name of its own; the four reserved names are where those
  land. It starts with the check that a policy held somewhere else is a dotted-path Authorizer
  first. Covers the Authorizer contract (agent levels, tool decisions, the list forms, validate),
  what the access gate does with the answers, the config section, replacing a reserved name with a
  factory branch, the AuthorizerContract test suite, and docs.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Authorizer

This guide walks through adding a built-in backend to the authorization layer
(`ak-py/src/agentkernel/identity/authz/`). Use `StaticAuthorizer` (`identity/authz/static.py`), the one
backend that ships, as the reference: it reads its policy from the `authorization.static` section,
resolves `tag:` entries against the agent registry, and checks its policy when agents load. The
`ak-dev-architecture` skill's *Identity and Access* section covers the principal, the access gate and
the surfaces this guide builds on; `ak-dev-new-identity-provider` covers who the principal is, which an
authorizer never decides.

## Existing Backends

| Backend | `type` value | Policy lives in | Extra |
|---|---|---|---|
| Static | `static` | `authorization.static`: `grants` (subjects, agents, level) and `tools` (tiers, allow, deny per agent) | none |
| Bring-your-own | dotted path, e.g. `myapp.authz.TeamAuthorizer` | wherever the subclass keeps it; its own settings in the block's `model_extra` | the user's own |
| Reserved | `casbin`, `openfga`, `cedar`, `authzen` | refused with `AKConfigError` ("not shipped yet; use a dotted path") until a branch lands | |

## Do You Need a Built-in?

Answer this before writing code: **a policy held somewhere else is a dotted-path `Authorizer`
before it is a built-in.** `authorization.type: myapp.authz.TeamAuthorizer` hands the subclass the
whole `authorization` block, which keeps keys it does not define (`_AuthorizationConfig` is
`extra="allow"`, and its validator refuses unknown keys only for a built-in type), so the subclass reads
its own settings from `config.model_extra`. That path is documented for users under *Bring your own
authorizer* in `docs/docs/advanced/identity-and-access.md` and needs no core change.

Add a built-in only for an engine broadly used enough to deserve a short name, tests and docs. The
four engines the design names already have their names reserved in `_RESERVED_ENGINES`
(`identity/authz/factory.py`); a built-in for one of them replaces its reserved entry with a branch. A
fifth engine adds its name the same way.

## The Contract

`Authorizer` (`identity/authz/base.py`) answers two questions. The rules around them are what matter:

- **`async agent_level(principal, agent_id) -> AccessLevel | None`**: the highest level (`read`,
  `write` or `admin`, an ordered `AccessLevel`) the policy gives the principal on the agent, or `None`
  for none. `agent_id` is the descriptor's `id`. The anonymous principal is asked about too (a request
  nothing authenticated), and the policy may give it a level.
- **`async check_tool(principal, agent_id, tool) -> Decision`**: whether the principal may call one
  tool. `tool` is the name the agent's descriptor reports (`Agent.get_tool_names()`: the name the
  application declared, without a prefix an adapter adds to serve it, such as Claude's `mcp__ak__`).
  A refusal is `Decision(allowed=False, reason=...)`. The reason is what the model reads in place of the
  tool's result: name the tool and the rule that refused it ("Tool 'refund' requires level admin; the
  current principal has write"), never anyone else's access or the engine's internals. An approval
  needs no reason.
- **Answer levels, never refusals.** Return `None`; do not raise `PermissionError` or
  `AgentNotFoundError`. The access gate (`identity/authz/gate.py`, `AccessGate`) turns `None` into one of
  two answers by the agent's `visibility`, which is the descriptor's and not the policy's: an agent the
  principal may not see raises `AgentNotFoundError` (the 404 of an agent that does not exist, text
  included), one it may see and holds no level on raises `PermissionError` (a 403). `public` admits
  everyone, `internal` every non-anonymous principal, `private` (the default) nobody. Visibility never
  confers a level.
- **The list forms have defaults.** `filter_tools(principal, agent_id, tools)` asks `check_tool` per
  tool and `visible_agents(principal, candidates)` asks `agent_level` per candidate, each keeping the
  order given. Override them when the engine answers a list in one call (a relationship store's
  `list-objects`), and keep the results equal to the walk: the contract asserts it. The gate builds
  every listing and each run's `ToolFilter` from these two (`visible_agents_async`, `narrow_async`,
  `tool_filter_async`), plus `check_tool` for the reason of each refused tool.
- **`capabilities: ClassVar[AuthorizerCapabilities]`** declares `lists_resources` (the backend lists
  the agents a principal may see itself). Set it `True` when you override `visible_agents` with a
  native listing. Nothing branches on it today: the gate calls `visible_agents` either way, and the
  contract only checks that it is declared.
- **`validate(agents, descriptors=None) -> list[str]`**: called by
  `AccessGate.validate_configuration` as a module loads and when a surface mounts. Raise
  `AKConfigError` for what cannot work for a hosted agent (the static backend refuses a tool policy that
  names a tool its agent does not have, since a misspelt `deny` would deny nothing); return findings,
  each a full sentence naming the setting, for what only matches nothing yet (a grant on an agent id or
  a `tag:` no descriptor carries, a `role:` subject with no role mapper configured). The gate logs each
  finding once. `descriptors` is `None` while not every agent has registered (a module that is one of
  several), and the findings that need every descriptor are left out then. A backend whose policy lives
  in an engine it cannot read back keeps the default, which finds nothing.
- **Decide from the principal you are handed and store nothing about it.** Its `subject`, `provider`,
  `namespace`, `groups`, `roles` and `claims` are what there is. `roles` come only from the configured
  role mapper (`identity.role_mapper`); a backend is free to ignore them. A messaging sender
  (`provider: messaging:<platform>`) carries a platform id as its subject, which can collide with a user
  subject, so the static backend never matches a `user:` subject for one; an engine that maps subjects
  keeps the provider in the key for the same reason.
- **No configuration reads in methods.** `from_config(cls, config: _AuthorizationConfig)` turns the
  block into constructor arguments, and the constructor raises `AKConfigError` on unusable settings, so
  a bad policy stops the process at startup, not on the first request.
- **One instance, more than one event loop.** `AuthorizerFactory.get()` shares one authorizer per
  process. It is awaited on the server's loop for a run, and on a short-lived loop when synchronous code
  asks from inside a coroutine: `AccessGate._wait` runs the question with `asyncio.run` on a worker
  thread (and `run_async_sync` outside any loop). A backend that talks to an engine must not bind a
  client to the loop it was first awaited on: no `httpx.AsyncClient` (or an SDK's async client) held on
  the instance. Use a synchronous client off the loop (`asyncio.to_thread`) or one opened per call.

## Step-by-Step

### 1. Create the Backend File

`identity/authz/<name>.py`, a subclass of `Authorizer` with `agent_level`, `check_tool` and a
`from_config` classmethod. When the policy needs agent metadata (a `tag:` entry needs an agent's
tags), take it the way `StaticAuthorizer` does: a hosted agent's own descriptor first
(`Runtime.current().registry.get(agent_id)`), and the registry's listing, read once per question and
off the event loop (`asyncio.to_thread`), only for an agent another process hosts. A system tool
declares the level it needs (`SystemTool.tier`); the static backend reads those tiers
(`SystemToolFactory.get_all(agent_id)`) as defaults a policy's `tiers` entry overrides, and an engine
backend should give the same defaults or document why not.

### 2. Configuration

In `ak-py/src/agentkernel/core/config.py`:

- Add a `_<Name>AuthorizerConfig(BaseModel)` with the engine's settings, every field with a real
  `description` and defaults that keep existing YAML working, and a `<name>:
  _<Name>AuthorizerConfig | None` field on `_AuthorizationConfig`, beside `static`.
- Extend `_check_authorizer_settings`: the section is required when `type` names the backend (as
  `static` requires `authorization.static`), and the unknown-key message names the block's settings
  ("it takes type and static"), so add the new section to it.
- Update the `type` field's description, which lists the built-ins and the reserved names and
  surfaces in generated docs: move the name from reserved to built-in.

### 3. Register with the Factory

In `identity/authz/factory.py`, add an `elif key == "<name>":` branch beside `static`, with the import
inside `require_extra("<extra>", "authorization.type: <name>")` (`core/util/factory.py`) when the
engine needs an SDK, add the name to `_BUILTIN_AUTHORIZERS`, and remove it from `_RESERVED_ENGINES`.
The dotted-path branch stays last: it hands a bring-your-own authorizer the whole block
(`resolve_dotted(authorizer_type, base=Authorizer)(authorization_config)`).

Export the class through the lazy table in `identity/__init__.py` (`_LAZY_EXPORTS` and the
`TYPE_CHECKING` imports), as `StaticAuthorizer` is, so `import agentkernel.identity` stays free of
optional imports.

### 4. Optional Dependency Extra

An engine SDK goes in an extra of its own in `ak-py/pyproject.toml` (or `auth`, when it is small and
identity-related), matched to its `require_extra(...)` call, with the bounds develop pins every
dependency with.

### 5. Tests

- **Contract:** subclass `AuthorizerContract` (`identity/authz/testing.py`, deliberately not exported
  from `agentkernel.identity`) and override the `authorizer` fixture. The suite states one policy in
  the static backend's terms (`GRANTS` and `TOOLS` over the agents in `DESCRIPTORS`) and asserts what
  each of its principals may do; load the equivalent policy into the engine (a fake of it, never the
  network) and leave the assertions as they are. `ak-py/tests/test_authorizer_static.py` runs it twice
  (`TestStaticAuthorizerContract` with the policy handed over, `TestStaticAuthorizerContractFromConfig`
  through `from_config`); a new backend's file does the same.
- **Backend-specific:** the engine's own corners, the way `TestStaticAgentLevels`,
  `TestStaticToolDecisions`, `TestSystemToolTiers` and `TestStaticFromConfig` cover the static backend:
  how a registry read happens (once, off the loop, none for a hosted agent), each refusal reason, and
  what `validate` raises and finds.
- **Factory and config:** beside `TestAuthorizerFactory` in `test_authorizer_static.py` (the short
  name, matched whatever its case; the extra named on a failed import; the reserved names that remain;
  the dotted path receiving the whole block) and `TestAuthorizationConfig` in `test_config.py` (the
  section required, its unknown keys refused, the environment form `AK_AUTHORIZATION__<NAME>__*`).
  `AuthorizerFactory` and `AccessGate` cache process-wide: reset both around a test that calls `get()`.
- **Through the gate:** `test_access_gate.py`'s `TestTheConfiguredGate` runs the real factory and the
  static backend's own lookups; add the same for the new backend when its lookups differ. The
  `authorization` fixture in `ak-py/tests/conftest.py` installs a `static` block on the live
  configuration for the surface tests, which need no change.

### 6. Documentation

- `docs/docs/advanced/identity-and-access.md`, *Authorization*: a subsection with the block, what the
  engine is asked and when, the extra, and its startup checks under *Startup checks*; drop the name from
  the reserved list at the end of *Bring your own authorizer*.
- `docs/docs/core-concepts/configuration.md` (*Authorization*) and `ak-py/README.md` (*Authorization*):
  the new section and the `type` value.
- `ak-dev-architecture/SKILL.md`, *Identity and Access*: the backend in the authorizers list and the
  factory mapping.
- The bundled skills: `ak-add-capabilities` (*Granting access* in its *Identity* section) and
  `ak-cloud-deploy` (its identity section), with their `evals/evals.json` when an expected output names
  the backends.
- Landing page inventories: a third-party engine gets an item in the **Observability, safety &
  testing** row of `INTEGRATION_ROWS` (`docs/src/components/HomeSections/integrations.data.tsx`) with
  role `Identity`, the Guard stage's identity set, and the backend joins the points of the **Identity
  and access** capability under Guard in `docs/src/pages/features.tsx`. Logo sourcing and the build
  check are in `ak-dev-sync-docs-from-branch`.

## Gotchas

- **Fail closed.** When the engine cannot answer, raise; never fall back to an approval. A run whose
  level or tool filter cannot be decided does not start (`Runtime` asks before the pre-hooks), and a
  tool gate that cannot read the run's filter refuses the call (`tool gate failed: <type>`).
- **The policy sees declared tools only.** A tool that exists only inside a run (an MCP server's, a
  toolset resolved per run) has no name a policy could offer; what each framework does with such a call
  under the block is the adapters' business (the identity page's *Tool policy* section lists it). Do not
  try to resolve those names in the backend.
- **A hosted agent's facts come from its own descriptor.** An overlaid `registry.agents.<id>` setting
  (tags included) reaches the hosted agent's descriptor, so reading the agent registry's store for a
  hosted agent can only be slower or staler.
- **`tag:` and `role:` that match nothing are warnings, not errors.** Another process may host the
  agent, or the role mapper may be configured there; `validate` raises only for what cannot work for an
  agent this process hosts.

## Checklist

- [ ] A dotted-path `Authorizer` ruled out first
- [ ] `identity/authz/<name>.py`: `agent_level` returns `None` for no level, `check_tool` refusals carry a reason naming the tool and the rule, list overrides equal the walk, `capabilities` declared
- [ ] `from_config` builds from the block; the constructor raises `AKConfigError` on unusable settings; no client bound to an event loop
- [ ] `validate` raises for what cannot work for a hosted agent and returns findings for what matches nothing yet
- [ ] Config: `_<Name>AuthorizerConfig` and its field on `_AuthorizationConfig`, `_check_authorizer_settings` and the `type` description updated (`core/config.py`)
- [ ] Factory branch behind `require_extra(...)`, name moved from `_RESERVED_ENGINES` to `_BUILTIN_AUTHORIZERS`, lazy export in `identity/__init__.py`
- [ ] `AuthorizerContract` subclass on a fake engine, backend-specific tests, factory and config tests
- [ ] Docs: `identity-and-access.md`, `configuration.md`, `ak-py/README.md`, architecture skill, bundled skills and evals, landing inventories
- [ ] `cd ak-py && uv run pytest tests/test_authorizer_*.py tests/test_access_gate.py tests/test_config.py` and `make lint-check-all` clean
- [ ] Changelog fragment `changelog.d/<issue>.added.md` (`+<short-slug>.added.md` when the PR has no issue), written for users with `ak-dev-sync-changelog-from-branch`
