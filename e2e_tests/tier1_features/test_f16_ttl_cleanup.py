"""Tier 1 Feature Coverage: F16 - Storage TTL Cleanup."""

import os
import time
from pathlib import Path

import pytest

from app.services import cleaner


def test_retain_fresh_task_directories(isolated_env: dict[str, Path]):
    """Verify task directories newer than TTL are retained."""
    downloads_dir = isolated_env["downloads_dir"]
    fresh_task = downloads_dir / "task_fresh_1"
    fresh_task.mkdir()
    (fresh_task / "media.mp4").write_bytes(b"sample data")

    # Ensure mtime is current
    now = time.time()
    os.utime(fresh_task, (now, now))

    deleted = cleaner.cleanup_old_downloads(downloads_dir, ttl_minutes=60)
    assert deleted == 0
    assert fresh_task.exists()


def test_delete_expired_task_directories(isolated_env: dict[str, Path]):
    """Verify task directories older than TTL are removed."""
    downloads_dir = isolated_env["downloads_dir"]
    old_task = downloads_dir / "task_old_1"
    old_task.mkdir()
    (old_task / "old_video.mp4").write_bytes(b"old data")

    # Set mtime to 120 minutes ago
    past_time = time.time() - (120 * 60)
    os.utime(old_task, (past_time, past_time))

    deleted = cleaner.cleanup_old_downloads(downloads_dir, ttl_minutes=60)
    assert deleted == 1
    assert not old_task.exists()


def test_clean_corrupt_or_empty_expired_tasks(isolated_env: dict[str, Path]):
    """Verify empty or corrupt expired task directories are safely cleaned."""
    downloads_dir = isolated_env["downloads_dir"]
    empty_task = downloads_dir / "task_empty_corrupt"
    empty_task.mkdir()

    past_time = time.time() - (90 * 60)
    os.utime(empty_task, (past_time, past_time))

    deleted = cleaner.cleanup_old_downloads(downloads_dir, ttl_minutes=60)
    assert deleted == 1
    assert not empty_task.exists()


def test_configurable_ttl_setting(isolated_env: dict[str, Path]):
    """Verify cleanup honors configurable TTL parameter."""
    downloads_dir = isolated_env["downloads_dir"]

    # Task aged 15 minutes
    task_15m = downloads_dir / "task_15m"
    task_15m.mkdir()
    t15 = time.time() - (15 * 60)
    os.utime(task_15m, (t15, t15))

    # Task aged 5 minutes
    task_5m = downloads_dir / "task_5m"
    task_5m.mkdir()
    t5 = time.time() - (5 * 60)
    os.utime(task_5m, (t5, t5))

    # With TTL = 10 minutes, task_15m should be deleted, task_5m kept
    deleted = cleaner.cleanup_old_downloads(downloads_dir, ttl_minutes=10)
    assert deleted == 1
    assert not task_15m.exists()
    assert task_5m.exists()


def test_active_tasks_are_never_deleted(isolated_env: dict[str, Path]):
    """Verify actively running tasks are shielded from TTL deletion."""
    downloads_dir = isolated_env["downloads_dir"]
    active_task = downloads_dir / "task_currently_active"
    active_task.mkdir()

    # Set mtime to 180 minutes ago
    past_time = time.time() - (180 * 60)
    os.utime(active_task, (past_time, past_time))

    # Pass active_task_ids set containing the task
    deleted = cleaner.cleanup_old_downloads(
        downloads_dir,
        ttl_minutes=60,
        active_task_ids={"task_currently_active"},
    )
    assert deleted == 0
    assert active_task.exists(), "Active task must be preserved despite being older than TTL"


def test_cleanup_ignores_hidden_and_dot_files(isolated_env: dict[str, Path]):
    """Verify cleaner ignores hidden files like .gitkeep or .temp."""
    downloads_dir = isolated_env["downloads_dir"]
    gitkeep = downloads_dir / ".gitkeep"
    gitkeep.write_text("keep")

    past_time = time.time() - (200 * 60)
    os.utime(gitkeep, (past_time, past_time))

    deleted = cleaner.cleanup_old_downloads(downloads_dir, ttl_minutes=60)
    assert deleted == 0
    assert gitkeep.exists()
