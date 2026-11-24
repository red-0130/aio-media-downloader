"""Filename formatting and sanitization service."""

import re
from datetime import datetime, timezone
from typing import Any

# Characters forbidden in Windows/Linux/macOS filenames
ILLEGAL_CHARS_PATTERN = re.compile(r'[/\\:*?"<>|]')
WHITESPACE_PATTERN = re.compile(r"\s+")


def _truncate_to_bytes(text: str, max_bytes: int = 240) -> str:
    """Truncate text so its UTF-8 byte representation does not exceed max_bytes.

    Encodes to UTF-8, slices at max_bytes, decodes with errors='ignore'
    to avoid splitting multi-byte character sequences, and strips trailing
    periods, spaces, underscores, or hyphens.
    """
    if not text or max_bytes <= 0:
        return ""

    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated.rstrip(". _-")


def sanitize_filename(
    name: str,
    max_length: int = 200,
    max_bytes: int | None = None,
) -> str:
    """Sanitize filename to be safe across Linux, Windows, and macOS."""
    if not name or not isinstance(name, str):
        return "download"

    # Remove non-printable control characters
    cleaned = "".join(c for c in name if ord(c) >= 32)

    # Replace forbidden characters with empty string or underscore
    cleaned = ILLEGAL_CHARS_PATTERN.sub("", cleaned)

    # Normalize multiple whitespace into single space
    cleaned = WHITESPACE_PATTERN.sub(" ", cleaned).strip()

    # Strip leading/trailing dots and spaces (problematic on Windows)
    cleaned = cleaned.strip(". ")

    # Determine effective UTF-8 byte budget
    effective_max_bytes = max_bytes if max_bytes is not None else min(max_length, 240)

    # Truncate by character length if needed
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(". ")

    # Truncate safely by UTF-8 byte budget to prevent OSError: [Errno 36] File name too long
    cleaned = _truncate_to_bytes(cleaned, max_bytes=effective_max_bytes)

    if not cleaned:
        return "download"

    return cleaned


def _parse_to_yyyymmdd(date_val: Any) -> str | None:
    """Parse various date formats into YYYYMMDD string."""
    if not date_val:
        return None

    # If already an 8-digit string like 20240512
    date_str = str(date_val).strip()
    if re.fullmatch(r"\d{8}", date_str):
        return date_str

    # Numeric timestamp (int or float)
    try:
        ts = float(date_str)
        # Check reasonable unix timestamp range
        if 100000000 < ts < 2500000000:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.strftime("%Y%m%d")
    except ValueError:
        pass

    # ISO formats via datetime.fromisoformat (supports 'Z', offsets, dates, datetimes in 3.11+)
    try:
        clean_iso = date_str.replace("Z", "+00:00") if date_str.endswith("Z") else date_str
        dt = datetime.fromisoformat(clean_iso)
        return dt.strftime("%Y%m%d")
    except Exception:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y%m%d")
        except ValueError:
            continue

    return None


def _clean_extension(ext: str | None, default: str = "mp4") -> str:
    """Clean and validate file extension, falling back to default if empty, whitespace, or invalid."""
    if not ext or not isinstance(ext, str):
        return default
    # Strip whitespace and leading/trailing dots
    cleaned = ext.strip().strip(".")
    # Remove illegal characters
    cleaned = ILLEGAL_CHARS_PATTERN.sub("", cleaned).strip().lower()
    if not cleaned or cleaned == "download":
        return default
    return cleaned


def format_instagram_filename(
    username: str | None,
    date_str: Any | None,
    original_name_first: str | None,
    media_id: str | None,
    title: str | None,
    ext: str = "mp4",
) -> str:
    """Format Instagram filename according to project specifications.

    Format: <username>_<YYYYMMDD>_<ORIGINAL_NAME_FIRST>.<ext>
    Fallbacks:
      - <username>_<id>.<ext>
      - <username>_<title>.<ext>
      - instagram_<id>.<ext>
    """
    clean_ext = _clean_extension(ext, "mp4")
    clean_user = sanitize_filename(username) if username else None
    if clean_user == "download":
        clean_user = None

    clean_id = sanitize_filename(media_id) if media_id else None
    if clean_id == "download":
        clean_id = None

    clean_title = sanitize_filename(title) if title else None
    if clean_title == "download":
        clean_title = None

    date_part = _parse_to_yyyymmdd(date_str)
    orig_name = sanitize_filename(original_name_first) if original_name_first else None
    if orig_name == "download":
        orig_name = None

    # Primary convention: <username>_<YYYYMMDD>_<ORIGINAL_NAME_FIRST>.<ext>
    if clean_user and date_part and orig_name:
        stem = f"{clean_user}_{date_part}_{orig_name}"
    # Fallback 1: <username>_<id>.<ext>
    elif clean_user and clean_id:
        stem = f"{clean_user}_{clean_id}"
    # Fallback 2: <username>_<title>.<ext>
    elif clean_user and clean_title:
        stem = f"{clean_user}_{clean_title}"
    # Fallback 3: instagram_<id>.<ext>
    elif clean_id:
        stem = f"instagram_{clean_id}"
    elif clean_user:
        stem = f"{clean_user}_media"
    else:
        stem = "instagram_media"

    # Ensure total generated filename (including extension) does not exceed 255 bytes
    # (POSIX NAME_MAX), enforcing a byte budget for the stem (max 240 bytes).
    ext_bytes = len(f".{clean_ext}".encode("utf-8"))
    max_stem_bytes = max(1, min(240, 255 - ext_bytes))
    stem = _truncate_to_bytes(stem, max_bytes=max_stem_bytes)
    if not stem:
        stem = "instagram_media"

    return f"{stem}.{clean_ext}"


def format_standard_filename(
    title: str | None,
    platform: str,
    media_id: str | None,
    ext: str = "mp4",
) -> str:
    """Format standard media filename, prioritizing original source title."""
    clean_ext = _clean_extension(ext, "mp4")
    clean_platform = sanitize_filename(platform).lower()
    if clean_platform == "download":
        clean_platform = "media"

    # Ensure total generated filename (including extension) does not exceed 255 bytes (POSIX NAME_MAX).
    # Budget stem bytes so that len(f"{stem}.{clean_ext}".encode("utf-8")) <= 255.
    ext_bytes = len(f".{clean_ext}".encode("utf-8"))
    max_stem_bytes = max(1, min(240 - len(clean_ext.encode("utf-8")), 255 - ext_bytes))

    if title:
        sanitized_title = sanitize_filename(title, max_length=240, max_bytes=max_stem_bytes)
        if sanitized_title and sanitized_title != "download":
            stem = _truncate_to_bytes(sanitized_title, max_bytes=max_stem_bytes)
            if not stem:
                stem = f"{clean_platform}_media"
            return f"{stem}.{clean_ext}"

    if media_id:
        clean_id = sanitize_filename(media_id, max_length=200, max_bytes=max_stem_bytes)
        if clean_id and clean_id != "download":
            stem = f"{clean_platform}_{clean_id}"
            stem = _truncate_to_bytes(stem, max_bytes=max_stem_bytes)
            if not stem:
                stem = f"{clean_platform}_media"
            return f"{stem}.{clean_ext}"

    stem = f"{clean_platform}_media"
    stem = _truncate_to_bytes(stem, max_bytes=max_stem_bytes)
    if not stem:
        stem = "media"
    return f"{stem}.{clean_ext}"
