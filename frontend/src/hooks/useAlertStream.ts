import { useCallback, useEffect, useReducer } from 'react';
import {
  acknowledgeAlert,
  fetchAlerts,
  fetchHealth,
  fetchStats,
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
 * Exponential backoff with ±20% jitter, so a fleet of dashboards does not
 * reconnect in lockstep after a backend restart: ~1s, 2s, 4s, 8s, then 15s.
 */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const exponential = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** attempt);
  return Math.round(exponential * (0.8 + 0.4 * random()));
}

export interface AlertStream extends AlertStreamState {
  acknowledge: (id: string) => Promise<void>;
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
        // The live stream keeps working without history; the next
        // reconnect will try the backfill again.
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

    connect();

    return () => {
      disposed = true;
      clearTimeout(retryTimer);
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

  return { ...state, acknowledge };
}
