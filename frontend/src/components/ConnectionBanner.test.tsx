import { render, screen } from '@testing-library/react';
import { ConnectionBanner } from './ConnectionBanner';

describe('ConnectionBanner', () => {
  it('warns that data is stale while reconnecting', () => {
    render(<ConnectionBanner connection="reconnecting" lastUpdate="2026-09-28T13:05:10Z" />);
    expect(screen.getByRole('alert')).toHaveTextContent(/Connection to the backend lost/);
  });

  it.each(['live', 'connecting'] as const)('stays hidden when %s', (connection) => {
    render(<ConnectionBanner connection={connection} lastUpdate="2026-09-28T13:05:10Z" />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says the backend cannot be reached when nothing has loaded yet', () => {
    render(<ConnectionBanner connection="reconnecting" lastUpdate={undefined} />);
    expect(screen.getByRole('alert')).toHaveTextContent(/reach the backend yet; retrying/);
  });

  it('reports degraded monitoring calmly, with the ingest error, while connected', () => {
    render(
      <ConnectionBanner
        connection="live"
        lastUpdate="2026-09-28T13:05:10Z"
        monitoring={{ kind: 'degraded', error: "PermissionError: 'logs/app.log'" }}
      />,
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    const banner = screen.getByRole('status');
    expect(banner).toHaveTextContent('Monitoring degraded');
    expect(banner).toHaveTextContent("PermissionError: 'logs/app.log'");
  });

  it('prefers the disconnected message over a stale degraded state', () => {
    render(
      <ConnectionBanner
        connection="reconnecting"
        lastUpdate="2026-09-28T13:05:10Z"
        monitoring={{ kind: 'degraded', error: 'boom' }}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/Connection to the backend lost/);
    expect(screen.queryByText(/Monitoring degraded/)).not.toBeInTheDocument();
  });
});
