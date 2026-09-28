import type { ConnectionState } from '../hooks/alertStreamReducer';
import { describeBaseline, type BaselineState } from '../lib/detector';
import { arnResourceName, formatClock, timeZoneLabel } from '../lib/format';
import { APP_NAME } from '../theme';
import type { Health } from '../types';

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  connecting: 'Connecting',
  live: 'Live',
  reconnecting: 'Reconnecting',
};

interface StatusBarProps {
  connection: ConnectionState;
  baseline: BaselineState;
  health: Health | null;
  now: number;
}

export function StatusBar({ connection, baseline, health, now }: StatusBarProps) {
  const snsTopic = arnResourceName(health?.aws.sns_topic_arn);
  const logGroup = health?.aws.cloudwatch_log_group ?? null;

  return (
    <header className="status-bar">
      <div className="status-bar__group">
        <span className="status-bar__name">{APP_NAME}</span>
        <span
          className={`connection connection--${connection}`}
          role="status"
          aria-label={`Live stream: ${CONNECTION_LABEL[connection]}`}
        >
          <span className="connection__dot" aria-hidden="true" />
          {CONNECTION_LABEL[connection]}
          {connection !== 'live' && <span aria-hidden="true">&hellip;</span>}
        </span>
        <span
          className={`status-bar__baseline status-bar__baseline--${baseline.kind}`}
          aria-label="Baseline status"
        >
          {describeBaseline(baseline)}
        </span>
      </div>

      <dl className="status-bar__meta">
        <div className="status-bar__item">
          <dt>Log source</dt>
          <dd className="mono">{health?.log_path ?? '\u2014'}</dd>
        </div>
        <div className="status-bar__item">
          <dt>SNS topic</dt>
          <dd className="mono">{snsTopic ?? 'disabled'}</dd>
        </div>
        <div className="status-bar__item">
          <dt>CloudWatch group</dt>
          <dd className="mono">{logGroup ?? 'disabled'}</dd>
        </div>
        <div className="status-bar__item status-bar__clock">
          <dt className="visually-hidden">Current time</dt>
          <dd className="mono">
            <time dateTime={new Date(now).toISOString()}>{formatClock(now)}</time>{' '}
            <span className="muted">{timeZoneLabel()}</span>
          </dd>
        </div>
      </dl>
    </header>
  );
}
