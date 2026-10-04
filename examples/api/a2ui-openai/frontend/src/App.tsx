/**
 * A chat box that renders a reply as prose or as an interface, decided by one field.
 *
 * The branch in `turnFor` is the whole client side of this feature: if the response carries
 * `media_type`, `result` is an object and gets rendered; otherwise it is the string it has always
 * been. A client that never opted in sees only the second case.
 */

import { useState } from "react";
import type { JSX } from "react";

import { Surface } from "./a2ui/Surface.tsx";
import { A2UI_MEDIA_TYPE } from "./a2ui/types.ts";
import type { A2UIMessage, ChatResponse } from "./a2ui/types.ts";

const SESSION_ID = crypto.randomUUID();

type Turn =
  | { kind: "you"; text: string }
  | { kind: "prose"; text: string }
  | { kind: "surface"; message: A2UIMessage; submitted: boolean }
  | { kind: "error"; text: string };

function turnFor(body: ChatResponse): Turn {
  if (body.media_type === A2UI_MEDIA_TYPE && typeof body.result === "object") {
    return { kind: "surface", message: body.result, submitted: false };
  }
  return { kind: "prose", text: String(body.result) };
}

export default function App(): JSX.Element {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(prompt: string) {
    if (!prompt.trim() || busy) return;
    setTurns((previous) => [...previous, { kind: "you", text: prompt }]);
    setDraft("");
    setBusy(true);
    try {
      const response = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt, session_id: SESSION_ID, agent: "expenses" }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body: ChatResponse = await response.json();
      setTurns((previous) => [...previous, turnFor(body)]);
    } catch (error) {
      setTurns((previous) => [...previous, { kind: "error", text: String(error) }]);
    } finally {
      setBusy(false);
    }
  }

  // A2UI is render-only here: a submitted form becomes an ordinary next message, so the round trip
  // uses the chat route that already exists rather than a callback path.
  //
  // The surface is then marked submitted, which disables its inputs. Without that the form stays
  // live after it has been sent, and a second click silently files the claim twice.
  function onSubmitSurface(event: React.FormEvent<HTMLFormElement>, index: number) {
    event.preventDefault();
    const entries = [...new FormData(event.currentTarget).entries()]
      .filter(([, value]) => String(value).trim() !== "")
      .map(([name, value]) => `${name}: ${value}`);
    setTurns((previous) =>
      previous.map((turn, at) => (at === index && turn.kind === "surface" ? { ...turn, submitted: true } : turn)),
    );
    void send(entries.length ? entries.join(", ") : "(submitted an empty form)");
  }

  return (
    <main>
      <h1>Expenses</h1>
      <p className="hint">
        Ask something ordinary and you get prose. Ask to file an expense and you get a form — same
        endpoint, same field, decided by <code>media_type</code>.
      </p>

      <ol className="transcript">
        {turns.map((turn, index) => (
          <li key={index} className={turn.kind}>
            {turn.kind === "surface" ? (
              <form onSubmit={(event) => onSubmitSurface(event, index)}>
                <fieldset disabled={turn.submitted}>
                  <Surface message={turn.message} />
                </fieldset>
                {turn.submitted && <p className="sent">Sent — see the reply below.</p>}
              </form>
            ) : (
              turn.text
            )}
          </li>
        ))}
        {busy && <li className="prose pending">…</li>}
      </ol>

      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="I need to file an expense"
          aria-label="Message"
        />
        <button type="submit" disabled={busy}>
          Send
        </button>
      </form>
    </main>
  );
}
