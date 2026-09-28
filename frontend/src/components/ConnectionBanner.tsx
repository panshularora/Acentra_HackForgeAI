import type { ConnectionState } from '../hooks/alertStreamReducer';
import { formatClock } from '../lib/format';
import type { MonitoringStatus } from '../lib/health';

interface ConnectionBannerProps {
  connection: ConnectionState;
  /** Timestamp of the newest bucket on screen, if any. */
  lastUpdate: string | undefined;
  /** From /api/health; "degraded" means connected but not reading the log. */
  monitoring?: MonitoringStatus;
}

/**
 * One line under the header, only when something is off:
 * - reconnecting: the backend is unreachable, so everything on screen is stale;
 * - degraded: the backend answers but its log ingest is failing and retrying.
 * The two are worded differently on purpose; they need different reactions.
 */
export function ConnectionBanner({ connection, lastUpdate, monitoring }: ConnectionBannerProps) {
  if (connection === 'reconnecting') {
    return (
      <div className="connection-banner connection-banner--offline" role="alert">
        {lastUpdate ? (
          <>
            Connection to the backend lost. Showing data up to{' '}
            <time className="mono" dateTime={lastUpdate}>
              {formatClock(lastUpdate)}
            </time>
            ; reconnecting automatically.
          </>
        ) : (
          <>Can&rsquo;t reach the backend yet; retrying automatically.</>
        )}
      </div>
    );
  }
  if (connection === 'live' && monitoring?.kind === 'degraded') {
    return (
      <div className="connection-banner connection-banner--degraded" role="status">
        Monitoring degraded: the backend cannot read the log and is retrying.
        {monitoring.error && (
          <>
            {' '}
            <span className="connection-banner__error mono">{monitoring.error}</span>
          </>
        )}
      </div>
    );
  }
  return null;
}
