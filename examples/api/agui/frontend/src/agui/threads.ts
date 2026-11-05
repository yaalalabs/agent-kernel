import type { Line } from "./types.ts";

/** One row of `GET /api/v1/threads`. */
export type ThreadSummary = {
  session_id: string;
  name: string;
  updated_at: string;
};

/** One message of `GET /api/v1/threads/{id}`; `content` is an object when `media_type` is set. */
export type ThreadMessage = {
  message_id: string;
  role: "user" | "assistant";
  content: unknown;
  media_type?: string;
  attachments?: { name?: string | null }[];
};

type ThreadPage = { threads: ThreadSummary[]; next_cursor: string | null };
type MessagePage = { messages: ThreadMessage[]; next_cursor: string | null };

const PAGE_SIZE = 200;

export class HttpError extends Error {
  readonly status: number;

  constructor(status: number, body: string) {
    super(`${status} ${body}`);
    this.status = status;
  }
}

async function getJson<T>(url: string, token: string): Promise<T> {
  const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new HttpError(response.status, await response.text());
  return (await response.json()) as T;
}

/**
 * The caller's threads, most recent first, following the cursor across pages. The server scopes the
 * list to the token's user. A 404 means the app records no threads (no `thread` block, or the read
 * routes are not mounted), which is an empty history rather than an error.
 */
export async function fetchThreads(token: string): Promise<ThreadSummary[]> {
  const threads: ThreadSummary[] = [];
  let cursor: string | null = null;
  try {
    do {
      const query = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
      const page: ThreadPage = await getJson<ThreadPage>(`/api/v1/threads?limit=${PAGE_SIZE}${query}`, token);
      threads.push(...page.threads);
      cursor = page.next_cursor;
    } while (cursor);
  } catch (e) {
    if (e instanceof HttpError && e.status === 404) return [];
    throw e;
  }
  return threads;
}

/** Every message of one thread, following the cursor across pages. */
export async function fetchThreadMessages(token: string, threadId: string): Promise<ThreadMessage[]> {
  const messages: ThreadMessage[] = [];
  let cursor: string | null = null;
  do {
    const query = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
    const page: MessagePage = await getJson<MessagePage>(`/api/v1/threads/${encodeURIComponent(threadId)}?limit=${PAGE_SIZE}${query}`, token);
    messages.push(...page.messages);
    cursor = page.next_cursor;
  } while (cursor);
  return messages;
}

/** Recorded messages as transcript lines. A payload (a pause, a decision) is shown as its JSON. */
export function toLines(messages: ThreadMessage[]): Line[] {
  return messages.map((message) => {
    const text = typeof message.content === "string" ? message.content : JSON.stringify(message.content, null, 2);
    const attachments = (message.attachments ?? []).map((a) => a.name ?? "attachment");
    return {
      id: message.message_id,
      kind: message.role,
      text,
      ...(attachments.length ? { attachments } : {}),
    };
  });
}
