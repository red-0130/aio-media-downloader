"""Test FastAPI ASGI application wiring backend services to REST and SSE endpoints."""

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.models.cookies import CookieStatus, CookieUpdateRequest
from app.models.download import DownloadRequest, DownloadResponse, DownloadResult
from app.models.inspect import InspectRequest, InspectResponse
from app.models.proxy import ProxyConfig, ProxyUpdateRequest
from app.services import (
    cleaner,
    cookie_manager,
    progress_manager,
    proxy_manager,
    router,
    security,
)
from app.services.ytdlp_service import (
    AuthRequiredError,
    ExtractionError,
    RateLimitError,
)


_active_workers: set[asyncio.Task] = set()


async def wait_for_all_workers(timeout: float = 2.0) -> None:
    """Await all background download tasks or cancel on timeout."""
    if not _active_workers:
        return
    tasks = list(_active_workers)
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    except Exception:
        for t in tasks:
            if not t.done():
                t.cancel()


def create_test_app() -> FastAPI:
    """Create and configure FastAPI test application wired to backend services."""
    app = FastAPI(title="All-in-One Media Downloader Test App")

    @app.get("/")
    async def root():
        return {"status": "ok", "app": "All-in-One Media Downloader"}

    # ========================================================================
    # 1. Media Inspection API
    # ========================================================================
    @app.post("/api/inspect", response_model=InspectResponse)
    async def inspect_media(request: InspectRequest):
        url = request.url
        if not url or not isinstance(url, str):
            raise HTTPException(status_code=400, detail="URL cannot be empty")

        clean_url = url.strip()
        if not security.is_safe_url(clean_url):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid or disallowed URL (SSRF protection): {url}",
            )

        try:
            return await router.inspect(clean_url)
        except AuthRequiredError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except RateLimitError as e:
            raise HTTPException(status_code=429, detail=str(e))
        except (ExtractionError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Inspection failed: {e}")

    # ========================================================================
    # 2. Download Execution API
    # ========================================================================
    @app.post("/api/download", response_model=DownloadResponse)
    async def start_download(request: DownloadRequest):
        url = request.url
        if not url or not isinstance(url, str):
            raise HTTPException(status_code=400, detail="URL cannot be empty")

        clean_url = url.strip()
        if not security.is_safe_url(clean_url):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid or disallowed URL (SSRF protection): {url}",
            )

        task = await progress_manager.create_task()
        task_id = task.task_id

        async def run_worker():
            try:
                async def on_progress(
                    progress: float,
                    speed: str | None = None,
                    eta: int | None = None,
                    message: str | None = None,
                    **kwargs,
                ):
                    await progress_manager.update_progress(
                        task_id=task_id,
                        progress=progress,
                        speed=speed,
                        eta=eta,
                        message=message,
                    )

                result: DownloadResult = await router.download(
                    task_id=task_id,
                    request=request,
                    progress_callback=on_progress,
                )

                await progress_manager.set_completed(
                    task_id=task_id,
                    filename=result.filename,
                    download_url=result.download_url,
                    file_size=result.file_size,
                )
            except Exception as exc:
                await progress_manager.set_error(task_id=task_id, error_message=str(exc))

        # Launch background task execution and track it
        worker_task = asyncio.create_task(run_worker())
        _active_workers.add(worker_task)
        worker_task.add_done_callback(_active_workers.discard)

        return DownloadResponse(task_id=task_id, status="queued")

    # ========================================================================
    # 3. SSE Progress Stream API
    # ========================================================================
    @app.get("/api/progress/{task_id}")
    async def get_progress_stream(task_id: str):
        task = progress_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        return EventSourceResponse(progress_manager.subscribe_sse(task_id))

    # ========================================================================
    # 4. File Retrieval API
    # ========================================================================
    @app.get("/api/files/{task_id}/{filename}")
    async def get_downloaded_file(task_id: str, filename: str):
        if ".." in task_id or ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Path traversal detected")

        task_dir = settings.DOWNLOADS_DIR / task_id
        try:
            safe_file = security.validate_safe_path(task_dir, filename)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

        if not safe_file.exists() or not safe_file.is_file():
            raise HTTPException(status_code=404, detail=f"File {filename} not found")

        ext = safe_file.suffix.lower()
        content_types = {
            ".mp4": "video/mp4",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".zip": "application/zip",
        }
        media_type = content_types.get(ext, "application/octet-stream")

        return FileResponse(
            path=safe_file,
            media_type=media_type,
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ========================================================================
    # 5. Cookie Management Settings API
    # ========================================================================
    @app.get("/api/settings/cookies", response_model=dict[str, CookieStatus])
    async def get_cookies_status():
        return cookie_manager.get_all_cookie_statuses()

    @app.post("/api/settings/cookies")
    async def save_cookie_text(body: CookieUpdateRequest):
        try:
            status = cookie_manager.save_cookies(body.platform, body.content)
            return {"status": "saved", "platform": body.platform, "cookie_status": status}
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/api/settings/cookies/upload")
    async def upload_cookie_file(
        platform: str = Form(...), file: UploadFile = File(...)
    ):
        try:
            raw_bytes = await file.read()
            content = raw_bytes.decode("utf-8", errors="replace")
            status = cookie_manager.save_cookies(platform, content)
            return {"status": "saved", "platform": platform, "cookie_status": status}
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.delete("/api/settings/cookies/{platform}")
    async def delete_platform_cookies(platform: str):
        deleted = cookie_manager.delete_cookies(platform)
        return {"status": "deleted" if deleted else "not_found", "platform": platform}

    # ========================================================================
    # 6. Proxy Configuration Settings API
    # ========================================================================
    @app.get("/api/settings/proxy", response_model=ProxyConfig)
    async def get_proxy_settings():
        return proxy_manager.get_proxy_config()

    @app.post("/api/settings/proxy", response_model=ProxyConfig)
    async def update_proxy_settings(body: ProxyUpdateRequest):
        try:
            proxy_manager.set_proxy(body.proxy)
            return proxy_manager.get_proxy_config()
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

    return app
