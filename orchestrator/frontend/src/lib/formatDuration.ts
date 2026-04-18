/**
 * Humanize a duration in milliseconds.
 *   1  →      "1ms"
 *   900 →     "900ms"
 *   1500 →    "1.5s"
 *   60000 →   "1m 0s"
 *   3600000 → "1h 0m"
 * null / undefined → "—"
 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const totalMin = Math.floor(s / 60);
  const sec = Math.round(s - totalMin * 60);
  if (totalMin < 60) return `${totalMin}m ${sec}s`;
  const h = Math.floor(totalMin / 60);
  const min = totalMin - h * 60;
  return `${h}h ${min}m`;
}

/**
 * Given a unix-seconds start timestamp and optional end, return a humanized
 * live duration. Falls back to "" if started is null.
 */
export function formatDurationSince(
  startedSec: number | null | undefined,
  endedSec: number | null | undefined = null,
): string {
  if (startedSec == null) return "";
  const nowSec = Math.floor(Date.now() / 1000);
  const end = endedSec ?? nowSec;
  return formatDuration(Math.max(0, (end - startedSec) * 1000));
}
