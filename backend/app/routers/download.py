"""API route handler for download task execution and file retrieval."""

import asyncio
import mimetypes
import urllib.parse
from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.config import settings
from app.models.download import DownloadRequest, DownloadResponse, DownloadResult
from app.services import cookie_manager, progress_manager, proxy_manager, router as media_router, security

router = APIRouter()
_active_workers: set[asyncio.Task] = set()

CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".zip": "application/zip",
}


async def wait_for_all_workers(timeout: float = 2.0) -> None:
    """Await all background download tasks or cancel on timeout."""
    if not _active_workers:
        return
    tasks = list(_active_workers)
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    except (Exception, asyncio.CancelledError):
        for t in tasks:
            if not t.done():
                t.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout,
                )
            except Exception:
                pass


@router.post("/download", response_model=DownloadResponse)
async def start_download(request: DownloadRequest):
    """Initiate an asynchronous media download job."""
    url = request.url
    if not url or not isinstance(url, str) or not url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL cannot be empty",
        )

    clean_url = url.strip()
    if not await security.is_safe_url_async(clean_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or disallowed URL (SSRF protection): {url}",
        )

    # Validate client proxy if provided, else fall back to server configuration
    effective_proxy = (
        request.proxy.strip()
        if (request.proxy and request.proxy.strip())
        else proxy_manager.get_proxy()
    )
    if effective_proxy:
        try:
            proxy_manager.validate_proxy_url(effective_proxy)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # Pre-validate client session cookies format if provided
    if request.cookies:
        if isinstance(request.cookies, str):
            if request.cookies.strip():
                is_valid, _, err = cookie_manager.verify_netscape_content(request.cookies)
                if not is_valid:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid client cookie format: {err}",
                    )
        elif isinstance(request.cookies, dict):
            for plat, val in request.cookies.items():
                if val and isinstance(val, str) and val.strip():
                    is_valid, _, err = cookie_manager.verify_netscape_content(val)
                    if not is_valid:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Invalid client cookie format for platform '{plat}': {err}",
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

            result: DownloadResult = await media_router.download(
                task_id=task_id,
                request=request,
                progress_callback=on_progress,
                proxy=effective_proxy,
                cookies=request.cookies,
            )

            files_payload = (
                [f.model_dump() for f in result.files] if result.files else None
            )
            await progress_manager.set_completed(
                task_id=task_id,
                filename=result.filename,
                download_url=result.download_url,
                file_size=result.file_size,
                files=files_payload,
            )
        except asyncio.CancelledError:
            try:
                await asyncio.shield(
                    progress_manager.set_error(task_id=task_id, error_message="Task was cancelled")
                )
            except (asyncio.CancelledError, Exception):
                pass
            raise
        except Exception as exc:
            await progress_manager.set_error(task_id=task_id, error_message=str(exc))

    worker_task = asyncio.create_task(run_worker())
    _active_workers.add(worker_task)
    worker_task.add_done_callback(_active_workers.discard)

    return DownloadResponse(task_id=task_id, status="queued")


@router.get("/files/{task_id}/{filename:path}")
async def get_downloaded_file(task_id: str, filename: str):
    """Serve completed media download or packaged ZIP archive."""
    if not security.is_valid_task_id(task_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid task ID: '{task_id}'",
        )

    clean_filename = filename.strip() if filename else ""
    if (
        not clean_filename
        or clean_filename in (".", "..")
        or ".." in clean_filename
        or clean_filename.startswith("/")
        or "\\" in clean_filename
        or "\0" in clean_filename
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or unsafe filename: '{filename}'",
        )

    try:
        task_dir = security.validate_safe_path(settings.DOWNLOADS_DIR, task_id)
        if task_dir == settings.DOWNLOADS_DIR.resolve():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task ID cannot point to downloads root directory: '{task_id}'",
            )
        safe_file = security.validate_safe_path(task_dir, clean_filename)
        if safe_file == task_dir.resolve():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename cannot point to directory root",
            )
        if not safe_file.exists() and "%" in clean_filename:
            try:
                unquoted_name = urllib.parse.unquote(clean_filename)
                candidate = security.validate_safe_path(task_dir, unquoted_name)
                if candidate.exists() and candidate.is_file():
                    safe_file = candidate
            except Exception:
                pass
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )

    if not safe_file.exists() or not safe_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{filename}' not found",
        )

    ext = safe_file.suffix.lower()
    media_type = CONTENT_TYPES.get(ext)
    if not media_type:
        guessed, _ = mimetypes.guess_type(str(safe_file))
        media_type = guessed or "application/octet-stream"

    # Format Content-Disposition according to RFC 6266 and RFC 5987:
    # Include both standard filename="..." and filename*=utf-8''...
    # This preserves the '#' in the filename while ensuring browsers correctly save the file.
    encoded_filename = urllib.parse.quote(safe_file.name)
    escaped_ascii = safe_file.name.replace("\\", "\\\\").replace('"', '\\"')
    ascii_filename = escaped_ascii.encode("ascii", "replace").decode("ascii").replace("?", "_")
    content_disposition = (
        f'attachment; filename="{ascii_filename}"; filename*=utf-8\'\'{encoded_filename}'
    )

    return FileResponse(
        path=safe_file,
        media_type=media_type,
        filename=safe_file.name,
        headers={"content-disposition": content_disposition},
    )
