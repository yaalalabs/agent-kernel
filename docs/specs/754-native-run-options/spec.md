# #754: Per-agent native run options for framework adapters: Implementation Spec

Adds one framework-agnostic slot, `Agent.run_options`, declared through `Module.run_options(agent,
**options)` and merged by every adapter into its native run call with the keys Agent Kernel owns
written last. Requirements are `design.md` (as amended at this stage); this document details how they
are built. Line numbers are against `develop` at `348b8f6b`; SDK signatures are those verified in
`research/native-run-options-survey.md`.

## Design

Every component below is a method or attribute on an existing class. No new module, package, factory
or module-level function is introduced: the feature has no backend to select and no external system to
wrap, so the pluggable-backend shape does not apply. The one place behaviour is shared across the six
adapters is the base `Runner`, which is where the merge rule lives.

### `Agent` (`ak-py/src/agentkernel/core/base.py`)

```python
class Agent(ABC):
    RESERVED_RUN_OPTIONS: ClassVar[Mapping[str, str]] = {}
    """Native run-call keys this adapter populates itself, mapped to the reason (used in the error)."""

    def __init__(self, name: str, runner: Runner):
        ...
        self._pre_hooks: list[PreHook] = []          # existing, :431
        self._post_hooks: list[PostHook] = []        # existing, :432
        self._run_options: dict[str, Any] = {}       # new

    @property
    def run_options(self) -> dict[str, Any]:         # new; beside pre_hooks (:455-460)
        """Framework-native keyword arguments merged into every native run call for this agent."""
        return self._run_options

    def validate_run_options(self, options: Mapping[str, Any]) -> None:   # new
        """Raises ValueError naming every key in `options` that this adapter reserves."""
```

1. `run_options` is a live, mutable dict, the same contract as `pre_hooks` (design, Resolved
   questions). It is never persisted: `Session` serialisation does not see it, and it is not part of
   `get_all()`.
2. `validate_run_options` collects `sorted(set(options) & set(self.RESERVED_RUN_OPTIONS))` and, when
   non-empty, raises one `ValueError`:
   `f"Run option(s) reserved by the '{self.runner.name}' adapter for agent '{self.name}': "` followed by
   `"; ".join(f"'{key}': {self.RESERVED_RUN_OPTIONS[key]}" ...)`. Adapters that reserve a nested key
   (LangGraph) override it, call `super().validate_run_options(options)` first, then add their check.
3. The base class declares an empty mapping so a bring-your-own `Agent` subclass reserves nothing
   and validates trivially.

### `Module` (`ak-py/src/agentkernel/core/module.py`)

```python
class Module(ABC):
    def run_options(self, agent: Any, **options: Any) -> "Module":        # new, concrete
        """Declares framework-native run options for one loaded agent; chained like pre_hook."""
        name = self._native_agent_name(agent)
        wrapped = self.get_agent(name)                                      # existing, :39-48
        if wrapped is None:
            raise ValueError(f"Agent '{name}' is not loaded in this module")
        wrapped.validate_run_options(options)
        wrapped.run_options.update(options)
        return self

    def _native_agent_name(self, agent: Any) -> str:                       # new, concrete
        """The AK agent name a native agent is registered under. Adapters override the rule."""
        return agent.name
```

1. `run_options` is concrete (design amendment 1). It sits after `post_hook` (`:89-97`), is not
   abstract, and the two abstract hook methods are unchanged, so `SimpleModule`
   (`ak-py/tests/test_module.py:58`) and any out-of-tree module keep constructing.
2. `dict.update` gives the merge semantics the design requires: repeated calls merge, later call
   wins per key.
3. Only two adapters override `_native_agent_name`: `CrewAIModule` returns `agent.role`
   (`framework/crewai/crewai.py:604` is the rule `pre_hook` applies) and `SmolagentsModule` returns
   `getattr(agent, "name", "smolagent")` (`framework/smolagents/smolagents.py:337`, `:358`). The
   other four modules resolve by `agent.name` already (`openai.py:468`, `langgraph.py:676`,
   `adk.py:528`, `pydanticai.py:577`), which is the base default.
4. `pre_hook` / `post_hook` are not rewritten to use `_native_agent_name`. That would be a
   behaviour-preserving cleanup outside this change's scope; the plan may note it as a follow-up.

### `Runner` (`ak-py/src/agentkernel/core/base.py`)

```python
class Runner(ABC):
    @staticmethod
    def _native_kwargs(options: Mapping[str, Any], **ak_owned: Any) -> dict[str, Any]:   # new
        """Keyword arguments for a native run call: a copy of `options` with AK-owned keys written last."""
        kwargs = dict(options)
        kwargs.update(ak_owned)
        return kwargs
```

Rules, numbered so the adapter sections can cite them:

1. **Every native call site builds its keyword arguments through `_native_kwargs`.** No adapter
   passes a fixed keyword set directly any more. `options` is `agent.run_options` (or an adapter's
   filtered view of it, see ADK and Pydantic AI); `ak_owned` are the keys the adapter populates.
2. **AK-owned keys are written last.** This is the runtime invariant; declaration-time reservation
   (`validate_run_options`) is the redundancy. A caller that bypasses `Module.run_options` by
   mutating `agent.run_options` directly and inserts a reserved key has it overwritten, not
   honoured, and the run proceeds.
3. **The copy is shallow and per call.** An adapter that adjusts a value for one run (ADK forcing
   SSE) does so on the copy or on a copied value, never on `agent.run_options` or on an object held
   in it.
4. **It is a `@staticmethod`** so `GoogleADKRunner.get_response`, itself a static method, can call
   it without an instance.
5. **No type check on `options`.** `dict(options)` accepts any mapping. `Module.run_options` is the
   only writer AK provides and always writes a dict; the existing runner tests pass bare
   `MagicMock()` agents whose `run_options` attribute unpacks to `{}` (verified:
   `dict(MagicMock()) == {}`), so they need no change for this rule (see Testing for the one mock
   that does).

### OpenAI adapter (`ak-py/src/agentkernel/framework/openai/openai.py`)

- `OpenAIAgent` (`:363`) declares:

  ```python
  RESERVED_RUN_OPTIONS = {
      "starting_agent": "the native agent is the one this OpenAIAgent wraps",
      "input": "built from the AgentRequest list by the runner",
      "session": "the OpenAISession stored on the Agent Kernel session",
      "context": "populated from the session's framework_context; seed it with Session.set_framework_context()",
  }
  ```

- `run` (`:213`) becomes:

  ```python
  kwargs = self._native_kwargs(agent.run_options, session=self._session(session), context=produced)
  reply = (await Runner.run(agent.agent, input_data, **kwargs)).final_output
  ```

- `stream` (`:259`) becomes `Runner.run_streamed(agent.agent, input_data, **kwargs)` with the same
  `kwargs` construction. Both SDK methods accept `max_turns`, `hooks`, `run_config`,
  `error_handlers`, `previous_response_id`, `auto_previous_response_id`, `conversation_id` (survey).
- No mode-specific handling. `OpenAIModule` (`:423`) inherits `run_options` and the default name rule.

### LangGraph adapter (`ak-py/src/agentkernel/framework/langgraph/langgraph.py`)

- `LangGraphAgent` (`:204`) declares:

  ```python
  RESERVED_RUN_OPTIONS = {
      "input": "the graph input state is built from the messages and framework_context by the runner",
      "version": "the stream path fixes astream_events(version='v2')",
      "stream_mode": "the runner reads result['messages'] and result.get('structured_response'); a changed result shape breaks the reply mapping",
      "output_keys": "same reason as stream_mode",
      "print_mode": "same reason as stream_mode",
  }
  ```

  and overrides `validate_run_options` to add the nested check: when `options.get("config")` is a
  `Mapping` and `"thread_id" in (config.get("configurable") or {})`, raise
  `ValueError("Run option 'config.configurable.thread_id' is reserved by the 'langgraph' adapter for agent '<name>': the thread id is the Agent Kernel session id")`.
- `LangGraphRunner` gains one static method:

  ```python
  @staticmethod
  def _merge_run_config(base: dict, caller: Mapping[str, Any] | None) -> dict:
      """Deep-merge the caller's RunnableConfig under the AK-built one (design amendment 3)."""
      merged: dict[str, Any] = dict(caller or {})
      for key, value in base.items():
          current = merged.get(key)
          if isinstance(value, Mapping) and isinstance(current, Mapping):
              merged[key] = {**current, **value}                       # AK entries win (thread_id)
          elif isinstance(value, list) and isinstance(current, list):
              merged[key] = [*value, *(c for c in current if c not in value)]   # AK first
          else:
              merged[key] = value                                       # AK wins
      return merged
  ```

  `base` is the dict `_prepare_session_and_messages` returns (`:360-378`), which the Langfuse trace
  runner may already have decorated with `callbacks` (`trace/langfuse/langgraph.py:33-34`). Because
  the merge runs **after** that call, the trace handler is in `base` and is kept first.
- `run` (`:414-417`) becomes:

  ```python
  config, messages = self._prepare_session_and_messages(agent, session, prompt)
  ...
  kwargs = self._native_kwargs(
      agent.run_options,
      input=input_state,
      config=self._merge_run_config(config, agent.run_options.get("config")),
  )
  result = await agent.agent.ainvoke(**kwargs)
  ```

  `config` is thereby AK-owned at the top level (rule 2) while carrying the caller's entries through
  the merge. `stream` (`:469-473`) does the same and adds `version="v2"` to `ak_owned`.
- `interrupt_before`, `interrupt_after`, `durability`, `context` and any other keyword pass through
  untouched. `astream_events` forwards unknown keywords via `**kwargs` (survey), so the SDK, not the
  adapter, decides what it accepts.

### Google ADK adapter (`ak-py/src/agentkernel/framework/adk/adk.py`)

- `GoogleADKAgent` (`:428`) declares the reserved mapping for both destinations:

  ```python
  RESERVED_RUN_OPTIONS = {
      "agent": "the native agent is the one this GoogleADKAgent wraps",
      "app": "the runner constructs the ADK Runner from the agent, not an App",
      "app_name": "fixed to 'AgentKernel' by the runner",
      "node": "the runner constructs the ADK Runner from the agent",
      "session_service": "the GoogleADKSession stored on the Agent Kernel session",
      "auto_create_session": "the runner creates the ADK session itself",
      "user_id": "fixed to 'AgentKernel' by the runner",
      "session_id": "the Agent Kernel session id",
      "new_message": "built from the AgentRequest list by the runner",
      "state_delta": "state is seeded from the session's framework_context; seed it with Session.set_framework_context()",
      "invocation_id": "assigned by ADK per run",
      "yield_user_message": "the stream mapping expects model events only",
  }
  ```

- `GoogleADKRunner` gains a class constant and two helpers:

  ```python
  RUNNER_CONSTRUCTOR_OPTIONS: ClassVar[frozenset[str]] = frozenset(
      {"plugins", "memory_service", "artifact_service", "credential_service", "plugin_close_timeout"}
  )
  """Run options routed to the per-run google.adk Runner(...) constructor; everything else goes to run_async."""

  @classmethod
  def _split_run_options(cls, agent: Any) -> tuple[dict[str, Any], dict[str, Any]]:
      """(constructor options, run_async options) from agent.run_options."""

  def _stream_run_config(self, caller: RunConfig | None) -> RunConfig:
      """The caller's RunConfig copied with streaming_mode=SSE (or a fresh SSE RunConfig when None)."""
  ```

  `__init__` (`:111-115`, the existing one setting `self._log`) gains
  `self._streaming_mode_warned = False`.
- `_setup_session_context` (`:176-202`) builds the constructor through rule 1:
  `Runner(**self._native_kwargs(ctor_options, agent=agent.agent, app_name=app_name, session_service=adk_session.session_service))`
  where `ctor_options, run_options = self._split_run_options(agent)`. It returns the tuple it does
  today; `run` and `stream` call `_split_run_options` themselves for the run side (one extra
  dict comprehension per run, negligible).
- `get_response` (`:204-227`) gains a trailing optional parameter:
  `get_response(runner, user_id, session_id, parts, run_options: Mapping[str, Any] | None = None)`.
  Both branches call through
  `BaseRunner._native_kwargs(run_options or {}, user_id=user_id, session_id=session_id, new_message=new_message)`.
  Existing callers passing four arguments are unaffected.
- `run` passes `run_options` (the run-side split) to `get_response`. In run mode a caller's
  `run_config` is forwarded untouched (SDK default `streaming_mode=NONE`).
- `stream` (`:292-304`) replaces `run_config = RunConfig(streaming_mode=StreamingMode.SSE)` with
  `run_config = self._stream_run_config(run_options.get("run_config"))` and calls
  `runner.run_async(**self._native_kwargs(run_options, user_id=..., session_id=..., new_message=..., run_config=run_config))`.
  `_stream_run_config`: `None` returns `RunConfig(streaming_mode=StreamingMode.SSE)` (today's
  value); otherwise, if `caller.streaming_mode is not StreamingMode.SSE` and the flag is unset, log
  `self._log.warning("ADK RunConfig streaming_mode %s overridden to SSE for Agent Kernel stream mode; the stream mapping depends on partial events", caller.streaming_mode)`
  and set the flag; return `caller.model_copy(update={"streaming_mode": StreamingMode.SSE})`
  (`RunConfig` is a Pydantic model; `model_copy` verified against google-adk 2.8.0). The caller's
  object is never mutated (rule 3).

### Pydantic AI adapter (`ak-py/src/agentkernel/framework/pydanticai/pydanticai.py`)

- `PydanticAIAgent` (`:436`) declares:

  ```python
  RESERVED_RUN_OPTIONS = {
      "user_prompt": "built from the AgentRequest list by the runner",
      "message_history": "the PydanticAISession stored on the Agent Kernel session",
      "deps": "populated from the session's framework_context; seed it with Session.set_framework_context()",
  }
  ```

- `PydanticAIRunner.__init__` (`:88-92`) gains `self._event_stream_handler_warned = False` and the
  class gains:

  ```python
  def _stream_run_options(self, agent: Any) -> dict[str, Any]:
      """agent.run_options without event_stream_handler, which run_stream_events does not accept."""
  ```

  It copies `agent.run_options`, pops `event_stream_handler`, and when a value was present and the
  flag is unset logs
  `_log.warning("Pydantic AI event_stream_handler is ignored in Agent Kernel stream mode; the runner's own stream events carry the same information")`
  and sets the flag.
- `run` (`:171`) becomes
  `agent.agent.run(content, **self._native_kwargs(agent.run_options, message_history=history, deps=produced))`.
- `stream` (`:223`) becomes
  `agent.agent.run_stream_events(content, **self._native_kwargs(self._stream_run_options(agent), message_history=history, deps=produced))`.
- `usage_limits`, `model_settings`, `retries`, `metadata`, `toolsets`, `output_type` and the rest pass
  through to both calls (survey: identical signatures apart from `event_stream_handler`).

### CrewAI adapter (`ak-py/src/agentkernel/framework/crewai/crewai.py`)

- `CrewAIAgent` (`:427`) declares:

  ```python
  RESERVED_RUN_OPTIONS = {
      "agents": "the crew is the module's agent list",
      "tasks": "the runner builds one Task per run from the prompt",
      "memory": "the CrewAISession memory stored on the Agent Kernel session",
  }
  ```

- `CrewAIModule` (`:539`) overrides `_native_agent_name` to return `agent.role`.
- The `Crew(...)` construction (`:375-380`) becomes:

  ```python
  crew = Crew(**self._native_kwargs({"verbose": False, **agent.run_options}, agents=agent.crew, tasks=[task], memory=memory))
  ```

  `verbose=False` is a default under the caller's options, so a caller may override it; `agents`,
  `tasks` and `memory` are AK-owned (rule 2). `kickoff_async(inputs={})` (`:386`) is unchanged: its
  argument is template interpolation, not an options bag.
- The `Task(...)` construction (`:368-374`) is unchanged; Task-level options stay on the existing
  `output_pydantic` / `output_json` module maps (`:548-549`).

### smolagents adapter (`ak-py/src/agentkernel/framework/smolagents/smolagents.py`)

- `SmolagentsAgent` (`:203`) declares:

  ```python
  RESERVED_RUN_OPTIONS = {
      "task": "built from the AgentRequest list by the runner",
      "reset": "fixed to False so memory persists across turns",
      "additional_args": "populated from the session's framework_context; seed it with Session.set_framework_context()",
      "stream": "the runner maps a single return value, not a step stream",
      "return_full_result": "the runner maps the final answer, not a RunResult",
  }
  ```

- `SmolagentsModule` (`:308`) overrides `_native_agent_name` to return
  `getattr(agent, "name", "smolagent")`, the rule `_wrap` (`:337`) and `pre_hook` (`:358`) apply.
- `run` (`:159-164`) becomes:

  ```python
  run_kwargs = self._native_kwargs(agent.run_options, reset=False)
  if incoming is not None:
      run_kwargs["additional_args"] = incoming
  reply = await asyncio.to_thread(agent.agent.run, prompt, **run_kwargs)
  ```

  `additional_args` is assigned after the helper, so it is written last like the other AK-owned
  keys, and only when a framework context exists (today's behaviour).
- `stream` is unchanged (it raises `NotImplementedError`).

### Trace runners (`ak-py/src/agentkernel/trace/{langfuse,logfire,openllmetry}/*.py`)

No file changes. All 18 trace runners delegate to `super().run(agent, session, requests)`
(`research/native-run-options-survey.md`), so the base adapter reads `agent.run_options` inside the
span. `LangFuseLangGraph._prepare_session_and_messages` (`trace/langfuse/langgraph.py:24-35`) keeps
working because the LangGraph merge runs on its return value (see the LangGraph section): with a caller
`config={"callbacks": [mine]}` the graph receives `[langfuse_handler, mine]`.

### Consumer changes

- **`Runtime`, `AgentService`, `ChatService`, the pipeline, the deployment adapters**: no change.
  They never see run options; `Runtime.run` / `Runtime.stream` still call
  `agent.runner.run(agent, session, requests)` (`core/runtime.py:286`, `:341`).
- **`Session` and the session stores**: no change. `run_options` lives on the process-level `Agent`,
  not on the session.
- **`SystemToolFactory`, guardrails, multimodal**: no change.
- **Tests**: the `MagicMock(spec=[...])` agent in `ak-py/tests/test_crewai_runner.py:34` must add
  `"run_options"` to its spec list and set `agent.run_options = {}`; a spec-restricted mock raises
  `AttributeError` on the new read. The 69 bare `MagicMock()` agents across the other runner tests
  unpack to `{}` and need no change (Runner rule 5).
- **Documentation and skills**: see the dedicated section below.

### Config changes

No config changes. `AKConfig` is untouched; no field, flag or block is added, and existing YAML and
`AK_*` environment variables are read exactly as before. Run options are Python objects declared in
application code at module load (design, Configuration).

### Documentation changes

Every change is additive: a new section beside the existing "Per-run context/state" sections, plus
one correction.

- `docs/docs/core-concepts/runner.md`: a `### Per-agent native run options {#native-run-options}`
  section after "Per-run framework context" (`:216-243`): the declaration call, the merge rule and
  its two exceptions, and a per-framework table (destination, reserved keys, turn-limit key,
  progress-hook key).
- `docs/docs/core-concepts/module.md`: `run_options` documented under "Module Configuration"
  (`:118`) beside the fluent hook API, with the chained example from the issue.
- `docs/docs/core-concepts/agent.md`: a `#### Run options` entry under "Agent Properties" (`:229`)
  after "Runner".
- `docs/docs/integrations/hooks.md`: one paragraph under "Registering Hooks" (`:396`) pointing to
  run options for framework-native lifecycle hooks, and the two-path progress comparison (AK
  `StreamEvent`s vs native hooks) as a short table.
- `docs/docs/frameworks/openai.md` (`:113`), `langgraph.md` (`:134`), `google-adk.md` (`:116`),
  `pydantic-ai.md` (`:179`), `crewai.md` (`:121`), `smolagents.md` (`:121`): a `## Native run options`
  section directly after each page's "Per-run context/state" with that SDK's destination, reserved
  keys, a turn-limit example and a progress-hook example (smolagents: the note that `step_callbacks`
  is a constructor argument of the user-built agent). The ADK page states the stream-mode SSE
  override; the Pydantic AI page states the stream-mode `event_stream_handler` drop.
- `docs/docs/advanced/traceability.md:477-500`: the custom-runner example's `run(agent, session,
  prompt)` signature corrected to `run(agent, session, requests)`, and a sentence redirecting
  keyword-argument needs to run options.
- `.agents/skills/ak-dev-architecture/SKILL.md`: the Agent entry (`:85`) gains `run_options` /
  `RESERVED_RUN_OPTIONS` / `validate_run_options`; the Runner entry (`:96`) gains a "Per-agent
  native run options" bullet beside the framework-context one (`:104`); the Module entry (`:106`)
  gains `run_options` and `_native_agent_name`.
- `.agents/skills/ak-dev-new-framework-integration/SKILL.md`: step 4 (`:256`) adds
  `RESERVED_RUN_OPTIONS`; step 3 adds "build native keyword arguments with `_native_kwargs`"; step 6
  (`:305`) adds "override `_native_agent_name` only when the name rule is not `agent.name`"; the
  checklist (`:421`) gains the corresponding items and a test item.

### Examples (`examples/cli/<framework>-run-options/`)

Six new CLI examples, one per adapter, shaped like `examples/cli/openai_context/` (design, Examples).
Shared shape:

- `pyproject.toml` named `cli-<framework>-run-options`, depending on `agentkernel[cli,<extra>]` at the
  same pin the sibling `_context` example carries (`>=0.9.2` today; `publish.yaml` bumps it), the same
  `[dependency-groups] dev` block, black/isort at line length 120.
- `build.sh` copied verbatim from `examples/cli/openai/build.sh` (`./build.sh local` installs the
  branch wheel from `ak-py/dist`, which is what `run_single_test.py --type cli` runs).
- `demo.py`: one agent with the stub `get_weather` tool the sibling examples use; a **progress hook**
  in the framework's native form that increments `llm_calls` / `tool_calls` counters in
  `Session.current().get_volatile_cache()`; the framework's **turn-limit option**; and
  `AppendRunStatsPostHook(PostHook)` appending
  `Run stats: llm_calls=<n>, tool_calls=<n>, <limit name>=<value>` to every `AgentReplyText`, where the
  limit name is the framework's own (`max_turns`, `recursion_limit`, `max_llm_calls`, `request_limit`,
  `max_rpm`, `max_steps`); CrewAI and smolagents count `steps` instead of the two call counters. Post-hooks run
  before `Runtime.run` clears the volatile cache in its `finally` (`core/runtime.py:288-298`), so the
  counters are readable there.
- `demo_test.py`: the `Test("demo.py")` harness (which drives the CLI, i.e. `AgentService.run`, the
  non-stream path, `cli/cli.py:119`), two ordered turns, asserting the `Run stats:` line is present,
  the limit carries the declared static value exactly, and the counters are at least 1 on a
  tool-using turn. Model wording is never asserted.
- `README.md`: what is declared and why, the per-framework destination and reserved keys, the two
  progress paths (AK stream events vs native hooks), and the run instructions block the siblings use.
- `uv.lock` generated with `uv lock` in the directory and committed, as every sibling does.

Per framework (the declared call is the whole point of each demo):

| Example | `run_options(...)` call | Progress hook form | Notes in README |
|---|---|---|---|
| `openai-run-options` | `max_turns=25, hooks=ProgressHooks(), run_config=RunConfig(call_model_input_filter=trim_history)` | `RunHooks` subclass counting `on_llm_start` / `on_tool_start` | `trim_history` keeps the last 20 input items and bumps a `filter_runs` counter shown in the stats line |
| `langgraph-run-options` | `config={"callbacks": [ProgressCallbackHandler()], "recursion_limit": 50}` | `BaseCallbackHandler` counting `on_chat_model_start` / `on_tool_start` | how `callbacks` concatenates with a trace runner's handler; `thread_id` is reserved |
| `adk-run-options` | `plugins=[ProgressPlugin()], run_config=RunConfig(max_llm_calls=20)` | `BasePlugin` with `before_model_callback` / `before_tool_callback` | `plugins` goes to the per-run `Runner` constructor; stream mode forces SSE |
| `pydanticai-run-options` | `usage_limits=UsageLimits(request_limit=10), event_stream_handler=count_events` | async `event_stream_handler` counting model-request and tool-call events | `event_stream_handler` is dropped in stream mode with one warning |
| `crewai-run-options` | `step_callback=record_step, max_rpm=30` | `step_callback` counting steps | `Crew`-constructor destination; `verbose` overridable; `Task` options stay on the module maps |
| `smolagents-run-options` | `max_steps=6` | native `step_callbacks=[record_step]` on the `CodeAgent` constructor | nothing is needed from AK for progress; `reset` / `additional_args` reserved |

Indexes: each example is added to the CLI section of `docs/docs/examples/overview.md` as a block
beside the `_context` one (`:47-52`), linked from its framework page's "Example" section (the
`_context` link pattern at `openai.md:132`), and listed in `.github/test-config.yaml` under
`e2e.tests` as `type: cli`. The existing `examples/cli/smolagents` demo is **not** in that matrix
today (no entry names it); the new smolagents example is added anyway, and the plan flags the
asymmetry for the requester.

### Behavioural changes

All intentional.

1. **`Module.run_options` and `Module._native_agent_name` exist on every module.** New public
   fluent method plus an overridable protected hook; both concrete (design amendment 1).
2. **`Agent.run_options`, `Agent.RESERVED_RUN_OPTIONS`, `Agent.validate_run_options` exist on every
   agent.** An agent with no declared options carries `{}`.
3. **Every native call site builds its keyword arguments through `Runner._native_kwargs`.** With
   `{}` options the resulting call is keyword-for-keyword identical to today; the existing runner
   tests that assert on `call_args` are the regression guard.
4. **`GoogleADKRunner.get_response` gains a fifth, optional parameter.** Four-argument callers are
   unaffected.
5. **CrewAI `verbose` becomes overridable.** Today it is fixed `False`; it is now a default under
   the caller's options. No caller could set it before, so no existing behaviour changes.
6. **ADK stream mode honours a caller's `RunConfig` except `streaming_mode`**, which is forced to
   `SSE` with one warning per runner when the caller's value differed. Today no caller `RunConfig`
   reaches the stream call at all.
7. **Pydantic AI stream mode drops a caller's `event_stream_handler`** with one warning per runner.
   Today no caller options reach the call at all.
8. **Declaration-time `ValueError`s** for a reserved key and for an agent not loaded in the module.
   Both are new paths; nothing raised there before because the method did not exist.
9. **Test-only**: the CrewAI spec-restricted mock agent gains `run_options`.

**Non-changes.** `Runtime.run` / `Runtime.stream` / `AgentService` / `ChatService` signatures;
`Session` contents and serialisation (no new key, stores read old sessions identically); `AKConfig`;
the six `pre_hook` / `post_hook` implementations; the trace runners; public exports (`agentkernel`,
`agentkernel.core`, the framework aliases); the `runner=` constructor argument on every module; the
smolagents `stream()` and CrewAI `stream()` stubs; `Task` construction in CrewAI; the OpenAI, LangGraph,
ADK, Pydantic AI stream-event mapping.

## Error handling

- **Reserved key at declaration**: `Module.run_options` raises `ValueError` from
  `Agent.validate_run_options` naming the adapter (`runner.name`), the agent, every offending key and
  its reason. Nothing is written to `run_options` when the call raises (validate runs before
  `update`).
- **Nested LangGraph `thread_id`**: same `ValueError` shape from `LangGraphAgent.validate_run_options`.
- **Agent not loaded**: `Module.run_options` raises `ValueError("Agent '<name>' is not loaded in this
  module")`. This is a deliberate improvement over `pre_hook`, which raises `AttributeError` on
  `None` today; `pre_hook` itself is not changed.
- **Unknown option** (a key the SDK rejects): not validated by AK (design, Resolved questions). In
  `run`, the SDK's `TypeError` is caught by each adapter's existing `except Exception` and returned
  as an `AgentReplyText` via `user_facing_error_message`, exactly like any other framework error
  (`openai.py:223-224` and its siblings). In `stream`, the adapters have no `except` around the
  native call (OpenAI opens a `try` at `:249` closed only by the `finally` at `:275`; the inner
  `try/except` at `:271-274` guards the framework-context write-back alone), so the `TypeError`
  propagates out of `Runner.stream` into
  `Runtime.stream`, which per its existing contract lets non-`StreamHalt` exceptions propagate to
  the caller. Either way every request on that agent fails the same way until the declaration is
  fixed, which is the intended loudness.
- **Bypassing the declaration** (mutating `agent.run_options` directly with a reserved key): no
  error; the AK-owned value wins at call time (Runner rule 2). Documented on the runner page.
- **Options in a mode that cannot use them**: ADK `streaming_mode` and Pydantic AI
  `event_stream_handler` in stream mode are overridden / dropped with one `WARNING` per runner
  instance, never an error, so a `RunConfig` or option set declared for run mode keeps the agent
  usable when `execution.mode` is switched to `stream`.
- **A hook or callable that raises inside the native run**: surfaces exactly as a framework error
  does today (caught in `run`, propagated in `stream`). AK adds no wrapping.
- **No new exception types** are introduced; `ValueError` is the declaration-time error because the
  failure is a bad argument to `run_options`, and `AKConfigError` is reserved for configuration.

Concurrency: `agent.run_options` is read on every run by whichever runner instance serves the
agent, possibly from several sessions concurrently. Reads are dict iteration into a fresh copy
(rule 3), and AK never writes to it after load, so no lock is needed. Hook instances placed in
`run_options` are shared across every concurrent run of that agent; a stateful hook must key its
state by `Session.current().id`, the same rule `PostHook` instances follow (one instance per agent,
shared by every session; `docs/specs/670-streaming-post-hooks/design.md` states it for buffering
hooks). This is stated on the runner page.

Per-operation cost: one dict copy per native call (plus one shallow config merge on LangGraph and one
dict comprehension on ADK). Negligible next to the model call; no mitigation.

Data compatibility: nothing persisted changes. A session written before this change is read back
identically; `run_options` is process-level configuration and is never serialised.

## Testing

Run with `cd ak-py && uv run pytest` (the whole suite; the framework runner tests import their SDKs
and skip via `importorskip` where an extra is missing). Formatting: `make lint-check`.

### New assertions in existing files

- `ak-py/tests/test_base.py`
  - `test_agent_init` (`:53`): a fresh agent has `run_options == {}`, the attribute is the same
    object across reads (live dict), and `RESERVED_RUN_OPTIONS == {}` on the dummy.
  - New: `validate_run_options` on a dummy subclass declaring
    `RESERVED_RUN_OPTIONS = {"context": "why"}` raises `ValueError` whose message contains the
    runner name, the agent name, `'context'` and `why`; an unreserved key passes; two reserved keys
    are both named, sorted.
  - New: `Runner._native_kwargs({"a": 1, "session": "caller"}, session="ak", context=None)` returns
    `{"a": 1, "session": "ak", "context": None}` and does not mutate the input mapping.
- `ak-py/tests/test_module.py`
  - `SimpleModule` (`:58`) unchanged: asserts it still constructs (the concrete-method guarantee).
  - New: `run_options(agent, a=1)` then `run_options(agent, a=2, b=3)` yields `{"a": 2, "b": 3}`
    (merge, last wins); chaining `.pre_hook(...).run_options(...).post_hook(...)` returns the module;
    a reserved key on a `KernelWrappedAgent` subclass with `RESERVED_RUN_OPTIONS` raises `ValueError`
    and leaves `run_options` untouched; an unknown native agent raises `ValueError` naming it; a
    module overriding `_native_agent_name` resolves by that rule.
- `ak-py/tests/test_openai_runner.py` (patch target `agentkernel.framework.openai.openai.Runner`,
  `:66`): with `mock_agent.run_options = {"max_turns": 25, "hooks": hooks, "run_config": rc}`,
  `MockRunner.run.call_args.kwargs` contains those three plus `session` and `context`; the same for
  `run_streamed`; with `run_options = {"context": "caller"}` the call receives the framework-context
  value, not `"caller"` (rule 2); `mock_agent.run_options` is unchanged after two runs (rule 3).
  - New, both modes: a real `agents.RunHooks` subclass whose `on_tool_start` records
    `Session.current()` and `Agent.current()`, driven through `Runtime.run` and `Runtime.stream`
    with the SDK `Runner` patched to invoke the hook from inside the patched call (run) and from a
    task it spawns (stream), asserts both resolve to the run's session and agent.
- `ak-py/tests/test_langgraph_runner.py` (`agent.agent.ainvoke` is an `AsyncMock`, `:33-36`):
  `run_options = {"config": {"callbacks": [cb], "recursion_limit": 7, "configurable": {"x": 1}}}`
  yields `kwargs["config"] == {"callbacks": [cb], "recursion_limit": 7, "configurable": {"x": 1, "thread_id": "<session id>"}}`;
  a `base` already holding `callbacks=[trace]` merges to `[trace, cb]` (a direct `_merge_run_config`
  unit test, plus the trace test below); `interrupt_before=["tools"]` reaches `ainvoke`;
  `run_options = {"config": {"configurable": {"thread_id": "x"}}}` is rejected at
  `LangGraphModule.run_options` with a `ValueError` naming `config.configurable.thread_id`; stream
  keeps `version="v2"` when the caller passes `version="v1"` via direct mutation.
- `ak-py/tests/test_adk_runner.py` (mock `Runner` and `RunConfig` construction, `:21-32`):
  `run_options = {"plugins": [p], "run_config": RunConfig(max_llm_calls=3)}` puts `plugins` in the
  `Runner(...)` constructor kwargs and `run_config` in `run_async` kwargs with `max_llm_calls == 3`
  and `streaming_mode` untouched in run mode; in stream mode the `run_async` `run_config` has
  `streaming_mode == SSE`, `max_llm_calls == 3`, the caller's object is unchanged, and `caplog`
  holds exactly one warning across two streamed runs; `_split_run_options` unit test on the
  constant.
- `ak-py/tests/test_pydanticai_runner.py` (`mock_agent.agent.run` AsyncMock, `:52-54`):
  `run_options = {"usage_limits": ul, "event_stream_handler": h}` reaches `run` with both; the
  stream path's `run_stream_events` kwargs contain `usage_limits` and not `event_stream_handler`,
  `caplog` holds one warning across two streams, and `mock_agent.run_options` still contains the
  handler afterwards (rule 3).
- `ak-py/tests/test_crewai_runner.py` (patches at `:48-49`): the mock at `:34` adds
  `"run_options"` to its spec and sets it; `run_options = {"step_callback": cb, "verbose": True}`
  reaches the `Crew` patch with `verbose is True`, `step_callback is cb`, and `agents`/`tasks`/
  `memory` present; `run_options = {}` reproduces today's exact `Crew` kwargs (`verbose=False`).
- `ak-py/tests/test_smolagents_runner.py` (`asyncio.to_thread` patched, `:37`):
  `run_options = {"max_steps": 4}` yields `to_thread` kwargs `{"reset": False, "max_steps": 4}`
  (plus `additional_args` when a framework context is set), and a direct-mutation `reset=True` is
  overwritten to `False`.
- `ak-py/tests/test_trace_langfuse_langgraph.py`: a caller `config={"callbacks": [mine]}` through
  `LangFuseLangGraph.run` gives `ainvoke` a `callbacks` list whose first element is the runner's
  `_callback_handler` and whose second is `mine`; and `run_options = {"max_concurrency": 2}` passes
  through the traced runner unchanged (the composition guarantee).

### Example tests

Each new example's `demo_test.py` runs through `Test("demo.py")` against a real model (the e2e job,
`OPENAI_API_KEY` required; `run_single_test.py --type cli --path examples/cli/<name> --action test`).
Assertions per the Examples section: the `Run stats:` line, the exact static `limit=` value, and
counters at least 1 on the tool turn. Locally: `cd examples/cli/<name> && ./build.sh local && uv run pytest -s`.

### Existing assertions that must keep passing unchanged

Every `call_args` assertion in the six runner test files and in `test_framework_context.py`, since
an agent with `{}` options must produce today's exact keyword set. These are the regression guard
for Behavioural change 3 and need no edits beyond the CrewAI spec list.

### Patch targets

Unchanged: `agentkernel.framework.openai.openai.Runner`, `agentkernel.framework.crewai.crewai.Crew`,
`agentkernel.framework.crewai.crewai.Task`, `agentkernel.framework.smolagents.smolagents.asyncio.to_thread`,
`agentkernel.trace.langfuse.langgraph.propagate_attributes`. No module is moved and no shim is needed.
