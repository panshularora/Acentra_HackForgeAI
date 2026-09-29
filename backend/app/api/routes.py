"""REST and WebSocket endpoints. Shapes follow docs/contract.md."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.demo.injector import FAULTS
from app.detection.detector import DETECTORS
from app.services import Services

router = APIRouter()


def get_services(request: Request) -> Services:
    """Dependency returning the application's shared components."""
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("/health", include_in_schema=False)
def liveness(services: ServicesDep, response: Response) -> dict[str, str]:
    """Liveness probe for load balancers and container health checks.

    Returns 503 when the pipeline has stopped or cannot read the log, so a
    dead monitor fails its health check instead of looking fine.
    """
    if services.pipeline.healthy:
        return {"status": "ok"}
    response.status_code = 503
    return {"status": "degraded"}


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
        "status": "ok" if services.pipeline.healthy else "degraded",
        "ingest_error": services.pipeline.ingest_error,
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
            "detectors": list(DETECTORS),
        },
        "learning": services.detector.learning.to_dict(),
        "pipeline": {
            "parsed_lines": services.parser.parsed,
            "malformed_lines": services.parser.malformed,
            "baseline_warm": services.detector.baseline_warm,
            "websocket_clients": services.clients.client_count,
        },
        "faults": [fault.to_dict() for fault in services.injector.active()],
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


@router.post("/api/delivery/retry")
async def retry_delivery(services: ServicesDep) -> dict[str, Any]:
    """Re-queue alerts whose SNS publish failed or is still pending."""
    queued = await services.pipeline.retry_undelivered_sns()
    return {"queued": queued}


@router.get("/api/faults")
def list_faults(services: ServicesDep) -> dict[str, Any]:
    """Currently active demo faults."""
    return {"faults": [fault.to_dict() for fault in services.injector.active()]}


@router.post("/api/faults")
async def inject_fault(payload: dict[str, Any], services: ServicesDep) -> dict[str, Any]:
    """Inject a demo fault into the live log / generator control file."""
    name = str(payload.get("name", ""))
    if name not in FAULTS:
        raise HTTPException(status_code=400, detail=f"unknown fault: {name}")
    duration = payload.get("duration")
    try:
        seconds = None if duration is None else float(duration)
        fault = await services.injector.inject(name, seconds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return fault.to_dict()


@router.delete("/api/faults")
def stop_all_faults(services: ServicesDep) -> dict[str, Any]:
    """Stop every active demo fault."""
    stopped = services.injector.stop_all()
    return {
        "stopped": stopped,
        "faults": [fault.to_dict() for fault in services.injector.active()],
    }


@router.delete("/api/faults/{name}")
def stop_fault(name: str, services: ServicesDep) -> dict[str, Any]:
    """Stop one demo fault. Idempotent for a known name that is already idle."""
    if name not in FAULTS:
        raise HTTPException(status_code=400, detail=f"unknown fault: {name}")
    try:
        services.injector.stop(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "stopped": name,
        "faults": [fault.to_dict() for fault in services.injector.active()],
    }


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
