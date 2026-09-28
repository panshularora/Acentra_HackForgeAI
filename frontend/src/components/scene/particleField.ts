import { Color, Object3D, type InstancedMesh } from 'three';

/** Upper bound on log-line particles alive at once (one draw call for all of them). */
export const MAX_PARTICLES = 640;
/** Visual cap on spawns per second, so a log flood stays legible. */
const MAX_SPAWN_PER_SECOND = 160;
const OUTER_RADIUS = 3.8;
const CORE_RADIUS = 0.55;
const BASE_SIZE = 1;

/**
 * Simulation for the log-line particles: each dot is one log line (up to the
 * spawn cap) travelling from the outer shell into the detector core. Error
 * lines are coloured and slightly larger. All state lives in typed arrays and
 * is written straight into one InstancedMesh; nothing allocates per frame.
 */
export class ParticleField {
  private readonly alive = new Uint8Array(MAX_PARTICLES);
  private readonly progress = new Float32Array(MAX_PARTICLES);
  private readonly speed = new Float32Array(MAX_PARTICLES);
  private readonly theta = new Float32Array(MAX_PARTICLES);
  private readonly phi = new Float32Array(MAX_PARTICLES);
  private readonly swirl = new Float32Array(MAX_PARTICLES);
  private readonly size = new Float32Array(MAX_PARTICLES);
  private readonly isError = new Uint8Array(MAX_PARTICLES);
  private readonly dummy = new Object3D();
  private readonly lineColor = new Color();
  private readonly errorColor = new Color();
  private pending = 0;
  private cursor = 0;

  constructor(lineColor: string, errorColor: string) {
    this.lineColor.set(lineColor);
    this.errorColor.set(errorColor);
  }

  /** Hides every instance and allocates the colour attribute before first render. */
  attach(mesh: InstancedMesh): void {
    this.dummy.scale.setScalar(0);
    this.dummy.updateMatrix();
    for (let i = 0; i < MAX_PARTICLES; i++) {
      mesh.setMatrixAt(i, this.dummy.matrix);
      mesh.setColorAt(i, this.lineColor);
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }

  setErrorColor(mesh: InstancedMesh, color: string): void {
    if (this.errorColor.getHexString() === new Color(color).getHexString()) return;
    this.errorColor.set(color);
    for (let i = 0; i < MAX_PARTICLES; i++) {
      if (this.isError[i]) mesh.setColorAt(i, this.errorColor);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }

  private spawn(mesh: InstancedMesh, errorShare: number, progress = 0): boolean {
    for (let n = 0; n < MAX_PARTICLES; n++) {
      const i = (this.cursor + n) % MAX_PARTICLES;
      if (this.alive[i]) continue;
      this.cursor = (i + 1) % MAX_PARTICLES;
      const error = Math.random() < errorShare;
      this.alive[i] = 1;
      this.isError[i] = error ? 1 : 0;
      this.progress[i] = progress;
      this.speed[i] = 1 / (2.6 + Math.random() * 1.2);
      this.theta[i] = Math.random() * Math.PI * 2;
      // Uniform over the sphere, flattened a little so the flow reads as a disc.
      this.phi[i] = Math.acos(2 * Math.random() - 1);
      this.swirl[i] = 0.9 + Math.random() * 0.8;
      this.size[i] = BASE_SIZE * (error ? 1.6 : 0.8 + Math.random() * 0.4);
      mesh.setColorAt(i, error ? this.errorColor : this.lineColor);
      return true;
    }
    return false;
  }

  /** Static snapshot for reduced motion: particles spread along their paths, not moving. */
  seed(mesh: InstancedMesh, linesPerSecond: number, errorShare: number): void {
    this.alive.fill(0);
    const count = Math.min(MAX_PARTICLES, Math.round(Math.min(linesPerSecond, 60) * 3));
    for (let k = 0; k < count; k++) this.spawn(mesh, errorShare, Math.random() * 0.95);
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    this.write(mesh);
  }

  /** Advances the flow by `dt` seconds. `flow` scales speed (0 = frozen). */
  step(
    mesh: InstancedMesh,
    dt: number,
    linesPerSecond: number,
    errorShare: number,
    flow: number,
  ): void {
    this.pending += Math.min(linesPerSecond, MAX_SPAWN_PER_SECOND) * dt;
    let spawned = false;
    while (this.pending >= 1) {
      this.pending -= 1;
      spawned = this.spawn(mesh, errorShare) || spawned;
    }
    if (spawned && mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    for (let i = 0; i < MAX_PARTICLES; i++) {
      if (!this.alive[i]) continue;
      const next = (this.progress[i] ?? 0) + dt * flow * (this.speed[i] ?? 0);
      if (next >= 1) this.alive[i] = 0;
      else this.progress[i] = next;
    }
    this.write(mesh);
  }

  private write(mesh: InstancedMesh): void {
    const d = this.dummy;
    for (let i = 0; i < MAX_PARTICLES; i++) {
      if (!this.alive[i]) {
        d.position.set(0, 0, 0);
        d.scale.setScalar(0);
      } else {
        const t = this.progress[i] ?? 0;
        // Ease in: lines drift in slowly, then are pulled into the core.
        const r = CORE_RADIUS + (OUTER_RADIUS - CORE_RADIUS) * Math.pow(1 - t, 1.35);
        const theta = (this.theta[i] ?? 0) + (this.swirl[i] ?? 1) * t * 1.8;
        const phi = this.phi[i] ?? 0;
        const sinPhi = Math.sin(phi);
        d.position.set(
          r * sinPhi * Math.cos(theta),
          r * Math.cos(phi) * 0.55,
          r * sinPhi * Math.sin(theta),
        );
        const fadeIn = Math.min(1, t * 8);
        d.scale.setScalar((this.size[i] ?? 1) * fadeIn * (0.45 + 0.55 * (1 - t)));
      }
      d.updateMatrix();
      mesh.setMatrixAt(i, d.matrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
  }
}
