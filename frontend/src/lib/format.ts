/**
 * Pure formatting helpers. Nothing here reads the clock or the DOM; callers
 * pass `now` explicitly so the output is deterministic and easy to test.
 */

const EM_DASH = '\u2014';

/** 0.0218 -> "2.2%". Small non-zero rates keep an extra digit so they never read as 0. */
export function formatPercent(rate: number | null | undefined, digits = 1): string {
  if (rate == null || !Number.isFinite(rate)) return EM_DASH;
  const pct = rate * 100;
  const precision = pct !== 0 && Math.abs(pct) < 1 ? digits + 1 : digits;
  return `${pct.toFixed(precision)}%`;
}

/** Modified z-score, one decimal. */
export function formatScore(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return EM_DASH;
  return score.toFixed(1);
}

/** How many times above baseline, e.g. "15.5×". Returns null when not meaningful. */
export function formatMultiple(value: number, baseline: number | null | undefined): string | null {
  if (baseline == null || baseline <= 0 || !Number.isFinite(value)) return null;
  const multiple = value / baseline;
  if (multiple < 1.1) return null;
  return `${multiple >= 10 ? multiple.toFixed(0) : multiple.toFixed(1)}\u00d7`;
}

const countFormatter = new Intl.NumberFormat('en-US');

export function formatCount(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return EM_DASH;
  return countFormatter.format(Math.round(n));
}

/** "just now", "42s ago", "7m ago", "3h ago", "2d ago". */
export function formatRelative(iso: string, now: number): string {
  const seconds = Math.round((now - Date.parse(iso)) / 1000);
  if (!Number.isFinite(seconds)) return EM_DASH;
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** Compact duration: "45s", "4m 12s", "2h 05m". */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return EM_DASH;
  const total = Math.round(ms / 1000);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes < 60) return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, '0')}m`;
}

/**
 * Wall-clock time in the viewer's time zone (or an explicit one), 24-hour,
 * e.g. "18:35:10". The zone is shown once in the status bar rather than on
 * every timestamp.
 */
export function formatClock(
  iso: string | number,
  options: { timeZone?: string; seconds?: boolean } = {},
): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return EM_DASH;
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    second: options.seconds === false ? undefined : '2-digit',
    hour12: false,
    timeZone: options.timeZone,
  }).format(date);
}

/** Short name of a time zone as the viewer's locale spells it, e.g. "IST" or "GMT+5:30". */
export function timeZoneLabel(timeZone?: string, locale?: string): string {
  const parts = new Intl.DateTimeFormat(locale, { timeZoneName: 'short', timeZone }).formatToParts(
    new Date(),
  );
  return parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
}

/** "arn:aws:sns:us-east-1:000000000000:claimswatch-alerts" -> "claimswatch-alerts". */
export function arnResourceName(arn: string | null | undefined): string | null {
  if (!arn) return null;
  const parts = arn.split(':');
  return parts[parts.length - 1] || arn;
}

/** Start of the viewer's current calendar day, in epoch ms. */
export function startOfLocalDay(now: number): number {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}
