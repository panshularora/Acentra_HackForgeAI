import { SEVERITIES, SEVERITY_THRESHOLD } from '../lib/severity';
import { formatCount, formatPercent, formatScore, startOfLocalDay } from '../lib/format';
import type { Alert, Severity, StatsPoint } from '../types';
import { SeverityBadge } from './SeverityBadge';

interface SummaryStripProps {
  latest: StatsPoint | undefined;
  alerts: Alert[];
  now: number;
  /** Sliding window length from /api/health, for the labels. */
  windowSeconds?: number;
}

function countToday(alerts: Alert[], now: number): Record<Severity, number> {
  const since = startOfLocalDay(now);
  const counts: Record<Severity, number> = { CRITICAL: 0, HIGH: 0, WARNING: 0 };
  for (const alert of alerts) {
    if (Date.parse(alert.opened_at) >= since) counts[alert.severity] += 1;
  }
  return counts;
}

/** A compact row of the numbers an on-call engineer checks first. */
export function SummaryStrip({ latest, alerts, now, windowSeconds = 60 }: SummaryStripProps) {
  const openCount = alerts.filter((a) => a.status === 'open').length;
  const today = countToday(alerts, now);

  return (
    <section className="summary-strip panel" aria-label="Current summary">
      <dl className="summary-strip__grid">
        <div className="metric">
          <dt>Error rate ({windowSeconds}s window)</dt>
          <dd>
            <span className="metric__value">{formatPercent(latest?.error_rate)}</span>
            {latest?.severity && <SeverityBadge severity={latest.severity} />}
          </dd>
        </div>
        <div className="metric">
          <dt>Baseline median</dt>
          <dd>
            <span className="metric__value">{formatPercent(latest?.baseline_median)}</span>
            {latest?.band_upper != null && (
              <span className="metric__note">
                normal up to <span className="mono">{formatPercent(latest.band_upper)}</span>
              </span>
            )}
          </dd>
        </div>
        <div className="metric">
          <dt>Modified z-score</dt>
          <dd>
            <span className="metric__value">{formatScore(latest?.score)}</span>
            <span className="metric__note">
              alerts at <span className="mono">{SEVERITY_THRESHOLD.WARNING}</span>
            </span>
          </dd>
        </div>
        <div className="metric">
          <dt>Log lines ({windowSeconds}s)</dt>
          <dd>
            <span className="metric__value">{formatCount(latest?.total)}</span>
            <span className="metric__note">
              <span className="mono">{formatCount(latest?.errors)}</span> errors
            </span>
          </dd>
        </div>
        <div className="metric">
          <dt>Open incidents</dt>
          <dd>
            <span className="metric__value">{openCount}</span>
          </dd>
        </div>
        <div className="metric">
          <dt>Alerts today</dt>
          <dd className="metric__severities">
            {SEVERITIES.map((severity) => (
              <span key={severity} className="metric__severity">
                <span className={`swatch swatch--${severity.toLowerCase()}`} aria-hidden="true" />
                <span className="metric__severity-label">{severity}</span>
                <span className="mono">{today[severity]}</span>
              </span>
            ))}
          </dd>
        </div>
      </dl>
    </section>
  );
}
