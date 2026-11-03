/**
 * The slice of A2UI this demo understands.
 *
 * Deliberately not the whole protocol. A2UI also defines `updateComponents`, `updateDataModel`,
 * `deleteSurface` and a data-binding system; this example only ever receives a single
 * `createSurface` carrying its components inline, which is what render-only support needs.
 */

/** One component in the flat list. `id` is how a parent refers to it — there is no nesting. */
export interface A2UIComponent {
  id: string;
  /** A single-key object: the key is the component name, the value its properties. */
  component: Record<string, Record<string, unknown>>;
}

export interface A2UIMessage {
  version?: string;
  createSurface?: {
    surfaceId?: string;
    components?: A2UIComponent[];
  };
}

/** What `POST /api/v1/chat` returns. `result` is a string unless `media_type` is present. */
export interface ChatResponse {
  result: string | A2UIMessage;
  media_type?: string;
  session_id: string;
}

/**
 * One recorded message from `GET /api/v1/threads/{session_id}`.
 *
 * Note the shape: `content` and `media_type` are the same pair `result` and `media_type` are on a
 * live reply, which is what lets `turnFor` serve both without a second code path.
 */
export interface ThreadMessage {
  role: "user" | "assistant";
  content: string | A2UIMessage;
  media_type?: string;
}

/** A row in the thread list. `session_id` is the thread id — threads have no id of their own. */
export interface ThreadSummary {
  session_id: string;
  name: string;
  updated_at: string;
}

/** Both read routes page at 50 and hand back a cursor for the next page, or null on the last. */
export interface ThreadListResponse {
  threads: ThreadSummary[];
  next_cursor?: string | null;
}

export interface ThreadResponse {
  session_id: string;
  messages: ThreadMessage[];
  next_cursor?: string | null;
}

export const A2UI_MEDIA_TYPE = "application/a2ui+json";
