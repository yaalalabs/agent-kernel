/**
 * Renders one A2UI `createSurface` message, and nothing more.
 *
 * Deliberately dumb. It resolves ids to components and recurses; it does not validate the document,
 * track surface state, apply `updateComponents`, or bind a data model. The example only ever
 * receives a single self-contained `createSurface`, so anything beyond "walk the tree and draw it"
 * would be machinery with nothing to drive it.
 *
 * It also does not decide whether the payload is *good* A2UI. Agent Kernel labelled it and passed it
 * along without looking inside; the renderer is the first party that knows which components exist,
 * so an unknown one surfaces here as a visible placeholder rather than an exception.
 */

import type { JSX } from "react";

import { CATALOG, UnknownComponent } from "./catalog.tsx";
import type { A2UIComponent, A2UIMessage } from "./types.ts";

/** The id A2UI reserves for the top of the component tree. */
const ROOT_ID = "root";

/** Guards a malformed `children` array, and a cycle that would otherwise recurse forever. */
function renderById(id: string, byId: Map<string, A2UIComponent>, seen: Set<string>): JSX.Element {
  if (seen.has(id)) return <UnknownComponent key={id} name={`${id} (cycle)`} />;

  const node = byId.get(id);
  if (!node) return <UnknownComponent key={id} name={`${id} (no such id)`} />;

  // A component is a single-key object: {"Card": {...}}. The key is the name.
  const [name, props = {}] = Object.entries(node.component ?? {})[0] ?? [];
  if (!name) return <UnknownComponent key={id} name="(empty)" />;

  const render = CATALOG[name];
  if (!render) return <UnknownComponent key={id} name={name} />;

  const childIds = Array.isArray(props.children) ? props.children.map(String) : [];
  const children = childIds.map((childId) => renderById(childId, byId, new Set(seen).add(id)));

  return <div key={id}>{render(props, children)}</div>;
}

export function Surface({ message }: { message: A2UIMessage }): JSX.Element {
  const components = message.createSurface?.components ?? [];
  const byId = new Map(components.map((component) => [component.id, component]));

  if (!byId.has(ROOT_ID)) {
    return <UnknownComponent name={`surface has no "${ROOT_ID}" component`} />;
  }
  return <div className="surface">{renderById(ROOT_ID, byId, new Set())}</div>;
}
