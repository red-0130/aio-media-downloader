"""Pydantic models for media inspection."""

from typing import Literal
from pydantic import BaseModel, Field


class InspectRequest(BaseModel):
    """Payload to inspect a media URL."""

    url: str = Field(..., description="The URL of the media to inspect")
    cookies: dict[str, str | None] | str | None = Field(
        None,
        description="Optional client session cookies (Netscape format text per platform or raw string)",
    )
    proxy: str | None = Field(
        None, description="Optional client session proxy URL"
    )


class MediaItem(BaseModel):
    """Represents an individual item in a carousel or story."""

    index: int = Field(..., description="0-based index of the item")
    type: Literal["video", "image", "audio"] = Field(..., description="Type of media item")
    url: str | None = Field(None, description="Direct URL of the media resource if available")
    thumbnail: str | None = Field(None, description="Direct thumbnail URL")
    resolution: str | None = Field(None, description="Resolution string (e.g. 1080x1920)")
    duration: float | None = Field(None, description="Duration in seconds if video")
    date: str | None = Field(None, description="Media creation or upload date string")
    original_name: str | None = Field(None, description="Original filename stem or item identifier")
    original_name_first: str | None = Field(None, description="Original filename stem or item identifier")


class FormatOption(BaseModel):
    """Represents an available download quality or format."""

    format_id: str = Field(..., description="Unique format identifier for download")
    label: str = Field(..., description="Human-readable label for UI display")
    ext: str = Field(..., description="File extension (e.g. mp4, mp3, jpg)")
    filesize: int | float | None = Field(None, description="Estimated filesize in bytes")
    resolution: str | None = Field(None, description="Video resolution (e.g. 1080p, 720p)")


class InspectResponse(BaseModel):
    """Normalized response returned from inspection."""

    id: str = Field(..., description="Normalized identifier for the extracted media")
    url: str = Field(..., description="Original requested URL")
    platform: str = Field(..., description="Platform identifier (youtube, instagram, twitter, tiktok, generic)")
    title: str = Field(..., description="Media title or post description")
    uploader: str | None = Field(None, description="Author / channel / uploader handle")
    thumbnail: str | None = Field(None, description="Main thumbnail URL")
    media_type: Literal["video", "image", "audio", "carousel", "story"] = Field(
        ..., description="Overall classification of media"
    )
    items: list[MediaItem] = Field(default_factory=list, description="Items for carousels or stories")
    formats: list[FormatOption] = Field(
        default_factory=list, description="Available qualities/formats for single media"
    )
    date: str | None = Field(None, description="Media creation or upload date string")
    original_name_first: str | None = Field(
        None, description="Original CDN filename stem or resource identifier"
    )
