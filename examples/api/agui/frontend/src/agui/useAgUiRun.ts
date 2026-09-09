import type { RunAgentInput } from "@ag-ui/core";
import { useEffect, useReducer, useState } from "react";

import { EMPTY_VIEW, reduceEvent } from "./reduceEvent.ts";
import { sseEvents } from "./sse.ts";
import { persist, restore, forget } from "./storage.ts";
import type { Attachment, Line, OutboundPart } from "./types.ts";
import { uuid } from "./uuid.ts";

const saved = restore();

/**
 * Send each attachment under the part type its media type calls for.
 *
 * Audio and video are sent as `audio` and `video` even though Agent Kernel refuses both with a 400 —
 * that refusal is the point. The server decides on the part *type*, not the media type, so routing an
 * .mp3 through `document` would slip it past the guard and hand the model a generic file, which is the
 * misleading output the refusal exists to prevent.
 */
function toPart(attachment: Attachment): OutboundPart {
  const source = { type: "data" as const, value: attachment.data, mimeType: attachment.mimeType };
  if (attachment.mimeType.startsWith("image/")) return { type: "image", source };
  if (attachment.mimeType.startsWith("audio/")) return { type: "audio", source };
  if (attachment.mimeType.startsWith("video/")) return { type: "video", source };
  return { type: "document", source };
}

/**
 * One AG-UI conversation: the run envelope, the view folded out of the event stream, and the reload
 * persistence. Components below this only render — every state transition happens in `reduceEvent`.
 * Typing the request body as the SDK's `RunAgentInput` checks the outbound half of the protocol the
 * same way the reducer checks the inbound half.
 */
export function useAgUiRun(token: string) {
  const [threadId] = useState(() => saved.threadId || uuid());
  const [view, apply] = useReducer(reduceEvent, {
    ...EMPTY_VIEW,
    lines: saved.lines || [],
    state: saved.state ?? null,
  });
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);

  // Run boundaries and state changes only. `view.lines` is deliberately not a dependency: a response
  // is hundreds of events, and a message a reload interrupts mid-stream is legitimately incomplete.
  useEffect(() => {
    persist({ threadId, state: view.state, lines: view.lines });
  }, [running, view.state]);

  const local = (line: Line) => apply({ type: "__local", line });

  async function send(prompt: string, attachments: Attachment[] = []) {
    const id = uuid();
    setRunId(id);
    setRunning(true);
    local({ id: uuid(), kind: "user", text: prompt, ...(attachments.length ? { attachments: attachments.map((a) => a.name) } : {}) });

    // A plain string when there is nothing attached, typed parts when there is. Both are valid AG-UI
    // content; sending the string form for the common case keeps the request identical to before.
    const content: string | OutboundPart[] = attachments.length ? [{ type: "text", text: prompt }, ...attachments.map(toPart)] : prompt;

    const body: RunAgentInput = {
      threadId,
      runId: id,
      state: view.state,
      messages: [{ id: uuid(), role: "user", content }],
      tools: [],
      context: [{ description: "user's local time", value: new Date().toString() }],
      forwardedProps: { page: location.pathname, locale: navigator.language },
    };

    try {
      const response = await fetch("/agui", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        local({ id: uuid(), kind: "error", text: `${response.status} ${await response.text()}` });
        return;
      }

      for await (const event of sseEvents(response)) apply(event);
    } catch (e) {
      const reason = e instanceof Error ? e.message : String(e);
      local({ id: uuid(), kind: "error", text: `Could not reach the AG-UI endpoint: ${reason}` });
    } finally {
      setRunning(false);
    }
  }

  /** A new thread id means a new session, so the agent's memory and the shared state start clean. */
  function reset() {
    forget();
    location.reload();
  }

  /** Surface a client-side problem in the transcript — a file the browser could not read, say. */
  function report(message: string) {
    local({ id: uuid(), kind: "error", text: message });
  }

  return { threadId, runId, view, running, send, reset, report };
}
