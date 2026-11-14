"""Unit tests for gallery-dl parsing, authentication classification, and router fallback."""

import pytest
from unittest.mock import AsyncMock, patch

from app.services import gallerydl_service, router, ytdlp_service
from app.services.gallerydl_service import parse_gallerydl_json
from app.services.ytdlp_service import AuthRequiredError, ExtractionError, RateLimitError, classify_error


def test_parse_gallerydl_json_multiline_formatted_array():
    """Verify parse_gallerydl_json handles multi-line formatted JSON array from gallery-dl -j."""
    raw = """[
  [
    2,
    {
      "category": "instagram",
      "user": "danataranova",
      "description": "More photos from my shoot at Neon!",
      "post_id": "DfsTsqUEYfw"
    }
  ],
  [
    3,
    "https://instagram.com/p/DfsTsqUEYfw/1.jpg",
    {
      "extension": "jpg",
      "width": 1080,
      "height": 1350,
      "date": "2026-11-13 12:00:00"
    }
  ],
  [
    3,
    "https://instagram.com/p/DfsTsqUEYfw/2.jpg",
    {
      "extension": "jpg",
      "width": 1080,
      "height": 1350,
      "date": "2026-11-13 12:00:00"
    }
  ],
  [
    3,
    "https://instagram.com/p/DfsTsqUEYfw/3.jpg",
    {
      "extension": "jpg",
      "width": 1080,
      "height": 1350,
      "date": "2026-11-13 12:00:00"
    }
  ]
]"""
    items = parse_gallerydl_json(raw)
    assert len(items) == 3
    # Check that Type 3 extracted URLs and merged Type 2 category metadata
    assert items[0]["url"] == "https://instagram.com/p/DfsTsqUEYfw/1.jpg"
    assert items[0]["user"] == "danataranova"
    assert items[0]["description"] == "More photos from my shoot at Neon!"
    assert items[0]["post_id"] == "DfsTsqUEYfw"
    assert items[0]["extension"] == "jpg"
    assert items[1]["url"] == "https://instagram.com/p/DfsTsqUEYfw/2.jpg"
    assert items[2]["url"] == "https://instagram.com/p/DfsTsqUEYfw/3.jpg"


def test_parse_gallerydl_json_instagram_login_redirect():
    """Verify parse_gallerydl_json raises AuthRequiredError on Instagram login redirect."""
    raw = """[
  [
    -1,
    {
      "error": "AbortExtraction",
      "message": "HTTP redirect to login page (https://www.instagram.com/accounts/login/)"
    }
  ]
]"""
    with pytest.raises(AuthRequiredError) as exc_info:
        parse_gallerydl_json(raw)
    assert "Authentication required" in str(exc_info.value)
    assert "login page" in str(exc_info.value)


def test_parse_gallerydl_json_twitter_unavailable():
    """Verify parse_gallerydl_json raises AuthRequiredError on Twitter 'Unavailable' error."""
    raw = """[
  [
    -1,
    {
      "error": "AbortExtraction",
      "message": "'Unavailable'"
    }
  ]
]"""
    with pytest.raises(AuthRequiredError) as exc_info:
        parse_gallerydl_json(raw)
    assert "Authentication required" in str(exc_info.value)


def test_classify_error_extended_patterns():
    """Test extended error classification for various platform error strings."""
    # Instagram login redirect
    err_ig = classify_error("HTTP redirect to login page (https://www.instagram.com/accounts/login/)")
    assert isinstance(err_ig, AuthRequiredError)

    # Instagram private account
    err_priv = classify_error("This account is private. Sign in to view.")
    assert isinstance(err_priv, AuthRequiredError)

    # Twitter unavailable
    err_tw = classify_error("[twitter][error] 'Unavailable'")
    assert isinstance(err_tw, AuthRequiredError)

    # Twitter rate limit
    err_rate = classify_error("HTTP Error 429: Too Many Requests")
    assert isinstance(err_rate, RateLimitError)

    # Unrelated error
    err_gen = classify_error("Connection timed out after 30000ms")
    assert isinstance(err_gen, ExtractionError)
    assert not isinstance(err_gen, AuthRequiredError)


@pytest.mark.asyncio
async def test_router_inspect_instagram_photo_carousel_auth_preserved():
    """Verify router.inspect raises AuthRequiredError when gallery-dl gets login redirect and yt-dlp has no video."""
    target_url = "https://www.instagram.com/p/DfsTsqUEYfw/"

    # gallery-dl raises AuthRequiredError due to login redirect
    gdl_err = AuthRequiredError("Authentication required: Please provide valid cookies in Settings. (HTTP redirect to login page)")
    # yt-dlp raises ExtractionError because it has no video formats
    ytdlp_err = ExtractionError("ERROR: [Instagram] DfsTjjrR9Z2: No video formats found!")

    with patch("app.services.gallerydl_service.inspect_url", new_callable=AsyncMock, side_effect=gdl_err), \
         patch("app.services.ytdlp_service.inspect_url", new_callable=AsyncMock, side_effect=ytdlp_err):
        with pytest.raises(AuthRequiredError) as exc_info:
            await router.inspect(target_url)
        assert "Authentication required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_router_inspect_instagram_photo_carousel_generic_error_converted_to_auth():
    """Verify that when gallery-dl returns 'no media items' and yt-dlp fails with 'no video formats',
    router detects that Instagram photo post requires cookies and raises AuthRequiredError."""
    target_url = "https://www.instagram.com/p/DfsTsqUEYfw/"

    gdl_err = ExtractionError("gallery-dl found no media items for this URL")
    ytdlp_err = ExtractionError("ERROR: [Instagram] DfsTjjrR9Z2: No video formats found!")

    with patch("app.services.gallerydl_service.inspect_url", new_callable=AsyncMock, side_effect=gdl_err), \
         patch("app.services.ytdlp_service.inspect_url", new_callable=AsyncMock, side_effect=ytdlp_err):
        with pytest.raises(AuthRequiredError) as exc_info:
            await router.inspect(target_url)
        assert "Authentication required" in str(exc_info.value)
        assert "Instagram requires session cookies" in str(exc_info.value)


@pytest.mark.asyncio
async def test_router_inspect_twitter_photo_post_auth_preserved():
    """Verify router.inspect raises AuthRequiredError on Twitter photo post."""
    target_url = "https://x.com/NASA/status/1856747043004874987"

    gdl_err = AuthRequiredError("Authentication required: Twitter/X requires authentication ('Unavailable')")
    ytdlp_err = ExtractionError("ERROR: [twitter] 1856747043004874987: No video could be found in this tweet")

    with patch("app.services.gallerydl_service.inspect_url", new_callable=AsyncMock, side_effect=gdl_err), \
         patch("app.services.ytdlp_service.inspect_url", new_callable=AsyncMock, side_effect=ytdlp_err):
        with pytest.raises(AuthRequiredError) as exc_info:
            await router.inspect(target_url)
        assert "Authentication required" in str(exc_info.value)
