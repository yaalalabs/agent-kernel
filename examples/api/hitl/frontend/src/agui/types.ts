import type { Interrupt } from "@ag-ui/core";

/** One line in the transcript. A pause is a line too, so it renders in order with the rest.
 *
 * A pause line carries its own `id`, not the interrupt's: LangGraph re-runs an interrupting node
 * from the top, so a second question inside the same node arrives under the **same interrupt id**.
 * Keying the line by that would collide, and settling one would settle both.
 *
 * It also carries the `agent` that asked. One session can hold pauses from several agents at once —
 * which is the point, since each framework's replacement is scoped to its own — so the answer must go
 * back to whoever asked rather than to whichever agent happens to be selected when a human replies.
 */
export type Line =
  | { kind: "user"; id: string; text: string }
  | { kind: "agent"; id: string; text: string }
  | { kind: "tool"; id: string; name: string }
  | { kind: "error"; id: string; text: string }
  | { kind: "pause"; id: string; interrupt: Interrupt; agent: string; settled?: string };

/**
 * What the client sends back for one interrupt.
 *
 * The protocol carries two statuses where Agent Kernel carries three. `cancelled` is its own status,
 * so "nobody decided" never reaches the model as a refusal; approve and deny are both `resolved`,
 * told apart by a boolean payload — which is simply the answer to "may I?".
 *
 * There is deliberately nowhere to put *why* it was refused. AG-UI has no field for it, and inventing
 * one inside `payload` would contradict the SDK, which reserves that for "the answer the agent asked
 * for". A client that needs the human's words uses the REST surface, where `message` is its own field.
 */
export type Verdict = { status: "resolved"; payload: boolean | string } | { status: "cancelled" };

/** The shape a node passed to `interrupt()`, as Agent Kernel carries it in `Interrupt.metadata`. */
export type Question = { question?: string; options?: string[] };
