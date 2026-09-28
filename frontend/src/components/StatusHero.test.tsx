import { render, screen } from '@testing-library/react';
import type { MonitoringStatus } from '../lib/health';
import { sceneModel, type SceneInput } from '../lib/scene';
import { makeAlert, makeStatsPoint } from '../test/fixtures';
import { StatusHero } from './StatusHero';

const NOW = Date.parse('2026-09-28T13:07:00Z');

function renderHero(overrides: Partial<SceneInput> = {}) {
  const sceneInput: SceneInput = {
    connection: 'live',
    monitoring: { kind: 'ok' },
    baseline: { kind: 'ready' },
    latest: makeStatsPoint(),
    alerts: [],
    windowSeconds: 60,
    ...overrides,
  };
  const monitoring: MonitoringStatus = sceneInput.monitoring;
  return render(
    <StatusHero
      model={sceneModel(sceneInput)}
      monitoring={monitoring}
      baseline={sceneInput.baseline}
      latest={sceneInput.latest}
      now={NOW}
      windowSeconds={60}
    />,
  );
}

describe('StatusHero', () => {
  it('says all clear with the error rate against its normal range', () => {
    renderHero();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('No anomalies detected');
    expect(screen.getByText(/within the normal range/)).toHaveTextContent('up to 3.1%');
  });

  it('leads with the open incident, its modified z-score and the threshold it crossed', () => {
    renderHero({ alerts: [makeAlert()] });
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '94% of errors come from claim-adjudication',
    );
    expect(screen.getByText('CRITICAL')).toHaveClass('severity-badge');
    expect(screen.getByText(/Peak modified z.score/)).toHaveTextContent(
      '9.4 (Critical at \u22658)',
    );
    expect(screen.getByText(/shares of all errors in the 60s window/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View incident' })).toBeInTheDocument();
  });

  it('shows "Monitoring degraded, retrying" with the ingest error', () => {
    renderHero({
      monitoring: { kind: 'degraded', error: "IsADirectoryError(21, 'Is a directory')" },
      alerts: [makeAlert()],
    });
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Monitoring degraded, retrying',
    );
    expect(screen.getByText("IsADirectoryError(21, 'Is a directory')")).toBeInTheDocument();
    expect(screen.queryByText(/Backend unreachable/)).not.toBeInTheDocument();
  });

  it('words a lost connection differently from degraded monitoring', () => {
    renderHero({ connection: 'reconnecting' });
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Backend unreachable');
    expect(screen.getByText(/Reconnecting automatically/)).toBeInTheDocument();
  });

  it('tells how to start the backend when nothing has ever loaded', () => {
    renderHero({ connection: 'reconnecting', latest: undefined });
    expect(screen.getByText('make dev')).toBeInTheDocument();
  });

  it('explains warm-up while learning', () => {
    renderHero({ baseline: { kind: 'learning', collected: 2, required: 6 } });
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Learning what normal looks like',
    );
    expect(screen.getByText(/Learning baseline, 2 of 6 buckets/)).toBeInTheDocument();
  });
});
