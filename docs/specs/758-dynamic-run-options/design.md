# #758: Per-run computed run options: a callable form of Module.run_options

`Module.run_options` (#754) declares an agent's framework-native run options once, at load time, so
every run of that agent in every session gets the same `max_turns`, `RunConfig`, `plugins` or
`usage_limits`. This change lets the same fluent call also take a **factory**, a callable that
receives the agent, the session and the request list and returns the options for that run. The
factory's result is merged over the static dict and the adapters still write the keys Agent Kernel
owns last, so the declaration API, the reserved-key rule and the merge rule of #754 are unchanged;
what is added is one resolution step per run.

## Motivation

- **Options are static per agent today.** `Agent.run_options` is one dict
  (`ak-py/src/agentkernel/core/base.py:456`, property `:494`), filled by `Module.run_options`
  (`core/module.py:101-115`) at load time and read as-is by every adapter on every run: OpenAI
  `openai.py:214`, `:261`; LangGraph `langgraph.py:474-476`, `:531-532`; ADK through
  `_split_run_options(agent)` (`adk.py:126-134`, called at `:239`, `:292`, `:336`); Pydantic AI
  `pydanticai.py:191` and `_stream_run_options(agent)` (`:96-104`, called at `:244`); CrewAI
  `crewai.py:376`; smolagents `smolagents.py:160`.
- **Some options only make sense per run.** A turn cap, `UsageLimits`, `recursion_limit` or
  `max_steps` tied to a user's plan; SDK metadata carrying the session id (ADK
  `RunConfig(custom_metadata=...)`, OpenAI `RunConfig(trace_metadata=...)`); a model or
  `model_settings` chosen per request; a callback or plugin bound to a request-scoped tracer.
  None of these can be expressed by a value fixed at load time.
- **The existing per-request route changes behaviour, not values.** A static hook instance can read
  `Session.current()` inside its callbacks (#754 design, "Progress hooks and the AK session"), which
  lets *the hook* act per request; it cannot change what the runner passes as `max_turns` or
  `usage_limits`.
- **#754 left the seam open for exactly this.** Its design lists the callable form under Non-goals
  ("can be layered on this design later without changing the declaration or merge rule"), and the
  base helper already takes the options as a mapping rather than the agent:
  `Runner._native_kwargs(options, **ak_owned)` (`core/base.py:366`). The two adapter helpers that
  take the agent instead (`_split_run_options`, `_stream_run_options`) are private and take a mapping
  just as naturally.
- **Every adapter already has a place for the resolution.** Each `run` / `stream` sets the
  `ToolContext` before its native call (`openai.py:202`, `:252`; `langgraph.py:450`, `:511`;
  `pydanticai.py:178`, `:228`; `crewai.py:338`; `smolagents.py:139`; ADK inside
  `_setup_session_context`, `adk.py:231`), so a factory evaluated after that point can use
  `ToolContext.get()` as well as its own arguments.
- **A factory result can be validated where a static dict cannot be bypassed.** #754 rule 2 accepts
  that a caller mutating `agent.run_options` directly skips the reservation check. A factory result
  passes through `validate_run_options` on every run, so the factory path is checked in full.

## Requirements

### Declaration surface: `Module` (`core/module.py`)

- `run_options(agent, factory=None, /, **options) -> Self`.
  - `factory` is an optional positional-only callable. When given it is stored on the wrapped agent;
    keywords keep going to the static dict exactly as today. Both may be given in one call, or across
    calls.
  - A later factory **replaces** the earlier one, the way a repeated keyword wins per key. There is
    one factory per agent.
  - A non-callable `factory` raises `TypeError` naming the agent, at declaration.
  - A call with neither a factory nor keywords is a no-op that returns the module.
- Resolution of the wrapped agent, the `_native_agent_name` rule and chaining with `pre_hook` /
  `post_hook` are the existing `Module._wrapped` path (`:117-128`); nothing there changes.

### `Agent` (`core/base.py`)

- A type alias `RunOptionsFactory = Callable[[Agent, Session, list[AgentRequest]], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]`
  in `core/base.py`, exported beside `Agent`.
- `run_options_factory: RunOptionsFactory | None`, `None` by default, held beside `_run_options`
  and exposed as a property with a setter, so it has the same mutability contract as the
  `run_options` dict (#754, Resolved questions).
- `async resolve_run_options(session, requests) -> dict[str, Any]`: the options for one run.
  - Starts from a copy of `run_options` (the static dict is never mutated).
  - With no factory, returns that copy: an agent without a factory resolves to exactly its static
    dict, so every existing declaration behaves as today.
  - With a factory, calls `factory(self, session, requests)`, awaits the result when it is
    awaitable, and requires a `Mapping` (`TypeError` naming the agent otherwise).
  - Runs `validate_run_options` on the factory result, so a reserved key raises the same
    `ValueError` the declaration path raises, with the same message shape.
  - Merges the factory result **over** the static dict, top-level keys only: per-run knowledge is
    more specific than load-time knowledge. A factory that wants to keep a static dict-valued option
    (LangGraph `config`) returns a merged value itself.
  - A factory that raises is not caught: the exception propagates from `resolve_run_options`.

### Resolution point: the adapters

- Each of the twelve `run` / `stream` methods resolves **once**, with
  `options = await agent.resolve_run_options(session, requests)`, after the `ToolContext` is set
  and before anything reads the options, and uses that mapping everywhere it reads
  `agent.run_options` today. Exactly one factory call per native call.
- ADK: `run` and `stream` resolve before `_setup_session_context`, which gains an `options`
  parameter in place of its own `_split_run_options(agent)` call (`:239`);
  `_split_run_options` takes the mapping.
- Pydantic AI: `_stream_run_options` takes the mapping.
- LangGraph: `options.get("config")` feeds the existing `_merge_run_config`; the merged config
  still serves both the stream call and `aget_state`.
- CrewAI: `{"verbose": False, **options}`; smolagents: `_native_kwargs(options, reset=False)`.
- The AK-owned-keys-last rule, the LangGraph deep merge, the ADK constructor split and stream SSE
  copy, the Pydantic AI stream filter and every reserved-key list are unchanged.
- Trace runners: no change (they delegate to `super().run` / `super().stream`).

### Error surfacing

- Everything `resolve_run_options` raises (a factory's own exception, a non-mapping result, a
  reserved key) surfaces the way a framework error does on that adapter: in `run`, the adapter's
  existing `except Exception` turns it into a `user_facing_error_message` reply; in `stream`, it
  propagates (the OpenAI, LangGraph and Pydantic AI streams have no `except` around the native
  call, and the ADK stream wraps nothing in `try`). Every run of that agent fails the same way until
  the factory is fixed, the same loudness #754 chose for unknown keys.

### Concurrency and cost

- The factory is one object shared by every concurrent run of the agent; it must keep no per-run
  state on itself. It may read `Session.current()`, `ToolContext.get()` and the acting-user cache,
  all of which are set for the run by the time it is called.
- One factory call per run, on the hot path before the model call. Agents without a factory pay
  one dict copy, as today. Documented; no caching is added (a factory that wants to cache does so
  itself).

### Configuration

- **No new configuration.** The factory is code declared at module load, like hooks and the static
  options; nothing in `AKConfig` changes.

### Documentation and skills

- `docs/docs/core-concepts/runner.md` ("Per-agent native run options"): a "Computed per run"
  paragraph with the signature, the merge order and the error surfacing.
- `docs/docs/core-concepts/module.md` and `agent.md`: the factory parameter and the
  `run_options_factory` property.
- `.agents/skills/ak-dev-architecture/SKILL.md` (Agent and Module entries) and
  `.agents/skills/ak-dev-new-framework-integration/SKILL.md` (step 3: resolve once with
  `agent.resolve_run_options` and pass the mapping to the helpers; the checklist item).
- `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` and `ak-build/SKILL.md`: one
  paragraph each beside the run-options block.
- Example: a new `examples/cli/openai-dynamic-run-options/` demo, the shape of the six
  `<framework>-run-options` demos, whose factory sets `max_turns` from the session, adds per-session
  SDK metadata, and bumps a `factory_runs` counter; its `Run stats:` line reads the resolved limit
  back from the volatile cache the factory wrote, so `demo_test.py` asserts on the computed value and
  on `factory_runs`. It is indexed like its siblings (the examples overview, the OpenAI framework
  page, the e2e matrix). The six existing examples are untouched: the mechanism is
  framework-agnostic and identical in each.

### Testing

- `ak-py/tests/test_base.py`: no factory returns a copy of the static dict; a sync factory and an
  async factory are merged over it; the factory receives the agent, session and request list; a
  non-mapping result raises `TypeError`; a reserved key from a factory raises the same `ValueError`
  as declaration; a raising factory propagates; the static dict is unchanged after resolution.
- `ak-py/tests/test_module.py`: `run_options(agent, fn)` stores the factory;
  `run_options(agent, fn, max_turns=3)` stores both; a second factory replaces the first; a
  non-callable raises `TypeError`; chaining with the hook methods still returns the module.
- Per adapter, in the six runner test files: a factory's result reaches the native call and wins
  over a static key; ADK additionally routes a factory-supplied `plugins` to the `Runner`
  constructor; `resolve_run_options` is invoked exactly once per `run` and per `stream`.
- **Consumer change the tests must absorb**: the adapters now call
  `await agent.resolve_run_options(session, requests)`, and a bare `MagicMock()` agent returns a
  non-awaitable `MagicMock` from that call. The runner tests build 83 such agents inline (46 in
  `test_openai_runner.py`, 16 in `test_pydanticai_runner.py`, 10 in `test_smolagents_runner.py`, 6
  in `test_langgraph_runner.py`, 2 each in `test_adk_runner.py` and
  `test_trace_langfuse_langgraph.py`, 1 in `test_crewai_runner.py`) plus a handful of helper
  functions. The plan replaces the inline ones with a per-file `_mock_agent()` helper that sets
  `run_options = {}` and an `AsyncMock` `resolve_run_options` returning it, which is a test cleanup
  the #754 spec already noted as fragile (Runner rule 5).

## Non-goals

- **Per-request options on the chat request envelope** (rejected in #754 for the same reasons:
  not serialisable, every service signature changes).
- **A deep merge between the static dict and the factory result.** Top-level only; a factory that
  wants to extend a static `config` returns the combined value (open question below).
- **Caching or memoising factory results**, or a per-execution-mode factory.
- **Changing the AK-owned-keys-last rule, the reserved-key lists, or unknown-key handling.**
- **Making the factory reachable from `AKConfig`.**

## Resolved questions

Decisions taken with the requester on 2026-09-25 (the recommended answer in each case); the rejected
alternative is recorded so a reviewer can see it was considered.

- **Merge depth between static and factory results: top-level replace.** One rule, and a factory
  has the static dict in hand through `agent.run_options` when it wants to extend a dict-valued
  option such as LangGraph `config`. Rejected: a deep merge of dict values, which would add a second
  merge rule beside `_merge_run_config` and make "which `callbacks` list wins" a per-key question.
- **A reserved key from a factory raises on the run.** The run is the earliest point the result
  exists, and it fails every request until the factory is fixed, the loudness #754 chose for unknown
  keys. Rejected: logging once and dropping the key, which would let a wrong factory run silently.
- **`run_options_factory` is a settable property**, parity with the mutable `run_options` dict.
  Rejected: read-only with `Module.run_options` as the sole writer; direct assignment is documented as
  the caller's responsibility exactly as direct dict mutation is.
- **The factory receives the request list the runner receives**, after pre-hooks, since that is what
  the run will actually use. Rejected: the caller's original list, which the runner never sees.
