"""yt-dlp wrapper service with async subprocess execution and progress parsing."""

import inspect
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.services import ffmpeg_service
from app.services._exec import (
    AuthRequiredError as AuthRequiredError,
    ExtractionError as ExtractionError,
    RateLimitError as RateLimitError,
    classify_error as classify_error,
    run_subprocess,
)

# Regex patterns for parsing yt-dlp stdout progress
PROGRESS_PATTERN = re.compile(
    r"\[download\]\s+(?P<percent>\d+(?:\.\d+)?)%\s+of\s+~?(?P<size>[^\s]+)\s+at\s+(?P<speed>[^\s]+)\s+ETA\s+(?P<eta>[^\s]+)"
)
PROGRESS_SIMPLE_PATTERN = re.compile(
    r"\[download\]\s+(?P<percent>\d+(?:\.\d+)?)%"
)


def get_js_runtime_args() -> list[str]:
    """Detect available JS runtime and return corresponding yt-dlp flags."""
    args: list[str] = []
    if shutil.which("bun"):
        args.extend(["--js-runtimes", "bun"])
    elif shutil.which("deno"):
        args.extend(["--js-runtimes", "deno"])
    elif shutil.which("node"):
        args.extend(["--js-runtimes", "node"])

    # Enable remote challenge solver fallback
    args.extend(["--remote-components", "ejs:github"])
    return args


def get_extractor_args_for_url(url: str) -> list[str]:
    """Return platform-specific extractor optimizations (e.g. YouTube player client spoofing)."""
    args: list[str] = []
    url_lower = url.lower()
    if any(domain in url_lower for domain in ("youtube.com", "youtu.be")):
        clients = getattr(settings, "YOUTUBE_PLAYER_CLIENTS", "default").strip()
        if clients:
            args.extend(["--extractor-args", f"youtube:player_client={clients}"])
    return args


def _parse_eta(eta_str: str) -> int | None:
    """Convert ETA string (e.g. '00:05' or '01:23:45') into seconds."""
    if not eta_str or eta_str == "Unknown":
        return None
    try:
        parts = [int(p) for p in eta_str.split(":")]
        if len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        pass
    return None


async def inspect_url(
    url: str,
    proxy: str | None = None,
    cookies_path: Path | None = None,
) -> dict[str, Any]:
    """Inspect a URL using yt-dlp and return raw parsed metadata dictionary."""
    cmd = [
        "yt-dlp",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        "--no-playlist",
    ]
    cmd.extend(get_js_runtime_args())
    cmd.extend(get_extractor_args_for_url(url))

    if proxy:
        cmd.extend(["--proxy", proxy])
    if cookies_path and cookies_path.exists():
        cmd.extend(["--cookies", str(cookies_path)])

    cmd.append(url)

    returncode, raw_stdout, err_msg = await run_subprocess(cmd)
    if returncode != 0:
        raise classify_error(err_msg, extra_proxies=(proxy,))

    raw_json = raw_stdout.strip()
    if not raw_json:
        raise ExtractionError("yt-dlp produced empty metadata")

    try:
        return json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"Failed to parse yt-dlp metadata JSON: {e}")


async def download_media(
    url: str,
    output_dir: Path,
    format_id: str | None = None,
    extract_audio: bool = False,
    audio_format: str = "mp3",
    proxy: str | None = None,
    cookies_path: Path | None = None,
    progress_callback: Callable[..., Any] | None = None,
) -> list[Path]:
    """Download media using yt-dlp while streaming progress updates."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(output_dir / "%(title).200B.%(ext)s")

    cmd = [
        "yt-dlp",
        "--newline",
        "--no-warnings",
        "--no-playlist",
        "-o",
        out_template,
    ]
    ffmpeg_bin = ffmpeg_service.get_ffmpeg_bin()
    if ffmpeg_bin:
        cmd.extend(["--ffmpeg-location", ffmpeg_bin])

    cmd.extend(get_js_runtime_args())
    cmd.extend(get_extractor_args_for_url(url))

    if proxy:
        cmd.extend(["--proxy", proxy])
    if cookies_path and cookies_path.exists():
        cmd.extend(["--cookies", str(cookies_path)])

    if not extract_audio:
        cmd.extend(["--merge-output-format", "mp4"])

    if extract_audio:
        cmd.extend(["-x", "--audio-format", audio_format])
    elif format_id:
        clean_format = format_id.strip()
        if not clean_format or clean_format.lower() == "best":
            cmd.extend(["-f", "bestvideo+bestaudio/best"])
        elif clean_format.lower() == "4k":
            cmd.extend(["-f", "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best"])
        elif clean_format.lower().endswith("p") and clean_format[:-1].isdigit():
            h = int(clean_format[:-1])
            cmd.extend(["-f", f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"])
        elif clean_format.isdigit() and int(clean_format) in (144, 240, 360, 480, 720, 1080, 1440, 2160):
            h = int(clean_format)
            cmd.extend(["-f", f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"])
        elif "+" in clean_format or "/" in clean_format:
            cmd.extend(["-f", clean_format])
        else:
            cmd.extend(
                ["-f", f"{clean_format}[acodec!=none]/{clean_format}+bestaudio/{clean_format}/best"]
            )
    else:
        cmd.extend(["-f", "bestvideo+bestaudio/best"])

    cmd.append(url)

    async def _on_stdout_line(line: str) -> None:
        if not progress_callback:
            return
        match = PROGRESS_PATTERN.search(line)
        if match:
            res = progress_callback(
                progress=float(match.group("percent")),
                speed=match.group("speed"),
                eta=_parse_eta(match.group("eta")),
                message=f"Downloading: {float(match.group('percent')):.1f}%",
            )
            if inspect.isawaitable(res):
                await res
            return

        simple_match = PROGRESS_SIMPLE_PATTERN.search(line)
        if simple_match:
            percent = float(simple_match.group("percent"))
            res = progress_callback(
                progress=percent,
                message=f"Downloading: {percent:.1f}%",
            )
            if inspect.isawaitable(res):
                await res

    returncode, _stdout, full_err = await run_subprocess(cmd, on_stdout_line=_on_stdout_line)
    if returncode != 0:
        raise classify_error(full_err, extra_proxies=(proxy,))

    # Collect downloaded files in output_dir, excluding hidden, temporary, or cookie files
    files = [
        p
        for p in output_dir.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and not p.name.startswith("client_cookies_")
        and not p.name.endswith(".part")
        and not p.name.endswith(".ytdl")
    ]
    return sorted(files)
