import type { Alert, Health, StatsPoint } from '../types';

/** Builders for realistic contract objects; override only what a test cares about. */

export function makeStatsPoint(overrides: Partial<StatsPoint> = {}): StatsPoint {
  return {
    ts: '2026-09-28T13:05:10Z',
    total: 412,
    errors: 9,
    error_rate: 0.0218,
    baseline_median: 0.019,
    band_upper: 0.031,
    score: 0.8,
    severity: null,
    ...overrides,
  };
}

/** `count` consecutive 10-second buckets ending at `endTs`. */
export function makeStatsSeries(
  count: number,
  endTs = '2026-09-28T13:05:10Z',
  overrides: Partial<StatsPoint> = {},
): StatsPoint[] {
  const end = Date.parse(endTs);
  return Array.from({ length: count }, (_, i) =>
    makeStatsPoint({
      ts: new Date(end - (count - 1 - i) * 10_000).toISOString(),
      ...overrides,
    }),
  );
}

export function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 'a3f9c2e1',
    status: 'open',
    severity: 'CRITICAL',
    score: 9.4,
    error_rate: 0.31,
    baseline_median: 0.02,
    opened_at: '2026-09-28T13:05:00Z',
    updated_at: '2026-09-28T13:05:10Z',
    resolved_at: null,
    summary: '94% of errors come from claim-adjudication: DB connection timeout',
    top_contributors: {
      services: [{ value: 'claim-adjudication', count: 212, share: 0.94 }],
      messages: [
        { value: 'DB connection timeout for member <MEMBER_ID>', count: 200, share: 0.89 },
      ],
      source_ips: [{ value: '10.4.2.17', count: 310, share: 0.97 }],
    },
    sample_lines: [
      '2026-09-28T13:05:03Z ERROR claim-adjudication DB connection timeout for member <MEMBER_ID>',
    ],
    acknowledged: false,
    delivery: {
      sns: { status: 'sent', message_id: '5f1c8e2a-7b3d-4c1e-9a0f-2d6b8e4c1a7f', error: null },
      cloudwatch: { status: 'sent', error: null },
    },
    ...overrides,
  };
}

/** An alert carrying every contract v2 field, as the template-aware backend sends it. */
export function makeExplainedAlert(overrides: Partial<Alert> = {}): Alert {
  return makeAlert({
    detector: 'error_spike',
    template: {
      id: 't-17',
      text: 'DB connection timeout for member <*> after <*>ms',
      service: 'claim-adjudication',
    },
    baseline_band: { median: 1, upper: 4, unit: 'errors/60s' },
    observed: 212,
    first_bad_line:
      '2026-09-28T13:04:58Z ERROR claim-adjudication ip=10.4.2.17 DB connection timeout for member <MEMBER_ID> after 5000ms',
    params: [
      { name: 'source_ip', value: '10.4.2.17', count: 206, share: 0.97 },
      { name: 'timeout_ms', value: '5000', count: 212, share: 1 },
      { name: 'member', value: '<MEMBER_ID>', count: 212, share: 1 },
      { name: 'claim', value: '<CLAIM_ID>', count: 212, share: 1 },
    ],
    ...overrides,
  });
}

/** Element at `index` (negative counts from the end); throws instead of returning undefined. */
export function nth<T>(items: readonly T[], index: number): T {
  const item = items.at(index);
  if (item === undefined) throw new Error(`no item at index ${index}`);
  return item;
}

export function makeHealth(overrides: Partial<Health> = {}): Health {
  return {
    status: 'ok',
    app: 'ClaimsWatch',
    log_path: 'logs/app.log',
    tailer_offset: 0,
    aws: { sns_topic_arn: null, cloudwatch_log_group: null, endpoint: null },
    detector: { window_seconds: 60, bucket_seconds: 10, baseline_min_buckets: 6 },
    pipeline: { parsed_lines: 0, malformed_lines: 0, baseline_warm: false, websocket_clients: 0 },
    ...overrides,
  };
}
