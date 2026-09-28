/**
 * Picks a round tick step so the y-axis shows at most five intervals with
 * readable labels (0%, 5%, 10%...), leaving ~10% headroom above the data.
 */
export function percentAxis(maxValue: number): { max: number; ticks: number[] } {
  const steps = [0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25];
  const target = Math.max(maxValue, 0.01) * 1.1;
  const step = steps.find((s) => Math.ceil(target / s) <= 5) ?? 0.25;
  const count = Math.max(1, Math.ceil(target / step));
  const ticks = Array.from({ length: count + 1 }, (_, i) => Number((i * step).toFixed(4)));
  return { max: ticks[ticks.length - 1] ?? step, ticks };
}
