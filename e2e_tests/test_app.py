"""Test FastAPI ASGI application mounting production API routers."""

from fastapi import FastAPI

from app.routers import download, inspect, progress, settings as settings_router
from app.services.progress_manager import wait_for_all_workers

__all__ = ["create_test_app", "wait_for_all_workers"]


def create_test_app() -> FastAPI:
    """Create and configure FastAPI test application with production routers."""
    app = FastAPI(title="All-in-One Media Downloader Test App")

    @app.get("/")
    async def root():
        return {"status": "ok", "app": "All-in-One Media Downloader"}

    app.include_router(inspect.router, prefix="/api", tags=["inspect"])
    app.include_router(download.router, prefix="/api", tags=["download"])
    app.include_router(progress.router, prefix="/api", tags=["progress"])
    app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])

    return app
