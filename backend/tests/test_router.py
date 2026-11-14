"""Unit tests for extraction router, platform classification, and fallback mechanisms."""

import asyncio
from pathlib import Path
from urllib.parse import quote
from unittest.mock import AsyncMock, patch
import pytest

from app.models.download import DownloadRequest
from app.models.inspect import InspectResponse
from app.services import router
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




