import { useMemo, useRef, useState, type KeyboardEvent } from 'react';
import type { ConnectionState } from '../hooks/alertStreamReducer';
import type { BaselineState } from '../lib/detector';
import {
  DEFAULT_FEED_FILTER,
  STATUS_FILTERS,
  STATUS_FILTER_LABEL,
  describeFilter,
  filterAlerts,
  filterCounts,
  isFilterActive,
  serviceOptions,
  toggleService,
  toggleSeverity,
  toggleStatus,
  type FeedFilter,
  type SeverityFilter,
  type StatusFilter,
} from '../lib/filters';
import { feedOrder } from '../lib/scene';
import { SEVERITIES, SEVERITY_LABEL, SEVERITY_THRESHOLD } from '../lib/severity';
import type { Alert } from '../types';
import { AlertCard } from './AlertCard';

/** A card counts as new, and animates, only if it arrived on the socket this recently. */
const NEW_ALERT_WINDOW_MS = 5_000;
/** Long enough to notice a new incident that the current chips are hiding. */
const HIDDEN_NEW_WINDOW_MS = 20_000;

interface ChipOption<T extends string> {
  value: T;
  label: string;
  count: number;
  tone?: string;
}

function ChipRow<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: ChipOption<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="feed-filter">
      <span className="feed-filter__label" id={`${label}-label`}>
        {label}
      </span>
      <div className="chip-row" role="group" aria-labelledby={`${label}-label`}>
        {options.map((option) => {
          const pressed = value === option.value;
          const countLabel = `${label} ${option.label} (${option.count})`;
          return (
            <button
              key={option.value}
              type="button"
              className={[
                'chip',
                option.tone ? `chip--${option.tone}` : '',
                pressed ? 'chip--on' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-pressed={pressed}
              aria-label={countLabel}
              title={countLabel}
              onClick={() => onChange(option.value)}
            >
              <span className="chip__label">{option.label}</span>
              <span className="chip__count mono">{option.count}</span>
            </button>
          );
        })}
      </div>
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
  filter?: FeedFilter;
  onFilterChange?: (next: FeedFilter) => void;
}

export function AlertFeed({
  alerts,
  liveArrivals,
  connection,
  baseline = { kind: 'ready' },
  now,
  onAcknowledge,
  filter: filterProp,
  onFilterChange,
}: AlertFeedProps) {
  const [internal, setInternal] = useState<FeedFilter>(DEFAULT_FEED_FILTER);
  const filter = filterProp ?? internal;
  const setFilter = onFilterChange ?? setInternal;
  const searchRef = useRef<HTMLInputElement>(null);

  const ordered = useMemo(() => feedOrder(alerts), [alerts]);
  const visible = useMemo(() => filterAlerts(ordered, filter), [ordered, filter]);
  const counts = useMemo(() => filterCounts(alerts, filter), [alerts, filter]);
  const services = useMemo(() => serviceOptions(alerts), [alerts]);
  const openCount = alerts.filter((a) => a.status === 'open').length;
  const active = isFilterActive(filter);
  const hiddenNew = useMemo(
    () =>
      alerts.filter((alert) => {
        const arrivedAt = liveArrivals[alert.id];
        if (arrivedAt === undefined || now - arrivedAt >= HIDDEN_NEW_WINDOW_MS) return false;
        return !visible.some((item) => item.id === alert.id);
      }),
    [alerts, liveArrivals, now, visible],
  );

  const patch = (partial: Partial<FeedFilter>) => setFilter({ ...filter, ...partial });

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
    emptyMessage = `No incidents match ${describeFilter(filter)}.`;
  }

  const onSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      patch({ query: '' });
      searchRef.current?.blur();
    }
  };

  return (
    <section className="panel alert-feed" id="incidents" aria-labelledby="alert-feed-title">
      <header className="panel__header alert-feed__header">
        <div>
          <h2 id="alert-feed-title" className="panel__title">
            Incidents
          </h2>
          <p className="panel__subtitle">
            <span className="mono">{openCount}</span> open,{' '}
            <span className="mono">{alerts.length}</span> total
            {active && (
              <>
                {' '}
                · showing <span className="mono">{visible.length}</span> of{' '}
                <span className="mono">{alerts.length}</span>
              </>
            )}
          </p>
        </div>
        {active && (
          <button
            type="button"
            className="button button--small"
            onClick={() => setFilter(DEFAULT_FEED_FILTER)}
          >
            Clear filters
          </button>
        )}
      </header>

      <p className="alert-feed__scale">
        <span>Severity by modified z-score</span>
        {SEVERITIES.slice()
          .reverse()
          .map((severity) => (
            <button
              key={severity}
              type="button"
              className={[
                'alert-feed__threshold',
                filter.severity === severity ? 'alert-feed__threshold--on' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-pressed={filter.severity === severity}
              onClick={() => patch({ severity: toggleSeverity(filter.severity, severity) })}
            >
              <span className={`swatch swatch--${severity.toLowerCase()}`} aria-hidden="true" />
              {SEVERITY_LABEL[severity]}{' '}
              <span className="mono">&ge;{SEVERITY_THRESHOLD[severity]}</span>
            </button>
          ))}
      </p>

      <div className="feed-filters">
        <ChipRow<StatusFilter>
          label="Status"
          value={filter.status}
          onChange={(status) => patch({ status: toggleStatus(filter.status, status) })}
          options={STATUS_FILTERS.map((status) => ({
            value: status,
            label: STATUS_FILTER_LABEL[status],
            count: counts.status[status],
          }))}
        />
        <ChipRow<SeverityFilter>
          label="Severity"
          value={filter.severity}
          onChange={(severity) => patch({ severity: toggleSeverity(filter.severity, severity) })}
          options={[
            { value: 'all', label: 'All', count: counts.severity.all },
            ...SEVERITIES.map((severity) => ({
              value: severity as SeverityFilter,
              label: SEVERITY_LABEL[severity],
              count: counts.severity[severity],
              tone: severity.toLowerCase(),
            })),
          ]}
        />
        {services.length > 0 && (
          <ChipRow<string>
            label="Service"
            value={filter.service ?? 'all'}
            onChange={(value) =>
              patch({ service: value === 'all' ? null : toggleService(filter.service, value) })
            }
            options={[
              { value: 'all', label: 'All', count: counts.serviceAll },
              ...services.map((name) => ({
                value: name,
                label: name,
                count: counts.services[name] ?? 0,
              })),
            ]}
          />
        )}
        <label className="feed-filter feed-filter--search">
          <span className="feed-filter__label">Search</span>
          <input
            ref={searchRef}
            type="search"
            className="feed-search"
            value={filter.query}
            placeholder="Timeout, service, IP…"
            aria-label="Search incidents"
            onChange={(event) => patch({ query: event.target.value })}
            onKeyDown={onSearchKey}
          />
        </label>
      </div>

      {hiddenNew.length > 0 && (
        <button
          type="button"
          className="alert-feed__hidden"
          onClick={() => setFilter(DEFAULT_FEED_FILTER)}
        >
          <span className="mono">{hiddenNew.length}</span> new{' '}
          {hiddenNew.length === 1 ? 'incident' : 'incidents'} hidden by filters — show{' '}
          {hiddenNew.length === 1 ? 'it' : 'them'}
        </button>
      )}

      {visible.length === 0 ? (
        <div className="empty-state empty-state--feed">
          <p>{emptyMessage}</p>
          {alerts.length > 0 && active && (
            <button
              type="button"
              className="button button--small"
              onClick={() => setFilter(DEFAULT_FEED_FILTER)}
            >
              Show all {alerts.length}
            </button>
          )}
        </div>
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
                  onSelectService={(service) => patch({ service })}
                />
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

export type { FeedFilter, SeverityFilter, StatusFilter };
