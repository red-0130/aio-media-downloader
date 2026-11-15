"""Tier 1 Feature Coverage: F13 - SOCKS5 Proxy Configuration."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import settings
from app.services import proxy_manager, ytdlp_service


def test_proxy_configured_via_env_var(isolated_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    """Verify SOCKS5 proxy configured via environment variable is detected."""
    test_proxy = "socks5://127.0.0.1:1080"
    monkeypatch.setattr(settings, "SOCKS5_PROXY", test_proxy)
    proxy_manager.reset_runtime_proxy()

    assert proxy_manager.get_proxy() == test_proxy
    cfg = proxy_manager.get_proxy_config()
    assert cfg.proxy == test_proxy
    assert cfg.source == "env"

    # Client-facing config must mask default proxy URL
    cfg_client = proxy_manager.get_proxy_config(client_facing=True)
    assert cfg_client.proxy is None
    assert cfg_client.source == "env"


@pytest.mark.asyncio
async def test_default_socks5_proxy_not_leaked_via_api(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify GET /api/settings/proxy masks default proxy and leaks no credentials/URL."""
    secret_proxy = "socks5://sec_user:sec_pass@secret.corp.internal:1080"
    monkeypatch.setattr(settings, "SOCKS5_PROXY", secret_proxy)
    proxy_manager.reset_runtime_proxy()

    resp = await async_client.get("/api/settings/proxy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["proxy"] is None
    assert data["source"] == "env"
    assert "sec_user" not in resp.text
    assert "sec_pass" not in resp.text
    assert "secret.corp.internal" not in resp.text


@pytest.mark.asyncio
async def test_proxy_configured_via_api_settings(async_client: httpx.AsyncClient):
    """Verify updating proxy via POST /api/settings/proxy takes effect with source 'runtime'."""
    proxy_manager.reset_runtime_proxy()
    payload = {"proxy": "socks5://192.168.1.100:9050"}
    resp = await async_client.post("/api/settings/proxy", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["proxy"] == "socks5://192.168.1.100:9050"
    assert data["source"] == "runtime"
    assert proxy_manager.get_proxy() == "socks5://192.168.1.100:9050"


@pytest.mark.asyncio
async def test_get_proxy_status_api(async_client: httpx.AsyncClient):
    """Verify GET /api/settings/proxy returns current proxy configuration."""
    proxy_manager.set_proxy("socks5://10.0.0.5:1080")
    resp = await async_client.get("/api/settings/proxy")

    assert resp.status_code == 200
    data = resp.json()
    assert data["proxy"] == "socks5://10.0.0.5:1080"
    assert data["source"] == "runtime"


@pytest.mark.asyncio
async def test_clear_proxy_via_api(async_client: httpx.AsyncClient):
    """Verify clearing proxy via POST /api/settings/proxy with null resets proxy."""
    proxy_manager.set_proxy("socks5://10.0.0.5:1080")
    resp = await async_client.post("/api/settings/proxy", json={"proxy": None})

    assert resp.status_code == 200
    data = resp.json()
    assert data["proxy"] is None
    assert proxy_manager.get_proxy() is None


@pytest.mark.asyncio
async def test_proxy_flag_injected_into_engine_cli(
    mock_bin_path: Path, call_log: Any
):
    """Verify active proxy is passed to CLI subprocess with --proxy flag."""
    call_log.clear()
    test_proxy = "socks5://proxy.secure.net:1080"
    proxy_manager.set_proxy(test_proxy)

    await ytdlp_service.inspect_url(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        proxy=test_proxy,
    )

    records = call_log.filter_by_engine("yt-dlp")
    assert len(records) >= 1
    assert records[0]["proxy"] == test_proxy


@pytest.mark.asyncio
async def test_invalid_proxy_scheme_rejected(async_client: httpx.AsyncClient):
    """Verify unsupported proxy schemes (e.g. ftp, ssh) are rejected with 400."""
    resp = await async_client.post(
        "/api/settings/proxy", json={"proxy": "ftp://proxy.example.com:21"}
    )
    assert resp.status_code == 400
    assert "Unsupported proxy scheme" in resp.json()["detail"]
