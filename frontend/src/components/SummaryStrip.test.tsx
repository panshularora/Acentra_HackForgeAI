import { render, screen } from '@testing-library/react';
import { makeStatsPoint } from '../test/fixtures';
import { SummaryStrip } from './SummaryStrip';

describe('SummaryStrip', () => {
  it('shows no error rate for a window that held no lines', () => {
    const empty = makeStatsPoint({ total: 0, errors: 0, error_rate: null, score: null });
    render(<SummaryStrip latest={empty} alerts={[]} now={0} />);

    const rate = screen.getByText('Error rate (60s window)').nextElementSibling;
    expect(rate).toHaveTextContent('\u2014');
  });

  it('shows the edge of normal and the baseline median', () => {
    render(<SummaryStrip latest={makeStatsPoint()} alerts={[]} now={0} />);
    const normal = screen.getByText('Normal up to').nextElementSibling;
    expect(normal).toHaveTextContent('3.1%');
    expect(normal).toHaveTextContent('median 1.9%');
  });

  it('labels the window with the configured length', () => {
    render(<SummaryStrip latest={makeStatsPoint()} alerts={[]} now={0} windowSeconds={120} />);

    expect(screen.getByText('Log lines (120s)')).toBeInTheDocument();
  });
});
