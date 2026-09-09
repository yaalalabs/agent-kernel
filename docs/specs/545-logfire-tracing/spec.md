# #545: Add Pydantic Logfire as a tracing provider — Implementation Spec

Implements the design in `design.md`: a third built-in trace backend, `logfire`, added under
`trace/logfire/` and registered in `trace/trace.py`. `Logfire.init()` configures the global
OpenTelemetry tracer provider once; five no-arg traced runners wrap each agent run in a
`logfire.span(...)` and activate deep instrumentation in `__init__`. The design idea: mirror the
OpenLLMetry provider's shape (once-guarded global init, no-arg runners) with Langfuse-style
span-with-io-attributes wrapping.

`design.md` is the requirements source; every requirement there maps to a section below.

## Design

### New package `trace/logfire/`

```
ak-py/src/agentkernel/trace/logfire/
├── __init__.py        # empty (matches trace/langfuse/__init__.py, trace/openllmetry/__init__.py)
├── logfire.py         # Logfire(BaseTrace) — factory-facing class
├── openai.py          # LogfireOpenAIRunner(OpenAIRunner)
├── langgraph.py       # LogfireLangGraphRunner(LangGraphRunner)
├── crewai.py          # LogfireCrewAIRunner(CrewAIRunner)
├── adk.py             # LogfireADKRunner(GoogleADKRunner)
└── smolagents.py      # LogfireSmolagentsRunner(SmolagentsRunner)
```

Rules:

1. `trace/` may import from `framework/` (it is not `core/`); the runners import their base runner
   exactly as the Langfuse/OpenLLMetry runners do (e.g. `from ...framework.openai.openai import
   OpenAIRunner`).
2. `import logfire` in these modules binds the third-party top-level package (absolute import),
   never the sibling `agentkernel.trace.logfire` package — the same situation as
   `trace/langfuse/langfuse.py` importing `langfuse`.
3. Every framework method on `Logfire` is implemented (all five are `@abstractmethod` on `BaseTrace`),
   so the class is instantiable.

#### `Logfire` (`trace/logfire/logfire.py`)

```python
class Logfire(BaseTrace):
    _init_lock = threading.Lock()      # class-level: init() runs once per Module construction
    _configured = False

    def __init__(self):
        self._log = logging.getLogger("ak.trace.logfire")

    def init(self):
        with Logfire._init_lock:
            if not Logfire._configured:
                logfire.configure(service_name="AgentKernel", send_to_logfire="if-token-present")
                Logfire._configured = True

    def openai(self) -> Runner: ...      # returns LogfireOpenAIRunner() (lazy import)
    def langgraph(self) -> Runner: ...   # LogfireLangGraphRunner()
    def crewai(self) -> Runner: ...      # LogfireCrewAIRunner()
    def adk(self) -> Runner: ...         # LogfireADKRunner()
    def smolagents(self) -> Runner: ...  # LogfireSmolagentsRunner()
```

- Runners take no constructor args (like OpenLLMetry's, unlike Langfuse's client-taking ones), because
  they use the process-global `logfire` module rather than a client handle.
- The once-guard mirrors `TraceloopContext.initialize_global` (`trace/openllmetry/openllmetry.py:43-55`);
  it is class-level so concurrent Module constructions across threads configure once.

#### Traced runners — shared shape

All five share this shape (differing only in base class, span name, and the `__init__`
instrumentation block):

```python
class LogfireSmolagentsRunner(SmolagentsRunner):
    def __init__(self):
        super().__init__()
        self._log = logging.getLogger("ak.trace.logfire.smolagents")
        # (OpenAI/CrewAI/ADK activate instrumentation here; LangGraph/Smolagents do not)

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        with logfire.span("Agent Kernel Smolagents", session_id=session.id) as span:
            result = await super().run(agent, session, requests)
            span.set_attribute("input", result.prompt)
            span.set_attribute("output", str(result))
        return result
```

Per-framework `__init__` instrumentation (activated once per runner construction; the instrumentors
are internally idempotent):

- `openai.py`: `logfire.instrument_openai_agents()`.
- `crewai.py`: `from openinference.instrumentation.crewai import CrewAIInstrumentor` +
  `from openinference.instrumentation.litellm import LiteLLMInstrumentor`;
  `CrewAIInstrumentor().instrument(skip_dep_check=True)`, `LiteLLMInstrumentor().instrument()`
  (identical to `trace/langfuse/crewai.py:24-25`).
- `adk.py`: `from openinference.instrumentation.google_adk import GoogleADKInstrumentor`;
  `GoogleADKInstrumentor().instrument()` (identical to `trace/langfuse/adk.py:23`).
- `langgraph.py`, `smolagents.py`: no instrumentation block — span only.

`span.set_attribute` is the Logfire/OTel API; `result.prompt` and `str(result)` are the same values
Langfuse writes via `span.update(input=result.prompt, output=str(result))`
(`trace/langfuse/openai.py:39`). `str(AgentReplyText)` returns `.response` (`core/model.py:103-104`).

Error handling: the `with logfire.span(...)` block is not wrapped in try/except. An exception raised by
`super().run(...)` propagates through the context manager, which records the exception and sets the
span's error status (OTel `__exit__` semantics), then re-raises — matching every Langfuse/OpenLLMetry
runner (`trace/langfuse/smolagents.py:30-33`, `trace/openllmetry/openai.py:28-30`).

### Consumer changes

- **`trace/trace.py`** — add `logfire` as a built-in:
  - `_BUILTIN_TRACERS = ["langfuse", "openllmetry", "logfire"]` (line 8).
  - New branch in `_build()` after the `openllmetry` branch:
    ```python
    if trace_type == "logfire":
        with require_extra("logfire", "trace.type: logfire"):
            from .logfire.logfire import Logfire
        return Logfire()
    ```
  - Nothing else changes: the disabled path (`Trace(None)`), the unknown-type `AKConfigError`, and the
    dotted-path BYO branch are untouched.
- **Framework Modules** — no change. `Trace.get().<framework>()` already routes to whichever provider
  `_build()` returns (`framework/openai/openai.py:302-307` and the four siblings). Logfire is picked up
  transparently.
- **`trace/base.py`** — no change (all six methods already `@abstractmethod`).

### Config changes

- `core/config.py`, `_TraceConfig.type` (`config.py:267-270`): keep `type: str`, `default="langfuse"`,
  no `pattern`. Change only the description:
  - From: `"Tracing backend: a built-in short name (langfuse, openllmetry) or a dotted path to a BaseTrace subclass"`
  - To: `"Tracing backend: a built-in short name (langfuse, openllmetry, logfire) or a dotted path to a BaseTrace subclass"`
- Existing `config.yaml` / `AK_TRACE__*` env vars are unaffected: `logfire` is a new opt-in value; no
  default changes; no field renamed or removed.

### Optional dependency

- `ak-py/pyproject.toml`, `[project.optional-dependencies]`, after the `openllmetry` extra:
  ```toml
  logfire = [
      "logfire>=3.0",
  ]
  ```
- No OpenInference packages here — `crewai`/`adk` extras already provide
  `openinference-instrumentation-crewai`, `-litellm` (`pyproject.toml:36-37`) and
  `-google-adk` (`pyproject.toml:90`). A Logfire user of those frameworks installs the framework
  extra, so the instrumentor import in the runner resolves.

### Example `examples/cli/logfire/`

Modeled on `examples/cli/openai/`; files:

- `demo.py` — the `examples/cli/openai/demo.py` triage/math/general/weather agents verbatim (tracing is
  transparent, so agent code is unchanged).
- `config.yaml`:
  ```yaml
  trace:
    enabled: true
    type: logfire
  ```
- `pyproject.toml` — `dependencies = ["agentkernel[cli,openai,logfire]>=<current>"]`, dev group
  `agentkernel[test]`, black/isort/mypy config with `line-length = 120` (example convention).
- `build.sh` — copy of `examples/cli/openai/build.sh` (the `local` branch reinstalls
  `agentkernel[cli,openai,logfire,test]`).
- `README.md` — run steps + `export LOGFIRE_TOKEN=...` (and a note that without a token it runs locally
  via `send_to_logfire="if-token-present"`).
- `demo_test.py` — the `examples/cli/openai/demo_test.py` two-question flow (proves the agent still runs
  with tracing enabled).

### Behavioural changes

All additive; none change existing behavior:

1. `trace.type: logfire` is newly accepted and resolves to the `Logfire` provider (previously an
   unknown type → `AKConfigError`).
2. A missing `logfire` SDK under `trace.type: logfire` raises the friendly
   `pip install "agentkernel[logfire]"` `ImportError` (via `require_extra`).

**Non-changes:** default `trace.type` (`langfuse`); the disabled path (`Trace(None)`); the BYO
dotted-path resolution; the `BaseTrace` interface; the Langfuse and OpenLLMetry providers; all framework
Module wiring; existing config field names/types/defaults; existing tests in `test_trace.py`.

## Error handling

- **Missing optional dependency** (`logfire` not installed, `trace.type: logfire`): `_build()`'s
  `require_extra("logfire", "trace.type: logfire")` converts the `ImportError` into one whose message
  contains `pip install "agentkernel[logfire]"` (`core/util/factory.py:49-64`).
- **`LOGFIRE_TOKEN` unset**: `send_to_logfire="if-token-present"` → `logfire.configure()` runs locally
  without shipping and without raising (contrast Langfuse's `init()`, which raises when `auth_check()`
  fails, `trace/langfuse/langfuse.py:25-28`). Deliberate: Logfire supports token-less/local and
  OTLP-to-any-backend modes.
- **Runtime exception during a run**: propagates out of `logfire.span(...)`, which records it and sets
  error status before re-raising; the caller (`Runtime.run`) sees the same exception it would without
  tracing.
- **Concurrent `init()`**: serialized by `Logfire._init_lock`; `logfire.configure()` runs once.

## Testing

Run: `cd ak-py && uv run pytest tests/test_trace.py tests/test_trace_logfire.py`

### `tests/test_trace.py` (extend)

Add one test mirroring the langfuse/openllmetry missing-extra tests (`test_trace.py:81-97`):

```python
def test_trace_logfire_missing_extra_raises_friendly_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "logfire", None)  # simulate SDK not installed
    with patch.object(AKConfig, "get", return_value=_config(True, "logfire")):
        with pytest.raises(ImportError) as exc_info:
            Trace.get()
    assert "agentkernel[logfire]" in str(exc_info.value)
```

(`_config` and imports already exist in the file.)

### `tests/test_trace_logfire.py` (new)

The `logfire` SDK is not a test dependency, so a `fake_logfire` fixture injects a fake module into
`sys.modules` and purges any cached `agentkernel.trace.logfire.*` submodules before and after, so the
AK runner modules import against the fake and later `test_trace.py` runs see a clean slate:

- **Fake module**: `configure = Mock()`, `instrument_openai_agents = Mock()`, and `span = Mock(return
  value=span_cm)` where `span_cm` is a `MagicMock` with `__enter__` returning itself and `__exit__`
  returning `False`.
- `test_factory_builds_logfire` — `patch.object(AKConfig, "get", ...)` with `type="logfire"`, assert
  `Trace.get()._instance` is a `Logfire` and `fake.configure` was called.
- `test_init_configures_once` — reset `Logfire._configured = False`, call `init()` twice, assert
  `fake.configure.call_count == 1`.
- `test_smolagents_runner_wraps_span_and_sets_io` — `patch.object(SmolagentsRunner, "run",
  AsyncMock(return_value=AgentReplyText(response="hi", prompt="q")))`; run the Logfire runner; assert
  `fake.span` called with `session_id=session.id`, and `span.set_attribute` called with `("input","q")`
  and `("output","hi")`.
- `test_smolagents_runner_propagates_error_to_span` — base `run` raises `RuntimeError`; assert the run
  re-raises and `span_cm.__exit__` first positional arg is `RuntimeError`.
- `test_openai_runner_activates_instrumentation` — patch `OpenAIRunner.run`; construct
  `LogfireOpenAIRunner`; assert `fake.instrument_openai_agents` called; run and assert span wrap.
- `test_all_runners_subclass_base` — for each of the five runners (patching the OpenInference
  instrumentors on the crewai/adk modules to avoid real global instrumentation side effects), assert
  the Logfire runner is a subclass of its framework base and is constructible.

Patch targets: base runner `run` methods (`agentkernel.framework.<fw>.<fw>.<Fw>Runner.run`); the
crewai/adk OpenInference instrumentors by attribute on the imported runner module
(`agentkernel.trace.logfire.crewai.CrewAIInstrumentor`, `...crewai.LiteLLMInstrumentor`,
`...adk.GoogleADKInstrumentor`); `logfire` via the `fake_logfire` fixture. `Session` from
`agentkernel.core.base`; reply/request models from `agentkernel.core.model`.

The riskiest consumer (`trace/trace.py`) is covered by the factory build test plus the existing
`test_trace.py` disabled/unknown/BYO/missing-extra suite.
