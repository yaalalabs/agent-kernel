# #706: structured replies carry their format, end to end — Implementation Plan

Eight iterations, every one about A2UI. Detail lives in [`spec.md`](spec.md); this file is the
order.

**The property that makes the order safe:** nothing sets `media_type` until **iteration 6**, the
last one that changes behaviour. Until
then no labelled reply can exist, so every gate added in iterations 2–5 is unreachable and the branch
stays green whatever order they land in. Iteration 6 is the switch-on, and it is deliberately last
among the behavioural changes.

**Nothing is blocked, and A2A is not here at all.** It does not import against the pinned SDK today,
and fixing that, porting to 1.x and carrying A2UI over it all belong to the `a2a-sdk` port issue
(design Decision 6). No iteration touches `pyproject.toml`, `uv.lock` or `api/a2a/`.

Per iteration: `cd ak-py && uv run pytest tests/<file>` for the named test, then
`make lint-check-all` before the commit.

---

## Iteration 1: the JSON-safe payload type

- **Goal:** `AgentReplyAny` carries a `media_type` and a `content` that cannot hold an unserialisable
  value. No consumer behaviour changes yet.
- **Files:** `core/util/payload.py` (new), `core/model.py`
- **Steps:**
  1. Write `core/util/payload.py`: the **`PayloadCodec`** class — `normalise` (shape check, then the
     non-finite walk, then the round trip) and `encode` (used by iteration 3's gates) — plus the
     `JSONPayload` annotated type built from `normalise`. Spec § *`core/util/payload.py`*.
  2. `AgentReplyAny`: `content: JSONPayload`, add `media_type: str | None = None`. Leave
     `from_output` alone — `content` accepts a list, but promoting a bare list there would change
     `result` for an agent that never opted in (spec § `core/model.py`). Do **not** touch `__str__`.
  3. `tests/test_payload.py` (new) — both halves of `PayloadCodec` — and the `tests/test_model.py`
     additions, including the convergence assertion and the two pinned bypasses.
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
  3. Extend `tests/test_api_http.py:400` into a matrix — **the existing assertion must keep
     passing**. This is the back-compat guarantee.
- **Verify:** `uv run pytest tests/test_chat_service_core.py tests/test_api_http.py`

## Iteration 3: the polymorphic-`result` consequences

- **Goal:** every path that would break on a dict `result` is fixed **before** anything can produce
  one. Nothing here is observable yet.
- **Files:** `pipeline/envelope.py`, `pipeline/transport/sqs.py`,
  `deployment/aws/serverless/core/router/rest_lambda.py`, `deployment/azure/akfunction.py`,
  `deployment/aws/core/websocket_service.py`, `pipeline/request_handler.py`,
  `core/util/driver/dynamodb.py`, `integration/thread/recorder.py`
- **Steps:**
  1. Put the rule where it cannot be skipped rather than at each seam (spec § *Serialisation
     gates*): `ResponseBuilder.build_response` re-normalises the one value that can reach a client as an
     object, so anything it returns survives a bare `json.dumps`, and `QueueMessage.body` takes
     `JSONText` so no sender or future transport has to know the rule exists. One explicit
     `PayloadCodec.encode` remains, in `serialize_message_body`, which also serves callers that
     passed through neither.
  2. `pipeline/request_handler.py:122`'s `JSONResponse` → the same `PayloadCodec.encode`.
  3. New **`DynamoDecimalCodec`** beside `DynamoDBDriver`: `to_dynamo` on write, `from_dynamo` on
     read — **both directions**; the read side is half the fix, not an afterthought.
  4. New **`ThreadRecorder._as_thread_content`** — the three call sites pass three different types,
     so "always `json.dumps`" would raise on the direct path. A named method, not inline branching.
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
- **Files:** `a2ui/__init__.py` (new), `a2ui/hook.py` (new), `core/config.py`, `core/runtime.py`
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

## Iteration 7: tests

Per-iteration tests land with their iteration. This iteration adds what spans them.

- **Files:** `tests/test_cross_surface_parity.py` (new)
- **Steps:**
  1. One labelled reply asserted to arrive with the same content and label on REST, WebSocket, MCP
     and AG-UI. **The fixture carries a `datetime` and a `Decimal`** — parity on a payload that was
     never at risk proves nothing. A2A joins when the port issue adds the data part.
  2. Confirm `PayloadCodec.encode` is the only encoder at every gate site — the copy-drift the
     single component exists to prevent — and that `QueueMessage.body` carries the rule on the
     field (`JSONText`) rather than leaving it to each sender, so a transport added later inherits
     it. The thread recorder is the one deliberate exception and uses `json.dumps(default=str)`, to
     stay byte-identical to the direct path's `AgentReplyAny.__str__`
     (spec § `integration/thread/recorder.py`).
  3. Confirm the back-compat matrix from iteration 2 still passes unchanged.
  4. Full suite green.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all`

## Iteration 8: example, docs and skills

- **Files:**
  - New example under `examples/` — an agent with its own catalog in its instructions, `a2ui`
    enabled, payload over plain REST. Its `app_test.py` asserts `media_type` is present and `result`
    is an object.
  - **Docs:** `docs/docs/api/rest-api.md` (the gated `result` contract and `media_type`),
    `mcp-server.md`, `agui-server.md`, and a new
    `docs/docs/advanced/a2ui.md` beside `sandbox.md` plus its sidebar entry.
  - **Config reference — one section per capability, and A2UI needs its own in each:**
    `ak-py/README.md` (`#### A2UI Configuration`, in the AG-UI section's Field/Default/Description/
    Environment Variable shape, plus a `## Features` bullet) and
    `docs/docs/core-concepts/configuration.md` (an `a2ui:` entry in the Basic Configuration File
    sample and an `### A2UI` env-var subsection). Its "Complete Configuration Reference" is left
    alone — it already omits six other blocks and is stale beyond this change.
  - **Where the capability is announced:** `README.md`'s Open Standards row,
    `docs/docs/intro.md`'s protocol bullet list and its What's New tip, and the `protocols` array in
    `docs/src/pages/features.tsx`. All four list MCP / A2A / AG-UI and none mentions A2UI.
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
    - `.agents/skills/ak-dev-architecture/SKILL.md:146` — "`OutputGuardrailFactory` as system
      post-hook" names the only one there is; after iteration 6 there are two.
    - `.agents/skills/ak-dev-architecture/SKILL.md:275` — the Key sections list of config blocks has
      no `a2ui`. It belongs with `sandbox` (an `enabled` flag), not with the capability-gating
      blocks on the line below.
    - `.agents/skills/ak-dev-architecture/SKILL.md` directory tree — a new **top-level** `a2ui/`
      branch under `agentkernel/`. It is not under `integration/`, where `agui/` lives.
    - `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` — the **user** skill, which
      enumerates every capability twice: a numbered menu item and a `#### <Capability>` body. Both
      need an A2UI entry, in the AG-UI entry's shape.
  - **CI:** `.github/test-config.yaml` — the new example needs a two-line `type: api` entry beside
    its siblings, or its `app_test.py` never runs.
- **Verified as needing no update:** `ak-dev-new-framework-integration` (no `AgentReplyAny` mention —
  adapters never set `media_type`), and four of the five other docs pages showing a `result`
  (`advanced/scheduling.md`, `advanced/traceability.md`, `deployment/aws-serverless.md`,
  `deployment/azure-serverless.md`) — every example there is a text or unlabelled reply, so none
  becomes wrong. `architecture/execution-flow.md` **does** need one: it enumerates the system
  post-hooks, which is a list this change adds to.
- **Steps:** run `ak-dev-sync-skills-from-branch` and `ak-dev-sync-docs-from-branch` rather than
  editing by hand, then confirm the three skill edits above are present.
- **Verify:** `make lint-check-all`; the example's own `uv run pytest`.
