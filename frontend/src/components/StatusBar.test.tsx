import { render, screen } from '@testing-library/react';
import type { Health } from '../types';
import { StatusBar } from './StatusBar';

const health: Health = {
  status: 'ok',
  app: 'ClaimsWatch',
  log_path: 'logs/app.log',
  tailer_offset: 0,
  aws: {
    sns_topic_arn: 'arn:aws:sns:us-east-1:000000000000:claimswatch-alerts',
    cloudwatch_log_group: '/claimswatch/alerts',
    endpoint: 'http://localhost:5000',
  },
};

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
