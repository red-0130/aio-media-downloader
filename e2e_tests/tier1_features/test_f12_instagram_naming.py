"""Tier 1 Feature Coverage: F12 - Instagram File Naming."""

from app.services import naming_service


def test_instagram_naming_full_metadata():
    """Verify Instagram naming with complete metadata produces username_YYYYMMDD_original.ext."""
    res = naming_service.format_instagram_filename(
        username="nature_lens",
        date_str="2024-05-12 18:30:00",
        original_name_first="sunset_point",
        media_id="334819201",
        title="Sunset over hills",
        ext="jpg",
    )
    assert res == "nature_lens_20240512_sunset_point.jpg"


def test_instagram_naming_missing_date_fallback():
    """Verify missing post date falls back to username_id.ext."""
    res = naming_service.format_instagram_filename(
        username="nature_lens",
        date_str=None,
        original_name_first="sunset_point",
        media_id="334819201",
        title="Sunset over hills",
        ext="jpg",
    )
    assert res == "nature_lens_334819201.jpg"


def test_instagram_naming_missing_original_name_fallback():
    """Verify missing original name falls back to username_id or username_title."""
    res_with_id = naming_service.format_instagram_filename(
        username="traveler",
        date_str="2024-05-10",
        original_name_first=None,
        media_id="94821038",
        title=None,
        ext="mp4",
    )
    assert res_with_id == "traveler_94821038.mp4"

    res_with_title = naming_service.format_instagram_filename(
        username="traveler",
        date_str="2024-05-10",
        original_name_first=None,
        media_id=None,
        title="Kyoto Morning",
        ext="mp4",
    )
    assert res_with_title == "traveler_Kyoto Morning.mp4"


def test_instagram_naming_missing_username_fallback():
    """Verify missing username falls back to instagram_<id>.<ext>."""
    res = naming_service.format_instagram_filename(
        username=None,
        date_str="2024-05-12",
        original_name_first="photo1",
        media_id="334819201",
        title="Title",
        ext="jpg",
    )
    assert res == "instagram_334819201.jpg"


def test_instagram_naming_date_parsing_formats():
    """Verify various date formats (unix ts, ISO, standard YYYY-MM-DD) are normalized to YYYYMMDD."""
    dates = [
        ("1715538600", "20240512"),  # Unix timestamp
        ("2024-05-12T18:30:00Z", "20240512"),  # ISO 8601 with Z
        ("2024-05-12", "20240512"),  # YYYY-MM-DD
        ("20240512", "20240512"),  # 8-digit already
        ("2024/05/12", "20240512"),  # Slash format
    ]
    for date_input, expected_date in dates:
        res = naming_service.format_instagram_filename(
            username="user",
            date_str=date_input,
            original_name_first="orig",
            media_id="id1",
            title=None,
            ext="mp4",
        )
        assert expected_date in res, f"Expected {expected_date} in {res} for date input {date_input}"


def test_instagram_naming_sanitizes_username_and_id():
    """Verify illegal characters in username and media_id are sanitized."""
    res = naming_service.format_instagram_filename(
        username="user/name:test",
        date_str=None,
        original_name_first=None,
        media_id="id?*123",
        title=None,
        ext="mp4",
    )
    assert "/" not in res
    assert ":" not in res
    assert "?" not in res
    assert "*" not in res
    assert res == "usernametest_id123.mp4"
