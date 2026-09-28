import type { Alert, Health, StatsPoint } from '../types';

/**
 * Thin fetch wrappers for the REST side of the contract. All paths are
 * relative: in development Vite proxies /api to the backend, in production
 * nginx does, so the dashboard never needs to know the backend's address.
 */

const API_BASE: string = import.meta.env.VITE_API_BASE ?? '';

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      `${init?.method ?? 'GET'} ${path} failed: ${response.status}`,
    );
  }
  return (await response.json()) as T;
}

/**
 * /api/health. While ingest is failing, newer backends answer 200 with
 * `status: "degraded"`. Should a proxy or a later version turn that into a
 * non-2xx that still carries the JSON body, the body is used anyway, so the
 * dashboard shows "degraded" rather than treating the backend as unreachable.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch(`${API_BASE}/api/health`, {
    signal,
    headers: { Accept: 'application/json' },
  });
  if (response.ok) return (await response.json()) as Health;
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON: fall through to the error below.
  }
  if (body && typeof body === 'object' && 'status' in body) {
    const health = body as Health;
    // A 5xx that still says "ok" is not ok.
    return health.status === 'ok' ? { ...health, status: 'degraded' } : health;
  }
  throw new ApiError(response.status, `GET /api/health failed: ${response.status}`);
}

/** Stats buckets for the last `minutes`, oldest first. */
export async function fetchStats(minutes = 10, signal?: AbortSignal): Promise<StatsPoint[]> {
  const body = await request<{ points: StatsPoint[] }>(`/api/stats?minutes=${minutes}`, { signal });
  return body.points;
}

/** Most recent alerts, newest first by opened_at. */
export async function fetchAlerts(limit = 50, signal?: AbortSignal): Promise<Alert[]> {
  const body = await request<{ alerts: Alert[] }>(`/api/alerts?limit=${limit}`, { signal });
  return body.alerts;
}

export function acknowledgeAlert(id: string): Promise<Alert> {
  return request<Alert>(`/api/alerts/${encodeURIComponent(id)}/ack`, { method: 'POST' });
}

/** WebSocket endpoint on the same origin as the page (proxied like /api). */
export function alertStreamUrl(location: Location = window.location): string {
  const override: string | undefined = import.meta.env.VITE_WS_URL;
  if (override) return override;
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${location.host}/ws`;
}
