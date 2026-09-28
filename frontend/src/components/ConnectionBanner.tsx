import type { ConnectionState } from '../hooks/alertStreamReducer';
import { formatClock } from '../lib/format';

interface ConnectionBannerProps {
  connection: ConnectionState;
  /** Timestamp of the newest bucket on screen, if any. */
  lastUpdate: string | undefined;
}

/**
 * Shown only while reconnecting after a drop, so nobody mistakes a frozen
 * chart for a quiet system.
 */
export function ConnectionBanner({ connection, lastUpdate }: ConnectionBannerProps) {
  if (connection !== 'reconnecting' || !lastUpdate) return null;
  return (
    <div className="connection-banner" role="alert">
      Connection to the backend lost. Showing data up to{' '}
      <time className="mono" dateTime={lastUpdate}>
        {formatClock(lastUpdate)}
      </time>
      ; reconnecting automatically.
    </div>
  );
}
