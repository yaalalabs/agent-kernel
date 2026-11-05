import { useEffect, useState } from "react";

import { fetchThreads, HttpError, type ThreadSummary } from "./threads.ts";

const SETTLE_MS = 400;

function describe(e: unknown): string {
  if (e instanceof HttpError && (e.status === 401 || e.status === 403)) return "The server rejected the bearer token.";
  return e instanceof Error ? e.message : String(e);
}

/** The caller's recorded conversations, refetched once the token settles and whenever a run finishes. */
export function useThreads(token: string, running: boolean) {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (running) return;
    let stale = false;

    async function load() {
      try {
        const list = await fetchThreads(token);
        if (stale) return;
        setThreads(list);
        setError(null);
      } catch (e) {
        if (!stale) setError(describe(e));
      }
    }

    const timer = setTimeout(load, SETTLE_MS);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [token, running]);

  return { threads, error };
}
