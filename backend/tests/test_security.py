"""Unit tests for security, SSRF validation, and path traversal guards."""

import pytest
from pathlib import Path

from app.services.security import is_safe_url, validate_url, validate_safe_path, is_valid_task_id, validate_task_id


def test_safe_urls_accepted():
    valid_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://instagram.com/p/C7XYZ89_abc/",
        "https://twitter.com/user/status/1234567890",
        "https://x.com/user/status/1234567890",
        "https://www.tiktok.com/@user/video/1234567890",
        "http://example.com/media/sample.mp4",
    ]
    for url in valid_urls:
        assert is_safe_url(url) is True
        assert validate_url(url) == url


def test_unsafe_schemes_blocked():
    unsafe_schemes = [
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "ftp://example.com/file.mp4",
        "gopher://example.com/",
        "data:text/html,<script>alert(1)</script>",
        "javascript:alert(1)",
    ]
    for url in unsafe_schemes:
        assert is_safe_url(url) is False
        with pytest.raises(ValueError):
            validate_url(url)


def test_ssrf_internal_ips_and_localhost_blocked():
    blocked_urls = [
        "http://localhost:8000/api",
        "http://127.0.0.1:8000/secret",
        "http://0.0.0.0:8000/",
        "http://[::1]:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/router",
        "http://10.0.0.5:8080/",
        "http://172.16.0.1/",
        "http://sub.localhost/api",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://instance-data/latest/meta-data/",
    ]
    for url in blocked_urls:
        assert is_safe_url(url) is False
        with pytest.raises(ValueError):
            validate_url(url)


def test_ssrf_alternate_ipv4_representations():
    alternate_ips = [
        "http://2130706433/data",           # 127.0.0.1 as decimal integer
        "http://0177.0.0.1/secret",         # 127.0.0.1 as dotted octal
        "http://0x7f000001/admin",          # 127.0.0.1 as hex integer
        "http://127.1/api",                 # 127.0.0.1 shortened (2-part)
        "http://0/status",                  # 0.0.0.0 shortened
        "http://2852039166/latest",         # 169.254.169.254 as decimal integer (AWS IMDS)
        "http://0xA9FEA9FE/latest",         # 169.254.169.254 as hex integer (AWS IMDS)
        "http://017700000001/data",         # 127.0.0.1 single octal
        "http://0xa9.0xfe.0xa9.0xfe/meta",  # 169.254.169.254 dotted hex
        "http://10.1/internal",             # 10.0.0.1 shortened private
        "http://172.16.1/internal",         # 172.16.0.1 shortened private
        "http://192.168.1/router",          # 192.168.0.1 shortened private
    ]
    for url in alternate_ips:
        assert is_safe_url(url) is False, f"Expected {url} to be blocked as unsafe"
        with pytest.raises(ValueError):
            validate_url(url)


def test_ssrf_dns_rebinding_and_wildcard_domains(monkeypatch):
    from unittest.mock import patch

    # Mock DNS resolution returning loopback address for arbitrary domain
    with patch("socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]
        assert is_safe_url("http://rebind.malicious.com/api") is False
        with pytest.raises(ValueError):
            validate_url("http://rebind.malicious.com/api")

    # Mock DNS resolution returning AWS IMDS address
    with patch("socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(2, 1, 6, "", ("169.254.169.254", 80))]
        assert is_safe_url("http://cloud-metadata.attacker.org/latest") is False
        with pytest.raises(ValueError):
            validate_url("http://cloud-metadata.attacker.org/latest")

    # Live or standard resolution for nip.io wildcard if available
    assert is_safe_url("http://127.0.0.1.nip.io/secret") is False


def test_invalid_and_empty_urls_rejected():
    invalid_inputs = ["", "   ", None, "not_a_url", "http://", "://broken"]
    for url in invalid_inputs:
        assert is_safe_url(url) is False
        with pytest.raises(ValueError):
            validate_url(url)


def test_safe_path_resolution(tmp_path):
    base_dir = tmp_path / "downloads"
    base_dir.mkdir()
    child_file = base_dir / "task-1" / "video.mp4"
    child_file.parent.mkdir()
    child_file.touch()

    # Valid relative subpath
    resolved = validate_safe_path(base_dir, Path("task-1/video.mp4"))
    assert resolved == child_file.resolve()

    # Valid absolute path inside base_dir
    resolved_abs = validate_safe_path(base_dir, child_file)
    assert resolved_abs == child_file.resolve()


def test_path_traversal_detection(tmp_path):
    base_dir = tmp_path / "downloads"
    base_dir.mkdir()

    traversal_paths = [
        "../secret.txt",
        "task/../../etc/passwd",
        "../../../../../../etc/shadow",
        "/etc/passwd",
    ]

    for p in traversal_paths:
        with pytest.raises(ValueError, match="Path traversal"):
            validate_safe_path(base_dir, p)


def test_task_id_validation_valid():
    valid_task_ids = [
        "task-1",
        "task_123",
        "task-abc-def",
        "task-7832482abc91",
        "a",
        "A-B_c123",
    ]
    for tid in valid_task_ids:
        assert is_valid_task_id(tid) is True
        assert validate_task_id(tid) == tid


def test_task_id_validation_invalid():
    invalid_task_ids = [
        ".",
        "..",
        "./",
        "../",
        "task/1",
        "task\\1",
        "task 1",
        "task@123",
        "task#1",
        "task?query=1",
        "",
        "   ",
        None,
        123,
        "a" * 200,  # exceeds 128 chars
    ]
    for tid in invalid_task_ids:
        assert is_valid_task_id(tid) is False
        with pytest.raises(ValueError):
            validate_task_id(tid)
