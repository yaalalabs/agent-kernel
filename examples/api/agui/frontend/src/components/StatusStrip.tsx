import type { Status } from "../agui/types.ts";

/**
 * What the agent is doing right now, read off the run's boundary events rather than guessed from a
 * timer. Without those events a client can only show a spinner.
 */
export default function StatusStrip({ status }: { status: Status | null }) {
  return (
    <div className={status ? "status busy" : "status"}>
      <span className="dot" />
      {status ? (
        <>
          <span className="what">{status.what}</span>
          <span className="detail">{status.detail || ""}</span>
        </>
      ) : (
        <span className="muted">Idle</span>
      )}
    </div>
  );
}
