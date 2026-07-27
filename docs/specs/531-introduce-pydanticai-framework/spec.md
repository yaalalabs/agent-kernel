# #531: Evaluate and Integrate Pydantic AI as an Agentic Platform — Implementation Spec

Details how the sixth AK framework adapter approved in [design.md](design.md) gets built:
`framework/pydanticai/`, its two trace runners, packaging, tests, example, and docs. Every
Pydantic AI API referenced below was verified at runtime against `pydantic-ai==2.13.0` (installed
in an isolated venv, cross-checked against `github.com/pydantic/pydantic-ai` tag `v2.13.0` source)
during this spec's research pass — not paraphrased from memory. Two places where design.md's
OpenAI-mirroring assumption turned out not to hold for Pydantic AI are called out explicitly below,
since they change concrete requirements without changing the design decision design.md already made.

## Design

### Package layout

```
ak-py/src/agentkernel/framework/pydanticai/
├── __init__.py            # from .pydanticai import PydanticAIModule, PydanticAIToolBuilder
└── pydanticai.py          # PydanticAISession, PydanticAIRunner, PydanticAIAgent, PydanticAIModule, PydanticAIToolBuilder

ak-py/src/agentkernel/pydanticai.py                      # public alias (re-exports the above)
ak-py/src/agentkernel/trace/langfuse/pydanticai.py       # LangFusePydanticAIRunner
ak-py/src/agentkernel/trace/openllmetry/pydanticai.py    # OpenLLMetryPydanticAIRunner
ak-py/tests/test_pydanticai_runner.py
ak-py/tests/test_tool_pydanticai.py
examples/cli/pydanticai/{pyproject.toml,demo.py,demo_test.py,README.md}
docs/docs/frameworks/pydantic-ai.md
```

`FRAMEWORK = "pydanticai"` constant (settled naming, design.md "Package layout and naming").

### `PydanticAISession` — message history

```python
class PydanticAISession:
    def __init__(self):
        self._messages: list[dict] = []   # jsonable form — design.md "Session and message history"

    @property
    def messages(self) -> list[dict]:
        return self._messages

    @messages.setter
    def messages(self, value: list[dict]) -> None:
        self._messages = value
```

Retrieval mirrors `OpenAIRunner._session()` (`openai.py:86-95`):
`session.get(FRAMEWORK) or session.set(FRAMEWORK, PydanticAISession())`.

The Runner, not this class, does the jsonable↔object conversion (`to_jsonable_python()` /
`ModelMessagesTypeAdapter.validate_python()`), keeping this class a plain data holder — no Pydantic
AI imports needed here at all.

- `to_jsonable_python` is in **`pydantic_core`**, not `pydantic_ai`: `from pydantic_core import
  to_jsonable_python` (verified: `pydantic_ai/_spec.py:25` imports it from there).
- `ModelMessagesTypeAdapter` is a plain `pydantic.TypeAdapter(list[ModelMessage], ...)` instance in
  `pydantic_ai.messages` (also re-exported at top-level `pydantic_ai`) — `.validate_python()` /
  `.dump_python()` are standard `TypeAdapter` methods, nothing Pydantic-AI-specific.
  Source: `github.com/pydantic/pydantic-ai@v2.13.0/pydantic_ai_slim/pydantic_ai/messages.py:2451-2458`.

### Request/response conversion

`_process_requests()` equivalent (mirrors `openai.py:97-150`'s prompt-accumulation + content-list
shape), mapped to Pydantic AI's confirmed multi-modal input types:

```python
import base64
from pydantic_ai import BinaryContent, DocumentUrl, ImageUrl
from pydantic_ai.messages import UserContent

@staticmethod
def _process_requests(requests: list[AgentRequest]) -> tuple[str, list[UserContent]]:
    prompt = ""
    content: list[UserContent] = []
    for req in requests:
        if isinstance(req, AgentRequestAny):
            continue
        elif isinstance(req, AgentRequestText):
            prompt = f"{prompt}\n{req.prompt}" if prompt else req.prompt
            content.append(req.prompt)
        elif isinstance(req, AgentRequestImage):
            if not req.image_data:
                raise ValueError("no image input provided")
            if req.image_data.startswith(("http://", "https://", "s3://")):
                content.append(ImageUrl(url=req.image_data))
            else:
                if not req.mime_type:
                    raise ValueError("mime_type is missing for image input, either in the base64 or explicitly")
                content.append(BinaryContent(data=base64.b64decode(req.image_data), media_type=req.mime_type))
        elif isinstance(req, AgentRequestFile):
            if not req.file_data:
                raise ValueError("no file input provided")
            if req.file_data.startswith(("http://", "https://", "s3://")):
                content.append(DocumentUrl(url=req.file_data))
            else:
                if not req.mime_type:
                    raise ValueError("mime_type is missing for file input, either in the base64 or explicitly")
                content.append(BinaryContent(data=base64.b64decode(req.file_data), media_type=req.mime_type))
    return prompt, content
```

- `ImageUrl(url: str, *, media_type: str | None = None, ...)` and `DocumentUrl` (same `FileUrl`
  family) auto-infer `media_type` from the URL when omitted.
- `BinaryContent(data: bytes, *, media_type: str, ...)` requires raw `bytes` — unlike the OpenAI
  adapter, which passes the base64 string straight through as a `data:` URI (`openai.py:121,125`)
  and never decodes it, this adapter **must** `base64.b64decode()` first. No equivalent "pass the
  base64 string through" shortcut exists for Pydantic AI's `BinaryContent`.
- `[text, ImageUrl(...)]`-style plain lists are the documented multi-modal input shape (confirmed
  against `agent.run_sync(['What company...', ImageUrl(url=...)])` in the official docs), matching
  `run()`'s parameter type `user_prompt: str | Sequence[UserContent] | None`.
- Sources: `pydantic_ai_slim/pydantic_ai/messages.py:406-449` (`ImageUrl`), `:523-682`
  (`BinaryContent`), `:888-908` (`UserContent`/`MultiModalContent` aliases); `pydantic.dev/docs/ai/input/`.

### `PydanticAIRunner.run()`

```python
class PydanticAIRunner(BaseRunner):
    def __init__(self):
        super().__init__(FRAMEWORK)

    async def run(self, agent: "PydanticAIAgent", session: Session, requests: list[AgentRequest]) -> AgentReply:
        context: ToolContext | None = None
        prompt = ""
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, content = self._process_requests(requests)
            if not content:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            fw_session = self._session(session)
            history = ModelMessagesTypeAdapter.validate_python(fw_session.messages) if fw_session and fw_session.messages else None

            result = await agent.agent.run(content, message_history=history)

            if fw_session is not None:
                fw_session.messages = to_jsonable_python(result.all_messages())

            structured = AgentReplyAny.from_output(result.output, prompt)
            if structured is not None:
                return structured
            return AgentReplyText(response=str(result.output), prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()
```

- `agent.run()`'s full confirmed signature includes `message_history=`, `deps=`, `usage_limits=`,
  `model=` (override), among others (`agent/abstract.py:413-434`) — this adapter uses only
  `message_history=`, matching design.md's "Model and provider selection" (no `deps=` — AK doesn't
  adopt `deps_type`; no override params — AK never re-configures the user's own agent).
- `AgentRunResult.output` (a plain dataclass field, `run.py:483-484`) — confirmed **not** `.data` or
  `.final_output` (the pre-v2 names). `.all_messages()` (`run.py:523`) returns
  `list[ModelMessage]`.
- `AgentReplyAny.from_output(result.output, prompt)` (`core/model.py:143-159`) needs no change —
  it already handles a `BaseModel` or `dict` value; `result.output` is a real `BaseModel` instance
  when `output_type` is a Pydantic model on the user's agent.
- Error handling and the "no valid content" short-circuit are byte-for-byte the same contract as
  `openai.py:179-180,191-192`.

### `PydanticAIRunner.stream()`

```python
async def stream(self, agent: "PydanticAIAgent", session: Session, requests: list[AgentRequest]) -> AsyncGenerator[str, None]:
    context: ToolContext | None = None
    try:
        context = ToolContext(Runtime.current(), agent, session, requests).set()
        prompt, content = self._process_requests(requests)
        if not content:
            return

        fw_session = self._session(session)
        history = ModelMessagesTypeAdapter.validate_python(fw_session.messages) if fw_session and fw_session.messages else None

        async with agent.agent.run_stream(content, message_history=history) as result:
            async for delta in result.stream_text(delta=True):
                if delta:
                    yield delta
            if fw_session is not None:
                fw_session.messages = to_jsonable_python(result.all_messages())
    finally:
        if context is not None:
            context.reset()
```

- `run_stream()` shares `run()`'s exact parameter list (`agent/abstract.py:746-747`,
  `@asynccontextmanager`) — used as `async with agent.run_stream(...) as result:`.
- `StreamedRunResult` (a **different class** from `AgentRunResult` — no `.output` field; instead
  `async def get_output()`) **does** have `all_messages()` with the identical signature to
  `AgentRunResult.all_messages()` (confirmed: `result.py`, both list `all_messages`, `new_messages`,
  `all_messages_json`, `new_messages_json`) — history persistence after a streamed run uses the
  same call as the non-streaming path.
- `stream_text(delta=True)` yields plain `str` deltas (`result.py:550`), matching `Runner.stream()`'s
  contract (`core/base.py:235`, yields `str`).
- Caveat (design.md already flags this; restated for the implementer): a streaming run stops at the
  first `output_type` match, so combining `output_type` with AK's streaming mode truncates
  differently than the non-streaming path — document in the docs page (see Examples and docs).

### `PydanticAIToolBuilder` — tool binding

```python
from pydantic_ai import Tool

class PydanticAIToolBuilder(ToolBuilder):
    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Tool]:
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            tools.append(Tool(func))
        return tools
```

- `Tool.__init__(function, *, name=None, description=None, ...)` — confirmed real class,
  importable as `pydantic_ai.Tool` (`tools.py:290-336`; re-exported `pydantic_ai/__init__.py:137-142`).
  `Agent(tools=[...])` accepts a mix of `Tool` instances and bare callables in the same list
  (`tools: Sequence[Tool[AgentDepsT] | ToolFuncEither[AgentDepsT, ...]]`, `agent/__init__.py:354`) —
  this adapter always wraps explicitly with `Tool(func)` rather than relying on the auto-wrap, for
  parity with `function_tool(func)` (`openai.py:370`) always producing an explicit tool object.
- No `deps_type`/`RunContext` involvement — confirmed design decision (design.md "Tool binding"),
  unaffected by anything in this research pass.

### `PydanticAIAgent` — agent wrapper

Two of design.md's four "mirrors `openai.py`" assumptions **do not hold** for Pydantic AI — the
native API doesn't expose the same read path the OpenAI SDK's `Agent` does. Both are resolved here
with a verified, working alternative; the requirement itself (design.md's four abstract methods)
is unchanged.

**`get_description()` — corrected mechanism.**
```python
def get_description(self) -> str:
    if self.agent.description:
        return self.agent.description
    # Best-effort fallback: no public getter for instructions exists, so read the private
    # ``_instructions`` list and keep the static string parts (callable contributors are skipped).
    instructions = getattr(self.agent, "_instructions", None) or []
    return " ".join(i for i in instructions if isinstance(i, str))
```
Pydantic AI's `Agent` has a **separate**, purpose-built `description: str | None` constructor
parameter that *is* a plain readable/writable property (`agent/__init__.py:880-894`; confirmed
`Agent('test', description="does X").description == "does X"`, defaults to `None`) — that is the
primary source. When it is unset we fall back to the agent's static instructions, because unlike
the OpenAI adapter (where `instructions` doubles as the description) Pydantic AI keeps the two
fields apart, so a description-less agent otherwise reports an empty summary.

`agent.instructions` is **not** a readable attribute — it's an overloaded decorator method
(`type(Agent('test').instructions) is method`, confirmed at runtime) used to *register* a dynamic
instructions function, with no public getter (the configured value is normalized into a private
`agent._instructions: list[str | SystemPromptFunc]`, confirmed at runtime for 2.13.0). The fallback
therefore reads that private list defensively (`getattr(..., None)`) and joins only its `str`
parts.
- **Best-effort, deliberately not load-bearing.** Because `_instructions` is a private attribute of
  a fast-moving library, the fallback is wrapped so that if the attribute ever disappears or changes
  shape, `get_description()` degrades to `""` rather than raising — matching this design's own
  version-skew guidance. Setting `description=` explicitly avoids the fallback entirely and is the
  recommended path.
- Consequence to document prominently (docs page, example): unlike OpenAI agents, where
  `instructions` is effectively mandatory so `get_description()` reliably returns real content,
  Pydantic AI's `description` is optional and easy to leave unset — an agent that passes neither
  `description=` nor `instructions=` reports an empty string here and an empty A2A card summary.

**`override_system_prompt()` — corrected mechanism.**
```python
def override_system_prompt(self, prompt: str) -> None:
    if prompt:
        self._agent.instructions(lambda p=prompt: p)
```
Since `instructions` has no public read path, the OpenAI adapter's pattern — read the current
string, check membership, `+=` (`openai.py:255-262`) — has no equivalent. The only supported way to
*add* instruction content is Pydantic AI's own public decorator API: calling `agent.instructions(func)`
registers `func` as one more contributor to the agent's system prompt (appended to the private
list internally; confirmed decorator semantics, `agent/__init__.py:2045-2086`). No de-duplication
guard is possible (no read path to check "already present" against) — acceptably low risk, since
`_setup_system_prompt()` (`core/base.py:336-344`) is called exactly once per `Agent.__init__()`
under the existing convention, so no code path invokes `override_system_prompt()` twice on one
instance.

**`attach_tool()` — confirmed mechanism.**
```python
def attach_tool(self, tool: Any) -> None:
    wrapped = PydanticAIToolBuilder.bind([tool])
    function_toolset = next((ts for ts in self._agent.toolsets if isinstance(ts, FunctionToolset)), None)
    if function_toolset is None:
        return
    for w in wrapped:
        if w.name not in function_toolset.tools:
            function_toolset.add_tool(w)
```
`attach_tool()` runs during `PydanticAIAgent.__init__`, after the user's own `Agent(...)` call has
already completed, to register the multimodal `AnalyzeAttachmentsTool` on an **already-built**
`Agent`. The verified post-construction path (confirmed against `pydantic-ai==2.13.0`) is
`FunctionToolset.add_tool(tool)`: reach the agent's own `FunctionToolset` via the public
`agent.toolsets` property (AK never uses the `toolsets=` constructor parameter, so exactly one
`FunctionToolset` is present), then call `add_tool()`. The `w.name not in function_toolset.tools`
guard is safe because `FunctionToolset.tools` is a plain public `dict[str, Tool[Any]]`
(`toolsets/function.py:50`), and skips re-registering a tool of the same name (matching the
CI-tested behaviour in `test_pydanticai_runner.py`'s multimodal-wiring test).

**`get_a2a_card()` — confirmed safe enumeration.**
```python
def get_a2a_card(self):
    from a2a.types import AgentSkill
    from pydantic_ai import FunctionToolset

    skills = []

    def visitor(ts):
        if isinstance(ts, FunctionToolset):
            for name, tool in ts.tools.items():
                skills.append(AgentSkill(id=name, name=name, description=tool.description or "", tags=[]))

    for toolset in self.agent.toolsets:
        toolset.apply(visitor)

    return A2ACardBuilder.build(name=self.name, description=self.get_description(), skills=skills)
```
- `agent.toolsets` (public property, `agent/__init__.py:2834-2840`) — **do not** index `[0]`
  assuming exactly one entry. Confirmed count varies: a plain `Agent(tools=[fn1, fn2])` produces
  exactly one entry (an `_AgentFunctionToolset`, a `FunctionToolset` subclass), and a structured
  `output_type` does *not* add an entry (output tools are tracked separately, excluded by design per
  the property's own docstring) — but attaching anything via the constructor's `toolsets=[...]`
  parameter (MCP servers, prefixed/filtered/renamed wrapper toolsets) adds more entries. Confirmed:
  `Agent('test', toolsets=[FunctionToolset([fn1]).prefixed('ns')])` → 2 entries.
  Since AK's tool-binding model never uses `toolsets=`, only the plain `tools=[...]` construction
  path applies here in practice — but the enumeration code must not assume that structurally.
- `AbstractToolset.apply(visitor)` (`toolsets/abstract.py:182-184`) is the confirmed safe,
  synchronous, `RunContext`-free traversal: `CombinedToolset`/`WrapperToolset` subclasses recurse
  into their wrapped members, so `.apply()` reaches every real leaf toolset regardless of nesting
  (confirmed: applying to a `PrefixedToolset` wrapping a `FunctionToolset` visits the underlying
  `FunctionToolset`, not the wrapper).
- Only `FunctionToolset` (and subclasses) expose a public synchronous `.tools: dict[str, Tool[Any]]`
  — no other toolset kind has an equivalent sync attribute; the general async path
  (`get_tools(ctx)`) needs a `RunContext`, which isn't available here, so non-`FunctionToolset`
  leaves are silently skipped. Acceptable for this adapter (AK never attaches MCP/other toolsets to
  a wrapped agent), but worth a one-line comment so a future reader doesn't wonder why the skip
  exists.
- Known limitation to document (not fixed here): tool names read off an unwrapped
  `FunctionToolset.tools` do **not** carry a `PrefixedToolset`'s prefix (confirmed: dict key stayed
  `'fn1'`, unprefixed) — prefixing is applied only inside the wrapper's own async `get_tools()`. Not
  reachable via AK's tool-binding model today (no prefixing), so no action needed now; flagged for
  whoever adds prefixed-toolset support later.

### `PydanticAIModule`

```python
class PydanticAIModule(Module):
    def __init__(self, agents: list, runner: "PydanticAIRunner" = None):
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().pydanticai()
        else:
            self.runner = PydanticAIRunner()
        self.load(agents)

    def _wrap(self, agent, agents) -> "PydanticAIAgent":
        if agent.name is None:
            raise ValueError(
                "Pydantic AI agents passed to PydanticAIModule must have an explicit name= — "
                "AK registers agents by name immediately, before any run triggers Pydantic AI's "
                "call-frame name inference."
            )
        return PydanticAIAgent(agent.name, self.runner, agent)

    # load()/pre_hook()/post_hook() — identical three-line bodies to OpenAIModule (openai.py:319-346)
```

- `Agent.__init__` has a real `name: str | None = None` parameter (`agent/__init__.py:341-362`) —
  *not* always populated: per the docstring, when omitted Pydantic AI "tries to infer the agent
  name from the call frame when the agent is first run," confirmed at runtime (`Agent('test').name`
  reads back `None` until a run happens). Since `Module.load()` (`core/module.py:59-77`) calls
  `_wrap()` and registers the result immediately — before any run — an agent constructed without an
  explicit `name=` would reach `Runtime.register()` with `agent.name is None`. This validation is
  the only clean fix; no sibling adapter needs it, because none of the other five SDKs' agent
  objects have an optional/inferred name.

## Tracing — asymmetric wiring across the two backends

Two runner files, each following its own backend's *existing* wiring shape (design.md already
decided this; the exact mechanism below is new information from this spec's research pass).
Neither backend's Pydantic AI runner can be a mechanical copy of its OpenAI sibling, because
Pydantic AI is the only one of the six frameworks with **native** OTel instrumentation — every
other framework has no OTel support of its own and depends entirely on an external OpenInference
patch to emit any spans at all.

### `trace/langfuse/pydanticai.py` (`LangFusePydanticAIRunner`)

Structurally mirrors `LangFuseOpenAIRunner` (`trace/langfuse/openai.py:12-41`): constructor takes
the shared `Langfuse` client; `run()` wraps `super().run()` in
`propagate_attributes(session_id=session.id, tags=["agentkernel"])` +
`self._client.start_as_current_observation(name="Agent Kernel Pydantic AI", as_type="span")`, then
`span.update(input=result.prompt, output=str(result))`.

`__init__` instrumentation differs from `OpenAIAgentsInstrumentor().instrument()`
(`trace/langfuse/openai.py:23`) — there is no equivalent single-instrumentor-class call for
Pydantic AI. Two calls instead:
1. `Agent.instrument_all()` — confirmed `@staticmethod` (`agent/__init__.py:839-842`), sets a
   process-wide class variable (`Agent._instrument_default`) that every agent instance not
   explicitly overridden reads at run time. This turns on Pydantic AI's own native OTel emission.
2. Register `OpenInferenceSpanProcessor()` (from `openinference-instrumentation-pydantic-ai`,
   confirmed to exist on PyPI, v0.1.17, Arize-ai) on the active `TracerProvider` — reshapes Pydantic
   AI's native spans into OpenInference's semantic-convention schema.

Nuance worth documenting rather than silently treating as equally load-bearing: for the other four
patch-based frameworks, the OpenInference instrumentor is the *only* source of any tracing detail.
For Pydantic AI, step 1 alone already produces OTel GenAI-semantic-convention spans that Langfuse
(itself OTel-based since v3) can already ingest — Pydantic AI's own docs list Langfuse as a natively
supported OTel consumer. Step 2 is therefore supplementary (useful for OpenInference-schema
consumers like Arize Phoenix specifically) rather than strictly required for Langfuse — bundled per
the explicit decision to match the `crewai`/`adk` convention; it does no harm, but do not describe
it in docs/comments as the sole source of tracing the way it is for the other frameworks.

### `trace/openllmetry/pydanticai.py` (`OpenLLMetryPydanticAIRunner`)

Wraps `run()` in `TraceloopContext(app_name="AgentKernel Pydantic AI", association_properties={"session_id": session.id})`,
mirroring `OpenLLMetryOpenAIRunner` (`trace/openllmetry/openai.py:10-30`) exactly for that part.

`__init__` **diverges from every sibling OpenLLMetry runner** (openai/langgraph/crewai/adk/
smolagents — confirmed by reading all of `trace/openllmetry/openai.py` and `openllmetry.py`, none
call any per-framework instrumentor) by calling `Agent.instrument_all()` explicitly:
- Every sibling relies entirely on `Traceloop.init()` (`OpenLLMetry.init()`,
  `trace/openllmetry/openllmetry.py:96-101`, called once globally) auto-instrumenting whatever
  supported libraries the installed `traceloop-sdk` bundles.
- Whether `traceloop-sdk` (the actual pinned package, `openllmetry = ["traceloop-sdk>=0.61.0"]`)
  bundles a Pydantic AI auto-instrumentor is **unconfirmed** — a targeted search found no explicit
  documentation either way, and this spec does not assert it either way.
- Calling `Agent.instrument_all()` directly removes the dependency on that uncertainty: Pydantic
  AI's native instrumentation only needs an active `TracerProvider` to emit into — `Traceloop.init()`
  has already installed one globally — not a framework-specific patch. This makes the call a safe,
  low-cost addition regardless of whether Traceloop's own bundle turns out to cover Pydantic AI too
  (calling `instrument_all()` twice, from two places, is harmless — it's an idempotent class-variable
  assignment).

## Packaging (`ak-py/pyproject.toml`)

```toml
pydanticai = [
    "pydantic-ai-slim~=2.13.0",
    "openinference-instrumentation-pydantic-ai>=0.1.17",
]
```

`pydantic-ai-slim`, **not** the full `pydantic-ai` meta-package the design was first written against
— a correction forced by the shared `ak-py/uv.lock`, which resolves every extra together. The full
`pydantic-ai==2.13.0` pulls `pydantic-ai-slim[…,mcp,…]` → `fastmcp-slim` → `py-key-value-aio>=0.4.4`,
unsatisfiable alongside AK's existing `mcp` extra (`fastmcp>=2.14.2,<3.0.0` → `py-key-value-aio<0.4.0`);
`uv lock` fails outright. `pydantic-ai-slim` is the provider-agnostic core — no bundled providers, no
`fastmcp` — so the lock resolves cleanly (399 packages, verified) and it aligns with design.md's
"model/provider choice is entirely the user's responsibility" principle. The adapter imports only
slim-core symbols (`Agent`, `Tool`, `BinaryContent`/`ImageUrl`/`DocumentUrl`, `FunctionToolset`,
`messages.ModelMessagesTypeAdapter`/`UserContent`) and the tests use slim-core `TestModel`
(`pydantic_ai.models.test`), so slim is sufficient for the adapter and its whole test suite.
**Consequence to document:** `agentkernel[pydanticai]` installs no model provider — the user adds one
(`pydantic-ai-slim[openai]`, `[anthropic]`, `[google]`, …). Both version numbers confirmed
current-latest at spec time (`openinference-instrumentation-pydantic-ai` 0.1.17 released 2026-06-30).
`requires-python = ">=3.12,<3.14"` (`pyproject.toml:10`) already exceeds Pydantic AI's `>=3.10`
floor — no compatibility gate needed. `ak-py/uv.lock` must be regenerated (`uv lock`) as part of this
change.

## Consumer changes

- **Tracing — four factory files must change together.** `pydanticai()` is `@abstractmethod` on
  `BaseTrace`, and there are **three** concrete `BaseTrace` subclasses that get instantiated
  (`Trace` at `trace.py:8`, `LangFuse` at `langfuse/langfuse.py:11`, `OpenLLMetry` at
  `openllmetry/openllmetry.py:88`) — each currently declares exactly the five framework methods and
  no `pydanticai()`. Adding the abstract method without implementing it in all three makes them
  un-instantiable (`TypeError`). All four edits below land in one commit:
  - **`trace/base.py`** (`BaseTrace`, `:6-47`): add the abstract method, verbatim shape of the
    existing five:
    ```python
    @abstractmethod
    def pydanticai(self) -> Runner:
        """
        Initialize Pydantic AI instrumentation
        """
        raise NotImplementedError
    ```
  - **`trace/trace.py`** (`Trace`, `:8-94`): add the delegating method, verbatim shape of the
    existing five:
    ```python
    def pydanticai(self) -> Runner | None:
        """
        Returns the Pydantic AI trace runner instance.
        """
        if self._instance is not None:
            return self._instance.pydanticai()
        return None
    ```
  - **`trace/langfuse/langfuse.py`** (`LangFuse`, after `smolagents()` at `:62`): add the factory
    method returning the new runner, mirroring the sibling five (`return LangFusePydanticAIRunner(self._client)`).
  - **`trace/openllmetry/openllmetry.py`** (`OpenLLMetry`, after `smolagents()` at `:135`): same
    (`return OpenLLMetryPydanticAIRunner()`).
  - The two runner files themselves (`trace/langfuse/pydanticai.py`, `trace/openllmetry/pydanticai.py`)
    are specified under "Tracing — asymmetric wiring across the two backends" above.
- **`ak-py/pyproject.toml`**: add the `pydanticai` optional-dependency group (above). No other
  group changes.
- **`docs/sidebars.js`**: insert `'frameworks/pydantic-ai',` between the confirmed current entries
  `'frameworks/smolagents'` (line 55) and `'frameworks/multi-framework'` (line 56) — the last
  framework-specific page before the cross-framework synthesis page.
- **`ak-py/src/agentkernel/__init__.py`**: verified, no change — it does only `from .core import *`;
  none of the five existing frameworks are re-exported here either (confirmed by reading the file
  in full this session), so `pydanticai` needs no addition, consistent with existing precedent.

## Config changes

None. `AKConfig` (`core/config.py:374-402`) gains no new section or field:
- Model/provider selection has no `AKConfig` surface by design (design.md "Model and provider
  selection") — nothing to add.
- `Trace.get().pydanticai()` dispatches through the **existing** `_TraceConfig.type` field
  (`core/config.py:256-258`, pattern already `^(langfuse|openllmetry)$`) exactly like the other
  five frameworks — `pydanticai()` is one more method on the same `Trace`/`BaseTrace` pair, selected
  implicitly by whichever `trace.type` value is already configured. No pattern, field, or default
  changes.

## Behavioural notes — divergences from the sibling-adapter pattern

Not a refactor of existing shipped behavior (this is purely additive), but six points where this
adapter's concrete mechanism necessarily differs from the five existing adapters' pattern, each
because of a real Pydantic AI API difference discovered during this spec's research, not a
stylistic choice:

1. **`get_description()`** reads `agent.description` (a dedicated, publicly-readable property), not
   `agent.instructions` (write-only decorator method), with a guarded best-effort fallback to the
   private `_instructions` string parts when `description` is unset — see `PydanticAIAgent` wrapper
   above. Consequence: unlike the OpenAI adapter, where `instructions` is effectively mandatory,
   `description` is optional and commonly unset — wrapped agents that set neither `description=` nor
   `instructions=` report an empty string. Document prominently in the docs page and example.
2. **`override_system_prompt()`** appends via the public `agent.instructions(func)` decorator
   registration, not string `+=` — Pydantic AI's instructions have no public read path at all, so
   the "read, check, concatenate" pattern (`openai.py:255-262`) has no equivalent.
3. **No de-duplication guard** on `override_system_prompt()` — not possible without a read path.
   Low risk: `_setup_system_prompt()` runs exactly once per `Agent.__init__()`.
4. **`PydanticAIModule._wrap()` validates `agent.name is not None`** — no sibling adapter needs
   this; Pydantic AI is the only wrapped SDK where the agent's name is optional and inferred
   lazily (at first run), which is too late for AK's eager registration at load time.
5. **`OpenLLMetryPydanticAIRunner` self-instruments** (`Agent.instrument_all()` in `__init__`) —
   every sibling OpenLLMetry runner calls no per-framework instrumentor, relying entirely on
   Traceloop's bundled auto-instrumentors. Pydantic AI is the only one of the six frameworks where
   that bundle's coverage is unconfirmed, so this adapter doesn't assume it.
6. **`attach_tool()` registers on the agent's `FunctionToolset` via `add_tool()`** — the
   post-construction path verified against `pydantic-ai==2.13.0` (see `PydanticAIAgent` wrapper
   above), reaching the toolset through the public `agent.toolsets` property.

**Non-changes**, for reviewer confidence:
- All five existing adapters (`framework/{openai,crewai,langgraph,adk,smolagents}/`), their tests,
  and their examples are untouched.
- Core abstractions (`Session`, `Runner`, `Agent`, `Module`, `ToolContext`, `Runtime`) are
  unmodified; `PydanticAI*` classes subclass them exactly as the existing five do.
- `AKConfig` — zero fields, defaults, or patterns change (see Config changes).
- `agentkernel/__init__.py` — no re-export added, matching existing precedent.

## Error handling

- Model/provider/API failures during `agent.run()`/`run_stream()` (rate limits, timeouts, provider
  errors) are caught by the same catch-all as every other adapter:
  `except Exception as e: return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)`
  (`openai.py:191-192`) — Pydantic AI's own exception types are not special-cased, matching how the
  OpenAI adapter treats all exceptions uniformly today.
- Missing `mime_type` on non-URL image/file input raises `ValueError` synchronously before any
  model call — same trigger condition and message pattern as `openai.py:118-123,138-141`.
- Empty/invalid content (`_process_requests()` returns `[]`) short-circuits to
  `AgentReplyText(response="Sorry. No valid content found in the requests")` without invoking the
  agent, mirroring `openai.py:179-180`.
- Missing optional dependency (`pydantic-ai` or `openinference-instrumentation-pydantic-ai` not
  installed): the module-level `from pydantic_ai import ...` imports in
  `framework/pydanticai/pydanticai.py` raise a plain `ImportError` at import time — matching
  `framework/openai/openai.py`'s `from agents import ...` (no `try/except ImportError` guard in a
  framework adapter module itself; that pattern belongs to config-driven factories like
  `SessionStoreBuilder`, per `ak-dev-architecture` — a framework module is only imported when the
  user's own code imports it, so a missing extra surfaces immediately and unambiguously).
- `agent.name is None` at `_wrap()` time raises `ValueError` with a clear message (Behavioural
  notes #4) rather than silently registering an agent under a `None` key.

## Testing

**`ak-py/tests/test_pydanticai_runner.py`** — mirrors `test_openai_runner.py`'s two test classes
(`TestOpenAIRunnerErrorHandling`, `TestOpenAIRunnerStructuredOutput`), with one **mock-target
correction**: `test_openai_runner.py` patches a module-level `Runner` class
(`patch("agentkernel.framework.openai.openai.Runner")`, since the OpenAI Agents SDK calls
`Runner.run(agent.agent, ...)` as a free function). Pydantic AI has no equivalent module-level
runner — `run()` is an instance method on the agent object itself — so these tests must instead
mock the agent: `mock_agent.agent.run = AsyncMock(return_value=mock_run_result)` with
`mock_run_result.output = ...` (not `.final_output`). Copying the OpenAI test file's patch target
verbatim would silently test nothing.
- Error-handling cases (parity with `TestOpenAIRunnerErrorHandling`): `None` output → empty string;
  normal text reply; generic exception → normalized error (`"Error"` prefix); numeric reply → string
  coercion.
- Structured-output cases (parity with `TestOpenAIRunnerStructuredOutput`): `BaseModel`-typed
  `.output` → `AgentReplyAny` with `.content` matching `model_dump()`; `dict`-typed `.output` →
  `AgentReplyAny`.
- Streaming cases (no sibling analog — every adapter except OpenAI stubs `stream()`): drive the real
  `TestModel` streaming path through a wrapped `PydanticAIAgent` and assert `stream()` yields
  non-empty `str` deltas that reassemble into the model output and that the streamed run persists
  message history into the framework session (so a follow-up turn resumes); plus a no-valid-content
  case that yields nothing and leaves the session untouched. The e2e harness can't drive SSE, so
  this generator-level unit test is the coverage for the adapter's headline differentiator.
- New case, no analog in any sibling adapter test (per design.md "Tests"): `PydanticAISession`
  round-trips through `BinarySerde` (`core/session/serde.py`) — build a non-trivial jsonable
  message-history list via `to_jsonable_python()` on real `ModelRequest`/`ModelResponse` instances,
  pickle + unpickle, assert `ModelMessagesTypeAdapter.validate_python()` reconstructs identically.
- New case, addressing design.md's explicit test requirement ("Missing `override_system_prompt`/
  `attach_tool` means multimodal support silently degrades rather than erroring — needs a spec.md
  test case"): with `AKConfig.multimodal.enabled` monkeypatched to `True`, construct a
  `PydanticAIAgent` and assert both multimodal wiring points actually fire during `__init__` —
  `override_system_prompt()` is invoked with the system-tool prompt suffix (assert by spying on
  `agent.instructions`, since it has no public read-back to check the registered text against
  directly — see `PydanticAIAgent` wrapper above), and `attach_tool()` registers
  `AnalyzeAttachmentsTool` (assert it appears in the agent's `FunctionToolset.tools` — the confirmed
  `add_tool()` registration path above). This guards against exactly the failure mode design.md
  names: if either wiring point silently breaks, multimodal support disappears without raising, so
  this test must fail loudly instead of passing vacuously.

**`ak-py/tests/test_tool_pydanticai.py`** — mirrors `test_tool_openai.py`'s full class structure
(bind-basics, tool-metadata, sync/async/mixed-binding, edge cases) with two attribute-path
corrections: assert `isinstance(tools[0], Tool)` (`pydantic_ai.Tool`) in place of `FunctionTool`;
read the JSON schema via `tool.function_schema.json_schema` in place of `tool.params_json_schema`
(Pydantic AI's confirmed schema attribute path, `tools.py`).

**Existing test files**: none change — this is purely additive; no existing test references
anything this adapter touches.

**Command**: `cd ak-py && uv run pytest tests/test_pydanticai_runner.py tests/test_tool_pydanticai.py`,
then the full `uv run pytest` + `make lint-check-all` per `ak-dev-code-quality`'s pre-submission
checklist.

## Examples and docs

**`examples/cli/pydanticai/`**:
- `pyproject.toml` — mirrors `examples/cli/openai/pyproject.toml` exactly (same black/isort/mypy
  120-line config, same `dev` group shape), swapping the extra:
  `dependencies = ["agentkernel[cli,pydanticai]>=0.6.1"]` (`0.6.1` matches the current
  `ak-py/pyproject.toml` version, confirmed this session).
- `demo.py` — triage/math/weather multi-agent shape mirroring `examples/cli/openai/demo.py`, using
  delegation-via-tool in place of `handoffs=[...]` (design.md Non-goals). Every agent must pass an
  explicit `name=` (Behavioural notes #4) and should pass `description=` explicitly (Behavioural
  notes #1), so the example itself demonstrates non-empty agent descriptions rather than silently
  relying on the same omission it documents as a pitfall.
- `demo_test.py` — mirrors `examples/cli/openai/demo_test.py` exactly:
  `agentkernel.test.Test`, `@pytest.mark.order`-sequenced turns, `test_client.send()`/`.expect()`.

**`docs/docs/frameworks/pydantic-ai.md`** — mirrors `docs/docs/frameworks/openai.md`'s full section
set (confirmed by reading it in full: Installation, Basic Usage, Multi-Agent System, Configuration,
Tool Binding, Structured Output, Features, Example), with three adapter-specific deviations to
write explicitly rather than silently copy:
- "Multi-Agent System" shows delegation-via-tool-call, not a `handoffs=[...]` parameter (doesn't
  exist on Pydantic AI's `Agent`).
- "Structured Output" keeps the same `:::info Streaming limitation` callout pattern
  (`openai.md:109-111`) but with Pydantic AI's own caveat text: a streaming run stops at the first
  `output_type` match (`PydanticAIRunner.stream()` above), not "streamed runs emit token-by-token
  text deltas only" (the OpenAI page's reason, which doesn't apply the same way here).
- A short explicit note that `description=` should be set on every agent — unlike the OpenAI page's
  example, which needs no equivalent note since `instructions` alone already guarantees non-empty
  descriptions there.

**`docs/sidebars.js`** — insert `'frameworks/pydantic-ai',` between `'frameworks/smolagents'` and
`'frameworks/multi-framework'` (Consumer changes, above).

**`docs/docs/frameworks/overview.md`** — enumerates every framework in four places, all of which go
stale without a Pydantic AI entry (verified against the file): the mermaid diagram (`:13-17`), the
"when to use" table (`:28-32`), the capability matrix (`:39`), and the per-framework prose sections
with their `[Learn more →]` links (`:51-89`). Add a Pydantic AI row/branch/section to each, matching
the shape of the existing five. The capability matrix must state Pydantic AI's real support (native
streaming — unlike CrewAI/Smolagents; structured output via `output_type`; multi-provider), not a
copy of the OpenAI row.

**READMEs (accuracy, not marketing).** Two factual lists go wrong if left alone:
- `ak-py/README.md:11` — "Multi-Framework Support: OpenAI Agents SDK, CrewAI, LangGraph, Google ADK,
  and Smolagents" → add Pydantic AI.
- `ak-py/README.md:1327-1330` — the per-framework session-data-key list (`"openai"`, `"crewai"`,
  `"langgraph"`, `"adk"`) → add `"pydanticai"`.
- Root `README.md:39,100` (framework-agnostic feature line and framework badge) may also be updated
  for completeness, but note the badge at `:100` already lists "Smol Agents (soon)" despite
  Smolagents being implemented — that pre-existing staleness is out of scope for this ticket; do not
  try to reconcile it here.
Adding a per-framework "Pydantic AI Example" section to `ak-py/README.md` (mirroring the existing
`:54-128` blocks) is optional and can follow the docs page.
