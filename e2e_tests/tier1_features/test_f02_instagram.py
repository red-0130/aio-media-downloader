"""Tier 1 Feature Coverage: F02 - Instagram Extraction & Routing."""

import shutil
from pathlib import Path
from typing import Any

import pytest

from app.models.download import DownloadRequest
from app.services import cookie_manager, router


@pytest.mark.asyncio
async def test_instagram_single_photo_post(mock_bin_path: Path):
    """Verify inspection of single Instagram photo post via gallery-dl."""
    url = "https://www.instagram.com/p/post_photo_1001/"
    res = await router.inspect(url)

    assert res.platform == "instagram"
    assert res.media_type == "image"
    assert res.id == "post_photo_1001"
    assert res.uploader == "nature_lens"
    assert len(res.items) == 1
    assert res.items[0].type == "image"
    assert res.items[0].index == 0


@pytest.mark.asyncio
async def test_instagram_reel_video_routing(mock_bin_path: Path, call_log: Any):
    """Verify Instagram Reel is routed to yt-dlp with video formats."""
    call_log.clear()
    url = "https://www.instagram.com/reel/C7Reel12345/"
    res = await router.inspect(url)

    assert res.platform == "instagram"
    assert res.media_type == "video"
    assert res.id == "C7Reel12345"
    assert res.uploader == "doggo_world"
    assert any(f.format_id == "best" for f in res.formats)

    records = call_log.filter_by_engine("yt-dlp")
    assert len(records) >= 1
    assert any("C7Reel12345" in (r.get("url") or "") for r in records)


@pytest.mark.asyncio
async def test_instagram_multi_item_carousel(mock_bin_path: Path):
    """Verify inspection of Instagram multi-item carousel returns items list with indices."""
    url = "https://www.instagram.com/p/334819201948/"
    res = await router.inspect(url)

    assert res.platform == "instagram"
    assert res.media_type == "carousel"
    assert len(res.items) == 3

    assert res.items[0].index == 0
    assert res.items[0].type == "image"

    assert res.items[1].index == 1
    assert res.items[1].type == "image"

    assert res.items[2].index == 2
    assert res.items[2].type == "video"


@pytest.mark.asyncio
async def test_instagram_story_with_cookies(
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
    call_log: Any,
):
    """Verify inspection of Instagram Story loads cookies and extracts slides."""
    call_log.clear()
    # Install valid cookies into isolated cookies directory
    sample_cookie = fixtures_paths["cookies_sample"]
    target_cookie = isolated_env["cookies_dir"] / "instagram.txt"
    shutil.copyfile(sample_cookie, target_cookie)

    url = "https://www.instagram.com/stories/influencer_daily/94821038/"
    res = await router.inspect(url)

    assert res.platform == "instagram"
    assert res.media_type == "story"
    assert len(res.items) == 2
    assert res.uploader == "influencer_daily"

    # Verify cookies flag passed in call log
    records = call_log.filter_by_engine("gallery-dl")
    assert len(records) >= 1
    assert records[0]["cookies"] == str(target_cookie)


@pytest.mark.asyncio
async def test_instagram_gallerydl_fallback_to_ytdlp(mock_bin_path: Path, call_log: Any):
    """Verify that when gallery-dl fails on an Instagram URL, router falls back to yt-dlp."""
    call_log.clear()
    # URL triggered to fail in gallery-dl
    url = "https://www.instagram.com/p/fail_gallerydl_ig_fallback/"
    res = await router.inspect(url)

    assert res.platform == "instagram"
    assert res.media_type in ("video", "image", "carousel")

    # Verify both gallery-dl and yt-dlp were logged
    gdl_records = call_log.filter_by_engine("gallery-dl")
    yt_records = call_log.filter_by_engine("yt-dlp")
    assert len(gdl_records) >= 1
    assert len(yt_records) >= 1


@pytest.mark.asyncio
async def test_instagram_carousel_download_bundle(
    mock_bin_path: Path, isolated_env: dict[str, Path]
):
    """Verify downloading an Instagram carousel bundles files into a ZIP archive."""
    url = "https://www.instagram.com/p/334819201948/"
    req = DownloadRequest(
        url=url,
        selected_indices=[0, 1],
        package_as_zip=True,
    )
    result = await router.download(task_id="task_ig_bundle", request=req)

    assert result.is_zip is True
    assert result.filename.endswith(".zip")
    assert Path(result.file_path).exists()
    assert result.file_size > 0
