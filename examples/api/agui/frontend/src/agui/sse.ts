import type { AGUIEvent } from "@ag-ui/core";

/**
 * AG-UI's transport is Server-Sent Events, parsed by hand here because `EventSource` cannot issue a
 * POST. The server sends one `data: {json}` line per event, separated by blank lines; a network read
 * can split anywhere, so the trailing partial frame is held back until the rest of it arrives.
 */
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
        if (line.startsWith("data:")) yield JSON.parse(line.slice(5)) as AGUIEvent; // asserted, not validated
      }
    }
  }
}
