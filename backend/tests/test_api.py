"""Comprehensive integration test suite for Milestone 2 API endpoints and SSE streaming."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import httpx
import os
import time
import pytest

from app.config import settings
from app.main import app, lifespan
from app.models.download import DownloadFileInfo, DownloadResult
from app.models.inspect import FormatOption, InspectResponse, MediaItem
from app.services import cookie_manager, progress_manager, proxy_manager
from app.services.cleaner import cleanup_old_downloads
from app.services.ytdlp_service import (
    AuthRequiredError,
    ExtractionError,
    RateLimitError,
)


@pytest.fixture
async def async_client():
    """Create an httpx AsyncClient connected to genuine app.main:app via ASGITransport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def parse_sse_events(
    client: httpx.AsyncClient, task_id: str, max_events: int = 5
) -> list[dict]:
    """Helper to collect and parse SSE event packets from /api/progress/{task_id}."""
    events = []
    current_event = "message"
    async with client.stream("GET", f"/api/progress/{task_id}") as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("event:"):
                current_event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_str = line[len("data:") :].strip()
                try:
                    payload = json.loads(data_str)
                except Exception:
                    payload = data_str
                events.append({"event": current_event, "data": payload})
                if current_event in ("complete", "error") or len(events) >= max_events:
                    break
    return events


# ============================================================================
# Group A: Media Inspection (POST /api/inspect)
# ============================================================================


@pytest.mark.asyncio
async def test_inspect_valid_youtube_url(async_client: httpx.AsyncClient):
    """Verify POST /api/inspect returns 200 and structured InspectResponse."""
    mock_resp = InspectResponse(
        id="dQw4w9WgXcQ",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        platform="youtube",
        title="Rick Astley - Never Gonna Give You Up",
        uploader="Rick Astley",
        thumbnail="https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
        media_type="video",
        items=[],
        formats=[
            FormatOption(format_id="best", label="Original Quality", ext="mp4"),
            FormatOption(format_id="audio-mp3", label="Audio Only (MP3)", ext="mp3"),
        ],
    )
    with patch("app.services.router.inspect", new_callable=AsyncMock) as mock_inspect:
        mock_inspect.return_value = mock_resp
        resp = await async_client.post(
            "/api/inspect",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "dQw4w9WgXcQ"
        assert data["platform"] == "youtube"
        assert data["media_type"] == "video"
        assert "Rick Astley" in data["title"]
        assert len(data["formats"]) == 2


@pytest.mark.asyncio
async def test_inspect_valid_instagram_carousel(async_client: httpx.AsyncClient):
    """Verify POST /api/inspect returns 200 with carousel items."""
    mock_resp = InspectResponse(
        id="334819201948",
        url="https://www.instagram.com/p/334819201948/",
        platform="instagram",
        title="Sample carousel",
        uploader="photographer",
        thumbnail="https://instagram.com/thumb.jpg",
        media_type="carousel",
        items=[
            MediaItem(index=0, type="image", url="https://instagram.com/p1.jpg"),
            MediaItem(index=1, type="image", url="https://instagram.com/p2.jpg"),
            MediaItem(index=2, type="video", url="https://instagram.com/p3.mp4"),
        ],
        formats=[],
    )
    with patch("app.services.router.inspect", new_callable=AsyncMock) as mock_inspect:
        mock_inspect.return_value = mock_resp
        resp = await async_client.post(
            "/api/inspect",
            json={"url": "https://www.instagram.com/p/334819201948/"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform"] == "instagram"
        assert data["media_type"] == "carousel"
        assert len(data["items"]) == 3
        assert data["items"][0]["type"] == "image"
        assert data["items"][2]["type"] == "video"


@pytest.mark.asyncio
async def test_inspect_invalid_scheme_blocked(async_client: httpx.AsyncClient):
    """Verify non-HTTP schemes are rejected with 400 Bad Request."""
    r_file = await async_client.post("/api/inspect", json={"url": "file:///etc/passwd"})
    assert r_file.status_code == 400

    r_ftp = await async_client.post("/api/inspect", json={"url": "ftp://example.com/video.mp4"})
    assert r_ftp.status_code == 400


@pytest.mark.asyncio
async def test_inspect_ssrf_loopback_and_metadata_blocked(async_client: httpx.AsyncClient):
    """Verify loopback and cloud metadata SSRF targets are rejected with 400."""
    r_local = await async_client.post("/api/inspect", json={"url": "http://127.0.0.1:8000/admin"})
    assert r_local.status_code == 400

    r_meta = await async_client.post(
        "/api/inspect", json={"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert r_meta.status_code == 400


@pytest.mark.asyncio
async def test_inspect_ssrf_obfuscated_ips_blocked(async_client: httpx.AsyncClient):
    """Verify obfuscated POSIX integer and octal IPs are rejected with 400."""
    r_dec = await async_client.post("/api/inspect", json={"url": "http://2130706433/"})
    assert r_dec.status_code == 400

    r_oct = await async_client.post("/api/inspect", json={"url": "http://0177.0.0.1/"})
    assert r_oct.status_code == 400


@pytest.mark.asyncio
async def test_inspect_extraction_error_returns_400(async_client: httpx.AsyncClient):
    """Verify ExtractionError during inspect translates to 400 Bad Request."""
    with patch(
        "app.services.router.inspect",
        new_callable=AsyncMock,
        side_effect=ExtractionError("Video is unavailable"),
    ):
        resp = await async_client.post(
            "/api/inspect",
            json={"url": "https://www.youtube.com/watch?v=unavailable"},
        )
        assert resp.status_code == 400
        assert "unavailable" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_inspect_auth_required_error_returns_401(async_client: httpx.AsyncClient):
    """Verify AuthRequiredError translates to 401 Unauthorized with guidance."""
    with patch(
        "app.services.router.inspect",
        new_callable=AsyncMock,
        side_effect=AuthRequiredError("Sign in to confirm you are not a bot"),
    ):
        resp = await async_client.post(
            "/api/inspect",
            json={"url": "https://www.youtube.com/watch?v=bot_check"},
        )
        assert resp.status_code == 401
        assert "authentication" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_inspect_rate_limit_error_returns_429(async_client: httpx.AsyncClient):
    """Verify RateLimitError translates to 429 Too Many Requests."""
    with patch(
        "app.services.router.inspect",
        new_callable=AsyncMock,
        side_effect=RateLimitError("HTTP Error 429: Too Many Requests"),
    ):
        resp = await async_client.post(
            "/api/inspect",
            json={"url": "https://twitter.com/user/status/123"},
        )
        assert resp.status_code == 429


@pytest.mark.asyncio
async def test_inspect_missing_body_returns_422(async_client: httpx.AsyncClient):
    """Verify missing JSON body in POST /api/inspect returns 422."""
    resp = await async_client.post("/api/inspect", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_inspect_empty_url_returns_400(async_client: httpx.AsyncClient):
    """Verify blank URL string returns 400 Bad Request."""
    resp = await async_client.post("/api/inspect", json={"url": "   "})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_inspect_with_client_session_cookies_and_proxy(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify POST /api/inspect supplies client session cookies and proxy without modifying server config."""
    proxy_manager.reset_runtime_proxy()
    server_cookie_file = temp_environment["cookies_dir"] / "instagram.txt"
    assert not server_cookie_file.exists()

    mock_resp = InspectResponse(
        id="sample-id",
        url="https://www.instagram.com/p/sample/",
        platform="instagram",
        title="Sample post",
        media_type="image",
        items=[],
        formats=[],
    )

    client_netscape = (
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\tclient_session_val\n"
    )

    with patch("app.services.router.inspect", new_callable=AsyncMock) as mock_inspect:
        mock_inspect.return_value = mock_resp
        resp = await async_client.post(
            "/api/inspect",
            json={
                "url": "https://www.instagram.com/p/sample/",
                "cookies": {"instagram": client_netscape},
                "proxy": "socks5://127.0.0.1:9050",
            },
        )
        assert resp.status_code == 200
        mock_inspect.assert_awaited_once_with(
            "https://www.instagram.com/p/sample/",
            proxy="socks5://127.0.0.1:9050",
            cookies={"instagram": client_netscape},
        )

    # Server config remains untouched
    assert not server_cookie_file.exists()
    assert proxy_manager.get_proxy() is None


@pytest.mark.asyncio
async def test_inspect_invalid_client_cookies_returns_400(async_client: httpx.AsyncClient):
    """Verify POST /api/inspect with malformed client cookies returns 400 Bad Request."""
    resp = await async_client.post(
        "/api/inspect",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "cookies": {"youtube": "invalid_cookie_format_without_netscape_columns"},
        },
    )
    assert resp.status_code == 400
    assert "cookie format" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_inspect_invalid_client_proxy_returns_400(async_client: httpx.AsyncClient):
    """Verify POST /api/inspect with invalid proxy scheme or port returns 400 Bad Request."""
    resp = await async_client.post(
        "/api/inspect",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "proxy": "ftp://bad-proxy:21",
        },
    )
    assert resp.status_code == 400
    assert "unsupported proxy scheme" in resp.json()["detail"].lower()


# ============================================================================
# Group B: Download Enqueue & Execution (POST /api/download)
# ============================================================================


@pytest.mark.asyncio
async def test_download_with_client_session_cookies_and_proxy(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify POST /api/download supplies client session cookies and proxy to background worker."""
    proxy_manager.reset_runtime_proxy()
    server_cookie_file = temp_environment["cookies_dir"] / "youtube.txt"
    assert not server_cookie_file.exists()

    client_netscape = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tclient_sid_val\n"
    )

    with patch("app.services.router.download", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = DownloadResult(
            task_id="task-dl-client",
            filename="vid.mp4",
            file_path="/tmp/vid.mp4",
            file_size=2048,
            download_url="/api/files/task-dl-client/vid.mp4",
            is_zip=False,
        )
        resp = await async_client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "cookies": {"youtube": client_netscape},
                "proxy": "socks5://127.0.0.1:9050",
            },
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        for _ in range(30):
            t = progress_manager.get_task(task_id)
            if t and t.status in ("completed", "error"):
                break
            await asyncio.sleep(0.02)

        assert mock_dl.await_count == 1
        _, kwargs = mock_dl.await_args
        assert kwargs["proxy"] == "socks5://127.0.0.1:9050"
        assert kwargs["cookies"] == {"youtube": client_netscape}

    # Server config remains untouched
    assert not server_cookie_file.exists()
    assert proxy_manager.get_proxy() is None


@pytest.mark.asyncio
async def test_download_invalid_client_cookies_returns_400(async_client: httpx.AsyncClient):
    """Verify POST /api/download with malformed client cookies returns 400 Bad Request."""
    resp = await async_client.post(
        "/api/download",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "cookies": "not-a-valid-cookie-string",
        },
    )
    assert resp.status_code == 400
    assert "cookie format" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_download_invalid_client_proxy_returns_400(async_client: httpx.AsyncClient):
    """Verify POST /api/download with invalid client proxy URL returns 400 Bad Request."""
    resp = await async_client.post(
        "/api/download",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "proxy": "http://bad host:8080",
        },
    )
    assert resp.status_code == 400



@pytest.mark.asyncio
async def test_download_valid_request_queued(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify POST /api/download initiates a task and returns queued status."""
    with patch("app.services.router.download", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = DownloadResult(
            task_id="task-test-1",
            filename="video.mp4",
            file_path="/tmp/video.mp4",
            file_size=1024,
            download_url="/api/files/task-test-1/video.mp4",
            is_zip=False,
        )
        resp = await async_client.post(
            "/api/download",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "queued"

        # Await completion
        task_id = data["task_id"]
        for _ in range(30):
            t = progress_manager.get_task(task_id)
            if t and t.status in ("completed", "error"):
                break
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_download_triggers_background_execution_to_completion(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify background worker executes router.download and updates task to completed."""
    with patch("app.services.router.download", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = DownloadResult(
            task_id="task-mock",
            filename="sample.mp4",
            file_path="/tmp/sample.mp4",
            file_size=2048,
            download_url="/api/files/task-mock/sample.mp4",
            is_zip=False,
        )
        resp = await async_client.post(
            "/api/download",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        for _ in range(50):
            t = progress_manager.get_task(task_id)
            if t and t.status == "completed":
                break
            await asyncio.sleep(0.02)

        task = progress_manager.get_task(task_id)
        assert task is not None
        assert task.status == "completed"
        assert task.filename == "sample.mp4"
        assert task.download_url == f"/api/files/{task_id}/sample.mp4" or "/api/files/task-mock/sample.mp4"


@pytest.mark.asyncio
async def test_download_background_failure_updates_task_status(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify background worker exception sets task status to error."""
    with patch(
        "app.services.router.download",
        new_callable=AsyncMock,
        side_effect=ExtractionError("Network stream aborted"),
    ):
        resp = await async_client.post(
            "/api/download",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        for _ in range(50):
            t = progress_manager.get_task(task_id)
            if t and t.status == "error":
                break
            await asyncio.sleep(0.02)

        task = progress_manager.get_task(task_id)
        assert task is not None
        assert task.status == "error"
        assert "aborted" in (task.error or "").lower()


@pytest.mark.asyncio
async def test_download_invalid_scheme_blocked(async_client: httpx.AsyncClient):
    """Verify invalid scheme in POST /api/download is rejected with 400."""
    resp = await async_client.post("/api/download", json={"url": "file:///etc/shadow"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_download_ssrf_target_blocked(async_client: httpx.AsyncClient):
    """Verify SSRF loopback in POST /api/download is rejected with 400."""
    resp = await async_client.post("/api/download", json={"url": "http://127.0.0.1:8000/download"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_download_missing_body_returns_422(async_client: httpx.AsyncClient):
    """Verify missing JSON body in POST /api/download returns 422."""
    resp = await async_client.post("/api/download", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_download_empty_url_returns_400(async_client: httpx.AsyncClient):
    """Verify blank URL string returns 400 Bad Request."""
    resp = await async_client.post("/api/download", json={"url": "   "})
    assert resp.status_code == 400


# ============================================================================
# Group C: SSE Progress Streaming (GET /api/progress/{task_id})
# ============================================================================


@pytest.mark.asyncio
async def test_progress_sse_content_type(async_client: httpx.AsyncClient):
    """Verify SSE endpoint returns 200 with text/event-stream content-type."""
    task = await progress_manager.create_task()
    tid = task.task_id

    async def emit_done():
        await asyncio.sleep(0.02)
        await progress_manager.set_completed(
            tid, filename="test.mp4", download_url=f"/api/files/{tid}/test.mp4", file_size=1024
        )

    emitter = asyncio.create_task(emit_done())
    async with async_client.stream("GET", f"/api/progress/{tid}") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        async for line in response.aiter_lines():
            if "complete" in line:
                break
    await emitter


@pytest.mark.asyncio
async def test_progress_sse_event_lifecycle(async_client: httpx.AsyncClient):
    """Verify SSE stream emits progress, postprocessing, and complete events."""
    task = await progress_manager.create_task()
    tid = task.task_id

    async def emit_lifecycle():
        await asyncio.sleep(0.02)
        await progress_manager.update_progress(
            tid, progress=35.5, speed="3.1MiB/s", eta=10, message="Downloading video..."
        )
        await asyncio.sleep(0.02)
        await progress_manager.set_postprocessing(tid, message="Remuxing audio/video...")
        await asyncio.sleep(0.02)
        await progress_manager.set_completed(
            tid, filename="final.mp4", download_url=f"/api/files/{tid}/final.mp4", file_size=4096
        )

    emitter = asyncio.create_task(emit_lifecycle())
    events = await parse_sse_events(async_client, tid, max_events=10)
    await emitter

    event_types = [e["event"] for e in events]
    assert "progress" in event_types
    assert "postprocessing" in event_types
    assert "complete" in event_types

    prog_e = [e for e in events if e["event"] == "progress"][-1]
    assert prog_e["data"]["progress"] == 35.5
    assert prog_e["data"]["speed"] == "3.1MiB/s"
    assert prog_e["data"]["eta"] == 10

    comp_e = [e for e in events if e["event"] == "complete"][-1]
    assert comp_e["data"]["filename"] == "final.mp4"
    assert comp_e["data"]["file_size"] == 4096


@pytest.mark.asyncio
async def test_progress_sse_error_event(async_client: httpx.AsyncClient):
    """Verify SSE stream emits error event upon task failure."""
    task = await progress_manager.create_task()
    tid = task.task_id

    async def emit_err():
        await asyncio.sleep(0.02)
        await progress_manager.set_error(tid, error_message="ffmpeg process failed with code 1")

    emitter = asyncio.create_task(emit_err())
    events = await parse_sse_events(async_client, tid, max_events=5)
    await emitter

    err_events = [e for e in events if e["event"] == "error"]
    assert len(err_events) >= 1
    assert "ffmpeg" in err_events[0]["data"]["message"]


@pytest.mark.asyncio
async def test_progress_sse_nonexistent_task_returns_404(async_client: httpx.AsyncClient):
    """Verify requesting SSE stream for unknown task returns 404."""
    resp = await async_client.get("/api/progress/task-does-not-exist-xyz")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_progress_sse_already_completed_task(async_client: httpx.AsyncClient):
    """Verify connecting to an already completed task immediately emits complete event."""
    task = await progress_manager.create_task()
    tid = task.task_id
    await progress_manager.set_completed(
        tid, filename="done.mp4", download_url=f"/api/files/{tid}/done.mp4", file_size=100
    )

    events = await parse_sse_events(async_client, tid, max_events=3)
    assert len(events) == 1
    assert events[0]["event"] == "complete"
    assert events[0]["data"]["filename"] == "done.mp4"


@pytest.mark.asyncio
async def test_progress_sse_already_failed_task(async_client: httpx.AsyncClient):
    """Verify connecting to an already failed task immediately emits error event."""
    task = await progress_manager.create_task()
    tid = task.task_id
    await progress_manager.set_error(tid, error_message="Expired link")

    events = await parse_sse_events(async_client, tid, max_events=3)
    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert "Expired link" in events[0]["data"]["message"]


@pytest.mark.asyncio
async def test_progress_sse_invalid_task_id_returns_400(async_client: httpx.AsyncClient):
    """Verify requesting SSE progress with invalid task IDs returns 400 Bad Request."""
    invalid_task_ids = [".", "..", "task/bad", "task 123", "task@evil"]
    for tid in invalid_task_ids:
        resp = await async_client.get(f"/api/progress/{tid}")
        assert resp.status_code in (400, 404), f"Expected 400 or 404 for task_id '{tid}', got {resp.status_code}"


@pytest.mark.asyncio
async def test_progress_sse_early_client_abort_cleans_up_subscribers():
    """Verify early consumer abort after initial snapshot cleanly unregisters SSE subscriber."""
    task = await progress_manager.create_task("task-sse-abort")
    tid = task.task_id

    # Subscribe and consume ONLY the initial progress snapshot
    agen = progress_manager.subscribe_sse(tid)
    initial_event = await anext(agen)
    assert initial_event["event"] == "progress"

    # Verify subscriber queue was registered
    assert len(progress_manager._subscribers.get(tid, [])) == 1

    # Simulate client disconnect / generator early abort
    await agen.aclose()

    # Verify subscriber list is completely empty / cleaned up in try...finally
    subs = progress_manager._subscribers.get(tid)
    assert subs is None or len(subs) == 0



# ============================================================================
# Group D: File Serving & Path Traversal Guard (GET /api/files/{task_id}/{filename})
# ============================================================================


@pytest.mark.asyncio
async def test_serve_existing_single_media_file(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify serving existing media file returns 200 with attachment header."""
    task_dir = temp_environment["downloads_dir"] / "task-file-media"
    task_dir.mkdir(parents=True, exist_ok=True)
    media_file = task_dir / "sample_video.mp4"
    media_file.write_bytes(b"dummy mp4 video bytes")

    resp = await async_client.get("/api/files/task-file-media/sample_video.mp4")
    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "video/mp4"
    assert "attachment" in resp.headers.get("content-disposition", "").lower()
    assert 'filename="sample_video.mp4"' in resp.headers.get("content-disposition", "")
    assert resp.content == b"dummy mp4 video bytes"


@pytest.mark.asyncio
async def test_serve_cjk_filename_utf8_content_disposition(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify serving CJK filename returns 200 with matching Content-Type and RFC 5987 / RFC 6266 Content-Disposition."""
    task_dir = temp_environment["downloads_dir"] / "task-file-cjk"
    task_dir.mkdir(parents=True, exist_ok=True)
    cjk_name = "测试视频_20261113.mp4"
    cjk_file = task_dir / cjk_name
    cjk_file.write_bytes(b"cjk video binary payload")

    resp = await async_client.get(f"/api/files/task-file-cjk/{quote(cjk_name)}")
    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "video/mp4"
    disp = resp.headers.get("content-disposition", "")
    assert "attachment" in disp.lower()
    assert f"filename*=utf-8''{quote(cjk_name)}" in disp
    assert resp.content == b"cjk video binary payload"


@pytest.mark.asyncio
async def test_serve_emoji_filename_utf8_content_disposition(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify serving Emoji filename returns 200 with matching Content-Type and RFC 5987 / RFC 6266 Content-Disposition."""
    task_dir = temp_environment["downloads_dir"] / "task-file-emoji"
    task_dir.mkdir(parents=True, exist_ok=True)
    emoji_name = "🎉🔥🚀_media.mp4"
    emoji_file = task_dir / emoji_name
    emoji_file.write_bytes(b"emoji video binary payload")

    resp = await async_client.get(f"/api/files/task-file-emoji/{quote(emoji_name)}")
    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "video/mp4"
    disp = resp.headers.get("content-disposition", "")
    assert "attachment" in disp.lower()
    assert f"filename*=utf-8''{quote(emoji_name)}" in disp
    assert resp.content == b"emoji video binary payload"


@pytest.mark.asyncio
async def test_serve_multilingual_filenames_utf8_content_disposition(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify serving Cyrillic, Arabic, and Japanese filenames returns 200 with valid Content-Disposition."""
    task_dir = temp_environment["downloads_dir"] / "task-file-multilingual"
    task_dir.mkdir(parents=True, exist_ok=True)

    test_cases = [
        ("Русский_тест.mp4", "video/mp4", b"cyrillic content"),
        ("العربية_اختبار.mp3", "audio/mpeg", b"arabic content"),
        ("japanese_日本語_テスト.jpg", "image/jpeg", b"japanese image content"),
    ]

    for filename, expected_ct, content in test_cases:
        f = task_dir / filename
        f.write_bytes(content)
        resp = await async_client.get(f"/api/files/task-file-multilingual/{quote(filename)}")
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == expected_ct
        disp = resp.headers.get("content-disposition", "")
        assert "attachment" in disp.lower()
        assert f"filename*=utf-8''{quote(filename)}" in disp
        assert resp.content == content


@pytest.mark.asyncio
async def test_serve_hashtag_filename_preserves_leading_hash_and_disposition(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify serving a file whose filename starts with '#' (e.g. from Twitter post text)

    preserves the leading '#' in Content-Disposition (both filename= and filename*=),
    does not cause routing errors, and serves the complete media payload.
    """
    task_dir = temp_environment["downloads_dir"] / "task-file-hashtag"
    task_dir.mkdir(parents=True, exist_ok=True)
    hashtag_name = "#Umingle #Ometv #Monkeyapp #Omegle #CSL.mp4"
    hashtag_file = task_dir / hashtag_name
    hashtag_file.write_bytes(b"dummy twitter video with hashtag bytes")

    # The client requests the URL-encoded path (/api/files/{task_id}/%23...)
    encoded_filename = quote(hashtag_name)
    resp = await async_client.get(f"/api/files/task-file-hashtag/{encoded_filename}")
    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "video/mp4"

    disp = resp.headers.get("content-disposition", "")
    assert "attachment" in disp.lower()
    # Verify standard ASCII filename parameter retains '#'
    assert f'filename="{hashtag_name}"' in disp
    # Verify RFC 5987 filename* parameter retains URL-encoded '%23'
    assert f"filename*=utf-8''{encoded_filename}" in disp
    assert resp.content == b"dummy twitter video with hashtag bytes"


@pytest.mark.asyncio
async def test_serve_hashtag_filename_double_encoded_fallback(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify serving a hashtag filename when double-encoded (%2523) correctly resolves to the file."""
    task_dir = temp_environment["downloads_dir"] / "task-file-double-enc"
    task_dir.mkdir(parents=True, exist_ok=True)
    hashtag_name = "#CSL_highlight.mp4"
    hashtag_file = task_dir / hashtag_name
    hashtag_file.write_bytes(b"double encoded test bytes")

    double_encoded = quote(quote(hashtag_name))
    resp = await async_client.get(f"/api/files/task-file-double-enc/{double_encoded}")
    assert resp.status_code == 200
    assert resp.content == b"double encoded test bytes"
    disp = resp.headers.get("content-disposition", "")
    assert f'filename="{hashtag_name}"' in disp


@pytest.mark.asyncio
async def test_serve_existing_zip_bundle(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify serving existing ZIP bundle returns application/zip Content-Type."""
    task_dir = temp_environment["downloads_dir"] / "task-file-zip"
    task_dir.mkdir(parents=True, exist_ok=True)
    zip_file = task_dir / "bundle.zip"
    zip_file.write_bytes(b"PK\x03\x04dummy zip bytes")

    resp = await async_client.get("/api/files/task-file-zip/bundle.zip")
    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "application/zip"
    assert "attachment" in resp.headers.get("content-disposition", "").lower()


@pytest.mark.asyncio
async def test_serve_various_content_types(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify appropriate Content-Type headers for various media extensions."""
    task_dir = temp_environment["downloads_dir"] / "task-types"
    task_dir.mkdir(parents=True, exist_ok=True)

    types_matrix = [
        ("audio.mp3", "audio/mpeg"),
        ("audio.m4a", "audio/mp4"),
        ("audio.wav", "audio/wav"),
        ("image.jpg", "image/jpeg"),
        ("image.png", "image/png"),
        ("image.webp", "image/webp"),
    ]

    for fname, expected_ct in types_matrix:
        (task_dir / fname).write_bytes(b"test data")
        resp = await async_client.get(f"/api/files/task-types/{fname}")
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == expected_ct


@pytest.mark.asyncio
async def test_serve_nonexistent_file_returns_404(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify requesting non-existent file inside valid task directory returns 404."""
    task_dir = temp_environment["downloads_dir"] / "task-exists"
    task_dir.mkdir(parents=True, exist_ok=True)

    resp = await async_client.get("/api/files/task-exists/missing.mp4")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_serve_nonexistent_task_dir_returns_404(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify requesting file from non-existent task directory returns 404."""
    resp = await async_client.get("/api/files/task-missing-123/file.mp4")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_serve_path_traversal_dotdot_in_filename_blocked(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify directory traversal in filename (..) returns 400 Bad Request."""
    resp = await async_client.get("/api/files/task-1/../../etc/passwd")
    assert resp.status_code in (400, 404)


@pytest.mark.asyncio
async def test_serve_path_traversal_encoded_dotdot_blocked(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify URL-encoded dot-dot traversal returns 400 Bad Request."""
    resp = await async_client.get("/api/files/task-1/%2e%2e/%2e%2e/etc/passwd")
    assert resp.status_code in (400, 404)


@pytest.mark.asyncio
async def test_serve_path_traversal_in_task_id_blocked(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify path traversal in task_id parameter returns 400."""
    resp = await async_client.get("/api/files/..%2fdownloads%2ftask-1/sample.mp4")
    assert resp.status_code in (400, 404)


@pytest.mark.asyncio
async def test_serve_rejects_dot_task_id_and_task_isolation_bypass(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify task_id='.' is strictly rejected to prevent cross-task file isolation bypass."""
    from fastapi import HTTPException
    from app.routers.download import get_downloaded_file

    # Create a victim task folder and file in downloads
    victim_dir = temp_environment["downloads_dir"] / "task-victim"
    victim_dir.mkdir(parents=True, exist_ok=True)
    victim_file = victim_dir / "secret.mp4"
    victim_file.write_bytes(b"victim secret data")

    # Attacker attempts to use URL-encoded dot (%2e) to set task_id="." and access victim file across tasks
    resp1 = await async_client.get("/api/files/%2e/task-victim/secret.mp4")
    assert resp1.status_code == 400
    assert "Invalid task ID" in resp1.json().get("detail", "")

    # Attacker attempts URL-encoded dot-dot (%2e%2e)
    resp2 = await async_client.get("/api/files/%2e%2e/task-victim/secret.mp4")
    assert resp2.status_code in (400, 404)

    # Directly invoking endpoint handler with task_id="." raises 400 HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await get_downloaded_file(task_id=".", filename="task-victim/secret.mp4")
    assert exc_info.value.status_code == 400
    assert "Invalid task ID" in exc_info.value.detail

    # Directly invoking endpoint handler with task_id=".." raises 400 HTTPException
    with pytest.raises(HTTPException) as exc_info2:
        await get_downloaded_file(task_id="..", filename="task-victim/secret.mp4")
    assert exc_info2.value.status_code == 400
    assert "Invalid task ID" in exc_info2.value.detail


@pytest.mark.asyncio
async def test_serve_rejects_invalid_task_id_characters(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify various malformed task_id formats are rejected with 400."""
    invalid_ids = [
        ".",
        "..",
        "%2e",
        "%2e%2e",
        "task/123",
        "task%2f123",
        "task\\123",
        "task 123",
        "task@evil!",
        "task#anchor",
    ]
    for tid in invalid_ids:
        resp = await async_client.get(f"/api/files/{tid}/sample.mp4")
        assert resp.status_code in (400, 404), f"Expected 400 or 404 for invalid task_id '{tid}', got {resp.status_code}"



# ============================================================================
# Group E: Cookie Settings API (/api/settings/cookies)
# ============================================================================


@pytest.mark.asyncio
async def test_get_cookie_statuses(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify GET /api/settings/cookies returns dictionary for all platforms."""
    resp = await async_client.get("/api/settings/cookies")
    assert resp.status_code == 200
    data = resp.json()
    assert "instagram" in data
    assert "twitter" in data
    assert "youtube" in data
    for plat in ("instagram", "twitter", "youtube"):
        assert "exists" in data[plat]
        assert "valid" in data[plat]


@pytest.mark.asyncio
async def test_post_paste_valid_cookies(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify POST /api/settings/cookies saves valid Netscape cookie file."""
    netscape_content = (
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\tvalid_session_12345\n"
    )
    resp = await async_client.post(
        "/api/settings/cookies",
        json={"platform": "instagram", "content": netscape_content},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "saved"
    assert data["platform"] == "instagram"

    # Confirm cookie exists on disk
    cookie_path = temp_environment["cookies_dir"] / "instagram.txt"
    assert cookie_path.exists()
    assert "sessionid" in cookie_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_post_paste_invalid_cookies_returns_400(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify POST /api/settings/cookies with invalid format returns 400."""
    resp = await async_client.post(
        "/api/settings/cookies",
        json={"platform": "instagram", "content": "not-a-valid-netscape-cookie"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_upload_multipart_cookie_file(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify POST /api/settings/cookies/upload saves valid uploaded cookie file."""
    netscape_content = (
        "# Netscape HTTP Cookie File\n"
        ".twitter.com\tTRUE\t/\tTRUE\t2000000000\tauth_token\tvalid_auth_token_999\n"
    )
    files = {"file": ("twitter.txt", netscape_content.encode("utf-8"), "text/plain")}
    data = {"platform": "twitter"}

    resp = await async_client.post(
        "/api/settings/cookies/upload",
        data=data,
        files=files,
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "uploaded"
    assert res_data["platform"] == "twitter"

    cookie_path = temp_environment["cookies_dir"] / "twitter.txt"
    assert cookie_path.exists()


@pytest.mark.asyncio
async def test_post_upload_empty_cookie_file_returns_400(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify uploading an empty cookie file returns 400 Bad Request."""
    files = {"file": ("empty.txt", b"   ", "text/plain")}
    data = {"platform": "twitter"}

    resp = await async_client.post(
        "/api/settings/cookies/upload",
        data=data,
        files=files,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_upload_invalid_cookie_file_returns_400(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify uploading invalid cookie contents returns 400 Bad Request."""
    files = {"file": ("bad.txt", b"random binary garbage", "text/plain")}
    data = {"platform": "youtube"}

    resp = await async_client.post(
        "/api/settings/cookies/upload",
        data=data,
        files=files,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_upload_cookie_file_exceeding_5mb_returns_413(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify uploading a cookie file larger than 5MB is rejected with 413 Payload Too Large."""
    # 5MB + 1KB
    large_payload = b"# Netscape HTTP Cookie File\n" + b"A" * (5 * 1024 * 1024 + 1024)
    files = {"file": ("large_cookie.txt", large_payload, "text/plain")}
    data = {"platform": "youtube"}

    resp = await async_client.post(
        "/api/settings/cookies/upload",
        data=data,
        files=files,
    )
    assert resp.status_code in (413, 400)
    assert "5MB" in resp.json().get("detail", "") or "exceeds" in resp.json().get("detail", "").lower()

    # Ensure no file was written to disk
    cookie_path = temp_environment["cookies_dir"] / "youtube.txt"
    assert not cookie_path.exists()


@pytest.mark.asyncio
async def test_post_paste_cookie_content_exceeding_5mb_returns_413(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify pasting cookie content larger than 5MB is rejected with 413 Payload Too Large."""
    large_content = "# Netscape HTTP Cookie File\n" + ("x" * (5 * 1024 * 1024 + 1024))
    body = {"platform": "instagram", "content": large_content}

    resp = await async_client.post("/api/settings/cookies", json=body)
    assert resp.status_code in (413, 400)
    assert "5MB" in resp.json().get("detail", "") or "exceeds" in resp.json().get("detail", "").lower()



@pytest.mark.asyncio
async def test_delete_cookies_success(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify DELETE /api/settings/cookies/{platform} removes cookie file and is idempotent."""
    cookie_path = temp_environment["cookies_dir"] / "youtube.txt"
    cookie_path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    assert cookie_path.exists()

    resp = await async_client.delete("/api/settings/cookies/youtube")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert not cookie_path.exists()

    # Second delete is idempotent
    resp2 = await async_client.delete("/api/settings/cookies/youtube")
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_cookie_platform_traversal_rejected(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify platform parameter with path traversal is rejected."""
    resp = await async_client.post(
        "/api/settings/cookies",
        json={"platform": "../malicious", "content": "# Netscape HTTP Cookie File\n"},
    )
    assert resp.status_code == 400


# ============================================================================
# Group F: Proxy Settings API (/api/settings/proxy)
# ============================================================================


@pytest.mark.asyncio
async def test_get_proxy_default_none(async_client: httpx.AsyncClient):
    """Verify GET /api/settings/proxy returns none by default."""
    proxy_manager.reset_runtime_proxy()
    resp = await async_client.get("/api/settings/proxy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["proxy"] is None
    assert data["source"] == "none"


@pytest.mark.asyncio
async def test_post_valid_socks5_proxy(async_client: httpx.AsyncClient):
    """Verify POST /api/settings/proxy updates runtime proxy configuration."""
    resp = await async_client.post(
        "/api/settings/proxy",
        json={"proxy": "socks5://127.0.0.1:1080"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["proxy"] == "socks5://127.0.0.1:1080"
    assert data["source"] == "runtime"

    # Confirm subsequent GET reflects updated runtime proxy
    get_resp = await async_client.get("/api/settings/proxy")
    assert get_resp.json()["proxy"] == "socks5://127.0.0.1:1080"


@pytest.mark.asyncio
async def test_post_invalid_proxy_scheme_returns_400(async_client: httpx.AsyncClient):
    """Verify invalid proxy scheme returns 400 Bad Request."""
    resp = await async_client.post(
        "/api/settings/proxy",
        json={"proxy": "ftp://bad-proxy:21"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_invalid_proxy_port_returns_400(async_client: httpx.AsyncClient):
    """Verify invalid proxy port returns 400 Bad Request."""
    resp = await async_client.post(
        "/api/settings/proxy",
        json={"proxy": "socks5://127.0.0.1:99999"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_null_proxy_clears_proxy(async_client: httpx.AsyncClient):
    """Verify posting null proxy clears runtime proxy configuration."""
    proxy_manager.set_proxy("socks5://127.0.0.1:1080")
    assert proxy_manager.get_proxy() == "socks5://127.0.0.1:1080"

    resp = await async_client.post(
        "/api/settings/proxy",
        json={"proxy": None},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["proxy"] is None


@pytest.mark.asyncio
async def test_get_proxy_default_socks5_not_leaked(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify GET /api/settings/proxy masks default proxy and raw URL/credentials are completely absent."""
    secret_proxy = "socks5://leak_user:leak_pass@corp.private.leak:1080"
    monkeypatch.setattr(settings, "SOCKS5_PROXY", secret_proxy)
    proxy_manager.reset_runtime_proxy()

    resp = await async_client.get("/api/settings/proxy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["proxy"] is None
    assert data["source"] == "env"
    assert "leak_user" not in resp.text
    assert "leak_pass" not in resp.text
    assert "corp.private.leak" not in resp.text


@pytest.mark.asyncio
async def test_post_null_proxy_with_default_env_does_not_leak_default_proxy(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify POST /api/settings/proxy clearing runtime proxy never exposes default SOCKS5 URL."""
    secret_proxy = "socks5://leak_user:leak_pass@corp.private.leak:1080"
    monkeypatch.setattr(settings, "SOCKS5_PROXY", secret_proxy)
    proxy_manager.set_proxy("socks5://temp-runtime:9050")

    resp = await async_client.post(
        "/api/settings/proxy",
        json={"proxy": None},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["proxy"] is None
    assert "leak_user" not in resp.text
    assert "leak_pass" not in resp.text
    assert "corp.private.leak" not in resp.text


# ============================================================================
# Group G: Lifespan & SPA Fallback
# ============================================================================


@pytest.mark.asyncio
async def test_root_endpoint_default(async_client: httpx.AsyncClient):
    """Verify GET / returns 200 with welcome JSON when static dir not present."""
    resp = await async_client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "All-in-One Media Downloader" in data.get("app", "")


@pytest.mark.asyncio
async def test_spa_fallback_serves_index_html_when_static_exists(
    async_client: httpx.AsyncClient, tmp_path: Path
):
    """Verify SPA fallback returns index.html for client routes when static dir exists."""
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    index_file = static_dir / "index.html"
    index_file.write_text("<!DOCTYPE html><html><body>SPA Root</body></html>", encoding="utf-8")

    with patch("app.main.STATIC_DIR", static_dir):
        r_root = await async_client.get("/")
        assert r_root.status_code == 200
        assert "SPA Root" in r_root.text

        r_route = await async_client.get("/dashboard/settings")
        assert r_route.status_code == 200
        assert "SPA Root" in r_route.text


@pytest.mark.asyncio
async def test_spa_fallback_serves_static_assets(
    async_client: httpx.AsyncClient, tmp_path: Path
):
    """Verify specific static asset file is served if present."""
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    asset_file = static_dir / "favicon.ico"
    asset_file.write_bytes(b"\x00\x00\x01\x00test_icon")

    with patch("app.main.STATIC_DIR", static_dir):
        resp = await async_client.get("/favicon.ico")
        assert resp.status_code == 200
        assert resp.content == b"\x00\x00\x01\x00test_icon"


@pytest.mark.asyncio
async def test_spa_fallback_returns_404_when_static_does_not_exist(
    async_client: httpx.AsyncClient, tmp_path: Path
):
    """Verify non-API path returns 404 when static dir does not exist."""
    nonexistent_dir = tmp_path / "does_not_exist"
    with patch("app.main.STATIC_DIR", nonexistent_dir):
        resp = await async_client.get("/settings")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unknown_api_endpoint_always_returns_404(async_client: httpx.AsyncClient):
    """Verify unknown /api/* endpoint returns 404 JSON and is never caught by SPA fallback."""
    resp = await async_client.get("/api/nonexistent-route-123")
    assert resp.status_code == 404
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_cleaner():
    """Verify application lifespan initializes cleaner and cleans up without errors."""
    async with lifespan(app):
        # Lifespan active: cleaner task is running
        await asyncio.sleep(0.01)
    # Lifespan exited cleanly


@pytest.mark.asyncio
async def test_cleaner_evicts_in_memory_task_records_and_404s_subsequent_progress(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify cleaner evicts in-memory task records so subsequent SSE progress requests return 404."""
    downloads_dir = temp_environment["downloads_dir"]

    # Create task in progress_manager
    task = await progress_manager.create_task("task-cleaner-evict")
    tid = task.task_id

    # Create task directory with an old mtime (> 60 mins)
    task_dir = downloads_dir / tid
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "media.mp4").write_bytes(b"downloaded bytes")
    old_time = time.time() - (120 * 60)
    os.utime(task_dir, (old_time, old_time))

    # Verify task exists in progress_manager
    assert progress_manager.get_task(tid) is not None

    # Run cleanup
    deleted = cleanup_old_downloads(downloads_dir, ttl_minutes=60)
    assert deleted >= 1
    assert not task_dir.exists()

    # Verify in-memory task was evicted from progress_manager
    assert progress_manager.get_task(tid) is None

    # Verify requesting progress now returns 404 Not Found
    resp = await async_client.get(f"/api/progress/{tid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_api_youtube_high_res_format_selection(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify POST /api/download accepts high-res formats (1080p, 720p) and executes download."""
    downloads_dir = temp_environment["downloads_dir"]

    for resolution in ("1080p", "720p"):
        fake_result = DownloadResult(
            task_id="test-task-highres",
            filename=f"video_{resolution}.mp4",
            file_path=str(downloads_dir / f"video_{resolution}.mp4"),
            file_size=10240,
            download_url=f"/api/files/test-task-highres/video_{resolution}.mp4",
            is_zip=False,
        )

        with patch("app.services.router.download", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = fake_result

            resp = await async_client.post(
                "/api/download",
                json={
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "format_id": resolution,
                },
            )
            assert resp.status_code == 200
            task_id = resp.json()["task_id"]

            # Wait for background task to complete
            for _ in range(50):
                task = progress_manager.get_task(task_id)
                if task and task.status in ("completed", "error"):
                    break
                await asyncio.sleep(0.05)

            completed = progress_manager.get_task(task_id)
            assert completed is not None
            assert completed.status == "completed"
            assert completed.filename == f"video_{resolution}.mp4"


@pytest.mark.asyncio
async def test_download_api_multi_item_unbundled_delivery(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Verify unbundled multi-item download produces files list in SSE and enables individual downloads."""
    downloads_dir = temp_environment["downloads_dir"]
    task_id = "test-task-unbundled-api"
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    file1 = task_dir / "user_20240512_item1.jpg"
    file2 = task_dir / "user_20240512_item2.jpg"
    file1.write_bytes(b"image 1 bytes")
    file2.write_bytes(b"image 2 bytes")

    files_info = [
        DownloadFileInfo(
            filename=file1.name,
            file_path=str(file1),
            file_size=file1.stat().st_size,
            download_url=f"/api/files/{task_id}/{file1.name}",
        ),
        DownloadFileInfo(
            filename=file2.name,
            file_path=str(file2),
            file_size=file2.stat().st_size,
            download_url=f"/api/files/{task_id}/{file2.name}",
        ),
    ]

    fake_result = DownloadResult(
        task_id=task_id,
        filename=files_info[0].filename,
        file_path=files_info[0].file_path,
        file_size=sum(f.file_size for f in files_info),
        download_url=files_info[0].download_url,
        is_zip=False,
        files=files_info,
    )

    with patch("app.services.router.download", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = fake_result

        resp = await async_client.post(
            "/api/download",
            json={
                "url": "https://www.instagram.com/p/334819201948/",
                "package_as_zip": False,
            },
        )
        assert resp.status_code == 200
        assigned_id = resp.json()["task_id"]

        # Wait for worker completion
        for _ in range(50):
            task = progress_manager.get_task(assigned_id)
            if task and task.status in ("completed", "error"):
                break
            await asyncio.sleep(0.05)

        task = progress_manager.get_task(assigned_id)
        assert task is not None
        assert task.status == "completed"
        assert task.files is not None
        assert len(task.files) == 2

        # Verify serving both individual files
        for fi in files_info:
            file_resp = await async_client.get(f"/api/files/{task_id}/{fi.filename}")
            assert file_resp.status_code == 200
            assert file_resp.headers.get("content-type") == "image/jpeg"


@pytest.mark.asyncio
async def test_twitter_download_with_hashtag_title_retains_hash_and_serves(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Regression Test (R1 & R2):

    Verify Twitter video post whose text starts with '#' is properly handled through
    the download API:
    1. Retains the leading '#' in task.filename.
    2. Constructs task.download_url with '%23' URL-encoding (no raw '#' that causes
       browser fragment truncation / routing errors).
    3. GET request to the resulting task.download_url succeeds (200 OK) and delivers
       proper Content-Disposition with the leading '#' intact.
    """
    downloads_dir = temp_environment["downloads_dir"]
    task_id = "task-twitter-hashtag-e2e"
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    hashtag_title = "#Umingle #Ometv #Monkeyapp #Omegle #CSL"
    filename_on_disk = f"{hashtag_title}.mp4"
    output_file = task_dir / filename_on_disk
    output_file.write_bytes(b"twitter hashtag video content binary stream")

    fake_result = DownloadResult(
        task_id=task_id,
        filename=filename_on_disk,
        file_path=str(output_file),
        file_size=output_file.stat().st_size,
        download_url=f"/api/files/{task_id}/{quote(filename_on_disk)}",
        is_zip=False,
    )

    with patch("app.services.router.download", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = fake_result

        resp = await async_client.post(
            "/api/download",
            json={
                "url": "https://x.com/CSLfrreac/status/2121343870013222933?a=UXOELjiUHqCARzEpBGU&s=20",
                "format_id": "best",
                "package_as_zip": False,
                "metadata": {
                    "id": "2121343870013222933",
                    "title": hashtag_title,
                    "platform": "twitter",
                },
            },
        )
        assert resp.status_code == 200
        assigned_id = resp.json()["task_id"]

        for _ in range(50):
            task = progress_manager.get_task(assigned_id)
            if task and task.status in ("completed", "error"):
                break
            await asyncio.sleep(0.05)

        task = progress_manager.get_task(assigned_id)
        assert task is not None
        assert task.status == "completed"

        # 1. Filename retains leading '#'
        assert task.filename.startswith("#")
        assert task.filename == filename_on_disk

        # 2. Download URL uses '%23', NOT raw '#'
        assert "#" not in task.download_url
        assert "%23" in task.download_url
        assert task.download_url.startswith(f"/api/files/{task_id}/%23")

        # 3. Browser file retrieval via task.download_url succeeds without truncation/routing errors
        file_resp = await async_client.get(task.download_url)
        assert file_resp.status_code == 200
        assert file_resp.headers.get("content-type") == "video/mp4"

        disp = file_resp.headers.get("content-disposition", "")
        assert "attachment" in disp.lower()
        assert f'filename="{filename_on_disk}"' in disp
        assert f"filename*=utf-8''{quote(filename_on_disk)}" in disp
        assert file_resp.content == b"twitter hashtag video content binary stream"


@pytest.mark.asyncio
async def test_twitter_multi_file_download_with_hashtag_filenames(
    async_client: httpx.AsyncClient, temp_environment: dict[str, Path]
):
    """Regression Test (R2):

    Verify unbundled multi-item download with filenames containing/starting with '#'
    preserves '#' in filenames and encodes '%23' in all download_urls.
    """
    downloads_dir = temp_environment["downloads_dir"]
    task_id = "task-twitter-multi-hashtag"
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    file1 = task_dir / "#item_1.jpg"
    file1.write_bytes(b"image 1 bytes")
    file2 = task_dir / "#item_2.jpg"
    file2.write_bytes(b"image 2 bytes")

    files_info = [
        DownloadFileInfo(
            filename=file1.name,
            file_path=str(file1),
            file_size=file1.stat().st_size,
            download_url=f"/api/files/{task_id}/{quote(file1.name)}",
        ),
        DownloadFileInfo(
            filename=file2.name,
            file_path=str(file2),
            file_size=file2.stat().st_size,
            download_url=f"/api/files/{task_id}/{quote(file2.name)}",
        ),
    ]

    fake_result = DownloadResult(
        task_id=task_id,
        filename=files_info[0].filename,
        file_path=files_info[0].file_path,
        file_size=sum(f.file_size for f in files_info),
        download_url=files_info[0].download_url,
        is_zip=False,
        files=files_info,
    )

    with patch("app.services.router.download", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = fake_result

        resp = await async_client.post(
            "/api/download",
            json={
                "url": "https://x.com/someuser/status/1234567890",
                "package_as_zip": False,
            },
        )
        assert resp.status_code == 200
        assigned_id = resp.json()["task_id"]

        for _ in range(50):
            task = progress_manager.get_task(assigned_id)
            if task and task.status in ("completed", "error"):
                break
            await asyncio.sleep(0.05)

        task = progress_manager.get_task(assigned_id)
        assert task is not None
        assert task.status == "completed"
        assert task.files is not None
        assert len(task.files) == 2

        for item in task.files:
            assert item["filename"].startswith("#")
            assert "#" not in item["download_url"]
            assert "%23" in item["download_url"]

            item_resp = await async_client.get(item["download_url"])
            assert item_resp.status_code == 200
            assert "attachment" in item_resp.headers.get("content-disposition", "").lower()
            assert f'filename="{item["filename"]}"' in item_resp.headers.get("content-disposition", "")



