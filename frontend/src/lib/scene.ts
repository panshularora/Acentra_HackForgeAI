import type { ConnectionState } from '../hooks/alertStreamReducer';
import type { Alert, Severity, StatsPoint } from '../types';
import type { BaselineState } from './detector';
import { formatPercent } from './format';
import type { MonitoringStatus } from './health';
import { SEVERITIES, SEVERITY_LABEL } from './severity';

/**
 * What the dashboard's headline and 3D view should say right now, derived
 * from live data only. Kept pure so the rules are testable without WebGL.
 *
 * Precedence: a lost connection beats everything (the data is stale), then a
 * degraded backend (it is not reading the log), then an open incident, then
 * warm-up, then all clear.
 */
export type SceneTone = 'connecting' | 'offline' | 'degraded' | 'incident' | 'learning' | 'calm';

export interface SceneModel {
  tone: SceneTone;
  /** Highest severity among open incidents, when tone is "incident". */
  severity: Severity | null;
  /** The most severe (then newest) open incident. */
  topIncident: Alert | null;
  openCount: number;
  /** Log lines per second over the window; drives the particle spawn rate. */
  linesPerSecond: number;
  /** Share of lines that are errors, 0..1; drives the share of red particles. */
  errorShare: number;
  /** Current error rate divided by the edge of normal; null while learning. */
  rateRatio: number | null;
  /** Changes whenever an incident opens or escalates, to trigger one pulse. */
  pulseKey: string;
  /** Text alternative for the visual. */
  description: string;
}

export interface SceneInput {
  connection: ConnectionState;
  monitoring: MonitoringStatus;
  baseline: BaselineState;
  latest: StatsPoint | undefined;
  alerts: readonly Alert[];
  windowSeconds: number;
}

const rank = (severity: Severity) => SEVERITIES.indexOf(severity);

/** Open incidents, most severe first, newest first within a severity. */
export function openIncidents(alerts: readonly Alert[]): Alert[] {
  return alerts
    .filter((a) => a.status === 'open')
    .sort(
      (a, b) =>
        rank(a.severity) - rank(b.severity) || Date.parse(b.opened_at) - Date.parse(a.opened_at),
    );
}

export function sceneModel({
  connection,
  monitoring,
  baseline,
  latest,
  alerts,
  windowSeconds,
}: SceneInput): SceneModel {
  const open = openIncidents(alerts);
  const top = open[0] ?? null;
  const total = latest?.total ?? 0;
  const linesPerSecond = windowSeconds > 0 ? total / windowSeconds : 0;
  const errorShare = latest?.error_rate ?? (total > 0 ? (latest?.errors ?? 0) / total : 0);
  const rateRatio =
    latest?.error_rate != null && latest.band_upper != null && latest.band_upper > 0
      ? latest.error_rate / latest.band_upper
      : null;

  let tone: SceneTone;
  if (connection === 'connecting') tone = 'connecting';
  else if (connection === 'reconnecting') tone = 'offline';
  else if (monitoring.kind === 'degraded') tone = 'degraded';
  else if (top) tone = 'incident';
  else if (baseline.kind !== 'ready') tone = 'learning';
  else tone = 'calm';

  const rate = formatPercent(latest?.error_rate);
  const flow = `${Math.round(linesPerSecond)} log lines per second, error rate ${rate}`;
  let description: string;
  switch (tone) {
    case 'connecting':
      description = 'Detector view: connecting to the backend.';
      break;
    case 'offline':
      description = 'Detector view: backend unreachable, log flow stopped.';
      break;
    case 'degraded':
      description = 'Detector view: monitoring degraded, log ingestion stalled while it retries.';
      break;
    case 'incident':
      description = `Detector view: ${top ? SEVERITY_LABEL[top.severity] : ''} incident open. ${flow}.`;
      break;
    case 'learning':
      description = `Detector view: learning the baseline. ${flow}.`;
      break;
    case 'calm':
      description = `Detector view: all clear. ${flow}.`;
      break;
  }

  const live = tone === 'incident' || tone === 'learning' || tone === 'calm';
  return {
    tone,
    severity: tone === 'incident' && top ? top.severity : null,
    topIncident: top,
    openCount: open.length,
    linesPerSecond: live ? linesPerSecond : 0,
    errorShare: Math.min(1, Math.max(0, errorShare)),
    rateRatio,
    pulseKey: open.map((a) => `${a.id}:${a.severity}`).join('|'),
    description,
  };
}

/** How the 3D view (and its static fallback) renders a SceneModel. */
export interface SceneVisual {
  coreColor: string;
  /** Glow strength of the core, 0..~1.2. */
  glow: number;
  /** Heartbeat speed in radians per second; 0 freezes the core. */
  beat: number;
  /** Heartbeat amplitude as a fraction of the core radius. */
  beatAmp: number;
  /** Rotation speed of the wireframe shell, radians per second. */
  spin: number;
  /** Particle travel speed multiplier; near 0 means the flow has stalled. */
  flow: number;
  /** Opacity of particles and rings; lowered when the data is not live. */
  opacity: number;
  /** Colour of error-line particles and of the rate ring once above normal. */
  alertColor: string;
}

const BEAT: Record<Severity, number> = { WARNING: 3, HIGH: 4, CRITICAL: 5.5 };

export function sceneVisual(
  model: SceneModel,
  colors: {
    core: string;
    coreDim: string;
    error: string;
    severity: Record<Severity, string>;
  },
): SceneVisual {
  switch (model.tone) {
    case 'incident': {
      const severity = model.severity ?? 'WARNING';
      return {
        coreColor: colors.severity[severity],
        glow: 1.1,
        beat: BEAT[severity],
        beatAmp: 0.07,
        spin: 0.35,
        flow: 1,
        opacity: 1,
        alertColor: colors.severity[severity],
      };
    }
    case 'calm':
    case 'learning':
      return {
        coreColor: colors.core,
        glow: model.tone === 'calm' ? 0.35 : 0.22,
        beat: 1.4,
        beatAmp: 0.025,
        spin: 0.12,
        flow: 1,
        opacity: model.tone === 'calm' ? 1 : 0.85,
        alertColor: colors.error,
      };
    case 'degraded':
      // Stalled, not dead: the flow creeps and the core barely glows.
      return {
        coreColor: colors.coreDim,
        glow: 0.08,
        beat: 0.35,
        beatAmp: 0.015,
        spin: 0.02,
        flow: 0.06,
        opacity: 0.4,
        alertColor: colors.error,
      };
    case 'offline':
    case 'connecting':
      return {
        coreColor: colors.coreDim,
        glow: 0.04,
        beat: 0,
        beatAmp: 0,
        spin: 0,
        flow: 0,
        opacity: 0.3,
        alertColor: colors.error,
      };
  }
}
