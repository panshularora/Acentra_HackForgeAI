import { render, screen } from '@testing-library/react';
import { makeHealth } from '../test/fixtures';
import { StatusBar } from './StatusBar';

const health = makeHealth({
  aws: {
    sns_topic_arn: 'arn:aws:sns:us-east-1:000000000000:claimswatch-alerts',
    cloudwatch_log_group: '/claimswatch/alerts',
    endpoint: 'http://localhost:5000',
  },
});

describe('StatusBar', () => {
  it.each([
    ['connecting', 'Connecting'],
    ['live', 'Live'],
    ['reconnecting', 'Reconnecting'],
  ] as const)('shows the %s connection state in text', (connection, label) => {
    render(
      <StatusBar connection={connection} baseline={{ kind: 'ready' }} health={null} now={0} />,
    );
    expect(screen.getByRole('status', { name: `Live stream: ${label}` })).toBeInTheDocument();
  });

  it('shows baseline progress and where alerts are delivered', () => {
    render(
      <StatusBar
        connection="live"
        baseline={{ kind: 'learning', collected: 2, required: 12 }}
        health={health}
        now={0}
      />,
    );
    expect(screen.getByText('Learning baseline, 2 of 12 buckets')).toBeInTheDocument();
    expect(screen.getByText('logs/app.log')).toBeInTheDocument();
    expect(screen.getByText('claimswatch-alerts')).toBeInTheDocument();
    expect(screen.getByText('/claimswatch/alerts')).toBeInTheDocument();
  });
});

describe('StatusBar learning badge', () => {
  it('shows monitoring and the template count from the backend', () => {
    render(
      <StatusBar
        connection="live"
        baseline={{ kind: 'ready', templates: 38 }}
        health={health}
        now={0}
      />,
    );
    expect(screen.getByText('Monitoring, 38 templates')).toHaveClass('learning-badge');
  });

  it('labels the first-window phase with the window length from /api/health', () => {
    render(
      <StatusBar
        connection="live"
        baseline={{ kind: 'filling', collected: 1, required: 6 }}
        health={makeHealth({
          detector: { window_seconds: 120, bucket_seconds: 20, baseline_min_buckets: 4 },
        })}
        now={0}
      />,
    );
    expect(screen.getByText(/Filling first 120s window, 1 of 6 buckets/)).toBeInTheDocument();
  });
});
