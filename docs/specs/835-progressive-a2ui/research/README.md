# Research — #835 progressive A2UI over AG-UI

Supporting material for `../design.md`. Both files are source reviews, not runs.

| File | Takeaway | Status |
|---|---|---|
| [`ag-ui-a2ui-middleware.md`](ag-ui-a2ui-middleware.md) | The client middleware's contract: tool name `render_a2ui` (configurable via `a2uiToolNames`), params `surfaceId` / `components` / optional `data`, result `{"a2ui_operations": [...]}` with ops at `version: "v0.9"`. Pins the route to A2UI v0.9. | Read at `@ag-ui/a2ui-middleware@0.0.14`, 2026-11-10. Not executed. |
| [`adapter-tool-arg-fidelity.md`](adapter-tool-arg-fidelity.md) | Claude and Pydantic AI stream tool args in fragments (progressive); LangGraph, ADK and OpenAI send them whole (one snapshot); MAF is chunk-based and likely progressive, pending one read of the SDK; CrewAI and smolagents emit no tool-call events at all. | Verified against `develop` at `79789c51d`. |
