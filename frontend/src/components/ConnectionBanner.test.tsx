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

  it('stays hidden when there is nothing on screen to be stale', () => {
    render(<ConnectionBanner connection="reconnecting" lastUpdate={undefined} />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
