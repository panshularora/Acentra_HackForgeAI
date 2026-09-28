import {
  arnResourceName,
  formatClock,
  formatCount,
  formatDuration,
  formatMultiple,
  formatPercent,
  formatRelative,
  formatScore,
} from './format';

describe('formatPercent', () => {
  it('renders a 0..1 rate as a percentage with one decimal', () => {
    expect(formatPercent(0.0218)).toBe('2.2%');
    expect(formatPercent(0.31)).toBe('31.0%');
  });

  it('keeps an extra digit for small non-zero rates so they never read as zero', () => {
    expect(formatPercent(0.004)).toBe('0.40%');
    expect(formatPercent(0)).toBe('0.0%');
  });

  it('shows an em dash for missing values', () => {
    expect(formatPercent(null)).toBe('\u2014');
    expect(formatPercent(undefined)).toBe('\u2014');
    expect(formatPercent(Number.NaN)).toBe('\u2014');
  });
});

describe('formatScore and formatCount', () => {
  it('formats scores to one decimal and counts with grouping', () => {
    expect(formatScore(9.44)).toBe('9.4');
    expect(formatScore(null)).toBe('\u2014');
    expect(formatCount(12345)).toBe('12,345');
  });
});

describe('formatMultiple', () => {
  it('expresses how far above baseline a value is', () => {
    expect(formatMultiple(0.31, 0.02)).toBe('16\u00d7');
    expect(formatMultiple(0.05, 0.02)).toBe('2.5\u00d7');
  });

  it('returns null when the comparison is not meaningful', () => {
    expect(formatMultiple(0.02, 0.02)).toBeNull();
    expect(formatMultiple(0.3, 0)).toBeNull();
    expect(formatMultiple(0.3, null)).toBeNull();
  });
});

describe('formatRelative', () => {
  const now = Date.parse('2026-09-28T13:10:00Z');

  it.each([
    ['2026-09-28T13:09:58Z', 'just now'],
    ['2026-09-28T13:09:18Z', '42s ago'],
    ['2026-09-28T13:03:00Z', '7m ago'],
    ['2026-09-28T10:10:00Z', '3h ago'],
    ['2026-09-26T13:10:00Z', '2d ago'],
  ])('%s -> %s', (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected);
  });
});

describe('formatDuration', () => {
  it.each([
    [45_000, '45s'],
    [252_000, '4m 12s'],
    [7_500_000, '2h 05m'],
  ])('%d ms -> %s', (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });

  it('rejects negative durations', () => {
    expect(formatDuration(-1)).toBe('\u2014');
  });
});

describe('formatClock', () => {
  it('renders 24-hour wall-clock time in the requested zone', () => {
    expect(formatClock('2026-09-28T13:05:10Z', { timeZone: 'Asia/Kolkata' })).toBe('18:35:10');
    expect(formatClock('2026-09-28T13:05:10Z', { timeZone: 'UTC', seconds: false })).toBe('13:05');
  });

  it('handles invalid input without throwing', () => {
    expect(formatClock('not a date')).toBe('\u2014');
  });
});

describe('arnResourceName', () => {
  it('extracts the resource name from an ARN', () => {
    expect(arnResourceName('arn:aws:sns:us-east-1:000000000000:claimswatch-alerts')).toBe(
      'claimswatch-alerts',
    );
    expect(arnResourceName(null)).toBeNull();
  });
});
