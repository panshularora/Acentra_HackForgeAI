/**
 * Whether this browser can create a WebGL context. Checked once, before the
 * 3D bundle is even requested, so browsers without WebGL (and jsdom) get the
 * static picture instead of a blank box.
 */
let cached: boolean | undefined;

export function hasWebGL(): boolean {
  if (cached !== undefined) return cached;
  cached = false;
  try {
    if (typeof window === 'undefined' || typeof window.WebGLRenderingContext === 'undefined') {
      return cached;
    }
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
    cached = context !== null;
    (context as WebGLRenderingContext | null)?.getExtension('WEBGL_lose_context')?.loseContext();
  } catch {
    cached = false;
  }
  return cached;
}
