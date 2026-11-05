import { useEffect, useState } from "react";

import { fetchThreads, type ThreadSummary } from "./threads.ts";

/** The caller's recorded conversations, refetched when the token changes or a run finishes. */
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
        if (!stale) setError(e instanceof Error ? e.message : String(e));
      }
    }

    load();
    return () => {
      stale = true;
    };
  }, [token, running]);

  return { threads, error };
}
