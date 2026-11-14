"""Tier 1 Feature Coverage: F08 - FFmpeg Media Processing."""

import shutil
from pathlib import Path
from typing import Any

import pytest

from app.services import ffmpeg_service


@pytest.mark.asyncio
async def test_ffmpeg_audio_conversion_to_mp3(
    tmp_path: Path, fixtures_paths: dict[str, Path]
):
    """Verify extracting audio to MP3 using ffmpeg."""
    sample_mp4 = fixtures_paths["sample_mp4"]
    output_mp3 = tmp_path / "output_test.mp3"

    result = await ffmpeg_service.extract_audio(
        input_file=sample_mp4,
        output_file=output_mp3,
        audio_format="mp3",
    )

    assert result == output_mp3
    assert output_mp3.exists()
    assert output_mp3.suffix == ".mp3"
    assert output_mp3.stat().st_size > 500


@pytest.mark.asyncio
async def test_ffmpeg_audio_conversion_to_m4a(
    tmp_path: Path, fixtures_paths: dict[str, Path]
):
    """Verify extracting audio to M4A/AAC using ffmpeg."""
    sample_mp4 = fixtures_paths["sample_mp4"]
    output_m4a = tmp_path / "output_test.m4a"

    result = await ffmpeg_service.extract_audio(
        input_file=sample_mp4,
        output_file=output_m4a,
        audio_format="m4a",
    )

    assert result == output_m4a
    assert output_m4a.exists()
    assert output_m4a.suffix == ".m4a"
    assert output_m4a.stat().st_size > 500


@pytest.mark.asyncio
async def test_ffmpeg_audio_conversion_to_wav(
    tmp_path: Path, fixtures_paths: dict[str, Path]
):
    """Verify extracting audio to WAV (PCM) using ffmpeg."""
    sample_mp4 = fixtures_paths["sample_mp4"]
    output_wav = tmp_path / "output_test.wav"

    result = await ffmpeg_service.extract_audio(
        input_file=sample_mp4,
        output_file=output_wav,
        audio_format="wav",
    )

    assert result == output_wav
    assert output_wav.exists()
    assert output_wav.suffix == ".wav"
    assert output_wav.stat().st_size > 500


@pytest.mark.asyncio
async def test_ffmpeg_video_mp4_remuxing(
    tmp_path: Path, fixtures_paths: dict[str, Path]
):
    """Verify combining video stream and audio stream into MP4 container."""
    sample_mp4 = fixtures_paths["sample_mp4"]
    sample_mp3 = fixtures_paths["sample_mp3"]
    output_remux = tmp_path / "output_remux.mp4"

    result = await ffmpeg_service.remux_to_mp4(
        video_file=sample_mp4,
        audio_file=sample_mp3,
        output_file=output_remux,
    )

    assert result == output_remux
    assert output_remux.exists()
    assert output_remux.suffix == ".mp4"
    assert output_remux.stat().st_size > 1000


@pytest.mark.asyncio
async def test_ffmpeg_metadata_tag_embedding(
    tmp_path: Path, fixtures_paths: dict[str, Path]
):
    """Verify embedding title, artist, and optional artwork metadata."""
    sample_mp3 = fixtures_paths["sample_mp3"]
    target_mp3 = tmp_path / "song_with_tags.mp3"
    shutil.copyfile(sample_mp3, target_mp3)

    sample_cover = fixtures_paths["sample_jpg"]

    result = await ffmpeg_service.embed_metadata(
        file_path=target_mp3,
        title="Epic Test Song",
        artist="Test Artist",
        cover_image=sample_cover,
    )

    assert result == target_mp3
    assert target_mp3.exists()
    assert target_mp3.stat().st_size > 1000


@pytest.mark.asyncio
async def test_ffmpeg_invalid_input_error_handling(tmp_path: Path):
    """Verify FFmpeg raises RuntimeError on invalid or non-existent input files."""
    non_existent = tmp_path / "does_not_exist.mp4"
    output_file = tmp_path / "out.mp3"

    with pytest.raises(RuntimeError) as exc_info:
        await ffmpeg_service.extract_audio(non_existent, output_file, "mp3")

    assert "FFmpeg command failed" in str(exc_info.value)
