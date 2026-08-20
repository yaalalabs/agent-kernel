import type { Persisted } from "./types.ts";

/**
 * What survives a page reload, kept in `sessionStorage` so it lasts as long as the tab.
 *
 * `threadId` is the one that matters: Agent Kernel uses it as the session id, so minting a fresh one
 * orphans the agent's memory and the stored state alike. The state is kept for a different reason —
 * AG-UI has no "read the current state" request, so a reloaded page cannot ask for it and has to own
 * a copy. Storage access can throw (private mode, storage disabled), so every call is guarded.
 */
const STORE_KEY = "ak-agui-demo";

export function restore(): Persisted {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Persisted) : {};
  } catch {
    return {};
  }
}

export function persist(snapshot: Persisted): void {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(snapshot));
  } catch {
    /* the page still works, it just will not survive a reload */
  }
}

export function forget(): void {
  try {
    sessionStorage.removeItem(STORE_KEY);
  } catch {
    /* nothing stored to clear */
  }
}
