"""Pytest test configuration and shared fixtures."""

import asyncio
import json
from pathlib import Path
from typing import Any
import pytest

from app.config import settings
from app.services import proxy_manager

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def reset_proxy():
    """Ensure runtime proxy is reset before and after every test."""
    proxy_manager.reset_runtime_proxy()
    yield
    proxy_manager.reset_runtime_proxy()


@pytest.fixture
def temp_environment(tmp_path, monkeypatch):
    """Provide isolated cookies and downloads directories for test."""
    cookies_dir = tmp_path / "cookies"
    downloads_dir = tmp_path / "downloads"
    cookies_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "COOKIES_DIR", cookies_dir)
    monkeypatch.setattr(settings, "DOWNLOADS_DIR", downloads_dir)

    return {
        "cookies_dir": cookies_dir,
        "downloads_dir": downloads_dir,
    }


def load_fixture_json(filename: str) -> Any:
    """Load JSON content from tests/fixtures directory."""
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class MockStreamReader:
    """Mock asyncio StreamReader supporting readline()."""

    def __init__(self, lines: list[bytes]):
        self.lines = list(lines)
        self.idx = 0

    async def readline(self) -> bytes:
        if self.idx < len(self.lines):
            line = self.lines[self.idx]
            self.idx += 1
            return line
        return b""


class MockSubprocess:
    """Mock asyncio subprocess process."""

    def __init__(
        self,
        stdout_bytes: bytes = b"",
        stderr_bytes: bytes = b"",
        returncode: int = 0,
        stdout_lines: list[bytes] | None = None,
        stderr_lines: list[bytes] | None = None,
    ):
        self._stdout_bytes = stdout_bytes
        self._stderr_bytes = stderr_bytes
        self.returncode = returncode

        s_lines = stdout_lines if stdout_lines is not None else [
            line + b"\n" for line in stdout_bytes.splitlines() if line
        ]
        e_lines = stderr_lines if stderr_lines is not None else [
            line + b"\n" for line in stderr_bytes.splitlines() if line
        ]
        self.stdout = MockStreamReader(s_lines)
        self.stderr = MockStreamReader(e_lines)

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout_bytes, self._stderr_bytes

    async def wait(self) -> int:
        return self.returncode
