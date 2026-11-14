"""Pydantic models for proxy configuration."""

from typing import Literal
from pydantic import BaseModel, Field


class ProxyConfig(BaseModel):
    """Current proxy settings configuration."""

    proxy: str | None = Field(None, description="SOCKS5 or HTTP proxy URL")
    source: Literal["runtime", "env", "none"] = Field(
        "none", description="Source of current proxy configuration"
    )


class ProxyUpdateRequest(BaseModel):
    """Payload to update the runtime proxy setting."""

    proxy: str | None = Field(None, description="New proxy URL, or null/empty to clear")
