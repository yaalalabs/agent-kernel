/**
 * A chat box that renders a reply as prose or as an interface, decided by one field.
 *
 * The branch in `turnFor` is the whole client side of this feature: if the response carries
 * `media_type`, `result` is an object and gets rendered; otherwise it is the string it has always
 * been. A client that never opted in sees only the second case.
 *
 * Thread history replays through that same branch: a recorded message carries the same pair, named
 * `content` rather than `result`.
 */

import { useCallback, useEffect, useState } from "react";
import type { JSX } from "react";

import { isInteractive } from "./a2ui/catalog.tsx";
import { Surface } from "./a2ui/Surface.tsx";
import { A2UI_MEDIA_TYPE } from "./a2ui/types.ts";
import type { A2UIMessage, ChatResponse, ThreadListResponse, ThreadMessage, ThreadResponse, ThreadSummary } from "./a2ui/types.ts";

/** Threads are scoped to a user. A real app resolves this from a token with an `Authoriser`. */
const USER_ID = "demo-user";

type Turn =
  | { kind: "you"; text: string }
  | { kind: "prose"; text: string }
  | { kind: "surface"; message: A2UIMessage; submitted: boolean }
  | { kind: "error"; text: string };

/**
 * Read every page of a cursor-paginated route, in order.
 *
 * Both thread routes cap a page at 50 and hand back `next_cursor`. Taking only the first page
 * hides the oldest conversations from the list, and — because messages come back oldest-first —
 * drops the *newest* turns from a transcript, which would leave an already-answered form looking
 * like the last thing that happened.
 */
async function fetchAll<Row, Body extends { next_cursor?: string | null }>(
  url: string,
  rows: (body: Body) => Row[],
): Promise<Row[]> {
  const all: Row[] = [];
  let cursor: string | null | undefined;
  do {
    const page = cursor ? `${url}${url.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(cursor)}` : url;
    const response = await fetch(page);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body: Body = await response.json();
    all.push(...rows(body));
    cursor = body.next_cursor;
  } while (cursor);
  return all;
}

function turnFor(value: string | A2UIMessage, mediaType: string | undefined, submitted = false): Turn {
  if (mediaType === A2UI_MEDIA_TYPE && typeof value === "object") {
    return { kind: "surface", message: value, submitted };
  }
  return { kind: "prose", text: String(value) };
}

/**
 * Replay a recorded thread as turns. A surface counts as submitted only when something followed
 * it, so an abandoned form can still be picked up and an answered one cannot be answered twice.
 */
function turnsFromThread(messages: ThreadMessage[]): Turn[] {
  return messages.map((message, index) =>
    message.role === "user"
      ? { kind: "you", text: String(message.content) }
      : turnFor(message.content, message.media_type, index < messages.length - 1),
  );
}

/**
 * Split `Cost centre: ENG-4, Amount: 250` into pairs, for display only — null when it does not
 * split cleanly. Nothing reads the result; a value the app needs comes back inside a payload.
 */
function submittedFields(message: string): [string, string][] | null {
  const pairs = message.split(", ").map((pair) => {
    const at = pair.indexOf(": ");
    return at === -1 ? null : ([pair.slice(0, at), pair.slice(at + 2)] as [string, string]);
  });
  return pairs.every((pair) => pair !== null) ? (pairs as [string, string][]) : null;
}

function ThreadRail(props: {
  threads: ThreadSummary[];
  currentId: string;
  busy: boolean;
  onOpen: (id: string) => void;
  onNew: () => void;
}): JSX.Element {
  return (
    <aside className="threads">
      <div className="threads-head">
        <h2>History</h2>
        <button type="button" onClick={props.onNew} disabled={props.busy}>
          New
        </button>
      </div>
      {props.threads.length === 0 ? (
        <p className="hint">Nothing yet — send a message.</p>
      ) : (
        <ul>
          {props.threads.map((thread) => (
            <li key={thread.session_id}>
              <button
                type="button"
                className={thread.session_id === props.currentId ? "current" : undefined}
                onClick={() => props.onOpen(thread.session_id)}
                disabled={props.busy}
              >
                {thread.name || thread.session_id.slice(0, 8)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

function SurfaceTurn({ turn, onSubmit }: { turn: Extract<Turn, { kind: "surface" }>; onSubmit: React.FormEventHandler<HTMLFormElement> }): JSX.Element {
  // A receipt is never used up: only a surface with inputs is spent by being sent.
  const spent = turn.submitted && isInteractive(turn.message);

  return (
    <form onSubmit={onSubmit}>
      <fieldset disabled={spent}>
        <Surface message={turn.message} />
      </fieldset>
      {spent && <p className="sent">Sent — see the reply below.</p>}
    </form>
  );
}

function Chips({ fields }: { fields: [string, string][] }): JSX.Element {
  return (
    <span className="chips">
      {fields.map(([name, value]) => (
        <span key={name} className="chip">
          {name} <strong>{value}</strong>
        </span>
      ))}
    </span>
  );
}

function TurnView(props: { turn: Turn; follows?: Turn["kind"]; onSubmit: React.FormEventHandler<HTMLFormElement> }): JSX.Element {
  const { turn, follows } = props;

  if (turn.kind === "surface") return <SurfaceTurn turn={turn} onSubmit={props.onSubmit} />;

  // A user message straight after a surface is that form coming back.
  const fields = turn.kind === "you" && follows === "surface" ? submittedFields(turn.text) : null;
  return fields ? <Chips fields={fields} /> : <>{turn.text}</>;
}

export default function App(): JSX.Element {
  // Annotated: `crypto.randomUUID()` infers a template-literal type a thread id off the wire fails.
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID());
  const [turns, setTurns] = useState<Turn[]>([]);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const refreshThreads = useCallback(async () => {
    try {
      setThreads(await fetchAll<ThreadSummary, ThreadListResponse>(`/api/v1/threads?user_id=${encodeURIComponent(USER_ID)}`, (body) => body.threads));
    } catch {
      // The rail is a convenience; a failed refresh leaves the last list rather than emptying it.
    }
  }, []);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  async function send(prompt: string) {
    if (!prompt.trim() || busy) return;
    setTurns((previous) => [...previous, { kind: "you", text: prompt }]);
    setDraft("");
    setBusy(true);
    try {
      const response = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt, session_id: sessionId, user_id: USER_ID, agent: "expenses" }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body: ChatResponse = await response.json();
      setTurns((previous) => [...previous, turnFor(body.result, body.media_type)]);
      void refreshThreads();
    } catch (error) {
      setTurns((previous) => [...previous, { kind: "error", text: String(error) }]);
    } finally {
      setBusy(false);
    }
  }

  /**
   * Sets the session id too, so the agent's own memory resumes — not just the transcript.
   *
   * Holds `busy` for the whole load. Left free, Send stays enabled while the pages arrive and a
   * reply can be appended to a transcript that is about to be replaced, landing it in the wrong
   * conversation.
   */
  async function openThread(id: string) {
    if (busy) return;
    setBusy(true);
    try {
      const messages = await fetchAll<ThreadMessage, ThreadResponse>(`/api/v1/threads/${encodeURIComponent(id)}`, (body) => body.messages);
      setSessionId(id);
      setTurns(turnsFromThread(messages));
    } catch (error) {
      setTurns((previous) => [...previous, { kind: "error", text: String(error) }]);
    } finally {
      setBusy(false);
    }
  }

  function newThread() {
    setSessionId(crypto.randomUUID());
    setTurns([]);
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
    <div className="layout">
      <ThreadRail threads={threads} currentId={sessionId} busy={busy} onOpen={(id) => void openThread(id)} onNew={newThread} />

      <main>
        <h1>Expenses</h1>
        <p className="hint">
          Ask something ordinary and you get prose. Ask to file an expense and you get a form — same
          endpoint, same field, decided by <code>media_type</code>. File one, then reopen the
          conversation from <strong>History</strong>: the form comes back as a form.
        </p>

        <ol className="transcript">
          {/* Keyed by session: the catalog's inputs are uncontrolled, so without the prefix React
              reuses the DOM between two threads of the same shape and carries typed values across. */}
          {turns.map((turn, index) => (
            <li key={`${sessionId}-${index}`} className={turn.kind}>
              <TurnView turn={turn} follows={turns[index - 1]?.kind} onSubmit={(event) => onSubmitSurface(event, index)} />
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
    </div>
  );
}
