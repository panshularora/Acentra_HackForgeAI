import { useId, useState } from 'react';
import { incidentAnchor } from '../lib/anchors';
import { detectorLabel } from '../lib/detector';
import {
  formatClock,
  formatDuration,
  formatMeasure,
  formatMultiple,
  formatPercent,
  formatScore,
} from '../lib/format';
import type { Alert, Contributor, DeliveryStatus } from '../types';
import { MaskedText } from './MaskedText';
import { SeverityBadge } from './SeverityBadge';
import { TemplateText } from './TemplateText';

const MAX_CONTRIBUTORS = 3;
const MAX_PARAMS = 3;
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
  wrap = false,
}: {
  label: string;
  items: Contributor[];
  mono?: boolean;
  wrap?: boolean;
}) {
  if (items.length === 0) return null;
  return (
    <div className="contributors__group">
      <h4 className="contributors__label">{label}</h4>
      <ul className="contributors__list">
        {items.slice(0, MAX_CONTRIBUTORS).map((item) => (
          <li key={item.value} className="contributor">
            <span
              className={['contributor__value', mono && 'mono', wrap && 'contributor__value--wrap']
                .filter(Boolean)
                .join(' ')}
              title={item.value}
            >
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

/**
 * Why the detector fired, from the contract v2 fields: the template, its
 * normal band against the observed value, and the top extracted parameters.
 * Each row appears only when the backend sent it, and the whole block is
 * omitted for older backends.
 */
function AlertExplanation({ alert }: { alert: Alert }) {
  const { template, baseline_band: band, observed } = alert;
  const params = (alert.params ?? []).slice(0, MAX_PARAMS);
  if (!template && !band && params.length === 0) return null;

  return (
    <dl className="alert-card__explain">
      {template && (
        <div>
          <dt>Template</dt>
          <dd>
            <span className="alert-card__template mono">
              <TemplateText text={template.text} />
            </span>
          </dd>
        </div>
      )}
      {band && (
        <div>
          <dt>Baseline</dt>
          <dd className="alert-card__band">
            normal &le; <span className="mono">{formatMeasure(band.upper)}</span> {band.unit}
            {observed != null && (
              <>
                , observed{' '}
                <span className="mono alert-card__observed">{formatMeasure(observed)}</span>
              </>
            )}
          </dd>
        </div>
      )}
      {params.length > 0 && (
        <div>
          <dt>Parameters</dt>
          <dd>
            <ul className="param-list">
              {params.map((param) => (
                <li key={`${param.name}=${param.value}`} className="param">
                  <span className="param__name">{param.name}</span>{' '}
                  <span className="param__value mono">
                    <MaskedText text={param.value} />
                  </span>{' '}
                  <span className="param__share mono">{formatPercent(param.share, 0)}</span>
                </li>
              ))}
            </ul>
          </dd>
        </div>
      )}
    </dl>
  );
}

function logLinesTitle(hasFirstLine: boolean, sampleCount: number): string {
  if (!hasFirstLine) return 'Sample log lines';
  return sampleCount > 0 ? 'First bad line and samples' : 'First bad line';
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
  const detector = detectorLabel(alert.detector);
  const firstBadLine = alert.first_bad_line ?? null;
  const sampleCount = alert.sample_lines.length;

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
    <article
      id={incidentAnchor(alert.id)}
      className={classes}
      aria-labelledby={headingId}
      data-alert-id={alert.id}
      tabIndex={-1}
    >
      <header className="alert-card__header">
        <SeverityBadge severity={alert.severity} />
        {detector && (
          <span className="detector-label" title="Detector that opened this incident">
            {detector}
          </span>
        )}
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
          <dt>Peak modified z-score</dt>
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

      {/* Open incidents show why they fired; resolved ones fold it away to keep the feed short. */}
      <details className="alert-card__why" open={isOpen}>
        <summary>Why it fired</summary>
        <AlertExplanation alert={alert} />
        <div className="contributors">
          <p className="contributors__caption">Share of all errors in the window</p>
          <ContributorGroup label="Service" items={services} />
          <ContributorGroup label="Error message" items={messages} mono wrap />
          <ContributorGroup label="Source IP" items={sourceIps} mono />
        </div>
      </details>

      {(firstBadLine !== null || sampleCount > 0) && (
        <details className="samples">
          <summary>
            {logLinesTitle(firstBadLine !== null, sampleCount)}{' '}
            <span className="muted">({sampleCount > 0 && `${sampleCount}, `}PII masked)</span>
          </summary>
          {firstBadLine !== null && (
            <>
              <h4 className="samples__label">First bad line</h4>
              <pre className="samples__lines samples__lines--first">
                <code>
                  <MaskedText text={firstBadLine} />
                </code>
              </pre>
              {sampleCount > 0 && <h4 className="samples__label">Samples</h4>}
            </>
          )}
          {sampleCount > 0 && (
            <pre className="samples__lines">
              {alert.sample_lines.map((line, i) => (
                <code key={i}>
                  <MaskedText text={line} />
                </code>
              ))}
            </pre>
          )}
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
