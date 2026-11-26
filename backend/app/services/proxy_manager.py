"""Proxy management service for runtime and environment proxy settings."""

import urllib.parse
from app.config import settings
from app.models.proxy import ProxyConfig

# In-memory runtime proxy override
_runtime_proxy: str | None = None
_runtime_set: bool = False


def validate_proxy_url(proxy: str | None) -> str | None:
    """Validate proxy URL format (e.g., socks5://user:pass@host:port or http://host:port)."""
    if not proxy or not proxy.strip():
        return None

    cleaned = proxy.strip()
    try:
        parsed = urllib.parse.urlsplit(cleaned)
    except Exception as e:
        raise ValueError(f"Invalid proxy URL: {e}")

    if not parsed.scheme or parsed.scheme.lower() not in ("socks5", "socks5h", "http", "https"):
        raise ValueError(
            f"Unsupported proxy scheme '{parsed.scheme}'. Supported schemes: socks5, socks5h, http, https"
        )

    try:
        hostname = parsed.hostname
    except ValueError:
        raise ValueError("Invalid proxy hostname or port in proxy URL")

    if not hostname:
        raise ValueError("Proxy URL must include a valid hostname")

    if any(c.isspace() for c in hostname):
        raise ValueError("Proxy hostname cannot contain whitespace")

    try:
        port = parsed.port
    except ValueError:
        raise ValueError("Proxy port must be a valid integer between 1 and 65535")

    if port is not None:
        if not (1 <= port <= 65535):
            raise ValueError(f"Proxy port must be between 1 and 65535 (got {port})")

    return cleaned


def set_proxy(proxy: str | None) -> None:
    """Set the runtime proxy configuration."""
    global _runtime_proxy, _runtime_set
    if proxy is None or not proxy.strip():
        _runtime_proxy = None
        _runtime_set = True
    else:
        validated = validate_proxy_url(proxy)
        _runtime_proxy = validated
        _runtime_set = True


def reset_runtime_proxy() -> None:
    """Clear any runtime override and revert to environment configuration."""
    global _runtime_proxy, _runtime_set
    _runtime_proxy = None
    _runtime_set = False


def get_proxy() -> str | None:
    """Return effective proxy URL according to priority: runtime -> env -> None."""
    return get_proxy_config(client_facing=False).proxy


def get_proxy_config(client_facing: bool = False) -> ProxyConfig:
    """Return structured proxy configuration indicating current value and source.

    When client_facing is True, sensitive default proxy URLs (e.g. from environment)
    are masked (proxy=None) to prevent leaking internal SOCKS5 configuration to clients.
    """
    global _runtime_proxy, _runtime_set
    if _runtime_set and _runtime_proxy is not None:
        return ProxyConfig(proxy=_runtime_proxy, source="runtime")

    if not _runtime_set and settings.SOCKS5_PROXY:
        if client_facing:
            return ProxyConfig(proxy=None, source="env")
        return ProxyConfig(proxy=settings.SOCKS5_PROXY, source="env")

    if _runtime_set and _runtime_proxy is None:
        return ProxyConfig(proxy=None, source="runtime")

    return ProxyConfig(proxy=None, source="none")
