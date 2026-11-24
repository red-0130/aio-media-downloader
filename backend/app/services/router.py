"""Domain and content-aware extraction router with automated fallback."""

import asyncio
from datetime import datetime, timezone
import os
import re
import shutil
import urllib.parse
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.models.download import DownloadFileInfo, DownloadRequest, DownloadResult
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

SUPPORTED_VIDEO_EXTENSIONS: tuple[str, ...] = (
    "mp4",
    "webm",
    "mkv",
    "mov",
    "m4v",
    "avi",
    "flv",
    "wmv",
    "3gp",
    "ts",
    "ogv",
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


def _extract_instagram_username_from_url(url: str) -> str | None:
    """Extract Instagram username handle from URL if present."""
    match = re.search(r"instagram\.com/(?:stories/)?([A-Za-z0-9._]+)/?", url)
    if match:
        user = match.group(1)
        if user not in ("p", "reel", "reels", "stories", "tv", "explore"):
            return user
    return None


def _normalize_ytdlp_metadata(url: str, platform: str, data: dict[str, Any]) -> InspectResponse:
    """Transform yt-dlp metadata dictionary into unified InspectResponse."""
    media_id = str(data.get("id") or "media")
    title = data.get("title") or f"{platform.capitalize()} media"
    if platform == "instagram":
        uploader = data.get("channel") or data.get("uploader") or data.get("creator")
    else:
        uploader = data.get("uploader") or data.get("channel") or data.get("creator")
    thumbnail = data.get("thumbnail")
    date_val = data.get("upload_date") or data.get("timestamp") or data.get("date")
    orig_name_first = data.get("original_name_first") or data.get("id")

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
            item_date = entry.get("upload_date") or entry.get("timestamp") or date_val
            item_orig = entry.get("original_name_first") or entry.get("id") or str(idx + 1)
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
                    date=str(item_date) if item_date else None,
                    original_name=str(item_orig) if item_orig else None,
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
    height_to_fmt: dict[int, dict[str, Any]] = {}
    for fmt in raw_formats:
        h = fmt.get("height")
        vcodec = fmt.get("vcodec")
        protocol = str(fmt.get("protocol") or "")
        if h and vcodec and vcodec != "none":
            # Prefer direct progressive/DASH over m3u8 / mhtml protocols
            existing = height_to_fmt.get(h)
            if not existing:
                height_to_fmt[h] = fmt
            else:
                existing_proto = str(existing.get("protocol") or "")
                if "m3u8" in existing_proto and "m3u8" not in protocol:
                    height_to_fmt[h] = fmt

    # Sort descending by height
    for height in sorted(height_to_fmt.keys(), reverse=True):
        fmt = height_to_fmt[height]
        fid = fmt.get("format_id")
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
        date=str(date_val) if date_val else None,
        original_name_first=str(orig_name_first) if orig_name_first else None,
    )


def _normalize_gallerydl_metadata(
    url: str, platform: str, items_data: list[dict[str, Any]]
) -> InspectResponse:
    """Transform gallery-dl metadata list into unified InspectResponse."""
    first = items_data[0] if items_data else {}
    media_id = str(first.get("post_id") or first.get("id") or first.get("tweet_id") or "post")
    author_val = (
        first.get("user")
        or first.get("username")
        or first.get("author")
        or first.get("account")
        or first.get("channel")
    )
    if isinstance(author_val, dict):
        uploader = (
            author_val.get("nick")
            or author_val.get("name")
            or author_val.get("username")
            or None
        )
    elif author_val:
        uploader = str(author_val)
    else:
        uploader = None
    title = (
        first.get("content")
        or first.get("description")
        or first.get("title")
        or f"{platform.capitalize()} post"
    )
    thumbnail = first.get("url") or first.get("thumbnail")
    date_val = first.get("date") or first.get("post_date") or first.get("timestamp")
    orig_name = (
        first.get("original_name_first")
        or first.get("original_name")
        or first.get("filename")
        or first.get("original_filename")
        or first.get("post_id")
    )

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

        item_date = it.get("date") or it.get("post_date") or it.get("timestamp") or date_val
        item_url = it.get("url") or ""
        item_orig = (
            it.get("original_name_first")
            or it.get("original_name")
            or it.get("filename")
            or it.get("original_filename")
            or (Path(urlparse(item_url).path).stem if item_url else None)
            or str(idx + 1)
        )

        items.append(
            MediaItem(
                index=idx,
                type=item_type,
                url=it.get("url"),
                thumbnail=it.get("thumbnail") or it.get("url"),
                resolution=res_str,
                duration=it.get("duration"),
                date=str(item_date) if item_date else None,
                original_name=str(item_orig) if item_orig else None,
                original_name_first=str(item_orig) if item_orig else None,
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
        date=str(date_val) if date_val else None,
        original_name_first=str(orig_name) if orig_name else None,
    )


async def inspect(
    url: str,
    proxy: str | None = None,
    cookies: dict[str, str | None] | str | None = None,
) -> InspectResponse:
    """Inspect media URL with automatic primary and fallback engine dispatch."""
    clean_url = await security.validate_url_async(url)
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
    clean_url = await security.validate_url_async(request.url)
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

    # If audio extraction requested on gallery-dl downloaded video files
    if request.extract_audio:
        target_fmt = (request.audio_format or "mp3").lower().lstrip(".")
        converted_files: list[Path] = []
        total_videos = sum(
            1 for f in downloaded_files if f.suffix.lower().lstrip(".") in SUPPORTED_VIDEO_EXTENSIONS
        )
        converted_count = 0
        for raw_file in downloaded_files:
            ext = raw_file.suffix.lower().lstrip(".")
            if ext in SUPPORTED_VIDEO_EXTENSIONS:
                converted_count += 1
                if progress_callback:
                    res = progress_callback(
                        progress=min(round(90.0 + (converted_count / max(total_videos, 1)) * 9.0, 1), 99.0),
                        message=f"Extracting audio ({converted_count}/{total_videos})...",
                    )
                    if asyncio.iscoroutine(res):
                        await res

                audio_out = raw_file.with_suffix(f".{target_fmt}")
                # Ensure no collision with existing file or already converted items before conversion
                if (audio_out.exists() or audio_out in converted_files) and audio_out != raw_file:
                    counter = 1
                    while audio_out.exists() or audio_out in converted_files:
                        audio_out = raw_file.with_name(f"{raw_file.stem}_{counter}.{target_fmt}")
                        counter += 1

                await ffmpeg_service.extract_audio(
                    input_file=raw_file,
                    output_file=audio_out,
                    audio_format=target_fmt,
                )
                if raw_file != audio_out:
                    raw_file.unlink(missing_ok=True)
                converted_files.append(audio_out)
            else:
                converted_files.append(raw_file)
        downloaded_files = converted_files

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
        or meta_dict.get("channel")
        or meta_dict.get("author")
        or (platform == "instagram" and _extract_instagram_username_from_url(clean_url))
        or ("instagram_user" if platform == "instagram" else None)
    )
    date_val = (
        meta_dict.get("date")
        or meta_dict.get("upload_date")
        or meta_dict.get("timestamp")
        or meta_dict.get("created_at")
        or (datetime.now(timezone.utc).strftime("%Y%m%d") if platform == "instagram" else None)
    )
    orig_name_first = (
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
    title = meta_dict.get("title") or (downloaded_files[0].stem if downloaded_files else "media")

    items_list = meta_dict.get("items") or []
    selected = request.selected_indices
    if selected:
        candidate_items = [
            items_list[i] if i < len(items_list) else None for i in selected
        ]
    else:
        candidate_items = list(items_list)

    # Correlate downloaded files with item metadata: prefer name/identifier matching, fallback to index
    matched_items: list[dict[str, Any]] = []
    available_candidates = list(enumerate(candidate_items))

    for idx, f in enumerate(downloaded_files):
        matched_idx = None
        matched_item: dict[str, Any] = {}

        # 1. Match by original_name_first, original_name, filename, or post_id in f.stem
        for c_idx, candidate in available_candidates:
            if not candidate:
                continue
            cand_dict = (
                candidate.model_dump()
                if hasattr(candidate, "model_dump")
                else (candidate if isinstance(candidate, dict) else {})
            )
            cand_names = [
                cand_dict.get("original_name_first"),
                cand_dict.get("original_name"),
                cand_dict.get("filename"),
                cand_dict.get("post_id"),
            ]
            if any(name and str(name).lower() in f.stem.lower() for name in cand_names):
                matched_idx = c_idx
                matched_item = cand_dict
                break

        # 2. Fallback match by index if no identifier match
        if matched_idx is None and idx < len(candidate_items):
            cand = candidate_items[idx]
            if cand:
                matched_item = (
                    cand.model_dump()
                    if hasattr(cand, "model_dump")
                    else (cand if isinstance(cand, dict) else {})
                )
                matched_idx = idx

        if matched_idx is not None:
            available_candidates = [
                (ci, c) for ci, c in available_candidates if ci != matched_idx
            ]

        matched_items.append(matched_item)

    formatted_files: list[Path] = []
    used_names: set[str] = set()

    for idx, f in enumerate(downloaded_files):
        file_ext = f.suffix.lstrip(".")
        item_meta = matched_items[idx] if idx < len(matched_items) else {}

        item_date = item_meta.get("date") or date_val
        item_orig = (
            item_meta.get("original_name_first")
            or item_meta.get("original_name")
            or item_meta.get("filename")
            or (orig_name_first if len(downloaded_files) == 1 else None)
            or (f.stem if f.stem and f.stem != "download" else None)
            or (media_id if media_id and media_id not in ("media", "post", task_id) else None)
            or (f"item_{idx+1}" if len(downloaded_files) > 1 else "media")
        )

        if platform == "instagram":
            candidate_name = naming_service.format_instagram_filename(
                username=uploader,
                date_str=item_date,
                original_name_first=item_orig,
                media_id=str(media_id),
                title=title,
                ext=file_ext,
            )
        else:
            candidate_name = naming_service.format_standard_filename(
                title=f"{title}_{idx+1}" if len(downloaded_files) > 1 else title,
                platform=platform,
                media_id=str(media_id),
                ext=file_ext,
            )

        # Disambiguate if collision
        if candidate_name in used_names or (
            (task_dir / candidate_name).exists() and (task_dir / candidate_name) != f
        ):
            stem = Path(candidate_name).stem
            ext_suffix = Path(candidate_name).suffix
            counter = 1
            disambiguated = f"{stem}_{counter}{ext_suffix}"
            while disambiguated in used_names or (
                (task_dir / disambiguated).exists() and (task_dir / disambiguated) != f
            ):
                counter += 1
                disambiguated = f"{stem}_{counter}{ext_suffix}"
            candidate_name = disambiguated

        used_names.add(candidate_name)
        target_path = task_dir / candidate_name
        if f != target_path:
            shutil.move(str(f), str(target_path))
        formatted_files.append(target_path)

    # Package as ZIP if multiple files and package_as_zip is True
    if request.package_as_zip and len(formatted_files) > 1:
        zip_filename = f"{platform}_bundle_{task_id}.zip"
        zip_path = task_dir / zip_filename
        zip_service.create_zip_archive(formatted_files, zip_path)
        file_size = zip_path.stat().st_size
        return DownloadResult(
            task_id=task_id,
            filename=zip_filename,
            file_path=str(zip_path),
            file_size=file_size,
            download_url=f"/api/files/{task_id}/{urllib.parse.quote(zip_filename)}",
            is_zip=True,
        )

    # Unbundled delivery for multiple files when package_as_zip is False
    if len(formatted_files) > 1:
        files_info = [
            DownloadFileInfo(
                filename=pf.name,
                file_path=str(pf),
                file_size=pf.stat().st_size,
                download_url=f"/api/files/{task_id}/{urllib.parse.quote(pf.name)}",
            )
            for pf in formatted_files
        ]
        return DownloadResult(
            task_id=task_id,
            filename=files_info[0].filename,
            file_path=files_info[0].file_path,
            file_size=sum(fi.file_size for fi in files_info),
            download_url=files_info[0].download_url,
            is_zip=False,
            files=files_info,
        )

    # Single file output
    single_res = formatted_files[0]
    return DownloadResult(
        task_id=task_id,
        filename=single_res.name,
        file_path=str(single_res),
        file_size=single_res.stat().st_size,
        download_url=f"/api/files/{task_id}/{urllib.parse.quote(single_res.name)}",
        is_zip=False,
    )
