import { useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import { readAttachment } from "../agui/attachments.ts";
import type { Attachment } from "../agui/types.ts";

type Props = {
  onSend: (prompt: string, attachments: Attachment[]) => void;
  onError: (message: string) => void;
  disabled: boolean;
};

/**
 * The input, plus the attachment picker.
 *
 * Files are read to base64 when picked rather than on submit, so an unreadable or oversized file is
 * reported while the user is still looking at the picker instead of swallowing their prompt. Staged
 * files are shown as removable chips, because a base64 blob is invisible otherwise and sending the
 * wrong image is easy.
 */
export default function Composer({ onSend, onError, disabled }: Props) {
  const [value, setValue] = useState("");
  const [staged, setStaged] = useState<Attachment[]>([]);
  const picker = useRef<HTMLInputElement>(null);

  async function pick(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    // Reset immediately so picking the same file twice in a row still fires a change event.
    event.target.value = "";
    for (const file of files) {
      try {
        const attachment = await readAttachment(file);
        setStaged((current) => [...current, attachment]);
      } catch (error) {
        onError(error instanceof Error ? error.message : String(error));
      }
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = value.trim();
    // An attachment with no prompt is a legitimate turn, but Agent Kernel rejects a message with no
    // content at all, so one of the two has to be present.
    if (disabled || (!prompt && staged.length === 0)) return;
    setValue("");
    setStaged([]);
    onSend(prompt, staged);
  }

  return (
    <form onSubmit={submit}>
      {staged.length > 0 && (
        <ul className="staged">
          {staged.map((attachment, index) => (
            <li key={`${attachment.name}-${index}`}>
              {attachment.name}
              <button
                type="button"
                aria-label={`Remove ${attachment.name}`}
                onClick={() => setStaged((current) => current.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <input
        type="text"
        placeholder="add milk to my tasks"
        autoComplete="off"
        autoFocus
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <input ref={picker} type="file" multiple hidden onChange={pick} />
      <button type="button" title="Attach an image or document" disabled={disabled} onClick={() => picker.current?.click()}>
        📎
      </button>
      <button type="submit" disabled={disabled}>
        {disabled ? "…" : "Send"}
      </button>
    </form>
  );
}
