import type { AGUIEvent } from "@ag-ui/core";

/** Transcript, status, and shared-state shapes this client renders. */

export type TextLine = {
  id: string;
  kind: "user" | "assistant" | "thinking" | "error";
  text: string;
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

export type Status = {
  what: string;
  detail?: string | undefined;
};

export type LocalAction = {
  type: "__local";
  line: Line;
};

export type AgUiAction = AGUIEvent | LocalAction;

export type Task = {
  title?: string;
  done?: boolean;
};

export type DemoState = {
  tasks?: Task[];
};

export type View = {
  lines: Line[];
  status: Status | null;
  state: DemoState | null;
};

export type Persisted = {
  threadId?: string;
  lines?: Line[];
  state?: DemoState | null;
};
