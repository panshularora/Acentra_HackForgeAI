import { useCallback, useEffect, useReducer } from 'react';
import {
  acknowledgeAlert,
  fetchAlerts,
  fetchHealth,
  fetchStats,
  retryDelivery,
  alertStreamUrl,
} from '../api/client';
import {
  initialAlertStreamState,
  alertStreamReducer,
  parseWsMessage,
  type AlertStreamState,
} from './alertStreamReducer';

const HISTORY_MINUTES = 10;
const ALERT_HISTORY_LIMIT = 50;
const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS = 15_000;
/**
 * How often /api/health is re-read while the socket is live. The socket only
 * carries stats and alerts, so this is how the dashboard learns that ingest
 * is failing (a "degraded" backend) while the connection itself is fine.
 */
export const HEALTH_POLL_MS = 5_000;

/**
 * Exponential backoff with ±20% jitter, so a fleet of dashboards does not
 * reconnect in lockstep after a backend restart: ~1s, 2s, 4s, 8s, then 15s.
 */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const exponential = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** attempt);
  return Math.round(exponential * (0.8 + 0.4 * random()));
}

export interface AlertStream extends AlertStreamState {
  acknowledge: (id: string) => Promise<void>;
  retryDelivery: () => Promise<number>;
}

/**
 * Subscribes to the backend's /ws stream and keeps dashboard state current.
 *
 * On every (re)connect it backfills from REST, so anything that happened
 * while the socket was down (missed buckets, alerts that opened or resolved)
 * is filled in. The reducer de-duplicates, so overlap with live messages is
 * harmless.
 */
export function useAlertStream(url: string = alertStreamUrl()): AlertStream {
  const [state, dispatch] = useReducer(alertStreamReducer, initialAlertStreamState);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let disposed = false;
    const requests = new AbortController();

    const backfill = async () => {
      try {
        const [health, stats, alerts] = await Promise.all([
          fetchHealth(requests.signal),
          fetchStats(HISTORY_MINUTES, requests.signal),
          fetchAlerts(ALERT_HISTORY_LIMIT, requests.signal),
        ]);
        if (disposed) return;
        dispatch({ type: 'health', health });
        dispatch({ type: 'backfill', stats, alerts });
      } catch {
        // REST can fail while the socket is still up (or the other way around);
        // the next poll or reconnect tries again.
      }
    };

    const pollHealth = async () => {
      try {
        const health = await fetchHealth(requests.signal);
        if (!disposed) dispatch({ type: 'health', health });
      } catch {
        // Keep the last known health; a dead backend shows up as a socket close.
      }
    };

    const scheduleReconnect = () => {
      dispatch({ type: 'connection', state: 'reconnecting' });
      retryTimer = setTimeout(connect, backoffDelay(attempt));
      attempt += 1;
    };

    function connect() {
      if (disposed) return;
      const ws = new WebSocket(url);
      socket = ws;

      ws.onopen = () => {
        attempt = 0;
        dispatch({ type: 'connection', state: 'live' });
        void backfill();
      };
      ws.onmessage = (event: MessageEvent) => {
        const message = parseWsMessage(event.data);
        if (message) dispatch({ type: 'message', message, receivedAt: Date.now() });
      };
      ws.onclose = () => {
        if (disposed || socket !== ws) return;
        socket = null;
        scheduleReconnect();
      };
      // Errors are always followed by a close event, which drives the retry.
      ws.onerror = () => undefined;
    }

    // History and health do not wait for the socket: a dashboard whose
    // WebSocket proxy is down still shows the last incidents from REST, and
    // ingest degradation is visible while reconnecting.
    void backfill();
    const healthTimer = setInterval(() => void pollHealth(), HEALTH_POLL_MS);
    connect();

    return () => {
      disposed = true;
      clearTimeout(retryTimer);
      clearInterval(healthTimer);
      requests.abort();
      if (socket?.readyState === WebSocket.CONNECTING) {
        // Closing mid-handshake logs a browser warning; close once it opens.
        const pending = socket;
        pending.onmessage = null;
        pending.onopen = () => pending.close();
      } else {
        socket?.close();
      }
    };
  }, [url]);

  const acknowledge = useCallback(async (id: string) => {
    const alert = await acknowledgeAlert(id);
    dispatch({ type: 'alertUpdated', alert });
  }, []);

  const retry = useCallback(async () => {
    const result = await retryDelivery();
    return result.queued;
  }, []);

  return { ...state, acknowledge, retryDelivery: retry };
}
