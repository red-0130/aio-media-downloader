"""FFmpeg media post-processing service powered by pyffmpeg."""

import asyncio
import logging
import os
import shutil
from pathlib import Path

_CACHED_FFMPEG_BIN: str | None = None


def get_ffmpeg_bin() -> str:
    """Resolve and return path to FFmpeg binary via pyffmpeg, with system fallback."""
    global _CACHED_FFMPEG_BIN
    if _CACHED_FFMPEG_BIN and Path(_CACHED_FFMPEG_BIN).exists():
        return _CACHED_FFMPEG_BIN

    try:
        # Suppress pyffmpeg verbose logger output on init
        pyffmpeg_logger = logging.getLogger("pyffmpeg")
        pyffmpeg_logger.setLevel(logging.WARNING)

        from pyffmpeg import FFmpeg

        ff = FFmpeg(enable_log=False)
        bin_path = ff.get_ffmpeg_bin()
        if bin_path and Path(bin_path).exists():
            _CACHED_FFMPEG_BIN = str(bin_path)

            # Ensure pyffmpeg's bin dir is prepended to PATH for subprocesses (yt-dlp, etc.)
            bin_dir = str(Path(bin_path).parent)
            current_path = os.environ.get("PATH", "")
            if bin_dir not in current_path.split(os.pathsep):
                os.environ["PATH"] = f"{bin_dir}{os.pathsep}{current_path}"

            return _CACHED_FFMPEG_BIN
    except Exception:
        pass

    # Fallback to system ffmpeg if available
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        _CACHED_FFMPEG_BIN = system_ffmpeg
        return _CACHED_FFMPEG_BIN

    return "ffmpeg"


async def run_ffmpeg_command(cmd: list[str]) -> None:
    """Execute ffmpeg command safely using asyncio.create_subprocess_exec."""
    resolved_cmd = list(cmd)
    if resolved_cmd and (resolved_cmd[0] == "ffmpeg" or resolved_cmd[0].endswith("/ffmpeg")):
        resolved_cmd[0] = get_ffmpeg_bin()

    process = await asyncio.create_subprocess_exec(
        *resolved_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        err_msg = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg command failed (exit code {process.returncode}): {err_msg}")


async def extract_audio(
    input_file: Path,
    output_file: Path,
    audio_format: str = "mp3",
    bitrate: str = "320k",
) -> Path:
    """Extract audio track from video and convert to target format (mp3, m4a, wav)."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = audio_format.lower().lstrip(".")

    cmd = [get_ffmpeg_bin(), "-y", "-i", str(input_file), "-vn"]

    if fmt == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", bitrate])
    elif fmt == "m4a":
        cmd.extend(["-c:a", "aac", "-b:a", bitrate])
    elif fmt == "wav":
        cmd.extend(["-c:a", "pcm_s16le"])
    else:
        # Fallback to copy or generic codec
        cmd.extend(["-c:a", "copy"])

    cmd.append(str(output_file))
    await run_ffmpeg_command(cmd)
    return output_file


async def remux_to_mp4(
    video_file: Path,
    audio_file: Path,
    output_file: Path,
) -> Path:
    """Remux separate video and audio streams into a universal MP4 container."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        get_ffmpeg_bin(),
        "-y",
        "-i",
        str(video_file),
        "-i",
        str(audio_file),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_file),
    ]
    await run_ffmpeg_command(cmd)
    return output_file


async def embed_metadata(
    file_path: Path,
    title: str | None = None,
    artist: str | None = None,
    cover_image: Path | None = None,
) -> Path:
    """Embed title, artist, and optional cover art into media file."""
    if not title and not artist and not cover_image:
        return file_path

    temp_out = file_path.with_name(f"temp_{file_path.name}")
    cmd = [get_ffmpeg_bin(), "-y", "-i", str(file_path)]

    if cover_image and cover_image.exists():
        cmd.extend(["-i", str(cover_image), "-map", "0", "-map", "1"])
        cmd.extend(["-c", "copy", "-disposition:v:1", "attached_pic"])
    else:
        cmd.extend(["-c", "copy"])

    if title:
        cmd.extend(["-metadata", f"title={title}"])
    if artist:
        cmd.extend(["-metadata", f"artist={artist}"])

    cmd.append(str(temp_out))

    try:
        await run_ffmpeg_command(cmd)
        temp_out.replace(file_path)
    finally:
        if temp_out.exists():
            temp_out.unlink(missing_ok=True)

    return file_path
