import { SEVERITY_LABEL } from '../lib/severity';
import type { Alert, Health, StatsPoint, WsMessage } from '../types';

/**
 * All state the dashboard derives from the backend, and the pure reducer
 * that maintains it. Kept separate from the WebSocket plumbing in
 * useAlertStream so the merge rules can be tested without any I/O.
 */

/** How much stats history the chart keeps, measured back from the newest bucket. */
export const STATS_WINDOW_MS = 10 * 60 * 1000;
/** Upper bound on alerts held in memory; the oldest are dropped first. */
export const MAX_ALERTS = 200;

export type ConnectionState = 'connecting' | 'live' | 'reconnecting';

export interface AlertStreamState {
  connection: ConnectionState;
  health: Health | null;
  /** Oldest first, never older than STATS_WINDOW_MS behind the newest point. */
  stats: StatsPoint[];
  /** Newest first by opened_at, unique by id. */
  alerts: Alert[];
  /**
   * When each alert was first seen on the live socket (epoch ms). Alerts that
   * arrive through REST backfill are absent, so only genuinely new incidents
   * get the arrival animation.
   */
  liveArrivals: Record<string, number>;
  /** Latest text for the screen-reader live region. */
  announcement: string;
}

export type AlertStreamAction =
  | { type: 'connection'; state: ConnectionState }
  | { type: 'health'; health: Health }
  | { type: 'backfill'; stats: StatsPoint[]; alerts: Alert[] }
  | { type: 'message'; message: WsMessage; receivedAt: number }
  | { type: 'alertUpdated'; alert: Alert };

export const initialAlertStreamState: AlertStreamState = {
  connection: 'connecting',
  health: null,
  stats: [],
  alerts: [],
  liveArrivals: {},
  announcement: '',
};

/** Merges stats by bucket timestamp, keeps them ordered and trims to the window. */
export function mergeStats(existing: StatsPoint[], incoming: StatsPoint[]): StatsPoint[] {
  if (incoming.length === 0) return existing;
  const byTs = new Map<string, StatsPoint>();
  for (const point of existing) byTs.set(point.ts, point);
  for (const point of incoming) byTs.set(point.ts, point);

  const merged = [...byTs.values()].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
  const newest = merged[merged.length - 1];
  if (!newest) return merged;
  const cutoff = Date.parse(newest.ts) - STATS_WINDOW_MS;
  return merged.filter((point) => Date.parse(point.ts) >= cutoff);
}

/**
 * Inserts or replaces an alert by id. A stale copy (older updated_at, e.g. a
 * REST response that raced a WebSocket update) never overwrites a newer one.
 */
export function upsertAlert(alerts: Alert[], incoming: Alert): Alert[] {
  const current = alerts.find((a) => a.id === incoming.id);
  if (current && Date.parse(current.updated_at) > Date.parse(incoming.updated_at)) {
    return alerts;
  }
  const next = current
    ? alerts.map((a) => (a.id === incoming.id ? incoming : a))
    : [incoming, ...alerts];
  return next
    .sort((a, b) => Date.parse(b.opened_at) - Date.parse(a.opened_at))
    .slice(0, MAX_ALERTS);
}

function announce(previous: Alert | undefined, next: Alert): string | null {
  const label = SEVERITY_LABEL[next.severity];
  if (!previous) return `New ${label} alert: ${next.summary}`;
  if (previous.status === 'open' && next.status === 'resolved') {
    return `Resolved ${label} alert: ${next.summary}`;
  }
  if (previous.severity !== next.severity) return `Alert escalated to ${label}: ${next.summary}`;
  return null;
}

export function alertStreamReducer(
  state: AlertStreamState,
  action: AlertStreamAction,
): AlertStreamState {
  switch (action.type) {
    case 'connection':
      return state.connection === action.state ? state : { ...state, connection: action.state };

    case 'health':
      return { ...state, health: action.health };

    case 'backfill':
      return {
        ...state,
        stats: mergeStats(state.stats, action.stats),
        alerts: action.alerts.reduce(upsertAlert, state.alerts),
      };

    case 'alertUpdated':
      return { ...state, alerts: upsertAlert(state.alerts, action.alert) };

    case 'message': {
      const { message, receivedAt } = action;
      if (message.type === 'stats') {
        return { ...state, stats: mergeStats(state.stats, [message.data]) };
      }
      const alert = message.data;
      const previous = state.alerts.find((a) => a.id === alert.id);
      const alerts = upsertAlert(state.alerts, alert);
      if (alerts === state.alerts) return state;
      const announcement = announce(previous, alert);
      return {
        ...state,
        alerts,
        liveArrivals: previous
          ? state.liveArrivals
          : { ...state.liveArrivals, [alert.id]: receivedAt },
        announcement: announcement ?? state.announcement,
      };
    }
  }
}

/**
 * Validates an incoming frame just enough to route it. Unknown message types
 * are ignored rather than treated as errors, so the backend can add new ones
 * without breaking older dashboards.
 */
export function parseWsMessage(raw: unknown): WsMessage | null {
  if (typeof raw !== 'string') return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== 'object' || value === null) return null;
  const { type, data } = value as { type?: unknown; data?: unknown };
  if (typeof data !== 'object' || data === null) return null;
  if (type === 'stats' || type === 'alert') return value as WsMessage;
  return null;
}
