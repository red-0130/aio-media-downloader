"""Unit tests for SOCKS5 and HTTP proxy manager."""

import pytest
from app.config import settings
from app.services import proxy_manager


def test_proxy_default_none(monkeypatch):
    monkeypatch.setattr(settings, "SOCKS5_PROXY", None)
    proxy_manager.reset_runtime_proxy()

    assert proxy_manager.get_proxy() is None
    cfg = proxy_manager.get_proxy_config()
    assert cfg.proxy is None
    assert cfg.source == "none"


def test_proxy_env_fallback(monkeypatch):
    monkeypatch.setattr(settings, "SOCKS5_PROXY", "socks5://proxy.example.com:1080")
    proxy_manager.reset_runtime_proxy()

    assert proxy_manager.get_proxy() == "socks5://proxy.example.com:1080"
    cfg = proxy_manager.get_proxy_config()
    assert cfg.proxy == "socks5://proxy.example.com:1080"
    assert cfg.source == "env"


def test_proxy_runtime_override(monkeypatch):
    monkeypatch.setattr(settings, "SOCKS5_PROXY", "socks5://env-proxy.com:1080")
    proxy_manager.reset_runtime_proxy()

    # Set runtime proxy
    proxy_manager.set_proxy("socks5://runtime-proxy.com:9050")
    assert proxy_manager.get_proxy() == "socks5://runtime-proxy.com:9050"

    cfg = proxy_manager.get_proxy_config()
    assert cfg.proxy == "socks5://runtime-proxy.com:9050"
    assert cfg.source == "runtime"

    # Runtime clear proxy explicitly
    proxy_manager.set_proxy(None)
    assert proxy_manager.get_proxy() is None
    assert proxy_manager.get_proxy_config().source == "runtime"

    # Reset runtime reverts to env
    proxy_manager.reset_runtime_proxy()
    assert proxy_manager.get_proxy() == "socks5://env-proxy.com:1080"
    assert proxy_manager.get_proxy_config().source == "env"


def test_proxy_url_validation():
    valid = [
        "socks5://127.0.0.1:1080",
        "socks5h://user:pass@proxy.local:1080",
        "http://proxy.corp.com:8080",
        "https://secure-proxy.com:8443",
    ]
    for p in valid:
        assert proxy_manager.validate_proxy_url(p) == p

    invalid = [
        "ftp://proxy.com:21",
        "gopher://proxy.com",
        "not_a_proxy",
        "socks5://",
        "socks5://proxy host.com:1080",      # Whitespace in hostname
        "http://proxy:0",                    # Port below 1
        "http://proxy:65536",                # Port above 65535
        "socks5://proxy:notaport",           # Non-integer port
    ]
    for p in invalid:
        with pytest.raises(ValueError):
            proxy_manager.validate_proxy_url(p)


def test_proxy_port_boundary_validation():
    # Boundary port 1
    assert proxy_manager.validate_proxy_url("socks5://127.0.0.1:1") == "socks5://127.0.0.1:1"
    # Boundary port 65535
    assert proxy_manager.validate_proxy_url("socks5://127.0.0.1:65535") == "socks5://127.0.0.1:65535"

    # Out of range ports
    for bad_port in (0, -1, 65536, 70000):
        with pytest.raises(ValueError):
            proxy_manager.validate_proxy_url(f"socks5://127.0.0.1:{bad_port}")
