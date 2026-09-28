import { render, screen } from '@testing-library/react';
import { sceneModel, type SceneInput } from '../../lib/scene';
import { makeAlert, makeStatsPoint } from '../../test/fixtures';
import { DetectorScene } from './DetectorScene';

function model(overrides: Partial<SceneInput> = {}) {
  return sceneModel({
    connection: 'live',
    monitoring: { kind: 'ok' },
    baseline: { kind: 'ready' },
    latest: makeStatsPoint(),
    alerts: [],
    windowSeconds: 60,
    ...overrides,
  });
}

describe('DetectorScene', () => {
  it('falls back to the static picture when WebGL is unavailable (as in jsdom)', () => {
    const { container } = render(<DetectorScene model={model()} />);
    expect(container.querySelector('[data-renderer="static"]')).not.toBeNull();
    expect(container.querySelector('canvas')).toBeNull();
    expect(container.querySelector('svg.scene__static')).not.toBeNull();
  });

  it('describes the state in words for screen readers', () => {
    render(<DetectorScene model={model({ alerts: [makeAlert()] })} forceStatic />);
    expect(screen.getByRole('img')).toHaveAccessibleName(/Critical incident open/);
  });

  it('marks the degraded state so the core is drawn dim', () => {
    const { container } = render(
      <DetectorScene model={model({ monitoring: { kind: 'degraded', error: null } })} />,
    );
    expect(container.querySelector('.scene')).toHaveClass('scene--degraded');
    expect(container.querySelector('svg.scene__static')).toHaveAttribute('data-tone', 'degraded');
  });

  it('has a legend that explains the picture', () => {
    render(<DetectorScene model={model()} />);
    const legend = screen.getByRole('list', { name: 'How to read the detector view' });
    expect(legend).toHaveTextContent('Normal limit');
    expect(legend).toHaveTextContent('Current error rate');
  });
});
