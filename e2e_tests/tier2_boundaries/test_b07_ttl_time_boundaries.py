"""Tier 2 Boundary Tests: B07 - Background Storage TTL & Time Boundaries.

Covers:
- Task retention at 59 minutes (boundary just below 60m TTL)
- Task deletion at exact 60 minutes boundary (age_seconds == 3600s)
- Task deletion at 61 minutes (boundary above 60m TTL)
- Zero TTL handling (ttl_minutes=0 immediately purging completed tasks)
- Negative TTL handling (system robustness with negative time parameters)
- Active tasks exemption: active tasks older than TTL are strictly preserved
- Stray non-directory files in downloads root are ignored and preserved
- Hidden dot-directories (.gitkeep, .cache) are ignored
- Recursive purging of deeply nested subdirectories inside expired task folders
- Future timestamp clock skew (mtime in future is preserved)
- Ancient timestamps (epoch 0 / 1990s) cleanly purged
- Graceful handling of missing or deleted downloads directories
"""

import os
import time
from pathlib import Path
import pytest

from app.services import cleaner


def test_ttl_task_retained_at_59_minutes(tmp_path: Path):
    """Verify task directory aged 59 minutes (3540s) is retained under 60m TTL."""
    task_dir = tmp_path / "task-59m"
    task_dir.mkdir()
    target_time = time.time() - (59 * 60)
    os.utime(task_dir, (target_time, target_time))

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=60)
    assert deleted == 0
    assert task_dir.exists()


def test_ttl_task_deleted_at_exact_60_minutes_boundary(tmp_path: Path):
    """Verify task directory aged exactly 60 minutes (3600s) is deleted."""
    task_dir = tmp_path / "task-60m"
    task_dir.mkdir()
    target_time = time.time() - (60 * 60)
    os.utime(task_dir, (target_time, target_time))

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=60)
    assert deleted == 1
    assert not task_dir.exists()


def test_ttl_task_deleted_at_61_minutes(tmp_path: Path):
    """Verify task directory aged 61 minutes (3660s) is deleted."""
    task_dir = tmp_path / "task-61m"
    task_dir.mkdir()
    target_time = time.time() - (61 * 60)
    os.utime(task_dir, (target_time, target_time))

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=60)
    assert deleted == 1
    assert not task_dir.exists()


def test_ttl_zero_minutes_deletes_all_unprotected_folders(tmp_path: Path):
    """Verify ttl_minutes=0 cleans up all task directories regardless of age."""
    t1 = tmp_path / "fresh-task-1"
    t2 = tmp_path / "fresh-task-2"
    t1.mkdir()
    t2.mkdir()

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=0)
    assert deleted == 2
    assert not t1.exists()
    assert not t2.exists()


def test_ttl_negative_value_handling(tmp_path: Path):
    """Verify negative TTL values do not crash the cleanup routine."""
    task_dir = tmp_path / "task-neg"
    task_dir.mkdir()

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=-10)
    assert deleted == 1
    assert not task_dir.exists()


def test_ttl_active_tasks_never_deleted_even_if_expired(tmp_path: Path):
    """Verify active tasks (in active_task_ids) are protected even if older than 120 minutes."""
    active_id = "active-task-120m"
    expired_id = "idle-task-120m"

    active_dir = tmp_path / active_id
    expired_dir = tmp_path / expired_id
    active_dir.mkdir()
    expired_dir.mkdir()

    old_time = time.time() - (120 * 60)
    os.utime(active_dir, (old_time, old_time))
    os.utime(expired_dir, (old_time, old_time))

    deleted = cleaner.cleanup_old_downloads(
        downloads_dir=tmp_path,
        ttl_minutes=60,
        active_task_ids={active_id},
    )

    assert deleted == 1
    assert active_dir.exists()
    assert not expired_dir.exists()


def test_ttl_stray_regular_files_in_downloads_ignored(tmp_path: Path):
    """Verify stray non-directory files in downloads/ are preserved and not deleted."""
    stray_file = tmp_path / "readme.txt"
    stray_file.write_text("info")
    old_time = time.time() - (100 * 60)
    os.utime(stray_file, (old_time, old_time))

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=60)
    assert deleted == 0
    assert stray_file.exists()


def test_ttl_hidden_dot_directories_ignored(tmp_path: Path):
    """Verify hidden folders starting with dot (.gitkeep, .cache) are ignored."""
    dot_dir = tmp_path / ".hidden_cache"
    dot_dir.mkdir()
    old_time = time.time() - (200 * 60)
    os.utime(dot_dir, (old_time, old_time))

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=60)
    assert deleted == 0
    assert dot_dir.exists()


def test_ttl_nested_directories_and_files_fully_purged(tmp_path: Path):
    """Verify expired task folders with deep directory hierarchies are completely removed."""
    task_dir = tmp_path / "nested-task"
    sub_dir = task_dir / "sub1" / "sub2"
    sub_dir.mkdir(parents=True)
    media_file = sub_dir / "clip.mp4"
    media_file.write_bytes(b"content")

    old_time = time.time() - (70 * 60)
    os.utime(task_dir, (old_time, old_time))

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=60)
    assert deleted == 1
    assert not task_dir.exists()
    assert not media_file.exists()


def test_ttl_future_timestamps_clock_skew(tmp_path: Path):
    """Verify task folders with future timestamps (clock skew) are retained."""
    task_dir = tmp_path / "future-task"
    task_dir.mkdir()
    future_time = time.time() + 3600  # 1 hour in the future
    os.utime(task_dir, (future_time, future_time))

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=60)
    assert deleted == 0
    assert task_dir.exists()


def test_ttl_ancient_epoch_timestamps(tmp_path: Path):
    """Verify folders with very old timestamps (year 1990) are cleaned up."""
    task_dir = tmp_path / "epoch-task"
    task_dir.mkdir()
    ancient_time = 631152000.0  # Jan 1, 1990
    os.utime(task_dir, (ancient_time, ancient_time))

    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=60)
    assert deleted == 1
    assert not task_dir.exists()


def test_ttl_non_existent_downloads_dir():
    """Verify cleaner returns 0 gracefully when downloads directory does not exist."""
    fake_path = Path("/tmp/non_existent_downloads_dir_999999")
    deleted = cleaner.cleanup_old_downloads(fake_path, ttl_minutes=60)
    assert deleted == 0
