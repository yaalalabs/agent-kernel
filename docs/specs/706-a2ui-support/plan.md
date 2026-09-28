# #706: structured replies carry their format, end to end — Implementation Plan

Nine iterations. Detail lives in [`spec.md`](spec.md); this file is the order.

**The property that makes the order safe:** nothing sets `media_type` until **iteration 6**. Until
then no labelled reply can exist, so every gate added in iterations 2–5 is unreachable and the branch
stays green whatever order they land in. Iteration 6 is the switch-on, and it is deliberately last
among the behavioural changes.

**Nothing is blocked.** Iteration 7 caps `a2a-sdk` to the 0.3 line, which restores a working import
and lets A2A ship inside this issue. The 1.x port moves to its own issue and is a bigger job than it
looks — 1.x replaced the pydantic types with **protobuf** (`new_data_message` returns
`a2a_pb2.Message`, which has no `model_dump`), so it is an object-model migration, not an import
rename.

Per iteration: `cd ak-py && uv run pytest tests/<file>` for the named test, then
`make lint-check-all` before the commit.

---

## Iteration 1: the JSON-safe payload type

- **Goal:** `AgentReplyAny` carries a `media_type` and a `content` that cannot hold an unserialisable
  value. No consumer behaviour changes yet.
- **Files:** `core/util/payload.py` (new), `core/model.py`
- **Steps:**
  1. Write `core/util/payload.py`: `JSONPayload` plus `_to_json_safe` — the non-finite/shape walk
     first, then `json.loads(TypeAdapter(Any).dump_json(v))`, re-raising as `ValueError`.
     Spec § *`core/util/payload.py`*, rules 1–6.
  2. `AgentReplyAny`: `content: JSONPayload`, add `media_type: str | None = None`. Widen
     `from_output`'s second branch to accept `list`. Do **not** touch `__str__`.
  3. `tests/test_payload.py` (new) and the `tests/test_model.py` additions, including the
     convergence assertion and the two pinned bypasses.
- **Verify:** `uv run pytest tests/test_payload.py tests/test_model.py` — and the whole suite, since
  this changes a type every reply path constructs.

## Iteration 2: the response builder gate

- **Goal:** a labelled reply would emit an object on REST, WebSocket, async mode and threads. Still
  unreachable — nothing labels yet.
- **Files:** `core/chat_service.py`
- **Steps:**
  1. Branch `ResponseBuilder.build_response` on `isinstance(result, AgentReplyAny) and
     result.media_type`. The `else` is the existing line, unmodified.
  2. Extend `tests/test_chat_service_core.py` into the labelled/unlabelled matrix.
  3. Extend `tests/test_api_http.py:412` into a matrix — **the existing assertion must keep
     passing**. This is the back-compat guarantee.
- **Verify:** `uv run pytest tests/test_chat_service_core.py tests/test_api_http.py`

## Iteration 3: the polymorphic-`result` consequences

- **Goal:** every path that would break on a dict `result` is fixed **before** anything can produce
  one. Nothing here is observable yet.
- **Files:** `pipeline/agent_runner.py`, `pipeline/transport/sqs.py`,
  `deployment/aws/serverless/core/router/rest_lambda.py`, `deployment/azure/akfunction.py`,
  `pipeline/request_handler.py`, `core/util/driver/dynamodb.py`, `integration/thread/recorder.py`
- **Steps:**
  1. The four serialisation gates → pydantic's encoder (spec § *Serialisation gates*).
  2. `pipeline/request_handler.py:116`'s `JSONResponse` → the same encoder.
  3. `DynamoDBDriver._to_dynamo` / `_from_dynamo` — **both directions**; the read side is half the
     fix, not an afterthought.
  4. `ThreadRecorder.post_run` normalises **by type** — the three call sites pass three different
     types, so "always `json.dumps`" would raise on the direct path. Spec § *thread recording*.
- **Verify:** `uv run pytest tests/test_pipeline_agent_runner.py tests/test_thread_runner.py
  tests/test_shared_drivers.py tests/test_sessions_dynamodb.py tests/test_pipeline_request_handler.py`

## Iteration 4: the stream event

- **Goal:** a structured payload can travel mid-stream and reach an AG-UI client.
- **Files:** `core/event.py`, `core/__init__.py`, `core/chat_service.py`,
  `integration/agui/mapping.py`
- **Steps:**
  1. Add `DataMessage` to `core/event.py` and to the `StreamEvent` union.
  2. Amend the module docstring's invariant at `core/event.py:16-17` in the **same** commit — it
     currently contradicts the new field.
  3. Export `DataMessage` from `core/__init__.py:15-25`, beside the other event members.
  4. `ResponseBuilder.stream_chunk`: `model_dump(mode="json", exclude_none=True)`.
  5. `AGUIMapper.to_agui`: one `case "data_message"` above the `case _` fallback at `mapping.py:64`.
- **Verify:** `uv run pytest tests/test_stream_events.py tests/test_chat_service_streaming.py
  tests/test_agui_mapping.py`

## Iteration 5: MCP

- **Goal:** MCP carries the object and the label.
- **Files:** `api/mcp/akmcp.py`
- **Steps:**
  1. `MCP.Executor.execute`: `run_multi` instead of `run`; return a `ToolResult` with
     `structured_content` and `meta` for a labelled reply, `str(reply)` otherwise.
  2. Extend `tests/test_api_mcp.py`.
- **Verify:** `uv run pytest tests/test_api_mcp.py`

## Iteration 6: the `a2ui` capability — the switch-on

- **Goal:** `a2ui: {enabled: true}` labels a declared agent's JSON replies. **The first iteration
  whose behaviour a user can observe.**
- **Files:** `a2ui/__init__.py` (new), `a2ui/hooks.py` (new), `core/config.py`, `core/runtime.py`
- **Steps:**
  1. `A2UIPostHook`, `NoOpA2UIPostHook`, `A2UIPostHookFactory` — copy `SandboxPreHookFactory`
     (`sandbox/hooks.py:134-149`) for the enabled/disabled/failed resolution.
  2. `_A2UIConfig` beside `_SandboxConfig` (`core/config.py:786`); register on `AKConfig` beside
     `sandbox` (`:919`).
  3. Add `A2UIPostHookFactory.get()` to `Runtime._get_system_post_hooks` (`core/runtime.py:130`),
     today a one-element literal.
  4. `tests/test_a2ui_hook.py` (new) and the `tests/test_config.py` addition.
- **Verify:** `uv run pytest tests/test_a2ui_hook.py tests/test_config.py tests/test_runtime.py`
- **Note:** the hook is `on_run`, which `Runtime.stream` never calls — so the block has **no effect
  on a streamed run**. Deliberate (design Non-goals), but log a one-line warning at factory
  construction when `execution.mode` is `stream` and `a2ui.enabled` is true, so the silence is
  explained rather than discovered.

## Iteration 7: A2A — cap the pin, then send the data part

- **Goal:** A2A imports again, gets its first tests, and sends a data part for a labelled reply.
  **No longer blocked**: capping restores a working SDK, and the 1.x port becomes its own issue with
  a tested A2A to port *from*.
- **Files:** `ak-py/pyproject.toml`, `ak-py/uv.lock`, `api/a2a/a2a.py`,
  `ak-py/tests/test_a2a.py` (new)
- **Steps:**
  1. **Cap the pin** to `a2a-sdk[http-server]>=0.3.6,<0.4` (`pyproject.toml:168`) and regenerate
     `ak-py/uv.lock`. This moves the lock **backwards**, 1.1.2 → 0.3.x, which is safe precisely
     because nothing uses 1.1.2: A2A does not import against it, so no code path exercises it today.
     The example's lock (`examples/api/a2a/multi/uv.lock`) already pins 0.3.6 and does not move.
  2. **Write `tests/test_a2a.py` first** — A2A's first test file, against the now-importable SDK: a
     text reply produces a text message, the error path stays text, the card carries what it carries.
     This is the "characterise before porting" step the design wanted and could not previously run.
  3. `_execute_agent` → `run_multi`; tighten the return annotation from `Any`.
  4. `execute` branches on the media type at `a2a.py:49`. **Verified working on 0.3.6:**

     ```python
     new_agent_parts_message(
         [Part(root=DataPart(data=reply.content,
                             metadata={"mimeType": reply.media_type}))],
         context_id, task_id)
     ```

     Everything unlabelled keeps `new_agent_text_message`; the error path stays text.
  5. Declare the extension on each covered agent's card in `A2A._build` (`api/a2a/a2a.py:76`) —
     `A2UI_EXTENSION_URI` from the capability, `AgentExtension` built here so `core/` stays clean.
     Decision 12.
  6. Extend `tests/test_a2a.py` with both branches and the card declaration, and add the A2A leg to
     the parity test.
- **Verify:** `uv run pytest tests/test_a2a.py tests/test_cross_surface_parity.py`
- **The cost, recorded so the port issue inherits it:** on 0.3.x the label rides in
  `DataPart.metadata["mimeType"]`; on 1.x it is a first-class `media_type` field on the part. **The
  wire shape therefore changes at the port** — a breaking change for an A2A client reading the label,
  though there are none today because A2A has never sent a data part. The port issue owns the
  migration note.

## Iteration 8: tests

Per-iteration tests land with their iteration. This iteration adds what spans them.

- **Files:** `tests/test_cross_surface_parity.py` (new)
- **Steps:**
  1. One labelled reply asserted to arrive with the same content and label on REST, WebSocket, MCP
     and AG-UI. **The fixture carries a `datetime` and a `Decimal`** — parity on a payload that was
     never at risk proves nothing. A2A's leg is added with iteration 7.
  2. Confirm the back-compat matrix from iteration 2 still passes unchanged.
  3. Full suite green.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all`

## Iteration 9: example, docs and skills

- **Files:**
  - New example under `examples/` — an agent with its own catalog in its instructions, `a2ui`
    enabled, payload over plain REST. Its `app_test.py` asserts `media_type` is present and `result`
    is an object.
  - **Docs:** `docs/docs/api/rest-api.md` (the gated `result` contract and `media_type`),
    `mcp-server.md`, `agui-server.md`, `a2a-server.md` (with iteration 7), and a new
    `docs/docs/advanced/a2ui.md` beside `sandbox.md` plus its sidebar entry.
  - **Skills — named, with the line each invalidates:**
    - `.agents/skills/ak-dev-architecture/SKILL.md:275` — "`AgentReplyAny`: `content: dict` … `str(reply)`
      returns the JSON-serialized content" is wrong twice after iteration 1: `content` is
      `dict | list`, there is a `media_type`, and `str(reply)`'s output changes for non-JSON-safe
      content.
    - `.agents/skills/ak-dev-architecture/SKILL.md:101` — enumerates the twelve stream events;
      `DataMessage` is the thirteenth.
    - `.agents/skills/ak-dev-testing-conventions/SKILL.md` — the `test_stream_events.py` row gains
      `DataMessage`; add rows for `test_payload.py`, `test_a2ui_hook.py` and
      `test_cross_surface_parity.py`.
- **Verified as needing no update:** `ak-dev-new-framework-integration` (no `AgentReplyAny` mention —
  adapters never set `media_type`), and the five other docs pages showing a `result`
  (`advanced/scheduling.md`, `advanced/traceability.md`, `architecture/execution-flow.md`,
  `deployment/aws-serverless.md`, `deployment/azure-serverless.md`) — every example there is a text
  or unlabelled reply, so none becomes wrong.
- **Steps:** run `ak-dev-sync-skills-from-branch` and `ak-dev-sync-docs-from-branch` rather than
  editing by hand, then confirm the three skill edits above are present.
- **Verify:** `make lint-check-all`; the example's own `uv run pytest`.
