import type { Health } from '../types';

/**
 * Whether the backend is actually reading the log, as /api/health reports it.
 * Newer backends answer `status: "degraded"` with `ingest_error` set while the
 * ingest pipeline fails and retries; current main has no `ingest_error` and
 * always says "ok", which reads as healthy here.
 */
export type MonitoringStatus =
  { kind: 'unknown' } | { kind: 'ok' } | { kind: 'degraded'; error: string | null };

export function monitoringStatus(health: Health | null): MonitoringStatus {
  if (!health) return { kind: 'unknown' };
  const error =
    typeof health.ingest_error === 'string' && health.ingest_error.trim()
      ? health.ingest_error.trim()
      : null;
  if (health.status === 'degraded' || error !== null) return { kind: 'degraded', error };
  return { kind: 'ok' };
}
