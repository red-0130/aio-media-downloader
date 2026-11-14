"""Tier 1 Feature Coverage: F04 - Smart Fallback Router."""

from pathlib import Path
from typing import Any

import pytest

from app.models.download import DownloadRequest
from app.services import router
from app.services.ytdlp_service import (
    AuthRequiredError,
    ExtractionError,
    RateLimitError,
)


@pytest.mark.asyncio
async def test_primary_ytdlp_fails_fallback_gallerydl_succeeds(
    mock_bin_path: Path, call_log: Any
):
    """Verify that when primary engine yt-dlp fails, fallback engine gallery-dl executes."""
    call_log.clear()
    url = "https://www.tiktok.com/@user/video/fail_ytdlp_fallback"
    res = await router.inspect(url)

    assert res.platform == "tiktok"
    yt_records = call_log.filter_by_engine("yt-dlp")
    gdl_records = call_log.filter_by_engine("gallery-dl")

    assert len(yt_records) >= 1
    assert len(gdl_records) >= 1


@pytest.mark.asyncio
async def test_primary_gallerydl_fails_fallback_ytdlp_succeeds(
    mock_bin_path: Path, call_log: Any
):
    """Verify that when primary engine gallery-dl fails, fallback engine yt-dlp executes."""
    call_log.clear()
    url = "https://www.instagram.com/p/fail_gallerydl_fallback_test/"
    res = await router.inspect(url)

    assert res.platform == "instagram"
    gdl_records = call_log.filter_by_engine("gallery-dl")
    yt_records = call_log.filter_by_engine("yt-dlp")

    assert len(gdl_records) >= 1
    assert len(yt_records) >= 1


@pytest.mark.asyncio
async def test_dual_engine_failure_reports_descriptive_error(mock_bin_path: Path):
    """Verify that when both primary and fallback engines fail, ExtractionError is raised."""
    url = "https://www.youtube.com/watch?v=fail_engine_both_test"
    with pytest.raises(ExtractionError) as exc_info:
        await router.inspect(url)

    assert "Extraction failed" in str(exc_info.value) or "Unsupported" in str(exc_info.value)


@pytest.mark.asyncio
async def test_login_required_detection_and_suggestion(mock_bin_path: Path):
    """Verify login required output raises AuthRequiredError with cookie suggestion."""
    url = "https://www.youtube.com/watch?v=login_required_prompt_test"
    with pytest.raises(AuthRequiredError) as exc_info:
        await router.inspect(url)

    err_text = str(exc_info.value).lower()
    assert "cookie" in err_text or "authentication" in err_text or "settings" in err_text


@pytest.mark.asyncio
async def test_rate_limit_error_detection(mock_bin_path: Path):
    """Verify rate-limited output raises RateLimitError."""
    url = "https://www.youtube.com/watch?v=rate_limit_router_test"
    with pytest.raises(RateLimitError) as exc_info:
        await router.inspect(url)

    err_text = str(exc_info.value).lower()
    assert "rate limit" in err_text or "429" in err_text


@pytest.mark.asyncio
async def test_download_fallback_execution(
    mock_bin_path: Path, isolated_env: dict[str, Path]
):
    """Verify download execution automatically falls back when primary engine fails."""
    url = "https://www.instagram.com/p/fail_gallerydl_dl_test/"
    req = DownloadRequest(url=url, format_id="best")
    res = await router.download(task_id="task_fallback_dl", request=req)

    assert res.task_id == "task_fallback_dl"
    assert Path(res.file_path).exists()
