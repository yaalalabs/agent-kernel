import { useRef, useState } from "react";

import { runAgent, uuid } from "./agui/run.ts";
import type { Line, Verdict } from "./agui/types.ts";
import { Approval } from "./components/Approval.tsx";

/**
 * One conversation with an agent that stops for a person.
 *
 * The transcript is a flat list so a pause renders in order with everything else — it is a turn in
 * the conversation, not a modal bolted on top.
 */
export default function App() {
  const [agent, setAgent] = useState("support");
  const [lines, setLines] = useState<Line[]>([]);
  const [running, setRunning] = useState(false);
  const [prompt, setPrompt] = useState("");
  const threadId = useRef(uuid());
  const messages = useRef<{ id: string; role: "user" | "assistant"; content: string }[]>([]);

  const emit = (line: Line) => setLines((current) => [...current, line]);
  const patch = (id: string, text: string) =>
    setLines((current) => current.map((line) => (line.id === id && line.kind === "agent" ? { ...line, text } : line)));

  async function run(args: { prompt?: string; resume?: { interruptId: string; verdict: Verdict }[] }) {
    setRunning(true);
    try {
      await runAgent({ agent, threadId: threadId.current, messages: messages.current, ...args }, emit, patch);
    } catch (error) {
      emit({ kind: "error", id: uuid(), text: String(error) });
    } finally {
      setRunning(false);
    }
  }

  function send(event: React.FormEvent) {
    event.preventDefault();
    const text = prompt.trim();
    if (!text || running) return;
    setPrompt("");
    messages.current.push({ id: uuid(), role: "user", content: text });
    emit({ kind: "user", id: uuid(), text });
    void run({ prompt: text });
  }

  function decide(lineId: string, interruptId: string, verdict: Verdict, settled: string) {
    setLines((current) => current.map((line) => (line.id === lineId && line.kind === "pause" ? { ...line, settled } : line)));
    void run({ resume: [{ interruptId, verdict }] });
  }

  return (
    <>
      <main>
        <h1>Approval console</h1>
        <div className="agents">
          {[
            { id: "support", label: "support · OpenAI", hint: "approve or deny a gated tool" },
            { id: "planner", label: "planner · LangGraph", hint: "choose an option, then type an answer" },
          ].map((option) => (
            <button
              key={option.id}
              className={option.id === agent ? "pick on" : "pick"}
              onClick={() => setAgent(option.id)}
              title={option.hint}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="sub">
          {agent === "support"
            ? "Ask for a refund on ORD-1001 or ORD-1002. Looking an order up runs freely; issuing the refund stops here and waits for you."
            : "Ask it to plan a refund. It asks which method to use, then whether you want anything said to the customer."}
        </p>

        {lines.map((line) => {
          switch (line.kind) {
            case "user":
              return (
                <div key={line.id} className="msg user">
                  {line.text}
                </div>
              );
            case "agent":
              return (
                <div key={line.id} className="msg agent">
                  {line.text}
                </div>
              );
            case "tool":
              return (
                <div key={line.id} className="tool">
                  ↳ {line.name}
                </div>
              );
            case "error":
              return (
                <div key={line.id} className="msg error">
                  {line.text}
                </div>
              );
            case "pause":
              return <Approval key={line.id} lineId={line.id} interrupt={line.interrupt} settled={line.settled} onDecide={decide} />;
          }
        })}
      </main>

      <form onSubmit={send}>
        <input
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Please refund order ORD-1001."
          autoComplete="off"
        />
        <button type="submit" disabled={running}>
          Send
        </button>
      </form>
    </>
  );
}
