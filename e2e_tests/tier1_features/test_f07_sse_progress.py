"""Tier 1 Feature Coverage: F07 - Real-Time SSE Progress Stream (GET /api/progress/{task_id})."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services import progress_manager


async def parse_sse_events(
    client: httpx.AsyncClient, task_id: str, max_events: int = 5
) -> list[dict[str, Any]]:
    """Helper to collect SSE events from endpoint."""
    events: list[dict[str, Any]] = []
    current_event = "message"

    async with client.stream("GET", f"/api/progress/{task_id}") as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("event:"):
                current_event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_str = line[len("data:") :].strip()
                try:
                    payload = json.loads(data_str)
                except Exception:
                    payload = data_str
                events.append({"event": current_event, "data": payload})
                if current_event in ("complete", "error") or len(events) >= max_events:
                    break

    return events


@pytest.mark.asyncio
async def test_sse_progress_percentage_events(async_client: httpx.AsyncClient):
    """Verify SSE stream emits progress events with percentage float."""
    task = await progress_manager.create_task()
    tid = task.task_id

    async def emit_updates():
        await asyncio.sleep(0.05)
        await progress_manager.update_progress(tid, progress=25.0)
        await asyncio.sleep(0.05)
        await progress_manager.update_progress(tid, progress=75.0)
        await asyncio.sleep(0.05)
        await progress_manager.set_completed(
            tid, filename="test.mp4", download_url=f"/api/files/{tid}/test.mp4", file_size=1024
        )

    emitter = asyncio.create_task(emit_updates())
    events = await parse_sse_events(async_client, tid, max_events=10)
    await emitter

    progress_events = [e for e in events if e["event"] == "progress"]
    assert len(progress_events) >= 1
    percentages = [e["data"]["progress"] for e in progress_events if isinstance(e["data"], dict)]
    assert any(p >= 0.0 for p in percentages)


@pytest.mark.asyncio
async def test_sse_progress_speed_and_eta_fields(async_client: httpx.AsyncClient):
    """Verify progress events contain speed and eta metrics."""
    task = await progress_manager.create_task()
    tid = task.task_id

    async def emit_metrics():
        await asyncio.sleep(0.05)
        await progress_manager.update_progress(
            tid, progress=45.2, speed="4.2MiB/s", eta=12, message="Downloading 45.2%"
        )
        await asyncio.sleep(0.05)
        await progress_manager.set_completed(
            tid, filename="test.mp4", download_url=f"/api/files/{tid}/test.mp4", file_size=1024
        )

    emitter = asyncio.create_task(emit_metrics())
    events = await parse_sse_events(async_client, tid, max_events=10)
    await emitter

    metric_events = [
        e for e in events
        if e["event"] == "progress" and isinstance(e["data"], dict) and e["data"].get("speed") == "4.2MiB/s"
    ]
    assert len(metric_events) == 1
    assert metric_events[0]["data"]["eta"] == 12


@pytest.mark.asyncio
async def test_sse_postprocessing_status_transition(async_client: httpx.AsyncClient):
    """Verify state transition to postprocessing emits postprocessing SSE event."""
    task = await progress_manager.create_task()
    tid = task.task_id

    async def emit_postprocessing():
        await asyncio.sleep(0.05)
        await progress_manager.set_postprocessing(tid, message="Converting audio to MP3...")
        await asyncio.sleep(0.05)
        await progress_manager.set_completed(
            tid, filename="audio.mp3", download_url=f"/api/files/{tid}/audio.mp3", file_size=2048
        )

    emitter = asyncio.create_task(emit_postprocessing())
    events = await parse_sse_events(async_client, tid, max_events=10)
    await emitter

    post_events = [e for e in events if e["event"] == "postprocessing"]
    assert len(post_events) == 1
    assert post_events[0]["data"]["status"] == "postprocessing"
    assert "Converting audio" in post_events[0]["data"]["message"]


@pytest.mark.asyncio
async def test_sse_complete_event_with_download_url(async_client: httpx.AsyncClient):
    """Verify complete event emits download_url and filename."""
    task = await progress_manager.create_task()
    tid = task.task_id

    async def emit_completion():
        await asyncio.sleep(0.05)
        await progress_manager.set_completed(
            tid,
            filename="bundle.zip",
            download_url=f"/api/files/{tid}/bundle.zip",
            file_size=18492011,
        )

    emitter = asyncio.create_task(emit_completion())
    events = await parse_sse_events(async_client, tid, max_events=10)
    await emitter

    complete_events = [e for e in events if e["event"] == "complete"]
    assert len(complete_events) == 1
    data = complete_events[0]["data"]
    assert data["status"] == "completed"
    assert data["download_url"] == f"/api/files/{tid}/bundle.zip"
    assert data["filename"] == "bundle.zip"
    assert data["file_size"] == 18492011


@pytest.mark.asyncio
async def test_sse_invalid_task_id_handling(async_client: httpx.AsyncClient):
    """Verify requesting SSE progress for an unknown task returns 404."""
    resp = await async_client.get("/api/progress/nonexistent-task-999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sse_error_event_on_task_failure(async_client: httpx.AsyncClient):
    """Verify error event is emitted when download task fails."""
    task = await progress_manager.create_task()
    tid = task.task_id

    async def emit_err():
        await asyncio.sleep(0.05)
        await progress_manager.set_error(tid, error_message="Platform connection timed out")

    emitter = asyncio.create_task(emit_err())
    events = await parse_sse_events(async_client, tid, max_events=10)
    await emitter

    err_events = [e for e in events if e["event"] == "error"]
    assert len(err_events) == 1
    assert "timed out" in err_events[0]["data"]["message"]
