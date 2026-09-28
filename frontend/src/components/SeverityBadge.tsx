import type { Severity } from '../types';

/** Severity as text plus colour, so it never relies on colour alone. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`severity-badge severity-badge--${severity.toLowerCase()}`}>{severity}</span>
  );
}
