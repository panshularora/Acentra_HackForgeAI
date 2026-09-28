import { makeHealth, makeStatsPoint, makeStatsSeries } from '../test/fixtures';
import type { LearningState } from '../types';
import {
  baselineFromLearning,
  baselineState,
  currentBaselineState,
  DEFAULT_DETECTOR_TIMING,
  describeBaseline,
  detectorLabel,
  detectorTiming,
  windowBuckets,
} from './detector';

describe('baselineState', () => {
  it('waits when there is no data yet', () => {
    expect(baselineState([])).toEqual({ kind: 'waiting' });
  });

  const cold = { baseline_median: null, band_upper: null, score: null };

  it('first reports the sliding window filling up', () => {
    const state = baselineState(makeStatsSeries(4, undefined, cold), 12, 6);
    expect(state).toEqual({ kind: 'filling', collected: 4, required: 6 });
    expect(describeBaseline(state)).toBe('Filling first 60s window, 4 of 6 buckets');
  });

  it('then counts baseline samples, starting with the bucket that fills the window', () => {
    expect(baselineState(makeStatsSeries(6, undefined, cold), 12, 6)).toEqual({
      kind: 'learning',
      collected: 1,
      required: 12,
    });
    const state = baselineState(makeStatsSeries(9, undefined, cold), 12, 6);
    expect(state).toEqual({ kind: 'learning', collected: 4, required: 12 });
    expect(describeBaseline(state)).toBe('Learning baseline, 4 of 12 buckets');
  });

  it('never reports more samples than required', () => {
    expect(baselineState(makeStatsSeries(40, undefined, cold), 12, 6)).toMatchObject({
      collected: 12,
    });
  });

  it('is ready as soon as the newest bucket carries a baseline', () => {
    expect(baselineState(makeStatsSeries(3))).toEqual({ kind: 'ready' });
  });

  it('restarts the count after a backend restart', () => {
    const warm = makeStatsSeries(5, '2026-09-28T13:00:00Z');
    const restarted = makeStatsSeries(2, '2026-09-28T13:05:00Z', cold);
    expect(baselineState([...warm, ...restarted], 12, 6)).toEqual({
      kind: 'filling',
      collected: 2,
      required: 6,
    });
  });
});

describe('detectorTiming', () => {
  it('uses the timing reported by /api/health', () => {
    const detector = { window_seconds: 120, bucket_seconds: 20, baseline_min_buckets: 4 };
    expect(detectorTiming(makeHealth({ detector }))).toEqual(detector);
  });

  it('falls back to the backend defaults before health has loaded', () => {
    expect(detectorTiming(null)).toEqual(DEFAULT_DETECTOR_TIMING);
  });

  it('derives the number of buckets per window', () => {
    expect(windowBuckets(DEFAULT_DETECTOR_TIMING)).toBe(6);
    expect(
      windowBuckets({ window_seconds: 120, bucket_seconds: 20, baseline_min_buckets: 4 }),
    ).toBe(6);
  });

  it('labels the filling phase with the configured window length', () => {
    expect(describeBaseline({ kind: 'filling', collected: 2, required: 6 }, 120)).toBe(
      'Filling first 120s window, 2 of 6 buckets',
    );
  });
});

describe('detectorLabel', () => {
  it('names each contract v2 detector', () => {
    expect(detectorLabel('error_spike')).toBe('Error spike');
    expect(detectorLabel('silence')).toBe('Silence');
    expect(detectorLabel('new_pattern')).toBe('New pattern');
    expect(detectorLabel('flow_break')).toBe('Flow break');
  });

  it('returns null when the backend sent no detector', () => {
    expect(detectorLabel(undefined)).toBeNull();
    expect(detectorLabel(null)).toBeNull();
    expect(detectorLabel('')).toBeNull();
  });

  it('humanises a detector this build does not know yet', () => {
    expect(detectorLabel('rate_drop')).toBe('Rate drop');
    expect(detectorLabel('toString')).toBe('ToString');
  });
});

describe('currentBaselineState', () => {
  const learning = (overrides: Partial<LearningState> = {}): LearningState => ({
    state: 'learning',
    buckets_seen: 4,
    buckets_needed: 6,
    templates: 21,
    ...overrides,
  });
  const cold = { baseline_median: null, band_upper: null, score: null };

  it('follows the learning object on the newest stats bucket', () => {
    const stats = [
      makeStatsPoint({ ts: '2026-09-28T13:05:00Z', learning: learning({ buckets_seen: 3 }) }),
      makeStatsPoint({ ts: '2026-09-28T13:05:10Z', learning: learning() }),
    ];
    const state = currentBaselineState(stats, makeHealth());
    expect(state).toEqual({ kind: 'learning', collected: 4, required: 6 });
    expect(describeBaseline(state)).toBe('Learning baseline, 4 of 6 buckets');
  });

  it('reports monitoring with the template count once ready', () => {
    const stats = [makeStatsPoint({ learning: learning({ state: 'ready', templates: 38 }) })];
    const state = currentBaselineState(stats, null);
    expect(state).toEqual({ kind: 'ready', templates: 38 });
    expect(describeBaseline(state)).toBe('Monitoring, 38 templates');
  });

  it('uses the /api/health learning object before any bucket has arrived', () => {
    const health = makeHealth({ learning: learning({ buckets_seen: 1 }) });
    expect(currentBaselineState([], health)).toEqual({
      kind: 'learning',
      collected: 1,
      required: 6,
    });
  });

  it('prefers the live bucket over the learning state /api/health reported on load', () => {
    const health = makeHealth({ learning: learning({ buckets_seen: 1 }) });
    const stats = [makeStatsPoint({ learning: learning({ state: 'ready' }) })];
    expect(currentBaselineState(stats, health)).toMatchObject({ kind: 'ready' });
  });

  it('estimates from the buckets and health timing when the backend sends no learning', () => {
    const health = makeHealth({
      detector: { window_seconds: 40, bucket_seconds: 10, baseline_min_buckets: 3 },
    });
    expect(currentBaselineState(makeStatsSeries(5, undefined, cold), health)).toEqual({
      kind: 'learning',
      collected: 2,
      required: 3,
    });
    expect(currentBaselineState(makeStatsSeries(2, undefined, { learning: null }), null)).toEqual({
      kind: 'ready',
    });
    expect(currentBaselineState([], null)).toEqual({ kind: 'waiting' });
  });
});

describe('baselineFromLearning', () => {
  it('never reports more buckets than needed', () => {
    expect(
      baselineFromLearning({
        state: 'learning',
        buckets_seen: 9,
        buckets_needed: 6,
        templates: 0,
      }),
    ).toEqual({ kind: 'learning', collected: 6, required: 6 });
  });
});

describe('describeBaseline once ready', () => {
  it('says monitoring, with the template count when known', () => {
    expect(describeBaseline({ kind: 'ready' })).toBe('Monitoring');
    expect(describeBaseline({ kind: 'ready', templates: 1 })).toBe('Monitoring, 1 template');
    expect(describeBaseline({ kind: 'ready', templates: 0 })).toBe('Monitoring, 0 templates');
  });
});
