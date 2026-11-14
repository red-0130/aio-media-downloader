"""Tier 1 Feature Coverage: F06 - Download API (POST /api/download)."""

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services import progress_manager


@pytest.mark.asyncio
async def test_valid_download_queues_task_id(
    async_client: httpx.AsyncClient, mock_bin_path: Path, isolated_env: dict[str, Path]
):
    """Verify POST /api/download queues task and returns task_id with queued status."""
    payload = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    resp = await async_client.post("/api/download", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "queued"
    assert data["task_id"].startswith("task-") or len(data["task_id"]) > 5

    # Await background task completion before test teardown
    task_id = data["task_id"]
    for _ in range(50):
        task = progress_manager.get_task(task_id)
        if task and task.status in ("completed", "error"):
            break
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_download_with_format_id_selection(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Verify POST /api/download passes format_id selection to extraction engine."""
    call_log.clear()
    payload = {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "format_id": "22",
    }
    resp = await async_client.post("/api/download", json=payload)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    # Allow background task to execute
    for _ in range(50):
        task = progress_manager.get_task(task_id)
        if task and task.status in ("completed", "error"):
            break
        await asyncio.sleep(0.05)

    records = call_log.filter_by_engine("yt-dlp")
    assert any(
        r.get("format_id") in ("22", "22[acodec!=none]/22+bestaudio/22/best")
        or "22" in str(r.get("format_id"))
        for r in records
    )


@pytest.mark.asyncio
async def test_download_with_extract_audio_flag(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Verify POST /api/download with extract_audio=True passes audio extraction flags."""
    call_log.clear()
    payload = {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "extract_audio": True,
        "audio_format": "mp3",
    }
    resp = await async_client.post("/api/download", json=payload)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    for _ in range(50):
        task = progress_manager.get_task(task_id)
        if task and task.status in ("completed", "error"):
            break
        await asyncio.sleep(0.05)

    records = call_log.filter_by_engine("yt-dlp")
    assert any(r.get("extract_audio") is True for r in records)
    assert any(r.get("audio_format") == "mp3" for r in records)


@pytest.mark.asyncio
async def test_download_with_selected_indices(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    call_log: Any,
):
    """Verify POST /api/download with selected_indices passes range selection."""
    call_log.clear()
    payload = {
        "url": "https://www.instagram.com/p/334819201948/",
        "selected_indices": [0, 2],
    }
    resp = await async_client.post("/api/download", json=payload)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    for _ in range(50):
        task = progress_manager.get_task(task_id)
        if task and task.status in ("completed", "error"):
            break
        await asyncio.sleep(0.05)

    records = call_log.filter_by_engine("gallery-dl")
    assert any(r.get("range") == "1,3" for r in records)


@pytest.mark.asyncio
async def test_download_with_package_as_zip(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Verify POST /api/download with package_as_zip packages carousel into ZIP archive."""
    payload = {
        "url": "https://www.instagram.com/p/334819201948/",
        "package_as_zip": True,
    }
    resp = await async_client.post("/api/download", json=payload)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    for _ in range(50):
        task = progress_manager.get_task(task_id)
        if task and task.status == "completed":
            break
        await asyncio.sleep(0.05)

    completed_task = progress_manager.get_task(task_id)
    assert completed_task is not None
    assert completed_task.status == "completed"
    assert completed_task.filename is not None
    assert completed_task.filename.endswith(".zip")
    assert completed_task.download_url is not None


@pytest.mark.asyncio
async def test_download_missing_url_returns_422(async_client: httpx.AsyncClient):
    """Verify POST /api/download without URL returns 422 validation error."""
    resp = await async_client.post("/api/download", json={})
    assert resp.status_code == 422
