import { makeAlert, makeStatsPoint, makeStatsSeries, nth } from '../test/fixtures';
import type { StatsPoint, WsMessage } from '../types';
import {
  MAX_ALERTS,
  STATS_WINDOW_MS,
  alertStreamReducer,
  initialAlertStreamState,
  mergeStats,
  parseWsMessage,
  upsertAlert,
  type AlertStreamState,
} from './alertStreamReducer';

const receive = (state: AlertStreamState, message: WsMessage, receivedAt = 1_000) =>
  alertStreamReducer(state, { type: 'message', message, receivedAt });

describe('mergeStats', () => {
  it('appends new buckets in timestamp order and de-duplicates by ts', () => {
    const [a, b, c] = makeStatsSeries(3) as [StatsPoint, StatsPoint, StatsPoint];
    const updatedB = { ...b, total: 999 };
    const merged = mergeStats([a, b], [c, updatedB]);
    expect(merged.map((p) => p.ts)).toEqual([a.ts, b.ts, c.ts]);
    expect(nth(merged, 1).total).toBe(999);
  });

  it('trims buckets older than the window behind the newest point', () => {
    const series = makeStatsSeries(70); // 11.5 minutes of 10-second buckets
    const merged = mergeStats([], series);
    const newest = Date.parse(nth(merged, -1).ts);
    expect(Date.parse(nth(merged, 0).ts)).toBeGreaterThanOrEqual(newest - STATS_WINDOW_MS);
    expect(merged).toHaveLength(STATS_WINDOW_MS / 10_000 + 1);
  });

  it('returns the same array when there is nothing to merge', () => {
    const existing = makeStatsSeries(2);
    expect(mergeStats(existing, [])).toBe(existing);
  });
});

describe('upsertAlert', () => {
  it('inserts new alerts newest first by opened_at', () => {
    const older = makeAlert({ id: 'old', opened_at: '2026-09-28T12:00:00Z' });
    const newer = makeAlert({ id: 'new', opened_at: '2026-09-28T13:00:00Z' });
    expect(upsertAlert([older], newer).map((a) => a.id)).toEqual(['new', 'old']);
    expect(upsertAlert([newer], older).map((a) => a.id)).toEqual(['new', 'old']);
  });

  it('replaces an existing alert with a newer version', () => {
    const open = makeAlert();
    const resolved = makeAlert({
      status: 'resolved',
      updated_at: '2026-09-28T13:08:00Z',
      resolved_at: '2026-09-28T13:08:00Z',
    });
    const next = upsertAlert([open], resolved);
    expect(next).toHaveLength(1);
    expect(nth(next, 0).status).toBe('resolved');
  });

  it('ignores a stale copy that raced a newer update', () => {
    const current = makeAlert({ updated_at: '2026-09-28T13:08:00Z', acknowledged: true });
    const stale = makeAlert({ updated_at: '2026-09-28T13:06:00Z', acknowledged: false });
    const list = [current];
    expect(upsertAlert(list, stale)).toBe(list);
  });

  it(`keeps at most ${MAX_ALERTS} alerts`, () => {
    let alerts = [makeAlert({ id: 'first', opened_at: '2026-09-28T00:00:00Z' })];
    for (let i = 0; i < MAX_ALERTS; i++) {
      alerts = upsertAlert(
        alerts,
        makeAlert({
          id: `a${i}`,
          opened_at: new Date(Date.UTC(2026, 8, 28, 1, 0, i)).toISOString(),
        }),
      );
    }
    expect(alerts).toHaveLength(MAX_ALERTS);
    expect(alerts.some((a) => a.id === 'first')).toBe(false);
  });
});

describe('alertStreamReducer', () => {
  it('routes stats messages into the stats series', () => {
    const point = makeStatsPoint();
    const state = receive(initialAlertStreamState, { type: 'stats', data: point });
    expect(state.stats).toEqual([point]);
    expect(state.alerts).toEqual([]);
  });

  it('routes alert messages into the feed and records live arrival time', () => {
    const alert = makeAlert();
    const state = receive(initialAlertStreamState, { type: 'alert', data: alert }, 42);
    expect(state.alerts).toEqual([alert]);
    expect(state.liveArrivals).toEqual({ [alert.id]: 42 });
    expect(state.announcement).toBe(`New Critical alert: ${alert.summary}`);
  });

  it('keeps the original arrival time when an alert is updated', () => {
    const first = receive(initialAlertStreamState, { type: 'alert', data: makeAlert() }, 42);
    const updated = makeAlert({
      status: 'resolved',
      updated_at: '2026-09-28T13:09:00Z',
      resolved_at: '2026-09-28T13:09:00Z',
    });
    const state = receive(first, { type: 'alert', data: updated }, 99);
    expect(state.liveArrivals).toEqual({ [updated.id]: 42 });
    expect(state.announcement).toMatch(/^Resolved Critical alert/);
  });

  it('announces escalations', () => {
    const first = receive(initialAlertStreamState, {
      type: 'alert',
      data: makeAlert({ severity: 'WARNING' }),
    });
    const state = receive(first, {
      type: 'alert',
      data: makeAlert({ severity: 'HIGH', updated_at: '2026-09-28T13:06:00Z' }),
    });
    expect(state.announcement).toMatch(/^Alert escalated to High/);
  });

  it('does not treat backfilled alerts as live arrivals', () => {
    const state = alertStreamReducer(initialAlertStreamState, {
      type: 'backfill',
      stats: makeStatsSeries(3),
      alerts: [makeAlert({ id: 'x' }), makeAlert({ id: 'y' })],
    });
    expect(state.stats).toHaveLength(3);
    expect(state.alerts.map((a) => a.id).sort()).toEqual(['x', 'y']);
    expect(state.liveArrivals).toEqual({});
    expect(state.announcement).toBe('');
  });

  it('merges backfill with data already received live', () => {
    const [a, b, c] = makeStatsSeries(3) as [StatsPoint, StatsPoint, StatsPoint];
    const live = receive(initialAlertStreamState, { type: 'stats', data: c });
    const state = alertStreamReducer(live, { type: 'backfill', stats: [a, b, c], alerts: [] });
    expect(state.stats.map((p) => p.ts)).toEqual([a.ts, b.ts, c.ts]);
  });

  it('tracks connection state without churning identical updates', () => {
    const live = alertStreamReducer(initialAlertStreamState, { type: 'connection', state: 'live' });
    expect(live.connection).toBe('live');
    expect(alertStreamReducer(live, { type: 'connection', state: 'live' })).toBe(live);
  });
});

describe('parseWsMessage', () => {
  it('accepts stats and alert frames', () => {
    const frame = JSON.stringify({ type: 'stats', data: makeStatsPoint() });
    expect(parseWsMessage(frame)).toMatchObject({ type: 'stats' });
  });

  it.each([
    ['not json', '{'],
    ['unknown type', JSON.stringify({ type: 'ping', data: {} })],
    ['missing data', JSON.stringify({ type: 'alert' })],
    ['non-string frame', new ArrayBuffer(4)],
  ])('ignores %s', (_label, frame) => {
    expect(parseWsMessage(frame)).toBeNull();
  });
});
