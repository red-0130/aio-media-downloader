"""Tier 1 Feature Coverage: F03 - Twitter/X & TikTok Extraction."""

from pathlib import Path
from typing import Any

import pytest

from app.models.download import DownloadRequest
from app.services import router


@pytest.mark.asyncio
async def test_twitter_video_extraction(mock_bin_path: Path):
    """Verify inspection of Twitter video extracts highest bitrate MP4 format."""
    url = "https://twitter.com/SpaceFlightNow/status/1789012345678901234/video/1"
    res = await router.inspect(url)

    assert res.platform == "twitter"
    assert res.media_type == "video"
    assert res.id == "1789012345678901234"
    assert res.uploader == "SpaceFlightNow"
    assert any(f.format_id == "best" for f in res.formats)

    best_fmt = next(f for f in res.formats if f.format_id == "best")
    assert best_fmt.ext == "mp4"


@pytest.mark.asyncio
async def test_twitter_multi_image_gallery(mock_bin_path: Path):
    """Verify inspection of Twitter multi-image post extracts image items."""
    url = "https://twitter.com/digital_artist/status/1789098765432109876/photo/1"
    res = await router.inspect(url)

    assert res.platform == "twitter"
    assert res.media_type == "carousel"
    assert len(res.items) == 4
    for idx, item in enumerate(res.items):
        assert item.index == idx
        assert item.type == "image"
        assert item.url is not None


@pytest.mark.asyncio
async def test_tiktok_video_watermark_free(mock_bin_path: Path):
    """Verify inspection of TikTok video extracts video stream."""
    url = "https://www.tiktok.com/@cheftips_official/video/7369123456789012345"
    res = await router.inspect(url)

    assert res.platform == "tiktok"
    assert res.media_type == "video"
    assert res.id == "7369123456789012345"
    assert res.uploader == "cheftips_official"
    assert any(f.format_id == "best" for f in res.formats)


@pytest.mark.asyncio
async def test_tiktok_photo_slideshow(mock_bin_path: Path):
    """Verify inspection of TikTok photo slideshow extracts individual images."""
    url = "https://www.tiktok.com/@travel_couple/photo/7369999888777666555"
    res = await router.inspect(url)

    assert res.platform == "tiktok"
    assert res.media_type == "carousel"
    assert len(res.items) == 3
    for idx, item in enumerate(res.items):
        assert item.index == idx
        assert item.type == "image"
        assert item.resolution == "1080x1920"


@pytest.mark.asyncio
async def test_twitter_engine_fallback(mock_bin_path: Path, call_log: Any):
    """Verify that when gallery-dl fails on Twitter, router falls back to yt-dlp."""
    call_log.clear()
    url = "https://twitter.com/user/status/fail_gallerydl_tweet_123"
    res = await router.inspect(url)

    assert res.platform == "twitter"
    assert res.media_type in ("video", "image", "carousel")

    records = call_log.filter_by_engine("yt-dlp")
    assert len(records) >= 1


@pytest.mark.asyncio
async def test_tiktok_download_execution(
    mock_bin_path: Path, isolated_env: dict[str, Path]
):
    """Verify downloading TikTok video produces valid local file."""
    url = "https://www.tiktok.com/@cheftips_official/video/7369123456789012345"
    req = DownloadRequest(url=url, format_id="best")
    res = await router.download(task_id="task_tiktok_dl", request=req)

    assert res.task_id == "task_tiktok_dl"
    assert res.filename.endswith(".mp4")
    assert Path(res.file_path).exists()
