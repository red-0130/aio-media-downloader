"""yt-dlp wrapper service with async subprocess execution and progress parsing."""

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.services import ffmpeg_service

# Regex patterns for parsing yt-dlp stdout progress
PROGRESS_PATTERN = re.compile(
    r"\[download\]\s+(?P<percent>\d+(?:\.\d+)?)%\s+of\s+~?(?P<size>[^\s]+)\s+at\s+(?P<speed>[^\s]+)\s+ETA\s+(?P<eta>[^\s]+)"
)
PROGRESS_SIMPLE_PATTERN = re.compile(
    r"\[download\]\s+(?P<percent>\d+(?:\.\d+)?)%"
)


class ExtractionError(Exception):
    """Generic media extraction failure."""
    pass


class AuthRequiredError(ExtractionError):
    """Authentication required to access media (login wall, private post)."""
    pass


class RateLimitError(ExtractionError):
    """Platform rate limit reached (HTTP 429)."""
    pass


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


def classify_error(stderr_text: str) -> Exception:
    """Analyze stderr or extractor output and return appropriate specialized exception."""
    if settings.SOCKS5_PROXY:
        stderr_text = stderr_text.replace(settings.SOCKS5_PROXY, "[REDACTED_PROXY]")
        try:
            import urllib.parse
            parsed = urllib.parse.urlsplit(settings.SOCKS5_PROXY)
            if parsed.netloc and parsed.netloc in stderr_text:
                stderr_text = stderr_text.replace(parsed.netloc, "[REDACTED_PROXY]")
            if parsed.password and parsed.password in stderr_text:
                stderr_text = stderr_text.replace(parsed.password, "[REDACTED]")
        except Exception:
            pass

    text_lower = stderr_text.lower()

    # 1. Age-restricted or private media (strictly requires user account cookies)
    if any(
        term in text_lower
        for term in (
            "confirm your age",
            "age-restricted",
            "sign in to confirm your age",
            "private video",
            "this video is private",
            "private account",
            "this account is private",
            "members-only",
        )
    ):
        return AuthRequiredError(
            f"Authentication required: Age-restricted or private content. Please supply authenticated cookies in Settings. ({stderr_text.strip()})"
        )

    # 2. Platform Bot / Login walls
    if any(
        term in text_lower
        for term in (
            "sign in to confirm",
            "sign in to",
            "login required",
            "login_required",
            "login page",
            "redirect to login",
            "accounts/login",
            "checkpoint_required",
            "protected tweets",
            "registered users",
            "requires authentication",
            "authentication required",
            "could not authenticate you",
            "http error 401",
            "http error 403",
            "'unavailable'",
        )
    ):
        return AuthRequiredError(
            f"Authentication required: Bot verification or login required. Try alternate player clients or provide cookies in Settings. ({stderr_text.strip()})"
        )

    if any(
        term in text_lower
        for term in (
            "http error 429",
            "too many requests",
            "rate limit",
            "rate-limited",
            "exceeded the rate-limit",
        )
    ):
        return RateLimitError(
            f"Rate limited by platform. Please wait or configure a proxy in Settings. ({stderr_text.strip()})"
        )

    return ExtractionError(f"Extraction failed: {stderr_text.strip()}")


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

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        err_msg = stderr.decode("utf-8", errors="replace")
        raise classify_error(err_msg)

    raw_json = stdout.decode("utf-8", errors="replace").strip()
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

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stderr_lines: list[str] = []

    async def read_stderr():
        if process.stderr:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                stderr_lines.append(line.decode("utf-8", errors="replace"))

    stderr_task = asyncio.create_task(read_stderr())

    if process.stdout:
        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").strip()

            match = PROGRESS_PATTERN.search(line)
            if match and progress_callback:
                percent = float(match.group("percent"))
                speed = match.group("speed")
                eta = _parse_eta(match.group("eta"))
                res = progress_callback(
                    progress=percent,
                    speed=speed,
                    eta=eta,
                    message=f"Downloading: {percent:.1f}%",
                )
                if asyncio.iscoroutine(res):
                    await res
            else:
                simple_match = PROGRESS_SIMPLE_PATTERN.search(line)
                if simple_match and progress_callback:
                    percent = float(simple_match.group("percent"))
                    res = progress_callback(
                        progress=percent,
                        message=f"Downloading: {percent:.1f}%",
                    )
                    if asyncio.iscoroutine(res):
                        await res

    await process.wait()
    await stderr_task

    if process.returncode != 0:
        full_err = "".join(stderr_lines)
        raise classify_error(full_err)

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
