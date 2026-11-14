"""Tier 2 Boundary Tests: B04 - SOCKS5 / HTTP Proxy Configuration Boundaries.

Covers:
- Invalid proxy schemes (ftp://, gopher://, redis://)
- Port boundary validation (0, 1, 65535, 65536, negative, non-numeric)
- Authenticated proxy format (socks5://user:pass@host:port)
- SOCKS5h hostname resolution scheme
- IPv6 bracketed address format (socks5://[::1]:1080)
- Hostnames with embedded whitespace rejection
- Empty strings, whitespace, and None clearing runtime proxy
- Rapid toggling between proxy and direct routing
- Command-line injection of --proxy flag to extraction engines
- REST API validation and error responses for malformed proxy payloads
- Real ephemeral SOCKS5 proxy stub verification
"""

import httpx
import pytest

from app.services import proxy_manager, router


def test_proxy_invalid_scheme_rejected():
    """Verify unsupported schemes (ftp, gopher, redis) are rejected."""
    bad_schemes = [
        "ftp://proxy.example.com:1080",
        "gopher://proxy.example.com:1080",
        "redis://proxy.example.com:6379",
        "file:///etc/proxy",
    ]
    for bad in bad_schemes:
        with pytest.raises(ValueError, match="Unsupported proxy scheme"):
            proxy_manager.validate_proxy_url(bad)


def test_proxy_port_boundaries():
    """Verify port boundaries: 1 and 65535 are accepted; 0, 65536, and invalid ports fail."""
    # Valid boundaries
    assert proxy_manager.validate_proxy_url("socks5://proxy.example.com:1") is not None
    assert proxy_manager.validate_proxy_url("socks5://proxy.example.com:65535") is not None

    # Invalid boundaries
    with pytest.raises(ValueError, match="Proxy port must be between 1 and 65535"):
        proxy_manager.validate_proxy_url("socks5://proxy.example.com:0")

    with pytest.raises(ValueError, match="Proxy port must be a valid integer"):
        proxy_manager.validate_proxy_url("socks5://proxy.example.com:65536")

    with pytest.raises(ValueError, match="Proxy port must be a valid integer"):
        proxy_manager.validate_proxy_url("socks5://proxy.example.com:abc")


def test_proxy_authenticated_user_pass():
    """Verify authenticated proxies with username and password are supported and parsed."""
    auth_proxies = [
        "socks5://user:secret123@proxy.example.com:1080",
        "socks5h://admin:P%40ssw0rd!@10.0.0.1:8080",
        "http://crawler:token_xyz@edge.network:3128",
    ]
    for proxy in auth_proxies:
        validated = proxy_manager.validate_proxy_url(proxy)
        assert validated == proxy


def test_proxy_socks5h_hostname_resolution_scheme():
    """Verify socks5h scheme (remote DNS resolution) is accepted and configured."""
    s5h = "socks5h://internal-proxy.corp:1080"
    validated = proxy_manager.validate_proxy_url(s5h)
    assert validated == s5h


def test_proxy_ipv6_bracketed_host():
    """Verify IPv6 addresses enclosed in brackets are validated successfully."""
    ipv6_proxies = [
        "socks5://[::1]:1080",
        "socks5://[2001:db8::1]:1080",
        "http://[fe80::1]:8080",
    ]
    for p in ipv6_proxies:
        validated = proxy_manager.validate_proxy_url(p)
        assert validated == p


def test_proxy_whitespace_in_hostname_rejected():
    """Verify hostnames containing whitespace are rejected."""
    bad_host = "socks5://my proxy.example.com:1080"
    with pytest.raises(ValueError, match="whitespace"):
        proxy_manager.validate_proxy_url(bad_host)


def test_proxy_empty_or_none_clears_proxy(isolated_env):
    """Verify passing None, empty string, or whitespace clears any active runtime proxy."""
    proxy_manager.set_proxy("socks5://10.0.0.1:1080")
    assert proxy_manager.get_proxy() == "socks5://10.0.0.1:1080"

    # Clear with empty string
    proxy_manager.set_proxy("")
    assert proxy_manager.get_proxy() is None

    # Set and clear with None
    proxy_manager.set_proxy("socks5://10.0.0.1:1080")
    proxy_manager.set_proxy(None)
    assert proxy_manager.get_proxy() is None

    # Clear with whitespace
    proxy_manager.set_proxy("socks5://10.0.0.1:1080")
    proxy_manager.set_proxy("   \t  ")
    assert proxy_manager.get_proxy() is None


def test_proxy_rapid_toggle_between_proxy_and_direct(isolated_env):
    """Verify state consistency across rapid proxy updates and resets."""
    p1 = "socks5://proxy1.example.com:1080"
    p2 = "socks5://proxy2.example.com:1080"

    for _ in range(50):
        proxy_manager.set_proxy(p1)
        assert proxy_manager.get_proxy() == p1
        proxy_manager.set_proxy(None)
        assert proxy_manager.get_proxy() is None
        proxy_manager.set_proxy(p2)
        assert proxy_manager.get_proxy() == p2
        proxy_manager.reset_runtime_proxy()
        assert proxy_manager.get_proxy() is None


@pytest.mark.asyncio
async def test_proxy_flag_injected_to_engine_cli(
    isolated_env, mock_bin_path, call_log
):
    """Verify configured proxy is passed as --proxy to yt-dlp and gallery-dl CLI."""
    call_log.clear()
    proxy_url = "socks5://proxy.example.com:1080"
    proxy_manager.set_proxy(proxy_url)

    await router.inspect("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    logs = call_log.filter_by_engine("yt-dlp")
    assert len(logs) > 0
    assert "--proxy" in logs[0]["args"]
    proxy_idx = logs[0]["args"].index("--proxy")
    assert logs[0]["args"][proxy_idx + 1] == proxy_url


@pytest.mark.asyncio
async def test_proxy_api_validation_errors(async_client: httpx.AsyncClient):
    """Verify POST /api/settings/proxy returns HTTP 400 for invalid proxy URLs."""
    invalid_cases = [
        "not_a_url",
        "ftp://myproxy.com:1080",
        "socks5://host:70000",
        "socks5://",
    ]
    for bad_proxy in invalid_cases:
        resp = await async_client.post(
            "/api/settings/proxy",
            json={"proxy": bad_proxy},
        )
        assert resp.status_code == 400
        assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_proxy_api_lifecycle(async_client: httpx.AsyncClient, isolated_env):
    """Verify setting, fetching, and clearing proxy via REST API."""
    proxy_val = "socks5://127.0.0.1:9050"

    # Set proxy
    resp1 = await async_client.post("/api/settings/proxy", json={"proxy": proxy_val})
    assert resp1.status_code == 200
    assert resp1.json()["proxy"] == proxy_val
    assert resp1.json()["source"] == "runtime"

    # Get proxy
    resp2 = await async_client.get("/api/settings/proxy")
    assert resp2.status_code == 200
    assert resp2.json()["proxy"] == proxy_val

    # Clear proxy
    resp3 = await async_client.post("/api/settings/proxy", json={"proxy": None})
    assert resp3.status_code == 200
    assert resp3.json()["proxy"] is None


@pytest.mark.asyncio
async def test_proxy_live_socks5_stub_integration(
    socks5_proxy, isolated_env, mock_bin_path
):
    """Verify integration with running ephemeral MockSocks5Proxy fixture."""
    proxy_manager.set_proxy(socks5_proxy.proxy_url)
    assert proxy_manager.get_proxy() == socks5_proxy.proxy_url

    # Inspection works cleanly with the configured mock proxy
    res = await router.inspect("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert res.platform == "youtube"
