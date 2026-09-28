import { useId, useState } from 'react';
import {
  formatClock,
  formatDuration,
  formatMultiple,
  formatPercent,
  formatScore,
} from '../lib/format';
import type { Alert, Contributor, DeliveryStatus } from '../types';
import { MaskedText } from './MaskedText';
import { SeverityBadge } from './SeverityBadge';

const MAX_CONTRIBUTORS = 3;
const DELIVERY_LABEL: Record<DeliveryStatus, string> = {
  pending: 'pending',
  sent: 'sent',
  failed: 'failed',
  disabled: 'off',
};

function ContributorGroup({
  label,
  items,
  mono = false,
}: {
  label: string;
  items: Contributor[];
  mono?: boolean;
}) {
  if (items.length === 0) return null;
  return (
    <div className="contributors__group">
      <h4 className="contributors__label">{label}</h4>
      <ul className="contributors__list">
        {items.slice(0, MAX_CONTRIBUTORS).map((item) => (
          <li key={item.value} className="contributor">
            <span className={`contributor__value${mono ? ' mono' : ''}`} title={item.value}>
              <MaskedText text={item.value} />
            </span>
            <span className="contributor__share mono">{formatPercent(item.share, 0)}</span>
            <span className="contributor__bar" aria-hidden="true">
              <span style={{ width: `${Math.min(100, Math.max(0, item.share * 100))}%` }} />
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DeliveryChip({
  channel,
  status,
  error,
}: {
  channel: string;
  status: DeliveryStatus;
  error: string | null;
}) {
  return (
    <span
      className={`delivery-chip delivery-chip--${status}`}
      title={error ?? undefined}
      aria-label={`${channel} delivery ${DELIVERY_LABEL[status]}${error ? `: ${error}` : ''}`}
    >
      <span className="delivery-chip__channel">{channel}</span>
      <span className="delivery-chip__status">{DELIVERY_LABEL[status]}</span>
    </span>
  );
}

type AckState = 'idle' | 'pending' | 'error';

interface AlertCardProps {
  alert: Alert;
  now: number;
  /** Plays the one-off arrival animation (slide in + single pulse). */
  isNew?: boolean;
  onAcknowledge?: (id: string) => Promise<void>;
}

export function AlertCard({ alert, now, isNew = false, onAcknowledge }: AlertCardProps) {
  const headingId = useId();
  const [ackState, setAckState] = useState<AckState>('idle');

  const isOpen = alert.status === 'open';
  const endedAt = alert.resolved_at ? Date.parse(alert.resolved_at) : now;
  const duration = formatDuration(endedAt - Date.parse(alert.opened_at));
  const multiple = formatMultiple(alert.error_rate, alert.baseline_median);
  const { services, messages, source_ips: sourceIps } = alert.top_contributors;
  const { sns, cloudwatch } = alert.delivery;

  const acknowledge = async () => {
    if (!onAcknowledge) return;
    setAckState('pending');
    try {
      await onAcknowledge(alert.id);
      setAckState('idle');
    } catch {
      setAckState('error');
    }
  };

  const classes = [
    'alert-card',
    `alert-card--${alert.severity.toLowerCase()}`,
    isOpen ? 'alert-card--open' : 'alert-card--resolved',
    isNew ? 'alert-card--new' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <article className={classes} aria-labelledby={headingId} data-alert-id={alert.id}>
      <header className="alert-card__header">
        <SeverityBadge severity={alert.severity} />
        <span className="alert-card__status">
          {isOpen ? 'Open' : 'Resolved'}
          {alert.acknowledged && ' \u00b7 Acknowledged'}
        </span>
        <span className="alert-card__id mono" title="Incident ID">
          {alert.id}
        </span>
      </header>

      <h3 id={headingId} className="alert-card__summary">
        {alert.summary}
      </h3>

      <dl className="alert-card__facts">
        <div>
          <dt>Started</dt>
          <dd className="mono">
            <time dateTime={alert.opened_at}>{formatClock(alert.opened_at)}</time>
          </dd>
        </div>
        <div>
          <dt>{isOpen ? 'Ongoing for' : 'Lasted'}</dt>
          <dd className="mono">{duration}</dd>
        </div>
        <div>
          <dt>Peak z-score</dt>
          <dd className="mono">{formatScore(alert.score)}</dd>
        </div>
        <div>
          <dt>Peak error rate</dt>
          <dd>
            <span className="mono">{formatPercent(alert.error_rate)}</span>
            <span className="muted">
              {' '}
              vs <span className="mono">{formatPercent(alert.baseline_median)}</span>
              {multiple && <span className="mono"> ({multiple})</span>}
            </span>
          </dd>
        </div>
      </dl>

      <div className="contributors">
        <ContributorGroup label="Service" items={services} />
        <ContributorGroup label="Error message" items={messages} mono />
        <ContributorGroup label="Source IP" items={sourceIps} mono />
      </div>

      {alert.sample_lines.length > 0 && (
        <details className="samples">
          <summary>
            Sample log lines{' '}
            <span className="muted">({alert.sample_lines.length}, PII masked)</span>
          </summary>
          <pre className="samples__lines">
            {alert.sample_lines.map((line, i) => (
              <code key={i}>
                <MaskedText text={line} />
              </code>
            ))}
          </pre>
        </details>
      )}

      <footer className="alert-card__footer">
        <div className="alert-card__delivery">
          <DeliveryChip channel="SNS" status={sns.status} error={sns.error} />
          <DeliveryChip channel="CloudWatch" status={cloudwatch.status} error={cloudwatch.error} />
        </div>
        {alert.acknowledged ? (
          <span className="alert-card__acked">Acknowledged</span>
        ) : (
          onAcknowledge && (
            <button
              type="button"
              className="button"
              onClick={acknowledge}
              disabled={ackState === 'pending'}
            >
              {ackState === 'pending'
                ? 'Acknowledging\u2026'
                : ackState === 'error'
                  ? 'Retry acknowledge'
                  : 'Acknowledge'}
            </button>
          )
        )}
      </footer>
      <p className="alert-card__meta">
        {alert.resolved_at && (
          <>
            Resolved <time dateTime={alert.resolved_at}>{formatClock(alert.resolved_at)}</time>
            {' \u00b7 '}
          </>
        )}
        SNS message ID <span className="mono">{sns.message_id ?? '\u2014'}</span>
      </p>
    </article>
  );
}
