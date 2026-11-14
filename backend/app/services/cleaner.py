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

    Returns the number of deleted directories.
    """
    if not downloads_dir.exists() or not downloads_dir.is_dir():
        return 0

    active_set = active_task_ids or set()
    now = time.time()
    ttl_seconds = ttl_minutes * 60
    deleted_count = 0

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

    return deleted_count


async def run_periodic_cleaner(interval_seconds: int = 600) -> None:
    """Run periodic background cleanup loop removing expired task directories."""
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                active_ids = progress_manager.get_active_task_ids()
                deleted = cleanup_old_downloads(
                    downloads_dir=settings.DOWNLOADS_DIR,
                    ttl_minutes=settings.STORAGE_TTL_MINUTES,
                    active_task_ids=active_ids,
                )
                if deleted > 0:
                    logger.info("Cleaned %d expired download directories", deleted)
            except Exception as e:
                logger.warning("Error during periodic storage cleanup: %s", e)
    except asyncio.CancelledError:
        logger.info("Periodic storage cleaner cancelled")
