# `@ag-ui/a2ui-middleware`: what it expects from the agent

Read from `ag-ui-protocol/ag-ui` on `main`, 2026-11-10: `middlewares/a2ui-middleware/package.json`
(version `0.0.14`) and `middlewares/a2ui-middleware/src/{index,tools}.ts`.

**Status: source review, not a run.** Nothing below was executed against Agent Kernel. The spike in
`design.md`'s open questions is what confirms it end to end — though the correlation question it
was mainly there to answer is settled below.

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
above — unresolved, and listed as an open question in `design.md`.

## The tool's result

Success: JSON containing `a2ui_operations`, an array where each operation carries `version: "v0.9"`
and one of `createSurface`, `updateComponents` or `updateDataModel`, each targeting a `surfaceId`.

Hard failure: `code: "a2ui_recovery_exhausted"`, with `error` and `attempts`.

The middleware writes synthetic results of its own: `status: "rendered"` on a confirmed call,
`status: "failed"` + `code: "a2ui_render_failed"` on validation failure, and `status: "cancelled"` +
`code: "a2ui_unanswered_call"` for a call left unanswered when a new turn starts.

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
