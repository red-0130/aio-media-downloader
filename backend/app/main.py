"""FastAPI application entrypoint, lifespan management, CORS, routing, and SPA fallback."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import download, inspect, progress, settings as settings_router
from app.services import cleaner, ffmpeg_service
from app.services.progress_manager import wait_for_all_workers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager handling startup directory verification and background cleaner."""
    settings.ensure_directories()

    # Eagerly initialize and warm up pyffmpeg binary and configure PATH
    ffmpeg_service.get_ffmpeg_bin()

    # Start periodic storage cleaner (runs every 10 minutes)
    cleaner_task = asyncio.create_task(cleaner.run_periodic_cleaner(interval_seconds=600))

    try:
        yield
    finally:
        # Shutdown: cleanly cancel background storage cleaner
        cleaner_task.cancel()
        try:
            await cleaner_task
        except asyncio.CancelledError:
            pass

        # Await or cancel remaining active download workers
        await wait_for_all_workers(timeout=2.0)


app = FastAPI(
    title="All-in-One Media Downloader",
    description="High-performance media extractor and downloader API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(inspect.router, prefix="/api", tags=["inspect"])
app.include_router(download.router, prefix="/api", tags=["download"])
app.include_router(progress.router, prefix="/api", tags=["progress"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])

# Static Files & SPA Fallback
STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"

if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/")
async def serve_root():
    """Serve SPA index.html or welcome payload."""
    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"status": "ok", "app": "All-in-One Media Downloader"}


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Catch-all SPA fallback: return static file if exists, else index.html for non-API routes."""
    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API route not found")

    if STATIC_DIR.is_dir():
        target = (STATIC_DIR / full_path).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
            if target.is_file():
                return FileResponse(target)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")

        index_file = STATIC_DIR / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
