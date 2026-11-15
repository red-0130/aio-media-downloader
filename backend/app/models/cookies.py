"""Pydantic models for cookie management."""

from pydantic import BaseModel, Field


class CookieStatus(BaseModel):
    """Status details for a platform's cookie file."""

    platform: str = Field(..., description="Platform name (instagram, twitter, youtube, tiktok)")
    exists: bool = Field(..., description="Whether a cookie file exists on disk")
    valid: bool = Field(..., description="Whether cookies are well-formatted and not expired")
    expires_at: str | None = Field(None, description="ISO timestamp of key session cookie expiration")
    cookie_count: int = Field(0, description="Total number of valid cookies found in file")
    details: str | None = Field(None, description="Human-readable status summary or error notes")


class CookieUpdateRequest(BaseModel):
    """Payload to upload or paste cookie content."""

    platform: str = Field(..., description="Target platform (instagram, twitter, youtube, tiktok)")
    content: str = Field(..., description="Netscape HTTP Cookie File formatted text")
