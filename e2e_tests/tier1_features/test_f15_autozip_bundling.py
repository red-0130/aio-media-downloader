"""Tier 1 Feature Coverage: F15 - Auto-ZIP Bundling."""

import zipfile
from pathlib import Path

import httpx
import pytest

from app.models.download import DownloadRequest
from app.services import router, zip_service


@pytest.mark.asyncio
async def test_multi_item_auto_zip_packaging(
    mock_bin_path: Path, isolated_env: dict[str, Path]
):
    """Verify downloading multiple items packages them automatically into a clean ZIP archive."""
    url = "https://www.instagram.com/p/334819201948/"
    req = DownloadRequest(
        url=url,
        selected_indices=[0, 1, 2],
        package_as_zip=True,
    )
    result = await router.download(task_id="task_zip_bundle", request=req)

    assert result.is_zip is True
    assert result.filename.endswith(".zip")
    assert result.download_url.endswith(".zip")

    zip_file = Path(result.file_path)
    assert zip_file.exists()
    assert zip_file.stat().st_size > 100


def test_zip_contains_all_downloaded_items(tmp_path: Path):
    """Verify ZIP archive contains all provided files."""
    files_to_zip = []
    for i in range(3):
        f = tmp_path / f"photo_{i}.jpg"
        f.write_bytes(f"test content {i}".encode())
        files_to_zip.append(f)

    out_zip = tmp_path / "bundle.zip"
    zip_service.create_zip_archive(files_to_zip, out_zip)

    assert out_zip.exists()
    with zipfile.ZipFile(out_zip, "r") as zf:
        names = zf.namelist()
        assert len(names) == 3
        for i in range(3):
            assert f"photo_{i}.jpg" in names


def test_individual_files_retained_alongside_zip(tmp_path: Path):
    """Verify source media files are preserved on disk alongside the created ZIP."""
    f1 = tmp_path / "item1.mp4"
    f2 = tmp_path / "item2.jpg"
    f1.write_bytes(b"data1")
    f2.write_bytes(b"data2")

    out_zip = tmp_path / "archive.zip"
    zip_service.create_zip_archive([f1, f2], out_zip)

    assert out_zip.exists()
    assert f1.exists(), "Original file item1.mp4 must not be deleted"
    assert f2.exists(), "Original file item2.jpg must not be deleted"


@pytest.mark.asyncio
async def test_single_item_download_package_as_zip_false(
    mock_bin_path: Path, isolated_env: dict[str, Path]
):
    """Verify single-item download does not force ZIP packaging when package_as_zip is False."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    req = DownloadRequest(url=url, format_id="best", package_as_zip=False)
    result = await router.download(task_id="task_no_zip", request=req)

    assert result.is_zip is False
    assert result.filename.endswith(".mp4")
    assert not result.filename.endswith(".zip")


def test_zip_handles_duplicate_filenames(tmp_path: Path):
    """Verify zip creation safely handles files with duplicate base names without colliding."""
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()

    f1 = dir1 / "image.jpg"
    f2 = dir2 / "image.jpg"
    f1.write_bytes(b"first image")
    f2.write_bytes(b"second image")

    out_zip = tmp_path / "collision_safe.zip"
    zip_service.create_zip_archive([f1, f2], out_zip)

    with zipfile.ZipFile(out_zip, "r") as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert "image.jpg" in names
        assert "image_1.jpg" in names


@pytest.mark.asyncio
async def test_download_api_multi_item_zip_flow(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Verify POST /api/download API produces ZIP download URL for multi-item requests."""
    payload = {
        "url": "https://www.instagram.com/p/334819201948/",
        "package_as_zip": True,
    }
    resp = await async_client.post("/api/download", json=payload)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    import asyncio
    from app.services import progress_manager

    for _ in range(50):
        task = progress_manager.get_task(task_id)
        if task and task.status == "completed":
            break
        await asyncio.sleep(0.05)

    completed = progress_manager.get_task(task_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.download_url.endswith(".zip")


@pytest.mark.asyncio
async def test_multi_item_download_package_as_zip_false_delivers_separate_files(
    async_client: httpx.AsyncClient,
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
):
    """Verify downloading multiple items with package_as_zip=False delivers separate files and no ZIP."""
    import asyncio
    from app.services import progress_manager

    payload = {
        "url": "https://www.instagram.com/p/334819201948/",
        "selected_indices": [0, 1, 2],
        "package_as_zip": False,
    }
    resp = await async_client.post("/api/download", json=payload)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    for _ in range(50):
        task = progress_manager.get_task(task_id)
        if task and task.status == "completed":
            break
        await asyncio.sleep(0.05)

    completed = progress_manager.get_task(task_id)
    assert completed is not None
    assert completed.status == "completed"
    assert not completed.download_url.endswith(".zip")
    assert not completed.filename.endswith(".zip")
    assert completed.files is not None
    assert len(completed.files) == 3

    # Verify each unbundled file is accessible via file serving API
    for file_item in completed.files:
        assert not file_item["filename"].endswith(".zip")
        file_resp = await async_client.get(file_item["download_url"])
        assert file_resp.status_code == 200

    # Verify no .zip was generated in task downloads directory
    task_dir = isolated_env["downloads_dir"] / task_id
    if task_dir.exists():
        assert len(list(task_dir.glob("*.zip"))) == 0

