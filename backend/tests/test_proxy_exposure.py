"""Comprehensive automated tests for SOCKS5 default configuration leak prevention.

Verifies:
1. GET /api/settings/proxy masks default proxy (proxy is None, source is 'env') and
   completely omits raw proxy URLs, hosts, and credentials from response body.
2. POST /api/settings/proxy clearing runtime proxy returns proxy: None and does not leak default proxy.
3. Subprocess error redaction in ytdlp_service.classify_error redacts default SOCKS5 proxy URLs.
4. Internal proxy resolution via proxy_manager.get_proxy() preserves the effective proxy for engines.
5. proxy_manager.get_proxy_config(client_facing=True) masks default proxy while internal call retains it.
"""

import httpx
import pytest
from app.config import settings
from app.main import app
from app.services import proxy_manager, ytdlp_service


@pytest.fixture
async def async_client():
    """Create an httpx AsyncClient connected to genuine app.main:app via ASGITransport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture(autouse=True)
def cleanup_proxy():
    """Ensure runtime proxy and env settings are cleanly reset after each test."""
    original_env_proxy = settings.SOCKS5_PROXY
    yield
    settings.SOCKS5_PROXY = original_env_proxy
    proxy_manager.reset_runtime_proxy()


def test_get_proxy_config_client_facing_masking(monkeypatch: pytest.MonkeyPatch):
    """Test get_proxy_config client_facing parameter behavior."""
    secret_proxy = "socks5://sec_user:sec_pass@internal-socks.local:1080"
    monkeypatch.setattr(settings, "SOCKS5_PROXY", secret_proxy)
    proxy_manager.reset_runtime_proxy()

    # Internal call preserves full proxy details
    internal_cfg = proxy_manager.get_proxy_config(client_facing=False)
    assert internal_cfg.proxy == secret_proxy
    assert internal_cfg.source == "env"

    # Client-facing call strictly masks proxy URL to None
    client_cfg = proxy_manager.get_proxy_config(client_facing=True)
    assert client_cfg.proxy is None
    assert client_cfg.source == "env"

    # Internal get_proxy() continues to provide effective proxy to download engines
    assert proxy_manager.get_proxy() == secret_proxy


@pytest.mark.asyncio
async def test_api_get_proxy_does_not_leak_default_socks5(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify GET /api/settings/proxy masks default proxy and raw URL/credentials are completely absent."""
    secret_proxy = "socks5://agent_user:super_secret_token@vault-proxy.corp.internal:1080"
    monkeypatch.setattr(settings, "SOCKS5_PROXY", secret_proxy)
    proxy_manager.reset_runtime_proxy()

    resp = await async_client.get("/api/settings/proxy")
    assert resp.status_code == 200
    data = resp.json()

    # proxy must be null
    assert data["proxy"] is None
    assert data["source"] == "env"

    # Entire response text must NOT leak any sensitive token, username, or hostname
    assert "agent_user" not in resp.text
    assert "super_secret_token" not in resp.text
    assert "vault-proxy.corp.internal" not in resp.text
    assert "socks5://" not in resp.text


@pytest.mark.asyncio
async def test_api_post_clear_proxy_does_not_leak_default_socks5(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify POST /api/settings/proxy with None returns null proxy without leaking default proxy."""
    secret_proxy = "socks5://admin:top_secret@hidden-socks.net:1080"
    monkeypatch.setattr(settings, "SOCKS5_PROXY", secret_proxy)
    proxy_manager.set_proxy("socks5://user-override:9050")

    resp = await async_client.post("/api/settings/proxy", json={"proxy": None})
    assert resp.status_code == 200
    data = resp.json()

    assert data["proxy"] is None
    assert "admin" not in resp.text
    assert "top_secret" not in resp.text
    assert "hidden-socks.net" not in resp.text


def test_classify_error_redacts_default_socks5_proxy(monkeypatch: pytest.MonkeyPatch):
    """Verify subprocess error messages containing default proxy URLs have the proxy redacted."""
    secret_proxy = "socks5://leak_user:secret_pw@proxy.secret-corp.internal:1080"
    monkeypatch.setattr(settings, "SOCKS5_PROXY", secret_proxy)

    stderr_with_proxy = (
        f"ERROR: Unable to download webpage: Failed to connect to {secret_proxy} (Connection refused)"
    )

    err = ytdlp_service.classify_error(stderr_with_proxy)
    err_msg = str(err)

    # Sensitive values must be completely purged from error message
    assert "leak_user" not in err_msg
    assert "secret_pw" not in err_msg
    assert "proxy.secret-corp.internal" not in err_msg
    assert secret_proxy not in err_msg
    assert "[REDACTED_PROXY]" in err_msg


def test_classify_error_without_default_proxy_unchanged(monkeypatch: pytest.MonkeyPatch):
    """Verify classify_error behaves normally when no default proxy is set."""
    monkeypatch.setattr(settings, "SOCKS5_PROXY", None)

    stderr_msg = "ERROR: Video unavailable: Private video"
    err = ytdlp_service.classify_error(stderr_msg)

    assert isinstance(err, ytdlp_service.AuthRequiredError)
    assert "Private video" in str(err)


def test_classify_error_redacts_runtime_and_custom_proxy_credentials(monkeypatch: pytest.MonkeyPatch):
    """Verify classify_error redacts passwords from custom runtime/request proxy URLs."""
    monkeypatch.setattr(settings, "SOCKS5_PROXY", None)

    custom_socks5 = "socks5://custom_user:super_secret@proxy.internal:1080"
    custom_http = "http://http_user:top_secret_pass@192.168.1.100:8080"
    custom_no_user = "socks5://:pass_only@10.0.0.1:9050"
    stderr_text = (
        f"ERROR: Unable to download webpage: Connection error with {custom_socks5}, {custom_http}, and {custom_no_user}"
    )

    err = ytdlp_service.classify_error(stderr_text)
    err_msg = str(err)

    assert "super_secret" not in err_msg
    assert "top_secret_pass" not in err_msg
    assert "pass_only" not in err_msg
    assert "socks5://custom_user:[REDACTED]@proxy.internal:1080" in err_msg
    assert "http://http_user:[REDACTED]@192.168.1.100:8080" in err_msg
    assert "socks5://:[REDACTED]@10.0.0.1:9050" in err_msg


def test_classify_error_redacts_both_default_and_runtime_proxies(monkeypatch: pytest.MonkeyPatch):
    """Verify default SOCKS5_PROXY is replaced with [REDACTED_PROXY] and runtime proxy is redacted with regex."""
    default_proxy = "socks5://def_user:def_secret@default.corp.net:1080"
    monkeypatch.setattr(settings, "SOCKS5_PROXY", default_proxy)

    runtime_proxy = "socks5://runtime_user:runtime_secret@runtime.net:1080"
    stderr_text = f"Failed {default_proxy} then failed {runtime_proxy}"

    err = ytdlp_service.classify_error(stderr_text)
    err_msg = str(err)

    assert "def_secret" not in err_msg
    assert "def_user" not in err_msg
    assert "runtime_secret" not in err_msg
    assert "[REDACTED_PROXY]" in err_msg
    assert "socks5://runtime_user:[REDACTED]@runtime.net:1080" in err_msg


def test_classify_error_redacts_credentials_across_exception_types(monkeypatch: pytest.MonkeyPatch):
    """Verify credential redaction functions across AuthRequiredError, RateLimitError, and ExtractionError."""
    monkeypatch.setattr(settings, "SOCKS5_PROXY", None)

    # 1. AuthRequiredError
    auth_stderr = "ERROR: Sign in to confirm you're not a bot. Failed via socks5://auth_u:auth_p@gate:1080"
    auth_err = ytdlp_service.classify_error(auth_stderr)
    assert isinstance(auth_err, ytdlp_service.AuthRequiredError)
    assert "auth_p" not in str(auth_err)
    assert "socks5://auth_u:[REDACTED]@gate:1080" in str(auth_err)

    # 2. RateLimitError
    rate_stderr = "HTTP Error 429: Too Many Requests on http://rate_u:rate_p@gate:8080"
    rate_err = ytdlp_service.classify_error(rate_stderr)
    assert isinstance(rate_err, ytdlp_service.RateLimitError)
    assert "rate_p" not in str(rate_err)
    assert "http://rate_u:[REDACTED]@gate:8080" in str(rate_err)

    # 3. ExtractionError
    generic_stderr = "ERROR: Connection refused to socks5://generic_u:generic_p@gate:1080"
    generic_err = ytdlp_service.classify_error(generic_stderr)
    assert isinstance(generic_err, ytdlp_service.ExtractionError)
    assert "generic_p" not in str(generic_err)
    assert "socks5://generic_u:[REDACTED]@gate:1080" in str(generic_err)


def test_classify_error_preserves_non_proxy_urls_and_social_mentions(monkeypatch: pytest.MonkeyPatch):
    """Verify standard URLs with colons followed by @mentions are not falsely matched or corrupted."""
    monkeypatch.setattr(settings, "SOCKS5_PROXY", None)

    msg_twitter = "Error accessing https://twitter.com/user: tweet from @jack"
    err_tw = ytdlp_service.classify_error(msg_twitter)
    assert "https://twitter.com/user: tweet from @jack" in str(err_tw)
    assert "[REDACTED]" not in str(err_tw)

    msg_ig = "HTTP redirect to login page (https://www.instagram.com/accounts/login/?next=@me)"
    err_ig = ytdlp_service.classify_error(msg_ig)
    assert "https://www.instagram.com/accounts/login/?next=@me" in str(err_ig)
    assert "[REDACTED]" not in str(err_ig)


def test_classify_error_redacts_proxy_in_complex_multitarget_error(monkeypatch: pytest.MonkeyPatch):
    """Verify target URLs before proxy URLs in error messages are preserved while proxy credentials are scrubbed."""
    monkeypatch.setattr(settings, "SOCKS5_PROXY", None)

    stderr_text = (
        "Error downloading https://youtube.com/watch?v=123: HTTP Error 404 for socks5://user:pass@proxy:1080"
    )
    err = ytdlp_service.classify_error(stderr_text)
    err_msg = str(err)

    assert "pass" not in err_msg
    assert "https://youtube.com/watch?v=123: HTTP Error 404 for socks5://user:[REDACTED]@proxy:1080" in err_msg


def test_classify_error_edge_case_credential_formats(monkeypatch: pytest.MonkeyPatch):
    """Verify IPv6 proxy hosts, percent-encoded characters, colons in passwords, and empty passwords."""
    monkeypatch.setattr(settings, "SOCKS5_PROXY", None)

    # IPv6 proxy host
    err_ipv6 = ytdlp_service.classify_error("Failed connection to socks5://ipv6_u:ipv6_p@[::1]:1080")
    assert "ipv6_p" not in str(err_ipv6)
    assert "socks5://ipv6_u:[REDACTED]@[::1]:1080" in str(err_ipv6)

    # Percent-encoded @ in password (%40)
    err_encoded = ytdlp_service.classify_error("Error with socks5://user:p%40ssword@proxy:1080")
    assert "p%40ssword" not in str(err_encoded)
    assert "socks5://user:[REDACTED]@proxy:1080" in str(err_encoded)

    # Colons in password
    err_colons = ytdlp_service.classify_error("Failed via socks5://user:p:a:s:s@proxy:1080")
    assert "p:a:s:s" not in str(err_colons)
    assert "socks5://user:[REDACTED]@proxy:1080" in str(err_colons)

    # Empty password
    err_empty_pw = ytdlp_service.classify_error("Failed via socks5://user:@proxy:1080")
    assert "socks5://user:[REDACTED]@proxy:1080" in str(err_empty_pw)


