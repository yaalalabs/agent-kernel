import type { AgUiAction, DemoState, Line, Status, TextLine, ToolLine, View } from "./types.ts";
import { uuid } from "./uuid.ts";

/**
 * The AG-UI event stream folded into the view: one branch per protocol event, correlated by the ids
 * the events carry. Everything on screen comes out of here and nothing else. An unrecognised event
 * returns the view unchanged, which is how a client stays forward compatible with a pre-1.0 protocol —
 * so `default` is a feature, not a missing exhaustiveness check.
 */
export const EMPTY_VIEW: View = { lines: [], status: null, state: null };

const busy = (what: string, detail?: string): Status => ({ what, detail });

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
      // The event carries only the id, so the tool name has to come from the call already held.
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
      return { ...view, state: event.snapshot as DemoState }; // asserted, not validated

    default:
      return view;
  }
}

/**
 * Patch the line carrying `id`, creating one from `seed` when it is absent — which is what makes a
 * missing `*_START` event survivable rather than a silently dropped delta. `L` is the shape the caller
 * expects to find, and correlation ids are minted per kind, so asserting it once here keeps every
 * branch above free of casts.
 */
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
