"""Unit tests for naming conventions and filename sanitization."""

from pathlib import Path

from app.services.naming_service import (
    _parse_to_yyyymmdd,
    _truncate_to_bytes,
    disambiguate_filename,
    format_instagram_filename,
    format_standard_filename,
    sanitize_filename,
)


def test_sanitize_filename_removes_illegal_characters():
    dirty = 'Sample: Video / Post * Title ? With <Illegal> "Quotes" & | Pipe'
    cleaned = sanitize_filename(dirty)
    assert ":" not in cleaned
    assert "/" not in cleaned
    assert "*" not in cleaned
    assert "?" not in cleaned
    assert "<" not in cleaned
    assert ">" not in cleaned
    assert '"' not in cleaned
    assert "|" not in cleaned
    assert cleaned == "Sample Video Post Title With Illegal Quotes & Pipe"


def test_sanitize_filename_whitespace_and_dots():
    dirty = "  ...   My   Cool   Download...   "
    cleaned = sanitize_filename(dirty)
    assert cleaned == "My Cool Download"


def test_sanitize_filename_empty_and_control_chars():
    assert sanitize_filename("") == "download"
    assert sanitize_filename(None) == "download"
    assert sanitize_filename("\x00\x1f\t   ") == "download"


def test_instagram_filename_full_metadata():
    filename = format_instagram_filename(
        username="john_doe",
        date_str="2024-05-12T14:30:00Z",
        original_name_first="43829104_photo1",
        media_id="C7XYZ",
        title="Post Title",
        ext="jpg",
    )
    assert filename == "john_doe_20240512_43829104_photo1.jpg"


def test_instagram_filename_numeric_timestamp():
    # 1715522400 is 2024-05-12 14:00:00 UTC
    filename = format_instagram_filename(
        username="traveler",
        date_str=1715522400,
        original_name_first="img_orig_01",
        media_id="12345",
        title="Travel",
        ext="mp4",
    )
    assert filename == "traveler_20240512_img_orig_01.mp4"


def test_parse_to_yyyymmdd_unix_timestamp_utc():
    # 1716508800 is 2024-05-24 00:00:00 UTC
    assert _parse_to_yyyymmdd(1716508800) == "20240524"
    assert _parse_to_yyyymmdd("1716508800") == "20240524"
    # 1716508799 is 2024-05-23 23:59:59 UTC
    assert _parse_to_yyyymmdd(1716508799) == "20240523"


def test_instagram_filename_missing_date_fallback_to_id():
    filename = format_instagram_filename(
        username="jane_doe",
        date_str=None,
        original_name_first="orig_name",
        media_id="C987654",
        title="Jane's post",
        ext="mp4",
    )
    assert filename == "jane_doe_C987654.mp4"


def test_instagram_filename_missing_original_name_fallback_to_id():
    filename = format_instagram_filename(
        username="jane_doe",
        date_str="20240512",
        original_name_first=None,
        media_id="C987654",
        title="Jane's post",
        ext="mp4",
    )
    assert filename == "jane_doe_C987654.mp4"


def test_instagram_filename_missing_date_and_id_fallback_to_title():
    filename = format_instagram_filename(
        username="blogger",
        date_str=None,
        original_name_first=None,
        media_id=None,
        title="My Day in Tokyo",
        ext="mp4",
    )
    assert filename == "blogger_My Day in Tokyo.mp4"


def test_instagram_filename_missing_username_fallback_to_id():
    filename = format_instagram_filename(
        username=None,
        date_str=None,
        original_name_first=None,
        media_id="99887766",
        title="Untitled",
        ext="jpg",
    )
    assert filename == "instagram_99887766.jpg"


def test_standard_filename_prioritizes_source_title():
    filename = format_standard_filename(
        title="Awesome Song [Official Video] 4K",
        platform="youtube",
        media_id="abc1234",
        ext="mp4",
    )
    assert filename == "Awesome Song [Official Video] 4K.mp4"


def test_standard_filename_fallback_when_title_missing():
    filename = format_standard_filename(
        title=None,
        platform="twitter",
        media_id="1789456123",
        ext="mp4",
    )
    assert filename == "twitter_1789456123.mp4"


def test_standard_filename_fallback_when_title_and_id_missing():
    filename = format_standard_filename(
        title="",
        platform="tiktok",
        media_id=None,
        ext="mp4",
    )
    assert filename == "tiktok_media.mp4"


def test_instagram_filename_length_clamping():
    # Long username (150 chars) and long original name (150 chars)
    long_user = "a" * 150
    long_orig = "b" * 150
    filename = format_instagram_filename(
        username=long_user,
        date_str="20240501",
        original_name_first=long_orig,
        media_id="12345",
        title="Sample",
        ext="mp4",
    )
    assert len(filename) <= 255
    stem = filename.rsplit(".", 1)[0]
    assert len(stem) <= 240
    assert filename.endswith(".mp4")


def test_instagram_and_standard_filename_empty_or_whitespace_ext_fallback():
    # Empty, whitespace, or just dots must cleanly fall back to "mp4" (not ".download")
    for bad_ext in ("", "   ", ".", "...", None):
        insta_name = format_instagram_filename(
            username="user",
            date_str="20240501",
            original_name_first="photo",
            media_id="123",
            title="test",
            ext=bad_ext,
        )
        assert insta_name.endswith(".mp4"), f"Failed for insta ext={bad_ext!r}: {insta_name}"
        assert not insta_name.endswith(".download")

        std_name = format_standard_filename(
            title="My Video",
            platform="youtube",
            media_id="123",
            ext=bad_ext,
        )
        assert std_name.endswith(".mp4"), f"Failed for std ext={bad_ext!r}: {std_name}"
        assert not std_name.endswith(".download")


def test_standard_filename_length_clamping():
    long_title = "super_long_media_title_" * 20
    filename = format_standard_filename(
        title=long_title,
        platform="youtube",
        media_id="123",
        ext="mp4",
    )
    assert len(filename) <= 255
    stem = filename.rsplit(".", 1)[0]
    assert len(stem) <= 240
    assert filename.endswith(".mp4")


def test_truncate_to_bytes_helper():
    """Verify _truncate_to_bytes slices bytes safely without splitting characters and strips trailing punctuation."""
    # Empty and invalid budgets
    assert _truncate_to_bytes("", 240) == ""
    assert _truncate_to_bytes("hello", 0) == ""
    assert _truncate_to_bytes("hello", -5) == ""

    # Short string within budget is unchanged
    assert _truncate_to_bytes("hello_world", 240) == "hello_world"

    # Truncation with trailing separator stripped
    assert _truncate_to_bytes("hello_world_very_long", 12) == "hello_world"

    # CJK character boundary safety: 3 bytes/char
    cjk = "测试" * 50  # 100 chars, 300 bytes
    truncated = _truncate_to_bytes(cjk, 240)
    assert len(truncated.encode("utf-8")) <= 240
    # Decoded cleanly without replacement character
    assert "\ufffd" not in truncated

    # Odd byte count does not corrupt multi-byte character
    truncated_odd = _truncate_to_bytes(cjk, 7)
    assert len(truncated_odd.encode("utf-8")) == 6  # 2 full CJK chars (3 * 2 = 6 <= 7)
    assert truncated_odd == "测试"


def test_sanitize_filename_multibyte_cjk_and_emoji():
    """Verify sanitize_filename truncates by byte budget preventing POSIX NAME_MAX overflows."""
    long_cjk = "你好世界" * 50  # 200 CJK chars, 600 bytes
    sanitized = sanitize_filename(long_cjk)
    assert len(sanitized.encode("utf-8")) <= 200
    assert "\ufffd" not in sanitized

    long_emoji = "🔥🚀🎉" * 40  # 120 emojis, 480 bytes
    sanitized_emoji = sanitize_filename(long_emoji)
    assert len(sanitized_emoji.encode("utf-8")) <= 200
    assert "\ufffd" not in sanitized_emoji


def test_standard_filename_cjk_multibyte_long_title(tmp_path: Path):
    """Verify CJK multi-byte long titles (100+ CJK characters) do not exceed 255 bytes and create files on disk."""
    long_cjk_title = "测试视频" * 50  # 200 CJK characters (600 UTF-8 bytes)
    filename = format_standard_filename(
        title=long_cjk_title,
        platform="youtube",
        media_id="cjk_vid_123",
        ext="mp4",
    )
    # Check byte length <= 255 (POSIX NAME_MAX)
    assert len(filename.encode("utf-8")) <= 255
    assert filename.endswith(".mp4")

    # Verify real creation on filesystem succeeds without OSError: [Errno 36] File name too long
    file_path = tmp_path / filename
    file_path.touch()
    assert file_path.exists()
    assert file_path.stat().st_size == 0


def test_standard_filename_emoji_multibyte_long_title(tmp_path: Path):
    """Verify Emoji multi-byte long titles (80+ emojis) do not exceed 255 bytes and create files on disk."""
    long_emoji_title = "🔥⚽🚀🎉🌟" * 20  # 100 emojis (400 UTF-8 bytes)
    filename = format_standard_filename(
        title=long_emoji_title,
        platform="youtube",
        media_id="emoji_vid_123",
        ext="mp4",
    )
    assert len(filename.encode("utf-8")) <= 255
    assert filename.endswith(".mp4")

    file_path = tmp_path / filename
    file_path.touch()
    assert file_path.exists()


def test_instagram_filename_cjk_multibyte_long_fields(tmp_path: Path):
    """Verify Instagram filenames with long CJK username, date, and original filename do not exceed 255 bytes."""
    long_user = "用户名称" * 20  # 80 CJK chars (240 bytes)
    long_orig = "原始照片名称" * 30  # 180 CJK chars (540 bytes)
    filename = format_instagram_filename(
        username=long_user,
        date_str="20240520",
        original_name_first=long_orig,
        media_id="ig_12345",
        title="标题" * 30,
        ext="jpg",
    )
    assert len(filename.encode("utf-8")) <= 255
    stem = filename.rsplit(".", 1)[0]
    assert len(stem.encode("utf-8")) <= 240
    assert filename.endswith(".jpg")

    file_path = tmp_path / filename
    file_path.touch()
    assert file_path.exists()


def test_instagram_filename_emoji_multibyte_fields(tmp_path: Path):
    """Verify Instagram filenames with emoji fields do not exceed 255 bytes and can be created on filesystem."""
    emoji_user = "👑🔥" * 25  # 50 emojis (200 bytes)
    emoji_orig = "📸🎉" * 40  # 80 emojis (320 bytes)
    filename = format_instagram_filename(
        username=emoji_user,
        date_str="2024-05-20",
        original_name_first=emoji_orig,
        media_id="ig_emoji_99",
        title="Emoji Story",
        ext="mp4",
    )
    assert len(filename.encode("utf-8")) <= 255
    stem = filename.rsplit(".", 1)[0]
    assert len(stem.encode("utf-8")) <= 240
    assert filename.endswith(".mp4")

    file_path = tmp_path / filename
    file_path.touch()
    assert file_path.exists()


def test_multibyte_arabic_and_cyrillic_long_titles(tmp_path: Path):
    """Verify Arabic and Cyrillic 2-byte UTF-8 titles do not exceed 255 bytes and succeed on filesystem."""
    arabic_title = "عنوان الفيديو العربي طويل جدا للمعاينة والاختبار والتأكد " * 5
    fn_ar = format_standard_filename(
        title=arabic_title,
        platform="youtube",
        media_id="ar_123",
        ext="mp4",
    )
    assert len(fn_ar.encode("utf-8")) <= 255
    file_path_ar = tmp_path / fn_ar
    file_path_ar.touch()
    assert file_path_ar.exists()

    cyrillic_title = "Длинное название видео на русском языке для проверки длины файла " * 5
    fn_ru = format_standard_filename(
        title=cyrillic_title,
        platform="youtube",
        media_id="ru_123",
        ext="mp4",
    )
    assert len(fn_ru.encode("utf-8")) <= 255
    file_path_ru = tmp_path / fn_ru
    file_path_ru.touch()
    assert file_path_ru.exists()


def test_disambiguate_filename_handles_sets_dirs_and_ignore_path(tmp_path: Path):
    used: set[str] = set()
    assert disambiguate_filename("photo.jpg", used) == "photo.jpg"
    assert disambiguate_filename("photo.jpg", used) == "photo_1.jpg"
    assert disambiguate_filename("photo_2.jpg", used) == "photo_2.jpg"
    assert disambiguate_filename("photo.jpg", used) == "photo_3.jpg"

    existing = tmp_path / "clip.mp3"
    existing.touch()
    source_vid = tmp_path / "clip.mp4"
    source_vid.touch()

    disk_used: set[str] = set()
    assert (
        disambiguate_filename("clip.mp3", disk_used, target_dir=tmp_path, ignore_path=source_vid)
        == "clip_1.mp3"
    )
    assert (
        disambiguate_filename("clip.mp3", set(), target_dir=tmp_path, ignore_path=existing)
        == "clip.mp3"
    )
