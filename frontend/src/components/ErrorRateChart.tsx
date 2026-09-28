import { useMemo } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ConnectionState } from '../hooks/alertStreamReducer';
import { percentAxis } from '../lib/axis';
import { BUCKET_SECONDS, describeBaseline, type BaselineState } from '../lib/detector';
import { formatClock, formatCount, formatPercent, formatScore } from '../lib/format';
import { SEVERITIES } from '../lib/severity';
import { COLOR, FONT, SEVERITY_COLOR } from '../theme';
import type { Severity, StatsPoint } from '../types';
import { SeverityBadge } from './SeverityBadge';

const VISIBLE_WINDOW_MS = 10 * 60 * 1000;
const TICK_INTERVAL_MS = 60 * 1000;

interface ChartDatum {
  t: number;
  rate: number;
  /** [baseline median, band upper] for the ranged area; null while learning. */
  band: [number, number] | null;
  median: number | null;
  point: StatsPoint;
}

interface AnomalySpan {
  start: number;
  end: number;
  severity: Severity;
}

function toDatum(point: StatsPoint): ChartDatum {
  const { baseline_median: median, band_upper: upper } = point;
  return {
    t: Date.parse(point.ts),
    rate: point.error_rate,
    band: median !== null && upper !== null ? [median, upper] : null,
    median,
    point,
  };
}

/** Groups consecutive anomalous buckets into spans tinted by their peak severity. */
function anomalySpans(data: ChartDatum[]): AnomalySpan[] {
  const spans: AnomalySpan[] = [];
  const bucketMs = BUCKET_SECONDS * 1000;
  let current: AnomalySpan | null = null;
  for (const d of data) {
    const severity = d.point.severity;
    if (!severity) {
      current = null;
      continue;
    }
    if (current && d.t - current.end <= bucketMs) {
      current.end = d.t;
      if (SEVERITIES.indexOf(severity) < SEVERITIES.indexOf(current.severity)) {
        current.severity = severity;
      }
    } else {
      current = { start: d.t - bucketMs, end: d.t, severity };
      spans.push(current);
    }
  }
  return spans;
}

function minuteTicks(start: number, end: number): number[] {
  const ticks: number[] = [];
  for (
    let t = Math.ceil(start / TICK_INTERVAL_MS) * TICK_INTERVAL_MS;
    t <= end;
    t += TICK_INTERVAL_MS
  ) {
    ticks.push(t);
  }
  return ticks;
}

function AnomalyDot(props: { cx?: number; cy?: number; payload?: ChartDatum }) {
  const { cx, cy, payload } = props;
  const severity = payload?.point.severity;
  if (cx == null || cy == null || !severity) return null;
  return (
    <circle
      cx={cx}
      cy={cy}
      r={3.5}
      fill={SEVERITY_COLOR[severity]}
      stroke={COLOR.surface}
      strokeWidth={1.5}
    />
  );
}

/** Only the fields of Recharts' tooltip props this component reads. */
interface ChartTooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: unknown }>;
}

function ChartTooltip({ active, payload }: ChartTooltipProps) {
  const datum = payload?.[0]?.payload as ChartDatum | undefined;
  if (!active || !datum) return null;
  const { point } = datum;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__time mono">{formatClock(point.ts)}</div>
      <dl>
        <dt>Error rate</dt>
        <dd className="mono">{formatPercent(point.error_rate)}</dd>
        <dt>Baseline median</dt>
        <dd className="mono">{formatPercent(point.baseline_median)}</dd>
        <dt>Normal up to</dt>
        <dd className="mono">{formatPercent(point.band_upper)}</dd>
        <dt>Modified z-score</dt>
        <dd className="mono">{formatScore(point.score)}</dd>
        <dt>Errors / lines</dt>
        <dd className="mono">
          {formatCount(point.errors)} / {formatCount(point.total)}
        </dd>
      </dl>
      {point.severity && <SeverityBadge severity={point.severity} />}
    </div>
  );
}

interface ErrorRateChartProps {
  stats: StatsPoint[];
  baseline: BaselineState;
  connection: ConnectionState;
}

export function ErrorRateChart({ stats, baseline, connection }: ErrorRateChartProps) {
  const data = useMemo(() => stats.map(toDatum), [stats]);
  const spans = useMemo(() => anomalySpans(data), [data]);

  const end = data[data.length - 1]?.t ?? 0;
  const start = end - VISIBLE_WINDOW_MS;
  const yAxis = percentAxis(Math.max(0, ...data.map((d) => Math.max(d.rate, d.band?.[1] ?? 0))));
  const yDigits = yAxis.ticks.some((t) => Math.round(t * 1000) % 10 !== 0) ? 1 : 0;
  const axisTick = { fill: COLOR.textMuted, fontSize: 11, fontFamily: FONT.mono };

  return (
    <section className="panel chart-panel" aria-labelledby="chart-title">
      <header className="panel__header">
        <div>
          <h2 id="chart-title" className="panel__title">
            Error rate (60s window)
          </h2>
          <p className="panel__subtitle">Updated every {BUCKET_SECONDS}s, last 10 minutes</p>
        </div>
        <ul className="chart-legend" aria-label="Chart legend">
          <li>
            <span className="chart-legend__line" aria-hidden="true" />
            Error rate
          </li>
          <li>
            <span className="chart-legend__band" aria-hidden="true" />
            Normal range (baseline median to upper bound)
          </li>
          <li>
            <span className="chart-legend__dot" aria-hidden="true" />
            Anomalous bucket
          </li>
        </ul>
      </header>

      <div className="chart-panel__body">
        {data.length === 0 ? (
          <p className="empty-state">
            {connection === 'live'
              ? `Waiting for the first ${BUCKET_SECONDS}-second bucket from the log tailer.`
              : 'Connecting to the live stream.'}
          </p>
        ) : (
          <>
            {(baseline.kind === 'filling' || baseline.kind === 'learning') && (
              <p className="chart-panel__notice" role="status">
                {describeBaseline(baseline)}. The normal range and alerting start once it is ready.
              </p>
            )}
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: 4 }}>
                <CartesianGrid stroke={COLOR.grid} vertical={false} />
                <XAxis
                  dataKey="t"
                  type="number"
                  scale="time"
                  domain={[start, end]}
                  ticks={minuteTicks(start, end)}
                  tickFormatter={(t: number) => formatClock(t, { seconds: false })}
                  tick={axisTick}
                  tickLine={false}
                  axisLine={{ stroke: COLOR.border }}
                  allowDataOverflow
                />
                <YAxis
                  domain={[0, yAxis.max]}
                  ticks={yAxis.ticks}
                  tickFormatter={(v: number) => (v === 0 ? '0%' : `${(v * 100).toFixed(yDigits)}%`)}
                  tick={axisTick}
                  tickLine={false}
                  axisLine={false}
                  width={52}
                />
                {spans.map((span) => (
                  <ReferenceArea
                    key={span.start}
                    x1={Math.max(span.start, start)}
                    x2={span.end}
                    fill={SEVERITY_COLOR[span.severity]}
                    fillOpacity={0.08}
                    stroke="none"
                    ifOverflow="hidden"
                  />
                ))}
                <Area
                  dataKey="band"
                  type="linear"
                  fill={COLOR.band}
                  fillOpacity={1}
                  stroke={COLOR.bandEdge}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  isAnimationActive={false}
                  connectNulls={false}
                  activeDot={false}
                  name="Normal range"
                />
                <Line
                  dataKey="median"
                  type="linear"
                  stroke={COLOR.textMuted}
                  strokeWidth={1}
                  strokeOpacity={0.6}
                  dot={false}
                  activeDot={false}
                  isAnimationActive={false}
                  name="Baseline median"
                />
                <Line
                  dataKey="rate"
                  type="linear"
                  stroke={COLOR.line}
                  strokeWidth={1.75}
                  dot={<AnomalyDot />}
                  activeDot={{ r: 3, fill: COLOR.line, stroke: COLOR.surface }}
                  isAnimationActive={false}
                  name="Error rate"
                />
                <Tooltip
                  content={ChartTooltip}
                  cursor={{ stroke: COLOR.borderStrong }}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </>
        )}
      </div>
    </section>
  );
}
