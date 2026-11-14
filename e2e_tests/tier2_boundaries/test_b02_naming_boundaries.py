"""Tier 2 Boundary Tests: B02 - Media File Naming & Sanitization Boundaries.

Covers:
- 255-character filesystem filename limit (both Instagram and standard media)
- Filename titles consisting entirely of forbidden characters
- Leading and trailing periods and whitespace stripping
- RTL (right-to-left) Unicode and override characters
- Null bytes and low ASCII control character sanitization
- Safe preservation of non-forbidden punctuation
- Multi-byte Emoji preservation in filenames
- Very long or invalid file extensions
- Path traversal sequences embedded in title/username fields
- Instagram naming fallback cascade under degraded metadata
- Filesystem creation verification with boundary names
"""

from pathlib import Path
import pytest

from app.services import naming_service, security


def test_naming_255_char_filesystem_limit_instagram(tmp_path: Path):
    """Verify Instagram filenames never exceed 255 characters even with extreme inputs."""
    huge_user = "user_" + ("u" * 150)
    huge_date = "20240520"
    huge_orig = "orig_photo_" + ("o" * 150)
    huge_id = "media_" + ("9" * 100)
    huge_title = "caption_" + ("t" * 150)

    filename = naming_service.format_instagram_filename(
        username=huge_user,
        date_str=huge_date,
        original_name_first=huge_orig,
        media_id=huge_id,
        title=huge_title,
        ext="mp4",
    )

    assert len(filename) <= 255, f"Filename exceeds 255 chars: {len(filename)}"
    assert filename.endswith(".mp4")

    # Verify real creation on filesystem succeeds without OSError Errno 36
    file_path = tmp_path / filename
    file_path.write_text("boundary test content", encoding="utf-8")
    assert file_path.exists()


def test_naming_255_char_filesystem_limit_standard(tmp_path: Path):
    """Verify standard filenames never exceed 255 characters even with 500+ character titles."""
    huge_title = "Video Title With Extreme Length " + ("A" * 400)
    filename = naming_service.format_standard_filename(
        title=huge_title,
        platform="youtube",
        media_id="vid_12345",
        ext="mkv",
    )

    assert len(filename) <= 255
    assert filename.endswith(".mkv")

    file_path = tmp_path / filename
    file_path.write_bytes(b"dummy")
    assert file_path.exists()


def test_naming_only_forbidden_characters_fallback():
    """Verify titles consisting entirely of forbidden chars fall back safely instead of empty string."""
    forbidden_string = '???///:::***"""<<<>>>|||'
    sanitized = naming_service.sanitize_filename(forbidden_string)
    assert sanitized == "download"

    # In standard formatting
    filename = naming_service.format_standard_filename(
        title=forbidden_string,
        platform="youtube",
        media_id="12345",
        ext="mp4",
    )
    assert filename == "youtube_12345.mp4"


def test_naming_strip_leading_trailing_periods_and_spaces():
    """Verify leading and trailing periods and spaces are stripped to prevent Windows/POSIX issues."""
    dirty_name = "   ...   awesome_media_clip   ...   "
    sanitized = naming_service.sanitize_filename(dirty_name)
    assert sanitized == "awesome_media_clip"

    # Dots only
    dots_name = "....hidden_name...."
    sanitized_dots = naming_service.sanitize_filename(dots_name)
    assert sanitized_dots == "hidden_name"


def test_naming_rtl_characters_preservation(tmp_path: Path):
    """Verify RTL (Arabic, Hebrew) characters are preserved and safe on filesystem."""
    arabic_title = "فيديو جميل ومثير 2024"
    sanitized = naming_service.sanitize_filename(arabic_title)
    assert "فيديو جميل" in sanitized

    # RTL override character \u202e
    rtl_override = "song\u202egpj.mp3"
    sanitized_override = naming_service.sanitize_filename(rtl_override)
    assert len(sanitized_override) > 0

    target = tmp_path / f"{sanitized}.mp4"
    target.write_text("rtl media test")
    assert target.exists()


def test_naming_null_bytes_and_low_control_characters_removed(tmp_path: Path):
    """Verify null bytes (\x00) and ASCII control characters (< 32) are removed."""
    poisoned = "dangerous\x00file\x01\x1f\x0bname"
    sanitized = naming_service.sanitize_filename(poisoned)
    assert "\x00" not in sanitized
    assert sanitized == "dangerousfilename"

    # Creating a file with raw \x00 raises ValueError; sanitized version must succeed
    target = tmp_path / f"{sanitized}.mp4"
    target.write_text("null byte clean")
    assert target.exists()


def test_naming_special_punctuation_safe_handling():
    """Verify allowed punctuation is preserved while illegal characters are eliminated."""
    mixed_punctuation = "clip-1 [1080p] (official) #trending! @user {v1} & more; $100% ^top ~.mp4"
    sanitized = naming_service.sanitize_filename(mixed_punctuation)
    assert "[" in sanitized and "]" in sanitized
    assert "(" in sanitized and ")" in sanitized
    assert "trending!" in sanitized
    assert "@user" in sanitized
    assert "$100%" in sanitized


def test_naming_emoji_in_title_and_username(tmp_path: Path):
    """Verify multi-byte emojis in title and username are preserved without corrupting filename."""
    emoji_title = "🔥 Best Highlights ⚽ Goals & Skills 🚀"
    filename = naming_service.format_standard_filename(
        title=emoji_title,
        platform="youtube",
        media_id="yt_987",
        ext="mp4",
    )
    assert "🔥" in filename
    assert "⚽" in filename
    assert "🚀" in filename

    target = tmp_path / filename
    target.write_bytes(b"emoji file")
    assert target.exists()


def test_naming_extension_cleaning_and_fallbacks():
    """Verify long, dirty, or empty extensions are cleaned or defaulted to mp4."""
    # Empty / whitespace extension
    assert naming_service._clean_extension("") == "mp4"
    assert naming_service._clean_extension("   ") == "mp4"
    assert naming_service._clean_extension(None) == "mp4"

    # Extension with dots and uppercase
    assert naming_service._clean_extension("..MP4..") == "mp4"
    assert naming_service._clean_extension(" .WAV ") == "wav"

    # Extension with illegal characters
    assert naming_service._clean_extension("m:p*4?") == "mp4"


def test_naming_deep_path_traversal_attempts_in_names(tmp_path: Path):
    """Verify directory traversal tokens (../../) embedded in title or username are sanitized."""
    traversal_title = "../../../../etc/passwd"
    sanitized = naming_service.sanitize_filename(traversal_title)
    assert "/" not in sanitized
    assert "\\" not in sanitized
    assert ".." not in sanitized

    # Formatted standard filename is strictly a leaf file name
    formatted = naming_service.format_standard_filename(
        title=traversal_title,
        platform="youtube",
        media_id="123",
        ext="mp4",
    )
    assert "/" not in formatted
    assert "\\" not in formatted

    # Safe path resolution confirms it stays in tmp_path
    safe_path = security.validate_safe_path(tmp_path, formatted)
    assert safe_path.parent == tmp_path.resolve()


def test_naming_instagram_missing_metadata_cascading_fallbacks():
    """Verify Instagram naming fallback cascade when various metadata components are missing."""
    # 1. Full metadata -> <username>_<YYYYMMDD>_<ORIGINAL_NAME_FIRST>.<ext>
    f1 = naming_service.format_instagram_filename("alice", "2024-03-15", "photo1", "id99", "caption")
    assert f1 == "alice_20240315_photo1.mp4"

    # 2. Missing date -> <username>_<id>.<ext>
    f2 = naming_service.format_instagram_filename("alice", None, "photo1", "id99", "caption")
    assert f2 == "alice_id99.mp4"

    # 3. Missing date & id -> <username>_<title>.<ext>
    f3 = naming_service.format_instagram_filename("alice", None, None, None, "caption")
    assert f3 == "alice_caption.mp4"

    # 4. Missing username -> instagram_<id>.<ext>
    f4 = naming_service.format_instagram_filename(None, "2024-03-15", "photo1", "id99", "caption")
    assert f4 == "instagram_id99.mp4"

    # 5. Missing all fields -> instagram_media.<ext>
    f5 = naming_service.format_instagram_filename(None, None, None, None, None)
    assert f5 == "instagram_media.mp4"


def test_naming_consecutive_spaces_normalized_to_single_space():
    """Verify excessive internal whitespace is normalized to a single space."""
    spaced = "video    with     lots     of     spaces"
    sanitized = naming_service.sanitize_filename(spaced)
    assert sanitized == "video with lots of spaces"
