# PR 2: the adapter changes, and why each one is different

A walkthrough of what changed in the four framework adapters for human-in-the-loop (#606), written
to be explained to someone else. [`../design.md`](../design.md) says *what* was decided and
[`../spec.md`](../spec.md) says *how*; this says **why the four look so different from each other**.

Short version: they differ because the frameworks disagree about **where a paused run lives**, and
everything else follows from that one fact.

---

## 1. The shape every adapter gained

All four got the same five things:

| | |
|---|---|
| `supports_pause` | `True`, replacing the base class's `False` |
| detection in `run()` | **before** the reply is read |
| detection in `stream()` | **after** the stream drains |
| `resume()` / `resume_stream()` | continue from the human's decisions |
| `_paused_reply()` | write the record, return `AgentPausedReplyAny` |

### The one rule that matters: detect before you read the answer

Every adapter already ended with "read the result and turn it into a reply". The pause check goes
**in front of that**, never as a fallback.

The reason is the same in all four: **a paused run still populates the answer field.** It holds
whatever the model said on its way to stopping.

> **Scenario.** A waiter takes your order, heads for the kitchen, then stops at the till to ask the
> manager whether your discount applies. If you only listen for "here's your food", what you
> actually hear is *"Right, let me sort that discount…"* — and you write that down as the meal.

That is literally what the old code did. On Pydantic AI it was worse than a half-sentence: the user
received a **Python dataclass repr** as the agent's answer.

### One turn, end to end

```
client ──prompt──► ChatService ──► Runtime ──► Adapter ──► framework
                                                  │
                                    framework stops for a human
                                                  │
                                    adapter writes a PausedRun record
                                                  ▼
client ◄──202 PAUSED, run_id, interruptions───────┘

        ... an hour later, possibly on another replica ...

client ──decisions──► ChatService ──► Runtime ──validates──► Adapter.resume() ──► framework
```

`Runtime` does the framework-agnostic validation (does this run exist, are these ids real, is the
agent right). The adapter does the part that needs framework knowledge, and **rejects what its
framework cannot express before its own `try` opens** — otherwise the adapter's blanket
`except Exception` turns a precise message into *"Sorry, something went wrong"*.

---

## 2. Where things live: the session

This is the part worth drawing on a whiteboard.

```
Session
├── volatile cache            cleared after every run
├── non-volatile cache        persisted
│   └── "ak.paused_runs" ──► [PausedRun, PausedRun, ...]        ← NEW in PR 1
└── framework key             "openai" | "langgraph" | "pydanticai" | "adk"
    └── the framework's own session object                       ← already existed
```

Two homes, and the difference between them is the whole story:

- **`ak.paused_runs`** — Agent Kernel's own record. Who paused, what the human is being asked, and
  an opaque `payload` the adapter chooses.
- **the framework key** — the conversation itself, in whatever shape the framework likes.

And the constraint that ties them together:

> **`SessionStore.store()` pickles the entire `Session`.**
> In-memory keeps the object as-is. Redis, Valkey, DynamoDB and the rest turn it into bytes.

So *anything* hanging off a session has to pickle. On a single process this never gets exercised.
HITL is the first feature that **requires** it, because its whole promise is "answer an hour later,
maybe on another replica".

### What each framework keeps on the session

| Adapter | framework object | holds |
|---|---|---|
| OpenAI | `OpenAISession` | `_items` — a list of message dicts |
| LangGraph | `LangGraphSession` | `_checkpointer` — **a live framework object** |
| Pydantic AI | `PydanticAISession` | `_messages` — plain JSON-able data |
| ADK | `GoogleADKSession` | `_session_service`, `_session` — ADK objects |

Three of the four hold **data they assembled themselves**. LangGraph holds **a class AK wrote by
subclassing a LangGraph base class** — and that is the only place AK could inherit an attribute
nobody put there deliberately. Hold that thought for §4.

---

## 3. The question that predicts every difference

> **When a framework pauses, does it hand you the pause, or keep it?**

```
OpenAI          "here, take a photo of where we got to"   → a plain dict
LangGraph       "I've left a bookmark in my book"          → stays in the checkpointer
Pydantic AI     "the transcript is the state"              → a message history
ADK             "I'll remember; quote this ticket number"  → an invocation id
```

Everything else follows:

| | OpenAI | LangGraph | Pydantic AI | ADK |
|---|---|---|---|---|
| What the record's `payload` holds | the whole snapshot | `{"thread_id"}` | the message history | `{"invocation_id"}` |
| Payload size | largest (~4.7 KB for one gated call, measured) | tiny | medium | tiny |
| Second pause in one session | **appends** | replaces | replaces | replaces |
| Prompt beside a decision | rejected | AK's encoding | native | rejected |
| Structured answer (`payload`) | rejected | native | native | native |
| Interruption `kind` | `tool_call` | `input_required` | both | `tool_call` + `confirmation` |

### The `kind` vocabulary, and where it is spelled in full

All three kinds — `tool_call`, `input_required`, `confirmation` — are declared once, on
`PausedInterruption.kind` in `core/event.py`. That union is the vocabulary **across** adapters; no
single adapter produces all of it, as the row above shows.

Each adapter's own types were narrowed to what it can actually emit, so the type checker rejects a
kind the adapter has no producer for:

- **ADK** — `PauseKind` is `Literal["tool_call", "confirmation"]` (`adk.py:119`). It had carried the
  full three-value union under a docstring reading *"ADK has no `input_required`"* — a comment
  apologising for the line above it. ADK never asks for a value on its own: a
  `LongRunningFunctionTool` is answered with the tool's result, `adk_request_confirmation` with a
  verdict.
- **Pydantic AI** — `_interruption`'s `kind` parameter is `Literal["tool_call", "input_required"]`
  (`pydanticai.py:265`), matching its two channels. `confirmation` was reachable in the signature and
  produced by nothing.
- **OpenAI and LangGraph** — nothing to narrow. Each produces exactly one kind and writes the literal
  straight into `PausedInterruption(...)` (`openai.py:268`, `langgraph.py:621`), with no helper or
  alias in between to widen.

### Why only OpenAI appends

A `RunState` is a **self-contained photograph**. Two photographs are two independent pauses — and
that was verified by running it, not assumed: two paused OpenAI runs resumed independently in the
same session.

The other three keep **one bookmark in one book**. A second pause is the same conversation stopping
again, and the earlier bookmark is gone. Appending there would leave a record nobody can ever
answer, and AK would not detect it.

> **Scenario.** Two support requests in one chat: *"refund my order"* and *"and cancel my
> subscription"*. On OpenAI, both can sit waiting for a manager and be approved in either order. On
> the other three, the second question replaces the first — so the UI must not offer two pending
> approvals.

---

## 4. OpenAI — the photograph

**Scenario.** A `refund` tool is declared `needs_approval=True`. The model decides to call it. The
SDK stops and puts the call in `result.interruptions`.

### What changed

```python
result = await Runner.run(agent.agent, input_data, **kwargs)
self._store_framework_context(session, incoming, produced)

if result.interruptions:                       # ← before .final_output
    return self._paused_reply(agent, session, result)

reply = result.final_output
```

The record stores `result.to_state().to_json()` — a **plain dict**, already picklable, nothing to
convert. Resuming is `RunState.from_json(...)`, apply `approve`/`reject`, run again with the state
as the input.

### Two things rejected above the `try`

- **a structured `payload`** — `state.approve(item)` takes no value. There is nowhere to put "the
  human chose Large". Refused rather than silently dropped.
- **a prompt beside the decision** — `Runner.run`'s `input` is *either* a `RunState` *or* new input,
  never both.

### The bug worth telling the team about

`RunState.from_json` is **`async`**, and the first version didn't `await` it. The tests passed,
because the mock returned a plain value and the un-awaited coroutine was never inspected.

**`mypy` caught it**, not the test suite:

```
Incompatible return value type (got "Coroutine[...RunState]", expected "RunState")
```

Converting the 13 mocks to `AsyncMock` made 14 tests fail immediately — which is what they should
have been doing all along. Of the SDK's state API, `from_json` is the *only* async member;
`to_json`, `approve`, `reject` and `get_interruptions` are all sync, which is exactly why it was
easy to miss.

---

## 5. LangGraph — the bookmark, and the two bugs under it

**Scenario.** A graph node calls `interrupt({"question": "approve?"})`. The graph freezes mid-node.
Whatever you pass on resume *becomes the return value of that `interrupt()` call*.

### The contract decision

```python
choice = interrupt("what size?")     # a node author writes this
```

A human's answer reaches AK as three fields (`status`, `message`, `payload`) but `interrupt()` hands
back exactly **one** value. We chose to send **the answer itself** — `payload`, else `message`, else
the bare status verb — so ordinary LangGraph code works unchanged and `choice` is just the choice.

The accepted cost: a `denied` sent *with* a reason arrives as the reason text, so the word "denied"
isn't separately visible inside that node. It is still on the record and on the reply.

### Why `__getstate__` and `__setstate__` appeared here and nowhere else

This is the deviation worth explaining carefully, because it looks arbitrary until you see it.

**Step 1 — LangGraph is the only adapter where AK subclasses a framework class.**

```python
class CheckPointer(BaseCheckpointSaver):     # AK's own, subclassing LangGraph's
    def __init__(self):
        super().__init__()                    # ← this line attaches self.serde
```

The other three assemble plain data (`_items`, `_messages`). This one inherits whatever the parent
puts on it — and the parent attaches a **serializer**.

**Step 2 — that serializer cannot be pickled.** Three attributes; only one fails:

```
serde      -> FAILS   (JsonPlusSerializer)
_storage   -> fine    (dict)
_writes    -> fine    (dict)
```

Inside it is a function whose full name is `_create_msgpack_ext_hook.<locals>.ext_hook`. The
`<locals>` means *defined inside another function*. Pickle never stores a function's code — it
stores its **address** ("the thing called `X` in module `Y`") and looks it up on load. A nested
function has no address; it only exists while the outer call is running.

And pickle's default is all-or-nothing: it saves the whole attribute dictionary, so one bad entry
sinks the object.

**Step 3 — the fix.**

```python
def __getstate__(self) -> dict:               # "when saving me, here is what to save"
    state = self.__dict__.copy()
    state.pop("serde", None)                  # the one thing that cannot be pickled
    return state

def __setstate__(self, state: dict) -> None:  # "when loading me, do this"
    BaseCheckpointSaver.__init__(self)        # reattaches serde
    self.__dict__.update(state)
```

`serde` is never handed to pickle, so pickle never trips on it. On load the parent's `__init__`
reattaches it — and it isn't even rebuilt: the parent does `self.serde = serde or self.serde`, where
that second one is a **class attribute**, so every checkpointer shares one instance.

Note it **excludes one name** rather than listing what to keep. Listing would mean an attribute
added to this class next year is silently dropped on every Redis round trip — no error, it just
comes back missing. Two tests pin that.

### How pickle actually uses them

This is the part people get stuck on: **nothing in Agent Kernel calls these methods.** Search the
codebase and you will find no caller. They are hooks *pickle* looks for.

If you write frontend, you already know the pattern:

```js
JSON.stringify(obj)     // checks: does obj have a toJSON()? if so, use it
```

You never call `toJSON()` yourself. `__getstate__` is that, for pickle — and `__setstate__` is the
reviver half that JavaScript has no equivalent for.

**Watch it happen.** A throwaway class with print statements:

```python
class Demo:
    def __init__(self):
        self.data = "keep me"
        self.tool = "drop me"

    def __getstate__(self):
        print("   [pickle called __getstate__ — asking me what to save]")
        return {"data": self.data}

    def __setstate__(self, state):
        print("   [pickle called __setstate__ — handing back what was saved]")
        self.data = state["data"]
        self.tool = "rebuilt"

raw  = pickle.dumps(Demo())      # I never call __getstate__ myself
back = pickle.loads(raw)         # I never call __setstate__ myself
```

```
calling pickle.dumps(obj)
   [pickle called __getstate__ — asking me what to save]

calling pickle.loads(raw)
   [pickle called __setstate__ — handing back what was saved]

result -> keep me | rebuilt
```

Two calls in, two hooks fired. The rule is the naming: **double underscores on both sides** means
Python or a library calls it for you — the same as `__init__` when you write `Session("s")`, or
`__len__` when you write `len(x)`.

What pickle does internally:

```
pickle.dumps(obj):
    does obj define __getstate__?
        yes -> save whatever it returns
        no  -> save obj.__dict__            ← the old behaviour, which broke

pickle.loads(raw):
    make a blank object (no __init__ runs)
    does it define __setstate__?
        yes -> call it with the saved state
        no  -> shove the saved dict straight into __dict__
```

Before the fix, `CheckPointer` defined neither, so pickle took the `no` branch both times — saving
*everything*, `serde` included.

**So the real call chain is three layers down**, which is why the bug was so quiet — you cannot grep
for a call that does not exist:

```
RedisSessionStore.store(session)
  └─ BinarySerde.dumps(value)               ← Agent Kernel's own serialiser
       └─ pickle.dumps(...)
            └─ CheckPointer.__getstate__()  ← here
```

> **Two different things both called "serde".** `BinarySerde` (`core/session/serde.py`) is ours —
> a thin pickle wrapper the session stores call. LangGraph's `serde` is a `JsonPlusSerializer`
> attached by its base class, which Agent Kernel never calls. Ours is the caller that was failing;
> theirs was the cargo that would not fit.

> **Packing a suitcase.** You pack your clothes. You don't pack the hotel's hairdryer — there's an
> identical one at the other end. `_storage` and `_writes` are clothes. `serde` is the hairdryer.

**And AK never even calls it.** `serde` is referenced nowhere in the class. Its job is turning graph
state into bytes for a database column, which real LangGraph checkpointers (Postgres, Redis) need.
AK's keeps live Python objects in a dict and lets the session pickle handle persistence. So dropping
it loses nothing — it was inherited machinery for a job this subclass doesn't do.

**Why HITL forced it.** Keeping the object in an in-memory dict needs no conversion, so this never
failed on one process. HITL's definition *is* "an hour later, maybe another replica", which means
Redis, which means bytes. The broken step went from optional to mandatory.

### The second bug: `interrupt()` had never been resumable

`put_writes` stored writes; `get_tuple` never handed them back. LangGraph records both the pause
*and* the resume answer as pending writes, so with `get_tuple` silent:

- `aget_state(...).interrupts` was always empty, and
- a resume silently **re-ran the node from the top** and asked the same question again.

That's what the first failing test actually showed. Fixed by returning them, keyed by
`(thread_id, checkpoint_ns, checkpoint_id)` and `(task_id, index)` exactly as LangGraph's own
`InMemorySaver` does — so one turn's interrupt can't leak into the next, and a replayed task
replaces its entry rather than stacking a second one.

**Both bugs predate this branch and affect every LangGraph user.** They deserve their own issue and
a release-note line. They're fixed here because the feature is impossible without them.

**Caveat for the docs:** the interrupting node **re-runs from the top** on resume. Side effects
before `interrupt()` happen twice. That is LangGraph's behaviour, not AK's.

---

## 6. Pydantic AI — two channels, two questions

**Scenario A.** A tool raises `CallDeferred`. The model is waiting for somebody to supply **the
tool's return value**.
**Scenario B.** A tool is declared `requires_approval`. The model is waiting for **a yes or no**.

These are different questions, so they map to different kinds:

| channel | the model is waiting for | `kind` |
|---|---|---|
| `calls` | a **value** | `input_required` |
| `approvals` | a **verdict** | `tool_call` |

Collapsing them would lose the difference between *"what is it?"* and *"may I?"*.

### Measured, not assumed

Driving a real agent:

```
model received : [('ask_size', 'L'), ('ask_colour', ['red', 'blue'])]
```

**A list arrives as a list.** That is the measurement that justified widening `ResumeDecision.payload`
past `dict` back in PR 1 — the value is passed through untouched, not wrapped.

### What the user used to get

`DeferredToolRequests` is a **dataclass, not a `BaseModel`**, so `AgentReplyAny.from_output`
returned `None` and the adapter fell through to `str(result.output)` — handing the user a dataclass
repr as the agent's answer. Detecting before that call is the fix.

### Partial resume, rejected above the `try`

Two deferred calls, one answered:

```
UserError - Tool call results need to be provided for all deferred tool calls.
            Expected: {'c1', 'c2'}, got: {'c1'}
```

That message is *good* — which is exactly why AK pre-empts it. Left inside the `try`, the adapter's
`except Exception` would replace it with "Sorry, something went wrong".

**A prompt beside a decision is native here.** Supplying the deferred results is precisely what lifts
the framework's own guard against a new prompt while tool calls are outstanding.

---

## 7. Google ADK — the ticket number, and two questions answered by test

**Scenario.** A `LongRunningFunctionTool` is called. ADK ends the turn with the call still
outstanding and hands back an `invocation_id` — a ticket number to quote when you come back.

### Three changes

**1. The agent is now wrapped in an `App`.** `ResumabilityConfig(is_resumable=True)` lives on an
`App`, and the adapter was building a bare `Runner`. Enabled unconditionally, because a per-agent
gate would reintroduce the enable flag the issue forbids.

Two real costs, documented rather than hidden: **sub-agent routing changes** (a turn following a
function response is routed back to the agent that made the call), and **ADK sessions grow**, since
`is_resumable` also gates agent-state event emission.

`ResumabilityConfig` is also flagged **experimental** by ADK and warns on construction. It's the only
way to enable resumability, so there's no alternative — but the docs must say ADK may change it.

**2. `get_response` now returns a turn, not a string.** This was forced: a run that stops for a human
produces **no final response**, so reading the text alone made a pause look like an empty answer.

**3. Two kinds**, because ADK asks two different things — a long-running tool waiting for a
**result** (`tool_call`), and `adk_request_confirmation` waiting for a **verdict** (`confirmation`),
which takes ADK's own `{"confirmed": ...}` shape.

### The two open questions, settled by running it

The spec refused to guess on either. Both were answered by driving a real ADK app with a stand-in
model.

**Can streaming pause and resume at 2.8.0? — Yes.**

```
STREAMED pause events: [({'call-1'}, [('call-1', 'ask_size')], partial=None)]
STREAMED resume -> ["model saw: [{'result': 'large'}]"]
```

Neither feared risk bites: the event carrying the pending call is **non-partial**, so the id a client
reads off the stream is one ADK actually persisted.

**Can a prompt ride beside a decision? — No, and ADK says so itself:**

> `Message cannot contain both function responses and text. Function responses resume an existing
> invocation while text starts a new one.`

So the adapter rejects it above the `try`, like OpenAI.

---

## 8. Cheat sheet

| Question | Answer |
|---|---|
| Why detect before reading the reply? | A paused run still fills the answer field, with the text produced on the way to stopping |
| Why does only OpenAI append? | Its `RunState` is a self-contained snapshot; the others keep one conversation per session |
| Why did LangGraph need `__getstate__`? | It's the only adapter subclassing a framework class, so it inherited an unpicklable serializer |
| Why did that matter now? | HITL means Redis, Redis means pickling, and that step had never run on one process |
| Why does Pydantic AI have two kinds? | Its two channels ask different questions: a value vs. a verdict |
| Why do the adapters' `kind` types differ from core's? | The three-value union is the vocabulary across adapters; each adapter's type states only what it produces |
| Why does ADK wrap the agent in an `App`? | `ResumabilityConfig` lives on an `App`, not on a `Runner` |
| Why reject things above the `try`? | Every adapter's `except Exception` would flatten a precise message into "Sorry, something went wrong" |
| Why use real frameworks in tests? | Mocks hid an un-awaited coroutine on OpenAI and would have hidden both LangGraph bugs entirely |

## 9. The two pre-existing bugs, for the record

Both in LangGraph's `CheckPointer`, both predating this work, both affecting every LangGraph user:

1. **`get_tuple` dropped pending writes** — so `interrupt()` was never resumable.
2. **The checkpointer could not be pickled** — so a LangGraph session never reached a shared backend,
   despite the class docstring claiming "pickle-serializable" since the day it was written.

Neither was covered by a test. They surfaced only because iteration 6 drove a real graph instead of
a mock.
