import { useState } from 'react';
import type { ConnectionState } from '../hooks/alertStreamReducer';
import type { BaselineState } from '../lib/detector';
import { feedOrder } from '../lib/scene';
import { SEVERITIES, SEVERITY_LABEL, SEVERITY_THRESHOLD } from '../lib/severity';
import type { Alert, Severity } from '../types';
import { AlertCard } from './AlertCard';

/** A card counts as new, and animates, only if it arrived on the socket this recently. */
const NEW_ALERT_WINDOW_MS = 5_000;

type StatusFilter = 'all' | 'open' | 'resolved';
type SeverityFilter = 'all' | Severity;

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
];

const SEVERITY_OPTIONS: { value: SeverityFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  ...SEVERITIES.map((s) => ({ value: s, label: SEVERITY_LABEL[s] })),
];

function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="segmented__option"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

interface AlertFeedProps {
  alerts: Alert[];
  liveArrivals: Record<string, number>;
  connection: ConnectionState;
  /** Detector warm-up; nothing can alert until the baseline is learned. */
  baseline?: BaselineState;
  now: number;
  onAcknowledge: (id: string) => Promise<void>;
}

export function AlertFeed({
  alerts,
  liveArrivals,
  connection,
  baseline = { kind: 'ready' },
  now,
  onAcknowledge,
}: AlertFeedProps) {
  const [status, setStatus] = useState<StatusFilter>('all');
  const [severity, setSeverity] = useState<SeverityFilter>('all');

  const visible = feedOrder(alerts).filter(
    (a) =>
      (status === 'all' || a.status === status) && (severity === 'all' || a.severity === severity),
  );
  const openCount = alerts.filter((a) => a.status === 'open').length;

  let emptyMessage: string;
  if (alerts.length === 0) {
    if (connection !== 'live') {
      emptyMessage = 'Alerts will load once the live stream is connected.';
    } else if (baseline.kind !== 'ready') {
      emptyMessage = 'No alerts yet. Alerting starts once the detector has learned its baseline.';
    } else {
      emptyMessage = 'No alerts yet. Incidents appear here as soon as the detector opens them.';
    }
  } else {
    emptyMessage = 'No alerts match these filters.';
  }

  return (
    <section className="panel alert-feed" aria-labelledby="alert-feed-title">
      <header className="panel__header alert-feed__header">
        <div>
          <h2 id="alert-feed-title" className="panel__title">
            Incidents
          </h2>
          <p className="panel__subtitle">
            <span className="mono">{openCount}</span> open,{' '}
            <span className="mono">{alerts.length}</span> total, most severe open first
          </p>
        </div>
      </header>
      <p className="alert-feed__scale">
        <span>Severity by modified z-score</span>
        {SEVERITIES.slice()
          .reverse()
          .map((severity) => (
            <span key={severity} className="alert-feed__threshold">
              <span className={`swatch swatch--${severity.toLowerCase()}`} aria-hidden="true" />
              {SEVERITY_LABEL[severity]}{' '}
              <span className="mono">&ge;{SEVERITY_THRESHOLD[severity]}</span>
            </span>
          ))}
      </p>
      <div className="alert-feed__filters">
        <Segmented
          label="Filter by status"
          options={STATUS_OPTIONS}
          value={status}
          onChange={setStatus}
        />
        <Segmented
          label="Filter by severity"
          options={SEVERITY_OPTIONS}
          value={severity}
          onChange={setSeverity}
        />
      </div>

      {visible.length === 0 ? (
        <p className="empty-state">{emptyMessage}</p>
      ) : (
        <ol className="alert-feed__list">
          {visible.map((alert) => {
            const arrivedAt = liveArrivals[alert.id];
            return (
              <li key={alert.id}>
                <AlertCard
                  alert={alert}
                  now={now}
                  isNew={arrivedAt !== undefined && now - arrivedAt < NEW_ALERT_WINDOW_MS}
                  onAcknowledge={onAcknowledge}
                />
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
