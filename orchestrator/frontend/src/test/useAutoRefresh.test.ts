import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useAutoRefresh } from "../lib/useAutoRefresh";

describe("useAutoRefresh", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("calls fetcher immediately on mount", async () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAutoRefresh(fetcher, [], { intervalMs: 1000 }));
    await Promise.resolve();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("calls fetcher every intervalMs", async () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAutoRefresh(fetcher, [], { intervalMs: 1000 }));
    await Promise.resolve();
    expect(fetcher).toHaveBeenCalledTimes(1);

    act(() => { vi.advanceTimersByTime(1000); });
    await Promise.resolve();
    expect(fetcher).toHaveBeenCalledTimes(2);

    act(() => { vi.advanceTimersByTime(1000); });
    await Promise.resolve();
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("does not call fetcher when enabled=false", async () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAutoRefresh(fetcher, [], { enabled: false }));
    await Promise.resolve();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("cancels on unmount", async () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderHook(() =>
      useAutoRefresh(fetcher, [], { intervalMs: 1000 }),
    );
    await Promise.resolve();
    unmount();
    act(() => { vi.advanceTimersByTime(5000); });
    await Promise.resolve();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("passes an AbortSignal to the fetcher", async () => {
    let receivedSignal: AbortSignal | null = null;
    const fetcher = vi.fn(async (signal: AbortSignal) => {
      receivedSignal = signal;
    });
    renderHook(() => useAutoRefresh(fetcher, []));
    await Promise.resolve();
    expect(receivedSignal).not.toBeNull();
    expect(receivedSignal!.aborted).toBe(false);
  });

  it("pauses while document.visibilityState is hidden", async () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    const original = Object.getOwnPropertyDescriptor(Document.prototype, "visibilityState");
    Object.defineProperty(document, "visibilityState", {
      configurable: true, get: () => "hidden",
    });
    try {
      renderHook(() =>
        useAutoRefresh(fetcher, [], { intervalMs: 1000 }),
      );
      // First call is blocked — visibility hidden at mount.
      await Promise.resolve();
      expect(fetcher).not.toHaveBeenCalled();

      // Still hidden: interval ticks are skipped.
      act(() => { vi.advanceTimersByTime(5000); });
      await Promise.resolve();
      expect(fetcher).not.toHaveBeenCalled();
    } finally {
      if (original) Object.defineProperty(Document.prototype, "visibilityState", original);
    }
  });
});
