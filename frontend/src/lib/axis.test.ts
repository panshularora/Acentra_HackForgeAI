import { percentAxis } from './axis';

describe('percentAxis', () => {
  it('uses round steps with headroom above the data', () => {
    expect(percentAxis(0.19)).toEqual({ max: 0.25, ticks: [0, 0.05, 0.1, 0.15, 0.2, 0.25] });
    expect(percentAxis(0.03)).toEqual({ max: 0.04, ticks: [0, 0.01, 0.02, 0.03, 0.04] });
  });

  it('never collapses to a zero-height axis', () => {
    expect(percentAxis(0).max).toBeGreaterThan(0);
  });
});
