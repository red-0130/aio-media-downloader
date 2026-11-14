"""Tier 1 Feature Coverage: F10 - SSRF & Traversal Security."""

from pathlib import Path

import httpx
import pytest

from app.services import security


@pytest.mark.asyncio
async def test_reject_file_scheme(async_client: httpx.AsyncClient):
    """Verify file:// URL schemes are rejected with 400 Bad Request."""
    resp = await async_client.post("/api/inspect", json={"url": "file:///etc/passwd"})
    assert resp.status_code == 400
    assert "SSRF" in resp.json()["detail"] or "disallowed" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reject_localhost_and_loopback(async_client: httpx.AsyncClient):
    """Verify localhost and loopback IP addresses are rejected with 400 Bad Request."""
    urls = [
        "http://localhost:8000/api",
        "http://127.0.0.1:8000/api/files",
        "http://0.0.0.0:8000/",
        "http://[::1]:8000/",
    ]
    for url in urls:
        resp = await async_client.post("/api/inspect", json={"url": url})
        assert resp.status_code == 400, f"Expected 400 for {url}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_reject_cloud_metadata_ip(async_client: httpx.AsyncClient):
    """Verify AWS/GCP/Azure link-local metadata service (169.254.169.254) is blocked."""
    resp = await async_client.post(
        "/api/inspect", json={"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert resp.status_code == 400
    assert "disallowed" in resp.json()["detail"].lower() or "ssrf" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reject_path_traversal_in_files_endpoint(async_client: httpx.AsyncClient):
    """Verify path traversal sequences in /api/files/{task_id}/{filename} are blocked."""
    traversal_paths = [
        "/api/files/task1/../../etc/passwd",
        "/api/files/..%2Ftask1/file.mp4",
        "/api/files/task1/subdir/../../etc/shadow",
    ]
    for path in traversal_paths:
        resp = await async_client.get(path)
        assert resp.status_code in (400, 404), f"Expected 400/404 for {path}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_reject_non_http_schemes(async_client: httpx.AsyncClient):
    """Verify non-HTTP schemes (gopher, ftp, ssh) are rejected."""
    schemes = [
        "gopher://evil.com/1",
        "ftp://mirror.example.com/file.mp4",
        "ssh://git@github.com",
    ]
    for url in schemes:
        resp = await async_client.post("/api/inspect", json={"url": url})
        assert resp.status_code == 400


def test_security_service_unit_validation(tmp_path: Path):
    """Unit test security functions: is_safe_url and validate_safe_path."""
    # Valid safe URLs
    assert security.is_safe_url("https://www.youtube.com/watch?v=123") is True
    assert security.is_safe_url("https://instagram.com/p/abc/") is True

    # Unsafe private IPs and metadata domains
    assert security.is_safe_url("http://10.0.0.1/admin") is False
    assert security.is_safe_url("http://192.168.1.1/router") is False
    assert security.is_safe_url("http://172.16.0.5/api") is False
    assert security.is_safe_url("http://metadata.google.internal") is False

    # Path traversal validation
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    child_file = base_dir / "safe.txt"
    child_file.write_text("ok")

    # Safe path succeeds
    safe_res = security.validate_safe_path(base_dir, "safe.txt")
    assert safe_res == child_file

    # Escaping path raises ValueError
    with pytest.raises(ValueError):
        security.validate_safe_path(base_dir, "../outside.txt")
