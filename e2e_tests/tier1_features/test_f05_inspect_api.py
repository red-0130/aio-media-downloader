"""Tier 1 Feature Coverage: F05 - Two-Step Inspect API (POST /api/inspect)."""

from pathlib import Path
import httpx
import pytest


@pytest.mark.asyncio
async def test_valid_inspect_returns_200_and_structured_response(
    async_client: httpx.AsyncClient, mock_bin_path: Path
):
    """Verify POST /api/inspect returns 200 and structured InspectResponse."""
    payload = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    resp = await async_client.post("/api/inspect", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "dQw4w9WgXcQ"
    assert data["platform"] == "youtube"
    assert data["media_type"] == "video"
    assert "Rick Astley" in data["title"]
    assert len(data["formats"]) >= 3


@pytest.mark.asyncio
async def test_inspect_missing_url_returns_422(async_client: httpx.AsyncClient):
    """Verify POST /api/inspect with missing URL field returns 422 Unprocessable Entity."""
    resp = await async_client.post("/api/inspect", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_inspect_invalid_url_returns_400(async_client: httpx.AsyncClient):
    """Verify POST /api/inspect with non-URL or disallowed URL returns 400."""
    resp = await async_client.post("/api/inspect", json={"url": "not-a-valid-url"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_inspect_format_options_schema(
    async_client: httpx.AsyncClient, mock_bin_path: Path
):
    """Verify format options in inspect response match expected schema."""
    resp = await async_client.post(
        "/api/inspect", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    )
    assert resp.status_code == 200
    formats = resp.json()["formats"]
    assert len(formats) > 0

    for fmt in formats:
        assert "format_id" in fmt and isinstance(fmt["format_id"], str)
        assert "label" in fmt and isinstance(fmt["label"], str)
        assert "ext" in fmt and isinstance(fmt["ext"], str)


@pytest.mark.asyncio
async def test_inspect_carousel_items_array_schema(
    async_client: httpx.AsyncClient, mock_bin_path: Path
):
    """Verify carousel items array schema in inspect response."""
    resp = await async_client.post(
        "/api/inspect", json={"url": "https://www.instagram.com/p/334819201948/"}
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["media_type"] == "carousel"
    items = data["items"]
    assert len(items) == 3

    for idx, item in enumerate(items):
        assert item["index"] == idx
        assert item["type"] in ("image", "video")
        assert "url" in item
        assert "thumbnail" in item


@pytest.mark.asyncio
async def test_inspect_auth_required_returns_401(
    async_client: httpx.AsyncClient, mock_bin_path: Path
):
    """Verify POST /api/inspect returns 401 when platform requires login/cookies."""
    resp = await async_client.post(
        "/api/inspect", json={"url": "https://www.youtube.com/watch?v=auth_error_test"}
    )
    assert resp.status_code == 401
    assert "authentication" in resp.json()["detail"].lower()
