"""Tier 1 Feature Coverage: F11 - Standard Media Naming."""

from app.services import naming_service


def test_standard_naming_uses_original_title():
    """Verify standard filename prioritizes the original source title."""
    result = naming_service.format_standard_filename(
        title="Rick Astley - Never Gonna Give You Up",
        platform="youtube",
        media_id="dQw4w9WgXcQ",
        ext="mp4",
    )
    assert result == "Rick Astley - Never Gonna Give You Up.mp4"


def test_standard_naming_strips_illegal_characters():
    """Verify illegal filesystem characters are stripped from filename."""
    dirty_title = 'My Video: Episode 1/2? *Awesome* <Must Watch> | "Final"'
    result = naming_service.format_standard_filename(
        title=dirty_title,
        platform="youtube",
        media_id="12345",
        ext="mp4",
    )
    assert "/" not in result
    assert "\\" not in result
    assert ":" not in result
    assert "*" not in result
    assert "?" not in result
    assert '"' not in result
    assert "<" not in result
    assert ">" not in result
    assert "|" not in result
    assert result.endswith(".mp4")


def test_standard_naming_preserves_unicode_titles():
    """Verify Unicode characters (Japanese, Cyrillic, emojis, accents) are preserved."""
    titles = [
        ("君の名は - Sparkle", "君の名は - Sparkle.mp4"),
        ("Funny Dog 🐶 Video", "Funny Dog 🐶 Video.mp4"),
        ("Café Müller Live", "Café Müller Live.mp4"),
        ("Привет мир", "Привет мир.mp4"),
    ]
    for title, expected in titles:
        res = naming_service.format_standard_filename(
            title=title, platform="youtube", media_id="test", ext="mp4"
        )
        assert res == expected


def test_standard_naming_fallback_to_platform_and_id():
    """Verify empty or None title falls back to <platform>_<media_id>.<ext>."""
    res_none = naming_service.format_standard_filename(
        title=None,
        platform="tiktok",
        media_id="7369123456",
        ext="mp4",
    )
    assert res_none == "tiktok_7369123456.mp4"

    res_empty = naming_service.format_standard_filename(
        title="   ",
        platform="twitter",
        media_id="178901234",
        ext="mp4",
    )
    assert res_empty == "twitter_178901234.mp4"


def test_standard_naming_max_length_truncation():
    """Verify excessively long titles are truncated safely within filesystem limit (255) without breaking extension."""
    long_title = "A" * 300
    res = naming_service.format_standard_filename(
        title=long_title,
        platform="youtube",
        media_id="12345",
        ext="mp4",
    )
    assert len(res) <= 255
    assert res.endswith(".mp4")
    assert res.startswith("AAAA")


def test_standard_naming_leading_trailing_dots_and_spaces():
    """Verify leading and trailing dots and spaces are stripped."""
    title = " ...Special Video Episode...  "
    res = naming_service.format_standard_filename(
        title=title,
        platform="youtube",
        media_id="vid1",
        ext="mp4",
    )
    assert res == "Special Video Episode.mp4"
