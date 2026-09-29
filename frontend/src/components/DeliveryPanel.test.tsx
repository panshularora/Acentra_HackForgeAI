import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { makeAlert, makeHealth } from '../test/fixtures';
import { DeliveryPanel } from './DeliveryPanel';

const NOW = Date.parse('2026-09-28T13:06:00Z');
const emulated = makeHealth({
  aws: {
    sns_topic_arn: 'arn:aws:sns:us-east-1:000000000000:claimswatch-alerts',
    cloudwatch_log_group: '/claimswatch/alerts',
    endpoint: 'http://localhost:5000',
  },
});

describe('DeliveryPanel', () => {
  it('names the targets and says they are the local emulator', () => {
    render(<DeliveryPanel health={emulated} alerts={[]} now={NOW} />);
    expect(screen.getByText('Local AWS emulator')).toBeInTheDocument();
    expect(screen.getByText('claimswatch-alerts')).toBeInTheDocument();
    expect(screen.getByText('/claimswatch/alerts')).toBeInTheDocument();
    expect(screen.getByText('logs/app.log')).toBeInTheDocument();
    expect(screen.getAllByText('No alerts yet')).toHaveLength(2);
  });

  it('shows whether the latest alert reached SNS, with the error on failure', () => {
    const alerts = [
      makeAlert({ id: 'old', updated_at: '2026-09-28T13:00:00Z' }),
      makeAlert({
        id: 'new',
        updated_at: '2026-09-28T13:05:30Z',
        delivery: {
          sns: { status: 'failed', message_id: null, error: 'AuthorizationError' },
          cloudwatch: { status: 'sent', error: null },
        },
      }),
    ];
    render(<DeliveryPanel health={emulated} alerts={alerts} now={NOW} />);
    expect(screen.getByText('Last alert: failed')).toBeInTheDocument();
    expect(screen.getByText('AuthorizationError')).toBeInTheDocument();
    expect(screen.getByText('Last alert: sent')).toBeInTheDocument();
  });

  it('retries failed SNS deliveries from the panel', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn().mockResolvedValue(1);
    render(
      <DeliveryPanel
        health={emulated}
        alerts={[
          makeAlert({
            delivery: {
              sns: { status: 'failed', message_id: null, error: 'SNS topic unavailable' },
              cloudwatch: { status: 'disabled', error: null },
            },
          }),
        ]}
        now={NOW}
        onRetry={onRetry}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Retry 1 failed' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('says delivery is off when no topic is configured', () => {
    render(<DeliveryPanel health={makeHealth()} alerts={[makeAlert()]} now={NOW} />);
    expect(screen.getByText('Delivery disabled')).toBeInTheDocument();
    expect(screen.getAllByText('Off')).toHaveLength(2);
  });
});
