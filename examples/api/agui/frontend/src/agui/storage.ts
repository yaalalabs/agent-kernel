import type { Persisted } from "./types.ts";

const STORE_KEY = "ak-agui-demo";

/** Restore the last view from sessionStorage, or {}. */

export function restore(): Persisted {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Persisted) : {};
  } catch {
    return {};
  }
}

/** Write the view to sessionStorage. */
export function persist(snapshot: Persisted): void {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(snapshot));
  } catch {}
}

/** Drop the stored view. */
export function forget(): void {
  try {
    sessionStorage.removeItem(STORE_KEY);
  } catch {}
}
