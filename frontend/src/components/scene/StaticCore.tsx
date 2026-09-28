import { sceneVisual, type SceneModel } from '../../lib/scene';
import { SCENE_COLOR } from '../../theme';
import { RATIO_MAX, SCENE_PALETTE, clampRatio } from './sceneColors';

const SIZE = 200;
const C = SIZE / 2;
/** Baseline ring radius in SVG units; leaves room for the rate ring at RATIO_MAX. */
const BASELINE_R = 88 / RATIO_MAX;
const DOTS = 42;

/** Deterministic positions (golden-angle spiral) so the picture never jitters between renders. */
const DOT_POSITIONS = Array.from({ length: DOTS }, (_, i) => {
  const angle = i * 2.39996;
  const r = 34 + ((i * 37) % 60);
  return { x: C + r * Math.cos(angle), y: C + r * Math.sin(angle) * 0.62, r: 1.3 + (i % 3) * 0.35 };
});

/**
 * The same picture as the 3D view, flat and still: shown while the 3D bundle
 * loads, when WebGL is unavailable or fails, and nowhere else. It carries the
 * same meaning (core colour, rings, error-dot share) so nothing is lost.
 */
export function StaticCore({ model }: { model: SceneModel }) {
  const visual = sceneVisual(model, SCENE_PALETTE);
  const errorDots = Math.round(model.errorShare * DOTS);
  const showDots = model.linesPerSecond > 0 || model.tone === 'degraded';
  const ratio = model.rateRatio === null ? null : clampRatio(model.rateRatio);
  const above = (model.rateRatio ?? 0) > 1;

  return (
    <svg
      className="scene__static"
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
      focusable="false"
      data-tone={model.tone}
    >
      {showDots && (
        <g opacity={visual.opacity}>
          {DOT_POSITIONS.map((dot, i) => (
            <circle
              key={i}
              cx={dot.x}
              cy={dot.y}
              r={i < errorDots ? dot.r * 1.4 : dot.r}
              fill={i < errorDots ? visual.alertColor : SCENE_COLOR.line}
              opacity={0.75}
            />
          ))}
        </g>
      )}
      <circle
        cx={C}
        cy={C}
        r={BASELINE_R}
        fill="none"
        stroke={SCENE_COLOR.ring}
        strokeWidth={1}
        strokeDasharray="3 3"
        opacity={ratio === null ? 0.4 : 0.9}
      />
      {ratio !== null && (
        <circle
          cx={C}
          cy={C}
          r={BASELINE_R * ratio}
          fill="none"
          stroke={above ? visual.alertColor : SCENE_COLOR.rate}
          strokeWidth={above ? 2 : 1.25}
          opacity={visual.opacity}
        />
      )}
      <circle cx={C} cy={C} r={22} fill={visual.coreColor} opacity={0.18 + visual.glow * 0.3} />
      <circle cx={C} cy={C} r={15} fill={visual.coreColor} />
    </svg>
  );
}
