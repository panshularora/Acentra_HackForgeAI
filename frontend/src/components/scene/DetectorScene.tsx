import { Component, lazy, Suspense, useCallback, useRef, useState, type ReactNode } from 'react';
import { usePrefersReducedMotion } from '../../hooks/useMediaQuery';
import { useRenderGate } from '../../hooks/useRenderGate';
import type { SceneModel } from '../../lib/scene';
import { hasWebGL } from '../../lib/webgl';
import { StaticCore } from './StaticCore';

// three.js and React Three Fiber load only when the view mounts in a browser with WebGL.
const DetectorCanvas = lazy(() => import('./DetectorCanvas'));

/** Falls back to the static picture if the 3D view throws while rendering. */
class SceneBoundary extends Component<
  { fallback: ReactNode; onError: () => void; children: ReactNode },
  { failed: boolean }
> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override componentDidCatch() {
    this.props.onError();
  }

  override render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

interface DetectorSceneProps {
  model: SceneModel;
  /** Test hook: force the static picture regardless of WebGL support. */
  forceStatic?: boolean;
}

/**
 * The detector visual plus its legend. Picks the 3D canvas when WebGL works,
 * otherwise a static SVG with the same meaning; pauses rendering when hidden;
 * freezes motion for prefers-reduced-motion.
 */
export function DetectorScene({ model, forceStatic = false }: DetectorSceneProps) {
  const container = useRef<HTMLDivElement>(null);
  const active = useRenderGate(container);
  const reducedMotion = usePrefersReducedMotion();
  const [webgl] = useState(() => !forceStatic && hasWebGL());
  const [failed, setFailed] = useState(false);
  const fail = useCallback(() => setFailed(true), []);
  const fallback = <StaticCore model={model} />;
  const use3d = webgl && !failed;

  return (
    <div className={`scene scene--${model.tone}`} data-renderer={use3d ? 'webgl' : 'static'}>
      <div ref={container} className="scene__stage" role="img" aria-label={model.description}>
        {use3d ? (
          <SceneBoundary fallback={fallback} onError={fail}>
            <Suspense fallback={fallback}>
              <DetectorCanvas
                model={model}
                reducedMotion={reducedMotion}
                active={active}
                onContextLost={fail}
              />
            </Suspense>
          </SceneBoundary>
        ) : (
          fallback
        )}
      </div>
      <ul className="scene__legend" aria-label="How to read the detector view">
        <li>
          <span className="scene__key scene__key--line" aria-hidden="true" />
          Log line
        </li>
        <li>
          <span className="scene__key scene__key--error" aria-hidden="true" />
          Error line
        </li>
        <li>
          <span className="scene__key scene__key--band" aria-hidden="true" />
          Normal limit
        </li>
        <li>
          <span className="scene__key scene__key--rate" aria-hidden="true" />
          Current error rate
        </li>
      </ul>
    </div>
  );
}
