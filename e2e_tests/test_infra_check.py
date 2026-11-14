"""Infra check test suite verifying mock binaries, proxy server, and E2E harness."""

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.models.download import DownloadRequest
from app.services import cookie_manager, gallerydl_service, router, ytdlp_service
from app.services.ytdlp_service import AuthRequiredError, ExtractionError, RateLimitError


def test_mock_bin_path_interception(mock_bin_path: Path):
    """Verify that mock_bin_path properly intercepts yt-dlp and gallery-dl CLI calls."""
    ytdlp_which = shutil.which("yt-dlp")
    gallerydl_which = shutil.which("gallery-dl")

    assert ytdlp_which is not None, "yt-dlp not found in PATH"
    assert gallerydl_which is not None, "gallery-dl not found in PATH"

    assert Path(ytdlp_which).resolve() == (mock_bin_path / "yt-dlp").resolve()
    assert Path(gallerydl_which).resolve() == (mock_bin_path / "gallery-dl").resolve()


@pytest.mark.asyncio
async def test_ytdlp_mock_inspect_all_media(mock_bin_path: Path, call_log: Any):
    """Verify yt-dlp mock inspection produces valid metadata and logs calls."""
    call_log.clear()

    # YouTube standard video
    data = await ytdlp_service.inspect_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert data["id"] == "dQw4w9WgXcQ"
    assert "Rick Astley" in data["title"]
    assert len(data["formats"]) >= 3

    # YouTube short
    short_data = await ytdlp_service.inspect_url("https://www.youtube.com/shorts/short_12345678")
    assert short_data["height"] == 1920
    assert short_data["width"] == 1080

    # YouTube playlist
    playlist_data = await ytdlp_service.inspect_url("https://www.youtube.com/playlist?list=PL_sample")
    assert "entries" in playlist_data
    assert len(playlist_data["entries"]) == 3

    # Verify call log recorded entries
    records = call_log.filter_by_engine("yt-dlp")
    assert len(records) == 3
    assert any("dQw4w9WgXcQ" in r["url"] for r in records)


@pytest.mark.asyncio
async def test_gallerydl_mock_inspect_all_media(mock_bin_path: Path, call_log: Any):
    """Verify gallery-dl mock inspection produces structured items list."""
    call_log.clear()

    # Instagram carousel
    items = await gallerydl_service.inspect_url("https://www.instagram.com/p/334819201948/")
    assert len(items) == 3
    assert items[0]["extension"] == "jpg"
    assert items[2]["extension"] == "mp4"

    # Instagram story
    story_items = await gallerydl_service.inspect_url(
        "https://www.instagram.com/stories/influencer_daily/94821038/"
    )
    assert len(story_items) == 2
    assert story_items[0]["user"] == "influencer_daily"

    # Twitter gallery
    twitter_items = await gallerydl_service.inspect_url(
        "https://twitter.com/digital_artist/status/1789098765432109876/photo/1"
    )
    assert len(twitter_items) == 4

    records = call_log.filter_by_engine("gallery-dl")
    assert len(records) == 3


@pytest.mark.asyncio
async def test_ytdlp_mock_download_and_progress(
    mock_bin_path: Path, isolated_env: dict[str, Path]
):
    """Verify yt-dlp download emits progress events and creates valid media file."""
    progress_updates: list[float] = []

    def on_progress(progress: float, **kwargs):
        progress_updates.append(progress)

    download_dir = isolated_env["downloads_dir"] / "task_ytdlp_1"
    files = await ytdlp_service.download_media(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        output_dir=download_dir,
        format_id="best",
        progress_callback=on_progress,
    )

    assert len(files) == 1
    downloaded_file = files[0]
    assert downloaded_file.exists()
    assert downloaded_file.suffix == ".mp4"
    assert downloaded_file.stat().st_size > 1000

    # Verify progress events streamed from 0 to 100%
    assert len(progress_updates) >= 4
    assert 100.0 in progress_updates


@pytest.mark.asyncio
async def test_gallerydl_mock_download_with_range(
    mock_bin_path: Path, isolated_env: dict[str, Path]
):
    """Verify gallery-dl download honors selected indices range."""
    progress_calls: list[str] = []

    def on_progress(progress: float, message: str = "", **kwargs):
        progress_calls.append(message)

    download_dir = isolated_env["downloads_dir"] / "task_gdl_1"
    # Select index 0 and 2 (items 1 and 3)
    files = await gallerydl_service.download_items(
        url="https://www.instagram.com/p/334819201948/",
        output_dir=download_dir,
        selected_indices=[0, 2],
        progress_callback=on_progress,
    )

    assert len(files) == 2
    extensions = {f.suffix for f in files}
    assert ".jpg" in extensions
    assert ".mp4" in extensions
    assert len(progress_calls) == 2


@pytest.mark.asyncio
async def test_mock_error_simulations(mock_bin_path: Path):
    """Verify mock binaries simulate auth errors, rate limits, and engine failures."""
    # Auth required trigger
    with pytest.raises(AuthRequiredError):
        await ytdlp_service.inspect_url("https://www.youtube.com/watch?v=auth_error_test")

    with pytest.raises(AuthRequiredError):
        await gallerydl_service.inspect_url("https://www.instagram.com/p/login_required_test/")

    # Rate limit trigger
    with pytest.raises(RateLimitError):
        await ytdlp_service.inspect_url("https://www.youtube.com/watch?v=rate_limit_test")

    with pytest.raises(RateLimitError):
        await gallerydl_service.inspect_url("https://www.instagram.com/p/rate_limit_test/")

    # Unsupported / fail engine trigger
    with pytest.raises(ExtractionError):
        await ytdlp_service.inspect_url("https://www.youtube.com/watch?v=fail_engine_test")

    with pytest.raises(ExtractionError):
        await gallerydl_service.inspect_url("https://www.instagram.com/p/fail_engine_test/")


@pytest.mark.asyncio
async def test_socks5_proxy_fixture_and_tracking(socks5_proxy: Any):
    """Verify SOCKS5 test proxy completes handshake and tracks destination targets."""
    assert socks5_proxy.port > 0
    assert socks5_proxy.connection_count == 0

    # Connect to proxy using raw asyncio socket
    reader, writer = await asyncio.open_connection("127.0.0.1", socks5_proxy.port)

    # 1. Negotiation handshake
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    resp = await reader.read(2)
    assert resp == b"\x05\x00"

    # 2. Connect command to target host
    # 5=VER, 1=CONNECT, 0=RSV, 3=DOMAIN, len=10 (google.com), port=443 (\x01\xbb)
    writer.write(b"\x05\x01\x00\x03\ngoogle.com\x01\xbb")
    await writer.drain()
    resp2 = await reader.read(10)
    assert resp2[:2] == b"\x05\x00"

    writer.close()
    await writer.wait_closed()

    assert socks5_proxy.connection_count == 1
    conn = socks5_proxy.get_connections()[0]
    assert conn["target_host"] == "google.com"
    assert conn["target_port"] == 443


@pytest.mark.asyncio
async def test_proxy_and_cookies_cli_injection(
    mock_bin_path: Path, fixtures_paths: dict[str, Path], call_log: Any
):
    """Verify proxy and cookies flags are injected into CLI subprocess calls."""
    call_log.clear()
    cookie_file = fixtures_paths["cookies_sample"]
    test_proxy = "socks5://127.0.0.1:9999"

    await ytdlp_service.inspect_url(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        proxy=test_proxy,
        cookies_path=cookie_file,
    )

    records = call_log.filter_by_engine("yt-dlp")
    assert len(records) == 1
    assert records[0]["proxy"] == test_proxy
    assert records[0]["cookies"] == str(cookie_file)


def test_fixture_files_integrity(fixtures_paths: dict[str, Path]):
    """Verify pre-built cookie and media fixture files are intact and valid."""
    # 1. Cookie fixtures
    valid_file = fixtures_paths["cookies_sample"]
    invalid_file = fixtures_paths["cookies_invalid"]
    expired_file = fixtures_paths["cookies_expired"]

    is_valid, count, _ = cookie_manager.verify_netscape_content(
        valid_file.read_text(encoding="utf-8")
    )
    assert is_valid is True
    assert count >= 6

    is_inv, _, _ = cookie_manager.verify_netscape_content(
        invalid_file.read_text(encoding="utf-8")
    )
    assert is_inv is False

    is_exp, _, _ = cookie_manager.verify_netscape_content(
        expired_file.read_text(encoding="utf-8")
    )
    assert is_exp is True

    # 2. Media fixtures
    assert fixtures_paths["sample_mp4"].exists()
    assert fixtures_paths["sample_mp4"].stat().st_size > 1000

    assert fixtures_paths["sample_mp3"].exists()
    assert fixtures_paths["sample_mp3"].stat().st_size > 1000

    assert fixtures_paths["sample_jpg"].exists()
    assert fixtures_paths["sample_jpg"].stat().st_size > 100


@pytest.mark.asyncio
async def test_async_client_and_live_server(
    async_client: httpx.AsyncClient, live_server: str
):
    """Verify ASGI client and live uvicorn server fixtures operate properly."""
    # Test ASGI client connection
    asgi_resp = await async_client.get("/")
    assert asgi_resp.status_code in (200, 404)

    # Test live server connection over real TCP wire
    async with httpx.AsyncClient() as client:
        live_resp = await client.get(live_server)
        assert live_resp.status_code in (200, 404)


@pytest.mark.asyncio
async def test_router_end_to_end_with_mocks(
    mock_bin_path: Path, isolated_env: dict[str, Path]
):
    """Verify router inspection and download function end-to-end through mock binaries."""
    # Router inspection of YouTube
    inspect_res = await router.inspect("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert inspect_res.platform == "youtube"
    assert inspect_res.media_type == "video"
    assert any(f.format_id == "best" for f in inspect_res.formats)

    # Router inspection of Instagram carousel
    ig_res = await router.inspect("https://www.instagram.com/p/334819201948/")
    assert ig_res.platform == "instagram"
    assert ig_res.media_type == "carousel"
    assert len(ig_res.items) == 3

    # Router download of multi-item carousel (auto-bundled into zip)
    dl_req = DownloadRequest(
        url="https://www.instagram.com/p/334819201948/",
        selected_indices=[0, 1],
        package_as_zip=True,
    )
    dl_res = await router.download(task_id="task_test_carousel", request=dl_req)
    assert dl_res.is_zip is True
    assert dl_res.filename.endswith(".zip")
    assert Path(dl_res.file_path).exists()
    assert Path(dl_res.file_path).stat().st_size > 100
