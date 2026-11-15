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
