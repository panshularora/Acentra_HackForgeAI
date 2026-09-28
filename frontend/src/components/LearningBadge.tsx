import { describeBaseline, type BaselineState } from '../lib/detector';

interface LearningBadgeProps {
  state: BaselineState;
  /** Sliding window length, for the "filling first window" wording. */
  windowSeconds?: number;
}

/**
 * Whether the detector is still learning its baseline or already monitoring.
 * Deliberately neutral: severity colours are reserved for alerts, and a
 * learning detector is expected, not a problem.
 */
export function LearningBadge({ state, windowSeconds }: LearningBadgeProps) {
  const phase = state.kind === 'ready' ? 'monitoring' : 'learning';
  const hint =
    phase === 'learning'
      ? 'Anomaly alerts start once the baseline has been learned'
      : 'Baseline learned; anomaly alerts are active';

  return (
    <span className={`learning-badge learning-badge--${phase}`} title={hint}>
      <span className="learning-badge__dot" aria-hidden="true" />
      <span className="visually-hidden">Detector: </span>
      {describeBaseline(state, windowSeconds)}
    </span>
  );
}
