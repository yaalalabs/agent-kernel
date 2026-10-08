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
 *
 * Returns whether the run succeeded. The caller needs to know, because Agent Kernel keeps a paused
 * record when a resume fails so the same decision can be sent again — a UI that retires the question
 * regardless would throw that away.
 */
export async function runAgent(
  args: { agent: string; threadId: string; messages: Turn[]; prompt?: string; resume?: { interruptId: string; verdict: Verdict }[] },
  emit: (line: Line) => void,
  patch: (id: string, text: string) => void,
): Promise<boolean> {
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
    headers: { "content-type": "application/json", accept: "text/event-stream", authorization: `Bearer ${TOKEN}` },
    body: JSON.stringify(body),
  });

  // A rejected request answers with JSON, not SSE, so the parser below would find no events and the
  // run would end looking like an empty success. AG-UI has no anonymous mode, which makes a bad
  // token the likeliest way to land here.
  if (!response.ok) {
    emit({ kind: "error", id: uuid(), text: `${response.status} ${await response.text()}` });
    return false;
  }

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
          // The agent is carried on the line because a pause is answered by whoever asked, which is
          // not necessarily whoever is selected by the time a human gets to it.
          for (const interrupt of event.outcome.interrupts) emit({ kind: "pause", id: uuid(), interrupt, agent: args.agent });
        } else if (text) {
          args.messages.push({ id: uuid(), role: "assistant", content: text });
        }
        // Success is this event arriving, not the body ending: a dropped or truncated stream leaves
        // the loop too, and reporting that as success would retire an approval the server still holds.
        return true;

      case "RUN_ERROR":
        emit({ kind: "error", id: uuid(), text: event.message });
        return false;
    }
  }

  emit({ kind: "error", id: uuid(), text: "The run ended without finishing — the connection dropped partway." });
  return false;
}
