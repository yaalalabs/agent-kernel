# Research — #835 progressive A2UI over AG-UI

Supporting material for `../design.md`. Both files are source reviews, not runs.

| File | Takeaway | Status |
|---|---|---|
| [`ag-ui-a2ui-middleware.md`](ag-ui-a2ui-middleware.md) | The client middleware's contract: tool name `render_a2ui` (configurable via `a2uiToolNames`), params `surfaceId` / `components` / optional `data`, result `{"a2ui_operations": [...]}` with ops at `version: "v0.9"`. Three facts drive the design: a surface needs `createSurface` **and** `updateComponents` (plus `updateDataModel` when data is given) — `createSurface` alone throws in the renderer; the result is an **unvalidated fallback** that can override the middleware's own rejection; and painting is "components atomic, data incremental", so only a repeated data array paints progressively. Pins the route to A2UI v0.9. | Read at `@ag-ui/a2ui-middleware@0.0.14`; re-read at commit `8f6c8a4`, 2026-11-11. Not executed. |
| [`adapter-tool-arg-fidelity.md`](adapter-tool-arg-fidelity.md) | Claude, Pydantic AI and MAF stream tool args in fragments (progressive); LangGraph, ADK and OpenAI send them whole (one snapshot); CrewAI and smolagents emit no tool-call events at all. | Verified against `develop` at `79789c51d`; MAF confirmed against `agent-framework-core` 1.20.0. |
