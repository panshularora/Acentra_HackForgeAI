/**
 * How current the live stream looks, from the newest stats bucket vs the clock.
 * The WebSocket can sit "open" while ingest has stalled; this is what the
 * status bar uses to say "Live · delayed" instead of a green dot on stale data.
 */

export type StreamFreshness = 'unknown' | 'fresh' | 'delayed' | 'stale';

/** Age of `latestTs` in ms; NaN when the timestamp is missing or unparseable. */
export function streamAgeMs(latestTs: string | undefined, now: number): number {
  if (!latestTs) return Number.NaN;
  const age = now - Date.parse(latestTs);
  return Number.isFinite(age) ? age : Number.NaN;
}

/**
 * `bucketSeconds` is the backend's close interval (default 10). Fresh means
 * the last bucket is at most 1.5 intervals old; delayed up to 4; older is stale.
 */
export function streamFreshness(
  latestTs: string | undefined,
  now: number,
  bucketSeconds: number,
): StreamFreshness {
  const age = streamAgeMs(latestTs, now);
  if (!Number.isFinite(age)) return 'unknown';
  const bucketMs = Math.max(1, bucketSeconds) * 1000;
  if (age <= bucketMs * 1.5) return 'fresh';
  if (age <= bucketMs * 4) return 'delayed';
  return 'stale';
}
