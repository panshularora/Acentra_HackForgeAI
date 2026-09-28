import type { StatsPoint } from '../types';

/**
 * Detector parameters the dashboard needs for labelling. They mirror the
 * backend defaults in backend/app/config.py (window_seconds, bucket_seconds,
 * baseline_min_buckets); /api/health does not expose them today.
 */
export const WINDOW_SECONDS = 60;
export const BUCKET_SECONDS = 10;
export const BASELINE_MIN_BUCKETS = 12;

export type BaselineState =
  | { kind: 'waiting' }
  | { kind: 'learning'; collected: number; required: number }
  | { kind: 'ready' };

/**
 * Whether the baseline is trusted yet, judged from the newest bucket. While
 * it is still learning, progress is the run of trailing buckets without a
 * baseline (a backend restart starts that run again).
 */
export function baselineState(
  stats: readonly StatsPoint[],
  required: number = BASELINE_MIN_BUCKETS,
): BaselineState {
  const newest = stats[stats.length - 1];
  if (!newest) return { kind: 'waiting' };
  if (newest.baseline_median !== null) return { kind: 'ready' };

  let collected = 0;
  for (let i = stats.length - 1; i >= 0 && stats[i]?.baseline_median === null; i--) collected++;
  return { kind: 'learning', collected: Math.min(collected, required), required };
}

export function describeBaseline(state: BaselineState): string {
  switch (state.kind) {
    case 'waiting':
      return 'Waiting for first bucket';
    case 'learning':
      return `Learning baseline, ${state.collected} of ${state.required} buckets`;
    case 'ready':
      return 'Baseline ready';
  }
}
