"""API route handler for download task execution and file retrieval."""

import asyncio
from collections.abc import AsyncIterator
import mimetypes
import os
from pathlib import Path
from typing import Annotated
import urllib.parse

import anyio
from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models.download import DownloadRequest, DownloadResponse, DownloadResult
from app.services import cookie_manager, progress_manager, proxy_manager, router as media_router, security

router = APIRouter()
_active_workers: set[asyncio.Task] = set()

_download_semaphores: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def get_download_semaphore() -> asyncio.Semaphore:
    """Return semaphore for current event loop to bound concurrent downloads."""
    global _download_semaphores
    loop = asyncio.get_running_loop()
    sem = _download_semaphores.get(loop)
    if sem is None:
        _download_semaphores = {lp: s for lp, s in _download_semaphores.items() if not lp.is_closed()}
        sem = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)
        _download_semaphores[loop] = sem
    return sem

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
            async with get_download_semaphore():
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


CHUNK_SIZE = 64 * 1024


def _parse_ascii_uint(raw: str) -> int:
    """Parse an ASCII-only unsigned integer (RFC 9110 1*DIGIT), rejecting signs and underscores."""
    if not raw or not raw.isascii() or not raw.isdigit():
        raise ValueError("Invalid unsigned integer")
    return int(raw)


def _parse_byte_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single HTTP Range header; return inclusive (start, end) or None to serve full file."""
    value = range_header.strip()
    if not value.lower().startswith("bytes="):
        return None
    spec = value[6:].strip()
    if "," in spec:
        return None

    unsatisfiable = HTTPException(
        status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
        detail="Requested Range Not Satisfiable",
        headers={"Content-Range": f"bytes */{file_size}"},
    )
    if file_size <= 0 or "-" not in spec:
        raise unsatisfiable

    start_str, end_str = spec.split("-", 1)
    start_str, end_str = start_str.strip(), end_str.strip()

    try:
        if not start_str and end_str:
            suffix = _parse_ascii_uint(end_str)
            if suffix <= 0:
                raise unsatisfiable
            start = max(0, file_size - suffix)
            end = file_size - 1
        elif start_str:
            start = _parse_ascii_uint(start_str)
            end = _parse_ascii_uint(end_str) if end_str else file_size - 1
        else:
            raise unsatisfiable
    except ValueError as err:
        raise unsatisfiable from err

    if start >= file_size or end < start:
        raise unsatisfiable

    return start, min(end, file_size - 1)


async def _stream_file_range(
    file_obj: anyio.AsyncFile[bytes], start: int, end: int, chunk_size: int = CHUNK_SIZE
) -> AsyncIterator[bytes]:
    """Asynchronously stream inclusive byte range [start, end] from an already-open file."""
    try:
        remaining = end - start + 1
        if remaining <= 0:
            return
        if start > 0:
            await file_obj.seek(start)
        while remaining > 0:
            chunk = await file_obj.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        await file_obj.aclose()


@router.get("/files/{task_id}/{filename:path}")
async def get_downloaded_file(
    task_id: str,
    filename: str,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
):
    """Stream completed media download or packaged ZIP archive with byte-range support."""
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
    raw_ascii = escaped_ascii.encode("ascii", "replace").decode("ascii").replace("?", "_")
    ascii_filename = "".join("_" if ord(c) < 0x20 or ord(c) == 0x7F else c for c in raw_ascii)
    content_disposition = (
        f'attachment; filename="{ascii_filename}"; filename*=utf-8\'\'{encoded_filename}'
    )

    file_obj = await anyio.open_file(safe_file, "rb")
    try:
        file_size = os.fstat(file_obj.fileno()).st_size
        byte_range = _parse_byte_range(range_header, file_size) if range_header else None
    except BaseException:
        await file_obj.aclose()
        raise

    headers = {
        "content-disposition": content_disposition,
        "accept-ranges": "bytes",
    }
    if byte_range is not None:
        start, end = byte_range
        status_code = status.HTTP_206_PARTIAL_CONTENT
        headers["content-range"] = f"bytes {start}-{end}/{file_size}"
        headers["content-length"] = str(end - start + 1)
    else:
        start, end = 0, file_size - 1
        status_code = status.HTTP_200_OK
        headers["content-length"] = str(file_size)

    return StreamingResponse(
        _stream_file_range(file_obj, start, end),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )
