import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { makeAlert, makeExplainedAlert } from '../test/fixtures';
import { AlertCard } from './AlertCard';

const NOW = Date.parse('2026-09-28T13:09:12Z');

describe('AlertCard', () => {
  it('leads with the severity label and the summary sentence', () => {
    const alert = makeAlert();
    render(<AlertCard alert={alert} now={NOW} />);

    const card = screen.getByRole('article', { name: alert.summary });
    expect(within(card).getByText('CRITICAL')).toHaveClass('severity-badge--critical');
    expect(card).toHaveClass('alert-card--critical');
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent(alert.summary);
  });

  it.each(['WARNING', 'HIGH'] as const)('colours %s cards by severity', (severity) => {
    render(<AlertCard alert={makeAlert({ severity })} now={NOW} />);
    expect(screen.getByRole('article')).toHaveClass(`alert-card--${severity.toLowerCase()}`);
    expect(screen.getByText(severity)).toBeInTheDocument();
  });

  it('shows peak error rate against baseline and how long the incident has run', () => {
    render(<AlertCard alert={makeAlert()} now={NOW} />);
    expect(screen.getByText('31.0%')).toBeInTheDocument();
    expect(screen.getByText('2.0%')).toBeInTheDocument();
    expect(screen.getByText('Ongoing for').nextSibling).toHaveTextContent('4m 12s');
    expect(screen.getByText('9.4')).toBeInTheDocument();
  });

  it('uses the resolution time for the duration of resolved incidents', () => {
    const alert = makeAlert({
      status: 'resolved',
      resolved_at: '2026-09-28T13:06:30Z',
      updated_at: '2026-09-28T13:06:30Z',
    });
    render(<AlertCard alert={alert} now={NOW} />);
    expect(screen.getByText('Resolved')).toBeInTheDocument();
    expect(screen.getByText('Lasted').nextSibling).toHaveTextContent('1m 30s');
  });

  it('lists top contributors with their share', () => {
    render(<AlertCard alert={makeAlert()} now={NOW} />);
    expect(screen.getByText('claim-adjudication')).toBeInTheDocument();
    expect(screen.getByText('10.4.2.17')).toBeInTheDocument();
    expect(screen.getByText('97%')).toBeInTheDocument();
  });

  it('renders masked sample lines in monospace with placeholders set apart', () => {
    const { container } = render(<AlertCard alert={makeAlert()} now={NOW} />);
    const samples = container.querySelector('.samples__lines');
    expect(samples).not.toBeNull();
    expect(samples).toHaveTextContent('DB connection timeout for member <MEMBER_ID>');
    const tokens = within(samples as HTMLElement).getAllByText('<MEMBER_ID>');
    expect(tokens[0]).toHaveClass('masked-token');
    expect(screen.getByText(/Sample log lines/)).toBeInTheDocument();
  });

  it('shows AWS delivery status and the SNS message id', () => {
    const alert = makeAlert({
      delivery: {
        sns: { status: 'sent', message_id: 'msg-123', error: null },
        cloudwatch: { status: 'failed', error: 'AccessDenied' },
      },
    });
    render(<AlertCard alert={alert} now={NOW} />);
    expect(screen.getByLabelText('SNS delivery sent')).toBeInTheDocument();
    expect(screen.getByLabelText('CloudWatch delivery failed: AccessDenied')).toBeInTheDocument();
    expect(screen.getByText('msg-123')).toBeInTheDocument();
  });

  it('shows pending delivery before AWS confirms', () => {
    const alert = makeAlert({
      delivery: {
        sns: { status: 'pending', message_id: null, error: null },
        cloudwatch: { status: 'pending', error: null },
      },
    });
    render(<AlertCard alert={alert} now={NOW} />);
    expect(screen.getByLabelText('SNS delivery pending')).toBeInTheDocument();
    expect(screen.getByLabelText('CloudWatch delivery pending')).toBeInTheDocument();
  });

  it('acknowledges through the callback and reports failures', async () => {
    const user = userEvent.setup();
    const onAcknowledge = vi.fn().mockRejectedValueOnce(new Error('offline'));
    render(<AlertCard alert={makeAlert()} now={NOW} onAcknowledge={onAcknowledge} />);

    await user.click(screen.getByRole('button', { name: 'Acknowledge' }));
    expect(onAcknowledge).toHaveBeenCalledWith('a3f9c2e1');
    expect(await screen.findByRole('button', { name: 'Retry acknowledge' })).toBeEnabled();
  });

  it('replaces the button once acknowledged', () => {
    render(
      <AlertCard alert={makeAlert({ acknowledged: true })} now={NOW} onAcknowledge={vi.fn()} />,
    );
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getAllByText(/Acknowledged/).length).toBeGreaterThan(0);
  });

  it('labels the score as a modified z-score and can be jumped to from the headline', () => {
    render(<AlertCard alert={makeAlert()} now={NOW} />);
    expect(screen.getByText('Peak modified z-score').nextSibling).toHaveTextContent('9.4');
    expect(screen.getByRole('article')).toHaveAttribute('id', 'incident-a3f9c2e1');
  });

  it('labels contributor percentages as shares of window errors', () => {
    render(<AlertCard alert={makeAlert()} now={NOW} />);
    expect(screen.getByText('Share of all errors in the window')).toBeInTheDocument();
  });

  it('shows why an open incident fired and folds it away once resolved', () => {
    const { container, rerender } = render(<AlertCard alert={makeAlert()} now={NOW} />);
    expect(container.querySelector('details.alert-card__why')).toHaveAttribute('open');
    rerender(
      <AlertCard
        alert={makeAlert({ status: 'resolved', resolved_at: '2026-09-28T13:06:30Z' })}
        now={NOW}
      />,
    );
    expect(container.querySelector('details.alert-card__why')).not.toHaveAttribute('open');
  });

  it('marks freshly arrived cards for the entrance animation only', () => {
    const { rerender } = render(<AlertCard alert={makeAlert()} now={NOW} isNew />);
    expect(screen.getByRole('article')).toHaveClass('alert-card--new');
    rerender(<AlertCard alert={makeAlert()} now={NOW} />);
    expect(screen.getByRole('article')).not.toHaveClass('alert-card--new');
  });
});

describe('AlertCard explanation (contract v2 fields)', () => {
  it.each([
    ['error_spike', 'Error spike'],
    ['silence', 'Silence'],
    ['new_pattern', 'New pattern'],
    ['flow_break', 'Flow break'],
  ] as const)('labels the %s detector', (detector, label) => {
    render(<AlertCard alert={makeExplainedAlert({ detector })} now={NOW} />);
    const header = screen.getByRole('article').querySelector('header') as HTMLElement;
    expect(within(header).getByText(label)).toHaveClass('detector-label');
  });

  it('shows the template in monospace with its wildcards set apart', () => {
    const { container } = render(<AlertCard alert={makeExplainedAlert()} now={NOW} />);
    const template = container.querySelector('.alert-card__template');
    expect(template).toHaveClass('mono');
    expect(template).toHaveTextContent('DB connection timeout for member <*> after <*>ms');
    expect(within(template as HTMLElement).getAllByText('<*>')[0]).toHaveClass('template-wildcard');
  });

  it('compares the observed value with the normal band in its unit', () => {
    render(<AlertCard alert={makeExplainedAlert()} now={NOW} />);
    expect(screen.getByText('Baseline').nextElementSibling).toHaveTextContent(
      'normal \u2264 4 errors/60s, observed 212',
    );
  });

  it('formats fractional measurements and omits a missing observed value', () => {
    const alert = makeExplainedAlert({
      detector: 'silence',
      baseline_band: { median: 30, upper: 42.5, unit: 'seconds between lines' },
      observed: null,
    });
    render(<AlertCard alert={alert} now={NOW} />);
    const band = screen.getByText('Baseline').nextElementSibling;
    expect(band).toHaveTextContent('normal \u2264 42.5 seconds between lines');
    expect(band).not.toHaveTextContent('observed');
  });

  it('lists the top three extracted parameters with their share', () => {
    render(<AlertCard alert={makeExplainedAlert()} now={NOW} />);
    const params = within(screen.getByText('Parameters').nextElementSibling as HTMLElement);
    const items = params.getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('source_ip 10.4.2.17 97%');
    expect(params.getByText('<MEMBER_ID>')).toHaveClass('masked-token');
    expect(params.queryByText('<CLAIM_ID>')).not.toBeInTheDocument();
  });

  it('puts the masked first bad line ahead of the samples', async () => {
    const user = userEvent.setup();
    const { container } = render(<AlertCard alert={makeExplainedAlert()} now={NOW} />);

    await user.click(screen.getByText('First bad line and samples'));
    const first = container.querySelector('.samples__lines--first');
    expect(first).toHaveTextContent('ip=10.4.2.17 DB connection timeout for member <MEMBER_ID>');
    expect(within(first as HTMLElement).getByText('<MEMBER_ID>')).toHaveClass('masked-token');
    expect(screen.getByRole('heading', { level: 4, name: 'Samples' })).toBeInTheDocument();
  });

  it('shows the first bad line on its own when there are no samples', () => {
    render(<AlertCard alert={makeExplainedAlert({ sample_lines: [] })} now={NOW} />);
    expect(screen.getByText('First bad line', { selector: 'summary' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Samples' })).not.toBeInTheDocument();
  });

  it.each([
    ['missing', makeAlert()],
    [
      'null',
      makeAlert({
        detector: null,
        template: null,
        baseline_band: null,
        observed: null,
        first_bad_line: null,
        params: null,
      }),
    ],
  ])('renders the original card when the new fields are %s', (_, alert) => {
    const { container } = render(<AlertCard alert={alert} now={NOW} />);
    expect(container.querySelector('.detector-label')).toBeNull();
    expect(container.querySelector('.alert-card__explain')).toBeNull();
    expect(container.querySelector('.samples__lines--first')).toBeNull();
    expect(screen.getByText(/Sample log lines/)).toBeInTheDocument();
    expect(screen.getByText('Peak error rate')).toBeInTheDocument();
  });

  it('shows whichever explanation fields are present', () => {
    const alert = makeAlert({
      baseline_band: { median: 0, upper: 2, unit: 'incomplete flows/60s' },
    });
    render(<AlertCard alert={alert} now={NOW} />);
    expect(screen.getByText('Baseline')).toBeInTheDocument();
    expect(screen.queryByText('Template')).not.toBeInTheDocument();
    expect(screen.queryByText('Parameters')).not.toBeInTheDocument();
  });
});
