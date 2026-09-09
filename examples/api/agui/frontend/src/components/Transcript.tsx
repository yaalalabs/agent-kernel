import { useEffect, useRef } from "react";

import type { Line, TextLine, ToolLine } from "../agui/types.ts";

function Thinking({ line }: { line: TextLine }) {
  return (
    <div className="thinking">
      <span className="tag">thinking</span>
      {line.text}
    </div>
  );
}

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
  return (
    <div className={`msg ${line.kind}`}>
      {line.text}
      {/* What was sent, not what the agent made of it: the base64 never appears, so without this the
          turn reads as a bare prompt and there is no way to tell which file went with it. */}
      {line.attachments?.length ? <div className="attached">📎 {line.attachments.join(", ")}</div> : null}
    </div>
  );
}

/** Message list, scrolled to the latest line. */
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
