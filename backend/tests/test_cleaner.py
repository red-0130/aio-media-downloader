"""Unit tests for background TTL download directory cleaner."""

import os
import time
import pytest
from app.services.cleaner import cleanup_old_downloads
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

