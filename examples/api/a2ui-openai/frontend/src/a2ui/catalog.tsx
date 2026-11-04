/**
 * This application's component catalog — the nine things its UI can draw.
 *
 * This is the half Agent Kernel deliberately does not ship. A catalog has to match what a given
 * frontend actually implements, so the framework cannot supply one: a catalog listing components
 * your client cannot draw is worse than none, because the model emits them confidently and nothing
 * appears.
 *
 * It must agree with the catalog in `app.py`'s prompt. They are two copies of one list on purpose —
 * the agent is told what exists here. Add a component to one and not the other and you get the
 * failure `UnknownComponent` below is there to make visible.
 */

import type { JSX, ReactNode } from "react";

type Props = Record<string, unknown>;

const text = (value: unknown): string => (typeof value === "string" ? value : "");
const options = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);

/**
 * The components that collect input, as opposed to displaying it.
 *
 * Lives here because this file is what knows the difference. A surface built only from `Card`,
 * `Heading`, `Text` and `Field` is a receipt, and disabling it — or captioning it "Sent" — would
 * describe it as a form that has been used up.
 */
const INPUTS = new Set(["TextField", "NumberField", "DateField", "Select", "Button"]);

/** True when a surface has something to fill in or press. */
export function isInteractive(message: { createSurface?: { components?: { component?: object }[] } }): boolean {
  const components = message.createSurface?.components ?? [];
  return components.some((component) => Object.keys(component.component ?? {}).some((name) => INPUTS.has(name)));
}

/** Rendered in place of a component the catalog has no entry for, instead of throwing. */
export function UnknownComponent({ name }: { name: string }): JSX.Element {
  return <div className="unknown">⚠ Unknown component “{name}” — not in this client’s catalog</div>;
}

/**
 * Each entry takes the component's properties plus its already-rendered children, and returns an
 * element. Children arrive rendered because resolving ids is the renderer's job, not a component's.
 */
export const CATALOG: Record<string, (props: Props, children: ReactNode) => JSX.Element> = {
  Card: (_props, children) => <div className="card">{children}</div>,

  Heading: (props) => <h3 className="heading">{text(props.text)}</h3>,

  Text: (props) => <p className="text">{text(props.text)}</p>,

  // Read-only, and the only component here that carries a value rather than collecting one. It is
  // what lets a confirmation be a surface instead of prose: the values the agent recorded are part
  // of the payload, so they are stored with it and replay from history. A `TextField` would look
  // similar and be wrong — it is an empty input whose contents live only in the DOM.
  Field: (props) => (
    <div className="field readonly">
      <span>{text(props.label)}</span>
      <strong>{text(props.value)}</strong>
    </div>
  ),

  TextField: (props) => (
    <label className="field">
      <span>{text(props.label)}</span>
      <input name={text(props.name)} type="text" />
    </label>
  ),

  NumberField: (props) => (
    <label className="field">
      <span>{text(props.label)}</span>
      <input name={text(props.name)} type="number" step="any" />
    </label>
  ),

  DateField: (props) => (
    <label className="field">
      <span>{text(props.label)}</span>
      <input name={text(props.name)} type="date" />
    </label>
  ),

  Select: (props) => (
    <label className="field">
      <span>{text(props.label)}</span>
      <select name={text(props.name)} defaultValue="">
        <option value="" disabled>
          Choose…
        </option>
        {options(props.options).map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  ),

  Button: (props) => (
    <button className="submit" type="submit">
      {text(props.label) || "Submit"}
    </button>
  ),
};
