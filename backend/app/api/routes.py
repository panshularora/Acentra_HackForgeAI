"""REST and WebSocket endpoints. Shapes follow CONTRACT.md."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.services import Services

router = APIRouter()


def get_services(request: Request) -> Services:
    """Dependency returning the application's shared components."""
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("/health", include_in_schema=False)
def liveness() -> dict[str, str]:
    """Minimal liveness probe for load balancers and container health checks."""
    return {"status": "ok"}


@router.get("/api/health")
def health(services: ServicesDep) -> dict[str, Any]:
    """Liveness plus enough detail to tell whether ingestion and AWS are wired up.

    ``detector`` carries the timing the dashboard needs to label its chart and
    warm-up progress, so the frontend never keeps its own copy of these values.
    """
    settings = services.settings
    detector = services.detector.config
    publisher = services.publisher
    return {
        "status": "ok",
        "app": settings.app_name,
        "log_path": str(settings.log_path),
        "tailer_offset": services.tailer.offset,
        "aws": {
            "sns_topic_arn": publisher.topic_arn if publisher else None,
            "cloudwatch_log_group": publisher.log_group if publisher else None,
            "endpoint": settings.aws_endpoint_url if publisher else None,
        },
        "detector": {
            "window_seconds": detector.window_seconds,
            "bucket_seconds": detector.bucket_seconds,
            "baseline_min_buckets": detector.baseline_min_buckets,
        },
        "pipeline": {
            "parsed_lines": services.parser.parsed,
            "malformed_lines": services.parser.malformed,
            "baseline_warm": services.detector.baseline_warm,
            "websocket_clients": services.clients.client_count,
        },
    }


@router.get("/api/stats")
def stats(
    services: ServicesDep, minutes: Annotated[int, Query(ge=1, le=24 * 60)] = 10
) -> dict[str, Any]:
    """Stats points for the last ``minutes`` minutes, oldest first."""
    return {"points": [p.to_dict() for p in services.stats.since(minutes)]}


@router.get("/api/alerts")
def alerts(
    services: ServicesDep, limit: Annotated[int, Query(ge=1, le=500)] = 50
) -> dict[str, Any]:
    """Most recent alerts, newest first."""
    return {"alerts": [a.to_dict() for a in services.store.list_recent(limit)]}


@router.post("/api/alerts/{alert_id}/ack")
async def acknowledge(alert_id: str, services: ServicesDep) -> dict[str, Any]:
    """Acknowledge an alert so the team knows someone is on it."""
    alert = await services.pipeline.acknowledge(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    return alert.to_dict()


@router.websocket("/ws")
async def websocket_feed(websocket: WebSocket) -> None:
    """Live feed of stats and alert messages. Clients do not need to send anything."""
    services: Services = websocket.app.state.services
    await services.clients.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        services.clients.disconnect(websocket)
