import { useState } from "react";
import type { FormEvent } from "react";

type Props = {
  onSend: (prompt: string) => void;
  disabled: boolean;
};

/** Prompt input, disabled while a run is in flight. */
export default function Composer({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = value.trim();
    if (!prompt || disabled) return;
    setValue("");
    onSend(prompt);
  }

  return (
    <form onSubmit={submit}>
      <input
        type="text"
        placeholder="add milk to my tasks"
        autoComplete="off"
        autoFocus
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <button type="submit" disabled={disabled}>
        {disabled ? "…" : "Send"}
      </button>
    </form>
  );
}
