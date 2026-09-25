# #758: Per-run computed run options: a callable form of Module.run_options: Implementation Spec

Adds one resolution step to the #754 seam: `Module.run_options` also takes a factory callable, stored
on the agent, and every adapter resolves the options for a run through `Agent.resolve_run_options`
before building its native call. Requirements are `design.md` (with its Resolved questions). Line
numbers are against `develop` at `a244d2b0`, which contains #754 as merged in #756.

## Design

Every component is a member added to an existing class. No module-level function is introduced;
the one new module-level name is a type alias.

### `Agent` (`ak-py/src/agentkernel/core/base.py`)

```python
import inspect                                                              # new import
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Iterator, Mapping   # + Awaitable, Callable

RunOptionsFactory = Callable[["Agent", Session, list[AgentRequest]], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]
"""A per-run options factory: (agent, session, requests) -> mapping, sync or async. Defined just before Agent."""


class Agent(ABC):
    def __init__(self, name: str, runner: Runner):
        ...
        self._run_options: dict[str, Any] = {}                     # existing, :456
        self._run_options_factory: RunOptionsFactory | None = None # new

    @property
    def run_options_factory(self) -> RunOptionsFactory | None:     # new, after run_options (:494)
        """The per-run options factory declared for this agent, or None. Settable; parity with run_options."""
        return self._run_options_factory

    @run_options_factory.setter
    def run_options_factory(self, factory: RunOptionsFactory | None) -> None:
        self._run_options_factory = factory

    async def resolve_run_options(self, session: Session, requests: list[AgentRequest]) -> dict[str, Any]:   # new
        """The run options for one run: a copy of the static dict with the factory's result merged over it."""
        options = dict(self._run_options)
        factory = self._run_options_factory
        if factory is None:
            return options
        produced = factory(self, session, requests)
        if inspect.isawaitable(produced):
            produced = await produced
        if not isinstance(produced, Mapping):
            raise TypeError(f"Run options factory for agent '{self.name}' returned {type(produced).__name__}, expected a mapping")
        self.validate_run_options(produced)
        options.update(produced)
        return options
```

Rules:

1. **No factory means the static dict, copied.** An agent that never declared a factory resolves to
   `dict(self._run_options)`, so every existing declaration produces the native call it does today.
   The copy also means the static dict is never mutated by resolution.
2. **The factory is called exactly once per resolution**, with the AK agent, the session and the
   request list the runner received (design, Resolved questions). Sync and async factories are both
   accepted; `inspect.isawaitable` decides.
3. **The result is validated in full.** `validate_run_options` runs on the factory result, so a
   reserved key raises the existing `ValueError` (message shape unchanged; LangGraph's override adds
   its top-level `RunnableConfig` and nested `thread_id` checks for free).
4. **Merge is top-level, factory over static.** `options.update(produced)`; a dict-valued option in
   the result replaces the static one wholesale.
5. **Nothing is caught.** A factory's own exception, a non-mapping result and a reserved key all
   propagate out of `resolve_run_options`; the adapter decides how they surface (Error handling).
6. `RunOptionsFactory` is added to the `from .base import Agent, Runner, Session` line in
   `core/__init__.py:14`, which the top-level package re-exports through `from .core import *`
   (`agentkernel/__init__.py:21`), so applications annotate factories as `agentkernel.RunOptionsFactory`.
   The alias lives just before the `Agent` class in `base.py`, naming it through a forward reference, so the
   `Agent` annotations that use it resolve without quoting.

### `Module` (`ak-py/src/agentkernel/core/module.py`)

```python
from .base import Agent, RunOptionsFactory                                   # + RunOptionsFactory

class Module(ABC):
    def run_options(self, agent: Any, factory: RunOptionsFactory | None = None, /, **options: Any) -> Self:   # signature change
        wrapped = self._wrapped(agent)                                        # existing, :117-128
        if factory is not None and not callable(factory):
            raise TypeError(f"Run options factory for agent '{wrapped.name}' must be callable, got {type(factory).__name__}")
        wrapped.validate_run_options(options)                                 # existing
        if factory is not None:
            wrapped.run_options_factory = factory
        wrapped.run_options.update(options)                                   # existing, :114
        return self
```

1. `factory` is positional-only. A keyword `factory=` therefore still lands in `**options` (Python
   routes a keyword matching a positional-only name into `**kwargs`), so no existing keyword usage
   changes meaning and no native option name is shadowed.
2. A later factory replaces the earlier one (one per agent); keywords keep merging per key.
3. A non-callable factory raises `TypeError` at declaration, before anything is stored, and a reserved
   keyword raises the existing `ValueError` before the factory is stored either. A call with neither a
   factory nor keywords stores nothing and returns the module.
4. `pre_hook`, `post_hook`, `_wrapped` and `_native_agent_name` are unchanged.

### Resolution in the adapters

Each `run` / `stream` gains exactly one line, `options = await agent.resolve_run_options(session,
requests)`, placed **after the request-shape early returns** (so an empty request never invokes the
factory) and **before the framework-context load**, then reads `options` wherever it reads
`agent.run_options` today. The `ToolContext` is already set at that point in every adapter
(`openai.py:202`, `:252`; `langgraph.py:450`, `:511`; `pydanticai.py:178`, `:228`; `crewai.py:338`;
`smolagents.py:139`), so a factory may call `ToolContext.get()`.

- **OpenAI** (`openai.py:214`, `:261`): `kwargs = self._native_kwargs(options, session=..., context=produced)` in both.
- **LangGraph** (`langgraph.py:474-476`, `:531-532`): `config=self._merge_run_config(config, options.get("config"))`
  and `self._native_kwargs(options, ...)`; the stream keeps `merged_config` for `aget_state` as today.
- **Google ADK** (`adk.py`): `_split_run_options` becomes `_split_run_options(cls, options: Mapping[str, Any])`
  (`:126-134`). `_setup_session_context` gains a trailing `options: Mapping[str, Any] | None = None`
  parameter and calls `self._split_run_options(options or {})` at `:239` instead of reading the
  agent. `run` (`:291-292`) and `stream` (`:334-336`) resolve first, pass `options` into
  `_setup_session_context`, and take the run side from `self._split_run_options(options)`. The ADK
  `ToolContext` is created inside `_setup_session_context` (`:231`), so on this adapter the factory
  runs before it exists; `ToolContext.get()` is therefore not available to an ADK factory, and the
  docs say so. `get_response` and `_stream_run_config` are unchanged.
- **Pydantic AI** (`pydanticai.py`): `_stream_run_options` becomes `_stream_run_options(self, options: Mapping[str, Any])`
  (`:96-112`, `dict(options)` instead of `dict(agent.run_options)`); `run` (`:191`) uses
  `self._native_kwargs(options, ...)`; `stream` (`:244`) uses `self._native_kwargs(self._stream_run_options(options), ...)`.
- **CrewAI** (`crewai.py:376`): `Crew(**self._native_kwargs({"verbose": False, **options}, ...))`.
- **smolagents** (`smolagents.py:160`): `self._native_kwargs(options, reset=False)`.
- **Trace runners**: no change; they delegate to `super().run`, which resolves.
- `Runner._native_kwargs` (`core/base.py:366`) is unchanged.

### Consumer changes

- **`Runtime`, `AgentService`, `ChatService`, the pipeline, the deployment adapters, the session
  stores, `AKConfig`**: no change.
- **Tests, one real consequence**: the adapters now await `agent.resolve_run_options(...)`, and a
  bare `MagicMock()` returns a non-awaitable `MagicMock` for that call, so every runner test that
  hands a bare mock to a runner would fail with `TypeError: object MagicMock can't be used in 'await'
  expression`. The runner tests build such agents inline 83 times (46 in `test_openai_runner.py`,
  16 in `test_pydanticai_runner.py`, 10 in `test_smolagents_runner.py`, 6 in
  `test_langgraph_runner.py`, 2 each in `test_adk_runner.py` and
  `test_trace_langfuse_langgraph.py`, 1 in `test_crewai_runner.py`) and through eight helper
  functions (`_mock_agent` in the LangGraph, ADK, Pydantic AI, CrewAI and trace files;
  `_mock_stream_agent`, `_capturing_stream_agent`, `_mock_stream_events_agent`). Every mock agent
  handed to a runner must expose two things: `run_options`, a real dict, and
  `resolve_run_options`, an `AsyncMock` whose `side_effect` returns `dict(agent.run_options)` so a
  test that assigns `mock_agent.run_options = {...}` after construction still gets it. The existing
  helpers gain those two lines; the inline mocks in the OpenAI and smolagents files are replaced by a
  per-file `_mock_agent()` helper with the same contract. The CrewAI spec-restricted mock adds
  `"resolve_run_options"` to its spec list. Tests that use real agents (`OpenAIAgent` in the
  `RunHooks` tests, the module-level tests) need nothing.

### Config changes

No config changes. The factory is code declared at module load, like hooks and the static options.

### Documentation changes

- `docs/docs/core-concepts/runner.md`: a "**Computed per run.**" paragraph inserted before
  "**Progress: two paths.**" (`:295`) in the "Per-agent native run options" section: the signature,
  the merge order, error surfacing, the shared-instance rule, the ADK `ToolContext` caveat.
- `docs/docs/core-concepts/module.md` ("Native run options", `:131-155`): the factory parameter with
  a two-line example; `docs/docs/core-concepts/agent.md` ("Run options", `:263`):
  `run_options_factory` and `resolve_run_options`.
- `.agents/skills/ak-dev-architecture/SKILL.md`: the Agent entry (`:92`) gains
  `run_options_factory` / `resolve_run_options`; the Module entry (`:115`) gains the positional-only
  factory. `.agents/skills/ak-dev-new-framework-integration/SKILL.md`: step 3's bullet (`:122`)
  becomes "resolve once with `await agent.resolve_run_options(session, requests)` after the
  early returns and pass the mapping to `_native_kwargs` and your helpers"; the checklist item
  (`:426`) says the same.
- `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` (`:637` block) and
  `ak-build/SKILL.md` (`:396` block): one paragraph each showing the factory form, plus a
  `cap-run-options-factory` eval entry in `ak-add-capabilities/evals/evals.json` keyed on
  `def options_for(` and `module.run_options(agent, options_for`.
- **Example**: a new `examples/cli/openai-dynamic-run-options/` (`README.md`, `build.sh`, `demo.py`,
  `demo_test.py`, `pyproject.toml` named `cli-openai-dynamic-run-options`, `uv.lock`), scaffolded from
  `examples/cli/openai-run-options`. `demo.py` keeps that demo's weather agent, `_bump` helper and
  `ProgressHooks`, and adds `options_for(agent, session, requests)`, which bumps a `factory_runs`
  counter, returns `{"max_turns": 10, "run_config": RunConfig(trace_metadata={"session_id": session.id})}`
  for a session whose id starts with `guest` and `{"run_config": RunConfig(trace_metadata={"session_id": session.id})}`
  otherwise, and records the effective `max_turns` (its own or the static one) in the volatile cache.
  The declaration is `run_options(weather_agent, options_for, max_turns=MAX_TURNS, hooks=ProgressHooks())`,
  showing a factory and static keywords in one call; the post-hook's `Run stats:` line reads
  `max_turns` from the cache and appends `factory_runs`. `demo_test.py` asserts
  `stats["factory_runs"] >= 1`, `stats["max_turns"] == 25` (the harness session is not a guest
  session) and `stats["tool_calls"] >= 1`. The README explains the factory contract, the merge
  order, the shared-instance rule and the guest-session switch. Indexing follows the six siblings:
  a `type: cli` entry in `.github/test-config.yaml`, a bullet in the run-options block of
  `docs/docs/examples/overview.md`, and a link in the "Example" section of
  `docs/docs/frameworks/openai.md`. The six existing examples are unchanged.

### Behavioural changes

All intentional.

1. **`Module.run_options` accepts an optional positional-only factory.** Keyword-only usage is
   unchanged; a second positional argument, a `TypeError` today, is now the factory.
2. **`Agent` gains `run_options_factory` and `resolve_run_options`.** Both default to the
   no-factory behaviour.
3. **Every adapter resolves once per `run` / `stream`.** With no factory the resolved mapping is a
   copy of the static dict, so the native call is keyword-for-keyword what it is today; the existing
   `call_args` assertions guard this.
4. **Three private helpers change signature**: ADK `_setup_session_context` gains a trailing
   `options` parameter and `_split_run_options` takes a mapping; Pydantic AI `_stream_run_options`
   takes a mapping. All are underscore-prefixed and undocumented.
5. **Factory failures surface as framework errors** (Error handling). New paths; nothing raised
   there before because the method did not exist.
6. **Test-only**: every mock agent handed to a runner exposes `run_options` and an awaitable
   `resolve_run_options`.

**Non-changes.** The `Agent.run_options` dict and its mutability; `RESERVED_RUN_OPTIONS` on every
adapter; `validate_run_options` (called on one more input, not changed); `Runner._native_kwargs`;
the LangGraph `config` deep merge, the top-level `RunnableConfig` guard and the merged-config
`aget_state`; the ADK constructor split, the stream SSE copy and `get_response`; the Pydantic AI
stream drop; `pre_hook` / `post_hook` / `_wrapped` / `_native_agent_name`; the trace runners; the
six existing examples; `AKConfig`; session persistence; public exports other than the added
`RunOptionsFactory` (`core/__init__.py:14`).

## Error handling

- **Non-callable factory at declaration**: `TypeError` from `Module.run_options`, nothing stored.
- **Factory raises during a run**: propagates out of `resolve_run_options` unchanged.
- **Non-mapping result**: `TypeError` naming the agent and the returned type.
- **Reserved key in the result**: the existing `ValueError` from `validate_run_options`, on every run
  until the factory is fixed.
- **Where those surface**: the resolution line sits inside each adapter's existing `try`. In `run`,
  the adapter's `except Exception` returns a `user_facing_error_message` reply, like any framework
  error. In `stream`, the OpenAI, LangGraph and Pydantic AI generators wrap the native call in
  `try/finally` with no `except`, and the ADK stream wraps nothing in `try`, so the exception
  propagates out of `Runner.stream` into `Runtime.stream`, which lets non-`StreamHalt` exceptions
  propagate. Either way the failure is per request and loud.
- **Not invoked for an empty request**: the resolution line follows the request-shape early returns,
  so a request the adapter rejects before the native call never runs the factory.
- **ADK and `ToolContext`**: the factory runs before `_setup_session_context` creates the ADK
  `ToolContext`, so `ToolContext.get()` returns `None` inside an ADK factory. Documented on the
  runner page and the ADK page; the factory's own arguments carry the same information.

Concurrency: the factory is one object shared by every concurrent run of the agent and is called
inside the run's async context, after `Runtime` has set the session, the agent and the acting-user
cache, so `Session.current()` and the cache resolve in it. It must hold no per-run state on itself;
the docs say so. Resolution is one awaited call per run; no lock is needed because nothing is
written to the agent.

Per-operation cost: for an agent without a factory, one dict copy per run, as today. For an agent
with a factory, that factory's own cost on every run before the model call, which is the caller's
choice and is documented; no caching is added.

Data compatibility: nothing persisted changes; `run_options_factory` is never serialised.

## Testing

Run with `cd ak-py && uv run pytest`; the CrewAI files need the `uv run --with "crewai>=1.15.0"`
overlay in a venv without that extra. Formatting: `make lint-check-all`.

### New assertions

- `ak-py/tests/test_base.py`, a `TestAgentResolveRunOptions` class: no factory returns an equal but
  distinct dict; a sync factory's keys merge over the static dict and win per key; an async factory
  does the same; the factory is called with `(agent, session, requests)` by identity; a non-mapping
  result raises `TypeError` naming the agent; a reserved key from the factory raises the same
  `ValueError` as declaration; a raising factory propagates its exception; the static dict is
  unchanged after every case; `run_options_factory` defaults to `None` and is settable.
- `ak-py/tests/test_module.py`: `run_options(agent, fn)` stores `fn`; `run_options(agent, fn, max_turns=3)`
  stores both; a second call with `gn` replaces `fn`; a non-callable positional raises `TypeError`
  and stores nothing; `run_options(agent)` alone is a no-op returning the module; the chain with
  `pre_hook` / `post_hook` still returns the module.
- Per adapter (`test_openai_runner.py`, `test_langgraph_runner.py`, `test_adk_runner.py`,
  `test_pydanticai_runner.py`, `test_crewai_runner.py`, `test_smolagents_runner.py`): with a real
  agent class or a mock whose `resolve_run_options` returns the factory-merged mapping, the native
  call receives the factory's value over the static one (OpenAI `max_turns`, LangGraph
  `config.recursion_limit`, ADK `run_config` plus a factory-supplied `plugins` reaching the `Runner`
  constructor, Pydantic AI `usage_limits`, CrewAI `max_rpm`, smolagents `max_steps`); and
  `resolve_run_options` is awaited exactly once with `(session, requests)` per `run` and per
  `stream` (`AsyncMock.assert_awaited_once_with`).
- `test_adk_runner.py`: `_setup_session_context` receives the resolved options and routes a
  factory-supplied `plugins` to the `Runner` constructor.
- `test_trace_langfuse_langgraph.py`: a factory result reaches `ainvoke` through the traced runner.
- Example: `examples/cli/openai-dynamic-run-options/demo_test.py` asserts `factory_runs >= 1`,
  `max_turns == 25` and `tool_calls >= 1`; runs in the e2e job through its matrix entry.

### Existing assertions that must keep passing unchanged

Every `call_args` assertion in the six runner test files, once their mock agents carry the two new
attributes (Consumer changes). No production behaviour they pin changes.

### Patch targets

Unchanged: `agentkernel.framework.openai.openai.Runner`, `agentkernel.framework.crewai.crewai.Crew`
and `.Task`, `agentkernel.framework.smolagents.smolagents.asyncio.to_thread`,
`agentkernel.trace.langfuse.langgraph.propagate_attributes`, `GoogleADKRunner._setup_session_context`
(its `patch.object` sites in `test_adk_runner.py` keep working: the patched `AsyncMock` accepts the
extra positional argument). No module moves.
