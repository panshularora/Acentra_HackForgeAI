import type { ReactNode } from 'react';
import type { BaselineState } from '../lib/detector';
import { describeBaseline } from '../lib/detector';
import { formatClock, formatDuration, formatPercent, formatScore } from '../lib/format';
import type { MonitoringStatus } from '../lib/health';
import { incidentAnchor } from '../lib/anchors';
import type { SceneModel } from '../lib/scene';
import { SEVERITY_LABEL, SEVERITY_THRESHOLD } from '../lib/severity';
import type { StatsPoint } from '../types';
import { SeverityBadge } from './SeverityBadge';

interface StatusHeroProps {
  model: SceneModel;
  monitoring: MonitoringStatus;
  baseline: BaselineState;
  latest: StatsPoint | undefined;
  now: number;
  windowSeconds: number;
}

function focusIncident(id: string) {
  const card = document.getElementById(incidentAnchor(id));
  if (!card) return;
  card.scrollIntoView({ block: 'start', behavior: 'smooth' });
  card.focus({ preventScroll: true });
}

/**
 * The one-sentence answer to "is anything wrong right now?", in words. The
 * 3D view beside it shows the same state; this text is the source of truth.
 */
export function StatusHero({
  model,
  monitoring,
  baseline,
  latest,
  now,
  windowSeconds,
}: StatusHeroProps) {
  const incident = model.topIncident;

  let eyebrow: ReactNode;
  let title: string;
  let body: ReactNode;
  let extra: ReactNode = null;

  switch (model.tone) {
    case 'connecting':
      eyebrow = 'Connecting';
      title = 'Connecting to the detector\u2026';
      body = 'Waiting for the backend to answer on /api and /ws.';
      break;
    case 'offline':
      eyebrow = 'Disconnected';
      title = 'Backend unreachable';
      body = latest ? (
        <>
          Showing data up to{' '}
          <time className="mono" dateTime={latest.ts}>
            {formatClock(latest.ts)}
          </time>
          . Reconnecting automatically.
        </>
      ) : (
        <>
          No data yet. Start the backend (<code className="mono">make dev</code>, port 8000); the
          dashboard reconnects automatically.
        </>
      );
      break;
    case 'degraded':
      eyebrow = 'Degraded';
      title = 'Monitoring degraded, retrying';
      body =
        'The backend is up but cannot read the log right now, so no new anomalies can be detected. It retries on its own; nothing to do here unless this persists.';
      extra =
        monitoring.kind === 'degraded' && monitoring.error ? (
          <p className="hero__error">
            <span className="hero__error-label">Last error</span>
            <code className="mono">{monitoring.error}</code>
          </p>
        ) : null;
      break;
    case 'incident': {
      if (!incident) return null;
      const alert = incident;
      const others = model.openCount - 1;
      eyebrow = (
        <>
          <SeverityBadge severity={alert.severity} />
          <span>Open incident{others > 0 && ` \u00b7 ${others} more open`}</span>
        </>
      );
      title = alert.summary;
      body = (
        <>
          Started{' '}
          <time className="mono" dateTime={alert.opened_at}>
            {formatClock(alert.opened_at)}
          </time>
          , ongoing{' '}
          <span className="mono">{formatDuration(now - Date.parse(alert.opened_at))}</span>. Peak
          modified z-score <span className="mono">{formatScore(alert.score)}</span>{' '}
          <span className="muted">
            ({SEVERITY_LABEL[alert.severity]} at{' '}
            <span className="mono">&ge; {SEVERITY_THRESHOLD[alert.severity]}</span>)
          </span>
          .
        </>
      );
      extra = (
        <div className="hero__actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => focusIncident(alert.id)}
          >
            View incident
          </button>
          <span className="hero__hint">
            Percentages are shares of all errors in the {windowSeconds}s window.
          </span>
        </div>
      );
      break;
    }
    case 'learning':
      eyebrow = 'Learning';
      title = 'Learning what normal looks like';
      body = (
        <>
          {describeBaseline(baseline, windowSeconds)}. Alerts start once every error template has a
          baseline.
        </>
      );
      break;
    case 'calm':
      eyebrow = 'All clear';
      title = 'No anomalies detected';
      body = (
        <>
          Error rate <span className="mono">{formatPercent(latest?.error_rate)}</span>
          {latest?.band_upper != null && (
            <>
              , within the normal range (up to{' '}
              <span className="mono">{formatPercent(latest.band_upper)}</span>)
            </>
          )}
          . Each error template is scored against its own baseline.
        </>
      );
      break;
  }

  return (
    <div className={`hero__status hero__status--${model.tone}`}>
      <p className="hero__eyebrow">{eyebrow}</p>
      <h1 className="hero__title">{title}</h1>
      <p className="hero__body">{body}</p>
      {extra}
    </div>
  );
}
