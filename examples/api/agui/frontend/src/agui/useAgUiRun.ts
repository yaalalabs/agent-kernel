import type { RunAgentInput } from "@ag-ui/core";
import { useEffect, useReducer, useRef, useState } from "react";

import { EMPTY_VIEW, reduceEvent } from "./reduceEvent.ts";
import { sseEvents } from "./sse.ts";
import { persist, restore, forget } from "./storage.ts";
import { fetchThreadMessages, toLines } from "./threads.ts";
import type { Attachment, Line, OutboundPart } from "./types.ts";
import { uuid } from "./uuid.ts";

const saved = restore();

/** Send each attachment under the part type its media type calls for. */
function toPart(attachment: Attachment): OutboundPart {
  const source = { type: "data" as const, value: attachment.data, mimeType: attachment.mimeType };
  if (attachment.mimeType.startsWith("image/")) return { type: "image", source };
  if (attachment.mimeType.startsWith("audio/")) return { type: "audio", source };
  if (attachment.mimeType.startsWith("video/")) return { type: "video", source };
  return { type: "document", source };
}

/** One AG-UI conversation: the run, the view folded from its events, and reload persistence. */
export function useAgUiRun(token: string) {
  const [threadId, setThreadId] = useState(() => saved.threadId || uuid());
  const [view, apply] = useReducer(reduceEvent, {
    ...EMPTY_VIEW,
    lines: saved.lines || [],
    state: saved.state ?? null,
  });
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const openTicket = useRef(0);

  // Not keyed on `view.lines`: a response is hundreds of events.
  useEffect(() => {
    persist({ threadId, state: view.state, lines: view.lines });
  }, [running, view.state, threadId]);

  const local = (line: Line) => apply({ type: "__local", line });

  async function send(prompt: string, attachments: Attachment[] = []) {
    if (opening) return;
    const id = uuid();
    setRunId(id);
    setRunning(true);
    local({ id: uuid(), kind: "user", text: prompt, ...(attachments.length ? { attachments: attachments.map((a) => a.name) } : {}) });

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

  /** Continue a recorded conversation; a superseded load is dropped. */
  async function open(id: string) {
    const ticket = ++openTicket.current;
    setOpening(true);
    try {
      const lines = toLines(await fetchThreadMessages(token, id));
      if (ticket !== openTicket.current) return;
      apply({ type: "__load", lines });
      setThreadId(id);
      setRunId(null);
    } catch (e) {
      if (ticket === openTicket.current) report(`Could not load the conversation: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      if (ticket === openTicket.current) setOpening(false);
    }
  }

  /** Show a client-side error in the transcript. */
  function report(message: string) {
    local({ id: uuid(), kind: "error", text: message });
  }

  return { threadId, runId, view, running, opening, send, reset, report, open };
}
