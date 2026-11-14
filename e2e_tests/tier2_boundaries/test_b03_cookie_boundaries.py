"""Tier 2 Boundary Tests: B03 - Netscape Cookie Parsing & Storage Boundaries.

Covers:
- CRLF vs LF line ending normalization
- Expired timestamp detection and reporting
- Empty cookie content rejection (0 bytes)
- Non-Netscape formats (JSON, raw HTTP headers) rejection
- Multiple domains in a single cookie file
- Session cookies without expiration timestamps (expiry=0)
- Case-insensitive boolean flag parsing (TRUE/FALSE)
- Special characters, base64 tokens, and spaces in cookie values
- Scalability with large cookie files (500+ entries)
- Corrupted lines, missing columns, and #HttpOnly_ prefixes
- Platform parameter path traversal rejection in cookie endpoints
- Full REST lifecycle under boundary cookie inputs
"""

from pathlib import Path
import httpx
import pytest

from app.services import cookie_manager


def test_cookie_crlf_vs_lf_line_endings():
    """Verify Netscape parser produces identical output for Windows CRLF and Unix LF line endings."""
    entry = ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\tIG_SECRET_123"
    content_crlf = f"# Netscape HTTP Cookie File\r\n{entry}\r\n"
    content_lf = f"# Netscape HTTP Cookie File\n{entry}\n"

    parsed_crlf = cookie_manager.parse_netscape_cookies(content_crlf)
    parsed_lf = cookie_manager.parse_netscape_cookies(content_lf)

    assert len(parsed_crlf) == 1
    assert len(parsed_lf) == 1
    assert parsed_crlf[0]["name"] == "sessionid"
    assert parsed_crlf[0]["value"] == "IG_SECRET_123"
    assert parsed_crlf == parsed_lf


def test_cookie_expired_timestamp_detection(isolated_env):
    """Verify cookies with expired unix timestamps are accurately detected and marked invalid."""
    past_expiry = 1000000000  # Year 2001
    content = (
        f"# Netscape HTTP Cookie File\n"
        f".instagram.com\tTRUE\t/\tTRUE\t{past_expiry}\tsessionid\told_session\n"
    )
    cookie_manager.save_cookies("instagram", content)
    status = cookie_manager.check_cookie_status("instagram")

    assert status.exists is True
    assert status.valid is False
    assert status.cookie_count == 1
    assert "expired" in (status.details or "").lower()


def test_cookie_empty_file_rejected():
    """Verify empty or blank cookie content is rejected."""
    for empty_input in ("", "   ", "\n\r\t"):
        is_valid, count, err = cookie_manager.verify_netscape_content(empty_input)
        assert is_valid is False
        assert count == 0
        assert "empty" in (err or "").lower()


@pytest.mark.asyncio
async def test_cookie_non_netscape_json_rejected(async_client: httpx.AsyncClient):
    """Verify non-Netscape JSON or raw headers format is rejected with HTTP 400."""
    json_cookie = '{"name": "sessionid", "value": "123", "domain": ".instagram.com"}'
    resp = await async_client.post(
        "/api/settings/cookies",
        json={"platform": "instagram", "content": json_cookie},
    )
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower()


def test_cookie_multiple_domains_in_single_file():
    """Verify cookies for different domains and subdomains within one file are all parsed."""
    content = (
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\ttoken1\n"
        ".facebook.com\tTRUE\t/\tTRUE\t2147483647\tc_user\t1000293\n"
        "graph.instagram.com\tFALSE\t/\tTRUE\t2147483647\tdsr\txyz\n"
    )
    cookies = cookie_manager.parse_netscape_cookies(content)
    assert len(cookies) == 3
    domains = {c["domain"] for c in cookies}
    assert domains == {".instagram.com", ".facebook.com", "graph.instagram.com"}


def test_cookie_session_cookies_without_expiry_handled(isolated_env):
    """Verify session cookies (expiry=0 or non-expiring) are parsed and not marked expired."""
    content = (
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tindefinite_session\n"
    )
    cookie_manager.save_cookies("instagram", content)
    status = cookie_manager.check_cookie_status("instagram")

    assert status.exists is True
    assert status.valid is True
    assert status.cookie_count == 1
    assert status.expires_at is None


def test_cookie_boolean_flag_variations():
    """Verify boolean flag parsing handles case variations (TRUE, true, FALSE, false)."""
    content = (
        "# Netscape HTTP Cookie File\n"
        ".twitter.com\ttrue\t/\tfalse\t2147483647\tauth_token\tabc1\n"
        ".twitter.com\tTRUE\t/\tTRUE\t2147483647\tct0\tabc2\n"
    )
    cookies = cookie_manager.parse_netscape_cookies(content)
    assert len(cookies) == 2
    assert cookies[0]["include_subdomains"] is True
    assert cookies[0]["secure"] is False
    assert cookies[1]["include_subdomains"] is True
    assert cookies[1]["secure"] is True


def test_cookie_special_characters_in_values():
    """Verify complex cookie values (base64, padding, percent-encoding, colons, equal signs) are preserved."""
    complex_val = "v1:enc%3D%3D:token=abc==:extra"
    content = (
        f"# Netscape HTTP Cookie File\n"
        f".youtube.com\tTRUE\t/\tTRUE\t2147483647\tLOGIN_INFO\t{complex_val}\n"
    )
    cookies = cookie_manager.parse_netscape_cookies(content)
    assert len(cookies) == 1
    assert cookies[0]["value"] == complex_val


def test_cookie_large_file_parsing(isolated_env):
    """Verify scalability and performance with large cookie files (500+ lines)."""
    lines = ["# Netscape HTTP Cookie File"]
    for i in range(500):
        lines.append(
            f".youtube.com\tTRUE\t/\tTRUE\t2147483647\tcookie_{i}\tvalue_{i}_payload"
        )
    content = "\n".join(lines)

    cookies = cookie_manager.parse_netscape_cookies(content)
    assert len(cookies) == 500

    cookie_manager.save_cookies("youtube", content)
    status = cookie_manager.check_cookie_status("youtube")
    assert status.cookie_count == 500
    assert status.valid is True


def test_cookie_corrupted_lines_and_httponly_prefix():
    """Verify invalid/short lines are skipped while #HttpOnly_ lines are parsed correctly."""
    content = (
        "# Netscape HTTP Cookie File\n"
        "corrupted_line_with_too_few_parts\n"
        "# Just a comment\n"
        "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\tsecret\n"
        "another bad line\twith tabs only\n"
    )
    cookies = cookie_manager.parse_netscape_cookies(content)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "sessionid"
    assert cookies[0]["http_only"] is True


def test_cookie_platform_path_traversal_sanitized(isolated_env):
    """Verify path traversal sequences in platform names are sanitized or rejected."""
    # Attempt platform traversal
    path = cookie_manager.get_cookie_file_path("../../secrets")
    # Sanitized platform name removes slashes and dots, staying inside COOKIES_DIR
    assert path.parent == isolated_env["cookies_dir"].resolve()
    assert ".." not in path.name
    assert "/" not in path.name


@pytest.mark.asyncio
async def test_cookie_api_lifecycle_with_boundaries(
    async_client: httpx.AsyncClient, isolated_env
):
    """Verify complete cookie settings REST API lifecycle with boundary inputs."""
    cookie_body = (
        "# Netscape HTTP Cookie File\r\n"
        ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\tbound_tok_123\r\n"
    )

    # 1. Post cookies
    save_resp = await async_client.post(
        "/api/settings/cookies",
        json={"platform": "instagram", "content": cookie_body},
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "saved"

    # 2. Inspect status
    status_resp = await async_client.get("/api/settings/cookies")
    assert status_resp.status_code == 200
    ig_status = status_resp.json()["instagram"]
    assert ig_status["exists"] is True
    assert ig_status["valid"] is True
    assert ig_status["cookie_count"] == 1

    # 3. Delete cookies
    del_resp = await async_client.delete("/api/settings/cookies/instagram")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # 4. Status reflects missing
    status_after = await async_client.get("/api/settings/cookies")
    assert status_after.json()["instagram"]["exists"] is False
