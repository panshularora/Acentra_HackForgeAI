import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { makeAlert, makeExplainedAlert } from '../test/fixtures';
import { AlertFeed } from './AlertFeed';

const NOW = Date.parse('2026-09-28T13:10:00Z');

const alerts = [
  makeExplainedAlert({
    id: 'c1',
    severity: 'CRITICAL',
    summary: 'Claims DB timeouts',
    template: {
      id: '17',
      text: 'ERROR claim-adjudication msg="DB connection timeout"',
      service: 'claim-adjudication',
    },
  }),
  makeAlert({
    id: 'w1',
    severity: 'WARNING',
    status: 'resolved',
    resolved_at: '2026-09-28T12:59:00Z',
    opened_at: '2026-09-28T12:55:00Z',
    summary: 'Eligibility API 503s',
    template: { id: '9', text: 'WARN eligibility-check', service: 'eligibility-check' },
    top_contributors: {
      services: [{ value: 'eligibility-check', count: 8, share: 1 }],
      messages: [{ value: 'upstream 503', count: 8, share: 1 }],
      source_ips: [],
    },
  }),
];

function renderFeed(props: Partial<Parameters<typeof AlertFeed>[0]> = {}) {
  return render(
    <AlertFeed
      alerts={alerts}
      liveArrivals={{}}
      connection="live"
      now={NOW}
      onAcknowledge={vi.fn()}
      {...props}
    />,
  );
}

describe('AlertFeed', () => {
  it('lists open alerts before resolved ones', () => {
    renderFeed();
    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(['Claims DB timeouts', 'Eligibility API 503s']);
  });

  it('puts the most severe open incident first, then resolved ones by recency', () => {
    renderFeed({
      alerts: [
        makeAlert({
          id: 'w',
          severity: 'WARNING',
          summary: 'Newer warning',
          opened_at: '2026-09-28T13:08:00Z',
        }),
        makeAlert({
          id: 'c',
          severity: 'CRITICAL',
          summary: 'Older critical',
          opened_at: '2026-09-28T13:05:00Z',
        }),
        makeAlert({
          id: 'r',
          severity: 'CRITICAL',
          status: 'resolved',
          summary: 'Resolved critical',
          opened_at: '2026-09-28T13:09:00Z',
        }),
      ],
    });
    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(['Older critical', 'Newer warning', 'Resolved critical']);
  });

  it('filters by status and severity, with counts on each chip', async () => {
    const user = userEvent.setup();
    renderFeed();

    expect(screen.getByRole('button', { name: 'Status Open (1)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Status Resolved (1)' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Status Resolved (1)' }));
    expect(screen.queryByText('Claims DB timeouts')).not.toBeInTheDocument();
    expect(screen.getByText('Eligibility API 503s')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Status Resolved (1)' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    await user.click(screen.getByRole('button', { name: 'Severity Critical (0)' }));
    expect(screen.getByText(/No incidents match/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show all 2' })).toBeInTheDocument();
  });

  it('searches across summary and template text', async () => {
    const user = userEvent.setup();
    renderFeed();
    await user.type(screen.getByRole('searchbox', { name: 'Search incidents' }), 'Claims DB');
    expect(screen.getByText('Claims DB timeouts')).toBeInTheDocument();
    expect(screen.queryByText('Eligibility API 503s')).not.toBeInTheDocument();
  });

  it('filters by service and lets a second click clear it', async () => {
    const user = userEvent.setup();
    renderFeed();
    await user.click(screen.getByRole('button', { name: 'Service claim-adjudication (1)' }));
    expect(screen.getByText('Claims DB timeouts')).toBeInTheDocument();
    expect(screen.queryByText('Eligibility API 503s')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Service claim-adjudication (1)' }));
    expect(screen.getByText('Eligibility API 503s')).toBeInTheDocument();
  });

  it('tells the operator when a live arrival is hidden by the current chips', () => {
    renderFeed({
      filter: {
        status: 'resolved',
        severity: 'all',
        service: null,
        query: '',
      },
      onFilterChange: vi.fn(),
      liveArrivals: { c1: NOW - 1_000 },
    });
    expect(
      screen.getByRole('button', { name: /1 new incident hidden by filters/ }),
    ).toBeInTheDocument();
  });

  it('explains the empty state before any incident', () => {
    renderFeed({ alerts: [] });
    expect(screen.getByText(/No alerts yet/)).toBeInTheDocument();
  });

  it('does not promise alerts while the detector is still learning', () => {
    renderFeed({ alerts: [], baseline: { kind: 'learning', collected: 4, required: 6 } });
    expect(
      screen.getByText(
        'No alerts yet. Alerting starts once the detector has learned its baseline.',
      ),
    ).toBeInTheDocument();
  });

  it('asks for a connection before showing alerts', () => {
    renderFeed({ alerts: [], connection: 'reconnecting' });
    expect(
      screen.getByText('Alerts will load once the live stream is connected.'),
    ).toBeInTheDocument();
  });

  it('animates only alerts that just arrived on the live socket', () => {
    renderFeed({ liveArrivals: { c1: NOW - 1_000, w1: NOW - 60_000 } });
    const [fresh, old] = screen.getAllByRole('article');
    expect(fresh).toHaveClass('alert-card--new');
    expect(old).not.toHaveClass('alert-card--new');
  });
});
