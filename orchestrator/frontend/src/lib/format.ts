export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const sec = Math.round(s - m * 60);
  if (m < 60) return `${m}m ${sec}s`;
  const h = Math.floor(m / 60);
  const min = m - h * 60;
  return `${h}h ${min}m`;
}

/**
 * Parse a timestamp that may be:
 *   - empty string / null / undefined → returns null
 *   - ISO 8601 (e.g. "2026-04-17T12:00:00Z") → parsed
 *   - SQLite TIMESTAMP format "YYYY-MM-DD HH:MM:SS" (no T, no timezone)
 *     → coerced to UTC ISO and parsed
 *   - anything else parseable by `new Date(...)` → parsed
 *
 * Returns a `Date` on success, `null` on any failure.
 */
export function parseServerTimestamp(input: string | null | undefined): Date | null {
  if (!input) return null;
  let raw = input.trim();
  if (!raw) return null;
  // Coerce SQLite "YYYY-MM-DD HH:MM:SS" (no T, no TZ) to UTC ISO.
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?$/.test(raw)) {
    raw = raw.replace(" ", "T") + "Z";
  }
  const t = new Date(raw);
  return Number.isNaN(t.getTime()) ? null : t;
}

export function formatRelativeTime(iso: string, nowMs = Date.now()): string {
  const parsed = parseServerTimestamp(iso);
  if (!parsed) return "—";
  const t = parsed.getTime();
  const diff = Math.floor((nowMs - t) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export type Severity = "critical" | "high" | "medium" | "low" | "info";

export function severityColor(sev: Severity | string | null | undefined): string {
  switch ((sev ?? "").toLowerCase()) {
    case "critical": return "var(--c-red)";
    case "high":     return "var(--c-hot)";
    case "medium":   return "var(--c-amber)";
    case "low":      return "var(--c-accent)";
    case "info":     return "var(--c-text-dim)";
    default:         return "var(--c-text-dim)";
  }
}

export function percentage(numerator: number, denominator: number): string {
  if (denominator === 0) return "0%";
  return `${Math.round((numerator / denominator) * 100)}%`;
}
