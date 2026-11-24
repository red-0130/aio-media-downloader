"""Unit tests for background TTL download directory cleaner."""

import asyncio
import os
import time
import pytest
from app.services.cleaner import cleanup_old_downloads, run_periodic_cleaner
from app.services import progress_manager


def test_cleanup_deletes_expired_directories(tmp_path):
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    # Create old directory (older than 60 mins)
    old_task = downloads_dir / "task-old"
    old_task.mkdir()
    (old_task / "sample.mp4").write_bytes(b"data")

    # Set mtime to 120 minutes ago
    old_time = time.time() - (120 * 60)
    os.utime(old_task, (old_time, old_time))

    # Create new directory (10 mins old)
    new_task = downloads_dir / "task-new"
    new_task.mkdir()
    (new_task / "sample2.mp4").write_bytes(b"data")
    new_time = time.time() - (10 * 60)
    os.utime(new_task, (new_time, new_time))

    deleted = cleanup_old_downloads(downloads_dir, ttl_minutes=60)

    assert deleted == 1
    assert not old_task.exists()
    assert new_task.exists()


def test_cleanup_skips_active_tasks(tmp_path):
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    # Create old directory, but mark as active
    active_task = downloads_dir / "task-active"
    active_task.mkdir()
    (active_task / "in_progress.part").write_bytes(b"downloading...")
    old_time = time.time() - (120 * 60)
    os.utime(active_task, (old_time, old_time))

    # Another old directory that is NOT active
    inactive_task = downloads_dir / "task-inactive"
    inactive_task.mkdir()
    (inactive_task / "done.mp4").write_bytes(b"data")
    os.utime(inactive_task, (old_time, old_time))

    deleted = cleanup_old_downloads(
        downloads_dir,
        ttl_minutes=60,
        active_task_ids={"task-active"},
    )

    assert deleted == 1
    assert active_task.exists()  # Kept because active!
    assert not inactive_task.exists()  # Deleted


@pytest.mark.asyncio
async def test_cleanup_evicts_in_memory_task_from_progress_manager(tmp_path):
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    # Create task in progress_manager
    task_old = await progress_manager.create_task("task-mem-old")
    task_recent = await progress_manager.create_task("task-mem-recent")

    # Create directories
    dir_old = downloads_dir / "task-mem-old"
    dir_old.mkdir()
    (dir_old / "file.mp4").write_bytes(b"data")
    old_time = time.time() - (120 * 60)
    os.utime(dir_old, (old_time, old_time))

    dir_recent = downloads_dir / "task-mem-recent"
    dir_recent.mkdir()
    (dir_recent / "file2.mp4").write_bytes(b"data")
    recent_time = time.time() - (5 * 60)
    os.utime(dir_recent, (recent_time, recent_time))

    # Verify both exist in progress_manager before cleanup
    assert progress_manager.get_task("task-mem-old") is not None
    assert progress_manager.get_task("task-mem-recent") is not None

    deleted = cleanup_old_downloads(downloads_dir, ttl_minutes=60)
    assert deleted == 1

    # Verified: task-mem-old evicted from progress_manager!
    assert progress_manager.get_task("task-mem-old") is None
    # Verified: task-mem-recent remains in progress_manager!
    assert progress_manager.get_task("task-mem-recent") is not None


@pytest.mark.asyncio
async def test_cleanup_evicts_failed_task_without_directory(tmp_path):
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    # Create failed task older than TTL without disk directory
    old_time = time.time() - (120 * 60)
    task = await progress_manager.create_task("task-failed-no-dir", created_at=old_time)
    await progress_manager.set_error("task-failed-no-dir", "Immediate 401 Unauthorized")

    assert (downloads_dir / "task-failed-no-dir").exists() is False
    assert progress_manager.get_task("task-failed-no-dir") is not None

    deleted = cleanup_old_downloads(downloads_dir, ttl_minutes=60)
    assert deleted == 0
    assert progress_manager.get_task("task-failed-no-dir") is None


@pytest.mark.asyncio
async def test_cleanup_retains_recent_failed_task_without_directory(tmp_path):
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    # Create failed task within TTL (10 mins old) without disk directory
    recent_time = time.time() - (10 * 60)
    task = await progress_manager.create_task("task-recent-failed", created_at=recent_time)
    await progress_manager.set_error("task-recent-failed", "404 Not Found")

    deleted = cleanup_old_downloads(downloads_dir, ttl_minutes=60)
    assert deleted == 0
    assert progress_manager.get_task("task-recent-failed") is not None


@pytest.mark.asyncio
async def test_cleanup_retains_active_task_without_directory(tmp_path):
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    # Create active task older than TTL without disk directory
    old_time = time.time() - (120 * 60)
    task = await progress_manager.create_task("task-active-no-dir", created_at=old_time)
    await progress_manager.update_progress("task-active-no-dir", progress=50.0)

    deleted = cleanup_old_downloads(downloads_dir, ttl_minutes=60)
    assert deleted == 0
    assert progress_manager.get_task("task-active-no-dir") is not None


@pytest.mark.asyncio
async def test_run_periodic_cleaner_runs_immediately_on_startup(monkeypatch):
    """Verify run_periodic_cleaner executes cleanup immediately on startup without waiting for interval."""
    cleanup_called = asyncio.Event()
    received_kwargs = {}

    def mock_cleanup(*args, **kwargs):
        received_kwargs.update(kwargs)
        cleanup_called.set()
        return 2

    monkeypatch.setattr("app.services.cleaner.cleanup_old_downloads", mock_cleanup)

    # Use a large interval (10 minutes) - if it waits, cleanup_called will not be set
    cleaner_task = asyncio.create_task(run_periodic_cleaner(interval_seconds=600))

    try:
        await asyncio.wait_for(cleanup_called.wait(), timeout=1.0)
        assert cleanup_called.is_set()
        assert "downloads_dir" in received_kwargs
        assert "ttl_minutes" in received_kwargs
        assert "active_task_ids" in received_kwargs
    finally:
        cleaner_task.cancel()
        try:
            await cleaner_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_run_periodic_cleaner_purges_real_expired_directory_on_startup(tmp_path):
    """Verify run_periodic_cleaner actually purges expired directories on disk immediately on startup."""
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    old_task = downloads_dir / "task-startup-old"
    old_task.mkdir()
    (old_task / "sample.mp4").write_bytes(b"data")
    old_time = time.time() - (120 * 60)
    os.utime(old_task, (old_time, old_time))

    fresh_task = downloads_dir / "task-startup-fresh"
    fresh_task.mkdir()
    (fresh_task / "sample2.mp4").write_bytes(b"data")
    fresh_time = time.time() - (10 * 60)
    os.utime(fresh_task, (fresh_time, fresh_time))

    cleaner_task = asyncio.create_task(
        run_periodic_cleaner(
            interval_seconds=600,
            downloads_dir=downloads_dir,
            ttl_minutes=60,
        )
    )

    try:
        for _ in range(50):
            if not old_task.exists():
                break
            await asyncio.sleep(0.01)

        assert not old_task.exists(), "Expired directory should be deleted immediately on startup"
        assert fresh_task.exists(), "Fresh directory should be preserved"
    finally:
        cleaner_task.cancel()
        try:
            await cleaner_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_run_periodic_cleaner_handles_exception_and_continues(monkeypatch):
    """Verify run_periodic_cleaner catches exceptions and continues to subsequent periodic intervals."""
    call_count = 0
    second_call_event = asyncio.Event()

    def mock_cleanup_fail(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated transient disk error")
        second_call_event.set()
        return 0

    monkeypatch.setattr("app.services.cleaner.cleanup_old_downloads", mock_cleanup_fail)

    cleaner_task = asyncio.create_task(run_periodic_cleaner(interval_seconds=0.02))

    try:
        await asyncio.wait_for(second_call_event.wait(), timeout=1.0)
        assert call_count >= 2
        assert not cleaner_task.done()
    finally:
        cleaner_task.cancel()
        try:
            await cleaner_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_run_periodic_cleaner_cancellation_marks_task_cancelled():
    """Verify task is properly marked as cancelled and raises CancelledError on await."""
    cleaner_task = asyncio.create_task(run_periodic_cleaner(interval_seconds=600))
    await asyncio.sleep(0.01)
    cleaner_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await cleaner_task

    assert cleaner_task.cancelled() is True


