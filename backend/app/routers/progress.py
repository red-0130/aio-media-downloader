"""API route handler for Server-Sent Events (SSE) download progress streaming."""

from fastapi import APIRouter, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from app.services import progress_manager, security

router = APIRouter()


@router.get("/progress/{task_id}")
async def get_progress_stream(task_id: str):
    """Stream real-time download progress events for a task via SSE."""
    if not security.is_valid_task_id(task_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid task ID: '{task_id}'",
        )
    task = progress_manager.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )

    return EventSourceResponse(progress_manager.subscribe_sse(task_id))
