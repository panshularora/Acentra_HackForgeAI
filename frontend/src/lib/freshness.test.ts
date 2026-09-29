import { streamAgeMs, streamFreshness } from './freshness';

const TS = '2026-09-28T13:05:10Z';
const NOW = Date.parse(TS);

describe('streamFreshness', () => {
  it('is unknown without a bucket', () => {
    expect(streamFreshness(undefined, NOW, 10)).toBe('unknown');
    expect(streamAgeMs(undefined, NOW)).toBeNaN();
  });

  it('is fresh within 1.5 buckets', () => {
    expect(streamFreshness(TS, NOW + 10_000, 10)).toBe('fresh');
    expect(streamFreshness(TS, NOW + 15_000, 10)).toBe('fresh');
  });

  it('is delayed between 1.5 and 4 buckets', () => {
    expect(streamFreshness(TS, NOW + 16_000, 10)).toBe('delayed');
    expect(streamFreshness(TS, NOW + 40_000, 10)).toBe('delayed');
  });

  it('is stale after 4 buckets', () => {
    expect(streamFreshness(TS, NOW + 40_001, 10)).toBe('stale');
  });
});
