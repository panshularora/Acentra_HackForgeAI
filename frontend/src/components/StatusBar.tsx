import type { ConnectionState } from '../hooks/alertStreamReducer';
import { detectorTiming, type BaselineState } from '../lib/detector';
import { formatClock, timeZoneLabel } from '../lib/format';
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
}

/** Product name, connection, detector phase and the clock. Delivery targets live in DeliveryPanel. */
export function StatusBar({ connection, baseline, health, now, monitoring }: StatusBarProps) {
  const degraded = connection === 'live' && monitoring?.kind === 'degraded';
  return (
    <header className="status-bar">
      <div className="status-bar__brand">
        <span className="status-bar__logo" aria-hidden="true" />
        <span className="status-bar__name">{APP_NAME}</span>
        <span className="status-bar__tagline">Real-time log anomaly detection</span>
      </div>
      <div className="status-bar__group">
        <span
          className={`connection connection--${connection}`}
          role="status"
          aria-label={`Live stream: ${CONNECTION_LABEL[connection]}`}
        >
          <span className="connection__dot" aria-hidden="true" />
          {CONNECTION_TEXT[connection]}
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
