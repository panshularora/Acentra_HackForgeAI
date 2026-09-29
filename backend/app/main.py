"""FastAPI application factory and process lifecycle.

On startup the lifespan handler builds the shared components, prepares AWS
resources and starts the pipeline as a background task; on shutdown it cancels
the tasks and closes the database and log file. ``uvicorn app.main:app``
serves the module-level app.
"""

import asyncio
import contextlib
import logging
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router
from app.config import Settings, _REPO_ROOT, get_settings
from app.services import build_services

logger = logging.getLogger("app")


async def _start_loggen(settings: Settings) -> asyncio.subprocess.Process:
    """Write demo claims traffic into the file the tailer already follows."""
    log_path = Path(settings.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    script = _REPO_ROOT / "tools" / "loggen.py"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "--rate",
        "40",
        "--out",
        str(log_path),
        cwd=str(_REPO_ROOT),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    logger.info("demo loggen pid %s writing %s", process.pid, log_path)
    return process


def _mount_dashboard(app: FastAPI) -> None:
    """Serve the built dashboard from this origin so /api and /ws stay same-host."""
    dist = _REPO_ROOT / "frontend" / "dist"
    index = dist / "index.html"
    if not index.is_file():
        logger.warning("SERVE_DASHBOARD is set but %s is missing", index)
        return

    @app.get("/")
    async def dashboard_index() -> FileResponse:
        return FileResponse(index)

    favicon = dist / "favicon.svg"
    if favicon.is_file():

        @app.get("/favicon.svg")
        async def dashboard_favicon() -> FileResponse:
            return FileResponse(favicon)

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application for the given settings."""
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loggen: asyncio.subprocess.Process | None = None
        if settings.demo_loggen:
            loggen = await _start_loggen(settings)
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
            if loggen is not None and loggen.returncode is None:
                loggen.terminate()
                with contextlib.suppress(ProcessLookupError, TimeoutError):
                    await asyncio.wait_for(loggen.wait(), timeout=5)

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )
    app.include_router(router)
    if settings.serve_dashboard:
        _mount_dashboard(app)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
