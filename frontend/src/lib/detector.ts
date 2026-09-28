import type { DetectorKind, DetectorTiming, Health, LearningState, StatsPoint } from '../types';

/**
 * Fallback used until /api/health answers. Matches the backend defaults in
 * backend/app/config.py; the live values always come from the health payload.
 */
export const DEFAULT_DETECTOR_TIMING: DetectorTiming = {
  window_seconds: 60,
  bucket_seconds: 10,
  baseline_min_buckets: 6,
};

/** The backend's detector timing, or the defaults while health is unknown. */
export function detectorTiming(health: Health | null): DetectorTiming {
  return health?.detector ?? DEFAULT_DETECTOR_TIMING;
}

/** Number of buckets in one sliding window. */
export function windowBuckets(timing: DetectorTiming): number {
  return Math.max(1, Math.floor(timing.window_seconds / timing.bucket_seconds));
}

export type BaselineState =
  | { kind: 'waiting' }
  | { kind: 'filling'; collected: number; required: number }
  | { kind: 'learning'; collected: number; required: number }
  /** `templates` is the distinct log templates seen, when the backend reports it. */
  | { kind: 'ready'; templates?: number };

/**
 * Whether the baseline is trusted yet, estimated from the newest buckets.
 * This is the fallback for backends that do not report `learning`; see
 * currentBaselineState.
 *
 * The backend only feeds the baseline once the sliding window is full, so a
 * cold start has two phases: filling the first window (`windowBucketCount`
 * buckets), then collecting `required` window rates. Progress is
 * read from the trailing run of buckets without a baseline, so a backend
 * restart starts the count again.
 */
export function baselineState(
  stats: readonly StatsPoint[],
  required: number = DEFAULT_DETECTOR_TIMING.baseline_min_buckets,
  windowBucketCount: number = windowBuckets(DEFAULT_DETECTOR_TIMING),
): BaselineState {
  const newest = stats[stats.length - 1];
  if (!newest) return { kind: 'waiting' };
  if (newest.baseline_median !== null) return { kind: 'ready' };

  let cold = 0;
  for (let i = stats.length - 1; i >= 0 && stats[i]?.baseline_median === null; i--) cold++;
  if (cold < windowBucketCount) {
    return { kind: 'filling', collected: cold, required: windowBucketCount };
  }
  // The bucket that completes the window is also the first baseline sample.
  const collected = Math.min(cold - windowBucketCount + 1, required);
  return { kind: 'learning', collected, required };
}

/** Maps the backend's contract v2 learning object onto the dashboard's baseline states. */
export function baselineFromLearning(learning: LearningState): BaselineState {
  if (learning.state === 'ready') return { kind: 'ready', templates: learning.templates };
  const required = Math.max(0, learning.buckets_needed);
  return {
    kind: 'learning',
    collected: Math.min(Math.max(0, learning.buckets_seen), required),
    required,
  };
}

/**
 * The detector's warm-up state as the backend reports it: the newest stats
 * bucket's `learning`, else the one /api/health returned on load. Backends
 * without `learning` fall back to estimating it from the buckets, using the
 * timing from /api/health.
 */
export function currentBaselineState(
  stats: readonly StatsPoint[],
  health: Health | null,
): BaselineState {
  const learning =
    stats[stats.length - 1]?.learning ?? (stats.length === 0 ? health?.learning : null);
  if (learning) return baselineFromLearning(learning);
  const timing = detectorTiming(health);
  return baselineState(stats, timing.baseline_min_buckets, windowBuckets(timing));
}

export function describeBaseline(
  state: BaselineState,
  windowSeconds: number = DEFAULT_DETECTOR_TIMING.window_seconds,
): string {
  switch (state.kind) {
    case 'waiting':
      return 'Waiting for first bucket';
    case 'filling':
      return `Filling first ${windowSeconds}s window, ${state.collected} of ${state.required} buckets`;
    case 'learning':
      return `Learning baseline, ${state.collected} of ${state.required} buckets`;
    case 'ready':
      if (state.templates == null) return 'Monitoring';
      return `Monitoring, ${state.templates} ${state.templates === 1 ? 'template' : 'templates'}`;
  }
}

/** Short labels for the contract v2 detectors, as shown on alert cards. */
export const DETECTOR_LABEL: Record<DetectorKind, string> = {
  error_spike: 'Error spike',
  silence: 'Silence',
  new_pattern: 'New pattern',
  flow_break: 'Flow break',
};

/**
 * Label for Alert.detector, or null when the backend did not send one. A kind
 * this build does not know yet is shown humanised ("rate_drop" -> "Rate drop")
 * rather than hidden, so a newer backend still explains itself.
 */
export function detectorLabel(kind: string | null | undefined): string | null {
  if (!kind) return null;
  if (Object.hasOwn(DETECTOR_LABEL, kind)) return DETECTOR_LABEL[kind as DetectorKind];
  const words = kind.replace(/_/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : null;
}
