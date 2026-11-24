"""Unit tests for progress tracking, ytdlp service parsing, and ffmpeg operations."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.services import ffmpeg_service, gallerydl_service, progress_manager, ytdlp_service
from app.services.gallerydl_service import parse_gallerydl_json
from app.services.ytdlp_service import (
    AuthRequiredError,
    ExtractionError,
    RateLimitError,
    classify_error,
)
from tests.conftest import MockSubprocess


@pytest.mark.asyncio
async def test_progress_manager_lifecycle():
    task = await progress_manager.create_task()
    tid = task.task_id
    assert task.status == "queued"
    assert tid in progress_manager.get_active_task_ids()

    # Update progress
    await progress_manager.update_progress(
        tid, progress=45.5, speed="2.1MiB/s", eta=5, message="Downloading 45.5%"
    )
    task_curr = progress_manager.get_task(tid)
    assert task_curr is not None
    assert task_curr.status == "downloading"
    assert task_curr.progress == 45.5
    assert task_curr.speed == "2.1MiB/s"
    assert task_curr.eta == 5

    # Set postprocessing
    await progress_manager.set_postprocessing(tid, "Converting audio...")
    assert progress_manager.get_task(tid).status == "postprocessing"

    # Set completed
    await progress_manager.set_completed(
        tid, filename="video.mp4", download_url=f"/api/files/{tid}/video.mp4", file_size=1024
    )
    completed_task = progress_manager.get_task(tid)
    assert completed_task.status == "completed"
    assert completed_task.progress == 100.0
    assert tid not in progress_manager.get_active_task_ids()

    # Cleanup
    await progress_manager.cleanup_task(tid)
    assert progress_manager.get_task(tid) is None


@pytest.mark.asyncio
async def test_progress_manager_sse_subscription():
    task = await progress_manager.create_task()
    tid = task.task_id

    async def run_events():
        await asyncio.sleep(0.01)
        await progress_manager.update_progress(tid, progress=50.0, speed="1MiB/s", eta=10)
        await asyncio.sleep(0.01)
        await progress_manager.set_completed(
            tid, filename="test.mp4", download_url=f"/api/files/{tid}/test.mp4", file_size=2048
        )

    event_task = asyncio.create_task(run_events())

    events = []
    async for evt in progress_manager.subscribe_sse(tid):
        events.append(evt)

    await event_task
    assert len(events) >= 3
    assert events[0]["event"] == "progress"
    assert events[-1]["event"] == "complete"
    last_data = json.loads(events[-1]["data"])
    assert last_data["status"] == "completed"
    assert last_data["filename"] == "test.mp4"


@pytest.mark.asyncio
async def test_subscribe_sse_early_client_abort_unregisters_queue():
    """Verify that early generator close/abort during or right after initial yield unregisters queue."""
    task = await progress_manager.create_task("task-early-abort")
    tid = task.task_id

    agen = progress_manager.subscribe_sse(tid)
    # Receive only initial progress snapshot
    initial_event = await anext(agen)
    assert initial_event["event"] == "progress"

    # Verify queue was registered
    assert tid in progress_manager._subscribers
    assert len(progress_manager._subscribers[tid]) == 1

    # Simulate client early disconnect / abort
    await agen.aclose()

    # Verify queue was cleanly unregistered and removed in try...finally
    subs = progress_manager._subscribers.get(tid)
    assert subs is None or len(subs) == 0


@pytest.mark.asyncio
async def test_progress_manager_evict_task_notifies_and_cleans():
    """Verify evict_task removes task and notifies any active subscriber queues."""
    task = await progress_manager.create_task("task-evict-test")
    tid = task.task_id

    agen = progress_manager.subscribe_sse(tid)
    initial_event = await anext(agen)
    assert initial_event["event"] == "progress"

    # Evict task
    assert progress_manager.evict_task(tid, message="Task expired and removed") is True
    assert progress_manager.get_task(tid) is None

    # Subscriber should receive eviction error notification
    evicted_event = await anext(agen)
    assert evicted_event["event"] == "error"
    payload = json.loads(evicted_event["data"])
    assert "expired" in payload["message"]

    await agen.aclose()
    subs = progress_manager._subscribers.get(tid)
    assert subs is None or len(subs) == 0



def test_classify_error():
    auth_err = classify_error("ERROR: Sign in to confirm you're not a bot.")
    assert isinstance(auth_err, AuthRequiredError)
    assert "bot verification" in str(auth_err).lower()

    age_err = classify_error("ERROR: Sign in to confirm your age. This video may be inappropriate.")
    assert isinstance(age_err, AuthRequiredError)
    assert "age-restricted" in str(age_err).lower()

    private_err = classify_error("ERROR: Private video. Sign in if you've been granted access to this video")
    assert isinstance(private_err, AuthRequiredError)
    assert "private" in str(private_err).lower()

    rate_err = classify_error("HTTP Error 429: Too Many Requests")
    assert isinstance(rate_err, RateLimitError)

    generic_err = classify_error("Video unavailable: generic failure")
    assert isinstance(generic_err, ExtractionError)
    assert not isinstance(generic_err, AuthRequiredError)


def test_get_js_runtime_args(monkeypatch):
    # Test Bun detected
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/bun" if cmd == "bun" else None)
    args_bun = ytdlp_service.get_js_runtime_args()
    assert "--js-runtimes" in args_bun
    assert "bun" in args_bun
    assert "--remote-components" in args_bun
    assert "ejs:github" in args_bun

    # Test Deno fallback
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/deno" if cmd == "deno" else None)
    args_deno = ytdlp_service.get_js_runtime_args()
    assert "--js-runtimes" in args_deno
    assert "deno" in args_deno

    # Test Node fallback
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/node" if cmd == "node" else None)
    args_node = ytdlp_service.get_js_runtime_args()
    assert "--js-runtimes" in args_node
    assert "node" in args_node

    # Test no runtime available
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    args_none = ytdlp_service.get_js_runtime_args()
    assert "--js-runtimes" not in args_none
    assert "--remote-components" in args_none


def test_get_extractor_args_for_url():
    yt_args = ytdlp_service.get_extractor_args_for_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert "--extractor-args" in yt_args
    assert "youtube:player_client=default" in yt_args[1]

    youtu_be_args = ytdlp_service.get_extractor_args_for_url("https://youtu.be/dQw4w9WgXcQ")
    assert "--extractor-args" in youtu_be_args

    non_yt_args = ytdlp_service.get_extractor_args_for_url("https://www.tiktok.com/@user/video/123")
    assert non_yt_args == []


def test_gallerydl_json_parser():
    raw = '{"id": "1", "url": "https://example.com/1.jpg"}\n{"id": "2", "url": "https://example.com/2.jpg"}'
    items = parse_gallerydl_json(raw)
    assert len(items) == 2
    assert items[0]["id"] == "1"

    # gallery-dl tuple format: [2, {...}]
    raw_tuples = '[2, {"id": "100", "extension": "png"}]\n[2, {"id": "101", "extension": "jpg"}]'
    items_t = parse_gallerydl_json(raw_tuples)
    assert len(items_t) == 2
    assert items_t[0]["id"] == "100"


def test_get_ffmpeg_bin_resolves_binary():
    bin_path = ffmpeg_service.get_ffmpeg_bin()
    assert bin_path is not None
    assert "ffmpeg" in bin_path
    assert Path(bin_path).exists()
    assert str(Path(bin_path).parent) in os.environ["PATH"]


@pytest.mark.asyncio
async def test_ffmpeg_extract_audio(tmp_path):
    input_file = tmp_path / "input.mp4"
    output_file = tmp_path / "output.mp3"
    input_file.touch()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = MockSubprocess(returncode=0)
        mock_exec.return_value = mock_proc

        res = await ffmpeg_service.extract_audio(input_file, output_file, audio_format="mp3")
        assert res == output_file
        assert mock_exec.called
        cmd_args = mock_exec.call_args[0]
        assert any("ffmpeg" in str(arg) for arg in cmd_args)
        assert "-vn" in cmd_args
        assert "libmp3lame" in cmd_args


@pytest.mark.asyncio
async def test_ffmpeg_remux_mp4(tmp_path):
    video_file = tmp_path / "video.mp4"
    audio_file = tmp_path / "audio.m4a"
    output_file = tmp_path / "output.mp4"

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = MockSubprocess(returncode=0)
        mock_exec.return_value = mock_proc

        res = await ffmpeg_service.remux_to_mp4(video_file, audio_file, output_file)
        assert res == output_file
        assert mock_exec.called
        cmd_args = mock_exec.call_args[0]
        assert any("ffmpeg" in str(arg) for arg in cmd_args)
        assert "-c:v" in cmd_args
        assert "copy" in cmd_args


@pytest.mark.asyncio
async def test_subscribe_sse_completion_race_does_not_hang():
    """Verify subscriber arriving concurrently with task completion never hangs on queue.get()."""
    task = await progress_manager.create_task("task-completion-race")
    tid = task.task_id
    await progress_manager.update_progress(tid, progress=50.0, speed="3MiB/s", eta=5)

    # Hold _lock to simulate delayed registration while set_completed finishes
    async with progress_manager._lock:
        gen = progress_manager.subscribe_sse(tid)
        sub_task = asyncio.create_task(gen.__anext__())
        # Yield control briefly so sub_task reaches async with _lock:
        await asyncio.sleep(0.01)
        # Concurrent completion occurs before subscriber queue was registered
        await progress_manager.set_completed(
            tid, filename="video.mp4", download_url=f"/api/files/{tid}/video.mp4", file_size=1024
        )

    # Subscriber must yield the terminal complete event within timeout without hanging
    terminal_event = await asyncio.wait_for(sub_task, timeout=1.0)
    assert terminal_event["event"] == "complete"
    payload = json.loads(terminal_event["data"])
    assert payload["status"] == "completed"
    assert payload["filename"] == "video.mp4"

    # Subsequent __anext__ should terminate iteration cleanly
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=1.0)


@pytest.mark.asyncio
async def test_subscribe_sse_eviction_race_does_not_hang():
    """Verify subscriber arriving concurrently with task eviction never hangs on queue.get()."""
    task = await progress_manager.create_task("task-eviction-race")
    tid = task.task_id
    await progress_manager.update_progress(tid, progress=25.0)

    # Hold _lock to simulate delayed registration while evict_task runs
    async with progress_manager._lock:
        gen = progress_manager.subscribe_sse(tid)
        sub_task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.01)
        # Evict task while subscriber is pending lock acquisition
        evicted = progress_manager.evict_task(tid, message="Task cleaned up by TTL")
        assert evicted is True

    # Subscriber must yield error event immediately rather than hanging on queue.get()
    terminal_event = await asyncio.wait_for(sub_task, timeout=1.0)
    assert terminal_event["event"] == "error"
    payload = json.loads(terminal_event["data"])
    assert payload["status"] == "error"

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=1.0)


@pytest.mark.asyncio
async def test_subscribe_sse_concurrent_lifecycle_stress():
    """Stress test concurrent subscribers, updates, evictions, and completions."""
    tasks = [await progress_manager.create_task(f"stress-{i}") for i in range(30)]

    async def run_subscriber(tid: str) -> list[dict]:
        events = []
        try:
            async for evt in progress_manager.subscribe_sse(tid):
                events.append(evt)
        except asyncio.CancelledError:
            pass
        return events

    async def run_mutator(tid: str, idx: int):
        await asyncio.sleep(0.005 * (idx % 3))
        if idx % 3 == 0:
            await progress_manager.update_progress(tid, 30.0)
            await asyncio.sleep(0.005)
            await progress_manager.set_completed(tid, f"f_{idx}.mp4", f"/files/{tid}/f_{idx}.mp4", 1000)
        elif idx % 3 == 1:
            await progress_manager.update_progress(tid, 50.0)
            await asyncio.sleep(0.005)
            progress_manager.evict_task(tid, message="Cleaned")
        else:
            await progress_manager.update_progress(tid, 20.0)
            await asyncio.sleep(0.005)
            await progress_manager.set_error(tid, "Simulated failure")

    sub_coros = [asyncio.create_task(run_subscriber(t.task_id)) for t in tasks]
    mut_coros = [asyncio.create_task(run_mutator(t.task_id, i)) for i, t in enumerate(tasks)]

    await asyncio.wait_for(asyncio.gather(*mut_coros), timeout=5.0)
    results = await asyncio.wait_for(asyncio.gather(*sub_coros), timeout=5.0)

    # Every subscriber must have received at least 1 event and terminated cleanly
    assert len(results) == 30
    for events in results:
        assert len(events) >= 1
        last_event = events[-1]
        assert last_event["event"] in ("complete", "error")


@pytest.mark.asyncio
async def test_subscribe_sse_queue_overflow_receives_complete_without_hang():
    """Verify that emitting 65+ progress events before subscriber consumption
    does not drop the complete event or hang the subscriber (queue maxsize is 50)."""
    task = await progress_manager.create_task("overflow-complete-task")
    tid = task.task_id

    gen = progress_manager.subscribe_sse(tid)
    # Receive initial progress snapshot
    init_evt = await gen.__anext__()
    assert init_evt["event"] == "progress"

    # Emit 70 (>65) progress events in rapid succession without consuming, filling queue
    for p in range(1, 71):
        await progress_manager.update_progress(tid, progress=float(p), speed="4.5MiB/s", eta=10)

    # Mark completed
    await progress_manager.set_completed(
        tid, filename="overflow_video.mp4", download_url=f"/api/files/{tid}/overflow_video.mp4", file_size=4096
    )

    # Subscriber consumes all events; must receive complete event and terminate cleanly
    events = []
    try:
        while True:
            evt = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            events.append(evt)
            if evt["event"] in ("complete", "error"):
                break
    except asyncio.TimeoutError:
        pytest.fail("Subscriber hung waiting for complete event after queue overflow")

    assert len(events) > 0
    assert events[-1]["event"] == "complete"
    last_data = json.loads(events[-1]["data"])
    assert last_data["status"] == "completed"
    assert last_data["filename"] == "overflow_video.mp4"

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=1.0)


@pytest.mark.asyncio
async def test_subscribe_sse_queue_overflow_receives_eviction_without_hang():
    """Verify that emitting 65+ progress events followed by eviction does not drop eviction error."""
    task = await progress_manager.create_task("overflow-evict-task")
    tid = task.task_id

    gen = progress_manager.subscribe_sse(tid)
    init_evt = await gen.__anext__()
    assert init_evt["event"] == "progress"

    for p in range(1, 71):
        await progress_manager.update_progress(tid, progress=float(p))

    progress_manager.evict_task(tid, message="Task cleaned up by TTL")

    events = []
    try:
        while True:
            evt = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            events.append(evt)
            if evt["event"] in ("complete", "error"):
                break
    except asyncio.TimeoutError:
        pytest.fail("Subscriber hung waiting for eviction error event after queue overflow")

    assert len(events) > 0
    assert events[-1]["event"] == "error"
    last_data = json.loads(events[-1]["data"])
    assert "cleaned up" in last_data["message"].lower()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=1.0)


@pytest.mark.asyncio
async def test_download_services_exclude_cookie_and_temporary_files(temp_environment):
    """Verify ytdlp_service and gallerydl_service exclude client_cookies_* and .part files."""
    downloads_dir = temp_environment["downloads_dir"]
    out_dir = downloads_dir / "test-clean-collection"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Place media and non-media files in directory
    (out_dir / "valid_video.mp4").write_bytes(b"video bytes")
    (out_dir / "client_cookies_youtube_abc.txt").write_text("# Netscape cookies")
    (out_dir / ".hidden_file").write_text("secret")
    (out_dir / "incomplete.part").write_text("partial")

    mock_proc = MockSubprocess(returncode=0, stdout_bytes=b"[download] 100%\n")
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc

        ytdlp_files = await ytdlp_service.download_media(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir=out_dir,
        )
        assert len(ytdlp_files) == 1
        assert ytdlp_files[0].name == "valid_video.mp4"

        gdl_files = await gallerydl_service.download_items(
            url="https://www.instagram.com/p/123/",
            output_dir=out_dir,
        )
        assert len(gdl_files) == 1
        assert gdl_files[0].name == "valid_video.mp4"


@pytest.mark.asyncio
async def test_ytdlp_download_media_format_commands(temp_environment):
    """Verify ytdlp_service.download_media builds robust format selector and merge arguments."""
    downloads_dir = temp_environment["downloads_dir"]
    out_dir = downloads_dir / "test-format-cmd"
    out_dir.mkdir(parents=True, exist_ok=True)
    fake_file = out_dir / "video.mp4"
    fake_file.write_bytes(b"content")

    test_cases = [
        ("best", ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]),
        ("1080p", ["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best", "--merge-output-format", "mp4"]),
        ("720p", ["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best", "--merge-output-format", "mp4"]),
        ("4k", ["-f", "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best", "--merge-output-format", "mp4"]),
        ("137", ["-f", "137[acodec!=none]/137+bestaudio/137/best", "--merge-output-format", "mp4"]),
        ("bestvideo+bestaudio/best", ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]),
    ]

    for format_id, expected_flags in test_cases:
        mock_proc = MockSubprocess(returncode=0, stdout_bytes=b"[download] 100%\n")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc
            await ytdlp_service.download_media(
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir=out_dir,
                format_id=format_id,
            )
            args = mock_exec.call_args[0]
            for flag in expected_flags:
                assert flag in args, f"Expected flag '{flag}' for format '{format_id}', got: {args}"

    # Audio extraction mode
    mock_proc = MockSubprocess(returncode=0, stdout_bytes=b"[download] 100%\n")
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        await ytdlp_service.download_media(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir=out_dir,
            extract_audio=True,
            audio_format="mp3",
        )
        args = mock_exec.call_args[0]
        assert "-x" in args
        assert "--audio-format" in args
        assert "mp3" in args
        assert "--merge-output-format" not in args


@pytest.mark.asyncio
async def test_progress_manager_completion_with_files_list():
    """Verify set_completed passes files list and subscribe_sse emits files in completion event."""
    task = await progress_manager.create_task()
    task_id = task.task_id

    files_list = [
        {"filename": "photo_1.jpg", "file_path": "/path/photo_1.jpg", "file_size": 1024, "download_url": f"/api/files/{task_id}/photo_1.jpg"},
        {"filename": "photo_2.jpg", "file_path": "/path/photo_2.jpg", "file_size": 2048, "download_url": f"/api/files/{task_id}/photo_2.jpg"},
    ]

    await progress_manager.set_completed(
        task_id=task_id,
        filename="photo_1.jpg",
        download_url=f"/api/files/{task_id}/photo_1.jpg",
        file_size=3072,
        files=files_list,
    )

    completed_task = progress_manager.get_task(task_id)
    assert completed_task is not None
    assert completed_task.status == "completed"
    assert completed_task.files == files_list

    # Test subscribe_sse cached terminal event contains files
    events = []
    async for event in progress_manager.subscribe_sse(task_id):
        events.append(event)

    assert len(events) == 1
    complete_ev = events[0]
    assert complete_ev["event"] == "complete"
    payload = json.loads(complete_ev["data"])
    assert payload["status"] == "completed"
    assert "files" in payload
    assert len(payload["files"]) == 2
    assert payload["files"][0]["filename"] == "photo_1.jpg"
    assert payload["files"][1]["filename"] == "photo_2.jpg"


@pytest.mark.asyncio
async def test_ffmpeg_run_command_kills_process_on_cancellation():
    """Verify ffmpeg_service.run_ffmpeg_command terminates running subprocess if task is cancelled."""
    mock_proc = MockSubprocess(returncode=None)

    async def slow_communicate():
        await asyncio.sleep(10)
        return b"", b""

    mock_proc.communicate = slow_communicate

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        task = asyncio.create_task(ffmpeg_service.run_ffmpeg_command(["ffmpeg", "-i", "in.mp4"]))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert mock_proc.killed is True
        assert mock_proc.returncode == -9


@pytest.mark.asyncio
async def test_ytdlp_extract_metadata_kills_process_on_cancellation():
    """Verify ytdlp_service.inspect_url terminates running subprocess if task is cancelled."""
    mock_proc = MockSubprocess(returncode=None)

    async def slow_communicate():
        await asyncio.sleep(10)
        return b"", b""

    mock_proc.communicate = slow_communicate

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        task = asyncio.create_task(ytdlp_service.inspect_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert mock_proc.killed is True
        assert mock_proc.returncode == -9


@pytest.mark.asyncio
async def test_ytdlp_download_media_kills_process_on_cancellation(tmp_path):
    """Verify ytdlp_service.download_media terminates running subprocess if task is cancelled."""
    mock_proc = MockSubprocess(returncode=None)

    async def slow_readline():
        await asyncio.sleep(10)
        return b""

    mock_proc.stdout.readline = slow_readline

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        task = asyncio.create_task(
            ytdlp_service.download_media("https://www.youtube.com/watch?v=dQw4w9WgXcQ", tmp_path)
        )
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert mock_proc.killed is True
        assert mock_proc.returncode == -9


@pytest.mark.asyncio
async def test_gallerydl_extract_items_kills_process_on_cancellation():
    """Verify gallerydl_service.inspect_url terminates running subprocess if task is cancelled."""
    mock_proc = MockSubprocess(returncode=None)

    async def slow_communicate():
        await asyncio.sleep(10)
        return b"", b""

    mock_proc.communicate = slow_communicate

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        task = asyncio.create_task(gallerydl_service.inspect_url("https://www.instagram.com/p/123/"))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert mock_proc.killed is True
        assert mock_proc.returncode == -9


@pytest.mark.asyncio
async def test_gallerydl_download_items_kills_process_on_cancellation(tmp_path):
    """Verify gallerydl_service.download_items terminates running subprocess if task is cancelled."""
    mock_proc = MockSubprocess(returncode=None)

    async def slow_readline():
        await asyncio.sleep(10)
        return b""

    mock_proc.stdout.readline = slow_readline

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        task = asyncio.create_task(
            gallerydl_service.download_items("https://www.instagram.com/p/123/", tmp_path)
        )
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert mock_proc.killed is True
        assert mock_proc.returncode == -9


@pytest.mark.asyncio
async def test_subprocess_cleanup_swallows_process_lookup_error():
    """Verify process termination ignores ProcessLookupError if process already died."""
    mock_proc = MockSubprocess(returncode=None)

    async def slow_communicate():
        await asyncio.sleep(10)
        return b"", b""

    def raise_lookup():
        mock_proc.killed = True
        raise ProcessLookupError("No such process")

    mock_proc.communicate = slow_communicate
    mock_proc.kill = raise_lookup

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        task = asyncio.create_task(ffmpeg_service.run_ffmpeg_command(["ffmpeg", "-i", "in.mp4"]))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert mock_proc.killed is True


@pytest.mark.asyncio
async def test_mock_subprocess_terminate_sets_returncode_and_unblocks_wait():
    """Verify MockSubprocess.terminate sets terminated flag and unblocks wait immediately."""
    proc = MockSubprocess(returncode=None)

    async def wait_wrapper():
        return await proc.wait()

    task = asyncio.create_task(wait_wrapper())
    await asyncio.sleep(0.01)
    assert not task.done()

    proc.terminate()
    res = await asyncio.wait_for(task, timeout=1.0)
    assert res == -15
    assert proc.terminated is True
    assert proc.returncode == -15


@pytest.mark.asyncio
async def test_ffmpeg_run_command_kills_process_on_unhandled_exception():
    """Verify ffmpeg_service.run_ffmpeg_command terminates running subprocess on generic exception."""
    mock_proc = MockSubprocess(returncode=None)

    async def failing_communicate():
        raise RuntimeError("Unexpected pipeline crash")

    mock_proc.communicate = failing_communicate

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        with pytest.raises(RuntimeError, match="Unexpected pipeline crash"):
            await ffmpeg_service.run_ffmpeg_command(["ffmpeg", "-i", "in.mp4"])

        assert mock_proc.killed is True
        assert mock_proc.returncode == -9


@pytest.mark.asyncio
async def test_ytdlp_download_media_kills_process_on_unhandled_exception(tmp_path):
    """Verify ytdlp_service.download_media terminates running subprocess on unhandled stream error."""
    mock_proc = MockSubprocess(returncode=None)

    async def failing_readline():
        raise RuntimeError("Stream read failure")

    mock_proc.stdout.readline = failing_readline

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        with pytest.raises(RuntimeError, match="Stream read failure"):
            await ytdlp_service.download_media(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ", tmp_path
            )

        assert mock_proc.killed is True
        assert mock_proc.returncode == -9
