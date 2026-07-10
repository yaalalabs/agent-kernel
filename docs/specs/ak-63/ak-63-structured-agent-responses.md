# Structured agent response support in framework runners (AK-63)

This change introduces a new reply model, `AgentReplyAny`, that carries a structured (JSON) agent response as a dict, and teaches every framework runner (`OpenAIRunner`, `GoogleADKRunner`, `CrewAIRunner`, `LangGraphRunner`, `SmolagentsRunner`) to detect structured output from its framework and return it as an `AgentReplyAny` instead of coercing it to a string. The structured reply flows through the pre/post-execution hook chain unchanged, so hooks can inspect and modify the dict content directly. Plain-text agents continue to return `AgentReplyText` — existing behavior is fully preserved.

Streaming is explicitly out of scope: streamed runs emit token-by-token text deltas and are unaffected.

## Motivation

Every framework supported by Agent Kernel offers a first-class way to make an agent produce structured output (a Pydantic model or JSON schema-conforming result). Today the runners discard that structure:

- `OpenAIRunner.run()` (`ak-py/src/agentkernel/framework/openai/openai.py:182-185`) takes `RunResult.final_output` — which is a Pydantic instance when the agent is built with `Agent(output_type=MyModel)` — and does `str(reply)`, wrapping the repr in `AgentReplyText`.
- `GoogleADKRunner.run()` (`ak-py/src/agentkernel/framework/adk/adk.py:195-214`) returns the final response text as-is. For an `LlmAgent(output_schema=MyModel)` that text is a JSON string, which the caller must re-parse.
- `CrewAIRunner.run()` (`ak-py/src/agentkernel/framework/crewai/crewai.py:325-332`) only reads `CrewOutput.raw`, ignoring the `pydantic` / `json_dict` fields CrewAI populates for structured tasks. Moreover, the runner constructs the `Task` itself, so there is currently no way to even request structured output.
- `LangGraphRunner.run()` (`ak-py/src/agentkernel/framework/langgraph/langgraph.py:390-395`) extracts the last message's text and ignores the `structured_response` key that `create_react_agent(response_format=MyModel)` places in the result dict.
- `SmolagentsRunner.run()` (`ak-py/src/agentkernel/framework/smolagents/smolagents.py:156-161`) does `str(reply)` on whatever `agent.run()` returns, even when the final answer is a dict or Pydantic instance.

Consumers that need the structure are forced to re-parse `reply.text` (fragile: Pydantic reprs are not JSON) — structured output is effectively unsupported end-to-end.

There is a precedent on the request side: `AgentRequestAny` (`ak-py/src/agentkernel/core/model.py:55-66`) carries arbitrary content with `type: Literal["other"]`. `AgentReplyAny` is its reply-side analogue.

## `AgentReplyAny` model

**File:** `ak-py/src/agentkernel/core/model.py`

```python
import json


class AgentReplyAny(BaseModel):
    """
    AgentReplyAny encapsulates a structured (JSON) reply from an agent.

    content: dict : The structured agent output as a JSON-compatible dict
    prompt: str   : The text prompt sent to the agent
    type: Literal["other"]
    """

    content: dict
    prompt: str = ""
    type: Literal["other"] = "other"

    def __str__(self) -> str:
        return json.dumps(self.content)
```

Design points:

- `__str__` returns the JSON-serialized content. Every consumer that renders replies as text keeps working unchanged: the trace runners (`span.update(..., output=str(result))` in `ak-py/src/agentkernel/trace/langfuse/*.py`), chat integrations, and logging all call `str()` on the reply. All of them also read `reply.prompt`, which `AgentReplyAny` provides.
- `content` is typed `dict` (not `Any`), matching the requirement — a structured reply is always a JSON object at the top level. Runners guarantee JSON compatibility by converting Pydantic instances with `model_dump(mode="json")` (see below), so `json.dumps(self.content)` cannot fail on datetimes, UUIDs, enums, or nested models.
- `type` is `Literal["other"]`, symmetric with `AgentRequestAny`.

The reply union alias is extended:

```python
type AgentReply = Union[AgentReplyText, AgentReplyImage, AgentReplyAny]
```

`AgentReplyAny` is exported from `ak-py/src/agentkernel/core/__init__.py` alongside `AgentReplyText` / `AgentReplyImage` (and therefore from the top-level `agentkernel` package via `from .core import *`).

### Note on `model_dump(mode="json")`

The requirement states Pydantic results are converted "via `model_dump()`". This spec uses `model_dump(mode="json")` everywhere: it is the same method, but it serializes non-JSON-native field types (datetime, UUID, Enum, Decimal, nested models) into JSON-compatible values. Plain `model_dump()` would leave e.g. a `datetime` object inside `content`, and `str(reply)` / `json.dumps` would then raise `TypeError`. Since the class contract documents `content` as "a JSON-compatible dict", `mode="json"` is the correct conversion.

## Runtime hook-chain integration

**File:** `ak-py/src/agentkernel/core/runtime.py`

The runtime gates the hook chain with hardcoded isinstance tuples. All of them must include `AgentReplyAny` (import it alongside the existing model imports at `runtime.py:16-18`):

1. **`_prepare_requests()` — pre-hook halt detection (`runtime.py:148`).** `isinstance(reply, (AgentReplyText, AgentReplyImage))` becomes `isinstance(reply, (AgentReplyText, AgentReplyImage, AgentReplyAny))`. A pre-hook may now halt execution by returning a structured reply. (Without this, an `AgentReplyAny` returned from a pre-hook would fall through to the `list` validation and raise `TypeError`.)
2. **`run()` — halt short-circuit (`runtime.py:181`).** Same tuple extension, so a structured halt reply is returned to the caller.
3. **`run()` — post-hook return validation (`runtime.py:193`).** Same tuple extension. This is the critical one: without it, the first post-hook in a structured run (the always-present system `OutputGuardrail`) returns the `AgentReplyAny` untouched and the runtime raises `TypeError: PostHook 'OutputGuardrail' returned an invalid type` — structured output would break every run with the default configuration.
4. **`stream()` — pre-hook halt detection (`runtime.py:218`).** Same tuple extension. A structured halt reply during streaming yields `StreamChunk(error=str(requests_or_reply), done=True)` — the JSON string — consistent with the existing text behavior.

With these gates widened, hook semantics follow automatically from the existing flow (`runtime.py:190-195`): the reply produced by the runner — now an `AgentReplyAny` when output is structured — is passed as-is to each post-hook's `on_run(session, requests, agent, agent_reply)`. Hooks receive the structured object with its dict `content`, may inspect or mutate `reply.content` in place or return a different `AgentReply`, and the chain threading is unchanged.

`ak-py/src/agentkernel/core/hooks.py` needs no code change (it is typed against the `AgentReply` union). Its docstrings are updated to mention that `agent_reply` may be an `AgentReplyAny` carrying dict content.

## Runner changes

Common rules across all five runners:

- Detection happens only in the non-streaming `run()` path. `stream()` implementations are untouched.
- Pydantic instances → `AgentReplyAny(content=value.model_dump(mode="json"), prompt=prompt)`.
- Plain dicts → `AgentReplyAny(content=value, prompt=prompt)` (used directly as content).
- Anything else follows the existing text path → `AgentReplyText`.
- Error handling is unchanged: the existing `except Exception` blocks keep returning `AgentReplyText(text=user_facing_error_message(e), prompt=prompt)`. A failure is a text reply even for a structured-output agent.
- The "no valid content" early returns keep returning `AgentReplyText`.

A small shared helper keeps the type-based branches identical across runners. Since there is no shared runner-utility module today, add it to `ak-py/src/agentkernel/core/model.py` as a classmethod (keeping runners dependency-free of each other):

```python
class AgentReplyAny(BaseModel):
    ...

    @classmethod
    def from_output(cls, value: Any, prompt: str = "") -> "AgentReplyAny | None":
        """
        Builds an AgentReplyAny from a framework output value if it is structured.
        Returns None when the value is not structured (caller falls back to text).
        """
        if isinstance(value, BaseModel):
            return cls(content=value.model_dump(mode="json"), prompt=prompt)
        if isinstance(value, dict):
            return cls(content=value, prompt=prompt)
        return None
```

### OpenAI Agents SDK — `OpenAIRunner`

**File:** `ak-py/src/agentkernel/framework/openai/openai.py`

Structured output mechanism: `Agent(output_type=MyModel)`; `RunResult.final_output` is then a Pydantic instance (or a dict for schema-dict output types).

`run()` (`openai.py:182-185`) changes from:

```python
reply = (await Runner.run(agent.agent, input_data, session=session_to_use)).final_output

reply_text = "" if reply is None else str(reply)
return AgentReplyText(text=reply_text, prompt=prompt)
```

to:

```python
reply = (await Runner.run(agent.agent, input_data, session=session_to_use)).final_output

structured = AgentReplyAny.from_output(reply, prompt)
if structured is not None:
    return structured
reply_text = "" if reply is None else str(reply)
return AgentReplyText(text=reply_text, prompt=prompt)
```

`None` and scalar final outputs (e.g. the numeric reply covered by `test_runner_normalizes_numeric_reply`) keep their existing text behavior.

### Google ADK — `GoogleADKRunner`

**File:** `ak-py/src/agentkernel/framework/adk/adk.py`

Structured output mechanism: `LlmAgent(output_schema=MyModel)`. ADK does not hand back a Pydantic instance — the final response text is a JSON string conforming to the schema. Detection is therefore configuration-based, not type-based.

In `run()` (`adk.py:195-214`), after obtaining the response text:

```python
reply = await self.get_response(runner=runner, session_id=session.id, parts=parts, user_id=user_id)

output_schema = getattr(agent.agent, "output_schema", None)
if output_schema is not None:
    try:
        parsed = output_schema.model_validate_json(reply)
        return AgentReplyAny(content=parsed.model_dump(mode="json"), prompt=prompt)
    except ValidationError:
        self._log.warning("Agent '%s' has output_schema set but reply is not valid JSON for it; returning text", agent.name)
return AgentReplyText(text=reply, prompt=prompt)
```

Notes:

- `agent.agent` is the wrapped ADK `BaseAgent`; `output_schema` only exists on `LlmAgent`, hence `getattr(..., None)`. Multi-agent trees whose root has no `output_schema` are unaffected.
- Validating with `output_schema.model_validate_json()` (rather than a bare `json.loads`) enforces the schema and normalizes values; `model_dump(mode="json")` then produces the content dict.
- On validation failure (model produced malformed or non-conforming JSON) the runner logs a warning and falls back to `AgentReplyText` with the raw text — a degraded-but-usable reply rather than an error. `pydantic.ValidationError` is imported for this.
- `GoogleADKRunner` currently has no `self._log`; add one in `__init__` (`logging.getLogger("ak.adk.runner")`), consistent with `CrewAIRunner`.

### CrewAI — `CrewAIRunner`

**File:** `ak-py/src/agentkernel/framework/crewai/crewai.py`

Structured output mechanism: `Task(output_pydantic=MyModel)` or `Task(output_json=MyModel)`. CrewAI then populates `CrewOutput.pydantic` / `CrewOutput.json_dict` respectively, alongside `CrewOutput.raw`.

**Configuration gap.** Unlike the other frameworks, the structured-output knob lives on the `Task`, and `CrewAIRunner.run()` constructs the `Task` internally (`crewai.py:314-318`). To make the mechanism reachable, `CrewAIAgent` gains two optional attributes that the runner forwards to the task it builds:

- `CrewAIAgent.__init__(self, name, runner, agent, crew, output_pydantic: type[BaseModel] | None = None, output_json: type[BaseModel] | None = None)`, stored as `self._output_pydantic` / `self._output_json` and exposed via read/write properties (`output_pydantic`, `output_json`). Writable properties matter because `CrewAIModule._wrap()` (`crewai.py:441-448`) creates the wrappers automatically; users configure structured output after loading:

  ```python
  module = CrewAIModule([my_crewai_agent])
  module.get_agent("Researcher").output_pydantic = ResearchReport
  ```

- `CrewAIRunner.run()` builds the task as:

  ```python
  task = Task(
      description=prompt,
      expected_output="An answer is plain text",
      agent=agent.agent,
      output_pydantic=getattr(agent, "output_pydantic", None),
      output_json=getattr(agent, "output_json", None),
  )
  ```

  (`getattr` keeps the runner working with custom `Agent` subclasses that predate these properties, e.g. in tests.)

**Reply conversion** is purely type-based on the `CrewOutput`, replacing `crewai.py:326-332`:

```python
reply = await crew.kickoff_async(inputs={})
if isinstance(getattr(reply, "pydantic", None), BaseModel):
    return AgentReplyAny(content=reply.pydantic.model_dump(mode="json"), prompt=prompt)
if isinstance(getattr(reply, "json_dict", None), dict):
    return AgentReplyAny(content=reply.json_dict, prompt=prompt)
if hasattr(reply, "raw"):
    raw_reply = reply.raw
    reply_text = "" if raw_reply is None else str(raw_reply)
else:
    reply_text = "" if reply is None else str(reply)
return AgentReplyText(text=reply_text, prompt=prompt)
```

`pydantic.BaseModel` is imported for the isinstance check. Because detection reads the `CrewOutput` fields directly, it also works for users who run a custom `CrewAIRunner` subclass that builds structured tasks its own way.

**Conversation transcript & memory resilience.** Alongside the structured-output changes, `CrewAIRunner.run()` gains a lightweight conversation transcript so follow-up prompts carry deterministic context independent of embedding-based memory recall:

- `TRANSCRIPT_KEY = f"{FRAMEWORK}_transcript"` and `TRANSCRIPT_MAX_LINES = 20` class attributes.
- `_transcript(session)` reads (and lazily initializes to `[]`) the transcript list stored under `TRANSCRIPT_KEY` in session data; returns `None` when no session is provided.
- `_describe(prompt, transcript)` builds the `Task` description, prepending `"Previous conversation:\n{history}\n\nCurrent request:\n{prompt}"` when a transcript exists, else just the prompt. The task is now built with `description=self._describe(prompt, transcript)` instead of the bare prompt.
- After the reply is produced (structured or text), the current turn is appended as `f"User: {prompt}"` and `f"Assistant: {str(agent_reply)}"` (so a structured reply is recorded as its JSON string), then trimmed to the most recent `TRANSCRIPT_MAX_LINES` entries via `del transcript[: -TRANSCRIPT_MAX_LINES]`. The transcript is only updated on the success path — an error reply (from the `except` block) is not recorded.
- `memory.remember(content=prompt)` is now wrapped in a `try/except`: a failure (e.g. no embedder configured) logs a warning and sets `memory = None` so the run continues without memory rather than failing. The broken memory is therefore not handed to the `Crew`. The transcript is the deterministic fallback that keeps conversational context working regardless of memory availability.

### LangGraph — `LangGraphRunner`

**File:** `ak-py/src/agentkernel/framework/langgraph/langgraph.py`

Structured output mechanism: an agent built with `create_react_agent(..., response_format=MyModel)`. The result dict of `ainvoke()` then contains a `structured_response` key (a Pydantic instance) alongside `messages`.

`run()` (`langgraph.py:390-395`) changes to:

```python
result = await agent.agent.ainvoke(
    input={"messages": messages},
    config=config,
)
structured = AgentReplyAny.from_output(result.get("structured_response"), prompt)
if structured is not None:
    return structured
last_message = result["messages"][-1]
return AgentReplyText(text=self._extract_text_content(last_message.content), prompt=prompt)
```

`from_output` handles both the usual Pydantic instance and a dict (which LangGraph produces when `response_format` is given as a raw JSON schema); a missing key yields `None` and falls through to the existing text extraction.

### SmolAgents — `SmolagentsRunner`

**File:** `ak-py/src/agentkernel/framework/smolagents/smolagents.py`

SmolAgents has no first-class schema parameter; `agent.run()` returns whatever the agent passed to `final_answer`, which may be a non-string object. Detection is purely type-based, replacing `smolagents.py:161`:

```python
reply = await asyncio.to_thread(agent.agent.run, prompt, reset=False)

self._sync_memory(agent, session)

structured = AgentReplyAny.from_output(reply, prompt)
if structured is not None:
    return structured
return AgentReplyText(text=str(reply), prompt=prompt)
```

dict → `AgentReplyAny(content=reply)`; Pydantic instance → `AgentReplyAny(content=reply.model_dump(mode="json"))`; everything else (including smolagents' `AgentText`-style wrapper types, which are not dicts or BaseModels) → `AgentReplyText(text=str(reply))`, exactly as today.

### Trace runners

The Langfuse and OpenLLMetry runner wrappers (`ak-py/src/agentkernel/trace/langfuse/*.py`, `ak-py/src/agentkernel/trace/openllmetry/*.py`) subclass the framework runners and delegate to `super().run()`, recording `result.prompt` and `str(result)`. Both attributes exist on `AgentReplyAny` (with `str()` yielding the JSON content), so tracing works unchanged with no code changes.

## Downstream text consumers

`str(reply)` compatibility covers most consumers, but three places type-switch on the reply and need explicit handling:

1. **`ResponseBuilder.build_response()`** (`ak-py/src/agentkernel/core/chat_service.py:285`) currently emits `"Non textual result received"` for anything that is not `AgentReplyText` / `AgentReplyImage`. Add `AgentReplyAny` to the isinstance tuple, so the REST/API `result` field carries `str(result)` — the JSON string. The field deliberately stays a string (not a nested object) to avoid changing the response schema for existing API clients; callers who need the dict use the reply object in-process, and a follow-up may add a structured API response shape.
2. **`AgentService.run()`** (`ak-py/src/agentkernel/core/service.py:121-135`) returns `"Non-text reply given"` for non-text replies. Add a branch: `elif isinstance(result, AgentReplyAny): result = str(result)` so string-oriented callers (CLI) get the JSON text. `run_multi()` already returns the reply object untouched — it is the structured-consumption entry point.
3. **`BaseGuardrailUtil._extract_text_from_reply()`** (`ak-py/src/agentkernel/guardrail/guardrail.py:91-100`) returns `""` for replies without a `text` attribute, which would silently exempt structured replies from output guardrails. Add: `if isinstance(agent_reply, AgentReplyAny): return str(agent_reply)` so guardrails scan the JSON serialization of the structured content.
4. **Slack integration** (`ak-py/src/agentkernel/integration/slack/slack_chat.py:157`) has the same isinstance gate as `ResponseBuilder`: `str(result) if isinstance(result, (AgentReplyText, AgentReplyImage)) else "Non textual result received"`. Add `AgentReplyAny` to the tuple so structured replies render as their JSON string.
5. **Teams integration** (`ak-py/src/agentkernel/integration/teams/teams_chat.py:293`) had a gate that already fell through to `str(reply)` in both branches. It is tightened to match Slack/`ResponseBuilder`: `str(reply) if isinstance(reply, (AgentReplyText, AgentReplyImage, AgentReplyAny)) else "Non textual result received"` — `AgentReplyAny` renders as its JSON string and other reply types now surface the explicit "Non textual result received" message. `AgentReplyAny` is imported for the check.

The remaining chat integrations require no changes: WhatsApp (`whatsapp_chat.py:294`) calls `str(reply)` unconditionally, and Telegram/Instagram/Gmail/Messenger use `str(result.raw) if hasattr(result, "raw") else str(result)` — no `AgentReply` type has a `raw` attribute, so they fall through to `str(result)`, which yields the JSON string for `AgentReplyAny`.

## Out of scope

- **Streaming.** `Runner.stream()` implementations yield token-by-token text deltas; a structured-output agent used in streaming mode streams whatever text the framework emits (for ADK/OpenAI that is the raw JSON text as it is generated). No structured detection, buffering, or parsing is added to the stream path. The only stream-adjacent change is the widened isinstance gate for pre-hook halts (runtime item 4 above).
- **Agent-to-agent (handoff) calls inside a framework workflow** — hooks do not run there today (`hooks.py` module docstring) and this change does not alter that.
- **A structured (non-string) `result` field in API responses** — see `ResponseBuilder` note above.

## Error handling

- Runner exceptions: unchanged — `AgentReplyText(text=user_facing_error_message(e), prompt=prompt)` in every runner, even for structured-output agents.
- ADK `output_schema` set but the model's reply is not valid JSON for the schema: warning logged, fall back to `AgentReplyText` with the raw text (no exception surfaces to the caller).
- Post-hook returns something outside the `AgentReply` union: still raises `TypeError` (`runtime.py:193-194`), now with `AgentReplyAny` accepted as valid.
- `AgentReplyAny(content=...)` with a non-dict: pydantic `ValidationError` at construction — a programming error in a custom runner/hook, surfaced immediately.

## Testing

### `ak-py/tests/test_model.py` (new)

1. **Construction & defaults:** `AgentReplyAny(content={"a": 1})` has `prompt == ""` and `type == "other"`; `content` round-trips.
2. **`__str__` returns JSON:** `str(AgentReplyAny(content={"city": "Colombo", "temp_c": 31}))` equals the `json.dumps` of the dict (parseable via `json.loads`, not a Python repr).
3. **Serialization:** `model_dump()` / `model_dump_json()` include `content`, `prompt`, `type`.
4. **Validation:** non-dict `content` raises `ValidationError`.
5. **`from_output`:** Pydantic instance → content dict with JSON-compatible values (use a model containing a `datetime` field to pin `mode="json"`); dict → used as-is; string/int/None → `None`.

### Runner tests (per framework)

Each case asserts the reply type, the exact `content` dict, and the `prompt` field; plus one regression case asserting a plain-text agent still yields `AgentReplyText`.

6. **`ak-py/tests/test_openai_runner.py` (extend):** mock `Runner.run` so `final_output` is (a) a Pydantic instance → `AgentReplyAny` with `model_dump` content; (b) a dict → `AgentReplyAny` with that dict; (c) a string → `AgentReplyText` (existing tests, unchanged — including `test_runner_normalizes_numeric_reply`).
7. **`ak-py/tests/test_adk_runner.py` (new):** stub `GoogleADKRunner.get_response` to return a JSON string; agent stub with `output_schema=MyModel` → `AgentReplyAny` with the parsed dict; with `output_schema` set but a non-JSON reply → fallback `AgentReplyText` with the raw text (and no exception); without `output_schema` → `AgentReplyText`.
8. **`ak-py/tests/test_crewai_runner.py` (new):** mock `Crew.kickoff_async` to return a `CrewOutput`-shaped stub with (a) `pydantic` set → `AgentReplyAny` from `model_dump`; (b) `pydantic=None`, `json_dict` set → `AgentReplyAny` with `json_dict`; (c) only `raw` → `AgentReplyText`. Also verify `run()` forwards `output_pydantic` / `output_json` from the wrapped `CrewAIAgent` into the constructed `Task`. Transcript/memory coverage: `_describe()` returns the bare prompt with no transcript and prepends `"Previous conversation:"` history otherwise; `_transcript()` returns `None` without a session and lazily creates/reuses a list; a successful turn (structured or text) is appended and the transcript is capped at `TRANSCRIPT_MAX_LINES`; an error reply is not recorded; a `memory.remember()` failure does not fail the run and the broken memory is not handed to the `Crew`.
9. **`ak-py/tests/test_langgraph_runner.py` (new):** mock `agent.agent.ainvoke` to return `{"messages": [...], "structured_response": MyModel(...)}` → `AgentReplyAny`; a dict `structured_response` → `AgentReplyAny`; no `structured_response` key → `AgentReplyText` from the last message.
10. **`ak-py/tests/test_smolagents_runner.py` (extend):** `agent.run` returning a dict → `AgentReplyAny`; a Pydantic instance → `AgentReplyAny`; a string → `AgentReplyText` (existing tests unchanged).

### Hook-chain tests — `ak-py/tests/test_runtime.py` (extend)

11. **Post-hooks receive the structured object:** a runner stub returning `AgentReplyAny` + a spy post-hook; assert the hook's `agent_reply` argument `is` the `AgentReplyAny` instance (not a stringified reply) and its `content` is the dict.
12. **Post-hook returning `AgentReplyAny` passes validation:** no `TypeError` from `runtime.py:193`; `Runtime.run()` returns the (possibly hook-modified) `AgentReplyAny`. Include a hook that mutates `reply.content` and assert the mutation is visible to the caller.
13. **Pre-hook halt with `AgentReplyAny`:** a pre-hook returning `AgentReplyAny` halts execution (the runner is never called) and `Runtime.run()` returns it.
14. **Stream halt:** the same pre-hook in `Runtime.stream()` yields `StreamChunk(error=<JSON string>, done=True)`.

### Guardrail test — `ak-py/tests/test_guardrail.py` (extend)

15. `_extract_text_from_reply(AgentReplyAny(content={...}))` returns the JSON string.

### Text-consumer tests

16. **`ResponseBuilder.build_response()`** (add to `ak-py/tests/test_api_http.py` or alongside the existing chat-service tests): an `AgentReplyAny` result produces `{"result": <JSON string>}`, not `"Non textual result received"`; an `AgentReplyText` result is unchanged.
17. **Slack rendering** (`slack_chat.py:157`): the rendering expression is inline in the event handler, so cover it by driving the handler with a stubbed service whose `run_multi` returns an `AgentReplyAny` and asserting the message posted via the mocked `say` client is the JSON string. If stubbing the Slack Bolt handler proves disproportionate, the isinstance-tuple change is accepted with review-only coverage — but the `ResponseBuilder` test (item 16) must exist, as it pins the identical expression.

All existing tests must pass unchanged.

## Documentation

- **`docs/docs/core-concepts/runner.md`:** document the `AgentReply` union including `AgentReplyAny` (fields, `__str__` behavior, when each type is produced).
- **`docs/docs/integrations/hooks.md`:** note that `agent_reply` may be an `AgentReplyAny` when the agent produces structured output, with an example post-hook reading/modifying `reply.content`.
- **Framework pages (`docs/docs/frameworks/openai.md`, `google-adk.md`, `crewai.md`, `langgraph.md`, `smolagents.md`):** per-framework "Structured output" section covering the configuration mechanism (`output_type` / `output_schema` / `CrewAIAgent.output_pydantic` & `output_json` / `response_format` / returning a dict or model from `final_answer`) and a consumption example:

  ```python
  reply = await service.run_multi([AgentRequestText(text="Weather in Colombo as JSON")])
  if isinstance(reply, AgentReplyAny):
      data = reply.content          # dict — no re-parsing
  else:
      text = reply.text
  ```

- **Streaming limitation:** state on each framework page's structured-output section (and in the streaming docs under `docs/docs/deployment/` where applicable) that structured output applies to non-streaming execution only; streamed runs emit text deltas.
- Versioned docs (`docs/versioned_docs/`) are left as-is; they describe released versions.

## Implementation plan

### Task 1: Model — `AgentReplyAny`

**File:** `ak-py/src/agentkernel/core/model.py`

1. Add `import json` and define `AgentReplyAny` (fields, docstring, `__str__`, `from_output` classmethod) after `AgentReplyImage`.
2. Extend the alias: `type AgentReply = Union[AgentReplyText, AgentReplyImage, AgentReplyAny]`.
3. Export `AgentReplyAny` from `ak-py/src/agentkernel/core/__init__.py`.

### Task 2: Runtime hook-chain gates

**File:** `ak-py/src/agentkernel/core/runtime.py`

1. Import `AgentReplyAny`; add it to the isinstance tuples at lines 148, 181, 193, and 218.
2. Update the `PreHook` / `PostHook` docstrings in `ak-py/src/agentkernel/core/hooks.py` to mention structured replies.

### Task 3: OpenAI and SmolAgents runners (type-based detection)

**Files:** `ak-py/src/agentkernel/framework/openai/openai.py`, `ak-py/src/agentkernel/framework/smolagents/smolagents.py`

1. Import `AgentReplyAny`; insert the `from_output` check before the existing `str()` coercion in each `run()`.

### Task 4: ADK runner (schema-based detection)

**File:** `ak-py/src/agentkernel/framework/adk/adk.py`

1. Add `self._log` to `GoogleADKRunner.__init__`; import `AgentReplyAny` and `pydantic.ValidationError`.
2. In `run()`, when `getattr(agent.agent, "output_schema", None)` is set, parse the reply text with `output_schema.model_validate_json()` and return `AgentReplyAny`; on `ValidationError` log a warning and fall back to `AgentReplyText`.

### Task 5: CrewAI runner and agent configuration

**File:** `ak-py/src/agentkernel/framework/crewai/crewai.py`

1. Add optional `output_pydantic` / `output_json` constructor parameters and read/write properties to `CrewAIAgent`.
2. Forward them into the `Task` built in `CrewAIRunner.run()`.
3. Replace the reply extraction with the `pydantic` → `json_dict` → `raw` cascade.
4. Add the conversation transcript (`TRANSCRIPT_KEY` / `TRANSCRIPT_MAX_LINES`, `_transcript()`, `_describe()`), build the task description from it, and append/trim the turn on the success path.
5. Wrap `memory.remember()` in a `try/except` that logs a warning and falls back to `memory = None` on failure.

### Task 6: LangGraph runner

**File:** `ak-py/src/agentkernel/framework/langgraph/langgraph.py`

1. Import `AgentReplyAny`; check `result.get("structured_response")` via `from_output` before the last-message text extraction in `run()`.

### Task 7: Downstream text consumers

**Files:** `ak-py/src/agentkernel/core/chat_service.py`, `ak-py/src/agentkernel/core/service.py`, `ak-py/src/agentkernel/guardrail/guardrail.py`, `ak-py/src/agentkernel/integration/slack/slack_chat.py`, `ak-py/src/agentkernel/integration/teams/teams_chat.py`

1. `ResponseBuilder.build_response()`: include `AgentReplyAny` in the isinstance tuple (result field carries the JSON string).
2. `AgentService.run()`: map `AgentReplyAny` to `str(result)`.
3. `BaseGuardrailUtil._extract_text_from_reply()`: return `str(agent_reply)` for `AgentReplyAny`.
4. Slack `slack_chat.py:157`: include `AgentReplyAny` in the isinstance tuple so structured replies render as JSON instead of "Non textual result received".
5. Teams `teams_chat.py:293`: include `AgentReplyAny` in the isinstance tuple. The remaining integrations (WhatsApp, Telegram, Instagram, Gmail, Messenger) need no changes — verified they render via unconditional `str()`.

### Task 8: Tests

**Files:** `ak-py/tests/test_model.py` (new), `ak-py/tests/test_adk_runner.py` (new), `ak-py/tests/test_crewai_runner.py` (new), `ak-py/tests/test_langgraph_runner.py` (new), `ak-py/tests/test_openai_runner.py`, `ak-py/tests/test_smolagents_runner.py`, `ak-py/tests/test_runtime.py`, `ak-py/tests/test_guardrail.py`

1. Implement the test matrix from the Testing section (items 1–15).
2. Run the full suite; all existing tests must pass unchanged.

### Task 9: Documentation

**Files:** `docs/docs/core-concepts/runner.md`, `docs/docs/integrations/hooks.md`, `docs/docs/frameworks/*.md`

1. Document `AgentReplyAny`, per-framework structured-output configuration, hook behavior with structured replies, the consumption example, and the streaming limitation.
