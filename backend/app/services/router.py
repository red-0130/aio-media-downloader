"""Domain and content-aware extraction router with automated fallback."""

import asyncio
import os
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.models.download import DownloadRequest, DownloadResult
from app.models.inspect import FormatOption, InspectResponse, MediaItem
from app.services import (
    cleaner,
    cookie_manager,
    ffmpeg_service,
    gallerydl_service,
    naming_service,
    proxy_manager,
    security,
    ytdlp_service,
    zip_service,
)
from app.services.ytdlp_service import (
    AuthRequiredError,
    ExtractionError,
    RateLimitError,
)


def classify_url(url: str) -> tuple[str, str, str | None]:
    """Classify incoming URL into platform, primary extraction engine, and fallback engine.

    Returns: (platform, primary_engine, fallback_engine)
    """
    clean_url = url.strip()
    try:
        parsed = urllib.parse.urlsplit(clean_url)
        hostname = (parsed.hostname or "").lower()
        path = parsed.path.lower()
    except Exception:
        return "generic", "ytdlp", "gallerydl"

    # YouTube
    if any(h in hostname for h in ("youtube.com", "youtu.be")):
        return "youtube", "ytdlp", None

    # Instagram
    if any(h in hostname for h in ("instagram.com", "instagr.am")):
        if "/reel/" in path or "/reels/" in path or "/tv/" in path:
            return "instagram", "ytdlp", "gallerydl"
        elif "/stories/" in path or "/s/" in path or "/p/" in path:
            return "instagram", "gallerydl", "ytdlp"
        return "instagram", "gallerydl", "ytdlp"

    # Twitter / X
    if any(h in hostname for h in ("twitter.com", "x.com")):
        if "/photo/" in path:
            return "twitter", "gallerydl", "ytdlp"
        elif "/video/" in path or "/reel" in path:
            return "twitter", "ytdlp", "gallerydl"
        # Standard tweet may contain photos or videos; try gallery-dl then yt-dlp
        return "twitter", "gallerydl", "ytdlp"

    # TikTok
    if "tiktok.com" in hostname:
        if "/photo/" in path:
            return "tiktok", "gallerydl", "ytdlp"
        return "tiktok", "ytdlp", "gallerydl"

    # Generic
    return "generic", "ytdlp", "gallerydl"


def _normalize_ytdlp_metadata(url: str, platform: str, data: dict[str, Any]) -> InspectResponse:
    """Transform yt-dlp metadata dictionary into unified InspectResponse."""
    media_id = str(data.get("id") or "media")
    title = data.get("title") or f"{platform.capitalize()} media"
    uploader = data.get("uploader") or data.get("channel") or data.get("creator")
    thumbnail = data.get("thumbnail")

    # Determine media type
    if "stories" in url:
        media_type = "story"
    elif data.get("entries"):
        media_type = "carousel"
    elif data.get("vcodec") == "none":
        media_type = "audio"
    else:
        media_type = "video"

    # Process items (for playlists or carousels)
    items: list[MediaItem] = []
    entries = data.get("entries")
    if entries and isinstance(entries, list):
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            item_type = "video" if entry.get("vcodec") != "none" else "image"
            items.append(
                MediaItem(
                    index=idx,
                    type=item_type,
                    url=entry.get("webpage_url") or entry.get("url"),
                    thumbnail=entry.get("thumbnail"),
                    resolution=f"{entry.get('width')}x{entry.get('height')}"
                    if entry.get("width")
                    else None,
                    duration=entry.get("duration"),
                )
            )

    # Process format options
    formats: list[FormatOption] = []
    # Always provide default original quality
    formats.append(
        FormatOption(
            format_id="best",
            label="Original Quality",
            ext=data.get("ext") or "mp4",
            filesize=data.get("filesize") or data.get("filesize_approx"),
            resolution=f"{data.get('height')}p" if data.get("height") else None,
        )
    )

    # Extract available video resolutions
    raw_formats = data.get("formats") or []
    seen_heights = set()
    for fmt in reversed(raw_formats):
        height = fmt.get("height")
        fid = fmt.get("format_id")
        vcodec = fmt.get("vcodec")
        if height and height not in seen_heights and vcodec and vcodec != "none":
            seen_heights.add(height)
            formats.append(
                FormatOption(
                    format_id=str(fid),
                    label=f"{height}p Video",
                    ext=fmt.get("ext") or "mp4",
                    filesize=fmt.get("filesize") or fmt.get("filesize_approx"),
                    resolution=f"{height}p",
                )
            )

    # Always offer MP3 audio extraction
    formats.append(
        FormatOption(
            format_id="audio-mp3",
            label="Audio Only (MP3)",
            ext="mp3",
        )
    )

    return InspectResponse(
        id=media_id,
        url=url,
        platform=platform,
        title=title,
        uploader=uploader,
        thumbnail=thumbnail,
        media_type=media_type,
        items=items,
        formats=formats,
    )


def _normalize_gallerydl_metadata(
    url: str, platform: str, items_data: list[dict[str, Any]]
) -> InspectResponse:
    """Transform gallery-dl metadata list into unified InspectResponse."""
    first = items_data[0] if items_data else {}
    media_id = str(first.get("post_id") or first.get("id") or first.get("tweet_id") or "post")
    uploader = (
        first.get("user")
        or first.get("username")
        or first.get("author")
        or first.get("account")
        or first.get("channel")
    )
    title = first.get("description") or first.get("title") or f"{platform.capitalize()} post"
    thumbnail = first.get("url") or first.get("thumbnail")

    # Detect media type
    if "stories" in url:
        media_type = "story"
    elif len(items_data) > 1:
        media_type = "carousel"
    else:
        ext = (first.get("extension") or "").lower()
        if ext in ("mp4", "webm", "mov"):
            media_type = "video"
        elif ext in ("mp3", "m4a", "wav"):
            media_type = "audio"
        else:
            media_type = "image"

    # Build items list
    items: list[MediaItem] = []
    for idx, it in enumerate(items_data):
        ext = (it.get("extension") or "").lower()
        item_type = "video" if ext in ("mp4", "webm", "mov") else "image"
        width = it.get("width")
        height = it.get("height")
        res_str = f"{width}x{height}" if width and height else None

        items.append(
            MediaItem(
                index=idx,
                type=item_type,
                url=it.get("url"),
                thumbnail=it.get("thumbnail") or it.get("url"),
                resolution=res_str,
                duration=it.get("duration"),
            )
        )

    # Build formats
    formats: list[FormatOption] = [
        FormatOption(
            format_id="best",
            label="Original Quality",
            ext=first.get("extension") or "jpg",
        ),
        FormatOption(
            format_id="audio-mp3",
            label="Audio Only (MP3)",
            ext="mp3",
        ),
    ]

    return InspectResponse(
        id=media_id,
        url=url,
        platform=platform,
        title=title,
        uploader=uploader,
        thumbnail=thumbnail,
        media_type=media_type,
        items=items,
        formats=formats,
    )


async def inspect(
    url: str,
    proxy: str | None = None,
    cookies: dict[str, str | None] | str | None = None,
) -> InspectResponse:
    """Inspect media URL with automatic primary and fallback engine dispatch."""
    clean_url = security.validate_url(url)
    platform, primary, fallback = classify_url(clean_url)

    clean_client_proxy = proxy.strip() if (proxy and proxy.strip()) else None
    effective_proxy = clean_client_proxy or proxy_manager.get_proxy()
    if effective_proxy:
        effective_proxy = proxy_manager.validate_proxy_url(effective_proxy)

    async with cookie_manager.resolve_cookies_context(platform, cookies) as cookies_path:
        # Primary engine execution
        if primary == "ytdlp":
            try:
                data = await ytdlp_service.inspect_url(
                    clean_url, proxy=effective_proxy, cookies_path=cookies_path
                )
                return _normalize_ytdlp_metadata(clean_url, platform, data)
            except Exception as primary_err:
                if fallback == "gallerydl":
                    try:
                        gitems = await gallerydl_service.inspect_url(
                            clean_url, proxy=effective_proxy, cookies_path=cookies_path
                        )
                        return _normalize_gallerydl_metadata(clean_url, platform, gitems)
                    except Exception as fallback_err:
                        if isinstance(primary_err, (AuthRequiredError, RateLimitError)):
                            raise primary_err
                        if isinstance(fallback_err, (AuthRequiredError, RateLimitError)):
                            raise fallback_err
                        raise primary_err
                raise primary_err
        else:  # primary == "gallerydl"
            try:
                gitems = await gallerydl_service.inspect_url(
                    clean_url, proxy=effective_proxy, cookies_path=cookies_path
                )
                return _normalize_gallerydl_metadata(clean_url, platform, gitems)
            except Exception as primary_err:
                if fallback == "ytdlp":
                    try:
                        data = await ytdlp_service.inspect_url(
                            clean_url, proxy=effective_proxy, cookies_path=cookies_path
                        )
                        return _normalize_ytdlp_metadata(clean_url, platform, data)
                    except Exception as fallback_err:
                        if isinstance(primary_err, (AuthRequiredError, RateLimitError)):
                            raise primary_err
                        if isinstance(fallback_err, (AuthRequiredError, RateLimitError)):
                            raise fallback_err
                        if platform in ("instagram", "twitter") and "no video" in str(fallback_err).lower():
                            raise AuthRequiredError(
                                f"Authentication required: {platform.capitalize()} requires session cookies to inspect this post. Please configure cookies in Settings."
                            )
                        raise primary_err
                raise primary_err


async def download(
    task_id: str,
    request: DownloadRequest,
    progress_callback: Callable[..., Any] | None = None,
    proxy: str | None = None,
    metadata: dict[str, Any] | InspectResponse | None = None,
    cookies: dict[str, str | None] | str | None = None,
) -> DownloadResult:
    """Execute media download with naming conventions, audio conversion, and ZIP bundling."""
    clean_url = security.validate_url(request.url)
    platform, primary, fallback = classify_url(clean_url)

    clean_client_proxy = (proxy.strip() if (proxy and proxy.strip()) else None) or (
        request.proxy.strip() if (request.proxy and request.proxy.strip()) else None
    )
    effective_proxy = clean_client_proxy or proxy_manager.get_proxy()
    if effective_proxy:
        effective_proxy = proxy_manager.validate_proxy_url(effective_proxy)

    client_cookies = cookies if cookies is not None else request.cookies

    task_dir = settings.DOWNLOADS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    downloaded_files: list[Path] = []

    async with cookie_manager.resolve_cookies_context(
        platform, client_cookies
    ) as cookies_path:
        # Download via primary engine, with fallback on failure
        if primary == "ytdlp":
            try:
                downloaded_files = await ytdlp_service.download_media(
                    url=clean_url,
                    output_dir=task_dir,
                    format_id=request.format_id,
                    extract_audio=request.extract_audio,
                    audio_format=request.audio_format,
                    proxy=effective_proxy,
                    cookies_path=cookies_path,
                    progress_callback=progress_callback,
                )
            except Exception as primary_err:
                if fallback == "gallerydl":
                    try:
                        downloaded_files = await gallerydl_service.download_items(
                            url=clean_url,
                            output_dir=task_dir,
                            selected_indices=request.selected_indices,
                            proxy=effective_proxy,
                            cookies_path=cookies_path,
                            progress_callback=progress_callback,
                        )
                    except Exception as fallback_err:
                        if isinstance(primary_err, (AuthRequiredError, RateLimitError)):
                            raise primary_err
                        if isinstance(fallback_err, (AuthRequiredError, RateLimitError)):
                            raise fallback_err
                        raise primary_err
                else:
                    raise primary_err
        else:  # primary == "gallerydl"
            try:
                downloaded_files = await gallerydl_service.download_items(
                    url=clean_url,
                    output_dir=task_dir,
                    selected_indices=request.selected_indices,
                    proxy=effective_proxy,
                    cookies_path=cookies_path,
                    progress_callback=progress_callback,
                )
            except Exception as primary_err:
                if fallback == "ytdlp":
                    try:
                        downloaded_files = await ytdlp_service.download_media(
                            url=clean_url,
                            output_dir=task_dir,
                            format_id=request.format_id,
                            extract_audio=request.extract_audio,
                            audio_format=request.audio_format,
                            proxy=effective_proxy,
                            cookies_path=cookies_path,
                            progress_callback=progress_callback,
                        )
                    except Exception as fallback_err:
                        if isinstance(primary_err, (AuthRequiredError, RateLimitError)):
                            raise primary_err
                        if isinstance(fallback_err, (AuthRequiredError, RateLimitError)):
                            raise fallback_err
                        if platform in ("instagram", "twitter") and "no video" in str(fallback_err).lower():
                            raise AuthRequiredError(
                                f"Authentication required: {platform.capitalize()} requires session cookies to download this post. Please configure cookies in Settings."
                            )
                        raise primary_err
                else:
                    raise primary_err


    if not downloaded_files:
        raise ExtractionError("No files were downloaded")

    # If audio extraction requested on gallery-dl downloaded video file
    if request.extract_audio and len(downloaded_files) == 1:
        raw_file = downloaded_files[0]
        ext = raw_file.suffix.lower().lstrip(".")
        if ext in ("mp4", "webm", "mkv", "mov"):
            audio_out = raw_file.with_suffix(f".{request.audio_format}")
            await ffmpeg_service.extract_audio(
                input_file=raw_file,
                output_file=audio_out,
                audio_format=request.audio_format,
            )
            raw_file.unlink(missing_ok=True)
            downloaded_files = [audio_out]

    # Package as ZIP if multiple files or explicitly requested for bundle
    if len(downloaded_files) > 1 or (request.package_as_zip and len(downloaded_files) > 1):
        zip_filename = f"{platform}_bundle_{task_id}.zip"
        zip_path = task_dir / zip_filename
        zip_service.create_zip_archive(downloaded_files, zip_path)
        file_size = zip_path.stat().st_size
        return DownloadResult(
            task_id=task_id,
            filename=zip_filename,
            file_path=str(zip_path),
            file_size=file_size,
            download_url=f"/api/files/{task_id}/{zip_filename}",
            is_zip=True,
        )

    # Single file output: apply naming conventions with genuine metadata flow
    single_file = downloaded_files[0]
    file_ext = single_file.suffix.lstrip(".")

    # Extract metadata if provided or probe if missing
    meta_dict: dict[str, Any] = {}
    if metadata:
        if isinstance(metadata, InspectResponse):
            meta_dict = metadata.model_dump()
        elif isinstance(metadata, dict):
            meta_dict = metadata
    elif getattr(request, "metadata", None) and isinstance(request.metadata, dict):
        meta_dict = request.metadata

    # If metadata is missing for Instagram, probe inspect info
    if not meta_dict and platform == "instagram":
        try:
            inspected = await inspect(
                clean_url, proxy=effective_proxy, cookies=client_cookies
            )
            meta_dict = inspected.model_dump()
        except Exception:
            pass

    uploader = (
        meta_dict.get("uploader")
        or meta_dict.get("username")
        or meta_dict.get("user")
        or meta_dict.get("author")
    )
    date_val = (
        meta_dict.get("date")
        or meta_dict.get("upload_date")
        or meta_dict.get("timestamp")
        or meta_dict.get("created_at")
    )
    orig_name = (
        meta_dict.get("original_name_first")
        or meta_dict.get("original_name")
        or meta_dict.get("original_filename")
    )
    media_id = (
        meta_dict.get("id")
        or meta_dict.get("media_id")
        or meta_dict.get("post_id")
        or task_id
    )
    title = meta_dict.get("title") or single_file.stem

    if platform == "instagram":
        formatted_name = naming_service.format_instagram_filename(
            username=uploader,
            date_str=date_val,
            original_name_first=orig_name,
            media_id=str(media_id),
            title=title,
            ext=file_ext,
        )
    else:
        formatted_name = naming_service.format_standard_filename(
            title=title,
            platform=platform,
            media_id=str(media_id),
            ext=file_ext,
        )

    renamed_path = task_dir / formatted_name
    if single_file != renamed_path:
        single_file.rename(renamed_path)

    file_size = renamed_path.stat().st_size
    return DownloadResult(
        task_id=task_id,
        filename=formatted_name,
        file_path=str(renamed_path),
        file_size=file_size,
        download_url=f"/api/files/{task_id}/{formatted_name}",
        is_zip=False,
    )
