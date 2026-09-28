import { render, screen } from '@testing-library/react';
import { makeStatsSeries } from '../test/fixtures';
import { ErrorRateChart } from './ErrorRateChart';

describe('ErrorRateChart', () => {
  it('says it is connecting before any data arrives', () => {
    render(<ErrorRateChart stats={[]} baseline={{ kind: 'waiting' }} connection="connecting" />);
    expect(screen.getByText('Connecting to the live stream.')).toBeInTheDocument();
  });

  it('waits for the first bucket once connected', () => {
    render(<ErrorRateChart stats={[]} baseline={{ kind: 'waiting' }} connection="live" />);
    expect(screen.getByText(/Waiting for the first 10-second bucket/)).toBeInTheDocument();
  });

  it('explains that the normal range is still being learned', () => {
    const stats = makeStatsSeries(3, undefined, { baseline_median: null, band_upper: null });
    render(
      <ErrorRateChart
        stats={stats}
        baseline={{ kind: 'learning', collected: 3, required: 12 }}
        connection="live"
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Learning baseline, 3 of 12 buckets');
  });

  it('labels the chart plainly', () => {
    render(
      <ErrorRateChart stats={makeStatsSeries(5)} baseline={{ kind: 'ready' }} connection="live" />,
    );
    expect(screen.getByRole('heading', { name: 'Error rate (60s window)' })).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
