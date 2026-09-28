import { act, renderHook, waitFor } from '@testing-library/react';
import { makeAlert, makeHealth, makeStatsPoint, makeStatsSeries } from '../test/fixtures';
import type { Alert, Health, StatsPoint } from '../types';
import { backoffDelay, HEALTH_POLL_MS, useAlertStream } from './useAlertStream';

/** Minimal stand-in for the browser WebSocket that tests drive by hand. */
class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readonly url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  static latest(): MockWebSocket {
    const socket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    if (!socket) throw new Error('no socket created');
    return socket;
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  send(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  /** Server-side drop: error then close, as browsers report it. */
  drop() {
    this.readyState = MockWebSocket.CLOSED;
    this.onerror?.();
    this.onclose?.();
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
  }
}

let health: Health = makeHealth();

let backend: { stats: StatsPoint[]; alerts: Alert[] };
let fetchMock: ReturnType<typeof vi.fn>;

function respond(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
}

beforeEach(() => {
  MockWebSocket.instances = [];
  health = makeHealth();
  backend = { stats: [], alerts: [] };
  fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith('/api/health')) return respond(health);
    if (url.startsWith('/api/stats')) return respond({ points: backend.stats });
    if (url.startsWith('/api/alerts')) return respond({ alerts: backend.alerts });
    return Promise.resolve(new Response('not found', { status: 404 }));
  });
  vi.stubGlobal('WebSocket', MockWebSocket);
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const fetchedPaths = () => fetchMock.mock.calls.map(([input]) => String(input));

describe('useAlertStream', () => {
  it('connects, backfills history on open, then applies live messages', async () => {
    backend.stats = makeStatsSeries(3, '2026-09-28T13:05:00Z');
    backend.alerts = [makeAlert({ id: 'history' })];

    const { result } = renderHook(() => useAlertStream('ws://test/ws'));
    expect(result.current.connection).toBe('connecting');
    expect(MockWebSocket.latest().url).toBe('ws://test/ws');

    act(() => MockWebSocket.latest().open());
    expect(result.current.connection).toBe('live');

    await waitFor(() => expect(result.current.stats).toHaveLength(3));
    expect(result.current.alerts.map((a) => a.id)).toEqual(['history']);
    expect(result.current.health?.log_path).toBe('logs/app.log');
    expect(fetchedPaths()).toEqual(
      expect.arrayContaining(['/api/health', '/api/stats?minutes=10', '/api/alerts?limit=50']),
    );

    act(() =>
      MockWebSocket.latest().send({
        type: 'stats',
        data: makeStatsPoint({ ts: '2026-09-28T13:05:10Z', severity: 'HIGH' }),
      }),
    );
    act(() =>
      MockWebSocket.latest().send({
        type: 'alert',
        data: makeAlert({ id: 'live', opened_at: '2026-09-28T13:05:10Z' }),
      }),
    );
    expect(result.current.stats).toHaveLength(4);
    expect(result.current.alerts.map((a) => a.id)).toEqual(['live', 'history']);
    expect(result.current.liveArrivals).toHaveProperty('live');
    expect(result.current.liveArrivals).not.toHaveProperty('history');
  });

  it('reconnects with backoff after a drop and backfills what it missed', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = renderHook(() => useAlertStream('ws://test/ws'));
    act(() => MockWebSocket.latest().open());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    // While the socket is down, the backend keeps detecting.
    backend.stats = makeStatsSeries(2, '2026-09-28T13:06:00Z');
    backend.alerts = [makeAlert({ id: 'while-offline' })];

    act(() => MockWebSocket.latest().drop());
    expect(result.current.connection).toBe('reconnecting');
    expect(MockWebSocket.instances).toHaveLength(1);

    // First retry is ~1s (with jitter at most 1.2s).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_300);
    });
    expect(MockWebSocket.instances).toHaveLength(2);

    act(() => MockWebSocket.latest().open());
    expect(result.current.connection).toBe('live');
    await waitFor(() => expect(result.current.alerts.map((a) => a.id)).toEqual(['while-offline']));
    expect(result.current.stats).toHaveLength(2);
  });

  it('backs off further on consecutive failures', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderHook(() => useAlertStream('ws://test/ws'));

    act(() => MockWebSocket.latest().drop()); // attempt 0 -> ~1s
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_300);
    });
    expect(MockWebSocket.instances).toHaveLength(2);

    act(() => MockWebSocket.latest().drop()); // attempt 1 -> ~2s
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_300);
    });
    expect(MockWebSocket.instances).toHaveLength(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_200);
    });
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it('stays live when the history backfill fails', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(new Response('boom', { status: 500 })));
    const { result } = renderHook(() => useAlertStream('ws://test/ws'));
    act(() => MockWebSocket.latest().open());
    act(() => MockWebSocket.latest().send({ type: 'stats', data: makeStatsPoint() }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(result.current.connection).toBe('live');
    expect(result.current.stats).toHaveLength(1);
  });

  it('polls /api/health while live and picks up a degraded backend', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = renderHook(() => useAlertStream('ws://test/ws'));
    act(() => MockWebSocket.latest().open());
    await waitFor(() => expect(result.current.health?.status).toBe('ok'));

    // Ingest starts failing; the socket stays up, only health can tell.
    health = makeHealth({ status: 'degraded', ingest_error: 'PermissionError: logs/app.log' });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEALTH_POLL_MS + 50);
    });
    expect(result.current.connection).toBe('live');
    expect(result.current.health).toMatchObject({
      status: 'degraded',
      ingest_error: 'PermissionError: logs/app.log',
    });

    // Once the socket drops, polling stops until the next connect.
    act(() => MockWebSocket.latest().drop());
    const healthCalls = () => fetchedPaths().filter((p) => p === '/api/health').length;
    const before = healthCalls();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEALTH_POLL_MS * 2);
    });
    // Only reconnect attempts happen (no open), so no further health reads.
    expect(healthCalls()).toBe(before);
  });

  it('stops reconnecting once unmounted', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { unmount } = renderHook(() => useAlertStream('ws://test/ws'));
    act(() => MockWebSocket.latest().open());
    unmount();
    MockWebSocket.latest().drop();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });
});

describe('backoffDelay', () => {
  it('doubles per attempt and caps at 15 seconds', () => {
    const noJitter = () => 0.5;
    expect([0, 1, 2, 3, 4, 5, 10].map((n) => backoffDelay(n, noJitter))).toEqual([
      1_000, 2_000, 4_000, 8_000, 15_000, 15_000, 15_000,
    ]);
  });

  it('applies at most 20% jitter either way', () => {
    expect(backoffDelay(0, () => 0)).toBe(800);
    expect(backoffDelay(0, () => 1)).toBe(1_200);
  });
});
