import { makeAlert, makeStatsPoint } from '../test/fixtures';
import { SEVERITY_COLOR } from '../theme';
import { openIncidents, sceneModel, sceneVisual, type SceneInput } from './scene';

const palette = { core: '#aaaaaa', coreDim: '#444444', error: '#ee6666', severity: SEVERITY_COLOR };

function input(overrides: Partial<SceneInput> = {}): SceneInput {
  return {
    connection: 'live',
    monitoring: { kind: 'ok' },
    baseline: { kind: 'ready' },
    latest: makeStatsPoint({ total: 2400, errors: 48, error_rate: 0.02, band_upper: 0.04 }),
    alerts: [],
    windowSeconds: 60,
    ...overrides,
  };
}

describe('sceneModel', () => {
  it('is calm with live flow and the rate against the edge of normal', () => {
    const model = sceneModel(input());
    expect(model.tone).toBe('calm');
    expect(model.linesPerSecond).toBe(40);
    expect(model.errorShare).toBeCloseTo(0.02);
    expect(model.rateRatio).toBeCloseTo(0.5);
    expect(model.description).toMatch(/all clear/);
  });

  it('has no rate ratio while the baseline is still being learned', () => {
    const model = sceneModel(
      input({
        baseline: { kind: 'learning', collected: 2, required: 6 },
        latest: makeStatsPoint({ baseline_median: null, band_upper: null }),
      }),
    );
    expect(model.tone).toBe('learning');
    expect(model.rateRatio).toBeNull();
  });

  it('takes the most severe open incident and ignores resolved ones', () => {
    const alerts = [
      makeAlert({ id: 'w', severity: 'WARNING', opened_at: '2026-09-28T13:06:00Z' }),
      makeAlert({ id: 'c', severity: 'CRITICAL', opened_at: '2026-09-28T13:05:00Z' }),
      makeAlert({ id: 'r', severity: 'CRITICAL', status: 'resolved' }),
    ];
    const model = sceneModel(input({ alerts }));
    expect(model.tone).toBe('incident');
    expect(model.severity).toBe('CRITICAL');
    expect(model.topIncident?.id).toBe('c');
    expect(model.openCount).toBe(2);
    expect(openIncidents(alerts).map((a) => a.id)).toEqual(['c', 'w']);
  });

  it('changes the pulse key when an incident opens or escalates, not otherwise', () => {
    const open = sceneModel(input({ alerts: [makeAlert({ id: 'a', severity: 'HIGH' })] }));
    const same = sceneModel(input({ alerts: [makeAlert({ id: 'a', severity: 'HIGH' })] }));
    const escalated = sceneModel(input({ alerts: [makeAlert({ id: 'a' })] }));
    expect(same.pulseKey).toBe(open.pulseKey);
    expect(escalated.pulseKey).not.toBe(open.pulseKey);
  });

  it('shows degraded monitoring over an open incident, and stops the flow', () => {
    const model = sceneModel(
      input({ monitoring: { kind: 'degraded', error: 'boom' }, alerts: [makeAlert()] }),
    );
    expect(model.tone).toBe('degraded');
    expect(model.linesPerSecond).toBe(0);
    expect(model.description).toMatch(/degraded/);
  });

  it('shows a lost connection over everything else', () => {
    const model = sceneModel(
      input({ connection: 'reconnecting', monitoring: { kind: 'degraded', error: null } }),
    );
    expect(model.tone).toBe('offline');
    expect(model.linesPerSecond).toBe(0);
  });
});

describe('sceneVisual', () => {
  it('colours the core by severity and beats faster for worse incidents', () => {
    const critical = sceneVisual(sceneModel(input({ alerts: [makeAlert()] })), palette);
    const warning = sceneVisual(
      sceneModel(input({ alerts: [makeAlert({ severity: 'WARNING' })] })),
      palette,
    );
    expect(critical.coreColor).toBe(SEVERITY_COLOR.CRITICAL);
    expect(critical.beat).toBeGreaterThan(warning.beat);
  });

  it('dims and stalls the core when monitoring is degraded', () => {
    const calm = sceneVisual(sceneModel(input()), palette);
    const degraded = sceneVisual(
      sceneModel(input({ monitoring: { kind: 'degraded', error: null } })),
      palette,
    );
    expect(degraded.coreColor).toBe(palette.coreDim);
    expect(degraded.glow).toBeLessThan(calm.glow);
    expect(degraded.flow).toBeLessThan(0.1);
    expect(degraded.opacity).toBeLessThan(calm.opacity);
  });
});
