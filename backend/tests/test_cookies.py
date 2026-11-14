"""Unit tests for Netscape cookie parsing, validation, and storage."""

import concurrent.futures
import os
import stat
import time
import pytest
from app.services import cookie_manager

VALID_NETSCAPE_INSTAGRAM = """# Netscape HTTP Cookie File
.instagram.com\tTRUE\t/\tTRUE\t{expiry}\tsessionid\t123456%3Aabcd%3A23
.instagram.com\tTRUE\t/\tTRUE\t{expiry}\tds_user_id\t123456
"""

EXPIRED_NETSCAPE_TWITTER = """# Netscape HTTP Cookie File
.twitter.com\tTRUE\t/\tTRUE\t{expiry}\tauth_token\tabcdef1234567890
"""


def test_verify_netscape_content():
    future_ts = int(time.time()) + 86400
    content = VALID_NETSCAPE_INSTAGRAM.format(expiry=future_ts)

    is_valid, count, err = cookie_manager.verify_netscape_content(content)
    assert is_valid is True
    assert count == 2
    assert err is None


def test_verify_netscape_content_invalid():
    is_valid, count, err = cookie_manager.verify_netscape_content("not a cookie file at all")
    assert is_valid is False
    assert count == 0
    assert err is not None


def test_save_and_check_cookie_status(temp_environment):
    future_ts = int(time.time()) + 86400 * 30  # 30 days in future
    content = VALID_NETSCAPE_INSTAGRAM.format(expiry=future_ts)

    status = cookie_manager.save_cookies("instagram", content)
    assert status.platform == "instagram"
    assert status.exists is True
    assert status.valid is True
    assert status.cookie_count == 2
    assert status.expires_at is not None

    # Verify status from check_cookie_status
    refreshed = cookie_manager.check_cookie_status("instagram")
    assert refreshed.exists is True
    assert refreshed.valid is True
    assert refreshed.cookie_count == 2

    # Path helper returns valid path
    path = cookie_manager.get_cookie_path_for_platform("instagram")
    assert path is not None
    assert path.exists()


def test_expired_cookie_detected(temp_environment):
    past_ts = int(time.time()) - 3600  # 1 hour ago
    content = EXPIRED_NETSCAPE_TWITTER.format(expiry=past_ts)

    cookie_manager.save_cookies("twitter", content)
    status = cookie_manager.check_cookie_status("twitter")

    assert status.platform == "twitter"
    assert status.exists is True
    assert status.valid is False  # Expired!
    assert "expired" in (status.details or "").lower()

    # Path helper should return None for expired cookies
    assert cookie_manager.get_cookie_path_for_platform("twitter") is None


def test_missing_cookie_status(temp_environment):
    status = cookie_manager.check_cookie_status("youtube")
    assert status.exists is False
    assert status.valid is False
    assert status.cookie_count == 0
    assert cookie_manager.get_cookie_path_for_platform("youtube") is None


def test_delete_cookies(temp_environment):
    future_ts = int(time.time()) + 86400
    content = VALID_NETSCAPE_INSTAGRAM.format(expiry=future_ts)
    cookie_manager.save_cookies("instagram", content)

    assert cookie_manager.get_cookie_file_path("instagram").exists()
    deleted = cookie_manager.delete_cookies("instagram")
    assert deleted is True
    assert not cookie_manager.get_cookie_file_path("instagram").exists()

    status = cookie_manager.check_cookie_status("instagram")
    assert status.exists is False


def test_get_all_cookie_statuses(temp_environment):
    statuses = cookie_manager.get_all_cookie_statuses()
    assert "instagram" in statuses
    assert "twitter" in statuses
    assert "youtube" in statuses


def test_cookie_millisecond_timestamp_handling(temp_environment):
    # Millisecond timestamp (> 100_000_000_000)
    future_ms = (int(time.time()) + 86400 * 10) * 1000
    content = VALID_NETSCAPE_INSTAGRAM.format(expiry=future_ms)

    status = cookie_manager.save_cookies("instagram", content)
    assert status.valid is True
    assert status.expires_at is not None
    # Ensure parsed year is reasonable (e.g. within current or next year)
    assert status.expires_at.startswith("20")


def test_cookie_overflow_timestamp_handling(temp_environment):
    # Absurd timestamp exceeding year 9999 (e.g. 999999999999999)
    overflow_ts = 999999999999999
    content = VALID_NETSCAPE_INSTAGRAM.format(expiry=overflow_ts)

    # Should not raise OverflowError or ValueError
    status = cookie_manager.save_cookies("instagram", content)
    assert status.exists is True
    assert status.valid is True


def test_cookie_spaces_in_values_space_separated():
    # Space-separated Netscape line where cookie value contains spaces
    line = ".instagram.com TRUE / FALSE 1893456000 sessionid token with internal spaces\n"
    cookies = cookie_manager.parse_netscape_cookies(line)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "sessionid"
    assert cookies[0]["value"] == "token with internal spaces"


def test_cookie_platform_sanitization(temp_environment):
    # Platform name with path traversal
    with pytest.raises(ValueError):
        cookie_manager.save_cookies("../../../etc/passwd", "dummy content")

    # Status check with invalid characters should safely return invalid status, not crash
    status = cookie_manager.check_cookie_status("../../etc/shadow")
    assert status.valid is False
    assert status.exists is False


def test_concurrent_cookie_writes_and_reads_atomic_integrity(temp_environment):
    """Verify that concurrent writes and reads never observe truncated or corrupted files."""
    future_ts = int(time.time()) + 86400
    lines = ["# Netscape HTTP Cookie File"]
    for i in range(2000):
        lines.append(f".instagram.com\tTRUE\t/\tTRUE\t{future_ts}\tsessionid\tvalid_sess_{i}")
    cookie_payload = "\n".join(lines) + "\n"

    # Seed the file
    status = cookie_manager.save_cookies("instagram", cookie_payload)
    assert status.valid is True

    corruptions = []
    stop = False

    def writer_worker():
        while not stop:
            try:
                cookie_manager.save_cookies("instagram", cookie_payload)
            except Exception as e:
                corruptions.append(f"Write error: {e}")

    def reader_worker():
        for _ in range(40):
            st = cookie_manager.check_cookie_status("instagram")
            if not st.valid or st.cookie_count == 0 or "corrupted" in st.details:
                corruptions.append(f"Read error: count={st.cookie_count}, details={st.details}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        writer_futs = [executor.submit(writer_worker) for _ in range(3)]
        reader_futs = [executor.submit(reader_worker) for _ in range(4)]
        concurrent.futures.wait(reader_futs)
        stop = True
        concurrent.futures.wait(writer_futs)

    assert len(corruptions) == 0, f"Observed {len(corruptions)} corruptions: {corruptions[:5]}"


def test_save_cookies_preserves_file_permissions(temp_environment):
    """Verify that save_cookies preserves existing file permissions (e.g. 0o644, 0o660)."""
    future_ts = int(time.time()) + 86400 * 30
    content1 = VALID_NETSCAPE_INSTAGRAM.format(expiry=future_ts)
    content2 = VALID_NETSCAPE_INSTAGRAM.format(expiry=future_ts + 7200)

    # Initial save creates cookie file
    status = cookie_manager.save_cookies("instagram", content1)
    assert status.valid is True
    path = cookie_manager.get_cookie_file_path("instagram")
    assert path.exists()

    # Set explicit permission mode (0o644)
    os.chmod(path, 0o644)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644

    # Save updated cookies
    status2 = cookie_manager.save_cookies("instagram", content2)
    assert status2.valid is True

    # Assert permissions were preserved across atomic replacement
    assert stat.S_IMODE(path.stat().st_mode) == 0o644

    # Also test another mode (0o660)
    os.chmod(path, 0o660)
    assert stat.S_IMODE(path.stat().st_mode) == 0o660
    cookie_manager.save_cookies("instagram", content1)
    assert stat.S_IMODE(path.stat().st_mode) == 0o660


@pytest.mark.asyncio
async def test_resolve_cookies_context_with_client_cookies(temp_environment):
    """Verify resolve_cookies_context creates temporary cookie file and does not modify server file."""
    server_content = VALID_NETSCAPE_INSTAGRAM.format(expiry=int(time.time()) + 99999)
    cookie_manager.save_cookies("instagram", server_content)
    server_path = cookie_manager.get_cookie_file_path("instagram")
    server_mtime_before = server_path.stat().st_mtime

    client_content = (
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\tclient_session_xyz\n"
    )
    client_cookies = {"instagram": client_content}

    created_path = None
    task_dir = temp_environment["downloads_dir"] / "dummy_task"
    task_dir.mkdir(parents=True, exist_ok=True)

    async with cookie_manager.resolve_cookies_context("instagram", client_cookies, task_dir=task_dir) as cookie_path:
        assert cookie_path is not None
        assert cookie_path.exists()
        assert cookie_path != server_path
        # Must not be placed inside task_dir or downloads_dir
        assert not cookie_path.is_relative_to(task_dir)
        assert not cookie_path.is_relative_to(temp_environment["downloads_dir"])
        # Mode must be 0o600 (user read/write only)
        assert stat.S_IMODE(cookie_path.stat().st_mode) == 0o600

        created_path = cookie_path
        file_text = cookie_path.read_text(encoding="utf-8")
        assert "client_session_xyz" in file_text
        # Server file is untouched
        assert server_path.read_text(encoding="utf-8") == server_content
        assert server_path.stat().st_mtime == server_mtime_before

    # Verify temporary file cleaned up after context exit
    assert not created_path.exists()
    assert server_path.exists()


@pytest.mark.asyncio
async def test_resolve_cookies_context_fallback_to_server_when_omitted(temp_environment):
    """Verify resolve_cookies_context falls back to server cookies when client cookies omitted."""
    server_content = VALID_NETSCAPE_INSTAGRAM.format(expiry=int(time.time()) + 99999)
    cookie_manager.save_cookies("instagram", server_content)
    server_path = cookie_manager.get_cookie_file_path("instagram")

    async with cookie_manager.resolve_cookies_context("instagram", None) as cookie_path:
        assert cookie_path == server_path
        assert cookie_path.exists()

    # Still exists after context exit because it is server file
    assert server_path.exists()


@pytest.mark.asyncio
async def test_resolve_cookies_context_invalid_client_cookies_raises():
    """Verify invalid client cookies format raises ValueError without writing file."""
    with pytest.raises(ValueError, match="Invalid client cookie format"):
        async with cookie_manager.resolve_cookies_context("instagram", "invalid cookie content"):
            pass


def test_cookie_empty_value_parsing():
    """Verify parse_netscape_cookies handles empty cookie values (trailing tabs or 6 columns)."""
    # 7 columns with trailing tab and empty value
    c1 = ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tLOGIN_INFO\t"
    parsed1 = cookie_manager.parse_netscape_cookies(c1)
    assert len(parsed1) == 1
    assert parsed1[0]["name"] == "LOGIN_INFO"
    assert parsed1[0]["value"] == ""

    # 6 columns without trailing tab
    c2 = ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tLOGIN_INFO"
    parsed2 = cookie_manager.parse_netscape_cookies(c2)
    assert len(parsed2) == 1
    assert parsed2[0]["name"] == "LOGIN_INFO"
    assert parsed2[0]["value"] == ""

    # Space separated 6 columns
    c3 = ".youtube.com TRUE / TRUE 2000000000 LOGIN_INFO"
    parsed3 = cookie_manager.parse_netscape_cookies(c3)
    assert len(parsed3) == 1
    assert parsed3[0]["name"] == "LOGIN_INFO"
    assert parsed3[0]["value"] == ""


@pytest.mark.asyncio
async def test_resolve_cookies_context_case_insensitive_and_aliases(temp_environment):
    """Verify resolve_cookies_context matches platform case-insensitively and handles twitter/x alias."""
    # Mixed case 'YouTube'
    yt_netscape = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tsid_yt_123\n"
    )
    async with cookie_manager.resolve_cookies_context("youtube", {"YouTube": yt_netscape}) as p:
        assert p is not None
        assert "sid_yt_123" in p.read_text(encoding="utf-8")

    # Platform 'twitter' matched with client key 'X'
    tw_netscape = (
        "# Netscape HTTP Cookie File\n"
        ".x.com\tTRUE\t/\tTRUE\t2000000000\tauth_token\ttoken_x_456\n"
    )
    async with cookie_manager.resolve_cookies_context("twitter", {"X": tw_netscape}) as p:
        assert p is not None
        assert "token_x_456" in p.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_request_models_and_resolver_accept_dict_with_none_values(temp_environment):
    """Verify InspectRequest, DownloadRequest, and resolve_cookies_context accept dicts with None values."""
    from app.models.inspect import InspectRequest
    from app.models.download import DownloadRequest

    # InspectRequest and DownloadRequest should accept None values in cookies dict without 422
    insp = InspectRequest(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", cookies={"youtube": None, "instagram": None})
    assert insp.cookies == {"youtube": None, "instagram": None}

    dl = DownloadRequest(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", cookies={"youtube": None})
    assert dl.cookies == {"youtube": None}

    # resolve_cookies_context should treat None value as omitted and fall back to server cookies
    async with cookie_manager.resolve_cookies_context("youtube", {"youtube": None}) as p:
        # No server cookies exist for youtube in fresh temp_environment
        assert p is None

    # When server cookies exist, None value falls back to server cookies
    server_content = VALID_NETSCAPE_INSTAGRAM.format(expiry=int(time.time()) + 99999)
    cookie_manager.save_cookies("instagram", server_content)
    server_path = cookie_manager.get_cookie_file_path("instagram")

    async with cookie_manager.resolve_cookies_context("instagram", {"instagram": None}) as p:
        assert p == server_path
        assert p.exists()


@pytest.mark.asyncio
async def test_resolve_cookies_context_alias_and_casing_with_none_or_empty_entries(temp_environment):
    """Verify alias and case-insensitive resolution skip None or blank entries and find valid cookies."""
    tw_netscape = (
        "# Netscape HTTP Cookie File\n"
        ".x.com\tTRUE\t/\tTRUE\t2000000000\tauth_token\ttoken_x_valid\n"
    )
    # When exact key 'twitter' is None or empty string, fallback to 'x' alias
    async with cookie_manager.resolve_cookies_context("twitter", {"twitter": None, "x": tw_netscape}) as p:
        assert p is not None
        assert "token_x_valid" in p.read_text(encoding="utf-8")

    async with cookie_manager.resolve_cookies_context("twitter", {"twitter": "   ", "x": tw_netscape}) as p:
        assert p is not None
        assert "token_x_valid" in p.read_text(encoding="utf-8")

    # When exact key 'youtube' is None, fallback to 'YouTube'
    yt_netscape = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tsid_yt_valid\n"
    )
    async with cookie_manager.resolve_cookies_context("youtube", {"youtube": None, "YouTube": yt_netscape}) as p:
        assert p is not None
        assert "sid_yt_valid" in p.read_text(encoding="utf-8")




