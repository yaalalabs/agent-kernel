# #606: Human-in-the-loop — durable pause, decision, and resume — Implementation Spec

How the design in [`design.md`](design.md) is built. A framework pause becomes a typed
`AgentPausedReplyAny`; the opaque per-framework resume state is written into a list under one new
non-volatile session key; a later request carrying an `AgentResumeRequestAny` resolves that record
and calls `Runner.resume`. Requirements live in `design.md` — this document details the classes,
signatures, placement and tests. Measured framework behaviour is in
[`research/verification.md`](research/verification.md) and is cited rather than restated.

Ships as the five stacked PRs `design.md` defines; each section below names the PR that carries it.

---

## Blockers found while detailing

Two facts in the current code stop a resume request from existing at all. Both are implementation
consequences of a design requirement rather than design changes, but both alter a public model, so
they are called out before anything else.

1. **`BaseChatRequest.prompt` is required** — `prompt: str` with no default (`core/model.py:243-261`).
   A resume-only request carries no prompt, so pydantic rejects it before any AK code runs. It
   becomes `Optional[str] = None` (§ *Config and model changes*). Widening a required field is
   backward-compatible for every existing sender.
2. **`ChatService._validate` raises on a missing prompt** — `if requests is None: if not req.prompt:
   raise ValueError("No prompt provided in the request")` (`chat_service.py:672-688`). The check
   becomes "prompt **or** resume" on the built path.

Neither is optional: without both, PR 2 ships a request shape that cannot be constructed.

---

## Design

### `core/model.py` — the vocabulary (PR 1)

All five types are Pydantic `BaseModel`s beside the existing request/reply models.

```python
class PausedInterruption(BaseModel):
    """One thing a human must decide before the run can continue."""
    id: str                       # unique across every paused run in the session — see below
    kind: Literal["tool_call", "input_required", "confirmation"]
    tool_name: str | None = None
    arguments: str | None = None  # JSON-encoded; never a framework object
    message: str | None = None
    payload: dict | None = None   # the question's own shape, as the framework produced it


class ResumeDecision(BaseModel):
    """A human's answer to one interruption."""
    id: str                                                        # matches a PausedInterruption.id
    status: Literal["approved", "denied", "cancelled"] | None = None
    message: str | None = None                                     # free text
    payload: dict | None = None                                    # structured answer


class ResumeSpec(BaseModel):
    """The public request block, mirroring ScheduleSpec (`model.py:214`)."""
    run_id: str | None = None
    decisions: list[ResumeDecision]


class AgentResumeRequestAny(BaseModel):
    """Union member of AgentRequest. Not a subclass of AgentRequestAny."""
    run_id: str | None = None
    decisions: list[ResumeDecision]
    type: Literal["resume"] = "resume"


class AgentPausedReplyAny(AgentReplyAny):
    """The run stopped and needs a human. Subclass, so the AgentReply union is untouched."""
    run_id: str
    session_id: str
    agent: str
    interruptions: list[PausedInterruption]
    type: Literal["paused"] = "paused"          # overrides AgentReplyAny's "other"
```

Rules this section pins:

1. **`AgentPausedReplyAny` subclasses `AgentReplyAny` (`model.py:129`); the `AgentReply` union
   (`model.py:126`) gains no member.** Verified safe because nothing in `src/` re-validates a reply
   from JSON — no `model_validate`/`TypeAdapter` over `AgentReply` exists. A reviewer re-checks this
   with `grep -rn "model_validate\|TypeAdapter" src/ | grep -i reply`.
2. **`content` is derived, never assigned.** A `@model_validator(mode="after")` populates the
   inherited `content: dict` from `run_id`/`session_id`/`agent`/`interruptions`, so
   `AgentReplyAny.__str__` (`model.py:142-143`) yields readable JSON and the three stringify sites
   degrade gracefully. The typed fields are the source of truth; a caller-supplied `content` is
   overwritten.
3. **`AgentResumeRequestAny` joins the `AgentRequest` union (`model.py:125`)** and costs exactly one
   `isinstance` site: the request-type validation tuple at `runtime.py:247`.
4. **`PausedInterruption.id` is unique across every paused run in the session.** Load-bearing, not
   tidy: it is how `Runtime` resolves which run a decision belongs to when `run_id` is absent, which
   is the only thing AG-UI can do (§ *AG-UI*). Adapters use the framework's own id (OpenAI
   `call_id`, LangGraph `Interrupt.id`, ADK `FunctionCall.id`, Pydantic AI `tool_call_id`), which is
   already per-run unique. On a collision across runs the adapter prefixes with the record's
   `run_id`; `PausedRunState.add` raises `ValueError` if a colliding id reaches it, so the
   invariant fails loudly rather than mis-routing a decision.

`arguments` is a JSON string rather than a dict because a framework's tool arguments arrive as one
(OpenAI `ResponseFunctionToolCall.arguments`) and re-parsing to re-serialise buys nothing.

### `core/event.py` — `RunPaused` (PR 1)

```python
class RunPaused(StreamEventBase):
    type: Literal["run_paused"] = "run_paused"
    run_id: str
    interruptions: list[PausedInterruption]
```

Added to the `StreamEvent` union (`event.py:131-147`). The module docstring's second invariant
(`event.py:16-17`) currently reads *"No field carries a framework-native object. Every field is a
`str`, `int` or `bool`"*. The second sentence is narrowed by this change and is reworded to:

> Every field is composed of JSON primitives — a `str`, `int`, `bool`, or a model built only from
> those — so an event stays picklable and JSON-serialisable no matter which framework produced it.

The first sentence is unchanged and is the real rule. `tests/test_stream_events.py` pins the old
wording and is updated in the same PR; the round-trip and unknown-`type` assertions are unchanged.

Carrying the interruptions as a JSON string instead was rejected: it pushes parsing onto every
consumer to preserve wording whose purpose the list already satisfies.

### `core/paused_run.py` — the record and its accessor (PR 1)

New module. Shaped on `AGUIState` (`integration/agui/state.py:11,16-56`): a module-level key
constant plus a class of static methods over the non-volatile cache.

```python
AK_PAUSED_RUNS_KEY = "ak.paused_runs"


class PausedRun(BaseModel):
    """One paused run. Framework-agnostic envelope around an opaque payload."""
    id: str                                    # assigned by PausedRunState.add
    agent: str
    created_at: str                            # ISO-8601 UTC, diagnostics only
    interruptions: list[PausedInterruption]
    payload: Any                               # per-framework; must be picklable


class PausedRunState:
    """Every read and write of ak.paused_runs goes through here."""

    @staticmethod
    def list(session: Session) -> list[PausedRun]: ...
    @staticmethod
    def get(session: Session, run_id: str) -> PausedRun | None: ...
    @staticmethod
    def find_by_interruption(session: Session, interruption_ids: Iterable[str]) -> PausedRun | None: ...
    @staticmethod
    def add(session: Session, record: PausedRun) -> PausedRun: ...   # assigns id, returns stored
    @staticmethod
    def clear(session: Session, run_id: str) -> None: ...
```

Rules:

1. **The key name is spelled once.** No caller outside this module touches
   `session.get_non_volatile_cache()` for paused runs.
2. **`add` owns three things**, so each has exactly one implementation: it assigns
   `id = uuid4().hex`, runs the picklability check on `record.payload`, and emits the
   `in_memory` warn-once (§ *Durability*). It returns the stored record so the adapter can read the
   generated id back for the reply.
3. **Reads validate rather than trust.** The cache returns `Any`; `list` re-validates each entry
   through `PausedRun.model_validate` and drops (with a `WARNING`) anything that fails, so a cache
   corrupted by application code cannot crash a resume.
4. **`find_by_interruption` returns `None` when the ids span more than one record** — the caller
   turns that into failure mode 1 rather than guessing.
5. **`PausedRunState` is not a `Runner` method.** `Runtime` must read the record to validate a
   resume and `Runtime` is not a `Runner`; adapters must write it. A standalone class is the only
   home both can reach.
6. **Named `…State`, not `…Store`.** Every `*Store` in AK is a pluggable backend with an ABC,
   factory and config block. This is accessors over a dict `SessionStore` already persists
   (`runtime.py:295`). No ABC, no factory, no config — and none is warranted, because there is
   nothing to select between.

**The picklability check is generalised, not copied.** `Runner._ensure_framework_context_picklable`
(`core/base.py`, a `classmethod` taking `(session, ctx)`) and `Runner._not_picklable`
(a `staticmethod`) exist for framework context. `_not_picklable` moves to
`core/util/picklable.py` as a module-level helper — a genuinely stateless shared utility, the
`resolve_dotted` category — and both `Runner._ensure_framework_context_picklable` and
`PausedRunState.add` call it. `Runner`'s method keeps its name, signature and error text, so #526's
behaviour and any test patching it are unchanged.

### `core/base.py` — the `Runner` surface (PR 1)

```python
class Runner(ABC):
    @property
    def supports_pause(self) -> bool:
        """Whether this runner can pause and resume. Defaults to False; adapters opt in."""
        return False

    async def resume(
        self, agent: Any, session: Session, requests: list[AgentRequest],
        decisions: list[ResumeDecision], record: PausedRun,
    ) -> AgentReply:
        raise NotImplementedError(f"{self.name} does not support resuming a paused run")

    async def resume_stream(
        self, agent: Any, session: Session, requests: list[AgentRequest],
        decisions: list[ResumeDecision], record: PausedRun,
    ) -> AsyncGenerator[StreamEvent, None]:
        raise NotImplementedError(f"{self.name} does not support resuming a paused run")
        yield   # unreachable; makes this an async generator
```

- **`supports_pause` defaults to `False`, unlike `supports_streaming` (`base.py:377`, defaults
  `True`).** The asymmetry is deliberate and is the honesty argument: `stream()` is
  `@abstractmethod` (`base.py:386`) so every runner implements it and `True` is honest by default,
  whereas `resume()` is a non-abstract raising default — a `True` default would have a
  bring-your-own `Runner` advertise a capability it does not have and then raise inside its own
  `try`, surfacing as *"Sorry, something went wrong"*.
- **`requests` is the hook-processed list**, not the raw one. Every adapter opens with
  `ToolContext(Runtime.current(), agent, session, requests)` (nine sites, e.g. `openai.py:200`,
  `adk.py:194`) and post-hooks take `requests` (`runtime.py:290`); without it a resuming adapter has
  nothing to put in the tool context.
- **`record` is passed in, not re-read.** `Runtime` validated one record; the adapter must resume
  that one.
- **CrewAI and smolagents need no code.** They inherit the `False` default and the raising
  defaults. This inverts their streaming situation, where they must *actively* set
  `supports_streaming = False` (`crewai.py:412`, `smolagents.py:187`).

**Accepted duplication.** Every framework resumes through its normal native call with different
input, so `resume()` repeats most of `run()` — roughly 80 lines across the four adapters, and the
same again for streaming, of which ~14 per adapter is pure envelope (`ToolContext`,
framework-context load/store, the `except`). Accepted because a separate `resume()` keeps the
capability visible in the type and each method single-purpose. The envelope duplication is
pre-existing — every adapter's `run()` already repeats it — so extracting a shared base-`Runner`
template is its own issue. The piece worth watching is pause *detection*, which exists in both
methods (eight copies); if any envelope is shared first, it should be that.

### `core/runtime.py` — dispatch, diagnostics, cleanup (PR 2)

`Runtime.run` and `Runtime.stream` gain the same shape. Using `run` (`runtime.py:271-298`):

```python
incoming_resume = self._extract_resume(requests)          # before the hook chain
requests_or_reply = await self._prepare_requests(agent, session, requests)   # :278
if isinstance(requests_or_reply, (AgentReplyText, AgentReplyImage, AgentReplyAny)):   # :279
    if incoming_resume is not None:
        self._log.warning(...)                            # warning 2
    return requests_or_reply
requests = requests_or_reply
resume_req = self._extract_resume(requests)               # after the hook chain — the dispatch
if incoming_resume is not None and resume_req is None:
    self._log.warning(...)                                # warning 1
if resume_req is not None:
    record = self._validate_resume(agent, session, resume_req)     # raises; see Error handling
    agent = Runtime.current().agents()[record.agent]               # agent resolved from the record
    reply = await agent.runner.resume(agent, session, requests, resume_req.decisions, record)
    if not isinstance(reply, AgentPausedReplyAny) and PausedRunState.get(session, record.id):
        PausedRunState.clear(session, record.id)          # leftover-record cleanup
else:
    reply = await agent.runner.run(agent, session, requests)       # :286
```

Four rules:

1. **`Runtime` observes as the caller, not as a hook.** It holds the request list, calls
   `_prepare_requests` (`:278` for run, `:328` for stream) and receives either a new list or a
   halting reply. No warning depends on where AK's own hooks sit in the chain — which matters,
   because the order is not what one would guess: pre-hooks run **user first, system last**
   (`pre_hooks = agent.pre_hooks + self._get_system_pre_hooks()`, `runtime.py:238`) and post-hooks
   **system first, user last** (`runtime.py:288`, `:337`).
2. **The dispatch acts on the post-hook list.** A hook that removes the marker really does turn the
   resume into an ordinary turn. The pre-chain boolean exists only so that the loss is logged.
3. **Validation is generic and lives here.** Every adapter wraps its whole body in one `try` whose
   `except Exception` returns `AgentReplyText(user_facing_error_message(e))` (`openai.py:199-221`,
   `langgraph.py:429`, `pydanticai.py:184`, `adk.py:266`), so a check raised inside the adapter is
   swallowed. The four failure modes need no framework knowledge, so adapter-side checks would be
   written four times.
4. **`Runtime` clears a leftover record after a resume that did not pause.** `PausedRunState.clear`
   is otherwise the adapter's, because a resume can pause again and the adapter writes the new
   record. Scoped to *the reply is not an `AgentPausedReplyAny`*, no new pause was created, so a
   record still present can only be the one just resumed. Removing the failure mode beats warning
   about it: the next turn cannot inherit a phantom pause.

`_extract_resume(requests) -> AgentResumeRequestAny | None` and
`_validate_resume(agent, session, req) -> PausedRun` are private methods of `Runtime`.

**Diagnostics.** Three `WARNING`s on the existing `ak.runtime` logger (`runtime.py:139`), each
carrying session id and agent name. Per-occurrence, not warn-once: each is a distinct lost decision,
unlike the `in_memory` topology warning which is a property of the deployment.

| # | Situation | Detected by | Message |
|---|---|---|---|
| 1 | a pre-hook removed the `AgentResumeRequestAny` | before-flag set, post-hook list has no marker | a resume decision was dropped by the pre-hook chain; this run proceeds as a new turn and the pause is still open |
| 2 | a pre-hook halted on a resume | before-flag set and `_prepare_requests` returned a reply, never reaching the runner | a decision was accepted but never delivered; the pause is still open |
| 3 | a post-hook dropped `RunPaused` from a stream | a `RunPaused` was yielded and the chain returned nothing for it (`runtime.py:342-345`) | a pause was dropped by post-hook `<name>`; the client will not learn a decision is owed |

Warning 2 is the only halt with a durable consequence — every other costs a turn and leaves nothing
behind, whereas this leaves a record in the store while the client receives a reply that reads like
completion. It is already logged at `DEBUG` (`runtime.py:280`); what the level change buys is that
the open pause is *named*. Warning 3 can name the offending hook (`hook.name()` is in scope at the
drop site); warnings 1 and 2 cannot, because `_prepare_requests` returns only the reply. Changing
its return shape to carry the hook is **not** done in this change — the warning is useful without it
and the signature is shared with the non-resume path.

**AK does not constrain what a hook may do to a resume.** A guardrail that can stop a first prompt
can stop a decision; that is the application's call. The warnings are the entire mechanism.

### `core/runtime.py` — streaming (PR 2)

`Runtime.stream` (`runtime.py:300-371`) gains the same dispatch around `runner.stream` (`:341`),
dispatching to `resume_stream`, plus three stream-specific rules:

1. **A pause is not an error.** `RunPaused` is yielded as an ordinary `StreamChunk(event=...)` and
   the stream terminates with the existing `StreamChunk(done=True)` (`:365`) — never through
   `StreamChunk.error`, which has a legitimate owner in a post-hook raising `StreamHalt` (`:366`).
   A pause ended in a valid outcome the client can act on; a halt produced an invalidated partial
   the client must discard.
2. **A paused stream drains open boundaries before ending**, exactly as the halt path does at
   `:368-369`. `StreamBoundaryTracker` (`runtime.py:39-102`) exists because ending part-way through
   a `MessageStart`/`ToolCallStart` pair leaves a frontend rendering the tool call as work in
   progress. **The pause path is the common case** — an agent pauses precisely because a tool call
   needs approval, so a `ToolCallStart` is very likely open. Terminal sequence:
   `RunPaused` → the closing events the tracker still owes → `done=True`. Implemented by calling
   `boundaries.drain()` directly rather than reusing the `StreamHalt` branch, which also yields an
   error chunk and skips `sessions().store(session)`; a paused stream **does** store the session.
3. **The session is stored on the pause path.** The record must survive, so the paused stream takes
   the normal `:364` store, not the `StreamHalt` skip.

> **Note for `ak-dev-architecture`:** the skill places `StreamBoundaryTracker` in `core/stream.py`.
> It is at `runtime.py:39`. Worth fixing when the docs/skills sync runs in PR 5.

### `core/chat_service.py` — request and response surface (PR 2)

- **`RequestBuilder.known_fields`** (`chat_service.py:126-141`) gains `"resume"`, so the block is
  never forwarded to an agent as `AgentRequestAny` context — the same reason `schedule`,
  `scheduled_task_id` and `scheduled_time` are already there.
- **`RequestBuilder`** appends an `AgentResumeRequestAny` built from `req.resume` when present.
  Order: it is appended after any text/image/file requests, so a prompt sent alongside it (allowed
  — see below) stays first.
- **`ChatService._validate`** (`:672-688`) becomes prompt **or** resume on the built path:

  ```python
  if requests is None:
      if not req.prompt and req.resume is None:
          raise ValueError("No prompt provided in the request")
  ```

  The message is unchanged for the existing case so no test string moves.
- **`_success_status`** (`:547-554`) gains a second source. A pause is knowable only from the
  *reply*; a schedule only from the *request*. Both converge on `202` for different reasons from
  different inputs, so they stay two conditions:

  ```python
  @staticmethod
  def _success_status(req: BaseChatRequest, reply: AgentReply | None = None) -> int:
      if req.schedule is not None:
          return 202
      if isinstance(reply, AgentPausedReplyAny):
          return 202
      return 200
  ```

  The new parameter defaults to `None` so existing call sites that have no reply keep working.
- **`ResponseBuilder.build_response`** (`:302-335`) adds the discriminator keys when the result is
  an `AgentPausedReplyAny`, alongside the existing `result`:

  ```json
  {"result": "...", "session_id": "...", "status": "PAUSED",
   "run_id": "...", "interruptions": [...]}
  ```

  `status` is a **top-level key**, so a client branches without parsing `result`. **`202` now
  carries two meanings** — `"SCHEDULED"` for a deferred request, `"PAUSED"` for one waiting on a
  human — which is exactly why the key is required rather than optional. The existing
  `rest_api_mode and status_code != 200` branch (`:330`) already returns a `JSONResponse`, so the
  202 travels unchanged.
- **Case is deliberate and the two fields differ.** The model `type` is lowercase `"paused"`, like
  every other discriminator in `model.py`; the body's `status` is uppercase `"PAUSED"`, matching the
  scheduling acknowledgement's `"SCHEDULED"` (`chat_service.py:494`). Do not align them.
- **`schedule` + `resume` is rejected** with `ValueError` → 400: a decision cannot be deferred to a
  cron slot and still be a decision. **Placement is the requirement.** `_maybe_schedule` is the
  first statement of all four entry points — `execute` (`:390`), `execute_sync` (`:407`),
  `execute_stream` (`:428`), `execute_stream_sync` (`:455`) — while `_validate` is not reached until
  `:564`/`:575`. A guard in `_validate` would never fire: the scheduled `202` has already been
  returned. Implementation: a new `ChatService._reject_ambiguous(req)` static method called as the
  first statement of each of the four entry points, ahead of `_maybe_schedule`.
- **`prompt` + `resume` is *not* rejected.** Forwarded to the adapter, which carries or refuses it
  per framework (§ *Adapters*).

### `guardrail/` — the resume text must be guarded (PR 2)

`BaseGuardrailUtil._extract_text_from_requests` (`guardrail/guardrail.py:95-103`) collects text from
`AgentRequestText` only. As the code stands, a human's `ResumeDecision.message` would reach the
model **without any guardrail seeing it** — the exact hole that running pre-hooks on a resume is
meant to close. The loop gains:

```python
elif isinstance(req, AgentResumeRequestAny):
    for d in req.decisions:
        if d.message:
            text_parts.append(d.message)
        if d.payload:
            text_parts.extend(str(v) for v in d.payload.values() if isinstance(v, str))
```

Only **string** payload values are extracted; a nested structure is not flattened, because a
guardrail scanning arbitrary JSON produces false positives on ids and enum values. This lands in
PR 2, not an adapter PR: without it PRs 1–2 ship a stated security property they do not deliver.

Note the ordering consequence: the input guardrail is a *system* pre-hook, so it runs **after** any
user pre-hook (`runtime.py:238`). If a user hook strips the `AgentResumeRequestAny`, the guardrail
never sees the text — but the text never reaches the model either, so that is a lost decision, not
an unguarded one, and warning 1 makes it visible.

### Adapters

Detection is placed **before** the existing text extraction, never as a fallback — that ordering is
what distinguishes this from the current silent-loss behaviour. Each adapter's `resume()` mirrors
its `run()` envelope: `ToolContext`, `_load_framework_context`, the native call, then
`_store_framework_context` and `PausedRunState.clear`/`add` inside the `try` after a successful
call, never in a `finally`, so a crashed run leaves no phantom pause (the placement rule #526 set).

**Framework-specific rejections go above the `try`.** A check inside it is swallowed by the adapter's
own `except Exception`. This is the exception to "validation lives in `Runtime`": `Runtime` cannot
know that OpenAI has no channel for a structured answer without framework knowledge entering
`core/`.

#### OpenAI (PR 3)

| | |
|---|---|
| Detect | `result.interruptions` non-empty, checked **before** `.final_output` (`openai.py:211`) |
| `payload` | `result.to_state().to_json()` |
| Resume | `RunState.from_json(initial_agent=agent.agent, state_json=payload)`, apply `approve`/`reject`, `Runner.run(agent.agent, state)` |
| Interruption `id` | `item.raw_item.call_id` |
| `kind` | `"tool_call"` |

Above the `try`, two rejections — OpenAI has a channel for neither:

- any `ResumeDecision.payload` is not `None` → `ValueError` naming the decision id;
- `req.prompt` present alongside the resume → `ValueError`. `Runner.run`'s `input` is
  `str | list[TResponseInputItem] | RunState`, mutually exclusive (verified).

Decision rendering: `approved` → `state.approve(item)`; `denied` → `state.reject(item,
rejection_message=message)`; `cancelled` → `state.reject(item, rejection_message=<AK's dismissal
text>)`. `approve()` takes no value parameter, which is why a `payload` is refused rather than
dropped.

`resume()` passes `session=self._session(session)` exactly as `run()` does (`openai.py:211`); #679
made `_get_run_input` return only the input shape and both paths pass `session=` unconditionally, so
a paused multimodal run resumes on the same path and needs no special case.

#### LangGraph (PR 3)

| | |
|---|---|
| Detect | `"__interrupt__" in result`, checked **before** `result["messages"][-1]` (`langgraph.py:427`) |
| `payload` | interrupt ids and `.value`s only — AK's checkpointer already holds the state |
| Resume | `ainvoke(Command(resume={id: value}), config)` on the same `thread_id` (= `session.id`) |
| Interruption `id` | `Interrupt.id` |
| `kind` | `"input_required"` |

- **No new persistence.** `_prepare_session_and_messages` already assigns AK's own
  pickle-serializable checkpointer and derives `thread_id` from `session.id`
  (`langgraph.py:368-370`). The spec records that AK **overwrites** a user-supplied checkpointer —
  pre-existing behaviour that HITL makes load-bearing, and that the docs must state (PR 5).
- **Use the literal `"__interrupt__"`**, not `langgraph.constants.INTERRUPT`, which still resolves
  but raises `LangGraphDeprecatedSinceV10`.
- **Streaming detection** reads graph state after the stream drains: the adapter calls
  `astream_events(version="v2")` (`langgraph.py:469-473`), which has no `.interrupts`, and already
  calls `aget_state(config)` at `:481`.
- **A prompt alongside a decision is carried, and the mapping is AK's.** `Command.update` means
  *update the graph state*; there is no "send a prompt with your resume" feature. AK writes the
  prompt into the `messages` channel its adapter already feeds
  (`input_state["messages"] = messages`, `langgraph.py:412`):
  `Command(resume=..., update={"messages": [HumanMessage(content=prompt)]})`. The spec states this
  is AK's encoding, and the per-adapter docs must too.
- **Documented caveat to pass through verbatim** (PR 5): the interrupting node re-runs from the top
  on resume, so side effects before `interrupt()` must be idempotent.

#### Pydantic AI (PR 4)

| | |
|---|---|
| Detect | `isinstance(result.output, DeferredToolRequests)`, checked **before** `AgentReplyAny.from_output` (`pydanticai.py:178`) |
| `payload` | `to_jsonable_python(result.all_messages())` (already written at `:173-174`) plus the requests |
| Resume | `run(content, message_history=..., deferred_tool_results=DeferredToolResults(...))` |
| Interruption `id` | `ToolCallPart.tool_call_id` |
| `kind` | `approvals` → `"tool_call"`; **`calls` → `"input_required"`** |

- **`DeferredToolRequests` is a dataclass, not a `BaseModel`** (verified), so
  `AgentReplyAny.from_output` returns `None` for it (`model.py:157-161`) and today's adapter falls
  through to `str(result.output)` at `:182`, handing the user a dataclass repr. Detecting before
  that call is the fix.
- **Two axes, and both are the answer channel.** `approvals` takes
  `bool | ToolApproved(override_args=dict) | ToolDenied(message=str)`; **`calls` takes an arbitrary
  value that becomes the tool's return**. A `CallDeferred` tool is therefore `input_required`, and
  its `ResumeDecision.payload`/`message` is supplied as the call result — measured: `"damaged"` in,
  `'damaged'` seen by the model; a list in, the list seen.
- **Above the `try`: a partial resume is rejected**, naming the missing ids. The framework raises
  `UserError: Tool call results need to be provided for all deferred tool calls. Expected: {...},
  got: {...}` — a genuinely clear error that the adapter's `except` would turn into *"Sorry,
  something went wrong"*. AK pre-empts it to keep the message.
- **A prompt alongside a decision is native**: `run(prompt, message_history=...,
  deferred_tool_results=...)` returns a normal answer. The guard that otherwise blocks a new prompt
  (*"Cannot provide a new user prompt when the message history contains unprocessed tool calls"*) is
  lifted precisely by supplying the results.

#### Google ADK (PR 4)

| | |
|---|---|
| Detect | per event: `event.long_running_tool_ids` ∩ part `function_call.id`, **or** a `function_call` named `adk_request_confirmation` — in `get_response` (`adk.py:204-230`) |
| `payload` | pending `FunctionCall` id and name, confirmation hint/payload, `invocation_id` |
| Resume | `run_async(new_message=Content(parts=[Part(function_response=...)]))`, plus `invocation_id=` when resumable |
| Interruption `id` | `FunctionCall.id` |
| `kind` | long-running → `"tool_call"`; `adk_request_confirmation` → `"confirmation"` |

- **Durability is confirmed**: the ADK conversation lives in `InMemorySessionService` inside
  `GoogleADKSession` (`adk.py:59-70`), which pickles cleanly both empty and holding a live session
  (`research/verification.md`).
- **The `App` + `ResumabilityConfig` change.** `ResumabilityConfig(is_resumable=True)` lives on an
  `App`, while the adapter builds `Runner(agent=..., app_name=..., session_service=...)` from a bare
  agent (`adk.py:201`). Enabled **unconditionally** — a per-agent gate would reintroduce the enable
  flag the issue forbids. Structurally near-free: ADK already wraps AK's agent in an `App`
  internally and the `app_name` override preserves AK's session key. Two real costs, both documented
  in PR 5 release notes and adapter docs, not hidden:
  - **sub-agent routing changes** — with resumability on, a turn whose previous event was a function
    response is routed back to the agent that made the call. Which agent handles the next turn can
    change for an existing multi-agent ADK app. This is application logic the client owns.
  - **ADK sessions grow**, because `is_resumable` also gates agent-state event emission. Inherent to
    ADK.
- **Streaming pause is unverified — decided by test in PR 4, not assumed.** The design does not
  prevent it. Two things keep it a risk: ADK's own "known limitation" comment on its two-event pause
  window (`base_llm_flow.py:966-978`), and the partial/non-partial id split, where an id a client
  reads off a streamed partial event may never have been persisted (`functions.py:245-246`,
  `base_llm_flow.py:1130-1133`). If the test shows it broken, the streamed run yields a clear error
  and the limitation is documented as **AK's own finding against `google-adk` 2.8.0, with a
  reproducible case** — never attributed to an upstream position that does not exist.
- **A prompt alongside a decision is unverified**: a `Content` can carry a text part beside the
  `function_response`, so it is structurally possible. Established by test in this PR; if it does
  not work, rejected above the `try` like OpenAI.
- **Warning to pass through verbatim** (PR 5): ADK's own "tools in an agent are run at least once,
  and may run more than once when resuming".

#### How each adapter renders `ResumeDecision.status`

Only LangGraph carries all three natively; the others degrade to their binary call, and **AK
supplies the message that keeps the two negative cases distinguishable to the model**:

| Adapter | `approved` | `denied` | `cancelled` |
|---|---|---|---|
| OpenAI | `state.approve(item)` | `state.reject(item, rejection_message=message)` | `state.reject(item, rejection_message=<AK text>)` |
| Pydantic AI | `ToolApproved(override_args=payload)` | `ToolDenied(message=message)` | `ToolDenied(message=<AK text>)` |
| Google ADK | `{"confirmed": true, "payload": payload}` | `{"confirmed": false}` | `{"confirmed": false}` with AK's text where the body allows |
| LangGraph | `Command(resume=...)` | `Command(resume=...)` | `Command(resume=...)` — **carries the status faithfully** |

**The dismissal text is AK's, not the client's.** On `cancelled` the human gave no reason, so
`message` is typically empty. AK generates wording that reads as *an absence of a decision* rather
than a refusal — "we could not get this approved", not "your refund was declined". A bool plus a
client-supplied message could not guarantee that: a client sending nothing would leave the model to
infer a refusal. Defined once as a module constant in `core/model.py`
(`AK_CANCELLED_DECISION_MESSAGE`) so the four adapters do not each invent their own.

**`status` is required only where there is something to approve.** `Runtime` requires it when the
matching interruption's `kind` is `tool_call` or `confirmation`, and ignores it for
`input_required` — a LangGraph `interrupt()` asking "which of these three?" has nothing to approve,
and requiring a verb there would force clients to send a meaningless `approved`.

**All four `resume()` implementations preserve `framework_context`.** Every `run()` loads and writes
back the #526 context (`openai.py:206-210`, `langgraph.py:408-422`, `pydanticai.py:169-176`,
`adk.py:184-199`); `resume()` does the same, or a resumed turn silently drops the caller's context.

### `integration/agui/` — the terminal interrupt outcome (PR 5)

Verified present at AK's **pinned** `ag-ui-protocol` 0.1.22, so no dependency bump.

- **A pause is a terminal outcome, not a mapped mid-stream event.** The run ends with
  `RunFinishedEvent(outcome=RunFinishedInterruptOutcome(interrupts=[...]))`. So
  `AGUIRequestHandler._events` — which today always ends with exactly one of
  `RunFinishedEvent`/`RunErrorEvent` — grows a **third terminal shape**, rather than
  `AGUIMapper.to_agui` gaining a case. `to_agui` keeps returning `None` for `RunPaused`
  (`mapping.py:64-66`) and nothing is dropped, because the terminal outcome carries the pause.
- **`PausedInterruption` → `Interrupt` almost field-for-field.** `kind` passes through as `reason`
  unchanged: `reason` is a free-form `str` (verified, not a closed enum), so **no translation table
  is needed and none should be written** — including for any AK kind added later.
- **State must be emitted first**: any `StateSnapshot`/`MessagesSnapshot` needed for resume precedes
  the `RunFinished` carrying the interrupt.
- **Resume arrives as `RunAgentInput.resume` with no `run_id`** — `ResumeEntry` is
  `{interrupt_id, status, payload}` and the protocol has no field for a run. The run is resolved
  from the `interrupt_id`s via `PausedRunState.find_by_interruption`, which is exactly why
  `run_id` is optional and why `PausedInterruption.id` must be unique across records.
- **`ResumeEntry.status` maps without flattening**: `cancelled` stays `cancelled`; `resolved`
  becomes `approved` or `denied` according to the entry's payload.
- `RunAgentInput.resume` is `Optional[List[ResumeEntry]]` — nothing in the protocol requires every
  open interrupt to be addressed in one resume, and AK does not enforce it on any surface.

### Consumer changes

| Consumer | Change |
|---|---|
| `core/service.py:155` (`AgentService.run`) | Receives `AgentPausedReplyAny` through the existing `isinstance(result, AgentReplyAny)` branch and stringifies it. **Verified unchanged** — the derived `content` makes `str()` readable JSON. |
| `guardrail/guardrail.py:113`, `guardrail/walledai.py:203` | Output guardrails now also see a paused reply. **Desirable and left as-is** — a guardrail *should* see what is being asked of a human. Cannot break a resume: the resume state lives in the session, not the reply. |
| `chat_service.py:317`, `slack_chat.py:172`, `teams_chat.py:530` | The three stringify sites. Unchanged; a paused reply renders as its `__str__` JSON. |
| `runtime.py:241`, `:279`, `:291`, `:329` | The four `AgentReply` tuple `isinstance` sites. **Unchanged** — a subclass satisfies them. |
| `runtime.py:247` | The `AgentRequest` tuple gains `AgentResumeRequestAny`. The **one** site a union member costs. |
| `integration/thread/recorder.py` | **Unchanged** — see Non-goals. A resume-only request records an empty user turn because `pre_run` writes `req.prompt`; a paused reply is appended like any assistant message. |
| Queue pipeline (`pipeline/agent_runner.py`) | **Expected unchanged.** A paused reply travels as an ordinary output message and the runner already forwards whatever status `process_chat_request` returns as `ATTR_STATUS_CODE`. PR 2 **confirms by test** rather than assuming. |

### Config and model changes

**No new `AKConfig` fields, no new config block, no `enabled` flag.** Per the issue's Definition of
Done, HITL is active whenever a framework pauses. Checked against the existing models
(`grep "class _" core/config.py`): nothing to reuse and nothing to add — the capability has no
backend to select and no connection to describe. Expiry rides the session store's own TTL
(`session.redis.ttl`, default 604800, `config.py:27`); there is no separate pause TTL.

One **public model** change, in `core/model.py`:

| Field | Before | After | Reason |
|---|---|---|---|
| `BaseChatRequest.prompt` | `str` (required) | `Optional[str] = None` | a resume-only request carries no prompt; pydantic would reject it first |
| `BaseChatRequest.resume` | — | `Optional[ResumeSpec] = None` | the public resume block, mirroring `schedule` |

Existing YAML, `AK_*` env vars and request bodies are unaffected: widening a required field accepts
everything it accepted before. `_validate` keeps the "no prompt" `ValueError` for a request that
carries neither, so the *behaviour* a caller sees for a malformed request is unchanged.

### Behavioural changes

1. **A framework pause now reaches the caller** instead of being lost. Intentional — the change.
   Replaces four distinct silent losses (`design.md` Motivation).
2. **`202` now has two meanings on the chat API**: `status: "SCHEDULED"` and `status: "PAUSED"`.
   Intentional; the body key is the discriminator and is required.
3. **`BaseChatRequest.prompt` becomes optional.** Intentional and forced (§ *Blockers*). A request
   with neither prompt nor resume still 400s with the same message.
4. **Six existing sites that branch on `isinstance(..., AgentReplyAny)` now also receive pauses** —
   the two guardrail factories, `AgentService.run`, and the three stringify sites. Intentional and
   partly desirable; each is reviewed above and none is changed.
5. **ADK agents are wrapped in an `App` with `is_resumable=True` for every user**, changing
   sub-agent routing and growing ADK sessions. Intentional, forced by the no-flag requirement,
   documented in release notes.
6. **AK overwrites a user-supplied LangGraph checkpointer.** Pre-existing behaviour
   (`langgraph.py:368-370`) that this change makes load-bearing; now documented rather than new.
7. **A pre-hook halting on a resume logs at `WARNING`** where it logged at `DEBUG` (`runtime.py:280`)
   — that path already existed, only the level and message change.
8. **The `StreamEvent` invariant wording is relaxed** (`event.py:16-17`) and
   `test_stream_events.py` updated. The real rule — no framework-native objects — is unchanged.

**Non-changes**, stated so a reviewer can confirm them:

- the `AgentReply` union (`model.py:126`) and the `AgentReplyText`/`AgentReplyImage`/`AgentReplyAny`
  classes;
- every `Runner` signature except the two additions and the new property;
- `SessionStore`, its backends, and the session serialisation format — the record is an ordinary
  `nv_cache` entry;
- the queue transports, envelopes and `QueueMessage` attributes;
- `ThreadRecorder`, `ConversationThreadManager` and the thread models;
- `AGUIMapper.to_agui`'s existing cases;
- config: no field added, removed, renamed or re-defaulted.

**Data compatibility.** A session pickled before this change reads back identically: the new key is
simply absent, and `PausedRunState.list` returns `[]` for a missing key. A session pickled *after*
this change and read by an older AK carries one unknown `nv_cache` entry, which the older code
ignores.

---

## Error handling

### The four resume failure modes

Raised by `Runtime._validate_resume` **before** the branch, so none is swallowed by an adapter's
`except`. Each is a `ValueError` carrying an actionable message, surfacing as **400** through the
existing `ValueError` → 400 mapping in the presentation wrappers.

| # | Condition | Message names |
|---|---|---|
| 1 | no paused run matches — unknown `run_id`, decisions resolving to no record, a `run_id` disagreeing with its decisions' record, or decisions spanning **two** records | the session id and how many paused runs it holds |
| 2 | a `ResumeDecision.id` matching no `PausedInterruption.id` in the resolved record | the offending id and the ids the record holds |
| 3 | the opaque payload no longer deserialises — an SDK upgrade (OpenAI's `RunState` carries a `_schema_version`), or an agent whose framework changed while the pause was outstanding | the runner and the underlying error |
| 4 | agent mismatch — a `req.agent` conflicting with `record.agent` | both agent names |

`Runtime` resolves the agent **from the record**; a conflicting explicit `req.agent` is an error
rather than an override. Resuming the wrong agent would rebuild OpenAI's state with the wrong
`initial_agent`, and on ADK or Pydantic AI would resume another agent's conversation.

`supports_pause` is checked here too, so an unsupported runner names itself in the error rather than
reaching a `NotImplementedError` inside the adapter's `try`.

### Framework-specific rejections

Raised in the adapter, **above its `try`**, so they reach the caller:

| Adapter | Rejects | Because |
|---|---|---|
| OpenAI | a `ResumeDecision.payload` | `approve(item, always_approve=False)` takes no value |
| OpenAI | `prompt` alongside `resume` | `Runner.run`'s `input` is mutually exclusive |
| Pydantic AI | a partial resume | the framework requires all deferred calls resolved; AK keeps its clear message |
| ADK | `prompt` alongside `resume`, **if** the PR 4 test shows it unsupported | established by test, not assumed |

### Other failures

- **Not picklable**: `PausedRunState.add` raises `TypeError` naming the offending entry, reusing the
  #526 fail-fast rather than a second implementation. Raised inside the adapter's success path, so
  it surfaces as the adapter's error reply — acceptable, because it is a programming error in the
  adapter, caught by the PR 1/3/4 tests.
- **Duplicate interruption id across records**: `PausedRunState.add` raises `ValueError`.
- **Application cleared the cache**: `nv_cache` is documented application space (`base.py:35-38`)
  and `KeyValueCache.clear()` (`core/util/key_value_cache.py:68`) is reachable by any application
  holding the bucket, so clearing it **destroys pending decisions**, silently. Two mitigations, both
  required: the `ak.` key prefix marks it framework-owned, and the docs must state it (PR 5). This
  is the accepted cost of not taking a reserved `Session.Keys` entry.
- **Nothing detects an overtaken pause.** AK does not track it. Measured: Pydantic AI refuses a new
  question while a decision is outstanding, LangGraph's interrupt is sticky and re-pauses, **OpenAI
  allows it and reports nothing**, ADK has no validation
  ([`research/verification.md`](research/verification.md)). The residual risk is OpenAI, where a
  stale resume produces a confident answer computed as though the intervening turns never happened.
  Documented under the OpenAI adapter specifically (PR 5), not as a general caveat.

### Durability guardrails

- **Warn, do not fail, on a process-local session store.** `PausedRunState.add` emits a one-time
  `WARNING` naming `session.type` when a record is written while `session.type == "in_memory"`
  (`config.py:93-97`). Warn-once via a **class-level** flag, since `PausedRunState` is static
  methods only — follow `BookkeepingStoreFactory._fallback_warned`
  (`pipeline/transport/bookkeeping.py:128,151-152`), which is the class-level form; the instance
  form (`CrewAIRunner._context_warned`) does not apply.
- **Not an `AKConfigError`.** A single-process dev app pausing on the in-memory store is legitimate,
  and HITL has no enable flag, so there is no construction point at which a hard fail-fast could be
  scoped to apps that actually use it. Deliberately weaker than `ScheduleManager`'s hard
  `_validate_store_topology`, for that reason.
- Docs (PR 5) must state that a durable pause requires a shared session backend (`redis`, `valkey`,
  `dynamodb`, `cosmosdb`, `firestore`) on any multi-replica deployment, and that a pending decision
  should be answered before the conversation continues.

### Concurrency and cost

- **`PausedRunState` holds no state**, so it is thread-safe by construction; the list it reads lives
  on the `Session`, whose lock `Runtime.run` already holds (`async with session`). No new
  concurrency contract.
- **Per-operation cost on the hot path is one dict lookup.** `Runtime` reads `ak.paused_runs` only
  when a request carries an `AgentResumeRequestAny`; an ordinary turn touches it once, in the
  leftover-record check, which is itself scoped to resumed runs. Serialised size grows by the
  opaque payload — largest on OpenAI, where a `RunState` JSON was ~4.7 KB for a single gated call in
  the probe. That rides the existing session pickle and its TTL.

---

## Testing

Run with `cd ak-py && uv run pytest`. New files follow the `test_<module>.py` convention; doubles
follow `DummyRunner`/`DummyAgent` from `ak-dev-testing-conventions`, and a streaming double yields
`StreamEvent` members, never a bare `str`.

### New test files

| File | Asserts |
|---|---|
| `tests/test_paused_run_state.py` | PR 1. `add` assigns an id and returns the stored record; `list`/`get`/`clear` round-trip; `find_by_interruption` resolves one record and returns `None` when ids span two; a corrupted cache entry is dropped with a warning rather than raising; a non-picklable payload raises `TypeError` naming the entry; a duplicate interruption id raises `ValueError`; the record survives a real `SessionStore` round trip (not just an in-process set/get); **`get_non_volatile_cache().clear()` discards the pause** — a test of accepted behaviour, so it is known rather than discovered in production |
| `tests/test_hitl_models.py` | PR 1. The five types round-trip through pydantic; `AgentPausedReplyAny` satisfies `isinstance(x, AgentReplyAny)`; its `content` is derived and a caller-supplied one is overwritten; `str()` is readable JSON; `type` is `"paused"` while the body's status is `"PAUSED"`; `ResumeSpec` rejects an empty `decisions` list and duplicate ids; ids that merely fail to match a pending interruption are **not** rejected here (that is a `Runtime` check with a different error) |
| `tests/test_runtime_resume.py` | PR 2. Driven by a `DummyRunner` that pauses. Dispatch reaches `resume()` with the hook-processed list; the **four** failure modes each raise their own error; `supports_pause = False` names the runner; the agent is resolved from the record and a conflicting `req.agent` raises; a resume with no `run_id` resolves by interruption id, and decisions spanning two records are refused; a leftover record is cleared after a non-paused resume reply, and an **ordinary** turn with a pause pending leaves it alone |
| `tests/test_runtime_resume_warnings.py` | PR 2. All three warnings fire with the session and agent named: a pre-hook that drops the `AgentResumeRequestAny` (and the run proceeds as a new turn, record intact), a pre-hook that halts on a resume (record intact, answerable again), and a post-hook returning `None` for `RunPaused` (pause dropped, record intact, hook named). These are the only signal the behaviour is deliberately unconstrained. |
| `tests/test_hitl_stream.py` | PR 2. A paused stream emits `RunPaused` → the tracker's owed closing events → `StreamChunk(done=True)`; the pause never reaches `StreamChunk.error`; the session **is** stored (unlike the `StreamHalt` path); pausing with a `ToolCallStart` open yields `ToolCallEnd` before `done` |
| `tests/test_hitl_chat_service.py` | PR 2. A resume-only request (no prompt) is accepted; a request with neither raises the existing message; `schedule` + `resume` raises **from all four entry points**, asserted specifically because a guard in `_validate` runs after `_maybe_schedule` has already returned its 202; the response carries `202` with top-level `status: "PAUSED"`, `run_id` and `interruptions`, distinguishable from `202` + `"SCHEDULED"`; `resume` never reaches an agent as `AgentRequestAny` |
| `tests/test_hitl_guardrail.py` | PR 2. A `ResumeDecision.message` an input guardrail is configured to block **is** blocked; a string `payload` value is extracted; a non-string payload value is not. Without the `guardrail/` change this fails — which is the point of having it. |

### Changed test files

| File | Change |
|---|---|
| `tests/test_stream_events.py` | The invariant assertion is updated to the reworded rule (JSON primitives, no framework-native objects) and gains `RunPaused` to the round-trip matrix. Discriminator and unknown-`type` assertions unchanged. |
| `tests/test_chat_service_core.py` | Gains the optional-`prompt` case. Existing assertions on the "No prompt provided in the request" message are unchanged — the message is deliberately reused. |
| `tests/test_openai_runner.py`, `test_pydanticai_runner.py` | Gain the per-adapter matrix below. `test_langgraph_*` and the ADK runner gain new files if none covers the runner today. |

### Per-adapter matrix (PRs 3 and 4)

For each of OpenAI, LangGraph, Pydantic AI, ADK:

- pause detected and **not** swallowed, with detection ahead of text extraction;
- the record is written, picklable, and resumable after a **session-store round trip**;
- `resume()` returns a real reply and clears its own record;
- **multiple interruptions in one pause** resolve together — the list case, not the single-item one;
- **answering one interruption at a time**: the remainder returns as a second `AgentPausedReplyAny`
  with a fresh record, and answering that completes the run. On Pydantic AI, assert instead that AK
  refuses **before** the framework is called, naming the missing ids;
- **the three-way decision**: `denied` and `cancelled` are *distinguishable in what the model
  receives*. Asserting only that both refused would pass under a bool and prove nothing. On
  LangGraph, assert the status reaches the node intact;
- **the answer channel**: a structured `payload` reaches the framework natively on LangGraph and
  ADK and as a deferred tool's result on Pydantic AI — assert the value the human chose is what the
  model **receives**, not merely that the run completed — and is **rejected up front on OpenAI**;
- **`prompt` + `resume`**: carried on Pydantic AI and LangGraph (assert the prompt reaches the
  model), **established by test** on ADK, and raising from above the `try` on OpenAI so the error
  reaches the caller;
- **`ToolContext.requests` on a resume** holds the hook-processed list containing the
  `AgentResumeRequestAny` — assert a tool can read it, since nothing else proves the list was
  threaded through;
- `framework_context` survives a resume.

Plus, once: **more than one paused run in a session** — on OpenAI, pause twice, resume each by its
`run_id`, and assert both complete independently and each clears only its own record. On the
single-thread adapters, assert whatever append-or-replace behaviour the adapter settles on, since
that is what a user will hit.

**A stale resume on OpenAI is the one case AK does not catch.** Pin it as accepted behaviour: pause,
run an ordinary turn, resume the old snapshot, assert it returns an answer with **no error** — so
the gap is recorded in the suite rather than discovered in production.

### Negative and transport

- CrewAI and smolagents report `supports_pause = False` **without declaring it**, and raise on
  `resume`/`resume_stream` if called directly.
- **PR 2 confirms the queue pipeline needs no change**: a paused reply round-trips through
  `InMemoryTransport` with its `202` intact via `ATTR_STATUS_CODE`, asserted rather than assumed.

### Decided by test, not assumption

One item remains: **whether ADK streaming can pause and resume at `google-adk` 2.8.0** (PR 4). If it
fails, the streamed run yields a clear error and the limitation is documented as AK's own finding
with a repro.

### Example

At least one runnable example under `examples/` showing pause → decision → resume over REST (PR 5).
