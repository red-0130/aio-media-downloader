"""Background storage cleaner service for TTL expiration of temporary files."""

import asyncio
import logging
import shutil
import time
from pathlib import Path

from app.config import settings
from app.services import progress_manager

logger = logging.getLogger("cleaner")


def cleanup_old_downloads(
    downloads_dir: Path,
    ttl_minutes: int,
    active_task_ids: set[str] | None = None,
) -> int:
    """Scan downloads directory and remove folders older than TTL, skipping active tasks.
    Also evict expired in-memory tasks from progress_manager.

    Returns the number of deleted directories.
    """
    active_set = active_task_ids or set()
    now = time.time()
    ttl_seconds = ttl_minutes * 60
    deleted_count = 0

    if downloads_dir.exists() and downloads_dir.is_dir():
        for item in downloads_dir.iterdir():
            # Only process subdirectories (task directories)
            if not item.is_dir():
                continue

            # Skip gitkeep or special hidden folders
            if item.name.startswith("."):
                continue

            # Do not delete tasks that are currently active
            if item.name in active_set:
                continue

            try:
                # Check directory modification time
                stat = item.stat()
                age_seconds = now - stat.st_mtime

                if age_seconds >= ttl_seconds:
                    shutil.rmtree(item, ignore_errors=True)
                    deleted_count += 1
                    progress_manager.evict_task(item.name)
            except Exception:
                # Ignore errors for files currently being locked or cleaned
                continue

    progress_manager.evict_expired_tasks(ttl_minutes=ttl_minutes, active_task_ids=active_set)

    return deleted_count


async def run_periodic_cleaner(
    interval_seconds: float = 600,
    downloads_dir: Path | None = None,
    ttl_minutes: int | None = None,
) -> None:
    """Run periodic background cleanup loop removing expired task directories."""
    target_dir = downloads_dir if downloads_dir is not None else settings.DOWNLOADS_DIR
    target_ttl = ttl_minutes if ttl_minutes is not None else settings.STORAGE_TTL_MINUTES
    try:
        while True:
            try:
                active_ids = progress_manager.get_active_task_ids()
                deleted = cleanup_old_downloads(
                    downloads_dir=target_dir,
                    ttl_minutes=target_ttl,
                    active_task_ids=active_ids,
                )
                if deleted > 0:
                    logger.info("Cleaned %d expired download directories", deleted)
            except Exception as e:
                logger.warning("Error during periodic storage cleanup: %s", e)
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Periodic storage cleaner cancelled")
        raise
