# `@ag-ui/a2ui-middleware`: what it expects from the agent

Read from `ag-ui-protocol/ag-ui` on `main`, 2026-11-10: `middlewares/a2ui-middleware/package.json`
(version `0.0.14`) and `middlewares/a2ui-middleware/src/{index,tools}.ts`.

Re-read 2026-11-11 at commit `8f6c8a4` for the result-fallback, painting-strategy and user-action
sections below; line numbers in those sections are that commit's, since `main` moves.

**Status: source review, not a run.** Nothing below was executed against Agent Kernel. The example
in `design.md` is what confirms it end to end — the questions that could have forced a design change
(result correlation, and whether a bare `createSurface` suffices) are settled here by reading.

## The tool it watches for

`getA2UIToolNames()` returns `this.config.a2uiToolNames ?? [RENDER_A2UI_TOOL_NAME]`, and
`tools.ts` defines:

- `RENDER_A2UI_TOOL_NAME` = `"render_a2ui"`
- `LOG_A2UI_EVENT_TOOL_NAME` = `"log_a2ui_event"` — treated as a non-outer tool, not a render tool

**The name is configurable client-side.** This is the finding that makes the issue's "no
`injectA2UITool`" scope decision safe: a relay can point `a2uiToolNames` at whatever Agent Kernel
calls its tool, so AK never has to accept a client-declared tool for the middleware to find it.

## The tool's parameters

From `RENDER_A2UI_TOOL`'s `parameters` (type `object`):

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `surfaceId` | string | yes | Unique identifier for the surface |
| `components` | array of objects | yes | Flat-format A2UI v0.9 component array; the root component must have id `"root"` |
| `data` | object | no | Initial data model, written to the root path; pre-fills form values and feeds data-bound components |

The description begins *"Render a dynamic A2UI v0.9 surface with structured parameters."* and tells
the model to follow the usage guide in context.

While parsing the **streamed** args (`index.ts`), the middleware also:

- requires `surfaceId` to be a non-empty string, else `"A2UI tool arguments require a non-empty surfaceId."`
- reads an optional `catalogId` — resolution order is `defaultCatalogId`, the frontend catalog id,
  the streamed `catalogId` when it is not `"basic"`, then
  `https://a2ui.org/specification/v0_9/basic_catalog.json`
- validates `components` once the array closes
- reads a repeated list's data key from `children: { componentId, path }`, the path minus its
  leading slash (default `"items"`)

`catalogId` appears in the streamed-args parser but **not** in the tool parameter schema quoted
above. `design.md` resolves this by carrying `catalogId` as an optional tool parameter and placing
it on the emitted `createSurface`, leaving the relay's own resolution order intact when it is absent.

## The tool's result

Success: JSON containing `a2ui_operations`, an array where each operation carries `version: "v0.9"`
and one of `createSurface`, `updateComponents` or `updateDataModel`, each targeting a `surfaceId`.

Hard failure: `code: "a2ui_recovery_exhausted"`, with `error` and `attempts`.

The middleware writes synthetic results of its own: `status: "rendered"` on a confirmed call,
`status: "failed"` + `code: "a2ui_render_failed"` on validation failure, and `status: "cancelled"` +
`code: "a2ui_unanswered_call"` for a call left unanswered when a new turn starts. Those are written
only for calls still **pending** when the stream finishes (`findPendingToolCalls`, `index.ts:1155`),
so a server that answers its own tool call — as Agent Kernel does — never reaches them.

### The result is a fallback, and it is not validated

When the streaming path did not paint (`componentsEmitted` false — arguments that never parsed, or
components the validator rejected), the middleware parses the tool result's `a2ui_operations` and
emits them as activities (`index.ts:1036-1075`). Two consequences matter to Agent Kernel:

- **No validation on this path.** `tryParseA2UIOperations` is a parser; `validateA2UIComponents` is
  called only on the streamed arguments (`index.ts:811`). A server result therefore reinstates
  components the middleware has just rejected and shown as `"retrying"`. Agent Kernel accepts this
  rather than validating — see `design.md`, the tool's Requirements.
- **A `surfaceId` dedup stops a double paint.** Operations whose target surface is already in
  `streamedSurfaceIds` are filtered out; if that empties the list, nothing is emitted
  (`index.ts:1048-1062`). So returning the full envelope costs nothing when the streaming path
  already worked.

A result that parses as neither an envelope nor a recovery failure is ignored entirely.

## How it paints: components atomic, data incremental

The strategy is stated in the source (`index.ts:480-494`) and decides what "progressive" can mean:

1. `createSurface` **never** rides alone — an empty surface makes the renderer resolve a root that
   is not there and throw (`index.ts:870`). The first snapshot always carries components too.
2. `updateComponents` is computed **once**, only after the components array closes and validates
   (`index.ts:799-820`). It is re-included in later snapshots byte-for-byte, for idempotency.
3. `updateDataModel` is the only operation emitted **incrementally** — one snapshot per item as each
   entry of the repeated data array closes, reusing the already-emitted template component.

Each snapshot is cumulative and carries `replace: true`, so any one of them is self-sufficient.

The emitted shape, from `index.ts:882-911`:

```json
{"a2ui_operations": [
  {"version": "v0.9", "createSurface": {"surfaceId": "...", "catalogId": "..."}},
  {"version": "v0.9", "updateComponents": {"surfaceId": "...", "components": []}},
  {"version": "v0.9", "updateDataModel": {"surfaceId": "...", "path": "/", "value": {}}}
]}
```

**The practical reading:** a payload with a static component tree paints in exactly one snapshot, no
matter how finely the adapter streams its arguments. A growing surface needs a repeated data array
in the payload *and* an adapter that streams fragments.

## User actions never reach Agent Kernel

A click or form submission arrives as `forwardedProps.a2uiAction.userAction`. The middleware turns
it into two appended messages (`processUserAction`, `index.ts:329-383`): a synthetic assistant
message carrying a `log_a2ui_event` tool call whose arguments are the action, and a synthetic tool
message holding a prose summary of it.

Agent Kernel drops both. `AGUIRunInput.parse` selects the last message with `role == "user"` and
filters the list to that one message (`integration/agui/run_input.py:72,80`); an assistant message
and a tool message are not it. And a click with no typed text carries no user message at all, so the
request is refused with a 400 before any of this (`run_input.py:74`).

`forwardedProps` itself does survive into the session's volatile cache and is readable through the
opt-in `get_forwarded_props()` tool — but pull-based, so the model may never call it. Tracked as
issue #940; `design.md` records this route as render-only.

## How it correlates a result with its call

Entirely on `toolCallId`. `TOOL_CALL_RESULT` handling keys off `resultEvent.toolCallId`
(`index.ts:1046-1075`), streaming state is stored under `startEvent.toolCallId`
(`:710`), and the activity key is `outerCallId ?? toolCallId` throughout (`:726`, `:760`, `:970`).

**The `messageId` on a snapshot is one the middleware constructs itself** —
`` `a2ui-surface-${key}` `` (`:241`, `:970`) — not one it reads off the incoming event. So
`AGUIMapper` minting a fresh `uuid4().hex` message id for `ToolCallResultEvent`
(`integration/agui/mapping.py:52`) is harmless: nothing downstream reads it.

## What it emits

- `ACTIVITY_SNAPSHOT`, `activityType: "a2ui-surface"` (`A2UIActivityType`), each with `replace: true`
  and message id `a2ui-surface-${key}`. Lifecycle snapshots carry `status: "building"` / `"retrying"`
  / `"failed"` plus `progressTokens`, `attempt`, `errors`; the painted snapshot carries
  `a2ui_operations`.
- `TOOL_CALL_RESULT` — synthetic results for render calls still pending when the stream completes.
- `RUN_FINISHED` — held back while pending A2UI calls settle, then re-emitted.
- `RUN_ERROR` and error paths pass through, after failing any unsettled activities.
- `TEXT_MESSAGE_START/CONTENT/END`, `MESSAGES_SNAPSHOT`, `RUN_STARTED` pass through, with private
  user-action context messages filtered out. **A turn can therefore carry prose and a surface.**

A continuation loop guard stops processing with `"A2UI continuation limit reached (10)"`.

## Version pin

Every version string in the middleware is v0.9: the envelope it emits (`version: "v0.9"` at seven
sites in `index.ts`), the tool description, and the component format it asks for ("flat format
(v0.9)"). A2UI v1.0 is now the current specification (its wire string is `"1.0"`, with no `v`), but
nothing in this middleware reads or emits it. **The tool route is pinned to v0.9 by the client, not
by Agent Kernel** — see issue #931 for AK's own v1.0 move, which is deliberately separate.

## Sources

- https://github.com/ag-ui-protocol/ag-ui/tree/main/middlewares/a2ui-middleware
- https://a2ui.org/specification/v1.0-evolution-guide/
