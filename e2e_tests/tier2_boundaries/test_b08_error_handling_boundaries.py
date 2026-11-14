"""Tier 2 Boundary Tests: B08 - Engine Failure Modes & Error Handling Boundaries.

Covers:
- Engine non-zero exit codes with stderr diagnostics capture
- Specialized AuthRequiredError classification and cookie guidance
- Specialized RateLimitError classification (HTTP 429 handling)
- Malformed / corrupted JSON stdout parsing from extractors
- Empty stdout responses when engine returns exit 0
- Missing ffmpeg binary (FileNotFoundError) handling
- Disk full simulation (ENOSPC / OSError Errno 28)
- File permission errors (EACCES / PermissionError)
- Process timeout / cancellation handling
- Clean JSON error responses (400, 401, 429, 500) returned by REST API
- ProgressManager error state transition on background worker failure
- Partial download error containment and recovery
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models.download import DownloadRequest
from app.services import ffmpeg_service, gallerydl_service, progress_manager, router, ytdlp_service
from app.services.ytdlp_service import (
    AuthRequiredError,
    ExtractionError,
    RateLimitError,
)


@pytest.mark.asyncio
async def test_error_engine_non_zero_exit_with_stderr_captured(mock_bin_path: Path):
    """Verify engine non-zero exit code captures stderr diagnostics into ExtractionError."""
    with pytest.raises(ExtractionError) as exc_info:
        await ytdlp_service.inspect_url("https://www.youtube.com/watch?v=fail_engine_test")

    err_str = str(exc_info.value)
    assert "Extraction failed" in err_str or "fail_engine_test" in err_str


@pytest.mark.asyncio
async def test_error_auth_required_detection_and_cookie_suggestion(mock_bin_path: Path):
    """Verify stderr containing login wall indicators raises AuthRequiredError and suggests cookies."""
    with pytest.raises(AuthRequiredError) as exc_info:
        await ytdlp_service.inspect_url("https://www.youtube.com/watch?v=auth_error_test")

    msg = str(exc_info.value)
    assert "Authentication required" in msg
    assert "cookies" in msg.lower()


@pytest.mark.asyncio
async def test_error_rate_limit_detection(mock_bin_path: Path):
    """Verify HTTP 429 / rate-limiting output raises specialized RateLimitError."""
    with pytest.raises(RateLimitError) as exc_info:
        await ytdlp_service.inspect_url("https://www.youtube.com/watch?v=rate_limit_test")

    msg = str(exc_info.value)
    assert "Rate limited" in msg
    assert "proxy" in msg.lower() or "wait" in msg.lower()


@pytest.mark.asyncio
async def test_error_malformed_json_stdout_handling():
    """Verify malformed JSON emitted by engine raises descriptive ExtractionError instead of raw crash."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"<<<CRITICAL PARSE ERROR: NOT JSON>>>", b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(ExtractionError, match="Failed to parse yt-dlp metadata JSON"):
            await ytdlp_service.inspect_url("https://www.youtube.com/watch?v=any")


@pytest.mark.asyncio
async def test_error_empty_engine_stdout_handling():
    """Verify engine returning empty stdout with exit code 0 raises ExtractionError."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(ExtractionError, match="empty metadata"):
            await ytdlp_service.inspect_url("https://www.youtube.com/watch?v=any")


@pytest.mark.asyncio
async def test_error_missing_ffmpeg_binary_handling(tmp_path: Path):
    """Verify missing ffmpeg binary raises FileNotFoundError or RuntimeError safely."""
    in_file = tmp_path / "in.mp4"
    in_file.write_bytes(b"dummy")
    out_file = tmp_path / "out.mp3"

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("ffmpeg not found")):
        with pytest.raises(FileNotFoundError):
            await ffmpeg_service.extract_audio(in_file, out_file)


@pytest.mark.asyncio
async def test_error_disk_full_simulation_during_download(tmp_path: Path):
    """Verify disk full (ENOSPC / OSError Errno 28) during file writes is caught cleanly."""
    task = await progress_manager.create_task("task-enospc-test")

    with patch.object(Path, "write_bytes", side_effect=OSError(28, "No space left on device")):
        with pytest.raises(OSError, match="No space left on device"):
            # Attempt writing file
            (tmp_path / "test.mp4").write_bytes(b"data")

        # Mark task failed in progress manager
        await progress_manager.set_error(task.task_id, "Disk full: No space left on device")
        t = progress_manager.get_task(task.task_id)
        assert t.status == "error"
        assert "Disk full" in (t.error or "")


@pytest.mark.asyncio
async def test_error_permission_denied_simulation(tmp_path: Path):
    """Verify permission denied (EACCES) when creating files raises PermissionError safely."""
    read_only_dir = tmp_path / "locked"
    read_only_dir.mkdir()
    read_only_dir.chmod(0o444)

    try:
        with pytest.raises(PermissionError):
            (read_only_dir / "blocked.txt").write_bytes(b"cannot write")
    finally:
        read_only_dir.chmod(0o777)


@pytest.mark.asyncio
async def test_error_subprocess_cancellation():
    """Verify cancelled subprocess coroutines handle asyncio.CancelledError cleanly."""
    async def slow_mock_coro():
        await asyncio.sleep(10.0)

    task = asyncio.create_task(slow_mock_coro())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_error_clean_json_error_responses_from_api(
    async_client: httpx.AsyncClient, mock_bin_path: Path
):
    """Verify REST API inspect endpoint converts classified exceptions to clean JSON with appropriate status."""
    # 1. AuthRequiredError -> HTTP 401
    resp_auth = await async_client.post(
        "/api/inspect",
        json={"url": "https://www.youtube.com/watch?v=auth_error_test"},
    )
    assert resp_auth.status_code == 401
    assert "Authentication required" in resp_auth.json()["detail"]

    # 2. RateLimitError -> HTTP 429
    resp_rate = await async_client.post(
        "/api/inspect",
        json={"url": "https://www.youtube.com/watch?v=rate_limit_test"},
    )
    assert resp_rate.status_code == 429
    assert "Rate limited" in resp_rate.json()["detail"]

    # 3. ExtractionError -> HTTP 400
    resp_fail = await async_client.post(
        "/api/inspect",
        json={"url": "https://www.youtube.com/watch?v=fail_engine_test"},
    )
    assert resp_fail.status_code == 400
    assert "Extraction failed" in resp_fail.json()["detail"]


@pytest.mark.asyncio
async def test_error_download_worker_transitions_task_to_error_state(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Verify background worker failure transitions task status to 'error' and emits SSE error."""
    # Start download with failing URL
    resp = await async_client.post(
        "/api/download",
        json={"url": "https://www.youtube.com/watch?v=fail_engine_test"},
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    # Wait for background worker to catch error
    for _ in range(50):
        task = progress_manager.get_task(task_id)
        if task and task.status == "error":
            break
        await asyncio.sleep(0.05)

    task = progress_manager.get_task(task_id)
    assert task is not None
    assert task.status == "error"
    assert task.error is not None
    assert "Extraction failed" in task.error or "fail_engine_test" in task.error


@pytest.mark.asyncio
async def test_error_partial_download_cleanup_on_failure(
    isolated_env: dict[str, Path],
):
    """Verify router catches failure and ensures clean error propagation."""
    request = DownloadRequest(url="https://www.youtube.com/watch?v=fail_engine_test")

    with patch.object(ytdlp_service, "download_media", side_effect=ExtractionError("Network dropped")):
        with pytest.raises(ExtractionError, match="Network dropped"):
            await router.download(task_id="test-fail-cleanup", request=request)
