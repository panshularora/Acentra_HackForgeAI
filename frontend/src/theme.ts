import type { Severity } from './types';

/**
 * Single source of truth for the visual system. Values here are pushed into
 * CSS custom properties at startup (see applyThemeVariables), so styles.css
 * never hard-codes a colour, font or spacing value.
 *
 * Colour is reserved for severity. Everything else is a neutral charcoal
 * scale, with one exception: the small "connected" dot in the status bar.
 */

export const APP_NAME = 'ClaimsWatch';

export const COLOR = {
  bg: '#111418',
  surface: '#171b21',
  border: '#262b33',
  /** Hover/focus outlines and dividers that need a touch more contrast. */
  borderStrong: '#343a44',
  text: '#e6e8eb',
  textMuted: '#8a929c',
  /** Chart-only neutrals. The "normal" band is textMuted at 15% opacity. */
  band: 'rgba(138, 146, 156, 0.15)',
  bandEdge: 'rgba(138, 146, 156, 0.45)',
  grid: '#1f242b',
  line: '#e6e8eb',
  /** Used only for the live-connection dot. */
  ok: '#2fb344',
} as const;

export const SEVERITY_COLOR: Record<Severity, string> = {
  WARNING: '#e0a100',
  HIGH: '#e8590c',
  CRITICAL: '#e03131',
};

export const FONT = {
  ui: "'Inter Variable', Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
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
  xl: '20px',
  xxl: '28px',
} as const;

/** Flattens the tokens above into `--token-name` CSS custom properties. */
export function themeVariables(): Record<string, string> {
  const vars: Record<string, string> = {};
  const kebab = (s: string) => s.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

  for (const [key, value] of Object.entries(COLOR)) vars[`--color-${kebab(key)}`] = value;
  for (const [key, value] of Object.entries(SEVERITY_COLOR)) {
    vars[`--severity-${key.toLowerCase()}`] = value;
  }
  for (const [key, value] of Object.entries(FONT)) vars[`--font-${key}`] = value;
  for (const [key, value] of Object.entries(SPACE)) vars[`--space-${key}`] = value;
  vars['--radius'] = RADIUS;
  for (const [key, value] of Object.entries(FONT_SIZE)) vars[`--text-${key}`] = value;
  return vars;
}

export function applyThemeVariables(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(themeVariables())) {
    root.style.setProperty(name, value);
  }
}
