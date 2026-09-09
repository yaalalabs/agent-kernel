import assert from "node:assert/strict";
import test from "node:test";

import { EMPTY_VIEW, reduceEvent } from "./reduceEvent.ts";
import { sseEvents } from "./sse.ts";
import type { AgUiAction, TextLine, ToolLine, View } from "./types.ts";
import { uuid } from "./uuid.ts";

const fold = (events: unknown[], from: View = EMPTY_VIEW): View =>
  events.reduce<View>((view, event) => reduceEvent(view, event as AgUiAction), from);

const kinds = (view: View) => view.lines.map((line) => line.kind);

const statusOf = (events: unknown[]) => {
  const { status } = fold(events);
  return status && [status.what, status.detail];
};

const textAt = (view: View, index: number): TextLine => {
  const line = view.lines[index];
  assert.ok(line && line.kind !== "tool", `line ${index} should carry text`);
  return line;
};

const toolAt = (view: View, index: number): ToolLine => {
  const line = view.lines[index];
  assert.ok(line && line.kind === "tool", `line ${index} should be a tool call`);
  return line;
};

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test("uuid falls back when randomUUID is unavailable", () => {
  const real = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
  try {
    const ids = new Set(Array.from({ length: 5000 }, uuid));
    assert.equal(ids.size, 5000, "ids must be unique");
    assert.ok([...ids].every((id) => V4.test(id)), "ids must be RFC 4122 v4");
  } finally {
    Object.defineProperty(crypto, "randomUUID", { value: real, configurable: true });
  }
  assert.ok(V4.test(uuid()), "and it delegates to randomUUID when that exists");
});

test("a text message folds into one line", () => {
  const view = fold([
    { type: "TEXT_MESSAGE_START", messageId: "m1" },
    { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "Added " },
    { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "milk." },
    { type: "TEXT_MESSAGE_END", messageId: "m1" },
  ]);
  assert.deepEqual(view.lines, [{ id: "m1", kind: "assistant", text: "Added milk." }]);
});

test("reasoning stays separate from the answer", () => {
  const view = fold([
    { type: "REASONING_MESSAGE_START", messageId: "r1" },
    { type: "REASONING_MESSAGE_CONTENT", messageId: "r1", delta: "think" },
    { type: "REASONING_MESSAGE_END", messageId: "r1" },
    { type: "TEXT_MESSAGE_START", messageId: "m1" },
    { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "answer" },
  ]);
  assert.deepEqual(kinds(view), ["thinking", "assistant"]);
  assert.deepEqual([textAt(view, 0).text, textAt(view, 1).text], ["think", "answer"]);
});

test("a tool call keeps name, args and result apart", () => {
  const view = fold([
    { type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "update_agui_state" },
    { type: "TOOL_CALL_ARGS", toolCallId: "t1", delta: '{"updates":' },
    { type: "TOOL_CALL_ARGS", toolCallId: "t1", delta: ' "{}"}' },
    { type: "TOOL_CALL_END", toolCallId: "t1" },
    { type: "TOOL_CALL_RESULT", toolCallId: "t1", content: '{"tasks": []}' },
  ]);
  assert.deepEqual(toolAt(view, 0), {
    id: "t1",
    kind: "tool",
    name: "update_agui_state",
    args: '{"updates": "{}"}',
    result: '{"tasks": []}',
    open: false,
  });
});

test("an unfinished tool call is marked open", () => {
  const view = fold([{ type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "f" }]);
  assert.equal(toolAt(view, 0).open, true);
});

test("interleaved messages and tool calls stay correlated by id", () => {
  const view = fold([
    { type: "TEXT_MESSAGE_START", messageId: "m1" },
    { type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "f" },
    { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "one" },
    { type: "TOOL_CALL_ARGS", toolCallId: "t1", delta: "x" },
    { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "-two" },
  ]);
  assert.equal(textAt(view, 0).text, "one-two");
  assert.equal(toolAt(view, 1).args, "x");
});

test("the status strip follows the protocol's boundary events", () => {
  assert.equal(fold([]).status, null, "idle before anything");
  assert.deepEqual(statusOf([{ type: "RUN_STARTED" }]), ["Working", undefined]);
  assert.deepEqual(statusOf([{ type: "STEP_STARTED", stepName: "plan" }]), ["Step", "plan"]);
  assert.deepEqual(statusOf([{ type: "REASONING_MESSAGE_START", messageId: "r" }]), ["Thinking", undefined]);
  assert.deepEqual(statusOf([{ type: "TEXT_MESSAGE_START", messageId: "m" }]), ["Replying", undefined]);
  assert.deepEqual(statusOf([{ type: "TOOL_CALL_START", toolCallId: "t", toolCallName: "get_agui_state" }]), ["Calling", "get_agui_state"]);
  assert.equal(fold([{ type: "RUN_STARTED" }, { type: "RUN_FINISHED" }]).status, null, "idle again when the run ends");
});

test("TOOL_CALL_END names the tool from the call already held", () => {
  const status = statusOf([
    { type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "update_agui_state" },
    { type: "TOOL_CALL_END", toolCallId: "t1" },
  ]);
  assert.deepEqual(status, ["Running", "update_agui_state"]);
});

test("RUN_ERROR ends the run and shows the message", () => {
  const view = fold([{ type: "RUN_STARTED" }, { type: "RUN_ERROR", message: "boom" }]);
  assert.equal(view.status, null);
  assert.deepEqual([textAt(view, 0).kind, textAt(view, 0).text], ["error", "boom"]);
});

test("STATE_SNAPSHOT updates the state and adds no transcript line", () => {
  const view = fold([{ type: "STATE_SNAPSHOT", snapshot: { tasks: [{ title: "milk" }] } }]);
  assert.deepEqual(view.state, { tasks: [{ title: "milk" }] });
  assert.equal(view.lines.length, 0);
});

test("a client tolerates what a given adapter does not send", () => {
  assert.equal(textAt(fold([{ type: "TEXT_MESSAGE_CONTENT", messageId: "m9", delta: "orphan" }]), 0).text, "orphan");
  assert.deepEqual(fold([{ type: "TOOL_CALL_ARGS", toolCallId: "nope", delta: "x" }]).lines, [], "args for a call never announced");
  assert.deepEqual(fold([{ type: "ACTIVITY_SNAPSHOT" }, { type: "SOMETHING_FROM_0_3" }]), EMPTY_VIEW, "unknown types leave the view alone");
});

test("a full run of mixed events folds into a coherent view", () => {
  const view = fold([
    { type: "RUN_STARTED" },
    { type: "STEP_STARTED", stepName: "plan" },
    { type: "REASONING_MESSAGE_START", messageId: "r1" },
    { type: "REASONING_MESSAGE_CONTENT", messageId: "r1", delta: "read the state first" },
    { type: "REASONING_MESSAGE_END", messageId: "r1" },
    { type: "STEP_FINISHED", stepName: "plan" },
    { type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "update_agui_state" },
    { type: "TOOL_CALL_ARGS", toolCallId: "t1", delta: '{"updates": "{' },
    { type: "TOOL_CALL_ARGS", toolCallId: "t1", delta: '}"}' },
    { type: "TOOL_CALL_END", toolCallId: "t1" },
    { type: "TOOL_CALL_RESULT", toolCallId: "t1", content: '{"tasks": []}' },
    { type: "TEXT_MESSAGE_START", messageId: "m1" },
    { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "Done." },
    { type: "TEXT_MESSAGE_END", messageId: "m1" },
    { type: "STATE_SNAPSHOT", snapshot: { tasks: [{ title: "milk", done: false }] } },
    { type: "RUN_FINISHED" },
  ]);

  assert.deepEqual(kinds(view), ["thinking", "tool", "assistant"]);
  assert.deepEqual(view.state, { tasks: [{ title: "milk", done: false }] });
  assert.equal(view.status, null, "a finished run leaves the strip idle");
  assert.equal(typeof JSON.parse(toolAt(view, 1).args), "object");
});

test("SSE frames survive reads that split mid-JSON", async () => {
  const body = [
    '{"type":"RUN_STARTED","threadId":"t1","runId":"r1"}',
    '{"type":"TEXT_MESSAGE_CONTENT","messageId":"m1","delta":"Hi "}',
    '{"type":"TEXT_MESSAGE_CONTENT","messageId":"m1","delta":"there"}',
    '{"type":"RUN_FINISHED","threadId":"t1","runId":"r1"}',
  ]
    .map((frame) => `data: ${frame}\n\n`)
    .join("");

  const raw = new TextEncoder().encode(body);
  const cuts = [0, 30, 31, 120, raw.length];
  const chunks = cuts.slice(1).map((cut, i) => raw.slice(cuts[i], cut));

  let next = 0;
  const response = {
    body: { getReader: () => ({ read: async () => (next < chunks.length ? { value: chunks[next++], done: false } : { done: true }) }) },
  } as unknown as Response;

  const events = [];
  for await (const event of sseEvents(response)) events.push(event);

  assert.deepEqual(events.map((e) => e.type), ["RUN_STARTED", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_CONTENT", "RUN_FINISHED"]);
  assert.equal(textAt(fold(events), 0).text, "Hi there");
});
