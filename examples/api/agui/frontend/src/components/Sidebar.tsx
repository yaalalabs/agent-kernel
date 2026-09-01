import type { DemoState } from "../agui/types.ts";

type Props = {
  state: DemoState | null;
  onReset: () => void;
  token: string;
  onTokenChange: (token: string) => void;
  threadId: string;
  runId: string | null;
};

/** Shared state, Bearer token, and run envelope. */
export default function Sidebar({ state, onReset, token, onTokenChange, threadId, runId }: Props) {
  const tasks = state?.tasks ?? [];

  return (
    <aside>
      <div>
        <h2>Shared state</h2>

        {tasks.length === 0 ? (
          <div className="muted">— nothing yet —</div>
        ) : (
          tasks.map((task, index) => (
            <div className={task.done ? "task done" : "task"} key={index}>
              <span>{task.done ? "✓" : "○"}</span>
              <span>{task.title}</span>
            </div>
          ))
        )}

        <button type="button" onClick={onReset}>
          New conversation
        </button>
      </div>

      <div>
        <h2>Bearer token</h2>
        <label htmlFor="token">Sent on every run</label>
        <input id="token" type="text" value={token} onChange={(event) => onTokenChange(event.target.value)} />
      </div>

      <div>
        <h2>Run envelope</h2>
        <div className="trace">
          thread {threadId}
          <br />
          run {runId || "—"}
        </div>
      </div>
    </aside>
  );
}
