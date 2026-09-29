import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FaultPanel } from './FaultPanel';

vi.mock('../api/client', () => ({
  injectFault: vi.fn(() =>
    Promise.resolve({ name: 'db-outage', until: '2026-09-29T00:00:00Z', mode: 'lines' }),
  ),
  stopFault: vi.fn(() => Promise.resolve({ stopped: 'db-outage', faults: [] })),
  stopAllFaults: vi.fn(() => Promise.resolve({ stopped: ['db-outage'], faults: [] })),
}));

describe('FaultPanel', () => {
  it('offers every demo fault including silence and flow-break', () => {
    render(<FaultPanel />);
    const list = screen.getAllByRole('list')[0] as HTMLElement;
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(5);
    expect(list).toHaveTextContent('make incident-db');
    expect(list).toHaveTextContent('make incident-silence');
    expect(list).toHaveTextContent('make incident-flow');
  });

  it('injects a fault through the API', async () => {
    const user = userEvent.setup();
    const { injectFault } = await import('../api/client');
    render(<FaultPanel />);
    await user.click(screen.getAllByRole('button', { name: 'Inject' })[0] as HTMLElement);
    expect(injectFault).toHaveBeenCalledWith('db-outage', 45);
    expect(await screen.findByRole('button', { name: 'Stop' })).toBeInTheDocument();
  });

  it('stops a live fault through the API', async () => {
    const user = userEvent.setup();
    const { stopFault } = await import('../api/client');
    render(<FaultPanel activeNames={['db-outage']} />);
    await user.click(screen.getByRole('button', { name: 'Stop' }));
    expect(stopFault).toHaveBeenCalledWith('db-outage');
    expect(await screen.findAllByRole('button', { name: 'Inject' })).toHaveLength(5);
  });

  it('stops every live fault at once', async () => {
    const user = userEvent.setup();
    const { stopAllFaults } = await import('../api/client');
    render(<FaultPanel activeNames={['db-outage', 'heartbeat-stop']} />);
    await user.click(screen.getByRole('button', { name: 'Stop all' }));
    expect(stopAllFaults).toHaveBeenCalled();
    expect(await screen.findAllByRole('button', { name: 'Inject' })).toHaveLength(5);
  });

  it('switches to Docker commands', async () => {
    const user = userEvent.setup();
    render(<FaultPanel />);
    await user.click(screen.getByRole('button', { name: 'Docker' }));
    expect(
      screen.getByText(
        'docker compose exec loggen python tools/loggen.py --incident db-outage --duration 45',
      ),
    ).toBeInTheDocument();
  });

  it('copies a command to the clipboard', async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    render(<FaultPanel />);
    await user.click(screen.getByRole('button', { name: 'Copy command for Database outage' }));
    expect(writeText).toHaveBeenCalledWith('make incident-db');
    expect(await screen.findByText('Copied')).toBeInTheDocument();
  });
});
