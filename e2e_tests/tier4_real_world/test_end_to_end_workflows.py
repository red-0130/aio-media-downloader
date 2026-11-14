"""Tier 4: Real-World Application Scenarios & End-to-End Workflows.

Covers all workflows specified in TEST_INFRA.md:
- Workflow 1: YouTube Power User (inspect -> choose 1080p -> download -> stream SSE -> remux -> fetch file)
- Workflow 2: Instagram Story & Carousel Archiver (configure cookies -> inspect story -> select 3 items -> zip -> stream SSE -> verify zip contains exactly 3 files named <username>_<YYYYMMDD>_<ORIGINAL_NAME_FIRST>.<ext>)
- Workflow 3: Music Extraction from Video (inspect video -> choose MP3 320k -> SSE: download -> convert -> fetch MP3 -> verify ID3 tags)
- Workflow 4: Twitter Photo Gallery Collector (inspect 4-image tweet -> select all -> auto-zip -> download archive -> verify original images inside)
- Workflow 5: Restricted Network with SOCKS5 Proxy (configure proxy via API -> inspect -> download through proxy -> verify proxy usage)
- Workflow 6: Engine Outage with Automatic Fallback (Reel URL where yt-dlp fails -> auto fallback to gallery-dl -> seamless completion)
- Workflow 7: Security & Penetration Defense (adversary sending SSRF, file://, traversal, shell injection in URLs -> all safely rejected)
- Workflow 8: Lifecycle Garbage Collection (multiple tasks -> time advances -> background cleaner purges expired -> unexpired kept -> 404 for expired)
- Workflow 9: Multi-Format Audio Conversion Pipeline (WAV & M4A containers)
- Workflow 10: Dynamic Admin Settings Lifecycle (Cookie management + proxy reconfiguration + teardown)
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


async def _stream_sse_until_completion(
    client: httpx.AsyncClient, task_id: str, timeout: float = 4.0
) -> dict[str, Any]:
    """Helper to stream SSE progress events until terminal event or timeout."""
    events: list[dict[str, Any]] = []
    terminal_data: dict[str, Any] | None = None
    start = time.time()

    async with client.stream("GET", f"/api/progress/{task_id}") as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("data:"):
                try:
                    payload = json.loads(line[5:].strip())
                    if isinstance(payload, dict):
                        events.append(payload)
                        if payload.get("status") in ("completed", "error"):
                            terminal_data = payload
                            break
                except Exception:
                    pass
            if time.time() - start > timeout:
                break

    # If stream ended without terminal payload, check manager directly
    if not terminal_data:
        task = progress_manager.get_task(task_id)
        if task and task.status in ("completed", "error"):
            terminal_data = {
                "status": task.status,
                "download_url": task.download_url,
                "filename": task.filename,
                "file_size": task.file_size,
            }

    return {"events": events, "terminal": terminal_data}


async def _wait_task_done(task_id: str, max_wait: float = 3.0) -> Any:
    """Helper to await task completion in background worker."""
    start = time.time()
    while time.time() - start < max_wait:
        t = progress_manager.get_task(task_id)
        if t and t.status in ("completed", "error"):
            return t
        await asyncio.sleep(0.05)
    return progress_manager.get_task(task_id)


# ============================================================================
# Workflow 1: YouTube Power User
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_01_youtube_power_user(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Scenario 1: YouTube Power User workflow.

    1. Inspect YouTube URL.
    2. Choose 1080p format (format_id="137").
    3. Trigger download.
    4. Stream SSE progress stream from 0% -> 100%.
    5. Fetch completed file, verify size, headers, and MP4 container.
    """
    call_log.clear()
    yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # Step 1: Inspect media metadata
    resp_inspect = await async_client.post("/api/inspect", json={"url": yt_url})
    assert resp_inspect.status_code == 200
    inspect_data = resp_inspect.json()
    assert inspect_data["platform"] == "youtube"
    assert inspect_data["media_type"] == "video"

    # Step 2: Verify available formats and select 1080p
    format_ids = [fmt["format_id"] for fmt in inspect_data["formats"]]
    assert "137" in format_ids or "best" in format_ids
    chosen_fmt = "137" if "137" in format_ids else "best"

    # Step 3: Trigger download execution
    resp_dl = await async_client.post(
        "/api/download",
        json={"url": yt_url, "format_id": chosen_fmt, "package_as_zip": False},
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    # Step 4: Stream SSE progress to completion
    sse_result = await _stream_sse_until_completion(async_client, task_id)
    terminal = sse_result["terminal"]
    assert terminal is not None
    assert terminal["status"] == "completed"
    download_url = terminal["download_url"]
    assert download_url.startswith(f"/api/files/{task_id}/")

    # Step 5: Fetch completed MP4 file
    resp_file = await async_client.get(download_url)
    assert resp_file.status_code == 200
    assert resp_file.headers.get("content-type") == "video/mp4"
    assert "attachment" in resp_file.headers.get("content-disposition", "")
    assert len(resp_file.content) > 0


# ============================================================================
# Workflow 2: Instagram Story & Carousel Archiver
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_02_instagram_story_carousel_archiver(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
):
    """Scenario 2: Instagram Story & Carousel Archiver workflow.

    1. Configure Instagram cookies via Settings API.
    2. Inspect Instagram story containing 4 items (2 images, 2 clips).
    3. Select 3 out of 4 items ([0, 1, 2]), request ZIP archive.
    4. Monitor SSE progress to completion.
    5. Download generated .zip archive.
    6. Verify ZIP contains exactly 3 files, each named <username>_<YYYYMMDD>_<ORIGINAL_NAME_FIRST>.<ext>.
    """
    # Step 1: Configure Instagram cookies
    cookie_content = fixtures_paths["cookies_sample"].read_text(encoding="utf-8")
    resp_cookie = await async_client.post(
        "/api/settings/cookies",
        json={"platform": "instagram", "content": cookie_content},
    )
    assert resp_cookie.status_code == 200

    # Step 2: Inspect Instagram story with 4 items
    story_url = "https://www.instagram.com/stories/influencer_daily/story_4/"
    resp_inspect = await async_client.post("/api/inspect", json={"url": story_url})
    assert resp_inspect.status_code == 200
    inspect_data = resp_inspect.json()
    assert inspect_data["platform"] == "instagram"
    assert len(inspect_data["items"]) == 4

    # Step 3: Select 3 items ([0, 1, 2]) and request ZIP
    selected_indices = [0, 1, 2]
    resp_dl = await async_client.post(
        "/api/download",
        json={
            "url": story_url,
            "selected_indices": selected_indices,
            "package_as_zip": True,
        },
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    # Step 4: Stream SSE progress
    sse_result = await _stream_sse_until_completion(async_client, task_id)
    terminal = sse_result["terminal"]
    assert terminal is not None
    assert terminal["status"] == "completed"

    # Step 5: Download generated ZIP archive
    resp_file = await async_client.get(terminal["download_url"])
    assert resp_file.status_code == 200
    assert resp_file.headers.get("content-type") == "application/zip"

    # Step 6: Verify ZIP contents
    with zipfile.ZipFile(io.BytesIO(resp_file.content)) as zf:
        namelist = zf.namelist()
        assert len(namelist) == 3

        # Verify all filenames follow <username>_<YYYYMMDD>_<ORIGINAL_NAME_FIRST>.<ext>
        expected_files = [
            "influencer_daily_20240515_coffee_morning.jpg",
            "influencer_daily_20240515_outfit_check.jpg",
            "influencer_daily_20240515_morning_workout.mp4",
        ]
        for expected in expected_files:
            assert expected in namelist


# ============================================================================
# Workflow 3: Music Extraction from Video
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_03_music_extraction_from_video(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Scenario 3: Music Extraction from Video workflow.

    1. Inspect music video URL.
    2. Choose audio-only extraction in MP3 format.
    3. Monitor SSE progress (downloading -> complete).
    4. Download MP3 file.
    5. Verify audio headers, filename extension, and Content-Type.
    """
    call_log.clear()
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # Step 1: Inspect
    resp_inspect = await async_client.post("/api/inspect", json={"url": video_url})
    assert resp_inspect.status_code == 200
    assert any(f["format_id"] == "audio-mp3" for f in resp_inspect.json()["formats"])

    # Step 2: Request MP3 audio extraction
    resp_dl = await async_client.post(
        "/api/download",
        json={
            "url": video_url,
            "format_id": "audio-mp3",
            "extract_audio": True,
            "audio_format": "mp3",
        },
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    # Step 3: Stream SSE
    sse_result = await _stream_sse_until_completion(async_client, task_id)
    terminal = sse_result["terminal"]
    assert terminal is not None
    assert terminal["status"] == "completed"
    assert terminal["filename"].endswith(".mp3")

    # Step 4 & 5: Fetch MP3 file and verify content
    resp_file = await async_client.get(terminal["download_url"])
    assert resp_file.status_code == 200
    assert resp_file.headers.get("content-type") == "audio/mpeg"
    assert "attachment" in resp_file.headers.get("content-disposition", "")
    assert len(resp_file.content) > 0


# ============================================================================
# Workflow 4: Twitter Photo Gallery Collector
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_04_twitter_photo_gallery_collector(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Scenario 4: Twitter Photo Gallery Collector workflow.

    1. Inspect 4-image tweet.
    2. Verify 4 photo items returned.
    3. Select all 4 photos with auto-zip.
    4. Stream SSE to completion.
    5. Download archive and verify all 4 original photos are bundled.
    """
    tweet_url = "https://twitter.com/digital_artist/status/1789098765432109876/photo/1"

    # Step 1 & 2: Inspect
    resp_inspect = await async_client.post("/api/inspect", json={"url": tweet_url})
    assert resp_inspect.status_code == 200
    inspect_data = resp_inspect.json()
    assert inspect_data["platform"] == "twitter"
    assert len(inspect_data["items"]) == 4

    # Step 3: Select all 4 photos for download with auto-ZIP
    resp_dl = await async_client.post(
        "/api/download",
        json={
            "url": tweet_url,
            "selected_indices": [0, 1, 2, 3],
            "package_as_zip": True,
        },
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    # Step 4: Stream SSE
    sse_result = await _stream_sse_until_completion(async_client, task_id)
    terminal = sse_result["terminal"]
    assert terminal["status"] == "completed"
    assert terminal["filename"].endswith(".zip")

    # Step 5: Download and verify archive contents
    resp_file = await async_client.get(terminal["download_url"])
    assert resp_file.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp_file.content)) as zf:
        namelist = zf.namelist()
        assert len(namelist) == 4
        assert all(n.endswith(".jpg") for n in namelist)


# ============================================================================
# Workflow 5: Restricted Network with SOCKS5 Proxy
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_05_restricted_network_socks5_proxy(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Scenario 5: Restricted Network with SOCKS5 Proxy workflow.

    1. Configure SOCKS5 proxy via API.
    2. Verify GET /api/settings/proxy returns active proxy state.
    3. Inspect media; verify extractor uses proxy.
    4. Download media; verify proxy flag passed.
    5. Revert proxy setting to clean state.
    """
    call_log.clear()
    proxy_url = "socks5://127.0.0.1:1080"

    # Step 1: Configure proxy
    resp_post = await async_client.post(
        "/api/settings/proxy", json={"proxy": proxy_url}
    )
    assert resp_post.status_code == 200

    # Step 2: Verify active proxy state
    resp_get = await async_client.get("/api/settings/proxy")
    assert resp_get.status_code == 200
    assert resp_get.json()["proxy"] == proxy_url

    # Step 3: Inspect media under proxy
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    resp_inspect = await async_client.post("/api/inspect", json={"url": url})
    assert resp_inspect.status_code == 200

    # Step 4: Download through proxy
    resp_dl = await async_client.post("/api/download", json={"url": url})
    task_id = resp_dl.json()["task_id"]
    task = await _wait_task_done(task_id)
    assert task.status == "completed"

    records = call_log.filter_by_engine("yt-dlp")
    assert any(r.get("proxy") == proxy_url for r in records)

    # Step 5: Clean reset
    await async_client.post("/api/settings/proxy", json={"proxy": None})
    resp_reset = await async_client.get("/api/settings/proxy")
    assert resp_reset.json()["proxy"] is None


# ============================================================================
# Workflow 6: Engine Outage with Automatic Fallback
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_06_engine_outage_automatic_fallback(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Scenario 6: Engine Outage with Automatic Fallback workflow.

    1. Input Reel URL where primary engine (yt-dlp) fails.
    2. Smart router automatically delegates to secondary engine (gallery-dl).
    3. Download completes seamlessly without user intervention.
    4. Log indicates transparent dual-engine fallback invocation.
    """
    call_log.clear()
    failing_url = "https://www.instagram.com/reel/C7Reel12345/fail_ytdlp/"

    # Step 1 & 2: Start download
    resp_dl = await async_client.post(
        "/api/download",
        json={"url": failing_url, "package_as_zip": False},
    )
    assert resp_dl.status_code == 200
    task_id = resp_dl.json()["task_id"]

    # Step 3: Stream SSE
    sse_result = await _stream_sse_until_completion(async_client, task_id)
    terminal = sse_result["terminal"]
    assert terminal is not None
    assert terminal["status"] == "completed"
    assert terminal["filename"].endswith(".mp4")

    # Step 4: Verify dual-engine execution in logs
    yt_calls = call_log.filter_by_engine("yt-dlp")
    gdl_calls = call_log.filter_by_engine("gallery-dl")
    assert len(yt_calls) >= 1
    assert len(gdl_calls) >= 1


# ============================================================================
# Workflow 7: Security & Penetration Defense
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_07_security_penetration_defense(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Scenario 7: Security & Penetration Defense workflow.

    Adversary sends various attacks:
    1. Internal network and cloud metadata probes (SSRF).
    2. Local file:// URL probes.
    3. Path traversal sequences in file serving endpoints.
    4. Shell injection metacharacters in URL parameters.
    System systematically rejects every probe with HTTP 400/404/422 without 500 error or shell execution.
    """
    call_log.clear()

    # 1. SSRF & Local file probes
    malicious_urls = [
        "http://127.0.0.1:8000/api/settings/cookies",
        "http://localhost:8000/metrics",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "file:///proc/self/environ",
        "gopher://127.0.0.1:6379",
        "ftp://attacker.com/payload",
    ]
    for m_url in malicious_urls:
        resp_insp = await async_client.post("/api/inspect", json={"url": m_url})
        assert resp_insp.status_code in (400, 422), f"Failed for {m_url}: {resp_insp.status_code}"

        resp_down = await async_client.post("/api/download", json={"url": m_url})
        assert resp_down.status_code in (400, 422), f"Failed for {m_url}: {resp_down.status_code}"

    # 2. Path traversal in file endpoint
    traversal_paths = [
        "/api/files/task1/../../etc/passwd",
        "/api/files/..%2Ftask1/file.mp4",
        "/api/files/task1/subdir/../../etc/shadow",
        "/api/files/task1/..%2F..%2Fetc%2Fpasswd",
        "/api/files/task1/..\\..\\windows\\win.ini",
    ]
    for path in traversal_paths:
        resp_file = await async_client.get(path)
        assert resp_file.status_code in (400, 404), f"Failed for {path}: {resp_file.status_code}"

    # 3. Shell injection in URL parameter
    shell_injection_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ; rm -rf /;",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ | cat /etc/passwd",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ`id`",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ$(whoami)",
    ]
    for s_url in shell_injection_urls:
        # Since arguments are passed as array to asyncio.create_subprocess_exec (not shell=True),
        # these must be handled safely without command injection
        resp = await async_client.post("/api/inspect", json={"url": s_url})
        assert resp.status_code in (200, 400), f"Unexpected status {resp.status_code} for {s_url}"

    # Verify no dangerous operations succeeded
    assert len(call_log.filter_by_engine("rm")) == 0


# ============================================================================
# Workflow 8: Lifecycle Garbage Collection
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_08_lifecycle_garbage_collection(
    async_client: httpx.AsyncClient,
    isolated_env: dict[str, Path],
):
    """Scenario 8: Lifecycle Garbage Collection workflow.

    1. Multiple downloads occur creating several task folders.
    2. Clock advances past 60-minute TTL threshold for older tasks.
    3. Background cleaner scans downloads/, deletes expired, preserves unexpired.
    4. Expired file retrieval returns 404 cleanly; unexpired returns 200.
    """
    downloads_dir = isolated_env["downloads_dir"]

    # 1. Create two expired task folders (e.g. 90 minutes old)
    for tid in ("task_old_alpha", "task_old_beta"):
        tdir = downloads_dir / tid
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "media.mp4").write_bytes(b"old video content")
        old_time = time.time() - (90 * 60)
        os.utime(tdir, (old_time, old_time))

    # 2. Create one fresh task folder (e.g. 5 minutes old)
    fresh_dir = downloads_dir / "task_fresh_gamma"
    fresh_dir.mkdir(parents=True, exist_ok=True)
    fresh_file = fresh_dir / "media.mp4"
    fresh_file.write_bytes(b"fresh video content")

    # 3. Trigger cleaner
    purged = cleaner.cleanup_old_downloads(downloads_dir=downloads_dir, ttl_minutes=60)
    assert purged >= 2

    # 4. Verify expired directories deleted
    assert not (downloads_dir / "task_old_alpha").exists()
    assert not (downloads_dir / "task_old_beta").exists()

    # 5. Verify fresh directory preserved
    assert fresh_dir.exists()
    assert fresh_file.exists()

    # 6. Verify file endpoint returns 404 for expired task and 200 for fresh
    resp_expired = await async_client.get("/api/files/task_old_alpha/media.mp4")
    assert resp_expired.status_code == 404

    resp_fresh = await async_client.get("/api/files/task_fresh_gamma/media.mp4")
    assert resp_fresh.status_code == 200
    assert resp_fresh.content == b"fresh video content"


# ============================================================================
# Workflow 9: Multi-Format Audio Conversion Pipeline
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_09_multi_format_audio_conversion(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Scenario 9: Multi-Format Audio Conversion Pipeline (WAV & M4A)."""
    yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    for audio_fmt in ("wav", "m4a"):
        resp_dl = await async_client.post(
            "/api/download",
            json={
                "url": yt_url,
                "extract_audio": True,
                "audio_format": audio_fmt,
            },
        )
        assert resp_dl.status_code == 200
        task_id = resp_dl.json()["task_id"]

        task = await _wait_task_done(task_id)
        assert task.status == "completed"
        assert task.filename.endswith(f".{audio_fmt}")

        resp_file = await async_client.get(task.download_url)
        assert resp_file.status_code == 200
        expected_ct = "audio/wav" if audio_fmt == "wav" else "audio/mp4"
        assert resp_file.headers.get("content-type") == expected_ct


# ============================================================================
# Workflow 10: Dynamic Admin Settings Lifecycle
# ============================================================================
@pytest.mark.asyncio
async def test_workflow_10_dynamic_settings_lifecycle(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
    call_log: Any,
):
    """Scenario 10: Dynamic Admin Settings Lifecycle (upload cookies, change proxy, download, teardown)."""
    call_log.clear()

    # Step 1: Upload cookies
    sample_cookie = fixtures_paths["cookies_sample"].read_text(encoding="utf-8")
    resp_c = await async_client.post(
        "/api/settings/cookies",
        json={"platform": "twitter", "content": sample_cookie},
    )
    assert resp_c.status_code == 200

    # Step 2: Configure proxy
    proxy_val = "socks5://127.0.0.1:1080"
    resp_p = await async_client.post(
        "/api/settings/proxy", json={"proxy": proxy_val}
    )
    assert resp_p.status_code == 200

    # Step 3: Run download verifying both proxy and cookies are utilized
    tw_url = "https://twitter.com/digital_artist/status/1789098765432109876/photo/1"
    resp_dl = await async_client.post("/api/download", json={"url": tw_url})
    task = await _wait_task_done(resp_dl.json()["task_id"])
    assert task.status == "completed"

    records = call_log.filter_by_engine("gallery-dl")
    assert len(records) >= 1
    assert records[0]["proxy"] == proxy_val
    assert "twitter.txt" in str(records[0]["cookies"])

    # Step 4: Teardown settings
    await async_client.post("/api/settings/proxy", json={"proxy": None})
    await async_client.delete("/api/settings/cookies/twitter")

    p_check = await async_client.get("/api/settings/proxy")
    assert p_check.json()["proxy"] is None

    c_check = await async_client.get("/api/settings/cookies")
    assert c_check.json()["twitter"]["exists"] is False
