# #836: Record AG-UI runs as conversation threads — Implementation Spec

Both AG-UI handlers record their runs into the conversation-thread store when a `thread` block is
configured. Two new classes carry the work: `StreamedReply` turns a streamed run into the one thing a
thread records, and `AGUIThreadRecorder` turns an AG-UI run into `ThreadRecorder` calls. The direct
handler brackets its own run; the queue handler records the user turn at the edge and marks the
message, and `AgentRunner._process_agui` records the reply. Requirements source: [design.md](design.md).

**Base.** This spec is written against `develop` with #827 applied (`feature/607-hitl-threads-support`,
head `674550b9`). Citations marked **#827** are to that branch; unmarked citations, including
"develop" ones into the same files, are to `develop` (`34761337`). Re-verify the #827 ones after it
merges.

## Design

### 1. `StreamedReply` — `integration/thread/recorder.py`

Collects one streamed run and answers "what does the thread record for it?". It lives beside
`ThreadRecorder` because the rule it encodes — error beats pause beats text, empty records nothing —
is the thread capability's (#827 `thread_chat.py:174-196`), not AG-UI's.

```python
class StreamedReply:
    """The reply a streamed run leaves in a thread, accumulated chunk by chunk."""

    def __init__(self, session_id: str): ...
    def add(self, chunk: StreamChunk) -> None:      # records error / delta / DataMessage / RunPaused
    @property
    def paused(self) -> bool: ...                   # a pause was seen and no error
    def result(self) -> Optional[AgentReply | str]: # what post_run is handed, or None
```

Rules, in precedence order:

1. Any chunk with `error` set → `result()` is `None`. Error beats everything, the pause included
   (#827 `thread_chat.py:154-158` gives the reason: the failure after a pause is the one that never
   persisted it).
2. A `RunPaused` event → an `AgentPausedReplyAny(run_id, session_id, agent, interruptions)`, built
   field-for-field as #827 `thread_chat.py:185-190` builds it. `ThreadRecorder._as_thread_message`
   (#827 `recorder.py`) already maps it to `(content, HITL_MEDIA_TYPE)`.
3. A `DataMessage` event (`core/event.py:215`) → `AgentReplyAny(content=..., media_type=...)`, the
   last one seen. A labelled `AgentReplyAny` takes the existing labelled branch of
   `_as_thread_message`, so the stored shape is #763's with no new code in the recorder.
4. Text deltas → the deltas joined with `""`.
5. Nothing of the above → `None`.

`session_id` is a constructor argument because `RunPaused` carries none and `AgentPausedReplyAny`
requires one (`core/model.py:293`).

### 2. `AGUIThreadRecorder` — `integration/agui/thread.py` (new)

The one class both AG-UI paths call. It owns no recording logic; it adapts an AG-UI run to
`ThreadRecorder`.

```python
class AGUIThreadRecorder:
    """Thread recording for AG-UI runs, active exactly when a `thread` block is configured."""

    def __init__(self, recorder: ThreadRecorder): ...

    @classmethod
    def create(cls) -> Optional["AGUIThreadRecorder"]:
        # None when ConversationThreadManager.get() is None — the enabled-check, nothing else

    @staticmethod
    def chat_request(run_input, user_id: Optional[str], agent_name: str, requests: list[AgentRequest]) -> BaseChatRequest:
        # session_id=thread_id, user_id, agent, prompt=text parts joined with "\n" (explicit, even
        # when ""), resume=ResumeSpec(decisions=...) copied from the AgentResumeRequestAny in
        # `requests` when present; group_id / thread_name left None

    def pre_run(self, req: BaseChatRequest, requests: list[AgentRequest]) -> list[AgentRequest]:
        # ThreadRecorder.pre_run; ValueError -> HTTPException(400). Returns the rebuilt list.

    def post_run(self, req: BaseChatRequest, reply: StreamedReply) -> None:
        # direct path only: no-op when reply.result() is None; ThreadRecorder.post_run otherwise;
        # any exception is logged and swallowed
```

Rules:

1. **Enablement is `create()` returning non-`None`**, read once in each handler's `__init__`, the
   way `AgentThreadRequestHandler.__init__` reads the manager (`thread_chat.py:62`). No config field,
   no constructor parameter.
2. **`prompt` is always passed explicitly.** `BaseChatRequest._require_a_prompt_or_a_resume`
   (`core/model.py:434`) is keyed on `model_fields_set`, so an explicit `""` is valid. An image-only
   AG-UI turn (allowed: `_reject_empty_content` only refuses an empty part list,
   `run_input.py:179-183`) therefore builds a valid request with `prompt=""`.
3. **The decisions are copied, not re-derived.** `ResumeSpec` and `AgentResumeRequestAny` share
   their fields through `_ResumeDecisions` (`core/model.py:184-203`); `run_id` stays `None` because
   `to_resume` sets none (`run_input.py:121-134`).
4. **`pre_run`'s rejections are HTTP 400**, raised before anything is written — `ThreadRecorder.pre_run`
   runs `store_attachments` before `get_or_create_thread` for exactly this reason (`recorder.py:38-41`).
5. **`post_run` never fails the stream.** By the time it runs the client has its answer; a thread
   store outage is logged at `exception` level on `ak.integration.agui.thread`.

### 3. Direct path — `AGUIRequestHandler` (`integration/agui/handler.py`)

- `__init__`: `self._threads = AGUIThreadRecorder.create()`.
- `_run` (`handler.py:203-236`), after `prepare_agent_handler` and the session check
  (`handler.py:222-229`), when `self._threads` is set:
  1. `req = AGUIThreadRecorder.chat_request(run_input, user_id, agent_name, requests)`.
  2. `requests = await asyncio.to_thread(self._threads.pre_run, req, requests)`.
  3. Pass `req` to `_events`.
  - Placement: after every check that can reject the request, so a 404/400/500 from them leaves no
    thread. A `pre_run` 400 at this point has selected a session but not stored one — sessions are
    persisted only by `Runtime`'s `store()`, which no run reached.
- `_events` (`handler.py:238-318`) gains an optional `thread_request: Optional[BaseChatRequest]`:
  1. Build a `StreamedReply(run_input.thread_id)` and `add()` every chunk in the existing loop,
     including the error, `RunPaused` and unmapped ones it `continue`s past (`handler.py:280-293`).
  2. The existing early returns on an exception (`:294-297`) and on an error chunk (`:299-301`) stay
     where they are, so neither path records.
  3. After them, **before** the state snapshot and terminal event (`:303`), call
     `await asyncio.to_thread(self._threads.post_run, thread_request, reply)`.
  - Why before the terminal event, not after: Starlette stops iterating a `StreamingResponse`
    generator when the client disconnects, so code after the last `yield` can be skipped. Recording
    before `RunFinished` makes the record independent of how the client hangs up.
- Why `asyncio.to_thread` for both calls: `ThreadRecorder` is synchronous and does blocking I/O on
  the event loop otherwise — the store write, and on a thread's first turn the naming strategy's
  LiteLLM call (`ThreadNamingStrategy`). The queue handler already offloads its synchronous send for
  the same reason (`queue_handler.py:140-147`).

### 4. Queue path, edge — `AGUIPipelineRequestHandler` (`integration/agui/queue_handler.py`)

- `__init__`: inherits `self._threads` from the direct handler's `__init__`.
- `_run` (`queue_handler.py:112-151`), replacing the attachment offload (`:131-137`):
  - Threads on: build `req`, then `requests = await asyncio.to_thread(self._threads.pre_run, req, requests)`.
    `pre_run`'s `store_attachments` performs the same `AttachmentStorageManager.offload`
    (`integration/thread/manager.py:172-185`), so bytes are offloaded exactly once.
  - Threads off: today's `offload` call, unchanged.
- The enqueue attributes become `{ATTR_AGUI: "1", ATTR_THREAD: "1"}` when threads are on, else
  today's `{ATTR_AGUI: "1"}`.
- Placement: after `_resolve_run_inputs`, `AGUIRunEnvelope.build` and `reject_if_oversized`
  (`:126-128`), so none of their 400s leaves a thread; before the enqueue.

### 5. Queue path, runner — `AgentRunner._process_agui` (`pipeline/agent_runner.py`)

#827 leaves `_process_agui` byte-identical to `develop` (`agent_runner.py:87-145` develop,
#827 `:76-134`). Changes:

1. Build `reply = StreamedReply(body.session_id)` and `reply.add(chunk)` for every chunk of
   `handler.run_stream_sync(...)`, before the chunk is serialised (the loop at develop `:126-133`).
2. After the terminal chunk is sent (develop `:141-143`), call
   `self._record_thread_reply(message, body, 202 if reply.paused else 200, reply.result())`.
   - The existing guard does the rest (#827 `agent_runner.py:269`): no `ATTR_THREAD` → nothing;
     `result in (None, "")` → nothing. A runner without a `thread` block warns and drops, as today.
   - Status 202 for a pause matches #827 `StreamAgentRunner` (#827 `agent_runner.py:376`).
   - After the send, never raising: `_record_thread_reply`'s existing contract
     (#827 `agent_runner.py:242-286`), so a redelivery cannot duplicate the reply and a thread-store
     failure cannot re-run the agent.
3. The selection-failure early return (develop `:114-119`) records nothing: there is no reply.
4. The docstring line "Thread recording is likewise absent: `ATTR_AGUI` is not `ATTR_THREAD`"
   (develop `:96`) is rewritten to say the reply is recorded when the edge set `ATTR_THREAD`.

`StreamedReply` is imported lazily inside `_process_agui`, beside the existing lazy AG-UI imports
(develop `:106-107`) — `pipeline` reaches `integration` only in-method (architecture rule 2).
`AGUIRunRequest` subclasses `BaseRunRequest` (`run_input.py:342`), so it satisfies
`_record_thread_reply`'s `body` parameter unchanged.

### 6. Read routes — no handler change

- `AGUIRequestHandler.get_router` (`handler.py:129-176`) is unchanged: it does not include
  `ThreadRESTRequestHandler`'s router, with or without a `thread` block.
- The app mounts the read routes itself, beside the AG-UI handler:

  ```python
  from agentkernel.thread import ThreadRESTRequestHandler  # exported at integration/thread/__init__.py:18

  IOHandler.run(handlers=[
      AGUIPipelineRequestHandler(authoriser=auth),
      ThreadRESTRequestHandler(authoriser=auth),
  ])
  ```

  `IOHandler.run(handlers=...)` mounts both beside the pipeline's own `RequestHandler`; the
  `/api/v1/threads` paths collide with none of its routes. The same pair works under
  `RESTAPI.run(handlers=[AGUIRequestHandler(...), ThreadRESTRequestHandler(...)])` on the direct path.
- Passing the same `Authoriser` to both keeps a caller's listings and reads scoped to the user its
  runs were recorded under (`ThreadRESTRequestHandler` forces listings to the resolved user and
  enforces ownership on reads, `thread_chat.py:351-372`).
- An app that records AG-UI threads but mounts no read handler still records; nothing warns. The
  history is reachable once the routes are mounted, so this is documentation, not a startup check.

### 7. Example — `examples/api/agui`

| File | Change |
|---|---|
| `config.yaml` | Add `thread: {type: in_memory}`. `multimodal` is already enabled on `in_memory` storage (`config.yaml:30-31`), which `store_attachments` accepts. |
| `config.broker.yaml` | Add `thread: {type: valkey, valkey: {url: valkey://localhost:6379, prefix: "ak:agui:thread:"}}`, on the Valkey the file already uses for sessions (`config.broker.yaml:24-30`). Required: the edge records the user turn and `app_runner.py` records the reply, in different processes. |
| `app.py` | `runner()` (`app.py:111-119`) mounts `ThreadRESTRequestHandler(authoriser=DemoAuthoriser())` beside `AGUIPipelineRequestHandler`. |
| `app_test.py` | `test_a_run_is_recorded_as_a_thread`: send `run_input(prompt, thread_id)` through `collect`, then `GET /api/v1/threads/{thread_id}` with `AUTH`; assert `user_id == "demo-user"`, two messages, roles `user` then `assistant`, user content equals the prompt, assistant content non-empty. Uses the file's existing `base_url`, `run_input`, `collect` and `AUTH` helpers (`app_test.py:21-52`). |
| `README.md` | A "Conversation history" section after "Attachments" (`README.md:126`): the `thread` block, the read-route mount, a `curl` for `GET /api/v1/threads/{threadId}`, and the broker note. |

`examples/api/hitl` is unchanged (design non-goal).

### Module-level functions

None added.

### Consumer changes

| Consumer | Change |
|---|---|
| `AGUIRequestHandler` | `_threads` set in `__init__`; `_run` builds and pre-records; `_events` accumulates and post-records. Nothing changes when `_threads` is `None`. |
| `AGUIPipelineRequestHandler` | `_run` swaps `offload` for `pre_run` and adds `ATTR_THREAD` when `_threads` is set. |
| `AgentRunner._process_agui` | Accumulates and calls `_record_thread_reply`. |
| `ThreadRecorder`, `ConversationThreadManager`, store backends, read routes | Unchanged. |
| `AgentThreadRequestHandler`, `ThreadRequestHandler`, `StreamAgentRunner` | Unchanged; they keep their inline accumulators (design non-goal). |
| `examples/api/agui` | Records threads and serves the read routes (§7). |

### Config changes

None. The `thread` block (`_ThreadStoreConfig`) is reused as-is and its presence is the enabled-check.
Existing YAML and `AK_THREAD__*` variables behave identically; no field, default or description moves.
The env-var caveat the thread docs already state applies here too: any `AK_THREAD__*` variable
materialises the block, which now also turns on AG-UI recording.

### Behavioural changes

All intentional, all only when a `thread` block is present:

1. AG-UI runs on either handler create/append threads keyed by `threadId`. Without a `thread` block,
   nothing changes. *Justification:* the issue's objective.
2. Direct path: an AG-UI attachment is stored by `ThreadRecorder.pre_run` before the run and reaches
   the agent as an `AgentRequestAttachmentRef`, instead of being described and stored by
   `MultimodalPreHook` from the raw request. *Justification:* the REST thread path does the same, so
   the user message can carry `ThreadAttachment` references.
3. Direct path: an AG-UI attachment with `multimodal.enabled: false` or `storage_type: session_cache`
   is now a 400 (thread wording). Today it passes through to the adapter. *Justification:* a thread
   cannot reference an attachment it cannot store; the REST thread path already refuses it.
4. Queue path: the same two rejections use the thread wording rather than AG-UI's
   (`queue_handler.py:30-37`) and are a 400 rather than an uncaught `ValueError` (see Non-changes).
5. The first turn of a new thread makes the naming strategy's LiteLLM call before the run starts,
   adding its latency to time-to-first-event. *Justification:* REST threads pay the same; the call
   runs off the event loop.
6. AG-UI records a `DataMessage` payload as a labelled object. The threaded REST SSE path
   (#827 `thread_chat.py:174-196`) does not — it records only text or a pause. *Justification:*
   AG-UI is the surface that forwards `DataMessage` to clients (`mapping.py:65-66`), so replayed
   history should match what the client rendered. Aligning the REST SSE path is a follow-up.

**Non-changes:**

- `ThreadMessage` layout, `ThreadRecorder` signatures, store data layouts, read-route responses.
- AG-UI wire output: every event, its order and the terminal shapes are unchanged; recording emits nothing.
- AG-UI routes: neither handler gains a route; the read routes stay app-mounted (§6).
- The pre-existing uncaught `ValueError` from `AttachmentStorageManager.offload` on the queue path
  with threads **off** (`queue_handler.py:132-137`, no exception handler in `api/` or `pipeline/`).
  Out of scope; noted for a follow-up.
- Public exports: `AGUIThreadRecorder` and `StreamedReply` are not added to
  `agentkernel.agui` / `agentkernel.thread`.

## Error handling

| Failure | Where | Outcome |
|---|---|---|
| `pre_run` `ValueError` (attachments refused) | edge, both paths | HTTP 400, nothing written, nothing enqueued |
| Thread store down during `pre_run` | edge | HTTP 500 from FastAPI, before the stream starts; no run |
| Enqueue fails after `pre_run` | queue edge | User message recorded with no reply — same exposure as `ThreadRequestHandler` (`thread_chat.py:282-284`) |
| Run errors / halts / is empty | both | No assistant message (`StreamedReply.result()` is `None`) |
| Thread store down during `post_run` | direct | Logged; client still gets its terminal event |
| Thread store down during `_record_thread_reply` | runner | Logged; message acked, not retried (existing contract) |
| Runner has no `thread` block | runner | Existing warning; reply dropped |
| `RunPaused` without `session_id` | `StreamedReply` | Cannot happen: `session_id` is a constructor argument |

## Testing

New:

- `tests/test_thread_streamed_reply.py` — `StreamedReply` alone: text joined; error → `None`;
  empty → `None`; pause → `AgentPausedReplyAny` with `paused` true; pause after text → pause;
  error after pause → `None`; `DataMessage` → labelled `AgentReplyAny`; the paused reply equal
  (`model_dump_json`) to what #827 `_stream_with_recording` builds for the same event.
- `tests/test_agui_thread.py` — `AGUIThreadRecorder`: `create()` is `None` without a block;
  `chat_request` for text, multi-part text, image-only (`prompt == ""` passes validation), and a
  resume (decisions copied, `run_id` `None`); `pre_run` `ValueError` → `HTTPException(400)`;
  `post_run` no-op on `None`, swallow-and-log on a store error.

Extended:

- `tests/test_agui_handler.py` — with `ConversationThreadManager.reset()` and an in-memory `thread`
  block: user + assistant recorded, keyed by `threadId`, `user_id` from the authoriser; error chunk,
  raised exception and empty run record no assistant message; a pausing run records the pause; a
  resume run records the decision as the user message; an attachment with multimodal off is a 400
  with no thread; no `thread` block leaves the store untouched and the event stream byte-identical.
- `tests/test_agui_queue_handler.py` — `ATTR_THREAD` present only with a block; `offload` not called
  when threads are on (patch `AttachmentStorageManager.offload` and assert one store write);
  `pre_run` rejection is a 400 with nothing enqueued.
- `tests/test_thread_pipeline_recording.py` — `_process_agui` with `ATTR_THREAD`: reply recorded
  after the terminal chunk is sent; pause recorded under 202; error records nothing; no
  `ATTR_THREAD` records nothing; no `thread` block in the runner warns and drops.
- `tests/test_thread_integration.py` — round trip: an AG-UI run and a REST run of the same scripted
  agent, read back through `GET /api/v1/threads/{session_id}`, produce messages equal apart from
  `message_id` and `timestamp`.

Example:

- `examples/api/agui/app_test.py` — `test_a_run_is_recorded_as_a_thread` (§7), run against the
  single-process app with a real model, like the file's other tests.

Patch targets that move: none. Existing AG-UI and thread tests run unchanged, since no block means
no recording.

Example run: `cd examples/api/agui && ./build.sh local && .venv/bin/pytest -s app_test.py` (needs
`OPENAI_API_KEY`; `.venv/bin/pytest`, not `uv run`, so the local wheel is not re-resolved away —
`README.md:360-366`).

Run: `cd ak-py && uv run pytest tests/test_thread_streamed_reply.py tests/test_agui_thread.py tests/test_agui_handler.py tests/test_agui_queue_handler.py tests/test_thread_pipeline_recording.py tests/test_thread_integration.py`, then the full suite.
