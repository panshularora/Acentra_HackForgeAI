"""FastAPI application factory."""

from fastapi import FastAPI

from app import __version__
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application for the given settings."""
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, version=__version__)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "app": settings.app_name, "log_path": str(settings.log_path)}

    return app


app = create_app()
