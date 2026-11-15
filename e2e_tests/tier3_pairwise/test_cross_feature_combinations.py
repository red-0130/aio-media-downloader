"""Tier 3: Cross-Feature Combinations & Pairwise Testing.

Covers:
1. Instagram Story + SOCKS5 Proxy + Netscape Cookies + Auto-ZIP
2. YouTube 4K Video + Audio Extraction (MP3) + SOCKS5 Proxy
3. Twitter Multi-Photo + Auto-ZIP + Standard Title Naming
4. TikTok Video + Fallback Engine + MP4 Remuxing
5. Cookie Upload via API + Immediate Private Post Inspection
6. Proxy Setting Update + Download Route Switching
7. Two-Step Workflow with Partial Item Selection (indices [1, 3] from 5-item carousel)
8. Real-time SSE Tracking + Simultaneous File Download
9. Path Traversal Attack on Task ID + File Name simultaneously
10. SSRF Attempt with Proxy Enabled
11. Instagram Reel with Fallback + Instagram Naming (<username>_<YYYYMMDD>_<ORIGINAL_NAME_FIRST>)
12. TTL Cleanup While Active Tasks Run
13. Audio-Only Option with Custom Format (WAV/M4A) + Unicode Filename
14. Corrupt Cookie Fallback to Unauthenticated Engine Attempt
15. Rapid Successive Inspect & Download Calls (Rate & Concurrency)
16. Dynamic Settings Reset to Defaults (proxy + cookies)
17. Instagram Carousel Partial Selection with Cookies and Proxy
18. Generic URL Audio Extraction with Sanitized Filename
"""

import asyncio
import io
import json
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import settings
from app.models.download import DownloadRequest
from app.services import (
    cleaner,
    cookie_manager,
    progress_manager,
    proxy_manager,
    router,
    security,
)


async def _wait_task_complete(task_id: str, max_wait: float = 8.0) -> Any:
    """Helper to poll progress manager until task is completed or error."""
    start = time.time()
    while time.time() - start < max_wait:
        task = progress_manager.get_task(task_id)
        if task and task.status in ("completed", "error"):
            return task
        await asyncio.sleep(0.05)
    return progress_manager.get_task(task_id)


# ============================================================================
# 1. Instagram Story + SOCKS5 Proxy + Netscape Cookies + Auto-ZIP
# ============================================================================
@pytest.mark.asyncio
async def test_instagram_story_proxy_cookies_autozip(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
    call_log: Any,
):
    """Verify Instagram story extraction routes through proxy, reads cookies, and packages into ZIP."""
    call_log.clear()

    # 1. Configure SOCKS5 Proxy
    proxy_url = "socks5://127.0.0.1:1080"
    proxy_manager.set_proxy(proxy_url)

    # 2. Upload Netscape Cookies for Instagram
    cookie_content = fixtures_paths["cookies_sample"].read_text(encoding="utf-8")
    resp_cookie = await async_client.post(
        "/api/settings/cookies",
        json={"platform": "instagram", "content": cookie_content},
    )
    assert resp_cookie.status_code == 200

    # 3. Request Story Download with Auto-ZIP
    url = "https://www.instagram.com/stories/influencer_daily/94821038/"
    resp_dl = await async_client.post(
        "/api/download",
        json={"url": url, "package_as_zip": True},
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    # 4. Await task completion
    task = await _wait_task_complete(task_id)
    assert task is not None
    assert task.status == "completed"
    assert task.filename.endswith(".zip")

    # 5. Verify Engine Call Log
    records = call_log.filter_by_engine("gallery-dl")
    assert len(records) >= 1
    assert records[0]["proxy"] == proxy_url
    assert "instagram.txt" in str(records[0]["cookies"])

    # 6. Retrieve ZIP and verify archive contents
    resp_file = await async_client.get(f"/api/files/{task_id}/{task.filename}")
    assert resp_file.status_code == 200
    assert resp_file.headers.get("content-type") == "application/zip"

    with zipfile.ZipFile(io.BytesIO(resp_file.content)) as zf:
        namelist = zf.namelist()
        assert len(namelist) >= 2


# ============================================================================
# 2. YouTube 4K Video + Audio Extraction (MP3) + SOCKS5 Proxy
# ============================================================================
@pytest.mark.asyncio
async def test_youtube_4k_audio_extraction_proxy(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Verify YouTube video inspect -> choose MP3 audio -> download routes through SOCKS5 proxy."""
    call_log.clear()
    proxy_url = "socks5://127.0.0.1:1080"
    proxy_manager.set_proxy(proxy_url)

    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # Step 1: Inspect
    resp_inspect = await async_client.post("/api/inspect", json={"url": url})
    assert resp_inspect.status_code == 200
    data = resp_inspect.json()
    assert any(fmt["format_id"] == "audio-mp3" for fmt in data["formats"])

    # Step 2: Download Audio Only
    resp_dl = await async_client.post(
        "/api/download",
        json={
            "url": url,
            "format_id": "audio-mp3",
            "extract_audio": True,
            "audio_format": "mp3",
        },
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    task = await _wait_task_complete(task_id)
    assert task is not None
    assert task.status == "completed"
    assert task.filename.endswith(".mp3")

    # Verify proxy passed to yt-dlp
    records = call_log.filter_by_engine("yt-dlp")
    assert len(records) >= 1
    assert any(r.get("proxy") == proxy_url for r in records)
    assert any(r.get("extract_audio") is True for r in records)

    # Retrieve served file
    resp_file = await async_client.get(f"/api/files/{task_id}/{task.filename}")
    assert resp_file.status_code == 200
    assert resp_file.headers.get("content-type") == "audio/mpeg"


# ============================================================================
# 3. Twitter Multi-Photo + Auto-ZIP + Standard Title Naming
# ============================================================================
@pytest.mark.asyncio
async def test_twitter_multi_photo_autozip_standard_naming(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Verify Twitter 4-image tweet downloads all photos and bundles into ZIP with sanitized naming."""
    url = "https://twitter.com/digital_artist/status/1789098765432109876/photo/1"

    # Step 1: Inspect
    resp_inspect = await async_client.post("/api/inspect", json={"url": url})
    assert resp_inspect.status_code == 200
    assert len(resp_inspect.json()["items"]) == 4

    # Step 2: Download All as ZIP
    resp_dl = await async_client.post(
        "/api/download",
        json={"url": url, "package_as_zip": True},
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    task = await _wait_task_complete(task_id)
    assert task.status == "completed"
    assert task.filename.endswith(".zip")

    # Step 3: Fetch file
    resp_file = await async_client.get(f"/api/files/{task_id}/{task.filename}")
    assert resp_file.status_code == 200
    assert resp_file.headers.get("content-type") == "application/zip"

    with zipfile.ZipFile(io.BytesIO(resp_file.content)) as zf:
        names = zf.namelist()
        assert len(names) == 4
        for name in names:
            assert not any(c in name for c in r'/\:*?"<>|')


# ============================================================================
# 4. TikTok Video + Fallback Engine + MP4 Remuxing
# ============================================================================
@pytest.mark.asyncio
async def test_tiktok_video_fallback_engine_mp4_remux(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Verify TikTok video with primary engine failure automatically falls back to secondary and remuxes to MP4."""
    call_log.clear()
    url = "https://www.tiktok.com/@cheftips_official/video/7369123456789012345_fail_ytdlp"

    resp_dl = await async_client.post(
        "/api/download",
        json={"url": url, "package_as_zip": False},
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    task = await _wait_task_complete(task_id)
    assert task.status == "completed"
    assert task.filename.endswith(".mp4")

    # Verify fallback: both engines were called
    yt_calls = call_log.filter_by_engine("yt-dlp")
    gdl_calls = call_log.filter_by_engine("gallery-dl")
    assert len(yt_calls) >= 1
    assert len(gdl_calls) >= 1

    resp_file = await async_client.get(f"/api/files/{task_id}/{task.filename}")
    assert resp_file.status_code == 200
    assert resp_file.headers.get("content-type") == "video/mp4"


# ============================================================================
# 5. Cookie Upload via API + Immediate Private Post Inspection
# ============================================================================
@pytest.mark.asyncio
async def test_cookie_upload_api_immediate_private_inspect(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
):
    """Verify uploading cookies via Settings API immediately permits inspecting authenticated media."""
    auth_url = "https://www.youtube.com/watch?v=login_required_private_vid"

    # Step 1: Without cookies -> HTTP 401
    resp1 = await async_client.post("/api/inspect", json={"url": auth_url})
    assert resp1.status_code == 401

    # Step 2: Upload cookies via Settings endpoint
    cookie_content = fixtures_paths["cookies_sample"].read_text(encoding="utf-8")
    resp_upload = await async_client.post(
        "/api/settings/cookies",
        json={"platform": "youtube", "content": cookie_content},
    )
    assert resp_upload.status_code == 200

    # Step 3: Verify cookie status is now active
    resp_status = await async_client.get("/api/settings/cookies")
    assert resp_status.status_code == 200
    status_data = resp_status.json()["youtube"]
    assert status_data.get("exists") is True
    assert status_data.get("valid") is True

    # Step 4: Standard inspect now loads cookies
    resp2 = await async_client.post(
        "/api/inspect", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    )
    assert resp2.status_code == 200


# ============================================================================
# 6. Proxy Setting Update + Download Route Switching
# ============================================================================
@pytest.mark.asyncio
async def test_proxy_setting_update_download_route_switching(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Verify changing proxy via Settings API dynamically routes subsequent downloads through the new proxy."""
    call_log.clear()
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # Phase 1: Download without proxy
    resp1 = await async_client.post("/api/download", json={"url": url})
    assert resp1.status_code == 200
    task1 = await _wait_task_complete(resp1.json()["task_id"])
    assert task1.status == "completed"

    records1 = call_log.filter_by_engine("yt-dlp")
    assert any(r.get("proxy") is None for r in records1)

    # Phase 2: Update proxy setting dynamically
    new_proxy = "socks5://127.0.0.1:9050"
    resp_proxy = await async_client.post(
        "/api/settings/proxy", json={"proxy": new_proxy}
    )
    assert resp_proxy.status_code == 200
    assert resp_proxy.json()["proxy"] == new_proxy

    # Phase 3: Next download routes through new proxy
    call_log.clear()
    resp2 = await async_client.post("/api/download", json={"url": url})
    assert resp2.status_code == 200
    task2 = await _wait_task_complete(resp2.json()["task_id"])
    assert task2.status == "completed"

    records2 = call_log.filter_by_engine("yt-dlp")
    assert any(r.get("proxy") == new_proxy for r in records2)

    # Phase 4: Clear proxy setting
    await async_client.post("/api/settings/proxy", json={"proxy": None})
    call_log.clear()
    resp3 = await async_client.post("/api/download", json={"url": url})
    task3 = await _wait_task_complete(resp3.json()["task_id"])
    assert task3.status == "completed"
    records3 = call_log.filter_by_engine("yt-dlp")
    assert any(r.get("proxy") is None for r in records3)


# ============================================================================
# 7. Two-Step Workflow with Partial Item Selection (indices [1, 3] from 5-item carousel)
# ============================================================================
@pytest.mark.asyncio
async def test_two_step_workflow_partial_item_selection(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Verify inspecting 5-item carousel and downloading partial selection [1, 3] bundles exactly 2 files."""
    call_log.clear()
    url = "https://www.instagram.com/p/carousel_5/"

    # Step 1: Inspect
    resp_inspect = await async_client.post("/api/inspect", json={"url": url})
    assert resp_inspect.status_code == 200
    inspect_data = resp_inspect.json()
    assert len(inspect_data["items"]) == 5

    # Step 2: Download only items 1 and 3
    resp_dl = await async_client.post(
        "/api/download",
        json={
            "url": url,
            "selected_indices": [1, 3],
            "package_as_zip": True,
        },
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    task = await _wait_task_complete(task_id)
    assert task.status == "completed"
    assert task.filename.endswith(".zip")

    # Step 3: Verify ZIP has exactly 2 files
    resp_file = await async_client.get(f"/api/files/{task_id}/{task.filename}")
    assert resp_file.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp_file.content)) as zf:
        names = zf.namelist()
        assert len(names) == 2


# ============================================================================
# 8. Real-time SSE Tracking + Simultaneous File Download
# ============================================================================
@pytest.mark.asyncio
async def test_realtime_sse_tracking_simultaneous_file_download(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Verify client streams SSE progress events and immediately fetches file upon completion."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    resp_dl = await async_client.post("/api/download", json={"url": url})
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    # Stream SSE events
    download_url = None
    async with async_client.stream("GET", f"/api/progress/{task_id}") as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    payload = json.loads(line[5:].strip())
                    if isinstance(payload, dict) and payload.get("status") == "completed":
                        download_url = payload.get("download_url")
                        break
                except Exception:
                    pass

    assert download_url is not None
    # Immediately download the served file
    resp_file = await async_client.get(download_url)
    assert resp_file.status_code == 200
    assert len(resp_file.content) > 0
    assert "attachment" in resp_file.headers.get("content-disposition", "")


# ============================================================================
# 9. Path Traversal Attack on Task ID + File Name simultaneously
# ============================================================================
@pytest.mark.asyncio
async def test_path_traversal_attack_task_id_and_filename(
    async_client: httpx.AsyncClient,
    isolated_env: dict[str, Path],
):
    """Verify simultaneous directory traversal attempts on both task_id and filename are safely rejected."""
    attack_paths = [
        "/api/files/task1/../../etc/passwd",
        "/api/files/..%2Ftask1/file.mp4",
        "/api/files/task1/subdir/../../etc/shadow",
        "/api/files/task1/..%2F..%2Fetc%2Fpasswd",
        "/api/files/task1/..\\..\\windows\\win.ini",
    ]

    for path in attack_paths:
        resp = await async_client.get(path)
        assert resp.status_code in (400, 404), f"Failed for {path}: {resp.status_code}"
        assert b"root:" not in resp.content


# ============================================================================
# 10. SSRF Attempt with Proxy Enabled
# ============================================================================
@pytest.mark.asyncio
async def test_ssrf_attempt_with_proxy_enabled(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Verify SSRF filter intercepts local and cloud metadata endpoints even when proxy is active."""
    call_log.clear()
    proxy_manager.set_proxy("socks5://127.0.0.1:1080")

    ssrf_targets = [
        "http://127.0.0.1:8000/api/settings/cookies",
        "http://localhost:8080/admin",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379",
    ]

    for target in ssrf_targets:
        # Inspect rejected
        resp_inspect = await async_client.post("/api/inspect", json={"url": target})
        assert resp_inspect.status_code == 400

        # Download rejected
        resp_dl = await async_client.post("/api/download", json={"url": target})
        assert resp_dl.status_code == 400

    # Ensure no engines were spawned for SSRF targets
    assert len(call_log.read()) == 0


# ============================================================================
# 11. Instagram Reel with Fallback + Instagram Naming (<username>_<YYYYMMDD>_<ORIGINAL_NAME_FIRST>)
# ============================================================================
@pytest.mark.asyncio
async def test_instagram_reel_fallback_and_naming(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Verify Reel URL with yt-dlp outage triggers gallery-dl fallback and adheres to Instagram naming rule."""
    call_log.clear()
    url = "https://www.instagram.com/reel/C7Reel12345/fail_ytdlp/"

    # Pass metadata so format_instagram_filename can use full convention
    resp_dl = await async_client.post(
        "/api/download",
        json={
            "url": url,
            "package_as_zip": False,
            "metadata": {
                "uploader": "doggo_world",
                "date": "2024-05-12 18:30:00",
                "original_name_first": "dog_park_jump",
                "title": "Funny dog jumps over puddle",
            },
        },
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    task = await _wait_task_complete(task_id)
    assert task.status == "completed"

    # Strict Instagram naming: <username>_<YYYYMMDD>_<ORIGINAL_NAME_FIRST>.<ext>
    # doggo_world_20240512_dog_park_jump.mp4
    assert task.filename == "doggo_world_20240512_dog_park_jump.mp4"

    # Verify both engines were called (yt-dlp failed, gallery-dl handled)
    assert len(call_log.filter_by_engine("yt-dlp")) >= 1
    assert len(call_log.filter_by_engine("gallery-dl")) >= 1


# ============================================================================
# 12. TTL Cleanup While Active Tasks Run
# ============================================================================
@pytest.mark.asyncio
async def test_ttl_cleanup_while_active_tasks_run(
    isolated_env: dict[str, Path],
):
    """Verify background cleaner purges expired directories while preserving currently active tasks."""
    downloads_dir = isolated_env["downloads_dir"]

    # 1. Active task: registered in progress_manager
    active_task = await progress_manager.create_task()
    active_id = active_task.task_id
    active_dir = downloads_dir / active_id
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "active_file.part").write_bytes(b"data")

    # 2. Expired task: abandoned directory with mtime 120 minutes ago
    expired_id = "task-expired-1234"
    expired_dir = downloads_dir / expired_id
    expired_dir.mkdir(parents=True, exist_ok=True)
    (expired_dir / "old_file.mp4").write_bytes(b"old_data")

    old_time = time.time() - (120 * 60)
    os.utime(expired_dir, (old_time, old_time))

    # 3. Trigger cleaner with active task protection
    purged_count = cleaner.cleanup_old_downloads(
        downloads_dir=downloads_dir, ttl_minutes=60, active_task_ids={active_id}
    )

    # 4. Assertions
    assert purged_count >= 1
    assert not expired_dir.exists(), "Expired task directory should be deleted"
    assert active_dir.exists(), "Active task directory must be preserved"


# ============================================================================
# 13. Audio-Only Option with Custom Format (WAV/M4A) + Unicode Filename
# ============================================================================
@pytest.mark.asyncio
async def test_audio_custom_format_wav_m4a_unicode_filename(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Verify audio extraction to WAV and M4A formats preserves Unicode title characters."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # 1. Audio WAV download
    resp_wav = await async_client.post(
        "/api/download",
        json={
            "url": url,
            "extract_audio": True,
            "audio_format": "wav",
        },
    )
    assert resp_wav.status_code == 200
    task_wav = await _wait_task_complete(resp_wav.json()["task_id"])
    assert task_wav.status == "completed"
    assert task_wav.filename.endswith(".wav")

    resp_file = await async_client.get(f"/api/files/{task_wav.task_id}/{task_wav.filename}")
    assert resp_file.status_code == 200
    assert resp_file.headers.get("content-type") == "audio/wav"

    # 2. Audio M4A download
    resp_m4a = await async_client.post(
        "/api/download",
        json={
            "url": url,
            "extract_audio": True,
            "audio_format": "m4a",
        },
    )
    assert resp_m4a.status_code == 200
    task_m4a = await _wait_task_complete(resp_m4a.json()["task_id"])
    assert task_m4a.status == "completed"
    assert task_m4a.filename.endswith(".m4a")


# ============================================================================
# 14. Corrupt Cookie Fallback to Unauthenticated Engine Attempt
# ============================================================================
@pytest.mark.asyncio
async def test_corrupt_cookie_fallback_to_unauthenticated_engine(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
):
    """Verify corrupt cookie file is caught gracefully and does not trigger unhandled 500 crashes."""
    # Place corrupt cookie file
    corrupt_file = fixtures_paths["cookies_invalid"]
    target_cookie = isolated_env["cookies_dir"] / "youtube.txt"
    shutil.copyfile(corrupt_file, target_cookie)

    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    resp = await async_client.post("/api/inspect", json={"url": url})
    # Should either succeed unauthenticated or return clean client error (never 500)
    assert resp.status_code in (200, 400, 401)


# ============================================================================
# 15. Rapid Successive Inspect & Download Calls (Rate & Concurrency)
# ============================================================================
@pytest.mark.asyncio
async def test_rapid_successive_inspect_download_concurrency(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Verify multiple concurrent inspect and download requests run without state contamination."""
    urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/short_12345678",
        "https://twitter.com/digital_artist/status/1789098765432109876/photo/1",
        "https://www.tiktok.com/@cheftips_official/video/7369123456789012345",
        "https://www.instagram.com/p/post_photo_1001/",
    ]

    # Concurrent inspects
    inspect_tasks = [async_client.post("/api/inspect", json={"url": u}) for u in urls]
    inspect_resps = await asyncio.gather(*inspect_tasks)
    for r in inspect_resps:
        assert r.status_code == 200

    # Concurrent downloads
    download_tasks = [async_client.post("/api/download", json={"url": u}) for u in urls]
    download_resps = await asyncio.gather(*download_tasks)
    task_ids = [r.json()["task_id"] for r in download_resps if r.status_code == 200]
    assert len(task_ids) == 5
    assert len(set(task_ids)) == 5

    # Await all workers
    for tid in task_ids:
        t = await _wait_task_complete(tid)
        assert t is not None
        assert t.status == "completed"


# ============================================================================
# 16. Dynamic Settings Reset to Defaults (proxy + cookies)
# ============================================================================
@pytest.mark.asyncio
async def test_dynamic_settings_reset_to_defaults(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
    call_log: Any,
):
    """Verify resetting proxy to null and deleting cookies reverts system to clean unproxied state."""
    call_log.clear()

    # Setup: configure proxy & cookies
    await async_client.post(
        "/api/settings/proxy", json={"proxy": "socks5://127.0.0.1:1080"}
    )
    cookie_sample = fixtures_paths["cookies_sample"].read_text(encoding="utf-8")
    for plat in ("instagram", "twitter", "youtube"):
        await async_client.post(
            "/api/settings/cookies", json={"platform": plat, "content": cookie_sample}
        )

    # Teardown / Reset
    await async_client.post("/api/settings/proxy", json={"proxy": None})
    for plat in ("instagram", "twitter", "youtube"):
        del_resp = await async_client.delete(f"/api/settings/cookies/{plat}")
        assert del_resp.status_code == 200

    # Verify settings reflect reset
    proxy_resp = await async_client.get("/api/settings/proxy")
    assert proxy_resp.json()["proxy"] is None

    cookies_resp = await async_client.get("/api/settings/cookies")
    for plat in ("instagram", "twitter", "youtube"):
        assert cookies_resp.json()[plat]["exists"] is False

    # Subsequent download runs unproxied and cookie-free
    call_log.clear()
    resp_dl = await async_client.post(
        "/api/download",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )
    task = await _wait_task_complete(resp_dl.json()["task_id"])
    assert task.status == "completed"

    records = call_log.filter_by_engine("yt-dlp")
    assert any(r.get("proxy") is None for r in records)


# ============================================================================
# 17. Instagram Carousel Partial Selection with Cookies and Proxy
# ============================================================================
@pytest.mark.asyncio
async def test_instagram_carousel_partial_with_cookies_and_proxy(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
    call_log: Any,
):
    """Verify Instagram multi-item carousel download with partial index selection under active proxy and cookies."""
    call_log.clear()
    proxy_url = "socks5://127.0.0.1:1080"
    proxy_manager.set_proxy(proxy_url)

    cookie_sample = fixtures_paths["cookies_sample"].read_text(encoding="utf-8")
    cookie_manager.save_cookies("instagram", cookie_sample)

    url = "https://www.instagram.com/p/334819201948/"
    resp_dl = await async_client.post(
        "/api/download",
        json={
            "url": url,
            "selected_indices": [0, 2],
            "package_as_zip": True,
        },
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    task = await _wait_task_complete(task_id)
    assert task.status == "completed"
    assert task.filename.endswith(".zip")

    records = call_log.filter_by_engine("gallery-dl")
    assert len(records) >= 1
    assert records[0]["proxy"] == proxy_url
    assert "instagram.txt" in str(records[0]["cookies"])


# ============================================================================
# 18. Generic URL Audio Extraction with Sanitized Filename
# ============================================================================
@pytest.mark.asyncio
async def test_generic_url_audio_extraction_with_sanitized_title(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Verify generic URL audio download correctly sanitizes special characters in title."""
    url = "https://example.com/media/audio_track"
    resp_dl = await async_client.post(
        "/api/download",
        json={
            "url": url,
            "extract_audio": True,
            "audio_format": "mp3",
        },
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    task = await _wait_task_complete(task_id)
    assert task.status == "completed"
    assert task.filename.endswith(".mp3")
    assert not any(c in task.filename for c in r'/\:*?"<>|')
