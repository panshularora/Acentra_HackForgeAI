import { SEVERITIES, SEVERITY_LABEL } from '../lib/severity';
import { formatCount, formatPercent, startOfLocalDay } from '../lib/format';
import type { Alert, Severity, StatsPoint } from '../types';
import { SeverityBadge } from './SeverityBadge';

interface SummaryStripProps {
  latest: StatsPoint | undefined;
  alerts: Alert[];
  now: number;
  /** Sliding window length from /api/health, for the labels. */
  windowSeconds?: number;
  /** Focus the incident feed on open alerts. */
  onFilterOpen?: () => void;
  /** Focus the incident feed on one severity (today's counts). */
  onFilterSeverity?: (severity: Severity) => void;
}

function countToday(alerts: Alert[], now: number): Record<Severity, number> {
  const since = startOfLocalDay(now);
  const counts: Record<Severity, number> = { CRITICAL: 0, HIGH: 0, WARNING: 0 };
  for (const alert of alerts) {
    if (Date.parse(alert.opened_at) >= since) counts[alert.severity] += 1;
  }
  return counts;
}

/**
 * The four numbers an on-call engineer checks first. The global error rate is
 * shown against its own normal range for context; alerts come from the
 * per-template detector, whose scores appear on each incident.
 */
export function SummaryStrip({
  latest,
  alerts,
  now,
  windowSeconds = 60,
  onFilterOpen,
  onFilterSeverity,
}: SummaryStripProps) {
  const openCount = alerts.filter((a) => a.status === 'open').length;
  const today = countToday(alerts, now);
  const focusFeed = () => document.getElementById('incidents')?.scrollIntoView({ block: 'start' });

  return (
    <section className="summary-strip" aria-label="Current summary">
      <dl className="summary-strip__grid">
        <div className="metric">
          <dt>Error rate ({windowSeconds}s window)</dt>
          <dd>
            <span className="metric__value">{formatPercent(latest?.error_rate)}</span>
            {latest?.severity && <SeverityBadge severity={latest.severity} />}
          </dd>
        </div>
        <div className="metric">
          <dt>Normal up to</dt>
          <dd>
            <span className="metric__value">{formatPercent(latest?.band_upper)}</span>
            <span className="metric__note">
              {!latest ? null : latest.band_upper == null ? (
                'learning'
              ) : (
                <>
                  median <span className="mono">{formatPercent(latest.baseline_median)}</span>
                </>
              )}
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
            {onFilterOpen ? (
              <button
                type="button"
                className="metric__value metric__value--button"
                onClick={() => {
                  onFilterOpen();
                  focusFeed();
                }}
                aria-label={`Show open incidents (${openCount})`}
                title="Show open incidents"
              >
                {openCount}
              </button>
            ) : (
              <span className="metric__value">{openCount}</span>
            )}
            <span className="metric__note metric__today" aria-label="Alerts opened today">
              today
              {SEVERITIES.map((severity) =>
                onFilterSeverity ? (
                  <button
                    key={severity}
                    type="button"
                    className="metric__severity metric__severity--button"
                    aria-label={`Show ${SEVERITY_LABEL[severity]} (${today[severity]})`}
                    title={`Show ${SEVERITY_LABEL[severity].toLowerCase()} incidents`}
                    onClick={() => {
                      onFilterSeverity(severity);
                      focusFeed();
                    }}
                  >
                    <span
                      className={`swatch swatch--${severity.toLowerCase()}`}
                      aria-hidden="true"
                    />
                    <span className="visually-hidden">{SEVERITY_LABEL[severity]}</span>
                    <span className="mono">{today[severity]}</span>
                  </button>
                ) : (
                  <span
                    key={severity}
                    className="metric__severity"
                    title={SEVERITY_LABEL[severity]}
                  >
                    <span
                      className={`swatch swatch--${severity.toLowerCase()}`}
                      aria-hidden="true"
                    />
                    <span className="visually-hidden">{SEVERITY_LABEL[severity]}</span>
                    <span className="mono">{today[severity]}</span>
                  </span>
                ),
              )}
            </span>
          </dd>
        </div>
      </dl>
    </section>
  );
}
