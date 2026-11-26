"""Unit tests for Netscape cookie parsing, validation, and storage."""

import concurrent.futures
import os
import stat
import time
from pathlib import Path
import pytest
from app.config import settings
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
    path = cookie_manager.get_default_cookie_path("instagram")
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
    assert cookie_manager.get_default_cookie_path("twitter") is None


def test_missing_cookie_status(temp_environment):
    status = cookie_manager.check_cookie_status("youtube")
    assert status.exists is False
    assert status.valid is False
    assert status.cookie_count == 0
    assert cookie_manager.get_default_cookie_path("youtube") is None


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
    assert "tiktok" in statuses


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


VALID_NETSCAPE_TIKTOK = """# Netscape HTTP Cookie File
.tiktok.com\tTRUE\t/\tTRUE\t{expiry}\tsessionid\ttt_sess_12345
.tiktok.com\tTRUE\t/\tTRUE\t{expiry}\tsid_tt\ttt_sid_67890
"""

VALID_NETSCAPE_YOUTUBE = """# Netscape HTTP Cookie File
.youtube.com\tTRUE\t/\tTRUE\t{expiry}\tSID\tyt_sid_12345
.youtube.com\tTRUE\t/\tTRUE\t{expiry}\tLOGIN_INFO\tyt_login_67890
"""

VALID_NETSCAPE_TWITTER = """# Netscape HTTP Cookie File
.twitter.com\tTRUE\t/\tTRUE\t{expiry}\tauth_token\ttw_auth_12345
.twitter.com\tTRUE\t/\tTRUE\t{expiry}\tct0\ttw_ct0_67890
"""


def test_supported_platforms_and_aliases():
    """Verify SUPPORTED_PLATFORMS contains all 4 platforms and normalize_platform handles aliases."""
    for expected in ("instagram", "twitter", "youtube", "tiktok"):
        assert expected in cookie_manager.SUPPORTED_PLATFORMS

    # TikTok key cookies configured
    assert "tiktok" in cookie_manager.KEY_COOKIES_BY_PLATFORM
    for key in ("sessionid", "sessionid_ss", "sid_tt", "sid_guard"):
        assert key in cookie_manager.KEY_COOKIES_BY_PLATFORM["tiktok"]

    # Alias normalization
    assert cookie_manager.normalize_platform("x") == "twitter"
    assert cookie_manager.normalize_platform("X") == "twitter"
    assert cookie_manager.normalize_platform("  twitter  ") == "twitter"
    assert cookie_manager.normalize_platform("tt") == "tiktok"
    assert cookie_manager.normalize_platform("TikTok") == "tiktok"
    assert cookie_manager.normalize_platform("ig") == "instagram"
    assert cookie_manager.normalize_platform("Instagram") == "instagram"
    assert cookie_manager.normalize_platform("yt") == "youtube"
    assert cookie_manager.normalize_platform("YouTube") == "youtube"

    with pytest.raises(ValueError):
        cookie_manager.normalize_platform("  ")


def test_save_and_check_cookie_status_tiktok(temp_environment):
    """Verify saving and checking cookie status for TikTok."""
    future_ts = int(time.time()) + 86400 * 30
    content = VALID_NETSCAPE_TIKTOK.format(expiry=future_ts)

    status = cookie_manager.save_cookies("tiktok", content)
    assert status.platform == "tiktok"
    assert status.exists is True
    assert status.valid is True
    assert status.cookie_count == 2
    assert status.expires_at is not None

    refreshed = cookie_manager.check_cookie_status("tiktok")
    assert refreshed.exists is True
    assert refreshed.valid is True
    assert refreshed.cookie_count == 2

    path = cookie_manager.get_default_cookie_path("tiktok")
    assert path is not None
    assert path.exists()
    assert path.name == "tiktok.txt"


def test_expired_tiktok_cookie_detected(temp_environment):
    """Verify expired TikTok cookie is recognized and get_default_cookie_path returns None."""
    past_ts = int(time.time()) - 3600
    content = VALID_NETSCAPE_TIKTOK.format(expiry=past_ts)

    cookie_manager.save_cookies("tiktok", content)
    status = cookie_manager.check_cookie_status("tiktok")

    assert status.platform == "tiktok"
    assert status.exists is True
    assert status.valid is False
    assert "expired" in (status.details or "").lower()

    assert cookie_manager.get_default_cookie_path("tiktok") is None


def test_delete_tiktok_cookies(temp_environment):
    """Verify deleting TikTok cookies."""
    future_ts = int(time.time()) + 86400
    content = VALID_NETSCAPE_TIKTOK.format(expiry=future_ts)
    cookie_manager.save_cookies("tiktok", content)

    assert cookie_manager.get_cookie_file_path("tiktok").exists()
    deleted = cookie_manager.delete_cookies("tiktok")
    assert deleted is True
    assert not cookie_manager.get_cookie_file_path("tiktok").exists()

    status = cookie_manager.check_cookie_status("tiktok")
    assert status.exists is False
    assert status.valid is False


def test_default_cookie_lifecycle_and_validation(temp_environment):
    """Verify default cookie lifecycle through save_cookies, check_cookie_status, get_default_cookie_path, and delete_cookies."""
    future_ts = int(time.time()) + 86400 * 7

    # Initially missing
    assert cookie_manager.get_default_cookie_path("tiktok") is None
    assert cookie_manager.check_cookie_status("tiktok").exists is False

    # Invalid or header-only content raises ValueError without writing file
    with pytest.raises(ValueError):
        cookie_manager.save_cookies("tiktok", "random bad data that is not netscape")
    with pytest.raises(ValueError, match="no cookie entries"):
        cookie_manager.save_cookies("tiktok", "# Netscape HTTP Cookie File\n")
    assert cookie_manager.get_default_cookie_path("tiktok") is None

    # Saving headerless cookie line adds Netscape header automatically
    headerless_line = f".tiktok.com\tTRUE\t/\tTRUE\t{future_ts}\tsessionid\ttt_sess_12345"
    status = cookie_manager.save_cookies("tiktok", headerless_line)
    assert status.exists is True
    assert status.valid is True
    assert status.cookie_count == 1

    path = cookie_manager.get_default_cookie_path("tiktok")
    assert path is not None
    saved_text = path.read_text(encoding="utf-8")
    assert saved_text.startswith("# Netscape HTTP Cookie File\n")
    assert "tt_sess_12345" in saved_text

    # Header-only file on disk evaluates to valid=False and get_default_cookie_path returns None
    path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    header_only_status = cookie_manager.check_cookie_status("tiktok")
    assert header_only_status.exists is True
    assert header_only_status.valid is False
    assert cookie_manager.get_default_cookie_path("tiktok") is None

    # Empty file on disk evaluates to valid=False
    path.write_text("", encoding="utf-8")
    empty_status = cookie_manager.check_cookie_status("tiktok")
    assert empty_status.exists is True
    assert empty_status.valid is False
    assert cookie_manager.get_default_cookie_path("tiktok") is None

    # Deleting clears file and status
    assert cookie_manager.delete_cookies("tiktok") is True
    assert cookie_manager.check_cookie_status("tiktok").exists is False


def test_default_cookie_env_var_override(temp_environment, tmp_path, monkeypatch):
    """Verify environment variables override default cookie file path."""
    future_ts = int(time.time()) + 86400 * 5
    custom_env_file = tmp_path / "env_tiktok_cookies.txt"
    custom_env_file.write_text(VALID_NETSCAPE_TIKTOK.format(expiry=future_ts), encoding="utf-8")

    monkeypatch.setattr(settings, "TIKTOK_COOKIES_FILE", str(custom_env_file))

    resolved = cookie_manager.get_default_cookie_path("tiktok")
    assert resolved == custom_env_file.resolve()

    # If env var points to expired cookie file, get_default_cookie_path returns None
    expired_env_file = tmp_path / "expired_env_cookies.txt"
    expired_env_file.write_text(VALID_NETSCAPE_TIKTOK.format(expiry=int(time.time()) - 500), encoding="utf-8")
    monkeypatch.setattr(settings, "TIKTOK_COOKIES_FILE", str(expired_env_file))

    assert cookie_manager.get_default_cookie_path("tiktok") is None


def test_default_cookies_dir_resolution(temp_environment, tmp_path, monkeypatch):
    """Verify DEFAULT_COOKIES_DIR is checked when cookie file is placed there."""
    default_dir = tmp_path / "default_cookies"
    default_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "DEFAULT_COOKIES_DIR", default_dir)

    future_ts = int(time.time()) + 86400 * 5
    cookie_file = default_dir / "instagram.txt"
    cookie_file.write_text(VALID_NETSCAPE_INSTAGRAM.format(expiry=future_ts), encoding="utf-8")

    resolved = cookie_manager.get_default_cookie_path("instagram")
    assert resolved == cookie_file.resolve()


def test_read_only_cookie_checks_do_not_create_directories(tmp_path, monkeypatch):
    """Verify read-only checks and delete do not create missing directories, while save_cookies does."""
    cookies_dir = tmp_path / "uncreated_cookies"
    default_dir = tmp_path / "uncreated_default_cookies"
    downloads_dir = tmp_path / "uncreated_downloads"

    monkeypatch.setattr(settings, "COOKIES_DIR", cookies_dir)
    monkeypatch.setattr(settings, "DEFAULT_COOKIES_DIR", default_dir)
    monkeypatch.setattr(settings, "DOWNLOADS_DIR", downloads_dir)

    status = cookie_manager.check_cookie_status("instagram")
    assert status.exists is False
    assert status.valid is False
    assert len(cookie_manager.get_all_cookie_statuses()) == len(cookie_manager.SUPPORTED_PLATFORMS)
    assert cookie_manager.get_default_cookie_path("instagram") is None
    assert cookie_manager.delete_cookies("instagram") is False

    assert not cookies_dir.exists()
    assert not default_dir.exists()
    assert not downloads_dir.exists()

    future_ts = int(time.time()) + 86400
    saved = cookie_manager.save_cookies("instagram", VALID_NETSCAPE_INSTAGRAM.format(expiry=future_ts))
    assert saved.valid is True
    assert cookies_dir.exists()


def test_check_status_and_default_path_parse_and_resolve_once(temp_environment, monkeypatch):
    """Verify check_cookie_status parses once and get_default_cookie_path resolves and parses once."""
    future_ts = int(time.time()) + 86400
    cookie_manager.save_cookies("instagram", VALID_NETSCAPE_INSTAGRAM.format(expiry=future_ts))

    orig_parse = cookie_manager.parse_netscape_cookies
    orig_find = cookie_manager._find_candidate_cookie_path
    counts = {"parse": 0, "find": 0}

    def counting_parse(content: str):
        counts["parse"] += 1
        return orig_parse(content)

    def counting_find(platform: str):
        counts["find"] += 1
        return orig_find(platform)

    monkeypatch.setattr(cookie_manager, "parse_netscape_cookies", counting_parse)
    monkeypatch.setattr(cookie_manager, "_find_candidate_cookie_path", counting_find)

    status = cookie_manager.check_cookie_status("instagram")
    assert status.valid is True
    assert counts["parse"] == 1
    assert counts["find"] == 1

    counts["parse"] = 0
    counts["find"] = 0
    resolved = cookie_manager.get_default_cookie_path("instagram")
    assert resolved is not None
    assert counts["parse"] == 1
    assert counts["find"] == 1


def test_netscape_format_validation_strict(temp_environment, tmp_path):
    """Verify strict validation of Netscape HTTP cookie format."""
    # Valid header variants
    h1 = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tvalid\n"
    v1, c1, _ = cookie_manager.verify_netscape_content(h1)
    assert v1 is True and c1 == 1

    h2 = "# HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tvalid\n"
    v2, c2, _ = cookie_manager.verify_netscape_content(h2)
    assert v2 is True and c2 == 1

    # #HttpOnly_ line
    h3 = "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tvalid\n"
    v3, c3, _ = cookie_manager.verify_netscape_content(h3)
    assert v3 is True and c3 == 1

    # Invalid rejections
    for bad in (
        "",
        "   \n\t",
        "<html><body>Not a cookie</body></html>",
        '{"cookies": "bad"}',
        "name=value; domain=foo.com",
    ):
        v, c, err = cookie_manager.verify_netscape_content(bad)
        assert v is False
        assert c == 0
        assert err is not None

    # Corrupted default cookie file on disk evaluates to valid=False and get_default_cookie_path is None
    bad_file = settings.COOKIES_DIR / "tiktok.txt"
    bad_file.write_text("invalid plain text without tabs or columns", encoding="utf-8")

    st = cookie_manager.check_cookie_status("tiktok")
    assert st.exists is True
    assert st.valid is False

    assert cookie_manager.get_default_cookie_path("tiktok") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,tmpl,token_def,token_client", [
    ("instagram", VALID_NETSCAPE_INSTAGRAM, "def_ig_token", "client_ig_token"),
    ("twitter", VALID_NETSCAPE_TWITTER, "def_tw_token", "client_tw_token"),
    ("youtube", VALID_NETSCAPE_YOUTUBE, "def_yt_token", "client_yt_token"),
    ("tiktok", VALID_NETSCAPE_TIKTOK, "def_tt_token", "client_tt_token"),
])
async def test_cookie_precedence_all_platforms(temp_environment, platform, tmpl, token_def, token_client):
    """Verify 3-tier precedence for all 4 platforms:
    Tier 1: Client session cookie overrides default.
    Tier 2: Default cookie used when client cookie omitted.
    Tier 3: Neither exists -> None.
    """
    future_ts = int(time.time()) + 99999
    default_content = tmpl.format(expiry=future_ts).replace("12345", token_def)
    client_content = tmpl.format(expiry=future_ts).replace("12345", token_client)

    # Tier 3: Neither exists -> None
    async with cookie_manager.resolve_cookies_context(platform, None) as path:
        assert path is None

    async with cookie_manager.resolve_cookies_context(platform, {platform: None}) as path:
        assert path is None

    # Set up default cookie
    cookie_manager.save_cookies(platform, default_content)
    default_path = cookie_manager.get_default_cookie_path(platform)
    assert default_path is not None
    assert default_path.exists()

    # Tier 2: No client cookie provided -> default cookie used
    async with cookie_manager.resolve_cookies_context(platform, None) as path:
        assert path == default_path
        assert token_def in path.read_text(encoding="utf-8")

    async with cookie_manager.resolve_cookies_context(platform, {platform: None}) as path:
        assert path == default_path
        assert token_def in path.read_text(encoding="utf-8")

    # Tier 1: Client cookie provided -> client cookie used, default ignored
    async with cookie_manager.resolve_cookies_context(platform, {platform: client_content}) as path:
        assert path is not None
        assert path != default_path
        assert path.name.startswith(f"client_cookies_{platform}_")
        content_read = path.read_text(encoding="utf-8")
        assert token_client in content_read
        assert token_def not in content_read

        # Default file on disk remains intact and unchanged
        default_disk = default_path.read_text(encoding="utf-8")
        assert token_def in default_disk
        assert token_client not in default_disk

    # Client temp file unlinked after context exit
    assert not path.exists()


@pytest.mark.asyncio
async def test_client_cookie_invalid_format_raises_without_fallback(temp_environment):
    """Verify invalid client cookies raise ValueError immediately without falling back to default cookies."""
    future_ts = int(time.time()) + 99999
    cookie_manager.save_cookies("youtube", VALID_NETSCAPE_YOUTUBE.format(expiry=future_ts))

    with pytest.raises(ValueError, match="Invalid client cookie format"):
        async with cookie_manager.resolve_cookies_context("youtube", {"youtube": "invalid_cookie_format"}):
            pass




