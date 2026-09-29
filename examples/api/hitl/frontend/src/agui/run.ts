import type { RunAgentInput } from "@ag-ui/core";

import { sseEvents } from "./sse.ts";
import type { Line, Verdict } from "./types.ts";

const TOKEN = "demo-token";

export const uuid = () => crypto.randomUUID();

/** A message as AG-UI replays it: the client owns the history and sends it with every run. */
type Turn = { id: string; role: "user" | "assistant"; content: string };

/**
 * Run the agent once and fold its event stream into transcript lines.
 *
 * `resume` carries the human's decisions when this turn answers a pause, and is omitted otherwise.
 * Typing the body as the SDK's `RunAgentInput` checks the outbound half of the protocol the same way
 * the event types check the inbound half.
 */
export async function runAgent(
  args: { agent: string; threadId: string; messages: Turn[]; prompt?: string; resume?: { interruptId: string; verdict: Verdict }[] },
  emit: (line: Line) => void,
  patch: (id: string, text: string) => void,
): Promise<void> {
  const body: RunAgentInput = {
    threadId: args.threadId,
    runId: uuid(),
    state: null,
    messages: args.messages,
    tools: [],
    context: [],
    forwardedProps: null,
    ...(args.resume ? { resume: args.resume.map((r) => ({ interruptId: r.interruptId, ...r.verdict })) } : {}),
  };

  const response = await fetch(`/agui/${args.agent}`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${TOKEN}` },
    body: JSON.stringify(body),
  });

  let agentLineId: string | null = null;
  let text = "";

  for await (const event of sseEvents(response)) {
    switch (event.type) {
      case "TEXT_MESSAGE_CONTENT":
        if (agentLineId === null) {
          agentLineId = uuid();
          emit({ kind: "agent", id: agentLineId, text: "" });
        }
        text += event.delta;
        patch(agentLineId, text);
        break;

      case "TOOL_CALL_START":
        emit({ kind: "tool", id: uuid(), name: event.toolCallName });
        break;

      case "RUN_FINISHED":
        // The third terminal shape: the run ended because it needs a person. A pause is an outcome
        // of the run, not an error and not something that happened during it.
        if (event.outcome?.type === "interrupt") {
          for (const interrupt of event.outcome.interrupts) emit({ kind: "pause", id: uuid(), interrupt });
        } else if (text) {
          args.messages.push({ id: uuid(), role: "assistant", content: text });
        }
        break;

      case "RUN_ERROR":
        emit({ kind: "error", id: uuid(), text: event.message });
        break;
    }
  }
}
