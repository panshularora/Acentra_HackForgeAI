import { SCENE_COLOR, SEVERITY_COLOR } from '../../theme';

export const SCENE_PALETTE = {
  core: SCENE_COLOR.core,
  coreDim: SCENE_COLOR.coreDim,
  error: SCENE_COLOR.error,
  severity: SEVERITY_COLOR,
};

/** Radius of the dashed "edge of normal" ring; the rate ring is this times rateRatio. */
export const BASELINE_RING = 1.45;
/** Rate ring never shrinks below / grows beyond these multiples, so it stays readable. */
export const RATIO_MIN = 0.2;
export const RATIO_MAX = 1.65;

export function clampRatio(ratio: number): number {
  return Math.min(RATIO_MAX, Math.max(RATIO_MIN, ratio));
}
