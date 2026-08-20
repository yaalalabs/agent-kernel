import type { DemoState } from "../agui/types.ts";

type Props = {
  state: DemoState | null;
  onReset: () => void;
  token: string;
  onTokenChange: (token: string) => void;
  threadId: string;
  runId: string | null;
};

/**
 * The right-hand column: the shared state, the Bearer token, and the run envelope.
 *
 * The state panel is the round trip made visible — the agent writes with `update_agui_state`, the
 * server streams a snapshot, and the next run echoes it back. Neither side owns the list. Editing the
 * token is the quickest way to see the 401 path, since these routes have no anonymous mode.
 */
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
