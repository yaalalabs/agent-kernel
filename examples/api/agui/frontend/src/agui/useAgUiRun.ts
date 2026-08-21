import type { RunAgentInput } from "@ag-ui/core";
import { useEffect, useReducer, useState } from "react";

import { EMPTY_VIEW, reduceEvent } from "./reduceEvent.ts";
import { sseEvents } from "./sse.ts";
import { persist, restore, forget } from "./storage.ts";
import type { Line } from "./types.ts";
import { uuid } from "./uuid.ts";

const saved = restore();

/** One AG-UI conversation: send a turn, fold the event stream, persist across reload. */
export function useAgUiRun(token: string) {
  const [threadId] = useState(() => saved.threadId || uuid());
  const [view, apply] = useReducer(reduceEvent, {
    ...EMPTY_VIEW,
    lines: saved.lines || [],
    state: saved.state ?? null,
  });
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);

  useEffect(() => {
    persist({ threadId, state: view.state, lines: view.lines });
  }, [running, view.state]);

  const local = (line: Line) => apply({ type: "__local", line });

  async function send(prompt: string) {
    const id = uuid();
    setRunId(id);
    setRunning(true);
    local({ id: uuid(), kind: "user", text: prompt });

    const body: RunAgentInput = {
      threadId,
      runId: id,
      state: view.state,
      messages: [{ id: uuid(), role: "user", content: prompt }],
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

  function reset() {
    forget();
    location.reload();
  }

  return { threadId, runId, view, running, send, reset };
}
