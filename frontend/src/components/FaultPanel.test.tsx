import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FaultPanel } from './FaultPanel';

describe('FaultPanel', () => {
  it('offers only the faults the live detector catches', () => {
    render(<FaultPanel />);
    const list = screen.getAllByRole('list')[0] as HTMLElement;
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(list).toHaveTextContent('make incident-db');
    expect(list).toHaveTextContent('make incident-auth');
    expect(list).toHaveTextContent('make incident-new');
    expect(list).not.toHaveTextContent('incident-silence');
    expect(list).not.toHaveTextContent('incident-flow');
  });

  it('marks heartbeat-stop and flow-break as not detected yet', () => {
    render(<FaultPanel />);
    expect(screen.getByText(/not detected yet/)).toHaveTextContent('heartbeat-stop, flow-break');
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
