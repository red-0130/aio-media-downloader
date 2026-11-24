"""Unit tests for extraction router, platform classification, and fallback mechanisms."""

import asyncio
from pathlib import Path
from urllib.parse import quote
from unittest.mock import AsyncMock, patch
import zipfile
import pytest

from app.models.download import DownloadRequest
from app.models.inspect import InspectResponse
from app.services import cookie_manager, router
from app.services.router import classify_url
from app.services.ytdlp_service import ExtractionError, AuthRequiredError
from tests.conftest import load_fixture_json


def test_classify_url_matrix():
    # YouTube
    assert classify_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == ("youtube", "ytdlp", None)
    assert classify_url("https://youtu.be/dQw4w9WgXcQ") == ("youtube", "ytdlp", None)

    # Instagram Reels vs Carousels / Stories
    assert classify_url("https://www.instagram.com/reel/C7XYZ89_abc/") == ("instagram", "ytdlp", "gallerydl")
    assert classify_url("https://www.instagram.com/p/C7XYZ89_abc/") == ("instagram", "gallerydl", "ytdlp")
    assert classify_url("https://www.instagram.com/stories/username/123456/") == ("instagram", "gallerydl", "ytdlp")

    # Twitter / X
    assert classify_url("https://twitter.com/user/status/123456/photo/1") == ("twitter", "gallerydl", "ytdlp")
    assert classify_url("https://twitter.com/user/status/123456/video/1") == ("twitter", "ytdlp", "gallerydl")
    assert classify_url("https://x.com/user/status/123456") == ("twitter", "gallerydl", "ytdlp")

    # TikTok
    assert classify_url("https://www.tiktok.com/@user/video/123456") == ("tiktok", "ytdlp", "gallerydl")
    assert classify_url("https://www.tiktok.com/@user/photo/123456") == ("tiktok", "gallerydl", "ytdlp")

    # Generic
    assert classify_url("https://vimeo.com/123456") == ("generic", "ytdlp", "gallerydl")


@pytest.mark.asyncio
async def test_inspect_youtube_via_ytdlp():
    canned = load_fixture_json("ytdlp_youtube_video.json")

    with patch("app.services.ytdlp_service.inspect_url", new_callable=AsyncMock) as mock_ytdlp:
        mock_ytdlp.return_value = canned

        res = await router.inspect("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert res.id == "dQw4w9WgXcQ"
        assert res.platform == "youtube"
        assert res.title == "Rick Astley - Never Gonna Give You Up (Official Music Video)"
        assert res.uploader == "Rick Astley"
        assert res.media_type == "video"
        assert len(res.formats) >= 3
        format_ids = [f.format_id for f in res.formats]
        assert "best" in format_ids
        assert "audio-mp3" in format_ids


@pytest.mark.asyncio
async def test_inspect_instagram_carousel_via_gallerydl():
    canned = load_fixture_json("gallerydl_instagram_carousel.json")

    with patch("app.services.gallerydl_service.inspect_url", new_callable=AsyncMock) as mock_gdl:
        mock_gdl.return_value = canned

        res = await router.inspect("https://www.instagram.com/p/334819201948/")

        assert res.platform == "instagram"
        assert res.media_type == "carousel"
        assert len(res.items) == 3
        assert res.items[0].type == "image"
        assert res.items[2].type == "video"


@pytest.mark.asyncio
async def test_inspect_instagram_story_via_gallerydl():
    canned = load_fixture_json("gallerydl_instagram_story.json")

    with patch("app.services.gallerydl_service.inspect_url", new_callable=AsyncMock) as mock_gdl:
        mock_gdl.return_value = canned

        res = await router.inspect("https://www.instagram.com/stories/influencer_daily/94821038/")

        assert res.platform == "instagram"
        assert res.media_type == "story"
        assert len(res.items) == 2


@pytest.mark.asyncio
async def test_fallback_routing_when_primary_fails():
    # Simulate Instagram reel where primary is yt-dlp, but yt-dlp fails and gallery-dl succeeds
    canned_gdl = load_fixture_json("gallerydl_instagram_carousel.json")

    with patch(
        "app.services.ytdlp_service.inspect_url",
        new_callable=AsyncMock,
        side_effect=ExtractionError("yt-dlp rate limit or schema failure"),
    ), patch("app.services.gallerydl_service.inspect_url", new_callable=AsyncMock) as mock_gdl:
        mock_gdl.return_value = canned_gdl

        # Reels URL -> primary is yt-dlp
        res = await router.inspect("https://www.instagram.com/reel/C7XYZ89_abc/")

        # Verify fallback to gallery-dl happened and succeeded
        assert res.platform == "instagram"
        assert len(res.items) == 3


@pytest.mark.asyncio
async def test_both_engines_fail_raises_error():
    with patch(
        "app.services.ytdlp_service.inspect_url",
        new_callable=AsyncMock,
        side_effect=AuthRequiredError("Sign in required"),
    ), patch(
        "app.services.gallerydl_service.inspect_url",
        new_callable=AsyncMock,
        side_effect=ExtractionError("gallery-dl also failed"),
    ):
        with pytest.raises(AuthRequiredError):
            await router.inspect("https://www.instagram.com/reel/C7XYZ89_abc/")


@pytest.mark.asyncio
async def test_download_single_file_named_properly(temp_environment):
    task_id = "test-task-123"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    fake_file = task_dir / "Cool_Video.mp4"
    fake_file.write_bytes(b"sample video bytes")

    with patch("app.services.ytdlp_service.download_media", new_callable=AsyncMock) as mock_down:
        mock_down.return_value = [fake_file]

        req = DownloadRequest(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            format_id="best",
            package_as_zip=False,
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is False
        assert result.filename == "Cool_Video.mp4"
        assert Path(result.file_path).exists()


@pytest.mark.asyncio
async def test_download_multiple_files_bundled_as_zip(temp_environment):
    task_id = "test-task-bundle"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    img1 = task_dir / "img1.jpg"
    img2 = task_dir / "img2.jpg"
    img1.write_bytes(b"data1")
    img2.write_bytes(b"data2")

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down:
        mock_down.return_value = [img1, img2]

        req = DownloadRequest(
            url="https://www.instagram.com/p/334819201948/",
            package_as_zip=True,
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is True
        assert result.filename.endswith(".zip")
        assert Path(result.file_path).exists()
        assert result.download_url == f"/api/files/{task_id}/{result.filename}"


@pytest.mark.asyncio
async def test_download_instagram_single_file_metadata_flow(temp_environment):
    task_id = "insta-task-456"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    fake_file = task_dir / "raw_download.mp4"
    fake_file.write_bytes(b"sample instagram video")

    with patch("app.services.ytdlp_service.download_media", new_callable=AsyncMock) as mock_down:
        mock_down.return_value = [fake_file]

        req = DownloadRequest(
            url="https://www.instagram.com/reel/C7XYZ89_abc/",
            package_as_zip=False,
            metadata={
                "uploader": "travel_blogger",
                "upload_date": "20240510",
                "original_name_first": "reel_video",
            },
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is False
        assert result.filename == "travel_blogger_20240510_reel_video.mp4"
        assert Path(result.file_path).exists()


def test_format_option_filesize_flexibility():
    from app.models.inspect import FormatOption

    # int filesize
    opt_int = FormatOption(format_id="1", label="1080p", ext="mp4", filesize=1048576)
    assert opt_int.filesize == 1048576

    # float filesize (common in some extractors/probes)
    opt_float = FormatOption(format_id="2", label="720p", ext="mp4", filesize=524288.5)
    assert opt_float.filesize == 524288.5

    # None filesize
    opt_none = FormatOption(format_id="3", label="Audio", ext="mp3", filesize=None)
    assert opt_none.filesize is None


@pytest.mark.asyncio
async def test_router_inspect_with_client_cookies_and_proxy(temp_environment):
    """Verify router.inspect passes client session cookies and proxy to engine."""
    canned = load_fixture_json("ytdlp_youtube_video.json")
    client_netscape = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tclient_session_sid\n"
    )

    with patch("app.services.ytdlp_service.inspect_url", new_callable=AsyncMock) as mock_ytdlp:
        mock_ytdlp.return_value = canned

        res = await router.inspect(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            proxy="socks5://127.0.0.1:9050",
            cookies={"youtube": client_netscape},
        )

        assert res.id == "dQw4w9WgXcQ"
        assert mock_ytdlp.await_count == 1
        _, kwargs = mock_ytdlp.await_args
        assert kwargs["proxy"] == "socks5://127.0.0.1:9050"
        cookie_path = kwargs["cookies_path"]
        assert cookie_path is not None
        assert "client_cookies_youtube_" in str(cookie_path)


@pytest.mark.asyncio
async def test_router_download_with_client_cookies_and_proxy(temp_environment):
    """Verify router.download passes client session cookies and proxy to engine."""
    task_id = "test-task-client-dl"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    fake_file = task_dir / "Video.mp4"
    fake_file.write_bytes(b"sample video bytes")

    client_netscape = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tclient_sid_123\n"
    )

    with patch("app.services.ytdlp_service.download_media", new_callable=AsyncMock) as mock_down:
        mock_down.return_value = [fake_file]

        req = DownloadRequest(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            format_id="best",
            package_as_zip=False,
            cookies={"youtube": client_netscape},
            proxy="socks5://127.0.0.1:9050",
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is False
        assert not result.filename.endswith(".zip")
        assert mock_down.await_count == 1
        _, kwargs = mock_down.await_args
        assert kwargs["proxy"] == "socks5://127.0.0.1:9050"
        cookie_path = kwargs["cookies_path"]
        assert cookie_path is not None
        assert "client_cookies_youtube_" in str(cookie_path)
        # Verify cookie file was NOT created in task_dir
        assert not cookie_path.is_relative_to(task_dir)


@pytest.mark.asyncio
async def test_router_download_instagram_fallback_probe_passes_client_cookies(temp_environment):
    """Verify fallback Instagram metadata probe passes client cookies to router.inspect."""
    task_id = "test-task-ig-meta-probe"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    fake_file = task_dir / "sample_post.jpg"
    fake_file.write_bytes(b"sample image bytes")

    client_cookies = {
        "instagram": (
            "# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\tclient_ig_session_999\n"
        )
    }

    mock_inspected = InspectResponse(
        id="sample_media_id",
        url="https://www.instagram.com/p/sample123/",
        platform="instagram",
        title="Custom Instagram Post",
        uploader="ig_creator",
        thumbnail="https://example.com/thumb.jpg",
        media_type="image",
        items=[],
        formats=[],
    )

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_g_down, \
         patch("app.services.router.inspect", new_callable=AsyncMock) as mock_inspect:
        mock_g_down.return_value = [fake_file]
        mock_inspect.return_value = mock_inspected

        req = DownloadRequest(
            url="https://www.instagram.com/p/sample123/",
            cookies=client_cookies,
            proxy="socks5://127.0.0.1:9050",
            metadata=None,  # Trigger probe
        )

        res = await router.download(task_id, req)
        assert res.task_id == task_id
        assert "ig_creator" in res.filename

        mock_inspect.assert_awaited_once_with(
            "https://www.instagram.com/p/sample123/",
            proxy="socks5://127.0.0.1:9050",
            cookies=client_cookies,
        )


@pytest.mark.asyncio
async def test_router_whitespace_proxy_falls_back_to_server_proxy(temp_environment, monkeypatch):
    """Verify router inspect and download treat whitespace proxy as omitted and fall back to server proxy."""
    from app.services import proxy_manager
    from app.config import settings

    monkeypatch.setattr(settings, "SOCKS5_PROXY", "socks5://server-proxy.corp:1080")
    proxy_manager.reset_runtime_proxy()

    canned = load_fixture_json("ytdlp_youtube_video.json")
    with patch("app.services.ytdlp_service.inspect_url", new_callable=AsyncMock) as mock_ytdlp:
        mock_ytdlp.return_value = canned

        # Pass whitespace proxy
        await router.inspect("https://www.youtube.com/watch?v=dQw4w9WgXcQ", proxy="   ")
        _, kwargs = mock_ytdlp.await_args
        # Should fall back to server proxy without whitespace
        assert kwargs["proxy"] == "socks5://server-proxy.corp:1080"


def test_normalize_ytdlp_metadata_formats_sorted_descending():
    """Verify _normalize_ytdlp_metadata sorts video formats descending by resolution height."""
    raw_data = {
        "id": "sample_video_123",
        "title": "High-Res Test Video",
        "uploader": "Test Channel",
        "formats": [
            {"format_id": "18", "height": 360, "vcodec": "avc1", "protocol": "https"},
            {"format_id": "95", "height": 720, "vcodec": "avc1", "protocol": "m3u8"},
            {"format_id": "22", "height": 720, "vcodec": "avc1", "protocol": "https"},
            {"format_id": "137", "height": 1080, "vcodec": "avc1", "protocol": "https"},
            {"format_id": "313", "height": 2160, "vcodec": "vp9", "protocol": "https"},
        ],
    }
    normalized = router._normalize_ytdlp_metadata(
        "https://www.youtube.com/watch?v=sample_video_123",
        "youtube",
        raw_data,
    )
    video_formats = [f for f in normalized.formats if f.format_id not in ("best", "audio-mp3")]
    heights = [int(f.resolution.rstrip("p")) for f in video_formats if f.resolution]
    assert heights == [2160, 1080, 720, 360]
    # Check that 720p preferred https (format 22) over m3u8 (format 95)
    fmt_720 = next(f for f in video_formats if f.resolution == "720p")
    assert fmt_720.format_id == "22"


def test_normalize_metadata_preserves_date_and_original_name():
    """Verify _normalize_ytdlp_metadata and _normalize_gallerydl_metadata extract date and original_name."""
    # yt-dlp metadata
    ytdlp_data = {
        "id": "reel_123",
        "title": "Reel Title",
        "channel": "instagram_artist",
        "upload_date": "20240510",
        "original_name_first": "clip_original",
        "formats": [{"format_id": "best", "ext": "mp4", "height": 1080, "vcodec": "avc1"}],
    }
    res_ytdlp = router._normalize_ytdlp_metadata(
        "https://www.instagram.com/reel/reel_123/", "instagram", ytdlp_data
    )
    assert res_ytdlp.date == "20240510"
    assert res_ytdlp.original_name_first == "clip_original"
    assert res_ytdlp.uploader == "instagram_artist"

    # gallery-dl metadata
    gdl_data = [
        {
            "post_id": "post_789",
            "user": "photo_master",
            "date": "2024-05-12 18:30:00",
            "original_name_first": "golden_hour",
            "extension": "jpg",
            "url": "https://instagram.com/p/post_789/1.jpg",
        },
        {
            "post_id": "post_789",
            "user": "photo_master",
            "date": "2024-05-12 18:30:00",
            "original_name_first": "blue_hour",
            "extension": "jpg",
            "url": "https://instagram.com/p/post_789/2.jpg",
        },
    ]
    res_gdl = router._normalize_gallerydl_metadata(
        "https://www.instagram.com/p/post_789/", "instagram", gdl_data
    )
    assert res_gdl.date == "2024-05-12 18:30:00"
    assert res_gdl.original_name_first == "golden_hour"
    assert len(res_gdl.items) == 2
    assert res_gdl.items[0].original_name_first == "golden_hour"
    assert res_gdl.items[1].original_name_first == "blue_hour"


@pytest.mark.asyncio
async def test_download_multiple_files_unbundled_when_package_as_zip_false(temp_environment):
    """Verify downloading multiple files delivers separate files when package_as_zip=False."""
    task_id = "test-task-unbundled"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    img1 = task_dir / "img1.jpg"
    img2 = task_dir / "img2.jpg"
    img3 = task_dir / "img3.jpg"
    img1.write_bytes(b"data1")
    img2.write_bytes(b"data2")
    img3.write_bytes(b"data3")

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down:
        mock_down.return_value = [img1, img2, img3]

        req = DownloadRequest(
            url="https://www.instagram.com/p/334819201948/",
            package_as_zip=False,
            metadata={
                "uploader": "nature_photographer",
                "date": "20240512",
                "items": [
                    {"index": 0, "type": "image", "original_name_first": "mountain_peak", "date": "20240512"},
                    {"index": 1, "type": "image", "original_name_first": "lake_view", "date": "20240512"},
                    {"index": 2, "type": "image", "original_name_first": "forest_trail", "date": "20240512"},
                ],
            },
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is False
        assert not result.filename.endswith(".zip")
        assert result.files is not None
        assert len(result.files) == 3

        # Verify no .zip exists in task_dir
        zip_files = list(task_dir.glob("*.zip"))
        assert len(zip_files) == 0

        # Verify all 3 files exist and follow Instagram convention
        expected_names = [
            "nature_photographer_20240512_mountain_peak.jpg",
            "nature_photographer_20240512_lake_view.jpg",
            "nature_photographer_20240512_forest_trail.jpg",
        ]
        file_names = [f.filename for f in result.files]
        for expected in expected_names:
            assert expected in file_names
            assert (task_dir / expected).exists()


@pytest.mark.asyncio
async def test_download_twitter_hashtag_title_retains_hash_and_encodes_url(temp_environment):
    """Regression Test (R1 & R2):

    Verify router.download retains leading '#' in filename and percent-encodes '%23'
    in download_url for Twitter posts with text starting with '#'.
    """
    task_id = "twitter-hashtag-test-123"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    fake_file = task_dir / "raw_twitter_video.mp4"
    fake_file.write_bytes(b"twitter test stream")

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down:
        mock_down.return_value = [fake_file]

        hashtag_title = "#Umingle #Ometv #Monkeyapp #Omegle #CSL"
        req = DownloadRequest(
            url="https://x.com/CSLfrreac/status/2121343870013222933?a=UXOELjiUHqCARzEpBGU&s=20",
            package_as_zip=False,
            metadata={
                "id": "2121343870013222933",
                "title": hashtag_title,
                "platform": "twitter",
            },
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is False
        # Filename retains leading '#'
        assert result.filename.startswith("#")
        assert result.filename == f"{hashtag_title}.mp4"
        assert Path(result.file_path).exists()
        assert Path(result.file_path).name == f"{hashtag_title}.mp4"

        # Download URL is properly URL-encoded (%23 instead of raw #)
        assert "#" not in result.download_url
        assert "%23" in result.download_url
        assert result.download_url == f"/api/files/{task_id}/{quote(result.filename)}"


def test_normalize_gallerydl_metadata_extracts_content_hashtag():
    """Verify _normalize_gallerydl_metadata extracts tweet content starting with '#' as post title."""
    items_data = [
        {
            "category": "twitter",
            "subcategory": "tweet",
            "tweet_id": "2121343870013222933",
            "author": {"name": "CSL", "nick": "CSLfrreac"},
            "content": "#Umingle #Ometv #Monkeyapp #Omegle #CSL",
            "description": None,
            "title": None,
            "extension": "mp4",
            "url": "https://video.twimg.com/ext_tw_video/2121343870013222933/pu/vid/avc1/720x1280/test.mp4",
        }
    ]

    res = router._normalize_gallerydl_metadata(
        url="https://x.com/CSLfrreac/status/2121343870013222933",
        platform="twitter",
        items_data=items_data,
    )

    assert res.title.startswith("#")
    assert res.title == "#Umingle #Ometv #Monkeyapp #Omegle #CSL"
    assert res.id == "2121343870013222933"


@pytest.mark.asyncio
@pytest.mark.parametrize("url,platform", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
    ("https://www.instagram.com/reel/C12345/", "instagram"),
    ("https://twitter.com/user/status/123456/video/1", "twitter"),
    ("https://www.tiktok.com/@user/video/1234567890", "tiktok"),
])
async def test_router_inspect_cookie_precedence_all_platforms(temp_environment, url, platform):
    """Verify router.inspect follows 3-tier cookie precedence across all 4 platforms:
    Tier 1: Client session cookie overrides default.
    Tier 2: Default cookie used when client cookie omitted.
    Tier 3: Neither exists -> cookies_path is None.
    """
    canned = {"id": "media123", "title": "Precedence Title", "uploader": "precedence_user"}
    future_ts = 2000000000
    default_netscape = f"# Netscape HTTP Cookie File\n.{platform}.com\tTRUE\t/\tTRUE\t{future_ts}\tsessionid\tdefault_{platform}\n"
    client_netscape = f"# Netscape HTTP Cookie File\n.{platform}.com\tTRUE\t/\tTRUE\t{future_ts}\tsessionid\tclient_{platform}\n"

    with patch("app.services.ytdlp_service.inspect_url", new_callable=AsyncMock) as mock_ytdlp:
        mock_ytdlp.return_value = canned

        # Tier 3: No default cookie on disk, no client cookie -> cookies_path is None
        await router.inspect(url, cookies=None)
        assert mock_ytdlp.await_count == 1
        _, kwargs = mock_ytdlp.await_args
        assert kwargs["cookies_path"] is None

        # Set up default cookie on disk
        cookie_manager.save_cookies(platform, default_netscape)
        default_path = cookie_manager.get_default_cookie_path(platform)
        assert default_path is not None

        # Tier 2: Default cookie on disk, no client cookie -> default cookie path passed
        mock_ytdlp.reset_mock()
        await router.inspect(url, cookies=None)
        assert mock_ytdlp.await_count == 1
        _, kwargs = mock_ytdlp.await_args
        assert kwargs["cookies_path"] == default_path

        # Tier 1: Default cookie on disk, client cookie provided -> temporary client cookie path passed
        mock_ytdlp.reset_mock()
        await router.inspect(url, cookies={platform: client_netscape})
        assert mock_ytdlp.await_count == 1
        _, kwargs = mock_ytdlp.await_args
        resolved_cookie_path = kwargs["cookies_path"]
        assert resolved_cookie_path is not None
        assert resolved_cookie_path != default_path
        assert f"client_cookies_{platform}_" in str(resolved_cookie_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("url,platform", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
    ("https://www.instagram.com/reel/C12345/", "instagram"),
    ("https://twitter.com/user/status/123456/video/1", "twitter"),
    ("https://www.tiktok.com/@user/video/1234567890", "tiktok"),
])
async def test_router_download_cookie_precedence_all_platforms(temp_environment, url, platform):
    """Verify router.download follows 3-tier cookie precedence across all 4 platforms."""
    task_id = f"test-prec-dl-{platform}"
    task_dir = temp_environment["downloads_dir"] / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    fake_file = task_dir / "media.mp4"
    fake_file.write_bytes(b"dummy")

    future_ts = 2000000000
    default_netscape = f"# Netscape HTTP Cookie File\n.{platform}.com\tTRUE\t/\tTRUE\t{future_ts}\tsessionid\tdefault_{platform}\n"
    client_netscape = f"# Netscape HTTP Cookie File\n.{platform}.com\tTRUE\t/\tTRUE\t{future_ts}\tsessionid\tclient_{platform}\n"

    with patch("app.services.ytdlp_service.download_media", new_callable=AsyncMock) as mock_down:
        mock_down.return_value = [fake_file]

        # Tier 3: Neither exists -> cookies_path is None
        fake_file.write_bytes(b"dummy")
        req3 = DownloadRequest(url=url, format_id="best", package_as_zip=False, cookies=None)
        await router.download(task_id, req3)
        assert mock_down.await_count == 1
        _, kwargs = mock_down.await_args
        assert kwargs["cookies_path"] is None

        # Set up default cookie
        cookie_manager.save_cookies(platform, default_netscape)
        default_path = cookie_manager.get_default_cookie_path(platform)
        assert default_path is not None

        # Tier 2: Default exists, client omitted -> default cookie passed
        fake_file.write_bytes(b"dummy")
        mock_down.reset_mock()
        req2 = DownloadRequest(url=url, format_id="best", package_as_zip=False, cookies=None)
        await router.download(task_id, req2)
        assert mock_down.await_count == 1
        _, kwargs = mock_down.await_args
        assert kwargs["cookies_path"] == default_path

        # Tier 1: Client provided -> client cookie passed, default ignored
        fake_file.write_bytes(b"dummy")
        mock_down.reset_mock()
        req1 = DownloadRequest(url=url, format_id="best", package_as_zip=False, cookies={platform: client_netscape})
        await router.download(task_id, req1)
        assert mock_down.await_count == 1
        _, kwargs = mock_down.await_args
        resolved_path = kwargs["cookies_path"]
        assert resolved_path is not None
        assert resolved_path != default_path
        assert f"client_cookies_{platform}_" in str(resolved_path)


@pytest.mark.asyncio
async def test_download_multiple_gallery_videos_audio_extraction_bundled_zip(temp_environment):
    """Verify multiple gallery videos are all converted to MP3 when extract_audio=True and bundled as ZIP."""
    task_id = "test-gallery-multi-audio-zip"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    vid1 = task_dir / "clip1.mp4"
    vid2 = task_dir / "clip2.mp4"
    vid1.write_bytes(b"dummy video 1")
    vid2.write_bytes(b"dummy video 2")

    async def fake_extract(input_file, output_file, audio_format="mp3", bitrate="320k"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(b"dummy extracted mp3 audio")
        return output_file

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down, \
         patch("app.services.ffmpeg_service.extract_audio", side_effect=fake_extract) as mock_extract:
        mock_down.return_value = [vid1, vid2]

        req = DownloadRequest(
            url="https://www.instagram.com/p/C7XYZ89_abc/",
            extract_audio=True,
            audio_format="mp3",
            package_as_zip=True,
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is True
        assert result.filename.endswith(".zip")
        assert Path(result.file_path).exists()
        assert mock_extract.call_count == 2

        # Verify original video files were deleted
        assert not vid1.exists()
        assert not vid2.exists()

        # Verify ZIP contains MP3 files
        with zipfile.ZipFile(result.file_path, "r") as zf:
            zip_entries = zf.namelist()
            assert len(zip_entries) == 2
            assert all(entry.endswith(".mp3") for entry in zip_entries)


@pytest.mark.asyncio
async def test_download_multiple_gallery_videos_audio_extraction_unbundled(temp_environment):
    """Verify multiple gallery videos are converted to MP3 when package_as_zip=False."""
    task_id = "test-gallery-multi-audio-unbundled"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    vid1 = task_dir / "reel1.mp4"
    vid2 = task_dir / "reel2.mp4"
    vid1.write_bytes(b"video 1 data")
    vid2.write_bytes(b"video 2 data")

    async def fake_extract(input_file, output_file, audio_format="mp3", bitrate="320k"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(b"audio content")
        return output_file

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down, \
         patch("app.services.ffmpeg_service.extract_audio", side_effect=fake_extract) as mock_extract:
        mock_down.return_value = [vid1, vid2]

        req = DownloadRequest(
            url="https://www.instagram.com/p/C7XYZ89_abc/",
            extract_audio=True,
            audio_format="mp3",
            package_as_zip=False,
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is False
        assert result.files is not None
        assert len(result.files) == 2
        assert all(f.filename.endswith(".mp3") for f in result.files)
        assert mock_extract.call_count == 2
        assert not vid1.exists()
        assert not vid2.exists()


@pytest.mark.asyncio
async def test_download_mixed_gallery_items_audio_extraction(temp_environment):
    """Verify mixed carousel (image + video) only extracts audio for the video item."""
    task_id = "test-gallery-mixed-audio"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    img = task_dir / "photo.jpg"
    vid = task_dir / "clip.mp4"
    img.write_bytes(b"dummy image bytes")
    vid.write_bytes(b"dummy video bytes")

    async def fake_extract(input_file, output_file, audio_format="mp3", bitrate="320k"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(b"extracted mp3 bytes")
        return output_file

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down, \
         patch("app.services.ffmpeg_service.extract_audio", side_effect=fake_extract) as mock_extract:
        mock_down.return_value = [img, vid]

        req = DownloadRequest(
            url="https://www.instagram.com/p/C7XYZ89_abc/",
            extract_audio=True,
            audio_format="mp3",
            package_as_zip=True,
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is True
        assert mock_extract.call_count == 1
        # Extract audio should only have been called on the video file
        assert mock_extract.call_args[1]["input_file"] == vid
        assert not vid.exists()
        # Original image was untouched and bundled into zip
        with zipfile.ZipFile(result.file_path, "r") as zf:
            zip_entries = zf.namelist()
            assert len(zip_entries) == 2
            exts = {Path(e).suffix for e in zip_entries}
            assert exts == {".jpg", ".mp3"}


@pytest.mark.asyncio
async def test_download_single_video_audio_extraction_regression(temp_environment):
    """Verify single video gallery download still extracts audio properly."""
    task_id = "test-gallery-single-audio"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    vid = task_dir / "single_video.mp4"
    vid.write_bytes(b"single video bytes")

    async def fake_extract(input_file, output_file, audio_format="mp3", bitrate="320k"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(b"audio bytes")
        return output_file

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down, \
         patch("app.services.ffmpeg_service.extract_audio", side_effect=fake_extract) as mock_extract:
        mock_down.return_value = [vid]

        req = DownloadRequest(
            url="https://www.instagram.com/p/C7XYZ89_abc/",
            extract_audio=True,
            audio_format="mp3",
            package_as_zip=False,
        )

        result = await router.download(task_id, req)

        assert result.task_id == task_id
        assert result.is_zip is False
        assert result.filename.endswith(".mp3")
        assert mock_extract.call_count == 1
        assert not vid.exists()


@pytest.mark.asyncio
async def test_download_multiple_gallery_videos_audio_extraction_m4a_format(temp_environment):
    """Verify target format m4a is respected for multi-video extraction."""
    task_id = "test-gallery-multi-m4a"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    vid1 = task_dir / "part1.mp4"
    vid2 = task_dir / "part2.webm"
    vid1.write_bytes(b"part 1")
    vid2.write_bytes(b"part 2")

    async def fake_extract(input_file, output_file, audio_format="m4a", bitrate="320k"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(b"m4a bytes")
        return output_file

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down, \
         patch("app.services.ffmpeg_service.extract_audio", side_effect=fake_extract) as mock_extract:
        mock_down.return_value = [vid1, vid2]

        req = DownloadRequest(
            url="https://www.instagram.com/p/C7XYZ89_abc/",
            extract_audio=True,
            audio_format="m4a",
            package_as_zip=True,
        )

        result = await router.download(task_id, req)

        assert result.is_zip is True
        assert mock_extract.call_count == 2
        for call in mock_extract.call_args_list:
            assert call[1]["audio_format"] == "m4a"
        with zipfile.ZipFile(result.file_path, "r") as zf:
            zip_entries = zf.namelist()
            assert len(zip_entries) == 2
            assert all(e.endswith(".m4a") for e in zip_entries)


@pytest.mark.asyncio
async def test_download_gallery_extended_video_extensions_audio_extraction(temp_environment):
    """Verify extended video containers (avi, flv, wmv, ogv) are converted to audio."""
    task_id = "test-gallery-extended-exts"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    f_avi = task_dir / "clip1.avi"
    f_flv = task_dir / "clip2.flv"
    f_wmv = task_dir / "clip3.wmv"
    f_ogv = task_dir / "clip4.ogv"
    for f in (f_avi, f_flv, f_wmv, f_ogv):
        f.write_bytes(b"dummy video data")

    async def fake_extract(input_file, output_file, audio_format="mp3", bitrate="320k"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(b"dummy mp3 data")
        return output_file

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down, \
         patch("app.services.ffmpeg_service.extract_audio", side_effect=fake_extract) as mock_extract:
        mock_down.return_value = [f_avi, f_flv, f_wmv, f_ogv]

        req = DownloadRequest(
            url="https://www.instagram.com/p/C7XYZ89_abc/",
            extract_audio=True,
            audio_format="mp3",
            package_as_zip=True,
        )

        result = await router.download(task_id, req)

        assert result.is_zip is True
        assert mock_extract.call_count == 4
        for f in (f_avi, f_flv, f_wmv, f_ogv):
            assert not f.exists()
        with zipfile.ZipFile(result.file_path, "r") as zf:
            assert len(zf.namelist()) == 4
            assert all(name.endswith(".mp3") for name in zf.namelist())


@pytest.mark.asyncio
async def test_download_gallery_videos_audio_extraction_stem_collision(temp_environment):
    """Verify two video files with the same stem (e.g. clip.mp4 and clip.webm) do not collide when converted."""
    task_id = "test-gallery-stem-collision"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    vid_mp4 = task_dir / "sample.mp4"
    vid_webm = task_dir / "sample.webm"
    vid_mp4.write_bytes(b"mp4 content")
    vid_webm.write_bytes(b"webm content")

    async def fake_extract(input_file, output_file, audio_format="mp3", bitrate="320k"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(f"audio for {input_file.name}".encode())
        return output_file

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down, \
         patch("app.services.ffmpeg_service.extract_audio", side_effect=fake_extract) as mock_extract:
        mock_down.return_value = [vid_mp4, vid_webm]

        req = DownloadRequest(
            url="https://www.instagram.com/p/C7XYZ89_abc/",
            extract_audio=True,
            audio_format="mp3",
            package_as_zip=True,
        )

        result = await router.download(task_id, req)

        assert result.is_zip is True
        assert mock_extract.call_count == 2
        with zipfile.ZipFile(result.file_path, "r") as zf:
            names = zf.namelist()
            assert len(names) == 2
            assert len(set(names)) == 2  # Disambiguated and distinct
            assert all(n.endswith(".mp3") for n in names)


@pytest.mark.asyncio
async def test_download_gallery_videos_audio_extraction_progress_callback(temp_environment):
    """Verify progress_callback receives extraction progress and message during multi-video audio extraction."""
    task_id = "test-gallery-progress-cb"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    vid1 = task_dir / "clip1.mp4"
    vid2 = task_dir / "clip2.mp4"
    vid1.write_bytes(b"vid1")
    vid2.write_bytes(b"vid2")

    progress_events = []

    async def on_progress(progress, message=None, **kwargs):
        progress_events.append((progress, message))

    async def fake_extract(input_file, output_file, audio_format="mp3", bitrate="320k"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(b"audio")
        return output_file

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down, \
         patch("app.services.ffmpeg_service.extract_audio", side_effect=fake_extract):
        mock_down.return_value = [vid1, vid2]

        req = DownloadRequest(
            url="https://www.instagram.com/p/C7XYZ89_abc/",
            extract_audio=True,
            audio_format="mp3",
            package_as_zip=True,
        )

        await router.download(task_id, req, progress_callback=on_progress)

        messages = [msg for _, msg in progress_events if msg and "Extracting audio" in msg]
        assert len(messages) == 2
        assert "Extracting audio (1/2)..." in messages[0]
        assert "Extracting audio (2/2)..." in messages[1]


@pytest.mark.asyncio
async def test_download_gallery_videos_real_ffmpeg_end_to_end(temp_environment):
    """Deep verification: Transcode multiple real videos to MP3 using pyffmpeg without mocking extract_audio."""
    from app.services import ffmpeg_service

    ffmpeg_bin = ffmpeg_service.get_ffmpeg_bin()
    if not Path(ffmpeg_bin).exists():
        pytest.skip("FFmpeg binary not available in this environment")

    task_id = "test-gallery-real-ffmpeg"
    downloads_dir = temp_environment["downloads_dir"]
    task_dir = downloads_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    vid1 = task_dir / "segment1.mp4"
    vid2 = task_dir / "segment2.mp4"

    # Generate 2 valid MP4 files with video and synthetic sine wave audio
    for v in (vid1, vid2):
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
            "-c:v", "libx264", "-c:a", "aac", str(v),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        assert proc.returncode == 0

    with patch("app.services.gallerydl_service.download_items", new_callable=AsyncMock) as mock_down:
        mock_down.return_value = [vid1, vid2]

        req = DownloadRequest(
            url="https://www.instagram.com/p/C7XYZ89_abc/",
            extract_audio=True,
            audio_format="mp3",
            package_as_zip=True,
        )

        result = await router.download(task_id, req)

        assert result.is_zip is True
        assert Path(result.file_path).exists()
        assert not vid1.exists()
        assert not vid2.exists()

        with zipfile.ZipFile(result.file_path, "r") as zf:
            names = zf.namelist()
            assert len(names) == 2
            assert all(n.endswith(".mp3") for n in names)
            # Verify extracted MP3 file headers (ID3 or MPEG frame sync)
            for name in names:
                extracted_data = zf.read(name)
                assert len(extracted_data) > 0
                assert extracted_data[:3] == b"ID3" or extracted_data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")






