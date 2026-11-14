"""Pydantic models for download progress tracking."""

from typing import Any, Literal
from pydantic import BaseModel, Field


class TaskProgress(BaseModel):
    """Progress status of an asynchronous download job."""

    task_id: str = Field(..., description="Unique task identifier")
    status: Literal["queued", "downloading", "postprocessing", "completed", "error"] = Field(
        "queued", description="Current lifecycle state of the download task"
    )
    progress: float = Field(0.0, description="Download progress percentage (0.0 to 100.0)")
    speed: str | None = Field(None, description="Download speed string (e.g. 4.2MiB/s)")
    eta: int | None = Field(None, description="Estimated time remaining in seconds")
    message: str | None = Field(None, description="Detailed status or post-processing message")
    download_url: str | None = Field(None, description="Relative URL to retrieve the finished media")
    filename: str | None = Field(None, description="Filename for client saving")
    file_size: int | None = Field(None, description="Total size in bytes if available")
    error: str | None = Field(None, description="Error message if task failed")
    files: list[dict[str, Any]] | None = Field(
        None, description="List of individual completed files when unbundled"
    )
