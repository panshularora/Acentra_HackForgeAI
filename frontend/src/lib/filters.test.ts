import { makeAlert, makeExplainedAlert } from '../test/fixtures';
import {
  DEFAULT_FEED_FILTER,
  alertServices,
  describeFilter,
  filterAlerts,
  filterCounts,
  isFilterActive,
  serviceOptions,
  toggleService,
  toggleSeverity,
  toggleStatus,
  type FeedFilter,
} from './filters';

const dbOutage = makeExplainedAlert({
  id: 'db',
  status: 'open',
  severity: 'CRITICAL',
  summary: '74% of errors come from claim-adjudication: DB connection timeout',
  template: {
    id: '17',
    text: 'ERROR claim-adjudication msg="DB connection timeout" <*>',
    service: 'claim-adjudication',
  },
});

const credStuffing = makeAlert({
  id: 'auth',
  status: 'open',
  severity: 'CRITICAL',
  summary: '179 failed logins from 10.4.2.17 in the last 60s',
  sample_lines: ['ERROR member-auth login failed: invalid credentials ip=10.4.2.17'],
  template: {
    id: '4',
    text: 'ERROR member-auth msg="login failed: invalid credentials" <*>',
    service: 'member-auth',
  },
  top_contributors: {
    services: [{ value: 'member-auth', count: 179, share: 0.9 }],
    messages: [{ value: 'login failed: invalid credentials', count: 179, share: 0.9 }],
    source_ips: [{ value: '10.4.2.17', count: 179, share: 1 }],
  },
});

const resolvedWarn = makeAlert({
  id: 'w1',
  status: 'resolved',
  severity: 'WARNING',
  summary: 'Eligibility API 503s',
  sample_lines: ['WARN eligibility-check upstream 503'],
  resolved_at: '2026-09-28T12:59:00Z',
  opened_at: '2026-09-28T12:55:00Z',
  template: { id: '9', text: 'WARN eligibility-check <*>', service: 'eligibility-check' },
  top_contributors: {
    services: [{ value: 'eligibility-check', count: 12, share: 1 }],
    messages: [{ value: 'upstream 503', count: 12, share: 1 }],
    source_ips: [],
  },
});

const alerts = [dbOutage, credStuffing, resolvedWarn];
const all: FeedFilter = DEFAULT_FEED_FILTER;

describe('filterAlerts', () => {
  it('returns every alert when the filter is the default', () => {
    expect(filterAlerts(alerts, all).map((a) => a.id)).toEqual(['db', 'auth', 'w1']);
  });

  it('keeps only open incidents', () => {
    expect(filterAlerts(alerts, { ...all, status: 'open' }).map((a) => a.id)).toEqual([
      'db',
      'auth',
    ]);
  });

  it('keeps only a severity', () => {
    expect(filterAlerts(alerts, { ...all, severity: 'WARNING' }).map((a) => a.id)).toEqual(['w1']);
  });

  it('keeps a service named on the template or contributors', () => {
    expect(filterAlerts(alerts, { ...all, service: 'claim-adjudication' }).map((a) => a.id)).toEqual([
      'db',
    ]);
  });

  it('searches summary, template, IP and sample lines', () => {
    expect(filterAlerts(alerts, { ...all, query: 'timeout' }).map((a) => a.id)).toEqual(['db']);
    expect(filterAlerts(alerts, { ...all, query: 'login failed' }).map((a) => a.id)).toEqual([
      'auth',
    ]);
    expect(filterAlerts(alerts, { ...all, query: 'Eligibility' }).map((a) => a.id)).toEqual(['w1']);
  });

  it('combines chips: open + critical + search', () => {
    expect(
      filterAlerts(alerts, { status: 'open', severity: 'CRITICAL', service: null, query: 'login' }).map(
        (a) => a.id,
      ),
    ).toEqual(['auth']);
  });
});

describe('filterCounts', () => {
  it('counts each status independently of the status chip', () => {
    const counts = filterCounts(alerts, { ...all, status: 'open' });
    expect(counts.status).toEqual({ all: 3, open: 2, resolved: 1 });
    expect(counts.serviceAll).toBe(2);
  });

  it('narrows severity counts to the other active chips', () => {
    const counts = filterCounts(alerts, { ...all, status: 'open' });
    expect(counts.severity.all).toBe(2);
    expect(counts.severity.CRITICAL).toBe(2);
    expect(counts.severity.WARNING).toBe(0);
  });

  it('lists services with how many matching alerts they have', () => {
    const counts = filterCounts(alerts, all);
    expect(counts.services['claim-adjudication']).toBe(1);
    expect(counts.services['member-auth']).toBe(1);
  });
});

describe('helpers', () => {
  it('treats the default filter as inactive', () => {
    expect(isFilterActive(all)).toBe(false);
    expect(isFilterActive({ ...all, status: 'open' })).toBe(true);
    expect(isFilterActive({ ...all, query: '  timeout  ' })).toBe(true);
  });

  it('toggles a selected chip back to all / none', () => {
    expect(toggleStatus('open', 'open')).toBe('all');
    expect(toggleStatus('all', 'open')).toBe('open');
    expect(toggleSeverity('CRITICAL', 'CRITICAL')).toBe('all');
    expect(toggleService('claim-adjudication', 'claim-adjudication')).toBeNull();
    expect(toggleService(null, 'claim-adjudication')).toBe('claim-adjudication');
  });

  it('names services from the template before contributor rows', () => {
    expect(alertServices(dbOutage)).toEqual(['claim-adjudication']);
    expect(serviceOptions(alerts)).toEqual([
      'claim-adjudication',
      'eligibility-check',
      'member-auth',
    ]);
  });

  it('describes the active filter in one phrase', () => {
    expect(describeFilter(all)).toBe('all incidents');
    expect(describeFilter({ ...all, status: 'open', severity: 'CRITICAL' })).toBe(
      'open, critical',
    );
  });
});
