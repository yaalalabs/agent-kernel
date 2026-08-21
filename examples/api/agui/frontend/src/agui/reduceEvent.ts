import type { AgUiAction, DemoState, Line, Status, TextLine, ToolLine, View } from "./types.ts";
import { uuid } from "./uuid.ts";

export const EMPTY_VIEW: View = { lines: [], status: null, state: null };

const busy = (what: string, detail?: string): Status => ({ what, detail });

/** Fold one AG-UI event into the view. Unknown types leave the view unchanged. */
export function reduceEvent(view: View, event: AgUiAction): View {
  switch (event.type) {
    case "__local":
      return { ...view, lines: [...view.lines, event.line] };

    case "RUN_STARTED":
      return { ...view, status: busy("Working") };
    case "RUN_FINISHED":
      return { ...view, status: null };
    case "RUN_ERROR":
      return { ...view, status: null, lines: [...view.lines, { id: uuid(), kind: "error", text: event.message }] };

    case "STEP_STARTED":
      return { ...view, status: busy("Step", event.stepName) };
    case "STEP_FINISHED":
      return { ...view, status: busy("Working") };

    case "TEXT_MESSAGE_START":
      return { ...view, status: busy("Replying"), lines: [...view.lines, { id: event.messageId, kind: "assistant", text: "" }] };
    case "TEXT_MESSAGE_CONTENT":
      return {
        ...view,
        lines: patchLine<TextLine>(view.lines, event.messageId, { kind: "assistant", text: "" }, (line) => ({ text: line.text + event.delta })),
      };
    case "TEXT_MESSAGE_END":
      return { ...view, status: busy("Working") };

    case "REASONING_MESSAGE_START":
      return { ...view, status: busy("Thinking"), lines: [...view.lines, { id: event.messageId, kind: "thinking", text: "" }] };
    case "REASONING_MESSAGE_CONTENT":
      return {
        ...view,
        status: busy("Thinking"),
        lines: patchLine<TextLine>(view.lines, event.messageId, { kind: "thinking", text: "" }, (line) => ({ text: line.text + event.delta })),
      };
    case "REASONING_MESSAGE_END":
      return { ...view, status: busy("Working") };

    case "TOOL_CALL_START":
      return {
        ...view,
        status: busy("Calling", event.toolCallName),
        lines: [...view.lines, { id: event.toolCallId, kind: "tool", name: event.toolCallName, args: "", result: null, open: true }],
      };
    case "TOOL_CALL_ARGS":
      return { ...view, lines: patchLine<ToolLine>(view.lines, event.toolCallId, null, (line) => ({ args: line.args + event.delta })) };
    case "TOOL_CALL_END": {
      const call = view.lines.find((line) => line.id === event.toolCallId);
      return {
        ...view,
        status: busy("Running", call?.kind === "tool" ? call.name : undefined),
        lines: patchLine<ToolLine>(view.lines, event.toolCallId, null, () => ({ open: false })),
      };
    }
    case "TOOL_CALL_RESULT":
      return {
        ...view,
        status: busy("Working"),
        lines: patchLine<ToolLine>(view.lines, event.toolCallId, null, () => ({ result: event.content, open: false })),
      };

    case "STATE_SNAPSHOT":
      return { ...view, state: event.snapshot as DemoState };

    default:
      return view;
  }
}

/** Patch the line with `id`, creating one from `seed` if it is missing. */
export function patchLine<L extends Line>(lines: Line[], id: string, seed: Omit<L, "id"> | null, change: (line: L) => Partial<L>): Line[] {
  const index = lines.findIndex((line) => line.id === id);

  if (index === -1) {
    if (!seed) return lines;
    const created = { id, ...seed } as L;
    return [...lines, { ...created, ...change(created) }];
  }

  const copy = [...lines];
  const target = copy[index] as L;
  copy[index] = { ...target, ...change(target) };
  return copy;
}
