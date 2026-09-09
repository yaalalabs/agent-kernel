# #670: Streaming post-hooks never see tool-call events — Implementation Spec

`Runtime.stream` currently offers only `TextDelta` and `ReasoningDelta` content to the post-hook chain,
so the other ten `StreamEvent` types — every tool call, every message boundary — reach clients
uninspected. This spec details the change `design.md` requires: `PostHook.on_stream_chunk` is replaced
by `PostHook.on_stream_event`, which every event passes through and which may return zero, one, or
several events; a new `StreamHalt` exception ends a run; and a new `StreamBoundaryTracker` in
`StreamBoundaryTracker` in `core/runtime.py` lets the halt path close whatever the stream left
open. `design.md` is the
requirements source — every requirement there is traced to a section here.

## Design

### Conventions

- **Class-based throughout. No module-level functions, and no module-level mutable or configuration
  constants.** Behaviour lives on a class; where an existing class is the right owner, extend it rather
  than adding a new one.
  - This matches the package as it stands, not a new preference: `ak-py/src/agentkernel/core/*.py`
    contains exactly one module-level function across the whole package (`core/config.py:11`,
    `_get_ak_version`), and `examples/api/hooks/hooks.py` is three `PreHook`/`PostHook` classes with no
    free functions or module constants.
  - Applies to every file this change touches, the four `hooks.md` examples, and PR 2's runnable
    example. A regex set plus the operations over it is a class (e.g. a `Redactor` holding its patterns
    as class attributes and exposing `scrub` / `split`), not a module of functions and constants.
  - Two exceptions, both pre-existing conventions rather than judgement calls: a module-level
    constant that is part of a public contract (`ACTING_USER_CACHE_KEY`, `core/runtime.py:35`) and a
    `type` alias (`StreamEvent`, `core/event.py:131`).
- **Compliance of the components below**, so a reviewer can check rather than infer: `StreamHalt` is a
  class; `on_stream_event` is a method on the existing `PostHook`; `StreamBoundaryTracker` is a class;
  the dispatch loop is inline in `Runtime.stream`, a method on `Runtime`. No new free function is
  introduced.

### `core/hooks.py` — the hook contract

Two additions and one deletion. The module currently holds `PreHook` and `PostHook` only.

```python
class StreamHalt(Exception):
    """Raised by a post-hook to end a stream early.

    `Runtime.stream` catches it, closes any boundary the stream left open, and yields one terminal
    error chunk carrying `reason`. The partial response is invalid: clients must discard what they
    have rather than render it as a truncated answer.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class PostHook(ABC):

    @abstractmethod
    async def on_run(self, session, requests, agent, agent_reply) -> AgentReply: ...   # unchanged

    async def on_stream_event(
        self,
        session: "Session",
        requests: list[AgentRequest],
        agent: "Agent",
        event: StreamEvent,
    ) -> StreamEvent | list[StreamEvent] | None:
        """Called for every event a streamed run produces, boundaries included.

        Return the event to pass it on, a modified event of the **same** `type` to rewrite it in
        place, `None` to drop it, or a list to emit several events in its place. A returned list is
        emitted as-is and **ends the chain for that event**, so `return event` and `return [event]`
        are not equivalent. Raise `StreamHalt` to end the run.
        """
        return event

    @abstractmethod
    def name(self) -> str: ...                                                        # unchanged
```

Rules this encodes:

1. **The default is a pass-through**, so a hook that only implements `on_run` is unaffected by the
   whole change.
2. **`on_stream_chunk` (`core/hooks.py:73-85`) is deleted outright**, not deprecated. There is one
   streaming callback. A downstream override becomes an uncalled method — see Behavioural changes #1.
3. **The docstring carries the list-ends-the-chain rule**, because it is the one non-obvious part of
   the contract and the place a hook author will look.
4. `StreamHalt` subclasses `Exception`, not a new AK error base: `core/` has no error hierarchy
   (`core/util/factory.py:18`'s `AKConfigError` is the only exception class under `core/`, and it is
   config-specific).

### `core/runtime.py` — `StreamBoundaryTracker`

One class, declared above `Runtime` in the module that is its only consumer, and not exported from
`core/__init__.py`. No new module: `core/chat_service.py` already groups four collaborating classes
this way.

```python
class StreamBoundaryTracker:
    """Remembers which paired events are still open, and how to close them."""

    def __init__(self) -> None:
        self._open: dict[tuple[str, str], StreamEvent] = {}

    def observe(self, event: StreamEvent) -> None:
        """Record an emitted event, opening or closing the boundary it represents."""

    def drain(self) -> list[StreamEvent]:
        """Return the closes for everything still open, innermost first, and forget them."""
```

Rules:

1. **`observe` takes the events actually emitted**, never what the runner yielded, so a hook that
   holds, drops or injects a boundary cannot desynchronise it.
2. **Keyed `(kind, id)`** where `kind` is one of `message`/`reasoning`/`tool`/`step` and `id` is
   `message_id`, `tool_call_id`, or a step's `name`. A single run can open several message ids —
   `framework/adk/adk.py:325-336` streams one partial message and can also emit one-shot
   start/delta/end triples.
3. **The value stored is the closing event itself**, built at open time. `drain` then needs no
   kind-to-constructor mapping.
4. **`drain` returns `reversed(self._open.values())`** — dicts preserve insertion order, so reversal
   gives innermost-first — then clears. It mutates, which is why it is not named `pending_closes`.
5. **Ids only, never payload**, so the tracker needs no size bound.
6. **Branching is `match event.type`**, matching `AGUIMapper.to_agui` (`integration/agui/mapping.py:39`),
   the established way this repo branches on an event's discriminator.
7. **Steps are tracked** although no shipped adapter emits them (in `ak-py/src` there are zero
   `StepStart(`/`StepEnd(` construction sites outside `core/event.py`; tests construct both). An
   unclosed step renders as work in progress in an AG-UI client
   (`integration/agui/mapping.py:54-57`), and a bring-your-own `Runner` may emit them.

### `core/runtime.py` — the streaming loop

**Imports.** `core/runtime.py:16` currently reads `from .event import ReasoningDelta, TextDelta`.
It becomes:

```python
from .event import StreamEvent, TextDelta
from .hooks import StreamHalt
from .stream import StreamBoundaryTracker
```

`ReasoningDelta` drops out with the deleted text gate. `StreamEvent` is used in annotations only, and
`from __future__ import annotations` is already in force (`core/runtime.py:1`). Neither new import is
a cycle: `core/hooks.py` imports `.model` at runtime and `.base` only under `TYPE_CHECKING`, and
`StreamBoundaryTracker` adds only `event.py` names to a module that already imports from it.

**Body.** `core/runtime.py:268-286` is replaced. Everything outside — `async with session`, the
acting-user publish, `agent._activate()`, the pre-hook halt at `:259-264`, and the `finally` at
`:287-288` — is untouched.

```python
                    post_hooks = self._get_system_post_hooks() + agent.post_hooks
                    boundaries = StreamBoundaryTracker()

                    try:
                        async for ev in agent.runner.stream(agent, session, requests):
                            for hook in post_hooks:
                                result = await hook.on_stream_event(session, requests, agent, ev)
                                if result is None:
                                    emitted = []
                                    break
                                if isinstance(result, list):
                                    emitted = result
                                    break
                                if result.type != ev.type:
                                    raise TypeError(
                                        f"PostHook '{hook.name()}' returned event type '{result.type}' for a '{ev.type}'. "
                                        "Return a list to emit a different type"
                                    )
                                ev = result
                            else:
                                emitted = [ev]

                            for event in emitted:
                                boundaries.observe(event)
                                yield StreamChunk(delta=event.content if isinstance(event, TextDelta) else None, event=event)

                        self.sessions().store(session)
                        yield StreamChunk(done=True)
                    except StreamHalt as halt:
                        self._log.warning(f"Stream halted for agent '{agent.name}': {halt.reason}")
                        for closing in boundaries.drain():
                            yield StreamChunk(event=closing)
                        yield StreamChunk(error=halt.reason, done=True)
```

Rules this encodes:

1. **Single pass over the chain.** `for ... else` sets `emitted` exactly once when no hook broke out,
   so the pass-through case needs no sentinel.
2. **`ev` is reassigned on a single-event return**, so a chain of rewriting hooks composes and the
   next hook sees the previous hook's output.
3. **A list breaks the loop**, which is the list-ends-the-chain rule. A hook re-emitting the event it
   was handed therefore terminates.
4. **`delta` is derived from the emitted event**, not from any separate text value. This is what makes
   the "`delta` and `event` never disagree" rule of `docs/specs/523-ag-ui-support/spec.md:211` hold by
   construction: after this change there is no second copy of the text to drift.
5. **`observe` is called at the one emission site**, immediately before the yield.
6. **The `except` wraps the `async for` only.** `self.sessions().store(session)` sits inside the
   `try` and before the `except`, so a halt cannot reach the store — matching the pre-hook halt, which
   returns at `:262-263` before the store at `:285`.
7. **Only the same-type rule is checked.** A return that is not a `StreamEvent` at all fails at
   `StreamChunk(event=...)` with a pydantic `ValidationError`, because `StreamChunk.event`
   (`core/model.py:187`) is the discriminated union. This is the established mechanism —
   `docs/specs/523-ag-ui-support/spec.md:244-248` relies on it and
   `tests/test_runtime_stream_events.py:176-187` is its test — so a hand-rolled membership check would
   only relabel the error. The same-type rule exists because pydantic *cannot* catch it: a
   `MessageEnd` returned for a `TextDelta` is a valid `StreamEvent` and round-trips faithfully as a
   `MessageEnd`. It is accident detection on the rewrite path, not transport safety.
8. **`StreamHalt` is the only exception caught** — see Error handling.

**Docstring.** The second paragraph of `stream()`'s docstring (`core/runtime.py:239-245`) is replaced:

```
        Pre-hooks run first; if halted, yields a StreamChunk with error and done=True. Every event the
        runner yields passes through PostHook.on_stream_event, which may pass it, rewrite it, drop it by
        returning None, or return a list to emit several events in its place. A returned list ends the
        chain for that event. A hook raising StreamHalt ends the run: the closing events for any still
        open boundary are emitted, then a single error chunk, and the session is not stored. The
        volatile cache is cleared on exit.
```

### `core/__init__.py` — export

`core/__init__.py:47` becomes `from .hooks import PreHook, PostHook, StreamHalt`. The top-level
package does `from .core import *` (`agentkernel/__init__.py:21`) and neither module declares
`__all__`, so `from agentkernel import StreamHalt` resolves without further change.
`StreamBoundaryTracker` is deliberately **not** exported: it is internal to `Runtime.stream`.

### Consumer changes

Every consumer of `Runtime.stream` was checked. None requires a code change.

| Consumer | Verified behaviour |
|---|---|
| `integration/agui/handler.py` | `:264-265` sets `error` from `chunk.error` and `continue`s; `:277-279` emits `RunErrorEvent(message=error)` after the loop. A halt's terminal chunk therefore already ends an AG-UI run correctly, and the synthesised closes pass through `AGUIMapper` as ordinary events before it. **No change.** |
| `integration/agui/mapping.py` | `:39-66` is a stateless one-to-one `match` on `event.type`. A rewritten event of the same type maps identically; a list member maps like any other event. **No change.** |
| `integration/thread/thread_chat.py` | `:160-172` accumulates `chunk.delta`, sets `error_seen` on an error chunk, and records only `if not error_seen and deltas`. A halted run therefore records no assistant message, and a released rewritten `TextDelta` is recorded in its redacted form because `delta` is derived from it. **No change.** |
| `pipeline/agent_runner.py` | `StreamAgentRunner.process` (`:153-167`) fans out one output message per chunk with a `{receive_count}-{chunk_count}` dedup suffix. A list return produces more chunks; the counter stays monotonic. **No change.** |
| `framework/*/`, all six adapters | `Runner.stream` is unchanged; `Runtime.stream` at `core/runtime.py:270` is its only production caller. **No change.** |
| `guardrail/` | No provider implements `on_stream_chunk` (verified: zero matches under `ak-py/src/agentkernel/guardrail/`), so no provider is broken by its deletion, and none gains `on_stream_event` in this change. |

### Config changes

**None.** No new `AKConfig` field, no new block, no new env var. The capability is always available;
whether a hook uses it is a property of the hook. Existing `config.yaml` files and `AK_*` variables
are unaffected.

### Behavioural changes

1. **`PostHook.on_stream_chunk` is removed.** *Intentional, breaking.* A downstream subclass that
   overrides it still imports and constructs; its method is simply never called, so its filtering
   silently stops. No `__init_subclass__` guard or `DeprecationWarning` is added — an explicit
   decision recorded in `design.md`. Migration: rename to `on_stream_event`, take a `StreamEvent`
   instead of a `str`, return an event instead of a `str`. Announced in the release notes.
2. **Ten event types now reach the post-hook chain.** *Intentional; the point of the issue.*
3. **The Runtime-side write-back is gone.** `core/runtime.py:280-281`'s
   `ev.model_copy(update={"content": text})` is deleted; a hook that rewrites text returns the
   rewritten event.
4. **A streamed run can end without `MessageEnd` or `done=True`** when a hook raises `StreamHalt`. It
   ends with the synthesised closes plus one `StreamChunk(error=..., done=True)`. Clients must treat
   the partial response as invalid.
5. **A halted run stores no session.** Consistent with the pre-hook halt.
6. **The hook chain now runs on every event, not only text events.** See Per-operation cost below.

**Non-changes**, stated so a reviewer can check them:

- `StreamChunk`'s fields and serialised form (`core/model.py:186-189`) — unchanged, so the SSE wire
  format, the queue message body, and every client that reads `delta` are unaffected.
- The `StreamEvent` union and every member (`core/event.py`) — unchanged.
- `PreHook`, `Runtime.run`, `Runtime._prepare_requests`, and every framework adapter — unchanged.
- `PostHook.on_run` is still **not** called on a streamed run. That is a separate issue.

## Error handling

| Failure | Behaviour |
|---|---|
| Hook raises `StreamHalt` | Caught. `WARNING` logged with the agent name and reason; `boundaries.drain()` emitted as plain `StreamChunk(event=...)` frames that **bypass the hook chain**; then one `StreamChunk(error=reason, done=True)`. Session not stored; volatile cache cleared by the existing `finally`. The reason reaches the client verbatim — AK substitutes no wording of its own. |
| Hook returns a single event of a different `type` | `TypeError` naming the hook, the incoming type and the returned type. **Not** caught by `Runtime.stream`. |
| Hook returns something that is not an event | Uncaught `AttributeError` on `result.type`, or a pydantic `ValidationError` at `StreamChunk(event=...)`. Not specially handled: the annotation forbids it and both failures are immediate and loud. |
| Hook raises anything else | **Propagates unchanged.** No boundary drain, no terminal chunk from `Runtime`; the `finally` still clears the volatile cache and the session is not stored. Each surface then handles it as it does today: `integration/agui/handler.py:272-275` catches `Exception` and emits `RunErrorEvent`, `integration/thread/thread_chat.py:170-172` emits an SSE error frame, and queue mode retries to `max_receive_count` before its permanent-failure path. The asymmetry with `StreamHalt` is deliberate: a halt is an orderly teardown a hook asked for, an unexpected exception is a defect, and dressing it up as a clean end-of-stream would hide it. |
| Runner raises mid-stream | Unchanged from today. The `async for` propagates it; boundaries are not drained. |

**No sequence validation.** `Runtime.stream` does not check that a runner's or a hook's events form
a well-formed sequence — not the one-`ToolCallResult`-per-`tool_call_id` assumption a hook may rely on,
and not the pairing of a hook's list return. Enforcing that is a broader contract question than #670,
and rejecting a runner's events mid-stream would turn a third-party adapter bug into a failed run.
`StreamBoundaryTracker` tolerates the malformed cases silently: a close for an id it never opened is a
no-op `dict.pop(..., None)`, and a second open for the same id overwrites the first.

**Exception scope.** The `except` clause names `StreamHalt` exactly — never `Exception`. Nothing
between a hook and that clause may catch broadly, or a halt never becomes a terminal chunk.

**Concurrency contract.** `StreamBoundaryTracker` is constructed as a local inside `stream()`, so it
is per-run by construction and is never shared between concurrent requests. Hook *instances* are
shared: `Runtime._system_post_hooks` is a class-level cache built once per process
(`core/runtime.py:48`, `:59-64`), and agent hooks live on the `Agent`. A hook that needs per-run state
must use `session.get_volatile_cache()`, which is per session and cleared by the existing `finally` —
never `self`. This must be stated in the docs examples.

**Per-operation cost.** Today the hook loop is skipped entirely for ten of the twelve event types
(`core/runtime.py:273`); after this change every event traverses the chain. For a stream of N events
and H hooks that is N×H awaits instead of N_text×H. The added calls land on the boundary and tool
events, which are a small fraction of a text-heavy stream, and each is a no-op `return event` on the
base class. Accepted, and worth a note only because it is a hot path.

## Documentation and skills

`design.md`'s Documentation section lists the surfaces this change invalidates — the two "tool-call
payloads are not filtered" claims, the six pages describing the text-only contract, the two bundled and
three dev skill entries, the migration note, and the four replacement examples for
`docs/docs/integrations/hooks.md`. The four examples follow the Conventions above: each is a
`PostHook` subclass, and any pattern set or helper they need is a class, matching
`examples/api/hooks/hooks.py`. Otherwise none of it changes the implementation, so it is not restated
here;
it is ordered as the final iteration of `plan.md`, per the `ak-dev-write-spec` flow, and verified with
`ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` before merge.

## Testing

Run: `cd ak-py && uv run pytest tests/test_runtime_stream_events.py tests/test_stream_events.py`,
then the full suite: `cd ak-py && uv run pytest`.

### `tests/test_runtime_stream_events.py` — rewritten in place

The file's module docstring (`:1-8`) and `RecordingHook` (`:71-86`) both name the removed method.

- **`RecordingHook`** — `on_stream_chunk` becomes `on_stream_event`; `self.seen` appends the event
  object it was handed (so assertions compare against the script directly), and `_transform` receives
  an event and returns an event, a list, or `None`. Its `on_run` (`:81-82`) is unchanged.
- **`ScriptedRunner`/`ScriptedAgent`** (`:37-68`) — unchanged; they yield a fixed script and are
  already event-based.
- **`isolate_system_hooks`** (`:21-34`) — unchanged. It pins `Runtime._system_pre_hooks` and
  `_system_post_hooks` to `[]` and restores `None`, which stays correct.

Existing tests, and what changes:

| Test | Change |
|---|---|
| `test_text_delta_populates_both_delta_and_event` (`:104-110`) | Unchanged — no hook involved. |
| `test_hook_rewrite_is_written_back_into_the_event` (`:113-123`) | Rewritten: the hook returns `event.model_copy(update={"content": ...})`; assert `chunk.delta` and `chunk.event.content` both carry the rewrite. The assertion survives; the mechanism moves from Runtime to hook. |
| `test_hook_returning_none_drops_the_whole_chunk` (`:126-138`) | Rewritten against `on_stream_event`; assertions unchanged. |
| `test_non_text_events_skip_the_hook_chain` (`:141-155`) | **Reversed** and renamed, e.g. `test_every_event_reaches_the_hook_chain`: `hook.seen` must now contain all three scripted events, and `_events(chunks) == script` still holds. |
| `test_reasoning_reaches_hooks_but_never_reaches_delta` (`:158-173`) | Rewritten against `on_stream_event`; the `delta` projection assertion (`[None, "ANSWER"]`) is the part that must survive. |
| `test_a_str_yielding_runner_now_fails_loudly` (`:176-187`) | Unchanged, and load-bearing: it is the test the "pydantic rejects non-events" decision relies on. |
| `test_event_yielding_runner_gets_no_synthetic_boundaries` (`:190-201`) | Unchanged. |

New tests in the same file:

1. **A list return emits N chunks in order** — a hook returning `[TextDelta(...), MessageEnd(...)]`
   for a `MessageEnd` produces two chunks, in that order, with `delta` set on the first only.
2. **A list return ends the chain** — two hooks; the first returns a list, the second records what it
   sees. Assert the second saw only the events before the fan-out. This guards the one non-obvious
   contract rule.
3. **A rewriting chain composes** — two hooks each returning a modified single event; assert the
   second received the first's output and the emitted event carries both edits.
4. **A different single-event `type` raises `TypeError`** — the message names the hook, and
   `pytest.raises(TypeError, match=...)` pins that.
5. **`StreamHalt` closes open boundaries, then yields one error chunk** — script
   `MessageStart`, `ToolCallStart`, then a hook that raises on the third event. Assert the emitted
   sequence ends `ToolCallEnd`, `MessageEnd`, `StreamChunk(error=..., done=True)`, that no
   `done=True`-without-error chunk appears, and that the closes are innermost-first.
6. **A halted run stores no session** — spy on the store (or assert the session is absent/unchanged
   after the run), mirroring rule 6 of the loop.
7. **A halt with nothing open emits only the error chunk** — no synthesised closes.
8. **Non-`StreamHalt` exceptions propagate** — a hook raising `RuntimeError` escapes
   `runtime.stream`, and no error chunk is produced. This pins the Error handling decision.
9. **The no-op case is byte-identical** — a script of one of each of the twelve event types with no
   hooks attached yields the same event sequence, in order, as the script. This is the regression
   guard for the "no subscriber, no behaviour change" claim.

### `tests/test_stream_events.py`

Unchanged. It covers the `StreamEvent` union's JSON round-trip and pickle-safety only, and touches no
hook. Its `StepStart`/`StepEnd` constructions (`:39-40`) are unaffected.

### New file: `tests/test_stream_boundaries.py`

`StreamBoundaryTracker` is exercised through `Runtime.stream` by tests 5–7 above, so a direct test was
initially called optional. It is included because without it the iteration that adds the class has
nothing to verify but "the suite is still green", which is no check at all on code not yet wired in.
It covers open/close pairing per kind, innermost-first drain order, `drain` clearing, events that open
nothing, and the two malformed cases the class tolerates by design — a close for an id never opened,
and a second open for the same id. Ids of the same value across kinds are also covered, since
LangGraph uses one `run_id` for both a message and its tool call.

### Patch targets

No `monkeypatch` target moves. `isolate_system_hooks` patches
`agentkernel.core.config.AKConfig.get`, which is untouched, and sets `Runtime._system_pre_hooks` /
`Runtime._system_post_hooks` directly — both still exist with the same names.
