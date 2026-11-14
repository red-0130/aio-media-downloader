"""Pydantic models for media download requests and responses."""

from typing import Any, Literal
from pydantic import BaseModel, Field


class DownloadRequest(BaseModel):
    """Payload to request media download."""

    url: str = Field(..., description="Target media URL")
    format_id: str | None = Field("best", description="Requested format identifier")
    selected_indices: list[int] | None = Field(
        None, description="Subset of item indices to download (for carousels/stories)"
    )
    extract_audio: bool = Field(False, description="Whether to extract audio only")
    audio_format: Literal["mp3", "m4a", "wav"] = Field("mp3", description="Audio container format")
    package_as_zip: bool = Field(True, description="Whether to bundle multiple items into a ZIP archive")
    metadata: dict[str, Any] | None = Field(None, description="Optional pre-inspected metadata")
    cookies: dict[str, str | None] | str | None = Field(
        None,
        description="Optional client session cookies (Netscape format text per platform or raw string)",
    )
    proxy: str | None = Field(
        None, description="Optional client session proxy URL"
    )


class DownloadResponse(BaseModel):
    """Initial response acknowledging download task creation."""

    task_id: str = Field(..., description="Unique task identifier")
    status: str = Field("queued", description="Initial task status")


class DownloadFileInfo(BaseModel):
    """Metadata for an individual unbundled downloaded file."""

    filename: str = Field(..., description="Filename of individual file")
    file_path: str = Field(..., description="Absolute path on disk")
    file_size: int = Field(..., description="Size in bytes")
    download_url: str = Field(..., description="Relative API URL to retrieve file")


class DownloadResult(BaseModel):
    """Final result of a completed download task."""

    task_id: str = Field(..., description="Unique task identifier")
    filename: str = Field(..., description="Human-friendly filename of the output media or bundle")
    file_path: str = Field(..., description="Absolute path on disk to the output file")
    file_size: int = Field(..., description="Size of the output file in bytes")
    download_url: str = Field(..., description="Relative API URL to retrieve the file")
    is_zip: bool = Field(False, description="True if output is a packaged ZIP archive")
    files: list[DownloadFileInfo] | None = Field(
        None, description="List of individual files if delivered unbundled"
    )
