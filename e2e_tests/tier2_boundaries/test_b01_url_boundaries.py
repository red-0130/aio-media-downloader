"""Tier 2 Boundary Tests: B01 - URL & Input Parsing Boundaries.

Covers:
- Huge URLs (>2048 characters)
- Leading/trailing whitespace, tabs, and newlines stripping
- Multiple hash fragments in URLs
- Complex and nested query parameters
- Percent-encoded paths and symbols
- Bare domains without paths
- IDN / internationalized domains / punycode
- Scheme case-insensitivity (HTTPS, Http, hTtP)
- Custom port numbers
- Malformed protocols and non-HTTP schemes
- Empty and blank string URLs
- URLs with embedded user credentials (userinfo)
"""

import httpx
import pytest

from app.services import router, security


@pytest.mark.asyncio
async def test_url_huge_length_over_2048_characters(
    async_client: httpx.AsyncClient, mock_bin_path
):
    """Verify URLs exceeding 2048 characters with lengthy query parameters are processed safely."""
    base = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    padding = "&long_param=" + ("x" * 2500)
    huge_url = base + padding

    assert len(huge_url) > 2500
    assert security.is_safe_url(huge_url) is True

    resp = await async_client.post("/api/inspect", json={"url": huge_url})
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] == "youtube"


@pytest.mark.asyncio
async def test_url_leading_trailing_whitespace_and_tabs_stripped(
    async_client: httpx.AsyncClient, mock_bin_path
):
    """Verify leading and trailing whitespace, tabs, and newlines are sanitized and accepted."""
    dirty_urls = [
        "   https://www.youtube.com/watch?v=dQw4w9WgXcQ   ",
        "\t\thttps://www.youtube.com/watch?v=dQw4w9WgXcQ\n",
        "\r\n  https://www.youtube.com/watch?v=dQw4w9WgXcQ  \r\n",
    ]
    for url_input in dirty_urls:
        resp = await async_client.post("/api/inspect", json={"url": url_input})
        assert resp.status_code == 200, f"Failed for input: {repr(url_input)}"
        assert resp.json()["platform"] == "youtube"


@pytest.mark.asyncio
async def test_url_multiple_hash_fragments(
    async_client: httpx.AsyncClient, mock_bin_path
):
    """Verify URLs with multiple hash fragments (#fragment1#fragment2) are accepted."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ#t=10s#section2#details"
    assert security.is_safe_url(url) is True

    resp = await async_client.post("/api/inspect", json={"url": url})
    assert resp.status_code == 200
    assert resp.json()["platform"] == "youtube"


@pytest.mark.asyncio
async def test_url_complex_nested_query_params(
    async_client: httpx.AsyncClient, mock_bin_path
):
    """Verify URLs with complex, encoded, and array-style query parameters are parsed cleanly."""
    url = (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        "&list=PL12345&index=3"
        "&filter=%7B%22type%22%3A%22video%22%7D"
        "&tags[]=music&tags[]=rock"
        "&signature=a%2Bb%2Fc%3D%3D"
    )
    assert security.is_safe_url(url) is True

    resp = await async_client.post("/api/inspect", json={"url": url})
    assert resp.status_code == 200
    assert resp.json()["id"] == "dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_url_percent_encoded_path_segments(
    async_client: httpx.AsyncClient, mock_bin_path
):
    """Verify percent-encoded characters in URL path segments are handled correctly."""
    url = "https://www.instagram.com/p/%43%72%6f%77%6e%5f%31%32%33/"
    assert security.is_safe_url(url) is True

    platform, primary, fallback = router.classify_url(url)
    assert platform == "instagram"
    assert primary == "gallerydl"


@pytest.mark.asyncio
async def test_url_bare_domain_without_trailing_path(
    async_client: httpx.AsyncClient, mock_bin_path
):
    """Verify bare domain URLs without paths (e.g., https://www.youtube.com) are validated safely."""
    bare_urls = [
        "https://www.youtube.com",
        "https://www.youtube.com/",
        "https://instagram.com",
    ]
    for b_url in bare_urls:
        assert security.is_safe_url(b_url) is True
        platform, primary, _ = router.classify_url(b_url)
        assert platform in ("youtube", "instagram")


def test_url_idn_and_punycode_domains():
    """Verify IDN (internationalized domain names) and punycode representations are safely handled."""
    punycode_url = "https://xn--e1afmkfd.xn--p1ai/video/12345"
    assert security.is_safe_url(punycode_url) is True

    # International characters in domain
    unicode_url = "https://münchen.de/media/sample.mp4"
    assert security.is_safe_url(unicode_url) is True


@pytest.mark.asyncio
async def test_url_scheme_case_insensitivity(
    async_client: httpx.AsyncClient, mock_bin_path
):
    """Verify scheme case-insensitivity (HTTPS, Http, hTtP)."""
    case_variants = [
        "HTTPS://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "HttpS://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "hTtP://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]
    for url in case_variants:
        assert security.is_safe_url(url) is True
        resp = await async_client.post("/api/inspect", json={"url": url})
        assert resp.status_code == 200, f"Failed for case variant: {url}"
        assert resp.json()["platform"] == "youtube"


def test_url_custom_valid_port_numbers():
    """Verify standard and custom public ports are permitted while private ones remain blocked."""
    assert security.is_safe_url("https://www.youtube.com:443/watch?v=123") is True
    assert security.is_safe_url("http://example.com:80/video.mp4") is True
    assert security.is_safe_url("https://media.example.org:8443/stream.m3u8") is True

    # Blocked local port
    assert security.is_safe_url("http://127.0.0.1:8080/secret") is False


@pytest.mark.asyncio
async def test_url_malformed_protocols_rejected(async_client: httpx.AsyncClient):
    """Verify malformed, dangerous, or unsupported protocols are rejected with 400."""
    invalid_protocols = [
        "javascript:alert('xss')",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "ftp://files.example.com/movie.mp4",
        "gopher://gopher.floodgap.com/1/",
        "ht!tp://www.youtube.com/watch?v=123",
        "ssh://git@github.com:repo/media.git",
        "mailto:user@example.com",
    ]
    for inv_url in invalid_protocols:
        assert security.is_safe_url(inv_url) is False
        resp = await async_client.post("/api/inspect", json={"url": inv_url})
        assert resp.status_code == 400, f"Expected 400 for {inv_url}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_url_empty_and_blank_strings_rejected(async_client: httpx.AsyncClient):
    """Verify completely empty or whitespace-only URLs are rejected with 400 or 422."""
    empty_cases = ["", "   ", "\t\t", "\n\r"]
    for case in empty_cases:
        assert security.is_safe_url(case) is False
        resp = await async_client.post("/api/inspect", json={"url": case})
        assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_url_with_embedded_userinfo(
    async_client: httpx.AsyncClient, mock_bin_path
):
    """Verify URLs with userinfo (user:pass@host) are handled safely without crash."""
    url_with_auth = "https://guest:welcome123@www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert security.is_safe_url(url_with_auth) is True

    resp = await async_client.post("/api/inspect", json={"url": url_with_auth})
    assert resp.status_code == 200
    assert resp.json()["platform"] == "youtube"
