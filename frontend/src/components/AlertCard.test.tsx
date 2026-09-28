import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { makeAlert } from '../test/fixtures';
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

  it('marks freshly arrived cards for the entrance animation only', () => {
    const { rerender } = render(<AlertCard alert={makeAlert()} now={NOW} isNew />);
    expect(screen.getByRole('article')).toHaveClass('alert-card--new');
    rerender(<AlertCard alert={makeAlert()} now={NOW} />);
    expect(screen.getByRole('article')).not.toHaveClass('alert-card--new');
  });
});
