import { makeStatsSeries } from '../test/fixtures';
import { baselineState, describeBaseline } from './detector';

describe('baselineState', () => {
  it('waits when there is no data yet', () => {
    expect(baselineState([])).toEqual({ kind: 'waiting' });
  });

  it('reports learning progress from the trailing run of buckets without a baseline', () => {
    const stats = makeStatsSeries(4, undefined, {
      baseline_median: null,
      band_upper: null,
      score: null,
    });
    const state = baselineState(stats, 12);
    expect(state).toEqual({ kind: 'learning', collected: 4, required: 12 });
    expect(describeBaseline(state)).toBe('Learning baseline, 4 of 12 buckets');
  });

  it('is ready as soon as the newest bucket carries a baseline', () => {
    expect(baselineState(makeStatsSeries(3))).toEqual({ kind: 'ready' });
  });

  it('restarts the count after a backend restart', () => {
    const warm = makeStatsSeries(5, '2026-09-28T13:00:00Z');
    const cold = makeStatsSeries(2, '2026-09-28T13:05:00Z', {
      baseline_median: null,
      band_upper: null,
    });
    expect(baselineState([...warm, ...cold], 12)).toMatchObject({ collected: 2 });
  });
});
