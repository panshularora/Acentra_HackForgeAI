import { Line, PerformanceMonitor } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  AdditiveBlending,
  Color,
  type Group,
  type InstancedMesh,
  type Mesh,
  type MeshBasicMaterial,
  type MeshStandardMaterial,
  type PointLight,
} from 'three';
import { sceneVisual, type SceneModel, type SceneVisual } from '../../lib/scene';
import { COLOR, SCENE_COLOR } from '../../theme';
import { MAX_PARTICLES, ParticleField } from './particleField';
import { BASELINE_RING, SCENE_PALETTE, clampRatio } from './sceneColors';

/**
 * The 3D detector view: log lines stream in as instanced particles and fall
 * into the detector core. The dashed ring is the edge of normal; the solid
 * ring is the current error rate on the same scale, so it crossing the dashed
 * ring means "above baseline". The core takes the severity colour and beats
 * faster while an incident is open, and dims and stalls when the backend
 * cannot read the log. Loaded lazily; see DetectorScene for the fallbacks.
 */

interface DetectorCanvasProps {
  model: SceneModel;
  reducedMotion: boolean;
  /** False while the tab is hidden or the canvas is off screen: rendering stops. */
  active: boolean;
  onContextLost?: () => void;
}

/** Frame-rate independent exponential smoothing factor. */
const ease = (delta: number, rate: number) => 1 - Math.exp(-delta * rate);

const RING_POINTS = (() => {
  const points: [number, number, number][] = [];
  for (let i = 0; i <= 128; i++) {
    const a = (i / 128) * Math.PI * 2;
    points.push([Math.cos(a), Math.sin(a), 0]);
  }
  return points;
})();

function Particles({
  model,
  visual,
  reducedMotion,
}: {
  model: SceneModel;
  visual: SceneVisual;
  reducedMotion: boolean;
}) {
  const mesh = useRef<InstancedMesh>(null);
  const material = useRef<MeshBasicMaterial>(null);
  const [field] = useState(() => new ParticleField(SCENE_COLOR.line, SCENE_PALETTE.error));
  const flow = useRef(visual.flow);
  const invalidate = useThree((state) => state.invalidate);

  useLayoutEffect(() => {
    if (mesh.current) field.attach(mesh.current);
  }, [field]);

  useEffect(() => {
    if (mesh.current) field.setErrorColor(mesh.current, visual.alertColor);
  }, [field, visual.alertColor]);

  useEffect(() => {
    if (!reducedMotion || !mesh.current) return;
    field.seed(mesh.current, model.linesPerSecond, model.errorShare);
    if (material.current) material.current.opacity = visual.opacity;
    invalidate();
  }, [field, reducedMotion, model.linesPerSecond, model.errorShare, visual.opacity, invalidate]);

  useFrame((_, delta) => {
    if (reducedMotion || !mesh.current) return;
    const dt = Math.min(delta, 0.1);
    flow.current += (visual.flow - flow.current) * ease(dt, 2.5);
    field.step(mesh.current, dt, model.linesPerSecond, model.errorShare, flow.current);
    if (material.current) {
      material.current.opacity += (visual.opacity - material.current.opacity) * ease(dt, 3);
    }
  });

  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, MAX_PARTICLES]} frustumCulled={false}>
      <icosahedronGeometry args={[0.036, 1]} />
      <meshBasicMaterial ref={material} transparent opacity={visual.opacity} toneMapped={false} />
    </instancedMesh>
  );
}

function Core({
  visual,
  pulseKey,
  reducedMotion,
}: {
  visual: SceneVisual;
  pulseKey: string;
  reducedMotion: boolean;
}) {
  const body = useRef<Mesh>(null);
  const bodyMaterial = useRef<MeshStandardMaterial>(null);
  const shell = useRef<Group>(null);
  const shellMaterial = useRef<MeshBasicMaterial>(null);
  const light = useRef<PointLight>(null);
  const shock = useRef<Mesh>(null);
  const shockMaterial = useRef<MeshBasicMaterial>(null);
  const phase = useRef(0);
  const shockT = useRef(1);
  const lastPulse = useRef(pulseKey);
  const target = useMemo(() => new Color(), []);
  const invalidate = useThree((state) => state.invalidate);

  // One shockwave whenever an incident opens or escalates.
  useEffect(() => {
    if (pulseKey && pulseKey !== lastPulse.current && !reducedMotion) shockT.current = 0;
    lastPulse.current = pulseKey;
  }, [pulseKey, reducedMotion]);

  // Reduced motion: jump straight to the target look and draw one frame.
  useEffect(() => {
    if (!reducedMotion) return;
    const color = new Color(visual.coreColor);
    bodyMaterial.current?.color.copy(color);
    bodyMaterial.current?.emissive.copy(color);
    if (bodyMaterial.current) bodyMaterial.current.emissiveIntensity = visual.glow;
    shellMaterial.current?.color.copy(color);
    light.current?.color.copy(color);
    if (light.current) light.current.intensity = 2 + visual.glow * 10;
    invalidate();
  }, [reducedMotion, visual, invalidate]);

  useFrame((_, delta) => {
    if (reducedMotion) return;
    const dt = Math.min(delta, 0.1);
    target.set(visual.coreColor);
    const k = ease(dt, 3);
    const m = bodyMaterial.current;
    if (m) {
      m.color.lerp(target, k);
      m.emissive.lerp(target, k);
      m.emissiveIntensity += (visual.glow - m.emissiveIntensity) * k;
    }
    shellMaterial.current?.color.lerp(target, k);
    if (light.current) {
      light.current.color.lerp(target, k);
      light.current.intensity += (2 + visual.glow * 10 - light.current.intensity) * k;
    }
    phase.current += dt * visual.beat;
    const beat = Math.pow(Math.max(0, Math.sin(phase.current)), 6);
    body.current?.scale.setScalar(1 + visual.beatAmp * (0.3 + beat));
    if (shell.current) {
      shell.current.rotation.y += dt * visual.spin;
      shell.current.rotation.x += dt * visual.spin * 0.4;
    }
    if (shock.current && shockMaterial.current) {
      if (shockT.current < 1) {
        shockT.current = Math.min(1, shockT.current + dt / 1.6);
        const t = shockT.current;
        shock.current.visible = true;
        shock.current.scale.setScalar(0.7 + t * 3.2);
        shockMaterial.current.color.copy(target);
        shockMaterial.current.opacity = (1 - t) * 0.55;
      } else {
        shock.current.visible = false;
      }
    }
  });

  return (
    <group>
      <pointLight ref={light} position={[0, 0, 0]} intensity={4} distance={6} decay={1.6} />
      <mesh ref={body}>
        <icosahedronGeometry args={[0.55, 4]} />
        <meshStandardMaterial
          ref={bodyMaterial}
          color={visual.coreColor}
          emissive={visual.coreColor}
          emissiveIntensity={visual.glow}
          roughness={0.35}
          metalness={0.15}
        />
      </mesh>
      <group ref={shell}>
        <mesh>
          <icosahedronGeometry args={[0.82, 1]} />
          <meshBasicMaterial
            ref={shellMaterial}
            color={visual.coreColor}
            wireframe
            transparent
            opacity={0.22}
          />
        </mesh>
      </group>
      <mesh ref={shock} visible={false}>
        <ringGeometry args={[0.96, 1, 96]} />
        <meshBasicMaterial
          ref={shockMaterial}
          transparent
          opacity={0}
          blending={AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}

function Rings({
  model,
  visual,
  reducedMotion,
}: {
  model: SceneModel;
  visual: SceneVisual;
  reducedMotion: boolean;
}) {
  const rate = useRef<Group>(null);
  const hasRatio = model.rateRatio !== null;
  const ratio = clampRatio(model.rateRatio ?? 0);
  const above = (model.rateRatio ?? 0) > 1;
  const invalidate = useThree((state) => state.invalidate);

  useEffect(() => {
    if (reducedMotion && rate.current) {
      rate.current.scale.setScalar(BASELINE_RING * ratio);
      invalidate();
    }
  }, [reducedMotion, ratio, invalidate]);

  useFrame((_, delta) => {
    if (reducedMotion || !rate.current) return;
    const current = rate.current.scale.x;
    const next = current + (BASELINE_RING * ratio - current) * ease(Math.min(delta, 0.1), 2.5);
    rate.current.scale.setScalar(next);
  });

  return (
    <group>
      <group scale={BASELINE_RING}>
        <Line
          points={RING_POINTS}
          color={SCENE_COLOR.ring}
          lineWidth={1.2}
          dashed
          dashSize={0.035}
          gapSize={0.03}
          transparent
          opacity={(hasRatio ? 0.9 : 0.35) * Math.max(visual.opacity, 0.5)}
        />
      </group>
      <group ref={rate} scale={BASELINE_RING * ratio} visible={hasRatio}>
        <Line
          points={RING_POINTS}
          color={above ? visual.alertColor : SCENE_COLOR.rate}
          lineWidth={above ? 2.4 : 1.6}
          transparent
          opacity={0.9 * visual.opacity}
        />
      </group>
    </group>
  );
}

function ContextWatcher({ onLost }: { onLost?: () => void }) {
  const gl = useThree((state) => state.gl);
  useEffect(() => {
    if (!onLost) return;
    const canvas = gl.domElement;
    const handle = (event: Event) => {
      event.preventDefault();
      onLost();
    };
    canvas.addEventListener('webglcontextlost', handle);
    return () => canvas.removeEventListener('webglcontextlost', handle);
  }, [gl, onLost]);
  return null;
}

export default function DetectorCanvas({
  model,
  reducedMotion,
  active,
  onContextLost,
}: DetectorCanvasProps) {
  const [maxDpr, setMaxDpr] = useState(1.75);
  const visual = useMemo(() => sceneVisual(model, SCENE_PALETTE), [model]);
  const frameloop = !active ? 'never' : reducedMotion ? 'demand' : 'always';

  return (
    <Canvas
      className="scene__canvas"
      frameloop={frameloop}
      dpr={[1, maxDpr]}
      camera={{ position: [0, 0.3, 8.2], fov: 36 }}
      gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
      aria-hidden="true"
    >
      <PerformanceMonitor onDecline={() => setMaxDpr(1)} />
      <ContextWatcher onLost={onContextLost} />
      <fog attach="fog" args={[COLOR.surface, 6.5, 12]} />
      <ambientLight intensity={0.35} />
      <directionalLight position={[3, 4, 5]} intensity={0.9} />
      <Rings model={model} visual={visual} reducedMotion={reducedMotion} />
      <Core visual={visual} pulseKey={model.pulseKey} reducedMotion={reducedMotion} />
      <Particles model={model} visual={visual} reducedMotion={reducedMotion} />
    </Canvas>
  );
}
