"""FastAPI application factory and process lifecycle.

On startup the lifespan handler builds the shared components, prepares AWS
resources and starts the pipeline as a background task; on shutdown it cancels
the tasks and closes the database and log file. ``uvicorn app.main:app``
serves the module-level app.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.config import Settings, get_settings
from app.services import build_services

logger = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application for the given settings."""
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = build_services(settings)
        app.state.services = services
        if services.publisher is not None:
            await services.publisher.start()
            await services.pipeline.retry_undelivered_sns()
        task = asyncio.create_task(services.pipeline.run(), name="pipeline")
        logger.info("%s watching %s", settings.app_name, settings.log_path)
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            if services.publisher is not None:
                await services.publisher.stop()
            services.close()

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
