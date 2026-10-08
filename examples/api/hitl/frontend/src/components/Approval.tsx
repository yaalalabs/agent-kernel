import type { Interrupt } from "@ag-ui/core";
import { useState } from "react";

import type { Question, Verdict } from "../agui/types.ts";

/**
 * The card a human acts on — the whole point of the demo.
 *
 * It renders three shapes, and which one it gets is decided by the framework the agent runs on:
 *
 * - **approve / deny** (`reason: "tool_call"`) — a gated tool. The only thing the OpenAI SDK can
 *   ask, because it records an approval as a boolean and `RunState.approve()` takes no value.
 * - **a choice** (`reason: "input_required"` with `options`) — LangGraph's `interrupt()` returns
 *   whatever the resume supplies, so the chosen option becomes the node's return value.
 * - **free text** (`reason: "input_required"` with no options) — the same channel, typed instead.
 *
 * The tool name and arguments come from `metadata` rather than a field of their own: the protocol
 * has none, and `response_schema` means a JSON Schema, which is not what Agent Kernel carries.
 */
export function Approval({
  lineId,
  interrupt,
  settled,
  busy,
  onDecide,
}: {
  lineId: string;
  interrupt: Interrupt;
  settled?: string;
  /** A run is in flight. The in-flight latch in App already drops a second decision; this is what
   *  tells the human why, instead of letting a click look accepted and do nothing. */
  busy?: boolean;
  onDecide: (lineId: string, interruptId: string, verdict: Verdict, settled: string) => void;
}) {
  const [text, setText] = useState("");
  const metadata = (interrupt.metadata ?? {}) as { tool_name?: string; arguments?: string; payload?: Question };
  const question = metadata.payload ?? {};
  const asking = interrupt.reason === "input_required";

  let args = metadata.arguments;
  try {
    if (args) args = JSON.stringify(JSON.parse(args), null, 2);
  } catch {
    /* not JSON: show it as sent */
  }

  const decide = (verdict: Verdict, note: string) => onDecide(lineId, interrupt.id, verdict, note);

  return (
    <div className="approval">
      <header>{asking ? "Needs your answer" : "Needs your approval"}</header>
      <div className="body">
        <div className="what">{question.question ?? (metadata.tool_name ? `${metadata.tool_name}(…)` : interrupt.reason)}</div>
        {args && <pre>{args}</pre>}
        {!asking && (
          <div className="why">{interrupt.message ?? "The agent stopped before running this. Nothing has happened yet."}</div>
        )}
      </div>

      {settled ? (
        <div className="settled">{settled}</div>
      ) : question.options ? (
        <div className="actions">
          {question.options.map((option) => (
            <button key={option} disabled={busy} onClick={() => decide({ status: "resolved", payload: option }, `Answered: ${option}`)}>
              {option}
            </button>
          ))}
        </div>
      ) : asking ? (
        <div className="actions">
          <input
            className="answer"
            disabled={busy}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && decide({ status: "resolved", payload: text }, `Answered: ${text || "(nothing)"}`)}
            placeholder="Type your answer, or leave blank"
          />
          <button className="ok" disabled={busy} onClick={() => decide({ status: "resolved", payload: text }, `Answered: ${text || "(nothing)"}`)}>
            Send
          </button>
        </div>
      ) : (
        <div className="actions">
          <button className="ok" disabled={busy} onClick={() => decide({ status: "resolved", payload: true }, "Approved — the tool ran.")}>
            Approve
          </button>
          <button className="no" disabled={busy} onClick={() => decide({ status: "resolved", payload: false }, "Denied — the tool did not run.")}>
            Deny
          </button>
          <button disabled={busy} onClick={() => decide({ status: "cancelled" }, "Cancelled — nobody decided, and the model is told so.")}>Cancel</button>
        </div>
      )}
    </div>
  );
}
