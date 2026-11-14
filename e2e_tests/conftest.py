"""Pytest configuration and shared fixtures for offline hermetic E2E testing."""

import asyncio
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Generator

import httpx
import pytest
import pytest_asyncio
import uvicorn

# Ensure workspace root and backend root are in sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = WORKSPACE_ROOT / "backend"
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.services import proxy_manager
from e2e_tests.mocks.mock_proxy_server import MockSocks5Proxy

# Import FastAPI application or use test harness app
from e2e_tests.test_app import create_test_app

app = create_test_app()


E2E_DIR = Path(__file__).resolve().parent
MOCK_BIN_DIR = E2E_DIR / "mocks" / "bin"
CALL_LOG_PATH = E2E_DIR / "mocks" / "call_log.json"
FIXTURES_DIR = E2E_DIR / "fixtures"
SAMPLE_MEDIA_DIR = FIXTURES_DIR / "sample_media"


@pytest_asyncio.fixture(autouse=True)
async def cleanup_background_workers() -> AsyncGenerator[None, None]:
    """Ensure all background download workers are awaited or cancelled before teardown."""
    yield
    try:
        from e2e_tests.test_app import wait_for_all_workers
        await wait_for_all_workers(timeout=2.0)
    except Exception:
        pass


@pytest.fixture
def mock_bin_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """Prepend e2e_tests/mocks/bin to PATH and isolate mock call log."""
    old_path = os.environ.get("PATH", "")
    new_path = f"{MOCK_BIN_DIR}:{old_path}"
    monkeypatch.setenv("PATH", new_path)

    log_path = tmp_path / "mock_call_log.json"
    monkeypatch.setenv("MOCK_CALL_LOG_PATH", str(log_path))
    if log_path.exists():
        log_path.unlink(missing_ok=True)
    if CALL_LOG_PATH.exists():
        CALL_LOG_PATH.unlink(missing_ok=True)

    yield MOCK_BIN_DIR


@pytest.fixture
def isolated_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[dict[str, Path], None, None]:
    """Provide isolated temporary directories for cookies and downloads."""
    cookies_dir = tmp_path / "cookies"
    downloads_dir = tmp_path / "downloads"
    cookies_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "COOKIES_DIR", cookies_dir)
    monkeypatch.setattr(settings, "DOWNLOADS_DIR", downloads_dir)
    proxy_manager.reset_runtime_proxy()

    if "MOCK_CALL_LOG_PATH" not in os.environ:
        monkeypatch.setenv("MOCK_CALL_LOG_PATH", str(tmp_path / "mock_call_log.json"))

    yield {
        "cookies_dir": cookies_dir,
        "downloads_dir": downloads_dir,
        "tmp_path": tmp_path,
    }

    proxy_manager.reset_runtime_proxy()


@pytest_asyncio.fixture
async def socks5_proxy() -> AsyncGenerator[MockSocks5Proxy, None]:
    """Start an ephemeral asyncio SOCKS5 test proxy stub."""
    proxy = MockSocks5Proxy()
    port = await proxy.start()
    proxy.proxy_url = f"socks5://127.0.0.1:{port}"
    try:
        yield proxy
    finally:
        await proxy.stop()


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide httpx AsyncClient connected to FastAPI application via ASGITransport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


@pytest.fixture
def live_server() -> Generator[str, None, None]:
    """Run Uvicorn server in background thread on ephemeral port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error", loop="asyncio"
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    start_time = time.time()
    while not server.started:
        time.sleep(0.01)
        if time.time() - start_time > 5.0:
            raise RuntimeError("Uvicorn live server failed to start within 5s")

    server_url = f"http://127.0.0.1:{port}"
    try:
        yield server_url
    finally:
        server.should_exit = True
        thread.join(timeout=2.0)


@pytest.fixture
def call_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Helper to inspect and clear mock engine call logs."""
    if "MOCK_CALL_LOG_PATH" not in os.environ:
        monkeypatch.setenv("MOCK_CALL_LOG_PATH", str(tmp_path / "mock_call_log.json"))

    class CallLogHelper:
        @staticmethod
        def _get_path() -> Path:
            env_path = os.environ.get("MOCK_CALL_LOG_PATH")
            if env_path:
                return Path(env_path)
            return CALL_LOG_PATH

        @staticmethod
        def read() -> list[dict[str, Any]]:
            path = CallLogHelper._get_path()
            if not path.exists():
                return []
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return []

        @staticmethod
        def clear() -> None:
            path = CallLogHelper._get_path()
            if path.exists():
                path.unlink(missing_ok=True)
            if CALL_LOG_PATH.exists():
                CALL_LOG_PATH.unlink(missing_ok=True)

        @staticmethod
        def filter_by_engine(engine: str) -> list[dict[str, Any]]:
            return [e for e in CallLogHelper.read() if e.get("engine") == engine]

    return CallLogHelper


@pytest.fixture
def fixtures_paths():
    """Paths to all test fixtures."""
    return {
        "cookies_sample": FIXTURES_DIR / "cookies_sample.txt",
        "cookies_invalid": FIXTURES_DIR / "cookies_invalid.txt",
        "cookies_expired": FIXTURES_DIR / "cookies_expired.txt",
        "sample_mp4": SAMPLE_MEDIA_DIR / "sample.mp4",
        "sample_mp3": SAMPLE_MEDIA_DIR / "sample.mp3",
        "sample_jpg": SAMPLE_MEDIA_DIR / "sample.jpg",
    }
