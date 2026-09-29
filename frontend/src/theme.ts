import type { Severity } from './types';

/**
 * Visual system for the on-call console. Tokens land as CSS custom properties
 * (applyThemeVariables); styles.css never hard-codes a colour or font.
 *
 * Colour is reserved for severity, the live-connection dot, and a 2px incident
 * rail. Everything else is ink, paper, and a quiet teal for "healthy".
 */

export const APP_NAME = 'ClaimsWatch';

export const COLOR = {
  bg: '#0a1016',
  surface: '#101820',
  /** Raised surfaces inside a panel (cards, code blocks). */
  raised: '#161f29',
  border: '#1e2a36',
  /** Hover/focus outlines and dividers that need a touch more contrast. */
  borderStrong: '#2c3c4c',
  text: '#e6ebe4',
  textMuted: '#8a958c',
  /** Chart-only neutrals. The "normal" band is textMuted at 15% opacity. */
  band: 'rgba(138, 149, 140, 0.16)',
  bandEdge: 'rgba(138, 149, 140, 0.42)',
  grid: '#18222c',
  line: '#e6ebe4',
  /** Used only for the live-connection dot. */
  ok: '#3c9d74',
} as const;

/**
 * The 3D detector view. Neutral like the rest of the page: the core is silver
 * when calm and only takes a severity colour while an incident is open.
 */
export const SCENE_COLOR = {
  core: '#c5d0c8',
  coreDim: '#3d4a52',
  line: '#c5d0c8',
  error: '#d46568',
  ring: '#5c6b72',
  rate: '#e6ebe4',
} as const;

export const SEVERITY_COLOR: Record<Severity, string> = {
  WARNING: '#d4a017',
  HIGH: '#d65a31',
  CRITICAL: '#d13b3b',
};

export const FONT = {
  ui: "'Public Sans Variable', 'Public Sans', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
  mono: "'JetBrains Mono Variable', 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
} as const;

/** 4px spacing scale. Index n is n * 4px, except where noted. */
export const SPACE = {
  1: '4px',
  2: '8px',
  3: '12px',
  4: '16px',
  5: '20px',
  6: '24px',
  8: '32px',
  12: '48px',
} as const;

/** One radius everywhere keeps panels, chips and buttons visually related. */
export const RADIUS = '4px';

export const FONT_SIZE = {
  xs: '11px',
  sm: '12px',
  md: '13px',
  lg: '15px',
  xl: '22px',
  xxl: '32px',
} as const;

export const MOTION = {
  ease: 'cubic-bezier(0.16, 1, 0.3, 1)',
  duration: '180ms',
  enter: '220ms',
} as const;

/** Flattens the tokens above into `--token-name` CSS custom properties. */
export function themeVariables(): Record<string, string> {
  const vars: Record<string, string> = {};
  const kebab = (s: string) => s.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

  for (const [key, value] of Object.entries(COLOR)) vars[`--color-${kebab(key)}`] = value;
  for (const [key, value] of Object.entries(SCENE_COLOR)) vars[`--scene-${kebab(key)}`] = value;
  for (const [key, value] of Object.entries(SEVERITY_COLOR)) {
    vars[`--severity-${key.toLowerCase()}`] = value;
  }
  for (const [key, value] of Object.entries(FONT)) vars[`--font-${key}`] = value;
  for (const [key, value] of Object.entries(SPACE)) vars[`--space-${key}`] = value;
  vars['--radius'] = RADIUS;
  for (const [key, value] of Object.entries(FONT_SIZE)) vars[`--text-${key}`] = value;
  vars['--ease'] = MOTION.ease;
  vars['--duration'] = MOTION.duration;
  vars['--duration-enter'] = MOTION.enter;
  return vars;
}

export function applyThemeVariables(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(themeVariables())) {
    root.style.setProperty(name, value);
  }
}
