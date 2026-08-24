/**
 * The types this client works in. Protocol events come from `@ag-ui/core`, AG-UI's own SDK, imported
 * as types only so neither it nor its `zod` dependency reaches the bundle. Everything else below is
 * this app's own, because the protocol deliberately does not specify how a client renders a
 * transcript or what an agent keeps in the shared state.
 */
import type {
  AGUIEvent,
  AudioInputContent,
  DocumentInputContent,
  ImageInputContent,
  TextInputContent,
  VideoInputContent,
} from "@ag-ui/core";

/** A file the user has staged in the composer but not yet sent. `data` is bare base64, no data: prefix. */
export type Attachment = {
  name: string;
  mimeType: string;
  data: string;
};

/**
 * One part of a multimodal user message. AG-UI models a message's content as either a plain string or
 * a list of typed parts. Audio and video are included even though Agent Kernel refuses them: sending
 * them under their own type is what produces that refusal, where mapping them onto `document` would
 * smuggle them through as generic files.
 */
export type OutboundPart =
  | TextInputContent
  | ImageInputContent
  | AudioInputContent
  | VideoInputContent
  | DocumentInputContent;

/** A transcript entry. Two shapes because a tool call is not text; `kind` is the discriminant. */
export type TextLine = {
  id: string;
  kind: "user" | "assistant" | "thinking" | "error";
  text: string;
  /** Names of the files sent with this turn. Only ever set on a `user` line. */
  attachments?: string[];
};

export type ToolLine = {
  id: string;
  kind: "tool";
  name: string;
  args: string;
  result: string | null;
  open: boolean;
};

export type Line = TextLine | ToolLine;

/** What the agent is doing right now, or `null` when it is idle. */
export type Status = {
  what: string;
  detail?: string | undefined;
};

/** A line the browser authored: the user's own turn, or a transport error. */
export type LocalAction = {
  type: "__local";
  line: Line;
};

export type AgUiAction = AGUIEvent | LocalAction;

/**
 * The shared state as this demo's agent writes it. AG-UI leaves the shape to the app — its own
 * `StateSchema` is `z.any()` — so a snapshot is asserted to be this, never checked. Hence every field
 * is optional and consumers read defensively.
 */
export type Task = {
  title?: string;
  done?: boolean;
};

export type DemoState = {
  tasks?: Task[];
};

/** The view folded out of the event stream — the whole of what is on screen. */
export type View = {
  lines: Line[];
  status: Status | null;
  state: DemoState | null;
};

/** The subset of the view that survives a reload. */
export type Persisted = {
  threadId?: string;
  lines?: Line[];
  state?: DemoState | null;
};
