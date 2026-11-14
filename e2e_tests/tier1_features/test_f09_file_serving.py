"""Tier 1 Feature Coverage: F09 - File Serving & Content-Disposition (GET /api/files/{task_id}/{filename})."""

import shutil
import zipfile
from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_serve_media_attachment(
    async_client: httpx.AsyncClient,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
):
    """Verify serving media file returns 200 with Content-Disposition attachment header."""
    task_id = "task_f09_media"
    task_dir = isolated_env["downloads_dir"] / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    dest_file = task_dir / "rick_astley.mp4"
    shutil.copyfile(fixtures_paths["sample_mp4"], dest_file)

    resp = await async_client.get(f"/api/files/{task_id}/rick_astley.mp4")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "").lower()
    assert 'filename="rick_astley.mp4"' in resp.headers.get("content-disposition", "")
    assert len(resp.content) > 1000


@pytest.mark.asyncio
async def test_serve_zip_attachment(
    async_client: httpx.AsyncClient, isolated_env: dict[str, Path]
):
    """Verify serving bundled ZIP archive returns application/zip Content-Type."""
    task_id = "task_f09_zip"
    task_dir = isolated_env["downloads_dir"] / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    zip_path = task_dir / "instagram_bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test1.txt", "hello")
        zf.writestr("test2.txt", "world")

    resp = await async_client.get(f"/api/files/{task_id}/instagram_bundle.zip")
    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "application/zip"
    assert "attachment" in resp.headers.get("content-disposition", "").lower()


@pytest.mark.asyncio
async def test_content_type_headers_for_media_formats(
    async_client: httpx.AsyncClient,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
):
    """Verify distinct Content-Type headers for MP4, MP3, and JPG."""
    task_id = "task_f09_types"
    task_dir = isolated_env["downloads_dir"] / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(fixtures_paths["sample_mp4"], task_dir / "video.mp4")
    shutil.copyfile(fixtures_paths["sample_mp3"], task_dir / "audio.mp3")
    shutil.copyfile(fixtures_paths["sample_jpg"], task_dir / "image.jpg")

    r_mp4 = await async_client.get(f"/api/files/{task_id}/video.mp4")
    assert r_mp4.status_code == 200
    assert r_mp4.headers.get("content-type") == "video/mp4"

    r_mp3 = await async_client.get(f"/api/files/{task_id}/audio.mp3")
    assert r_mp3.status_code == 200
    assert r_mp3.headers.get("content-type") == "audio/mpeg"

    r_jpg = await async_client.get(f"/api/files/{task_id}/image.jpg")
    assert r_jpg.status_code == 200
    assert r_jpg.headers.get("content-type") == "image/jpeg"


@pytest.mark.asyncio
async def test_non_existent_file_returns_404(
    async_client: httpx.AsyncClient, isolated_env: dict[str, Path]
):
    """Verify requesting non-existent file in a task directory returns 404."""
    resp = await async_client.get("/api/files/task_empty/missing.mp4")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_isolated_task_directories(
    async_client: httpx.AsyncClient,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
):
    """Verify task directories are isolated: task B cannot serve files from task A."""
    dir_a = isolated_env["downloads_dir"] / "task_A"
    dir_a.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixtures_paths["sample_mp4"], dir_a / "secret.mp4")

    # Request file from task_B where it does not exist
    resp = await async_client.get("/api/files/task_B/secret.mp4")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_file_serving_path_traversal_rejection(
    async_client: httpx.AsyncClient, isolated_env: dict[str, Path]
):
    """Verify directory traversal in file serving is blocked with 400 Bad Request."""
    resp = await async_client.get("/api/files/task_1/../../etc/passwd")
    assert resp.status_code in (400, 404)
