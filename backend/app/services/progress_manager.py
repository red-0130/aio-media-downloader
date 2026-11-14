"""Progress manager service for asynchronous task tracking and SSE streaming."""

import asyncio
import json
import threading
import uuid
from typing import Any, AsyncGenerator
from app.models.progress import TaskProgress


class UnifiedLock:
    """Lock supporting re-entrant async enters within the same Task and sync enters."""

    def __init__(self) -> None:
        self._async_locks: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}
        self._owner_task: asyncio.Task | None = None
        self._async_depth: int = 0
        self._thread_lock = threading.RLock()

    def _get_async_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = self._async_locks.get(loop)
        if lock is None:
            self._async_locks = {lp: lk for lp, lk in self._async_locks.items() if not lp.is_closed()}
            lock = asyncio.Lock()
            self._async_locks[loop] = lock
        return lock

    async def __aenter__(self) -> "UnifiedLock":
        current = asyncio.current_task()
        if self._owner_task is not None and self._owner_task is current:
            self._async_depth += 1
            self._thread_lock.acquire()
            return self

        lock = self._get_async_lock()
        await lock.acquire()
        self._owner_task = current
        self._async_depth = 1
        self._thread_lock.acquire()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._thread_lock.release()
        self._async_depth -= 1
        if self._async_depth == 0:
            self._owner_task = None
            lock = self._get_async_lock()
            lock.release()

    def __enter__(self) -> "UnifiedLock":
        self._thread_lock.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._thread_lock.release()


_tasks: dict[str, TaskProgress] = {}
_subscribers: dict[str, list[asyncio.Queue]] = {}
_lock = UnifiedLock()


def _format_event(event_type: str, data: dict) -> dict:
    """Format dictionary into an SSE event structure."""
    return {
        "event": event_type,
        "data": json.dumps(data),
    }


async def create_task(task_id: str | None = None) -> TaskProgress:
    """Create and register a new task."""
    tid = task_id or f"task-{uuid.uuid4().hex[:12]}"
    task = TaskProgress(task_id=tid, status="queued", progress=0.0)
    async with _lock:
        _tasks[tid] = task
        _subscribers[tid] = []
    return task


def get_task(task_id: str) -> TaskProgress | None:
    """Retrieve task progress by task_id."""
    return _tasks.get(task_id)


def get_active_task_ids() -> set[str]:
    """Return set of task IDs that are currently running."""
    active_statuses = {"queued", "downloading", "postprocessing"}
    return {tid for tid, task in _tasks.items() if task.status in active_statuses}


async def _notify_subscribers(task_id: str, event: dict) -> None:
    """Push event to all active subscriber queues for task."""
    queues = _subscribers.get(task_id, [])
    for q in list(queues):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except Exception:
                pass
            try:
                q.put_nowait(event)
            except Exception:
                pass


async def update_progress(
    task_id: str,
    progress: float,
    speed: str | None = None,
    eta: int | None = None,
    message: str | None = None,
) -> None:
    """Update task download progress and emit SSE event."""
    async with _lock:
        task = _tasks.get(task_id)
        if not task:
            return

        task.status = "downloading"
        # Ensure progress is monotonic (does not decrease during a download)
        new_progress = min(max(round(progress, 2), 0.0), 100.0)
        task.progress = max(task.progress, new_progress)
        if speed is not None:
            task.speed = speed
        if eta is not None:
            task.eta = eta
        if message is not None:
            task.message = message

        event = _format_event(
            "progress",
            {
                "status": task.status,
                "progress": task.progress,
                "speed": task.speed,
                "eta": task.eta,
                "message": task.message,
            },
        )
        await _notify_subscribers(task_id, event)


async def set_postprocessing(task_id: str, message: str = "Processing media...") -> None:
    """Mark task as post-processing (e.g. ffmpeg conversion or zipping) and emit SSE event."""
    async with _lock:
        task = _tasks.get(task_id)
        if not task:
            return

        task.status = "postprocessing"
        task.message = message

        event = _format_event(
            "postprocessing",
            {
                "status": task.status,
                "message": task.message,
            },
        )
        await _notify_subscribers(task_id, event)


async def set_completed(
    task_id: str,
    filename: str,
    download_url: str,
    file_size: int,
    files: list[dict[str, Any]] | None = None,
) -> None:
    """Mark task as completed and emit SSE completion event."""
    async with _lock:
        task = _tasks.get(task_id)
        if not task:
            return

        # Ensure download_url has properly URL-encoded special characters (e.g. # as %23)
        # to prevent browsers from interpreting the filename as a client-side fragment identifier.
        safe_download_url = download_url
        if safe_download_url and "#" in safe_download_url:
            safe_download_url = safe_download_url.replace("#", "%23")

        safe_files = files
        if safe_files:
            for f_info in safe_files:
                if isinstance(f_info, dict) and "download_url" in f_info:
                    f_url = f_info.get("download_url")
                    if f_url and "#" in f_url:
                        f_info["download_url"] = f_url.replace("#", "%23")

        task.status = "completed"
        task.progress = 100.0
        task.filename = filename
        task.download_url = safe_download_url
        task.file_size = file_size
        task.files = safe_files
        task.message = "Download ready"

        complete_payload: dict[str, Any] = {
            "status": task.status,
            "download_url": task.download_url,
            "filename": task.filename,
            "file_size": task.file_size,
        }
        if task.files is not None:
            complete_payload["files"] = task.files

        event = _format_event("complete", complete_payload)
        await _notify_subscribers(task_id, event)


async def set_error(task_id: str, error_message: str) -> None:
    """Mark task as failed and emit SSE error event."""
    async with _lock:
        task = _tasks.get(task_id)
        if not task:
            return

        task.status = "error"
        task.error = error_message
        task.message = error_message

        event = _format_event(
            "error",
            {
                "status": "error",
                "message": error_message,
            },
        )
        await _notify_subscribers(task_id, event)


def evict_task(task_id: str, message: str = "Task expired and cleaned up") -> bool:
    """Evict in-memory task record and close/notify its subscriber queues.

    Returns True if the task was present and evicted, False otherwise.
    """
    with _lock:
        existed = task_id in _tasks or task_id in _subscribers
        queues = _subscribers.pop(task_id, [])
        err_event = _format_event("error", {"status": "error", "message": message})
        for q in queues:
            try:
                q.put_nowait(err_event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(err_event)
                except Exception:
                    pass
            except Exception:
                pass
        _tasks.pop(task_id, None)
        return existed


async def cleanup_task(task_id: str, message: str = "Task expired and cleaned up") -> bool:
    """Remove task tracking and close active subscriber queues."""
    async with _lock:
        return evict_task(task_id, message=message)


async def subscribe_sse(task_id: str) -> AsyncGenerator[dict, None]:
    """Yield SSE events for task until terminal state (completed or error) or cancellation."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    registered = False
    terminal_event: dict | None = None
    initial_event: dict | None = None

    async with _lock:
        task = _tasks.get(task_id)
        if not task:
            terminal_event = _format_event(
                "error", {"status": "error", "message": f"Task {task_id} not found"}
            )
        elif task.status == "completed":
            complete_data: dict[str, Any] = {
                "status": task.status,
                "download_url": task.download_url,
                "filename": task.filename,
                "file_size": task.file_size,
            }
            if task.files is not None:
                complete_data["files"] = task.files
            terminal_event = _format_event("complete", complete_data)
        elif task.status == "error":
            terminal_event = _format_event(
                "error", {"status": "error", "message": task.error or "Task failed"}
            )
        else:
            if task_id not in _subscribers:
                _subscribers[task_id] = []
            _subscribers[task_id].append(queue)
            registered = True

            initial_event = _format_event(
                "progress",
                {
                    "status": task.status,
                    "progress": task.progress,
                    "speed": task.speed,
                    "eta": task.eta,
                    "message": task.message or "Task initialized",
                },
            )

    if terminal_event is not None:
        yield terminal_event
        return

    try:
        if initial_event is not None:
            yield initial_event

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
                yield event
                if event["event"] in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                async with _lock:
                    task = _tasks.get(task_id)
                    if not task:
                        yield _format_event(
                            "error", {"status": "error", "message": f"Task {task_id} not found"}
                        )
                        break
                    elif task.status == "completed":
                        complete_data: dict[str, Any] = {
                            "status": task.status,
                            "download_url": task.download_url,
                            "filename": task.filename,
                            "file_size": task.file_size,
                        }
                        if task.files is not None:
                            complete_data["files"] = task.files
                        yield _format_event("complete", complete_data)
                        break
                    elif task.status == "error":
                        yield _format_event(
                            "error", {"status": "error", "message": task.error or "Task failed"}
                        )
                        break
    finally:
        if registered:
            async with _lock:
                subs = _subscribers.get(task_id)
                if subs and queue in subs:
                    subs.remove(queue)
                if subs is not None and len(subs) == 0:
                    _subscribers.pop(task_id, None)
