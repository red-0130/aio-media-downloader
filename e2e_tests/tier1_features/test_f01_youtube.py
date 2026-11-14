"""Tier 1 Feature Coverage: F01 - YouTube Extraction (yt-dlp)."""

from pathlib import Path
from typing import Any

import pytest

from app.models.download import DownloadRequest
from app.services import router, ytdlp_service


@pytest.mark.asyncio
async def test_youtube_standard_video_formats(mock_bin_path: Path):
    """Verify inspection of standard YouTube video returns resolutions, formats, and audio options."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    res = await router.inspect(url)

    assert res.platform == "youtube"
    assert res.media_type == "video"
    assert res.id == "dQw4w9WgXcQ"
    assert len(res.formats) >= 3

    # Format IDs and extensions
    format_ids = [f.format_id for f in res.formats]
    assert "best" in format_ids
    assert "audio-mp3" in format_ids

    # Best quality format
    best_fmt = next(f for f in res.formats if f.format_id == "best")
    assert best_fmt.ext == "mp4"
    assert best_fmt.label == "Original Quality"

    # Audio extraction format
    audio_fmt = next(f for f in res.formats if f.format_id == "audio-mp3")
    assert audio_fmt.ext == "mp3"
    assert "Audio" in audio_fmt.label


@pytest.mark.asyncio
async def test_youtube_short_vertical_format(mock_bin_path: Path):
    """Verify inspection of YouTube Short returns vertical video aspect ratio and formats."""
    url = "https://www.youtube.com/shorts/short_12345678"
    res = await router.inspect(url)

    assert res.platform == "youtube"
    assert res.media_type == "video"
    assert res.id == "short_12345678"
    assert "Shorts" in res.title

    # Formats should reflect high vertical resolution
    best_fmt = next(f for f in res.formats if f.format_id == "best")
    assert best_fmt.ext == "mp4"
    assert best_fmt.resolution == "1920p"


@pytest.mark.asyncio
async def test_youtube_playlist_entries(mock_bin_path: Path):
    """Verify inspection of YouTube Playlist parses items/entries array."""
    url = "https://www.youtube.com/playlist?list=PL_sample_playlist"
    res = await router.inspect(url)

    assert res.platform == "youtube"
    assert res.media_type == "carousel"
    assert len(res.items) == 3

    # Check entries structure
    for idx, item in enumerate(res.items):
        assert item.index == idx
        assert item.type == "video"
        assert item.url is not None
        assert "youtube.com" in item.url
        assert item.thumbnail is not None


@pytest.mark.asyncio
async def test_youtube_audio_only_options(mock_bin_path: Path):
    """Verify audio-only media URL or video inspection provides audio-mp3 format."""
    url = "https://www.youtube.com/watch?v=audio_track_99"
    res = await router.inspect(url)

    assert res.platform == "youtube"
    assert any(f.format_id == "audio-mp3" and f.ext == "mp3" for f in res.formats)

    audio_fmt = next(f for f in res.formats if f.format_id == "audio-mp3")
    assert audio_fmt.ext == "mp3"
    assert "MP3" in audio_fmt.label


@pytest.mark.asyncio
async def test_youtube_metadata_fields_parsing(mock_bin_path: Path):
    """Verify all expected metadata fields are properly parsed and mapped."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    res = await router.inspect(url)

    assert res.id == "dQw4w9WgXcQ"
    assert res.url == url
    assert res.platform == "youtube"
    assert "Rick Astley" in res.title
    assert res.uploader == "Rick Astley"
    assert res.thumbnail is not None
    assert res.thumbnail.startswith("http")


@pytest.mark.asyncio
async def test_youtube_download_execution(mock_bin_path: Path, isolated_env: dict[str, Path]):
    """Verify downloading a YouTube video streams progress and produces downloaded file."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    progress_records: list[float] = []

    def on_progress(progress: float, **kwargs):
        progress_records.append(progress)

    req = DownloadRequest(url=url, format_id="best")
    dl_res = await router.download(
        task_id="task_yt_download_test",
        request=req,
        progress_callback=on_progress,
    )

    assert dl_res.task_id == "task_yt_download_test"
    assert dl_res.is_zip is False
    assert dl_res.filename.endswith(".mp4")
    assert Path(dl_res.file_path).exists()
    assert Path(dl_res.file_path).stat().st_size > 0
    assert 100.0 in progress_records
