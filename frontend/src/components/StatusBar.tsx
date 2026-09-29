import type { ConnectionState } from '../hooks/alertStreamReducer';
import { detectorTiming, type BaselineState } from '../lib/detector';
import { formatClock, formatRelative, timeZoneLabel } from '../lib/format';
import { streamFreshness } from '../lib/freshness';
import type { MonitoringStatus } from '../lib/health';
import { APP_NAME } from '../theme';
import type { Health } from '../types';
import { LearningBadge } from './LearningBadge';

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  connecting: 'Connecting',
  live: 'Live',
  reconnecting: 'Reconnecting',
};

const CONNECTION_TEXT: Record<ConnectionState, string> = {
  connecting: 'Connecting\u2026',
  live: 'Live',
  reconnecting: 'Reconnecting\u2026',
};

interface StatusBarProps {
  connection: ConnectionState;
  baseline: BaselineState;
  health: Health | null;
  now: number;
  monitoring?: MonitoringStatus;
  /** Newest stats bucket timestamp, used to tell live from delayed. */
  lastUpdate?: string;
  bucketSeconds?: number;
}

function liveLabel(
  connection: ConnectionState,
  lastUpdate: string | undefined,
  now: number,
  bucketSeconds: number,
): { text: string; tone: string; aria: string } {
  if (connection !== 'live') {
    return {
      text: CONNECTION_TEXT[connection],
      tone: connection,
      aria: CONNECTION_LABEL[connection],
    };
  }
  const freshness = streamFreshness(lastUpdate, now, bucketSeconds);
  if (freshness === 'delayed' || freshness === 'stale') {
    const age = lastUpdate ? formatRelative(lastUpdate, now) : '';
    return {
      text: freshness === 'stale' ? `Stale · ${age}` : `Live · delayed`,
      tone: freshness,
      aria: freshness === 'stale' ? `Stale, last bucket ${age}` : `Live, delayed, last bucket ${age}`,
    };
  }
  const age = lastUpdate ? formatRelative(lastUpdate, now) : '';
  return {
    text: age && age !== 'just now' ? `Live · ${age}` : 'Live',
    tone: 'live',
    aria: age ? `Live, last bucket ${age}` : 'Live',
  };
}

/** Product name, connection, detector phase and the clock. Delivery targets live in DeliveryPanel. */
export function StatusBar({
  connection,
  baseline,
  health,
  now,
  monitoring,
  lastUpdate,
  bucketSeconds = 10,
}: StatusBarProps) {
  const degraded = connection === 'live' && monitoring?.kind === 'degraded';
  const live = liveLabel(connection, lastUpdate, now, bucketSeconds);
  return (
    <header className="status-bar">
      <div className="status-bar__brand">
        <span className="status-bar__logo" aria-hidden="true" />
        <span className="status-bar__name">{APP_NAME}</span>
        <span className="status-bar__tagline">Medicaid claims · on-call</span>
      </div>
      <div className="status-bar__group">
        <span
          className={`connection connection--${live.tone}`}
          role="status"
          aria-label={`Live stream: ${live.aria}`}
        >
          <span className="connection__dot" aria-hidden="true" />
          {live.text}
        </span>
        {degraded ? (
          <span className="monitor-badge" title="The backend cannot read the log and is retrying">
            <span className="visually-hidden">Monitoring: </span>Ingest retrying
          </span>
        ) : (
          <LearningBadge state={baseline} windowSeconds={detectorTiming(health).window_seconds} />
        )}
        <span className="status-bar__clock mono">
          <time dateTime={new Date(now).toISOString()}>{formatClock(now)}</time>{' '}
          <span className="muted">{timeZoneLabel()}</span>
        </span>
      </div>
    </header>
  );
}
