import assert from "node:assert/strict";
import test from "node:test";

import { EMPTY_VIEW, reduceEvent } from "./reduceEvent.ts";
import { fetchThreadMessages, fetchThreads, HttpError, toLines, type ThreadMessage } from "./threads.ts";

const message = (overrides: Partial<ThreadMessage>): ThreadMessage => ({ message_id: "m", role: "user", content: "", ...overrides });

function stubFetch(pages: Record<string, unknown>, calls: { url: string; auth: string | null }[] = []) {
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url, auth: new Headers(init?.headers).get("Authorization") });
    const body = pages[url];
    return body === undefined ? new Response("not found", { status: 404 }) : Response.json(body);
  }) as typeof fetch;
  return calls;
}

test("text messages become user and assistant lines", () => {
  const lines = toLines([message({ message_id: "1", content: "hello" }), message({ message_id: "2", role: "assistant", content: "hi" })]);
  assert.deepEqual(lines, [
    { id: "1", kind: "user", text: "hello" },
    { id: "2", kind: "assistant", text: "hi" },
  ]);
});

test("a payload such as a pause is shown as its JSON", () => {
  const [line] = toLines([message({ role: "assistant", content: { run_id: "r1" }, media_type: "application/json" })]);
  assert.equal(line?.kind === "tool" ? null : line?.text, JSON.stringify({ run_id: "r1" }, null, 2));
});

test("attachment names carry over, with a placeholder for an unnamed one", () => {
  const [line] = toLines([message({ content: "look", attachments: [{ name: "shot.png" }, { name: null }] })]);
  assert.deepEqual(line?.kind === "tool" ? null : line?.attachments, ["shot.png", "attachment"]);
});

test("a thread's messages are read across every page, with the token", async () => {
  const calls = stubFetch({
    "/api/v1/threads/t%201?limit=200": { messages: [message({ message_id: "1" })], next_cursor: "c 2" },
    "/api/v1/threads/t%201?limit=200&cursor=c%202": { messages: [message({ message_id: "2" })], next_cursor: null },
  });

  const messages = await fetchThreadMessages("tok", "t 1");

  assert.deepEqual(
    messages.map((m) => m.message_id),
    ["1", "2"],
  );
  assert.deepEqual(
    calls.map((c) => c.auth),
    ["Bearer tok", "Bearer tok"],
  );
});

test("the thread list is read across every page", async () => {
  stubFetch({
    "/api/v1/threads?limit=200": { threads: [{ session_id: "a", name: "A", updated_at: "" }], next_cursor: "c2" },
    "/api/v1/threads?limit=200&cursor=c2": { threads: [{ session_id: "b", name: "B", updated_at: "" }], next_cursor: null },
  });
  assert.deepEqual(
    (await fetchThreads("tok")).map((t) => t.session_id),
    ["a", "b"],
  );
});

test("no thread routes reads as an empty history, not an error", async () => {
  stubFetch({});
  assert.deepEqual(await fetchThreads("tok"), []);
});

test("any other failed listing rejects with the status, so the sidebar can say why", async () => {
  globalThis.fetch = (async () => new Response("bad token", { status: 401 })) as typeof fetch;
  await assert.rejects(() => fetchThreads("tok"), (e: unknown) => e instanceof HttpError && e.status === 401 && /bad token/.test(e.message));
});

test("loading a thread replaces the transcript and clears the run state", () => {
  const busy = { ...EMPTY_VIEW, lines: [{ id: "old", kind: "user" as const, text: "old" }], status: { what: "Working" } };
  const view = reduceEvent(busy, { type: "__load", lines: [{ id: "1", kind: "assistant", text: "past" }] });
  assert.deepEqual(view, { ...EMPTY_VIEW, lines: [{ id: "1", kind: "assistant", text: "past" }] });
});
