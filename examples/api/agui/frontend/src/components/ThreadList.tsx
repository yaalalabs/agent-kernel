import type { ThreadSummary } from "../agui/threads.ts";

type Props = {
  threads: ThreadSummary[];
  error: string | null;
  currentId: string;
  busy: boolean;
  onOpen: (threadId: string) => void;
};

/** Past conversations; opening one continues its thread. */
export default function ThreadList({ threads, error, currentId, busy, onOpen }: Props) {
  return (
    <nav>
      <h2>Conversations</h2>
      {error ? (
        <div className="muted">History unavailable: {error}</div>
      ) : threads.length === 0 ? (
        <div className="muted">— none recorded yet —</div>
      ) : (
        <ul className="threads">
          {threads.map((thread) => (
            <li key={thread.session_id}>
              <button
                type="button"
                className={thread.session_id === currentId ? "current" : ""}
                disabled={busy || thread.session_id === currentId}
                onClick={() => onOpen(thread.session_id)}
              >
                {thread.name || thread.session_id}
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}
