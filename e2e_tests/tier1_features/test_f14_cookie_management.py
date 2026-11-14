"""Tier 1 Feature Coverage: F14 - Cookie Management & Settings."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services import cookie_manager, gallerydl_service


@pytest.mark.asyncio
async def test_get_cookie_status_api(
    async_client: httpx.AsyncClient, isolated_env: dict[str, Path]
):
    """Verify GET /api/settings/cookies returns status for all supported platforms."""
    resp = await async_client.get("/api/settings/cookies")
    assert resp.status_code == 200
    data = resp.json()

    for platform in ("instagram", "twitter", "youtube"):
        assert platform in data
        assert "exists" in data[platform]
        assert "valid" in data[platform]
        assert "cookie_count" in data[platform]


@pytest.mark.asyncio
async def test_post_pasted_netscape_cookies(
    async_client: httpx.AsyncClient,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
):
    """Verify pasting valid Netscape cookies saves to cookies/<platform>.txt."""
    valid_content = fixtures_paths["cookies_sample"].read_text(encoding="utf-8")
    payload = {"platform": "instagram", "content": valid_content}

    resp = await async_client.post("/api/settings/cookies", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "saved"
    assert data["platform"] == "instagram"

    # Verify file was written to disk
    cookie_path = isolated_env["cookies_dir"] / "instagram.txt"
    assert cookie_path.exists()
    status = cookie_manager.check_cookie_status("instagram")
    assert status.exists is True
    assert status.valid is True
    assert status.cookie_count >= 6


@pytest.mark.asyncio
async def test_upload_cookie_file_api(
    async_client: httpx.AsyncClient,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
):
    """Verify uploading a cookie file via multipart POST saves properly."""
    cookie_bytes = fixtures_paths["cookies_sample"].read_bytes()
    files = {"file": ("cookies.txt", cookie_bytes, "text/plain")}
    data = {"platform": "twitter"}

    resp = await async_client.post(
        "/api/settings/cookies/upload", data=data, files=files
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"

    cookie_path = isolated_env["cookies_dir"] / "twitter.txt"
    assert cookie_path.exists()
    status = cookie_manager.check_cookie_status("twitter")
    assert status.exists is True
    assert status.valid is True


@pytest.mark.asyncio
async def test_delete_cookies_api(
    async_client: httpx.AsyncClient,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
):
    """Verify DELETE /api/settings/cookies/{platform} removes the cookie file."""
    # First save a cookie
    valid_content = fixtures_paths["cookies_sample"].read_text(encoding="utf-8")
    cookie_manager.save_cookies("youtube", valid_content)
    assert (isolated_env["cookies_dir"] / "youtube.txt").exists()

    # Now delete via API
    resp = await async_client.delete("/api/settings/cookies/youtube")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert not (isolated_env["cookies_dir"] / "youtube.txt").exists()


@pytest.mark.asyncio
async def test_cookies_flag_injected_into_engine_cli(
    mock_bin_path: Path,
    isolated_env: dict[str, Path],
    fixtures_paths: dict[str, Path],
    call_log: Any,
):
    """Verify saved cookie file is automatically passed to extraction engine via --cookies."""
    call_log.clear()
    cookie_file = fixtures_paths["cookies_sample"]

    await gallerydl_service.inspect_url(
        "https://www.instagram.com/stories/influencer_daily/94821038/",
        cookies_path=cookie_file,
    )

    records = call_log.filter_by_engine("gallery-dl")
    assert len(records) >= 1
    assert records[0]["cookies"] == str(cookie_file)


@pytest.mark.asyncio
async def test_invalid_cookie_content_rejected(
    async_client: httpx.AsyncClient, isolated_env: dict[str, Path]
):
    """Verify pasting invalid/non-Netscape content is rejected with 400 Bad Request."""
    invalid_content = "This is definitely not a Netscape cookie file content\nSome Random text"
    payload = {"platform": "instagram", "content": invalid_content}

    resp = await async_client.post("/api/settings/cookies", json=payload)
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"] or "format" in resp.json()["detail"]
