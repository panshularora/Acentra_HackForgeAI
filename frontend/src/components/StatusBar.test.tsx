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

  it('shows the product name and baseline progress', () => {
    render(
      <StatusBar
        connection="live"
        baseline={{ kind: 'learning', collected: 2, required: 12 }}
        health={health}
        now={0}
      />,
    );
    expect(screen.getByText('Learning baseline, 2 of 12 buckets')).toBeInTheDocument();
    expect(screen.getByText('ClaimsWatch')).toBeInTheDocument();
  });

  it('keeps the live label when the newest bucket is fresh', () => {
    render(
      <StatusBar
        connection="live"
        baseline={{ kind: 'ready' }}
        health={health}
        now={Date.parse('2026-09-28T13:05:18Z')}
        lastUpdate="2026-09-28T13:05:10Z"
        bucketSeconds={10}
      />,
    );
    expect(screen.getByRole('status', { name: /Live stream: Live/ })).toHaveTextContent(
      'Live · 8s ago',
    );
  });

  it('calls out a delayed stream instead of a green live dot', () => {
    render(
      <StatusBar
        connection="live"
        baseline={{ kind: 'ready' }}
        health={health}
        now={Date.parse('2026-09-28T13:05:40Z')}
        lastUpdate="2026-09-28T13:05:10Z"
        bucketSeconds={10}
      />,
    );
    expect(screen.getByRole('status')).toHaveClass('connection--delayed');
    expect(screen.getByRole('status')).toHaveTextContent('Live · delayed');
  });

  it('replaces the learning badge with "Ingest retrying" while monitoring is degraded', () => {
    render(
      <StatusBar
        connection="live"
        baseline={{ kind: 'ready', templates: 38 }}
        health={health}
        now={0}
        monitoring={{ kind: 'degraded', error: 'boom' }}
      />,
    );
    expect(screen.getByText('Ingest retrying')).toHaveClass('monitor-badge');
    expect(screen.queryByText('Monitoring, 38 templates')).not.toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Live stream: Live' })).toBeInTheDocument();
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
