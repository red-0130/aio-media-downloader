"""Tier 2 Boundary Tests: B05 - Server-Sent Events (SSE) & Concurrency Boundaries.

Covers:
- Client early disconnect handling
- Multiple concurrent subscribers to the same task
- Immediate event delivery when subscribing to completed tasks
- Immediate error delivery when subscribing to failed tasks
- 404 response when querying non-existent task IDs via REST API
- Rapid burst event delivery with strict FIFO ordering guarantees
- Subscriber queue cleanup on generator cancellation / disconnect
- Slow consumer backpressure and QueueFull resilience
- SSE data payload JSON structure and formatting
- Reconnection lifecycle simulating network drops
- Task memory cleanup via progress_manager.cleanup_task
- Cross-task event isolation between distinct concurrent tasks
"""

import asyncio
import json
import httpx
import pytest

from app.services import progress_manager


@pytest.mark.asyncio
async def test_sse_subscribe_to_completed_task():
    """Verify subscribing to an already completed task immediately emits 'complete' event."""
    task = await progress_manager.create_task("task-completed-test")
    await progress_manager.set_completed(
        task_id=task.task_id,
        filename="video.mp4",
        download_url="/api/files/task-completed-test/video.mp4",
        file_size=1048576,
    )

    gen = progress_manager.subscribe_sse(task.task_id)
    first_event = await anext(gen)
    assert first_event["event"] == "complete"
    data = json.loads(first_event["data"])
    assert data["status"] == "completed"
    assert data["filename"] == "video.mp4"
    assert data["download_url"] == "/api/files/task-completed-test/video.mp4"

    # Generator terminates immediately after complete event
    with pytest.raises(StopAsyncIteration):
        await anext(gen)


@pytest.mark.asyncio
async def test_sse_subscribe_to_error_task():
    """Verify subscribing to a failed task immediately emits 'error' event."""
    task = await progress_manager.create_task("task-error-test")
    await progress_manager.set_error(task.task_id, "Video is private")

    gen = progress_manager.subscribe_sse(task.task_id)
    event = await anext(gen)
    assert event["event"] == "error"
    data = json.loads(event["data"])
    assert data["status"] == "error"
    assert "private" in data["message"]

    with pytest.raises(StopAsyncIteration):
        await anext(gen)


@pytest.mark.asyncio
async def test_sse_non_existent_task_api_returns_404(async_client: httpx.AsyncClient):
    """Verify GET /api/progress/{non_existent_task} returns HTTP 404."""
    resp = await async_client.get("/api/progress/non-existent-task-uuid-999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sse_multiple_concurrent_subscribers_same_task():
    """Verify multiple concurrent subscribers to the same task all receive broadcast events."""
    task = await progress_manager.create_task("task-multi-sub")
    subscribers = [progress_manager.subscribe_sse(task.task_id) for _ in range(5)]

    # Initial progress event on each subscriber
    for sub in subscribers:
        ev = await anext(sub)
        assert ev["event"] == "progress"

    # Broadcast update
    await progress_manager.update_progress(
        task_id=task.task_id,
        progress=45.0,
        speed="5.0MiB/s",
        eta=10,
    )

    # All subscribers receive the 45% event
    for sub in subscribers:
        ev = await anext(sub)
        assert ev["event"] == "progress"
        data = json.loads(ev["data"])
        assert data["progress"] == 45.0
        assert data["speed"] == "5.0MiB/s"

    # Clean up generators
    for sub in subscribers:
        await sub.aclose()


@pytest.mark.asyncio
async def test_sse_rapid_event_burst_ordering():
    """Verify rapid consecutive progress events maintain strict FIFO ordering."""
    task = await progress_manager.create_task("task-burst-order")
    sub = progress_manager.subscribe_sse(task.task_id)
    await anext(sub)  # consume initial snapshot

    # Emit 30 rapid events
    for p in range(1, 31):
        await progress_manager.update_progress(task.task_id, float(p))

    received_progress = []
    for _ in range(30):
        ev = await anext(sub)
        data = json.loads(ev["data"])
        received_progress.append(data["progress"])

    assert received_progress == [float(p) for p in range(1, 31)]
    await sub.aclose()


@pytest.mark.asyncio
async def test_sse_subscriber_cleanup_on_early_disconnect():
    """Verify subscriber queues are removed from memory when client disconnects mid-stream."""
    task = await progress_manager.create_task("task-disconnect-test")
    sub = progress_manager.subscribe_sse(task.task_id)
    await anext(sub)  # initial snapshot

    # Push and consume a streaming update so generator is inside active listening loop
    await progress_manager.update_progress(task.task_id, 15.0)
    await anext(sub)

    # Active subscriber exists
    assert len(progress_manager._subscribers.get(task.task_id, [])) == 1

    # Client closes connection mid-stream
    await sub.aclose()

    # Subscriber queue is cleaned up in finally block
    assert len(progress_manager._subscribers.get(task.task_id, [])) == 0


@pytest.mark.asyncio
async def test_sse_slow_consumer_backpressure_queue_full():
    """Verify queue overflow from slow consumers does not raise unhandled exceptions."""
    task = await progress_manager.create_task("task-overflow-test")
    sub = progress_manager.subscribe_sse(task.task_id)
    await anext(sub)  # consume initial event

    # Queue maxsize is 50. Push 65 events without consumer reading them
    for i in range(65):
        await progress_manager.update_progress(task.task_id, float(i))

    # Producer didn't crash; consumer can still read remaining queued events
    first_buffered = await anext(sub)
    assert first_buffered["event"] == "progress"
    await sub.aclose()


def test_sse_event_format_and_json_validity():
    """Verify formatted SSE event structure contains valid JSON and required schema keys."""
    event = progress_manager._format_event(
        "progress",
        {"status": "downloading", "progress": 75.5, "speed": "1.2MB/s", "eta": 5},
    )
    assert event["event"] == "progress"
    assert isinstance(event["data"], str)

    parsed = json.loads(event["data"])
    assert parsed["status"] == "downloading"
    assert parsed["progress"] == 75.5
    assert parsed["speed"] == "1.2MB/s"
    assert parsed["eta"] == 5


@pytest.mark.asyncio
async def test_sse_reconnection_lifecycle():
    """Verify a client that disconnects can reconnect to the same task and receive subsequent updates."""
    task = await progress_manager.create_task("task-reconnect")

    # Client 1 connects and drops
    c1 = progress_manager.subscribe_sse(task.task_id)
    await anext(c1)
    await progress_manager.update_progress(task.task_id, 20.0)
    await anext(c1)
    await c1.aclose()

    # Client 2 connects (reconnection)
    c2 = progress_manager.subscribe_sse(task.task_id)
    snapshot = await anext(c2)
    data = json.loads(snapshot["data"])
    # Reflects the latest progress (20.0)
    assert data["progress"] == 20.0

    # Completes
    await progress_manager.set_completed(task.task_id, "out.mp4", "/api/files/out.mp4", 100)
    complete_ev = await anext(c2)
    assert complete_ev["event"] == "complete"
    await c2.aclose()


@pytest.mark.asyncio
async def test_sse_task_cleanup_removes_from_registry():
    """Verify cleanup_task thoroughly purges task progress and subscriber references."""
    task = await progress_manager.create_task("task-to-purge")
    assert progress_manager.get_task(task.task_id) is not None

    await progress_manager.cleanup_task(task.task_id)
    assert progress_manager.get_task(task.task_id) is None
    assert task.task_id not in progress_manager._subscribers


@pytest.mark.asyncio
async def test_sse_terminal_event_terminates_stream():
    """Verify receipt of 'complete' event causes the generator to terminate cleanly."""
    task = await progress_manager.create_task("task-terminal-test")
    sub = progress_manager.subscribe_sse(task.task_id)
    await anext(sub)  # initial event

    await progress_manager.set_completed(
        task.task_id, "done.mp4", "/files/done.mp4", 500
    )

    ev = await anext(sub)
    assert ev["event"] == "complete"

    with pytest.raises(StopAsyncIteration):
        await anext(sub)


@pytest.mark.asyncio
async def test_sse_concurrent_tasks_isolation():
    """Verify subscribers to task-A never receive events broadcast to task-B."""
    task_a = await progress_manager.create_task("task-iso-A")
    task_b = await progress_manager.create_task("task-iso-B")

    sub_a = progress_manager.subscribe_sse(task_a.task_id)
    sub_b = progress_manager.subscribe_sse(task_b.task_id)
    await anext(sub_a)
    await anext(sub_b)

    # Emit only on task-A
    await progress_manager.update_progress(task_a.task_id, 99.0)

    ev_a = await anext(sub_a)
    assert json.loads(ev_a["data"])["progress"] == 99.0

    # Ensure task-B queue remains empty (timeout on read)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(sub_b), timeout=0.05)

    await sub_a.aclose()
    await sub_b.aclose()
