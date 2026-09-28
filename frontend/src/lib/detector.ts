import type { StatsPoint } from '../types';

/**
 * Detector parameters the dashboard needs for labelling. They mirror the
 * backend defaults in backend/app/config.py (window_seconds, bucket_seconds,
 * baseline_min_buckets); /api/health does not expose them today.
 */
export const WINDOW_SECONDS = 60;
export const BUCKET_SECONDS = 10;
export const WINDOW_BUCKETS = WINDOW_SECONDS / BUCKET_SECONDS;
export const BASELINE_MIN_BUCKETS = 12;

export type BaselineState =
  | { kind: 'waiting' }
  | { kind: 'filling'; collected: number; required: number }
  | { kind: 'learning'; collected: number; required: number }
  | { kind: 'ready' };

/**
 * Whether the baseline is trusted yet, judged from the newest bucket.
 *
 * The backend only feeds the baseline once the sliding window is full, so a
 * cold start has two phases: filling the first window (WINDOW_BUCKETS
 * buckets), then collecting BASELINE_MIN_BUCKETS window rates. Progress is
 * read from the trailing run of buckets without a baseline, so a backend
 * restart starts the count again.
 */
export function baselineState(
  stats: readonly StatsPoint[],
  required: number = BASELINE_MIN_BUCKETS,
  windowBuckets: number = WINDOW_BUCKETS,
): BaselineState {
  const newest = stats[stats.length - 1];
  if (!newest) return { kind: 'waiting' };
  if (newest.baseline_median !== null) return { kind: 'ready' };

  let cold = 0;
  for (let i = stats.length - 1; i >= 0 && stats[i]?.baseline_median === null; i--) cold++;
  if (cold < windowBuckets) return { kind: 'filling', collected: cold, required: windowBuckets };
  // The bucket that completes the window is also the first baseline sample.
  const collected = Math.min(cold - windowBuckets + 1, required);
  return { kind: 'learning', collected, required };
}

export function describeBaseline(state: BaselineState): string {
  switch (state.kind) {
    case 'waiting':
      return 'Waiting for first bucket';
    case 'filling':
      return `Filling first 60s window, ${state.collected} of ${state.required} buckets`;
    case 'learning':
      return `Learning baseline, ${state.collected} of ${state.required} buckets`;
    case 'ready':
      return 'Baseline ready';
  }
}
