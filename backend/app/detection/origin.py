"""Suspected origin for cascading incidents.

A static depends-on map of the claims platform. When several services have
open incidents, each card names the most upstream alerting service as the
suspected origin. Incident keys stay per-template, so a lone DB timeout is
unchanged.
"""

# Downstream service -> services it needs. Walk this to find an upstream cause.
DEPENDS_ON: dict[str, tuple[str, ...]] = {
    "claim-intake": ("eligibility-check",),
    "claim-adjudication": ("claim-intake", "eligibility-check", "provider-directory"),
    "payment-gateway": ("claim-adjudication",),
    "payment-reconciler": ("payment-gateway",),
    "eligibility-sync": ("eligibility-check",),
}


def suspected_origin(service: str | None, alerting: set[str]) -> str | None:
    """Most upstream alerting service for ``service``, or ``service`` itself."""
    if service is None:
        return None
    best = service
    seen: set[str] = set()
    stack = list(DEPENDS_ON.get(service, ()))
    while stack:
        upstream = stack.pop()
        if upstream in seen:
            continue
        seen.add(upstream)
        if upstream in alerting:
            best = upstream
        stack.extend(DEPENDS_ON.get(upstream, ()))
    return best
