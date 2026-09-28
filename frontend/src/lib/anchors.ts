/** DOM id of an incident card, so the headline can jump straight to it. */
export function incidentAnchor(id: string): string {
  return `incident-${id}`;
}
