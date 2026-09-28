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
}

export function StatusBar({ connection, baseline, health, now }: StatusBarProps) {
  // Until /api/health answers, the targets are unknown rather than disabled.
  const unknown = '\u2014';
  const snsTopic = health ? (arnResourceName(health.aws.sns_topic_arn) ?? 'disabled') : unknown;
  const logGroup = health ? (health.aws.cloudwatch_log_group ?? 'disabled') : unknown;

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
          {CONNECTION_TEXT[connection]}
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
          <dd className="mono">{health?.log_path ?? unknown}</dd>
        </div>
        <div className="status-bar__item">
          <dt>SNS topic</dt>
          <dd className="mono">{snsTopic}</dd>
        </div>
        <div className="status-bar__item">
          <dt>CloudWatch group</dt>
          <dd className="mono">{logGroup}</dd>
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
