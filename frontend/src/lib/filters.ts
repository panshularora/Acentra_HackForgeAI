import { SEVERITIES, SEVERITY_LABEL } from './severity';
import type { Alert, Severity } from '../types';

/** Status chips in the incident feed. */
export type StatusFilter = 'all' | 'open' | 'resolved';

/** Severity chips; `all` means every severity. */
export type SeverityFilter = 'all' | Severity;

/**
 * What the incident feed is currently showing. Kept as a plain object so the
 * summary strip, cards and the filter bar can all drive the same state.
 */
export interface FeedFilter {
  status: StatusFilter;
  severity: SeverityFilter;
  /** Exact service name, or null for every service. */
  service: string | null;
  /** Case-insensitive substring over summary, template, IPs, samples. */
  query: string;
}

export const DEFAULT_FEED_FILTER: FeedFilter = {
  status: 'all',
  severity: 'all',
  service: null,
  query: '',
};

export const STATUS_FILTERS: readonly StatusFilter[] = ['all', 'open', 'resolved'];

export const STATUS_FILTER_LABEL: Record<StatusFilter, string> = {
  all: 'All',
  open: 'Open',
  resolved: 'Resolved',
};

/** True when any chip or the search box is narrowing the feed. */
export function isFilterActive(filter: FeedFilter): boolean {
  return (
    filter.status !== 'all' ||
    filter.severity !== 'all' ||
    filter.service != null ||
    filter.query.trim() !== ''
  );
}

/** Services named on an alert (template first, then contributor rows). */
export function alertServices(alert: Alert): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  const add = (value: string | null | undefined) => {
    const name = value?.trim();
    if (!name || seen.has(name)) return;
    seen.add(name);
    names.push(name);
  };
  add(alert.template?.service);
  for (const row of alert.top_contributors.services) add(row.value);
  return names;
}

/** Distinct services across the feed, most common first. */
export function serviceOptions(alerts: readonly Alert[]): string[] {
  const counts = new Map<string, number>();
  for (const alert of alerts) {
    for (const name of alertServices(alert)) {
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name]) => name);
}

function haystack(alert: Alert): string {
  const parts: Array<string | null | undefined> = [
    alert.summary,
    alert.id,
    alert.detector,
    alert.template?.text,
    alert.template?.service,
    alert.first_bad_line,
    ...alert.sample_lines,
    ...alert.top_contributors.services.map((c) => c.value),
    ...alert.top_contributors.messages.map((c) => c.value),
    ...alert.top_contributors.source_ips.map((c) => c.value),
    ...(alert.params ?? []).map((p) => `${p.name} ${p.value}`),
  ];
  return parts.filter((part): part is string => Boolean(part)).join('\n').toLowerCase();
}

function matchesQuery(alert: Alert, query: string): boolean {
  const needle = query.trim().toLowerCase();
  return needle.length === 0 || haystack(alert).includes(needle);
}

function matchesService(alert: Alert, service: string | null): boolean {
  return service == null || alertServices(alert).includes(service);
}

/** Alerts that pass every active chip and the search box. */
export function filterAlerts(alerts: readonly Alert[], filter: FeedFilter): Alert[] {
  return alerts.filter(
    (alert) =>
      (filter.status === 'all' || alert.status === filter.status) &&
      (filter.severity === 'all' || alert.severity === filter.severity) &&
      matchesService(alert, filter.service) &&
      matchesQuery(alert, filter.query),
  );
}

export interface StatusCounts {
  all: number;
  open: number;
  resolved: number;
}

export interface SeverityCounts {
  all: number;
  WARNING: number;
  HIGH: number;
  CRITICAL: number;
}

/**
 * Per-chip counts. Each dimension is counted after the *other* filters, so
 * clicking Open still shows how many of the currently searched/severity-filtered
 * incidents are open.
 */
export function filterCounts(
  alerts: readonly Alert[],
  filter: FeedFilter,
): {
  status: StatusCounts;
  severity: SeverityCounts;
  serviceAll: number;
  services: Record<string, number>;
} {
  const exceptStatus = filterAlerts(alerts, { ...filter, status: 'all' });
  const exceptSeverity = filterAlerts(alerts, { ...filter, severity: 'all' });
  const exceptService = filterAlerts(alerts, { ...filter, service: null });

  const status: StatusCounts = { all: exceptStatus.length, open: 0, resolved: 0 };
  for (const alert of exceptStatus) {
    if (alert.status === 'open') status.open += 1;
    else status.resolved += 1;
  }

  const severity: SeverityCounts = { all: exceptSeverity.length, WARNING: 0, HIGH: 0, CRITICAL: 0 };
  for (const alert of exceptSeverity) severity[alert.severity] += 1;

  const services: Record<string, number> = {};
  for (const name of serviceOptions(alerts)) {
    services[name] = exceptService.filter((alert) => matchesService(alert, name)).length;
  }

  return { status, severity, serviceAll: exceptService.length, services };
}

/**
 * Clicking an already-selected chip turns it off (back to "all"/no service)
 * so a filter is never a dead end.
 */
export function toggleStatus(current: StatusFilter, next: StatusFilter): StatusFilter {
  return current === next && next !== 'all' ? 'all' : next;
}

export function toggleSeverity(current: SeverityFilter, next: SeverityFilter): SeverityFilter {
  return current === next && next !== 'all' ? 'all' : next;
}

export function toggleService(current: string | null, next: string): string | null {
  return current === next ? null : next;
}

/** One-line description of the active filters, for the empty state and live region. */
export function describeFilter(filter: FeedFilter): string {
  const parts: string[] = [];
  if (filter.status !== 'all') parts.push(STATUS_FILTER_LABEL[filter.status].toLowerCase());
  if (filter.severity !== 'all') parts.push(SEVERITY_LABEL[filter.severity].toLowerCase());
  if (filter.service) parts.push(filter.service);
  const query = filter.query.trim();
  if (query) parts.push(`“${query}”`);
  if (parts.length === 0) return 'all incidents';
  return parts.join(', ');
}

export { SEVERITIES, SEVERITY_LABEL };
