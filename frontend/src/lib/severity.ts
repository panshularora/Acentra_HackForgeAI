import type { Severity } from '../types';

/** Most to least severe; used for sorting and for filter controls. */
export const SEVERITIES: readonly Severity[] = ['CRITICAL', 'HIGH', 'WARNING'];

/**
 * Modified z-score cut-offs. WARNING at 3.5 is the outlier threshold
 * recommended by Iglewicz & Hoaglin (1993); HIGH and CRITICAL are our own
 * product choices. Must match the backend (see CONTRACT.md).
 */
export const SEVERITY_THRESHOLD: Record<Severity, number> = {
  WARNING: 3.5,
  HIGH: 5,
  CRITICAL: 8,
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  WARNING: 'Warning',
  HIGH: 'High',
  CRITICAL: 'Critical',
};
