import { useEffect, useRef } from "react";

import type { Line, TextLine, ToolLine } from "../agui/types.ts";

/**
 * The message list, and the three ways a line can render. Choosing the renderer off `line.kind` is
 * why `Line` is a discriminated union: each branch hands on a line already narrowed to the fields its
 * renderer reads, so a tool card cannot be passed a line of prose.
 */

/** The agent's own working, styled to read as clearly *not* the answer. */
function Thinking({ line }: { line: TextLine }) {
  return (
    <div className="thinking">
      <span className="tag">thinking</span>
      {line.text}
    </div>
  );
}

/** One call, growing in three stages: the name, then the streamed args, then the result. */
function ToolCall({ line }: { line: ToolLine }) {
  return (
    <div className="tool">
      <div className="head">
        <span className="name">{line.name}</span>
        {line.open && <span className="spinner">calling…</span>}
      </div>

      {line.args && (
        <div className="args">
          <span className="label">args </span>
          {line.args}
        </div>
      )}

      {line.result !== null && (
        <div className="result">
          <span className="label">result </span>
          {line.result}
        </div>
      )}
    </div>
  );
}

function LineView({ line }: { line: Line }) {
  if (line.kind === "thinking") return <Thinking line={line} />;
  if (line.kind === "tool") return <ToolCall line={line} />;
  if (line.kind === "error") return <div className="error">{line.text}</div>;
  return <div className={`msg ${line.kind}`}>{line.text}</div>;
}

export default function Transcript({ lines }: { lines: Line[] }) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines]);

  return (
    <div className="log" ref={box}>
      {lines.length === 0 && <div className="muted">Ask for a task to be added.</div>}
      {lines.map((line) => (
        <LineView key={line.id} line={line} />
      ))}
    </div>
  );
}
