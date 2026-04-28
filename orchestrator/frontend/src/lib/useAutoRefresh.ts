import { useEffect } from "react";

type AutoRefreshOptions = {
  enabled?: boolean;
  intervalMs?: number;
  pauseWhenHidden?: boolean;
};

/**
 * Calls `fetcher` once on mount, then every `intervalMs` while the browser
 * tab is visible. `deps` re-subscribe semantics match useEffect.
 *
 * `fetcher` receives a `signal` param for AbortController-style cancellation
 * and should respect it; but even if it doesn't, the internal `cancelled`
 * flag blocks stale state updates.
 */
export function useAutoRefresh(
  fetcher: (signal: AbortSignal) => Promise<void>,
  deps: ReadonlyArray<unknown>,
  options: AutoRefreshOptions = {},
): void {
  const { enabled = true, intervalMs = 5000, pauseWhenHidden = true } = options;

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let cancelled = false;
    let intervalHandle: number | null = null;

    async function tick() {
      if (cancelled) return;
      if (pauseWhenHidden && typeof document !== "undefined"
          && document.visibilityState === "hidden") return;
      try {
        await fetcher(controller.signal);
      } catch (err) {
        if (cancelled) return;
        if ((err as { name?: string } | null)?.name === "AbortError") return;
        console.warn("[useAutoRefresh] fetch failed:", err);
      }
    }

    void tick();
    intervalHandle = window.setInterval(() => { void tick(); }, intervalMs);

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void tick();
    };
    if (pauseWhenHidden) {
      document.addEventListener("visibilitychange", onVisibilityChange);
    }

    return () => {
      cancelled = true;
      controller.abort();
      if (intervalHandle !== null) window.clearInterval(intervalHandle);
      if (pauseWhenHidden) {
        document.removeEventListener("visibilitychange", onVisibilityChange);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, intervalMs, pauseWhenHidden]);
}
