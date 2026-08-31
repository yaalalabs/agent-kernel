import type { Attachment } from "./types.ts";

/**
 * Turning a picked `File` into what AG-UI's `data` source wants: bare base64, no `data:` prefix.
 *
 * `FileReader` hands back a data URI, so the prefix is stripped rather than kept. Both forms reach the
 * agent — Agent Kernel classifies either — but bare base64 is the form that works on every path,
 * including with Conversation Thread Support enabled, so it is the one worth sending.
 *
 * Reading is capped: a picked file becomes base64 inside the JSON request body, which grows it by a
 * third, and a browser will happily hand over a 50MB video. The cap fails loudly instead of hanging.
 */
export const MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024;

export async function readAttachment(file: File): Promise<Attachment> {
  if (file.size > MAX_ATTACHMENT_BYTES) {
    throw new Error(`${file.name} is ${(file.size / 1024 / 1024).toFixed(1)}MB; the demo caps attachments at 4MB.`);
  }

  const dataUri = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });

  const comma = dataUri.indexOf(",");
  return {
    name: file.name,
    // A browser leaves `type` empty for an extension it does not know; the agent needs something.
    mimeType: file.type || "application/octet-stream",
    data: comma === -1 ? dataUri : dataUri.slice(comma + 1),
  };
}
