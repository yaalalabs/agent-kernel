import type { AGUIEvent } from "@ag-ui/core";

/** Parse SSE `data:` frames from a fetch Response. */
export async function* sseEvents(response: Response): AsyncGenerator<AGUIEvent> {
  if (!response.body) throw new Error("The AG-UI response carried no body to stream.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      for (const line of frame.split("\n")) {
        if (line.startsWith("data:")) yield JSON.parse(line.slice(5)) as AGUIEvent;
      }
    }
  }
}
