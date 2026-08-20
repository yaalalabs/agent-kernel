import { useState } from "react";

import type { TextLine } from "./agui/types.ts";
import { useAgUiRun } from "./agui/useAgUiRun.ts";
import Composer from "./components/Composer.tsx";
import Sidebar from "./components/Sidebar.tsx";
import StatusStrip from "./components/StatusStrip.tsx";
import Transcript from "./components/Transcript.tsx";

const FILE_ORIGIN_HINT: TextLine = {
  id: "file-origin",
  kind: "error",
  text:
    "Open this page from the running app — start it with `python app.py`, then visit " +
    "http://localhost:8000. Served from a file:// URL there is no server to send runs to.",
};

/** The layout and the page header. On a file:// origin there is no server to POST to, so say so up front. */
export default function App() {
  const [token, setToken] = useState("demo-token");
  const { threadId, runId, view, running, send, reset } = useAgUiRun(token);

  const offline = location.protocol === "file:";
  const lines = offline ? [FILE_ORIGIN_HINT, ...view.lines] : view.lines;

  return (
    <>
      <header>
        <h1>Task planner</h1>
        <p>An Agent Kernel agent over AG-UI. Ask for a task — the list on the right is state the agent writes and the browser echoes back.</p>
      </header>
      <main>
        <Transcript lines={lines} />
        <StatusStrip status={view.status} />
        <Composer onSend={send} disabled={running || offline} />
      </main>
      <Sidebar state={view.state} onReset={reset} token={token} onTokenChange={setToken} threadId={threadId} runId={runId} />
    </>
  );
}
